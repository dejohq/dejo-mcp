"""Every locator kind, and the refinements that compose with them.

Ten ways to find an element means a step has ten chances to survive a redesign instead of
four. `test_every_locator_kind_is_exercised` fails if a kind is added without a test.
"""

from __future__ import annotations

import pytest

from dejo.browser import Browser, Element
from dejo.models import Locator, LocatorKind

PAGE = """
<!doctype html>
<title>locator lab</title>

<a href="/invoices/9" id="link">September 2026</a>

<label for="email">Email address</label>
<input id="email" placeholder="you@company.com" data-testid="email-field">

<label>Wrapped label <input id="wrapped"></label>

<button data-test-id="save-btn">Save</button>
<button data-qa="cancel-btn">Cancel</button>

<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" alt="Company logo" id="logo">
<span title="Last updated today" id="stamp">Updated</span>

<input id="aria" aria-label="Search invoices">

<ul id="rows">
  <li class="row">August 2026 <button class="edit">Edit</button></li>
  <li class="row">September 2026 <button class="edit">Edit</button></li>
  <li class="row">October 2026 <button class="edit">Edit</button></li>
</ul>
"""


@pytest.fixture
def lab(browser: Browser) -> Browser:
    browser.page.set_content(PAGE)
    return browser


def described(browser: Browser, name: str):
    """Find a control by its visible name and read its durable descriptors.

    `snapshot()` returns role, name and a ref; the descriptors a locator is built from are
    read on demand, only for the elements actually used.
    """
    snapshot = browser.snapshot()
    for element in snapshot.elements:
        if element.name == name:
            return browser.describe(element)
    seen = [element.name for element in snapshot.elements]
    raise AssertionError(f"no control named {name!r}. saw: {seen}")


def resolves_to(browser: Browser, locator: Locator) -> str | None:
    """What did this locator actually land on?"""
    found = browser.resolve(locator)
    return None if found is None else found.get_attribute("id") or found.inner_text().strip()


# ------------------------------------------------------------ every base kind


def test_test_id(lab: Browser) -> None:
    assert resolves_to(lab, Locator("test_id", "data-testid=email-field")) == "email"


def test_test_id_handles_the_other_attribute_names(lab: Browser) -> None:
    """There is no single test-id attribute. A site using `data-test-id` or `data-qa` must
    work without any global configuration, which is why the name is stored with the value."""
    assert resolves_to(lab, Locator("test_id", "data-test-id=save-btn")) == "Save"
    assert resolves_to(lab, Locator("test_id", "data-qa=cancel-btn")) == "Cancel"


def test_test_id_with_no_value_misses_cleanly(lab: Browser) -> None:
    assert resolves_to(lab, Locator("test_id", "data-testid")) is None


def test_structural_href(lab: Browser) -> None:
    assert resolves_to(lab, Locator("structural", "href=/invoices/9")) == "link"


def test_label(lab: Browser) -> None:
    assert resolves_to(lab, Locator("label", "Email address")) == "email"


def test_label_that_wraps_the_field(lab: Browser) -> None:
    assert resolves_to(lab, Locator("label", "Wrapped label")) == "wrapped"


def test_label_finds_an_aria_label(lab: Browser) -> None:
    assert resolves_to(lab, Locator("label", "Search invoices")) == "aria"


def test_role(lab: Browser) -> None:
    assert resolves_to(lab, Locator("role", "link|September 2026")) == "link"


def test_placeholder(lab: Browser) -> None:
    assert resolves_to(lab, Locator("placeholder", "you@company.com")) == "email"


def test_alt(lab: Browser) -> None:
    assert resolves_to(lab, Locator("alt", "Company logo")) == "logo"


def test_title(lab: Browser) -> None:
    assert resolves_to(lab, Locator("title", "Last updated today")) == "stamp"


def test_text(lab: Browser) -> None:
    assert resolves_to(lab, Locator("text", "September 2026")) == "link"


def test_css(lab: Browser) -> None:
    assert resolves_to(lab, Locator("css", "#email")) == "email"


def test_a_kind_that_matches_nothing_returns_none(lab: Browser) -> None:
    """A miss is information, not an error — it is how drift gets noticed."""
    assert resolves_to(lab, Locator("label", "No such field")) is None
    assert resolves_to(lab, Locator("css", "#nope")) is None


# ------------------------------------------------------------- the refinements


def test_nth_picks_one_of_several_look_alikes(lab: Browser) -> None:
    """Three buttons all called Edit. Without an index every replay presses the first."""
    third = Locator("role", "button|Edit", nth=2)
    found = lab.resolve(third)
    assert found is not None
    assert "October" in found.locator("xpath=..").inner_text()


def test_nth_minus_one_is_the_last(lab: Browser) -> None:
    found = lab.resolve(Locator("css", ".row", nth=-1))
    assert found is not None
    assert "October 2026" in found.inner_text()


def test_has_text_finds_the_row_containing_something(lab: Browser) -> None:
    """The real shape of "edit the September row": narrow the list, then act."""
    found = lab.resolve(Locator("css", ".row", has_text="September 2026"))
    assert found is not None
    assert "September 2026" in found.inner_text()


