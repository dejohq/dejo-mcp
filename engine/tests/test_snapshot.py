"""The snapshot, on Playwright's own engine.

The page below is the reason this step exists. Our hand-written collector found **one**
element on it. Everything else was invisible: shadow DOM, iframe contents, a `div` acting
as a button, and content that had not loaded yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dejo import snapshot as aria
from dejo.browser import Browser
from dejo.models import Locator

HARD = """
<!doctype html>
<title>the hard page</title>

<button id="plain">Plain button</button>

<div id="host"></div>
<script>
  document.getElementById('host').attachShadow({mode: 'open'}).innerHTML =
    '<button id="inshadow">Shadow button</button>';
</script>

<div role="combobox" aria-expanded="false" tabindex="0" id="fake">Choose a month</div>

<div id="pretend" style="cursor: pointer" onclick="document.title='div clicked'">
  Looks like a button
</div>

<iframe id="frame" srcdoc='
  <button id="inframe" onclick="document.body.dataset.clicked=&apos;yes&apos;">Frame button</button>
  <a href="/x" id="framelink">Frame link</a>
'></iframe>

<a href="/invoices/9" data-testid="inv">September 2026</a>

<script>
  setTimeout(() => {
    const late = document.createElement('a');
    late.href = '/late';
    late.textContent = 'Late link';
    document.body.appendChild(late);
  }, 250);
