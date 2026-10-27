"""The page view, text in and text out: no browser, no model.

Every snapshot here is a real one from the 20 Oct lab (Playwright's ai snapshot, signed out),
and every task is the one the lab wrote for that page before measuring anything. The two
huge pages are gzipped: together they are 1.1 MB of text, and they are here because they are
huge (DESIGN-v2 §8, Phase 2: the budget must hold on them).
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path

import pytest

from dejo import view

FIXTURES = Path(__file__).parent / "fixtures"

# page -> (url, title, the lab's task for it)
PAGES = {
    "books_travel": (
        "https://books.toscrape.com/catalogue/category/books/travel_2/index.html",
        "Travel | Books to Scrape - Sandbox",
        "open the first book listed and tell me its price",
    ),
    "crates_search": (
        "https://crates.io/search?q=yaml",
        "Search Results for 'yaml' - crates.io: Rust Package Registry",
        "open the first crate in the search results, or go to the next page",
    ),
    "internet_iframe": (
        "https://the-internet.herokuapp.com/iframe",
        "The Internet",
        "type a sentence into the rich text editor",
    ),
    "quotes": (
        "https://quotes.toscrape.com/",
        "Quotes to Scrape",
        "open the About page of the first quote's author and tell me the date they were born;"
        " or go to the next page of quotes",
    ),
    "data_gov": (
        "https://catalog.data.gov/",
        "Catalog - Data.gov",
        "search the dataset catalog for air quality and go to the next page of results",
    ),
    "pkg_go_http": (
        "https://pkg.go.dev/net/http",
        "http package - net/http - Go Packages",
        "go to the documentation of the function Get in the index",
    ),
    "iana_rootdb": (
        "https://www.iana.org/domains/root/db",
        "Top-Level Domains",
        "open the record for the .museum top-level domain",
    ),
}
GOLDEN = ["books_travel", "crates_search", "internet_iframe", "quotes"]
HUGE = ["pkg_go_http", "iana_rootdb"]

# A ref as it starts an element: `e16`, `f1e3`, or `e147:` before its text.
REF = re.compile(r"^(?:f\d+)?e\d+:?$")


def snapshot(page: str) -> str:
    plain = FIXTURES / "aria" / f"{page}.txt"
    if plain.exists():
        return plain.read_text(encoding="utf-8")
    with gzip.open(FIXTURES / "aria" / f"{page}.txt.gz", "rt", encoding="utf-8") as handle:
        return handle.read()


def look(page: str, **options) -> view.View:
    url, title, task = PAGES[page]
    options.setdefault("focus", task)
    return view.render(snapshot(page), url=url, title=title, **options)


def element_lines(text: str) -> list[str]:
    """Everything but the header, the best block, the cut note and the pager line."""
    return [
        line
        for line in text.split("\n")[1:]
        if not line.startswith(("best for ", "pager: "))
        and not re.match(r"^\+\d+ more lines not shown: ", line)
    ]


def printed_refs(text: str) -> set[str]:
    """Every ref that starts an element anywhere in the text: on a line, inside a fold or a
    row, in the best block, on the pager line."""
    found: set[str] = set()
    for line in text.split("\n")[1:]:
        body = re.sub(r"^(best for \"[^\"]*\": |pager: | r\d+ |g\d+ \d+ \w+: )", "", line)
        for piece in body.split(" · "):
            words = piece.split()
            if words and REF.match(words[0]):
                found.add(words[0].rstrip(":"))
    return found


# ---------------------------------------------------------------------- golden text


@pytest.mark.parametrize("page", GOLDEN)
def test_the_view_reads_exactly_as_agreed(page: str) -> None:
    """The whole text, byte for byte. A change here changes what every agent reads, so it
    must be a deliberate one: rewrite the file from `look(page).text` and read the diff."""
    golden = (FIXTURES / "view" / f"{page}.txt").read_text(encoding="utf-8")
    assert look(page).text + "\n" == golden


def test_the_quotes_page_matches_the_design() -> None:
    """DESIGN-v2 §3.2, hand-rendered from the same snapshot before any code existed."""
    text = look("quotes").text
    assert text.startswith('page "Quotes to Scrape" https://quotes.toscrape.com/\n')
    assert "g1 10 rows, 3 shown:\n r1 e13: “The world as we have created it" in text
    assert ' · e14: by Albert Einstein · e15 link "(about)" · ' in text
    assert "\n +7 more rows: look g1\n" in text
    assert (
        '\ng2 10 links: e98 "love" · e100 "inspirational" · e102 "life" · +7 more: look g2\n'
        in text
    )
    assert '\ne94 link "Next"\n' in text


# ----------------------------------------------------------------------- the budget


@pytest.mark.parametrize("page", HUGE)
def test_the_budget_holds_on_a_huge_page(page: str) -> None:
    """IANA's root zone list is 166k tokens as Playwright prints it; pkg.go.dev's net/http,
    120k. The element lines stay inside the budget, and the cut says so."""
    text = look(page).text
    used = sum(len(line) + 1 for line in element_lines(text))
    assert used <= view.LINE_BUDGET
    assert re.search(
        r"^\+\d+ more lines not shown: look from (f\d+)?e\d+, or look <words>$", text, re.M
    )


@pytest.mark.parametrize("page", HUGE)
def test_everything_around_the_lines_stays_small(page: str) -> None:
    """Header, best block and pager come on top of the budget, and must stay under 1,500
    chars (DESIGN-v2 §3.3)."""
    text = look(page).text
    extras = len(text) - sum(len(line) + 1 for line in element_lines(text))
    assert extras < 1_500


def test_look_all_has_no_budget_but_a_cap() -> None:
    text = look("iana_rootdb", everything=True).text
    assert len(element_lines(text)) > len(element_lines(look("iana_rootdb").text))
    assert len(text) < 30_000


def test_a_tiny_budget_still_moves_forward() -> None:
    """A line longer than the budget is shown anyway, or `look from` would loop forever."""
    shown = look("quotes", budget=10)
    assert len(element_lines(shown.text)) == 1


# --------------------------------------------------------------------------- folds


@pytest.mark.parametrize("page", list(PAGES))
def test_a_printed_fold_always_shows_its_first_row(page: str) -> None:
    """Row 1 is what most list tasks need: "the first book", "the top story"."""
    shown = look(page)
    for group in shown.groups.values():
        if re.search(rf"^{group.id} ", shown.text, re.M):
            assert all(item.ref in shown.targets for item in group.rows[0])


def test_every_fold_is_printed_when_the_page_fits() -> None:
    shown = look("books_travel")
    assert set(shown.groups) == {"g1", "g2"}
    assert all(f"\n{group} " in shown.text for group in shown.groups)


def test_look_at_a_fold_lists_every_row() -> None:
    text = look("books_travel", group="g2").text
    assert "g2 11 rows:" in text
    assert ' r11 e335 link "1,000 Places to See ..." · e337: £26.08 · ' in text


def test_a_fold_keeps_which_button_belongs_to_which_book() -> None:
    """The lab's warning about compact views (lab-results.md §7): one line per row keeps
    the price and the button next to the right title."""
    text = look("books_travel").text
    assert (
        ' r1 e145 link "It\'s Only the Himalayas" · e147: £45.17 · e148: In stock'
        ' · e151 button "Add to basket"\n'
    ) in text


# --------------------------------------------------------------------------- paging


def test_look_from_picks_up_where_the_cut_left_off() -> None:
    first = look("books_travel", budget=500, focus="")
    note = re.search(r"look from ((f\d+)?e\d+)", first.text)
    assert note is not None
    after = look("books_travel", budget=500, focus="", start=note.group(1))
    refs = [word for line in element_lines(after.text) for word in line.split() if REF.match(word)]
    assert refs[0].rstrip(":") == note.group(1)
    assert not set(first.targets) & set(after.targets), "no line is shown twice"


def test_look_from_inside_a_fold_opens_it_at_that_row() -> None:
    text = look("books_travel", start="e202").text
    assert "g2 11 rows, from r4:\n r4 e202 link" in text


def test_an_unknown_ref_says_what_to_do() -> None:
    with pytest.raises(view.ViewError, match="look again to get fresh ones"):
        look("books_travel", start="e99999")


def test_an_unknown_group_names_the_real_ones() -> None:
    with pytest.raises(view.ViewError, match="the groups here are g1, g2"):
        look("books_travel", group="g9")


def test_only_one_way_of_paging_at_a_time() -> None:
    with pytest.raises(view.ViewError):
        look("books_travel", start="e30", everything=True)


# ------------------------------------------------------------------------- the pager


def test_the_pager_lists_a_load_more_button_past_the_cut() -> None:
    """data.gov replaced "next page" with "Show more results", which no task word matches
    (the lab's one control miss after focus). Under the default budget the button already
    has a line; under a tighter one it falls past the cut and the pager line names it."""
    assert '\ne595 button "Show more results"\n' in look("data_gov").text
    tight = look("data_gov", budget=2_000, focus="")
    assert 'pager: e595 button "Show more results"' in tight.text
    assert tight.targets["e595"].aria_ref == "f3e595"


@pytest.mark.parametrize(
    ("name", "pager"),
    [
        ("Next →", True),
        ("next page", True),
        ("Show more results", True),
        ("Load more", True),
        ("Older posts", True),
        ("»", True),
        ("More", True),
        (".next", False),
        ("…", False),
        ("Read more about pricing", False),
    ],
)
def test_what_counts_as_a_pager(name: str, pager: bool) -> None:
    raw = "- generic [ref=e1]:\n" + "".join(
        f"  - paragraph [ref=e{n}]: filler line {n}\n" for n in range(2, 40)
    )
    raw += f'  - link "{name}" [ref=e90] [cursor=pointer]:\n    - /url: /p/2\n'
    text = view.render(raw, url="https://x.test/", title="t", budget=100).text
    assert ("pager: e90 link" in text) is pager


# --------------------------------------------------------------- the lab's targets

# Playwright's refs for the elements the lab's tasks need, fixed on the live pages before any
# view was measured (lab/results.json `matching_refs`). A value counts when the element or a
# tight wrapper around it is printed, as in the lab.
LAB_TARGETS = {
    "books_travel": {"first book link": {"f1e145"}, "its price": {"f1e147", "f1e146"}},
    "quotes": {
        "first (about)": {"f2e15"},
        "Next": {"f2e94"},
        "first quote text": {"f2e13"},
    },
    "crates_search": {"first crate": {"f60e41"}, "next page": {"f60e359"}},
    "data_gov": {"search box": {"f3e44"}, "load more": {"f3e595"}},
    "pkg_go_http": {"func Get in the index": {"f61e127"}},
    "iana_rootdb": {".museum": {"f33e8848"}},
    # Every compact format in the lab missed this one: the editor has no control role. It is
    # printed here as a named text line, so the agent at least has its ref.
    "internet_iframe": {"editor body": {"f52e1"}},
}


@pytest.mark.parametrize("page", list(LAB_TARGETS))
def test_the_labs_targets_are_printed_with_the_labs_task(page: str) -> None:
    printed = {target.aria_ref for target in look(page).targets.values()}
    missing = [name for name, refs in LAB_TARGETS[page].items() if not refs & printed]
    assert not missing


# ------------------------------------------------------------------ refs and lookup


@pytest.mark.parametrize("page", list(PAGES))
def test_every_printed_ref_resolves(page: str) -> None:
    """Both ways: every ref in the text is in the lookup table, and nothing in the table is
    missing from the text."""
    shown = look(page)
    assert printed_refs(shown.text) == set(shown.targets)
    for ref, target in shown.targets.items():
        assert target.node.ref == ref
        assert target.aria_ref


def test_an_element_in_an_iframe_knows_its_frame() -> None:
    shown = look("internet_iframe", frames={"f51e77": "#mce_0_ifr"})
    assert "\ne77 iframe (f1)\n" in shown.text
    assert shown.targets["f1e1"].frame == "#mce_0_ifr"
    assert shown.targets["f1e1"].aria_ref == "f52e1"
    assert shown.targets["e94"].frame is None


# -------------------------------------------------------------- what is never shown


@pytest.mark.parametrize("page", ["books_travel", "crates_search", "quotes"])
def test_no_link_address_is_printed(page: str) -> None:
    """Addresses were half of a control list in the lab. Dejo keeps them for locators."""
    from dejo.snapshot import nodes

    text = look(page).text.split("\n", 1)[1]  # the header names the page's own address
    hrefs = {node.href for node in nodes(snapshot(page)) if node.href and len(node.href) > 1}
    assert hrefs
    assert not [href for href in hrefs if href in text]


def test_a_filled_field_never_shows_what_is_in_it() -> None:
    raw = (
        '- textbox "Password" [ref=e3]: hunter2\n'
        "- textbox [ref=e4]: typed-into-a-nameless-box\n"
        '- searchbox "Find" [ref=e5]\n'
        "- combobox [ref=e6]: Choose a month\n"
    )
    text = view.render(raw, url="https://x.test/", title="t").text
    assert "hunter2" not in text
    assert "typed-into-a-nameless-box" not in text
    assert 'e3 textbox "Password" [filled]' in text
    assert "e4 textbox [filled]" in text
    assert 'e5 searchbox "Find"\n' in text + "\n"
    assert 'e6 combobox "Choose a month"' in text, "a widget's own label is not typed text"


def test_a_native_select_lists_its_options_and_the_chosen_one() -> None:
    """Playwright gives a `<select>`'s options no ref, so they were never printed: an agent
    could not pick a category on mcpservers.org/submit it could not see."""
    raw = (  # Chromium's ai snapshot of two real <select>s and a custom combobox
        '- combobox "Category" [ref=e3]:\n'
        '  - option "Choose one"\n'
        '  - option "Development"\n'
        '  - option "Productivity" [selected]\n'
        '  - option "Other"\n'
        '- heading "Where" [level=2] [ref=e4]\n'
        '- combobox "Country" [ref=e5]:\n'
        + "".join(f'  - option "Country number {n}"\n' for n in range(1, 250))
    )
    whole = view.render(raw, url="https://x.test/", title="t").text.split("\n")
    assert (
        'e3 combobox "Category" [chosen "Productivity"]:'
        " options Choose one · Development · Productivity · Other"
    ) in whole
    country = next(line for line in whole if line.startswith('e5 combobox "Country"'))
    assert country.endswith(" · +244 more") and len(country) <= 150
    cut = view.render(raw, url="https://x.test/", title="t", focus="number 200", budget=10)
    assert "e5" in cut.text.split("\n")[1], "the options count when ranking by the task"


def test_a_picture_is_dropped_unless_it_can_be_clicked() -> None:
    assert " img " not in look("books_travel").text
    assert '\ne5 img "Fork me on GitHub"\n' in look("internet_iframe").text


def test_a_cover_link_that_repeats_the_title_link_is_dropped() -> None:
    """Book covers: a nameless link to the same page as the title link beside it."""
    assert "e136" not in look("books_travel").text


# ----------------------------------------------------------------------- line kinds


def test_a_text_child_melts_into_its_parent() -> None:
    """`strong "11"` + `text: results.` is one sentence, so it is one line."""
    assert "\ne126: 11 results.\n" in look("books_travel").text


def test_long_text_is_cut_with_an_ellipsis() -> None:
    assert "as though everything is… · e30: by Albert Einstein" in look("quotes").text


def test_an_icon_glyph_reads_as_nothing() -> None:
    """books.toscrape's "in stock" tick is U+F00C from an icon font."""
    assert "" not in look("books_travel").text


def test_a_name_with_a_quote_in_it_is_escaped() -> None:
    raw = '- button "say \\"hi\\"" [ref=e1]'
    assert 'e1 button "say \\"hi\\""' in view.render(raw, url="https://x.test/", title="t").text


def test_states_are_shown() -> None:
    raw = '- checkbox "Bacon" [checked] [ref=e2]\n- button "Undo" [disabled] [ref=e3]'
    text = view.render(raw, url="https://x.test/", title="t").text
    assert 'e2 checkbox "Bacon" [checked]' in text
    assert 'e3 button "Undo" [disabled]' in text


# -------------------------------------------------------------------------- focus


def test_focus_drops_common_words_and_splits_css_names() -> None:
    assert view.focus_words("read css .author-born-date as born") == [
        "read",
        "css",
        "author",
        "born",
        "date",
    ]
    assert view.focus_words("p.price_color") == ["price", "color"]


def test_the_best_block_finds_a_rare_word_past_the_cut() -> None:
    """IANA's .museum row is line 1,000-something; the task names it."""
    shown = look("iana_rootdb")
    best = next(line for line in shown.text.split("\n") if line.startswith("best for "))
    museum = next(ref for ref, t in shown.targets.items() if t.aria_ref == "f33e8848")
    assert museum in best.split()


def test_no_best_block_when_everything_fits() -> None:
    raw = '- button "Save" [ref=e1]\n- link "Cancel" [ref=e2]'
    text = view.render(raw, url="https://x.test/", title="t", focus="save it").text
    assert "best for" not in text


# ---------------------------------------------------------------------- determinism


@pytest.mark.parametrize("page", list(PAGES))
def test_the_same_page_reads_the_same_every_time(page: str) -> None:
    assert look(page).text == look(page).text


# ---------------------------------------------------------------------- filled fields

# What Playwright prints for fields that hold text. A field with a placeholder puts its value
# on a `text:` line of its own, under the placeholder, not after its name.
FILLED_FIELDS = """\
- generic [ref=e1]:
  - textbox "Website" [ref=e2]: https://dejo.run
  - textbox "Email address" [ref=e3]:
    - /placeholder: you@example.com
    - text: rohit@example.com
  - textbox "Tagline" [ref=e4]:
    - /placeholder: One line about it
  - row [ref=e5]:
    - cell "Password" [ref=e7]
    - cell [ref=e8]:
      - textbox "Password" [ref=e6]:
        - /placeholder: Your password
        - text: hunter2
"""


def test_a_field_with_a_placeholder_shows_it_is_filled() -> None:
    """mcpmarket.com, startupfa.me, dang.ai: the email box next to a [filled] URL box showed
    nothing, and an agent took the field for empty and filled it again."""
    shown = view.render(FILLED_FIELDS, url="https://example.com/", title="Submit").text

    assert 'e2 "Website" [filled]' in shown
    assert 'e3 "Email address" [filled]' in shown
    assert 'e4 "Tagline"\n' in shown, "an empty field is not filled"
    assert 'e6 textbox "Password" [filled]' in shown
    for typed in ("rohit@example.com", "hunter2", "dejo.run"):
        assert typed not in shown, f"{typed} was printed"


def test_what_a_field_holds_never_joins_the_words_around_it() -> None:
    """A row with no words of its own stands for the words inside it, and is printed with
    them in the "best for" block, which shows when the budget cut something."""
    page = view.render(
        FILLED_FIELDS, url="https://example.com/", title="Submit", focus="password", budget=40
    )
    assert "best for" in page.text
    assert "hunter2" not in page.text


def test_a_disabled_button_with_no_ref_is_still_shown() -> None:
    """mcpserver.dev: after `click! Submit` the view showed no Submit at all. The button was
    disabled with pointer-events off (how shadcn buttons are styled), so Playwright gave it
    no ref, and the agent could not tell "busy" from "gone"."""
    raw = (
        "- dialog [ref=e1]:\n"
        '  - textbox "Name" [ref=e2]: Dejo\n'
        '  - button "Cancel" [ref=e3]\n'
        '  - button "Submit" [disabled]\n'
        '  - button "Saving" [cursor=pointer]\n'
    )
    shown = view.render(raw, url="https://example.com/", title="Submit")

    assert '\nbutton "Submit" [disabled]' in shown.text
    assert "" not in shown.targets, "a line with no ref offers nothing to act on"


def _carousel(copies: int) -> str:
    cards = ""
    ref = 10
    for _ in range(copies):
        for who in ("Ana", "Bo", "Cy"):
            cards += (
                f"  - listitem [ref=e{ref}]:\n"
                f'    - heading "{who} says" [level=3] [ref=e{ref + 1}]\n'
                f'    - paragraph [ref=e{ref + 2}]: "Dejo saved me hours, {who} writes."\n'
                f'    - link "Read {who}" [ref=e{ref + 3}]:\n'
                f"      - /url: /reviews/{who}\n"
            )
            ref += 4
    return f"- list [ref=e1]:\n{cards}"


def test_a_block_cloned_many_times_is_printed_once() -> None:
    """tinylaunch.com: a testimonial carousel cloned about 20 times filled the view."""
    shown = view.render(_carousel(6), url="https://example.com/", title="Launch")

    assert shown.text.count("Dejo saved me hours, Ana writes.") == 1, shown.text
    assert "the 9 lines above appear 5 more times, word for word" in shown.text
    assert "e74" in shown.known, "the clones' refs still work"


def test_a_short_run_of_look_alikes_still_folds() -> None:
    stars = "".join(f'  - button "★" [ref=e{n}]\n' for n in range(2, 7))
    shown = view.render(f"- generic [ref=e1]:\n{stars}", url="https://example.com/", title="x")
    assert "5 buttons" in shown.text
    assert "more times" not in shown.text
