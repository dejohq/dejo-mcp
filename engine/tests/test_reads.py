"""Every read kind, and the postconditions built on them.

Reading is what makes "check my dashboard numbers" possible, and it is also what a
postcondition is made of. So the second half of this file checks that a read and the
postcondition built from it always agree — they share one code path on purpose.
"""

from __future__ import annotations

import pytest

from dejo import reads
from dejo.browser import Browser
from dejo.models import Postcondition
from dejo.operations import check_postcondition

PAGE = """
<!doctype html>
<title>Billing dashboard</title>
<style> .hidden { display: none; } </style>

<h1 id="heading">Billing</h1>
<p id="total">1,240.00</p>
<p id="empty"></p>
<p id="secret" class="hidden">hidden words</p>

<input id="email" value="finance@acme.com">
<input id="blank" value="">
<input id="locked" value="fixed" readonly>
<input id="off" value="nope" disabled>

<input type="checkbox" id="ticked" checked>
<input type="checkbox" id="unticked">

<button id="live">Submit</button>
<button id="greyed" disabled>Submit</button>

<a id="link" href="/invoices/9" data-state="open">September</a>

<ul id="invoices">
  <li class="invoice">August 2026</li>
  <li class="invoice">September 2026</li>
  <li class="invoice">October 2026</li>
</ul>
"""


@pytest.fixture
def dash(browser: Browser) -> Browser:
    browser.page.set_content(PAGE)
    return browser


def get(browser: Browser, kind: str, selector: str | None = None, **kwargs):
    target = browser.page.locator(selector) if selector else None
    return reads.read(kind, page=browser.page, target=target, **kwargs)


# ------------------------------------------------------------------ registry


def test_registry_and_readers_agree() -> None:
    reads.sanity_check()


def test_every_spec_names_itself() -> None:
    for key, spec in reads.READS.items():
        assert key == spec.name


def test_catalogue_lists_every_read() -> None:
    text = reads.catalogue()
    for name in reads.READS:
        assert name in text


def test_unknown_read_says_what_is_known() -> None:
    with pytest.raises(reads.UnknownRead) as raised:
        reads.spec_for("vibes")
    assert "text" in str(raised.value)


def test_read_without_an_element_is_refused(dash: Browser) -> None:
    with pytest.raises(reads.ReadNeedsMore):
        reads.read("text", page=dash.page)


def test_attribute_without_a_name_is_refused(dash: Browser) -> None:
    with pytest.raises(reads.ReadNeedsMore):
        get(dash, "attribute", "#link")


# --------------------------------------------------------------- the reads


def test_text(dash: Browser) -> None:
    assert get(dash, "text", "#total") == "1,240.00"


def test_text_of_an_empty_element(dash: Browser) -> None:
    assert get(dash, "text", "#empty") == ""


def test_all_text_reads_a_list_in_one_call(dash: Browser) -> None:
    """One call for a whole table, rather than one call per row."""
    assert get(dash, "all_text", ".invoice") == [
        "August 2026",
        "September 2026",
        "October 2026",
    ]


def test_value(dash: Browser) -> None:
    assert get(dash, "value", "#email") == "finance@acme.com"


def test_value_of_an_empty_field(dash: Browser) -> None:
    assert get(dash, "value", "#blank") == ""


@pytest.mark.parametrize(
    ("selector", "expected"),
    [("#ticked", True), ("#unticked", False), ("#missing", False)],
)
def test_checked(dash: Browser, selector: str, expected: bool) -> None:
    assert get(dash, "checked", selector) is expected


@pytest.mark.parametrize(
    ("selector", "expected"),
    [("#heading", True), ("#secret", False), ("#missing", False)],
)
def test_visible(dash: Browser, selector: str, expected: bool) -> None:
    assert get(dash, "visible", selector) is expected


@pytest.mark.parametrize(
    ("selector", "expected"),
    [("#live", True), ("#greyed", False), ("#missing", False)],
)
def test_enabled(dash: Browser, selector: str, expected: bool) -> None:
    assert get(dash, "enabled", selector) is expected


def test_editable_is_not_the_same_as_enabled(dash: Browser) -> None:
    """A read-only field is enabled but cannot be typed into. Telling a caller it is
    editable would send it into a retry loop that can never succeed."""
    assert get(dash, "enabled", "#locked") is True
    assert get(dash, "editable", "#locked") is False
    assert get(dash, "editable", "#email") is True


def test_attribute(dash: Browser) -> None:
    assert get(dash, "attribute", "#link", attribute="href") == "/invoices/9"
    assert get(dash, "attribute", "#link", attribute="data-state") == "open"