</script>
"""


@pytest.fixture
def hard(browser: Browser) -> Browser:
    browser.page.set_content(HARD)
    browser.page.wait_for_timeout(500)
    return browser


def names(browser: Browser) -> list[str]:
    return [element.name for element in browser.snapshot().elements]


def find(browser: Browser, name: str):
    for element in browser.snapshot().elements:
        if element.name == name:
            return element
    raise AssertionError(f"no control named {name!r}. saw: {names(browser)}")


# ------------------------------------------------------- what it now finds


def test_a_plain_button(hard: Browser) -> None:
    assert "Plain button" in names(hard)


def test_inside_a_shadow_dom(hard: Browser) -> None:
    """The old collector used `document.querySelectorAll`, which stops at a shadow root."""
    assert "Shadow button" in names(hard)


def test_inside_an_iframe(hard: Browser) -> None:
    """`querySelectorAll` never crosses a frame boundary either."""
    assert "Frame button" in names(hard)


def test_a_div_that_behaves_like_a_button(hard: Browser) -> None:
    """No interactive role at all — this is the shape most component libraries produce,
    and the old collector was blind to every one of them. Playwright reports the pointer
    cursor, which is the site itself saying "this is clickable"."""
    assert "Looks like a button" in names(hard)


def test_a_div_with_a_widget_role(hard: Browser) -> None:
    assert "Choose a month" in names(hard)


def test_content_that_arrived_late(hard: Browser) -> None:
    assert "Late link" in names(hard)


def test_the_whole_hard_page_is_seen(hard: Browser) -> None:
    """The measurement that justified this step. The old collector found 1."""
    found = names(hard)
    for wanted in (
        "Plain button",
        "Shadow button",
        "Choose a month",
        "Looks like a button",
        "Frame button",
        "Frame link",
        "September 2026",
        "Late link",
    ):
        assert wanted in found, f"{wanted!r} is missing. saw: {found}"


# ------------------------------------------------------ and can act on it


def test_a_shadow_dom_button_is_clickable(hard: Browser) -> None:
    """Finding it is only half. A ref has to resolve back to something usable."""
    hard.locate(find(hard, "Shadow button")).click()


def frame_was_clicked(browser: Browser) -> bool:
    """Read inside the frame. A frame has its own document, so the parent page's title
    would never change however hard the button is pressed."""
    inside = browser.page.frame_locator("#frame").locator("body")
    return inside.get_attribute("data-clicked") == "yes"


def test_an_iframe_button_is_clickable(hard: Browser) -> None:
    hard.locate(find(hard, "Frame button")).click()
    assert frame_was_clicked(hard)


def test_a_div_button_is_clickable(hard: Browser) -> None:
    hard.locate(find(hard, "Looks like a button")).click()
    assert hard.page.title() == "div clicked"


# --------------------------------------------------------------- frames


def test_an_element_in_a_frame_records_which_frame(hard: Browser) -> None:
    """A locator that does not name its frame is unresolvable later: `page.locator` does
    not look inside iframes, so the selector would simply find nothing."""
    inside = hard.describe(find(hard, "Frame button"))
    assert inside.frame == "#frame"
    assert all(locator.frame == "#frame" for locator in inside.locators())


def test_an_element_outside_a_frame_records_no_frame(hard: Browser) -> None:
    outside = hard.describe(find(hard, "Plain button"))
    assert outside.frame is None


def test_a_stored_locator_inside_a_frame_resolves_again(hard: Browser) -> None:
    """The end-to-end claim for frames: write it down, find it again."""
    inside = hard.describe(find(hard, "Frame button"))
    for locator in inside.locators():
        found = hard.resolve(locator)
        assert found is not None, f"{locator.describe()} found nothing"
    hard.resolve(inside.locators()[0]).click()
    assert frame_was_clicked(hard)


def test_the_same_locator_without_its_frame_finds_nothing(hard: Browser) -> None:
    """Proves the frame field is doing real work rather than being decoration."""
    inside = hard.describe(find(hard, "Frame button"))
    homeless = inside.locators()[0]
    homeless.frame = None
    assert hard.resolve(homeless) is None


def test_a_frame_locator_reads_clearly() -> None:
    written = Locator("css", "#inframe", frame="#frame").describe()
    assert written == "in frame #frame css=#inframe"


def test_a_frame_survives_being_saved() -> None:
    original = Locator("css", "#inframe", frame="#frame")
    assert Locator.from_dict(original.to_dict()) == original


def test_a_locator_with_no_frame_stores_nothing_extra() -> None:
    assert "frame" not in Locator("css", "#x").to_dict()


# ----------------------------------------------------- descriptors on demand


def test_a_fresh_snapshot_has_no_descriptors(hard: Browser) -> None:
    """Reading them for every element would cost a round trip each, and most elements are
    never touched."""
    assert find(hard, "Plain button").css == ""


def test_describing_fills_them_in(hard: Browser) -> None:
    described = hard.describe(find(hard, "September 2026"))
    assert described.css == "a[href='/invoices/9']" or described.css
    assert described.test_id == "data-testid=inv"
    assert described.tag == "a"
    assert described.href == "/invoices/9"


def test_describing_something_that_has_gone_is_not_an_error(hard: Browser) -> None:
    element = find(hard, "Plain button")
    hard.page.evaluate("document.getElementById('plain').remove()")
    assert hard.describe(element).css == ""


# ------------------------------------------- field contents never come out

FORM = """
<label for="e">Email</label><input id="e" value="finance@acme.com">
<label for="p">Password</label><input id="p" type="password" value="hunter2">
<label for="b">Blank</label><input id="b" value="">
"""


def test_playwright_itself_prints_the_password(browser: Browser) -> None:
    """Not our bug, but our problem. This is why the parser throws field contents away
    instead of reading them, and this test is here so nobody quietly "improves" it back."""
    browser.page.set_content(FORM)
    raw = browser.page.locator("body").aria_snapshot(mode="ai")
    assert "hunter2" in raw


def test_a_filled_field_says_only_that_it_is_filled(browser: Browser) -> None:
    browser.page.set_content(FORM)
    snapshot = browser.snapshot()

    password = next(el for el in snapshot.elements if el.name == "Password")
    assert password.value == aria.FILLED
    assert "hunter2" not in str(snapshot.to_dict())


def test_an_ordinary_field_is_no_different(browser: Browser) -> None:
    """One rule, no exceptions to remember. A caller that wants the text asks for it."""
    browser.page.set_content(FORM)
    email = next(el for el in browser.snapshot().elements if el.name == "Email")
    assert email.value == aria.FILLED


def test_an_empty_field_says_nothing(browser: Browser) -> None:
    browser.page.set_content(FORM)
    blank = next(el for el in browser.snapshot().elements if el.name == "Blank")
    assert blank.value is None


def test_describing_reads_the_real_value_but_still_hides_a_password(
    browser: Browser,
) -> None:
    """`describe` runs in the page, where it can see `type=password` and redact it."""
    browser.page.set_content(FORM)
    snapshot = browser.snapshot()

    email = browser.describe(next(el for el in snapshot.elements if el.name == "Email"))
    assert email.value == "finance@acme.com"

    secret = browser.describe(next(el for el in snapshot.elements if el.name == "Password"))
    assert secret.value == aria.FILLED


def test_a_name_that_is_only_trailing_text_still_survives() -> None:
    """A `div role="combobox"` has no quoted name — its trailing text IS its name. Telling
    the two cases apart is what stops the fix from erasing those names."""
    elements = aria.parse("- combobox [ref=e5]: Choose a month")
    assert elements[0].name == "Choose a month"
    assert elements[0].value is None


@pytest.mark.parametrize("role", ["textbox", "searchbox", "spinbutton"])
def test_an_unlabelled_field_never_takes_its_contents_as_a_name(role: str) -> None:
    """Playwright prints an unlabelled password box as `textbox [ref=e2]: hunter2`. Read as
    a name, the password went to the caller and into the locator written to memory."""
    element = aria.parse(f"- {role} [ref=e2]: hunter2")[0]
    assert "hunter2" not in element.name
    assert element.value == aria.FILLED
    assert all("hunter2" not in locator.value for locator in element.locators())


def test_an_unlabelled_password_box_in_a_real_browser(browser: Browser) -> None:
    browser.page.set_content("<input type=password id=pw>")
    browser.page.fill("#pw", "hunter2")
    assert "hunter2" not in str(browser.snapshot().to_dict())


# ------------------------------------------------------------- the parser


def test_parse_reads_a_snapshot() -> None:
    """Parsed without a browser, so a change in the format shows up as a parser failure
    rather than as a mysterious empty page."""
    elements = aria.parse(
        """
