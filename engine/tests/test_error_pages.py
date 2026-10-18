"""A run that lands on an error page or a sign-in page must not report the page as its answer.

Found in real use. A saved route read the full text of a Google Doc. Replayed later while
signed out, Google sent the document to accounts.google.com/...?continue=<the document>,
and three things went wrong in a row:

1. The address check passed, because the document's path sat inside the query string.
2. Walking back to the document joined its path onto accounts.google.com, which is 404.
3. The whole-page read then ran on that 404 page, and the run said `ok` with
   "404. That's an error." as the document's text.
"""

from __future__ import annotations

from types import SimpleNamespace

from dejo.browser import Browser
from dejo.executor import Executor, _trail_origin
from dejo.models import Playbook, Postcondition, Step
from dejo.operations import READ_ACTION, address_to_check, check_postcondition
from dejo.store import DejoStore

DOC = "/document/d/abc123/mobilebasic"
SIGN_IN = (
    f"https://accounts.google.com/v3/signin/accountchooser?continue=https://docs.google.com{DOC}"
)


def on(url: str) -> SimpleNamespace:
    """A stand-in browser that is on `url`, for checks that only look at the address."""
    return SimpleNamespace(page=SimpleNamespace(url=url))


class TestTheAddressCheck:
    def test_a_sign_in_page_carrying_the_document_in_its_query_is_not_the_document(self) -> None:
        assert not check_postcondition(on(SIGN_IN), Postcondition("url_contains", DOC))

    def test_the_document_itself_passes(self) -> None:
        assert check_postcondition(
            on(f"https://docs.google.com{DOC}"), Postcondition("url_contains", DOC)
        )

    def test_an_expectation_with_its_own_query_is_still_checked_against_the_query(self) -> None:
        here = "https://github.com/microsoft/playwright/issues?q=is%3Aopen"
        assert check_postcondition(on(here), Postcondition("url_contains", "/issues?q=is%3Aopen"))

    def test_the_query_and_fragment_are_set_aside_only_when_not_asked_for(self) -> None:
        assert address_to_check("https://a.example/x?y=1#z", "/x") == "https://a.example/x"
        assert address_to_check("https://a.example/x?y=1", "/x?y=1") == "https://a.example/x?y=1"


def test_a_trail_starts_where_its_first_address_is() -> None:
    trail = Playbook(
        domain="docs.google.com",
        task="read a doc",
        steps=[
            Step(
                index=1,
                intent="open it",
                action="goto",
                value=f"https://docs.google.com{DOC}",
                postcondition=Postcondition("url_contains", DOC),
            )
        ],
    )
    assert _trail_origin(trail) == "https://docs.google.com/"
    assert _trail_origin(Playbook(domain="x", task="t", steps=[])) is None


def test_an_error_page_is_reported_and_nothing_is_read(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """A page the server answers with 404 is a missing page, not an answer to report."""
    site, task = "billing.example", "read the archived statement"
    store.save_playbook(
        Playbook(
            domain=site,
            task=task,
            steps=[
                Step(
                    index=1,
                    intent="open the archived statement",
                    action="goto",
                    value=f"{demo_server}/statements/archived-and-gone",
                    postcondition=Postcondition("url_contains", "/statements/archived-and-gone"),
                ),
                Step(
                    index=2,
                    intent="the statement text",
                    action=READ_ACTION,
                    value="page_text",
                    postcondition=Postcondition("url_contains", "/statements/archived-and-gone"),
                ),
            ],
        )
    )

    result = Executor(store, browser).run(site, task=task)

    assert result.ok is False
    assert result.page_error == 404
    assert result.answers == {}
    assert result.repair is None
    assert "404" in result.reason