def test_attribute_that_is_not_there(dash: Browser) -> None:
    assert get(dash, "attribute", "#link", attribute="aria-expanded") is None


def test_count(dash: Browser) -> None:
    assert get(dash, "count", ".invoice") == 3


def test_count_of_nothing_is_zero(dash: Browser) -> None:
    """Zero, not an error. "How many are there" has an answer even when the answer is none."""
    assert get(dash, "count", ".does-not-exist") == 0


def test_url_and_title(dash: Browser, demo_server: str) -> None:
    assert get(dash, "title") == "Billing dashboard"
    dash.page.goto(f"{demo_server}/")
    assert get(dash, "url") == dash.page.url


def test_page_text(dash: Browser) -> None:
    text = get(dash, "page_text")
    assert "Billing" in text
    assert "September 2026" in text


# ------------------------------------------------------- the postconditions


def check(browser: Browser, kind: str, value: str, target: str | None = None) -> bool:
    return check_postcondition(browser, Postcondition(kind=kind, value=value, target=target))


def test_value_is(dash: Browser) -> None:
    assert check(dash, "value_is", "finance@acme.com", "#email")
    assert not check(dash, "value_is", "someone@else.com", "#email")


def test_value_is_proves_a_fill_landed(dash: Browser) -> None:
    """The point of the kind: a fill that silently did nothing is now caught."""
    dash.page.locator("#blank").fill("typed by dejo")
    assert check(dash, "value_is", "typed by dejo", "#blank")


def test_checked_is(dash: Browser) -> None:
    assert check(dash, "checked_is", "true", "#ticked")
    assert check(dash, "checked_is", "false", "#unticked")
    assert not check(dash, "checked_is", "false", "#ticked")


def test_count_is(dash: Browser) -> None:
    assert check(dash, "count_is", "3", ".invoice")
    assert not check(dash, "count_is", "2", ".invoice")


def test_count_is_rejects_a_value_that_is_not_a_number(dash: Browser) -> None:
    assert not check(dash, "count_is", "three", ".invoice")


def test_attribute_is(dash: Browser) -> None:
    assert check(dash, "attribute_is", "href=/invoices/9", "#link")
    assert not check(dash, "attribute_is", "href=/invoices/10", "#link")


def test_element_gone(dash: Browser) -> None:
    assert check(dash, "element_gone", "#does-not-exist")
    assert not check(dash, "element_gone", "#heading")


def test_element_present_still_reads_its_selector_from_value(dash: Browser) -> None:
    """The older kinds keep their selector in `value`. Every playbook already in memory
    was written that way, so this must not break."""
    assert check(dash, "element_present", "#heading")
    assert not check(dash, "element_present", "#does-not-exist")


def test_a_check_on_a_missing_element_fails_rather_than_crashing(dash: Browser) -> None:
    """This is drift, which the caller repairs. It is not an error."""
    assert not check(dash, "value_is", "anything", "#gone")
    assert not check(dash, "attribute_is", "href=/x", "#gone")
    assert not check(dash, "checked_is", "true", "#gone")


def test_postcondition_round_trips_with_its_target() -> None:
    """A target that did not survive being saved would turn every new kind into a check
    against the wrong element."""
    original = Postcondition(kind="value_is", value="hello", target="#email")
    assert Postcondition.from_dict(original.to_dict()) == original


def test_old_postconditions_still_load() -> None:
    """Written before `target` existed."""
    revived = Postcondition.from_dict({"kind": "text_present", "value": "Billing"})
    assert revived.target is None
    assert revived.value == "Billing"


# ------------------------------------------------------------------ the seam


def test_reads_never_search_for_elements() -> None:
    """`reads.py` reads; it must never locate. Same rule as `actions.py`, so that swapping
    the snapshot cannot turn into a rewrite of this file."""
    with open(reads.__file__, encoding="utf-8") as handle:
        source = handle.read()
    body = source.split("def read(")[1]
    for forbidden in ("page.locator(", "get_by_role(", "get_by_text(", "query_selector("):
        assert forbidden not in body, f"reads.py should not resolve elements: {forbidden}"


EXERCISED = {
    "text",
    "all_text",
    "value",
    "checked",
    "visible",
    "enabled",
    "editable",
    "attribute",
    "count",
    "url",
    "title",
    "page_text",
    # Covered in tests/test_escape_hatch.py.
    "console_errors",
    "failed_requests",
}


def test_every_read_is_exercised() -> None:
    untested = sorted(set(reads.READS) - EXERCISED)
    assert not untested, f"these reads have no test: {untested}"