- generic [active] [ref=e1]:
  - button "Plain button" [ref=e2]
  - combobox [ref=e5]: Choose a month
  - link "September 2026" [ref=e7] [cursor=pointer]:
    - /url: /invoices/9
"""
    )
    assert [element.ref for element in elements] == ["e2", "e5", "e7"]
    assert elements[1].name == "Choose a month"
    assert elements[2].href == "/invoices/9"


def test_parse_keeps_a_pointer_cursor_even_without_a_role() -> None:
    elements = aria.parse('- generic "Looks like a button" [ref=e3] [cursor=pointer]')
    assert [element.ref for element in elements] == ["e3"]


def test_parse_drops_layout() -> None:
    """A container with no role and no pointer is not something to offer a caller."""
    assert aria.parse('- generic "just a wrapper" [ref=e9]') == []


def test_parse_counts_look_alikes() -> None:
    elements = aria.parse(
        """
- button "Edit" [ref=e1]
- button "Edit" [ref=e2]
- button "Edit" [ref=e3]
"""
    )
    assert [element.nth for element in elements] == [0, 1, 2]
    assert all(element.twins == 3 for element in elements)


def test_parse_ties_an_element_to_its_frame() -> None:
    elements = aria.parse(
        '- iframe [ref=e3]:\n  - button "In a frame" [ref=f1e2]', frames={"e3": "#frame"}
    )
    assert elements[0].frame == "#frame"
    assert elements[0].ref == "f1e2"


# Playwright's snapshot of a page reached by navigating: every ref is prefixed, the main
# page's included. Taken from a real run (the shape repro'd on 20 Oct 2026).
NAVIGATED = """
- generic [active] [ref=f3e1]:
  - button "Outside" [ref=f3e2]
  - iframe [ref=f3e3]:
    - button "Pay now" [ref=f4e2]
  - link "After the frame" [ref=f3e5]
"""


def test_a_main_page_element_on_a_navigated_page_has_no_frame() -> None:
    """`f3e2` is a plain button. Read as "frame 3" it was tied to a frame that is not
    there, or, as here, the real frame's element was tied to nothing."""
    outside = aria.parse(NAVIGATED, frames={"f3e3": "#card"})[0]
    assert outside.frame is None


def test_an_element_in_a_frame_is_found_by_nesting_whatever_its_number() -> None:
    elements = {e.name: e for e in aria.parse(NAVIGATED, frames={"f3e3": "#card"})}
    assert elements["Pay now"].frame == "#card"
    assert elements["After the frame"].frame is None, "the frame ends where its indent does"


def test_refs_read_the_same_on_every_visit() -> None:
    """A caller sees Dejo's refs, not Playwright's numbering of the document."""
    elements = {e.name: e for e in aria.parse(NAVIGATED)}
    assert elements["Outside"].ref == "e2"
    assert elements["Pay now"].ref == "f1e2"
    assert elements["Pay now"].aria_ref == "f4e2", "Playwright's own ref is kept for acting"


