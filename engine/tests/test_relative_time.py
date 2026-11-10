"""A task that names a time relative to today must not replay the date it was learned on.

"Download this month's invoice", learned in September, clicks "September 2026". Asked in
October, a replay that clicks "September 2026" again passes every check and hands back the
wrong month's invoice. The task's words say "this month", and the trail holds a fixed one:
Dejo aims the route at the month the words mean now, or stops and says which it could not.

`/safety/months` draws its links from the browser's own clock, and `set_time` moves it.
"""

from __future__ import annotations

import pytest

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.operations import Session
from dejo.runner import Runner
from dejo.store import DejoStore

# Replays here use the browser's own clock, moved by set_time, not the demo's calendar.
pytestmark = pytest.mark.own_clock

LEARNED_ON = "2026-09-15T10:00:00"
NEXT_MONTH = "2026-10-15T10:00:00"
NEXT_YEAR = "2027-01-15T10:00:00"


def learn(browser: Browser, store: DejoStore, demo_server: str, task: str, month: str) -> None:
    browser.set_time(LEARNED_ON)
    runner = Runner(Session(browser=browser, store=store), task=task, store=store)
    outcome = runner.run(
        program.parse(
            f"go {demo_server}/safety/months\n"
            f'click link "{month}"\n'
            'read css "#month" as month\n'
            'read css "#amount" as amount'
        )
    )
    assert outcome.ok, outcome.text()


def replay(browser: Browser, store: DejoStore, demo_server: str, task: str, when: str):
    browser.set_time(when)
    browser.goto("about:blank")
    return Executor(store, browser).run(domain_of(demo_server), task=task)


@pytest.mark.parametrize(
    ("task", "learned", "when", "meant"),
    [
        ("download this month's invoice", "September 2026", NEXT_MONTH, "October 2026"),
        ("download last month's invoice", "August 2026", NEXT_MONTH, "September 2026"),
        ("download the latest invoice", "September 2026", NEXT_MONTH, "October 2026"),
        ("download the current invoice", "September 2026", NEXT_YEAR, "January 2027"),
    ],
)
def test_a_relative_time_is_never_replayed_as_the_old_date(
    browser: Browser, store: DejoStore, demo_server: str, task, learned, when, meant
) -> None:
    learn(browser, store, demo_server, task, learned)

    later = replay(browser, store, demo_server, task, when)

    if later.ok:
        assert later.answers["month"] == f"Invoice for {meant}", later.answers
        assert any(meant in line for line in later.decisions), later.decisions
    else:
        assert learned in later.reason and meant in later.reason, later.reason


def test_the_same_month_replays_as_learned(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    task = "download this month's invoice"
    learn(browser, store, demo_server, task, "September 2026")

    again = replay(browser, store, demo_server, task, "2026-09-28T10:00:00")

    assert again.ok, again.reason
    assert again.answers["month"] == "Invoice for September 2026"
    assert again.decisions == []


def test_asking_for_last_month_is_not_answered_with_this_month(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Saved as "this month", asked as "last month": the same words but one, and that one
    is the whole question."""
    learn(browser, store, demo_server, "download this month's invoice", "September 2026")

    later = replay(browser, store, demo_server, "download last month's invoice", LEARNED_ON)

    if later.ok:
        assert later.answers["month"] == "Invoice for August 2026", later.answers
    else:
        assert "August 2026" in later.reason, later.reason


def test_a_task_that_names_its_month_is_never_moved(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """ "the September invoice" means September in any month."""
    task = "download the September 2026 invoice"
    learn(browser, store, demo_server, task, "September 2026")

    later = replay(browser, store, demo_server, task, NEXT_MONTH)

    assert later.ok, later.reason
    assert later.answers["month"] == "Invoice for September 2026"


def test_an_aimed_month_never_writes_over_the_trail(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    task = "download this month's invoice"
    learn(browser, store, demo_server, task, "September 2026")

    replay(browser, store, demo_server, task, NEXT_MONTH)

    kept = store.load_playbook(domain_of(demo_server), task)
    assert kept is not None
    assert any(
        locator.value.endswith("September 2026") for step in kept.steps for locator in step.locators
    ), "the trail itself still holds the month it was learned on"