def test_has_text_and_nth_compose(lab: Browser) -> None:
    found = lab.resolve(Locator("css", "li", has_text="2026", nth=1))
    assert found is not None
    assert "September 2026" in found.inner_text()


def test_a_refinement_that_matches_nothing_misses(lab: Browser) -> None:
    assert lab.resolve(Locator("css", ".row", has_text="December 2026")) is None
    assert lab.resolve(Locator("css", ".row", nth=99)) is None


def test_refinements_survive_being_saved() -> None:
    """A refinement lost in storage would silently turn "row three" back into "row one"."""
    original = Locator("role", "button|Edit", nth=2, has_text="September")
    revived = Locator.from_dict(original.to_dict())
    assert revived.nth == 2
    assert revived.has_text == "September"
    assert revived == original


def test_locators_without_refinements_store_nothing_extra() -> None:
    """Old playbooks must round-trip byte for byte, or every one of them looks changed."""
    written = Locator("css", "#email").to_dict()
    assert "nth" not in written
    assert "has_text" not in written


def test_old_locators_still_load() -> None:
    revived = Locator.from_dict({"kind": "css", "value": "#email", "hits": 3, "misses": 1})
    assert revived.nth is None
    assert revived.has_text is None
    assert revived.hits == 3


def test_describe_reads_clearly() -> None:
    """This is what a human sees in a repair request."""
    assert Locator("css", ".row").describe() == "css=.row"
    plain = Locator("role", "button|Edit", nth=2, has_text="September").describe()
    assert plain == "role=button|Edit containing 'September' [2]"


# --------------------------------------------------- what a snapshot produces


def test_snapshot_captures_the_new_descriptors(lab: Browser) -> None:
    email = described(lab, "Email address")
    assert email.css == "#email"
    assert email.test_id == "data-testid=email-field"
    assert email.label == "Email address"
    assert email.placeholder == "you@company.com"


def test_snapshot_counts_look_alikes(lab: Browser) -> None:
    """Three Edit buttons must be told apart, or all three store the same locator."""
    edits = [el for el in lab.snapshot().elements if el.name == "Edit"]
    assert len(edits) == 3
    assert [el.nth for el in edits] == [0, 1, 2]
    assert all(el.twins == 3 for el in edits)


def test_a_unique_element_is_not_pinned_to_a_position(lab: Browser) -> None:
    """An index is one more thing that can go stale, so it is only added when needed."""
    save = described(lab, "Save")
    assert save.twins == 1
    assert all(loc.nth is None for loc in save.locators())


def test_look_alikes_are_pinned(lab: Browser) -> None:
    edits = [el for el in lab.snapshot().elements if el.name == "Edit"]
    third = lab.describe(edits[2]).locators()
    assert any(loc.nth == 2 for loc in third)


def test_test_id_is_ranked_first(lab: Browser) -> None:
    """Before any locator has a track record, order is all we have. A test id is written
    for machines and is almost never touched by a redesign."""
    element = Element(
        ref="e1",
        role="button",
        name="Save",
        tag="button",
        css="#save",
        test_id="data-testid=save",
        label="Save it",
    )
    kinds = [loc.kind for loc in element.locators()]
    assert kinds[0] == "test_id"
    assert kinds.index("label") < kinds.index("css")


def test_a_form_field_is_not_given_a_text_locator(lab: Browser) -> None:
    """A field takes its name from a `<label>` beside it, so searching the page for that
    text finds the label, not the field — and filling a label does nothing. Found by
    `test_every_locator_a_real_element_offers_actually_resolves`."""
    email = described(lab, "Email address")
    assert not any(loc.kind == "text" for loc in email.locators())


def test_a_link_is_still_given_a_text_locator(lab: Browser) -> None:
    """Links and buttons contain their own words, so text is sound for them."""
    link = described(lab, "September 2026")
    assert any(loc.kind == "text" for loc in link.locators())


@pytest.mark.parametrize(
    ("name", "wanted"),
    [("Email address", "email"), ("September 2026", "link"), ("Company logo", "logo")],
)
def test_every_locator_a_real_element_offers_actually_resolves(
    lab: Browser, name: str, wanted: str
) -> None:
    """The end-to-end claim: every locator we store for an element finds that element.
    A locator that is written down but never resolves is worse than none — it costs a
    failed attempt on every replay."""
    element = described(lab, name)
    assert element.locators(), f"{name} offers no locators at all"
    for locator in element.locators():
        found = lab.resolve(locator)
        assert found is not None, f"{locator.describe()} found nothing"
        assert found.get_attribute("id") == wanted, f"{locator.describe()} found the wrong element"


# --------------------------------------------------------------- the coverage

EXERCISED: set[str] = {
    "test_id",
    "structural",
    "label",
    "role",
    "placeholder",
    "alt",
    "title",
    "text",
    "css",
}


def test_every_locator_kind_is_exercised() -> None:
    from typing import get_args

    untested = sorted(set(get_args(LocatorKind)) - EXERCISED)
    assert not untested, f"these locator kinds have no test: {untested}"
