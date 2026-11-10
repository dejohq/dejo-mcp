"""The drift lab: learn a task on one visit, replay it on the next, where the page changed.

Every page in `demo_site/drift.py` is different on the visit after the first, the way real
sites are. Each case below learns on visit one, replays on visit two, and says what Dejo did:
went through and said what it decided on its own, or stopped and said why. Nothing that
changed what ran may be missing from `decisions`.

The narrower behaviour behind each case is tested beside it: `test_popups.py`,
`test_toasts.py`, `test_accounts.py`, `test_signed_out.py` and `test_decisions.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from tests.demo_site.drift import ACCOUNT_COOKIE

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor, ReplayResult
from dejo.operations import Session
from dejo.runner import Runner
from dejo.store import DejoStore

TASK = "the lab task"

_PRICE = 'click button "Show the price"\nread css "#price" as answer'


@dataclass(frozen=True)
class Case:
    path: str
    steps: str
    answer: str
    """What the replay must answer."""
    decided: str = ""
    """Words one of the replay's decisions must hold. Empty: it decides nothing."""


CASES = {
    "a toast shown on some visits": Case(
        "/drift/toast?kind=fade",
        f'click button "Close"\n{_PRICE}',
        "£12 a month",
        'skipped (click button "Close")',
    ),
    "a newsletter box only on replay": Case(
        "/drift/newsletter", _PRICE, "£12 a month", 'closed by its "No thanks" control'
    ),
    "a consent banner only on replay": Case(
        "/drift/consent", _PRICE, "£12 a month", 'consent banner answered with "Reject all"'
    ),
    "a box only Escape closes": Case(
        "/drift/escape", _PRICE, "£12 a month", "closed with the Escape key"
    ),
    "a button whose words and class change, id kept": Case(
        "/drift/button?keep=id",
        'click button "Show total"\nread css "#total" as answer',
        "£31.40",
        "found by a backup way",
    ),
    "a button whose words and class change, nothing kept but its role": Case(
        "/drift/button?keep=role",
        'click button "Show total"\nread css "#total" as answer',
        "£31.40",
        "found by a backup way (css:",
    ),
    "a list that reorders, item picked by name": Case(
        "/drift/list", 'click link "Teapot"\nread css "#price" as answer', "£18.50"
    ),
    "a list that reorders, item picked as the first": Case(
        "/drift/list", 'click css "li.item a" first\nread css "#price" as answer', "£6.00"
    ),
    "a button that arrives late": Case(
        "/drift/late", 'click button "Continue"\nread css "#total" as answer', "£42.00"
    ),
}


def learn(browser: Browser, store: DejoStore, url: str, steps: str) -> None:
    runner = Runner(Session(browser=browser, store=store), task=TASK, store=store)
    outcome = runner.run(program.parse(f"go {url}\n{steps}"))
    assert outcome.ok, outcome.text()


def replay(browser: Browser, store: DejoStore, url: str) -> ReplayResult:
    return Executor(store, browser).run(domain_of(url), task=TASK)


@pytest.mark.parametrize("case", list(CASES.values()), ids=list(CASES))
def test_learned_on_one_visit_replayed_on_the_next(
    browser: Browser, store: DejoStore, demo_server: str, case: Case
) -> None:
    url = f"{demo_server}{case.path}"
    learn(browser, store, url, case.steps)

    result = replay(browser, store, url)

    assert result.ok, result.reason
    assert result.answers == {"answer": case.answer}
    if case.decided:
        assert any(case.decided in line for line in result.decisions), result.decisions
    else:
        assert result.decisions == []


def test_a_second_account_signed_in_stops_before_anything_is_done(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    def signed_in_as(email: str) -> None:
        browser._context.add_cookies([{"name": ACCOUNT_COOKIE, "value": email, "url": demo_server}])

    url = f"{demo_server}/drift/account/home"
    signed_in_as("finance@acme.com")
    learn(browser, store, url, 'read css "#due" as answer')
    signed_in_as("riya@acme.com")

    result = replay(browser, store, url)

    assert result.wrong_account == ("finance@acme.com", "riya@acme.com")
    assert result.answers == {}
