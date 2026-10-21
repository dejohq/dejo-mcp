"""`dejo_login done=true` looks at the window before it believes anyone.

Found for real on Google: called twice while the sign-in window still sat on the identifier
page, it answered "signed in" both times and wrote "signed in by hand" into the site's
memory. The next run then failed with nothing to explain why.

The window is stood in for here, so these tests need no screen: what is under test is what
the tool decides from what the window shows.
"""

from __future__ import annotations

from typing import Any

import pytest

from helpers import call

SITE = "accounts.example.com"


class StandInWindow:
    """Answers the one question the tool asks a sign-in window, and records being closed."""

    def __init__(self, shows: tuple[str, bool] | None) -> None:
        self.shows = shows
        self.closed = False

    def submit(self, job) -> Any:
        return job(self)

    def sign_in_window(self) -> tuple[str, bool] | None:
        return self.shows

    def stop(self) -> None:
        self.closed = True


@pytest.fixture
def window_showing(mcp_server):
    def open_one(shows: tuple[str, bool] | None) -> StandInWindow:
        window = StandInWindow(shows)
        mcp_server.dejo_tools._login_worker = window
        return window

    return open_one


def facts_about(mcp_server, site: str) -> list[str]:
    knowledge = mcp_server.dejo_tools.store.load_site_knowledge(site)
    return knowledge.summary() if knowledge else []


def done(mcp_server, **extra) -> str:
    return call(mcp_server, "dejo_login", site=SITE, done=True, **extra)


def test_a_window_still_on_the_sign_in_page_is_not_signed_in(mcp_server, window_showing):
    window = window_showing((f"https://{SITE}/signin/identifier", True))

    said = done(mcp_server)

    assert said.startswith("the window still shows a sign-in page, so it is still open")
    assert window.closed is False, "the person is still signing in; the window must stay"
    assert facts_about(mcp_server, SITE) == [], "nothing untrue may be written to memory"


def test_once_the_window_has_moved_on_it_is_signed_in(mcp_server, window_showing):
    window = window_showing((f"https://{SITE}/home", False))

    said = done(mcp_server)

    assert said.startswith(f"signed in to {SITE}")
    assert "No password or code was kept" in said
    assert window.closed is True
    assert any("signed in by hand" in fact for fact in facts_about(mcp_server, SITE))


def test_the_person_can_overrule_a_wrong_guess(mcp_server, window_showing):
    """A signed-in page can live at an address with /auth in it. The check is a guess, so
    the person looking at the window gets the last word."""
    window = window_showing((f"https://{SITE}/auth/welcome", True))

    assert done(mcp_server, confirmed=True).startswith("signed in")
    assert window.closed is True


def test_a_closed_window_claims_nothing(mcp_server, window_showing):
    window_showing(None)

    said = done(mcp_server)

    assert "closed before Dejo could check it" in said
    assert mcp_server.dejo_tools.signing_in is False, "the dead window is let go of"
    assert facts_about(mcp_server, SITE) == []
