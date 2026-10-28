"""The query part of an address: when it tells two pages apart, and when it is noise.

Found on real sites on 22 Oct 2026: a price filter, page 2 of a shop, page 5 of a table, and
a college catalog that serves every page as `/content.php?navoid=N`. Dejo compared paths only,
so a replay on the wrong page was called right.
"""

from __future__ import annotations

from dejo.distill import _landing
from dejo.executor import _leaves_out_of
from dejo.models import Playbook, Postcondition, Step
from dejo.operations import TraceEntry, at_address


def moved(before: str, after: str) -> str:
    return _landing(TraceEntry(intent="go", action="click", url_before=before, url_after=after))


def trail_from(address: str) -> Playbook:
    start = Step(1, "open", "goto", Postcondition("url_contains", "/"), value=address)
    return Playbook(domain="x.org", task="t", steps=[start])


def test_a_filter_on_the_same_path_keeps_what_changed() -> None:
    assert moved("https://x.org/books", "https://x.org/books?price=50-") == "/books?price=50-"


def test_only_the_values_that_changed_are_kept() -> None:
    landed = moved("https://x.org/list?sort=a&page=1", "https://x.org/list?sort=a&page=2")
    assert landed == "/list?page=2"


def test_a_new_path_drops_the_query_as_before() -> None:
    assert moved("https://x.org/", "https://x.org/search?sid=91ab&q=x") == "/search"


def test_the_address_check_compares_values_not_their_order() -> None:
    assert at_address("https://x.org/list?utm=1&page=2&sort=a", "/list?page=2")
    assert not at_address("https://x.org/list?page=1", "/list?page=2")
    assert not at_address("https://x.org/other?page=2", "/list?page=2")


def test_a_plain_path_check_is_unchanged() -> None:
    assert at_address("https://x.org/invoices?variant=b", "/invoices")


def test_a_url_with_parts_left_out_is_not_a_new_start() -> None:
    trail = trail_from("https://www.x.org/pages/forms/?page_num=5")
    assert _leaves_out_of("https://www.x.org/pages/forms/", trail)
    assert _leaves_out_of("https://x.org/", trail)


def test_a_url_that_adds_or_changes_something_is_a_new_start() -> None:
    trail = trail_from("https://x.org/pages/forms/?page_num=5")
    assert not _leaves_out_of("https://x.org/pages/forms/?page_num=7", trail)
    assert not _leaves_out_of("https://x.org/?variant=b", trail)
    assert not _leaves_out_of("https://y.org/pages/forms/", trail)


def test_a_page_belongs_to_its_site_with_or_without_www_and_under_it() -> None:
    from dejo.browser import on_site

    assert on_site("https://www.saashub.com/x", "saashub.com")
    assert on_site("https://app.saashub.com/", "www.saashub.com")
    assert not on_site("https://saashub.com/", "agenticskills.io")
    assert not on_site("https://notsaashub.com/", "saashub.com")
    assert not on_site("about:blank", "saashub.com")