# ------------------------------------------------- lines Playwright puts in quotes


def test_a_name_with_a_colon_and_space_is_not_skipped() -> None:
    """Playwright quotes the whole line when the name has ": " in it. Every such element
    used to vanish: 47 controls on one GitHub page."""
    elements = aria.parse(
        '- link "Docs" [ref=e1]\n- \'link "Fix: login bug" [ref=e2] [cursor=pointer]\':\n'
        "  - /url: /issues/7"
    )
    assert [e.name for e in elements] == ["Docs", "Fix: login bug"]
    assert elements[1].href == "/issues/7"
    assert elements[1].clickable


def test_a_quoted_line_keeps_its_escaped_quote() -> None:
    elements = aria.parse("- 'button \"Joe''s: bar\" [ref=e4]'")
    assert elements[0].name == "Joe's: bar"


def test_a_double_quoted_line_is_read_too() -> None:
    elements = aria.parse('- "button \\"say: hi\\" [ref=e5]"')
    assert elements[0].name == "say: hi"


def test_quoted_trailing_text_is_unquoted() -> None:
    elements = aria.parse('- combobox [ref=e6]: "Month: September"')
    assert elements[0].name == "Month: September"


# ------------------------------------------------------- real pages, every node

FIXTURES = Path(__file__).parent / "fixtures" / "aria"


@pytest.mark.parametrize("page", ["books_travel", "crates_search", "internet_iframe", "quotes"])
def test_every_node_with_a_ref_is_read(page: str) -> None:
    """Real snapshots from the 20 Oct lab, signed out. Not one ref'd line may be dropped."""
    text = (FIXTURES / f"{page}.txt").read_text(encoding="utf-8")
    assert len(aria.nodes(text)) == text.count("[ref=")


def test_a_real_frame_is_tied_to_its_iframe() -> None:
    """The-internet's TinyMCE page: the main document is `f51`, the editor's frame `f52`."""
    text = (FIXTURES / "internet_iframe.txt").read_text(encoding="utf-8")
    inside = [node for node in aria.nodes(text) if node.frame_ref]
    assert inside and all(node.frame_ref == "f51e77" for node in inside)
    assert all(e.ref.startswith("e") for e in aria.parse(text) if not e.frame)


def test_main_page_refs_lose_playwrights_prefix() -> None:
    text = (FIXTURES / "crates_search.txt").read_text(encoding="utf-8")
    assert all(not e.ref.startswith("f") for e in aria.parse(text))


def test_an_address_goes_to_the_line_it_is_nested_under() -> None:
    """The-internet's "Fork me" link has no ref of its own. Its address used to be handed to
    the last line that HAD a ref, here a plain button, which would then have stored a
    `structural` locator for somewhere it does not go."""
    text = (
        '- button "Save" [ref=e1]\n'
        '- link "Fork me on GitHub":\n'
        "  - /url: https://github.com/saucelabs/the-internet\n"
        '  - img "Fork me on GitHub" [ref=e2] [cursor=pointer]\n'
    )
    assert aria.nodes(text)[0].href is None
    link = next(node for node in aria.lines(text) if node.role == "link")
    assert link.href == "https://github.com/saucelabs/the-internet"
    assert not link.aria_ref and not link.ref


def test_every_line_carries_its_depth_and_its_callers_ref() -> None:
    every = aria.lines(NAVIGATED)
    assert [(node.depth, node.ref) for node in every] == [
        (0, "e1"),
        (2, "e2"),
        (2, "e3"),
        (4, "f1e2"),
        (2, "e5"),
    ]


def test_parse_handles_a_quoted_name_with_quotes_in_it() -> None:
    elements = aria.parse('- button "say \\"hello\\"" [ref=e1]')
    assert elements[0].name == 'say "hello"'


def test_parse_survives_a_line_it_does_not_understand() -> None:
    """A format change should cost us one element, not the whole page."""
    elements = aria.parse('nonsense\n- button "Real" [ref=e1]\n   \n')
    assert [element.name for element in elements] == ["Real"]


def test_iframe_refs_are_found_in_order() -> None:
    assert aria.iframe_refs("- iframe [ref=e6]:\n- iframe [ref=e9]:") == ["e6", "e9"]


def test_the_hand_written_collector_is_gone() -> None:
    """It could only ever see the tags it was told to look for."""
    from dejo import browser

    assert not hasattr(browser, "_COLLECT_JS")
