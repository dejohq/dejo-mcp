"""A finished run must not hand back a site that is still moving.

Reported from a real marketplace. Replaying an admin sign-in worked perfectly — four steps,
half a second, `ok: true` — and then:

    dejo_read(kind="url")  ->  ".../admin/sign-in/"     # looks like it failed

The sign-in HAD succeeded; the app's redirect was simply still in flight. But a caller
reading the URL straight afterwards concludes the trail is broken and goes off to explore a
site Dejo already knew, which is the exact cost this project exists to remove.

The shape that causes it is specific, and it is the commonest shape there is: a submit
BUTTON. It has no href to hint that navigation is coming, so nothing recorded at learn time
says the address will change, and the last step's check passes on the page it was already
on.

Trails that end in a READ — the answer, which is most of them — have nothing in flight and
wait for nothing.
"""

from __future__ import annotations

import pytest

from dejo.browser import Browser
from dejo.executor import Executor
from dejo.operations import Session
from dejo.store import DejoStore

SITE = "hard.example"


@pytest.fixture
def hard(browser: Browser, store: DejoStore, demo_server: str) -> Session:
    session = Session(browser=browser, store=store)
    session.act("open the hard page", "goto", value=f"{demo_server}/hard")
    session.act("learn the cookie banner", "dismiss_when_seen", value="#accept-cookies")
    return session


def _ref(session: Session, name: str) -> str:
    for element in session.look()["elements"]:
        if element["name"] == name:
            return element["ref"]
    raise AssertionError(f"no control called {name!r}")


class TestATrailThatEndsByPressingSomething:
    def test_the_run_waits_for_the_app_to_finish_moving(
        self, hard: Session, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        """The claim, as the caller experiences it: read the URL the instant `run` returns
        and it is already the page the sign-in led to."""
        hard.act("sign in", "click", ref=_ref(hard, "Sign in"))
        hard.save("sign in", domain=SITE)

        browser.goto(f"{demo_server}/hard")
        result = Executor(store, browser).run(SITE, task="sign in", start_url=f"{demo_server}/hard")

        assert result.ok is True
        assert browser.page.url.endswith("/hard/dashboard"), (
            "the run returned while the redirect was still in flight"
        )

    def test_the_last_step_had_no_url_check_of_its_own(
        self, hard: Session, store: DejoStore
    ) -> None:
        """Why the wait has to exist at all.

        The button carries no href, so nothing at learn time knew the address was about to
        change — the step's own check is about the element, not the URL, and passes on the
        page it started on.
        """
        hard.act("sign in", "click", ref=_ref(hard, "Sign in"))
        playbook = hard.save("sign in", domain=SITE)

        assert playbook.steps[-1].postcondition.kind != "url_contains"


class TestATrailThatEndsByReading:
    def test_it_waits_for_nothing(
        self, hard: Session, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        """Most trails end with the answer, and there is nothing in flight after a read.

        This is the common case and the one the benchmark measures, so it must not pay for
        a wait it does not need.
        """
        hard.read("text", ref="#spa-where", remember=True, intent="where we are")
        playbook = hard.save("read where we are", domain=SITE)
        assert playbook.steps[-1].action == "read"

        browser.goto(f"{demo_server}/hard")
        result = Executor(store, browser).run(
            SITE, task="read where we are", start_url=f"{demo_server}/hard"
        )

        assert result.ok is True
        assert result.answers["where we are"] == "nowhere yet"
