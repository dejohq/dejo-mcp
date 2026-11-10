"""Every choice a replay makes on its own is reported, in the result and in the step log.

Self-healing that nobody hears about hides real breakage: a site that moved its button
every week would look perfectly healthy. So a step skipped, a pop-up cleared, a known pop-up
cleared up front, a sign-in skipped, or a backup way of finding an element is one line in
`ReplayResult.decisions` and in `~/.dejo/logs`, and nothing that changes what ran is silent.
"""

from __future__ import annotations

from tests.conftest import TASK, cold_run

from dejo import program, steplog
from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.operations import Session
from dejo.runner import Runner
from dejo.store import DejoStore


def logged() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in steplog.folder().glob("*.log"))


def learn_the_price(browser: Browser, store: DejoStore, url: str, first: str = "") -> None:
    runner = Runner(Session(browser=browser, store=store), task="the price", store=store)
    outcome = runner.run(
        program.parse(f'go {url}\n{first}click button "Show the price"\nread css "#price" as p')
    )
    assert outcome.ok, outcome.text()


def test_a_backup_way_of_finding_an_element_is_reported(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The button's words and class change on the next visit and its id stays: the ways by
    its words miss, its id finds it, and that is said rather than passed off as nothing."""
    url = f"{demo_server}/drift/button"
    runner = Runner(Session(browser=browser, store=store), task="the total", store=store)
    outcome = runner.run(
        program.parse(f'go {url}\nclick button "Show total"\nread css "#total" as total')
    )
    assert outcome.ok, outcome.text()

    result = Executor(store, browser).run(domain_of(url), task="the total")

    assert result.ok, result.reason
    assert result.answers == {"total": "£31.40"}
    backups = [line for line in result.decisions if "found by a backup way" in line]
    assert backups and backups[0].startswith("step 2: "), result.decisions
    assert "role:button|Show total" in backups[0] and "missed and moved down" in backups[0]
    assert "decided on its own: found by a backup way" in logged()


def test_pop_ups_cleared_new_and_known_are_reported(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    url = f"{demo_server}/drift/newsletter"
    learn_the_price(browser, store, url)

    first = Executor(store, browser).run(domain_of(url), task="the price")
    again = Executor(store, browser).run(domain_of(url), task="the price")

    assert first.decisions == [
        'step 2: cleared a pop-up: "Join our newsletter" closed by its "No thanks" control; '
        "cleared up front from now on"
    ]
    assert len(again.decisions) == 1 and "cleared a known pop-up" in again.decisions[0]
    log = logged()
    assert "step 2 cleared a pop-up" in log
    assert "decided on its own: cleared a known pop-up" in log


def test_a_skipped_step_is_in_the_list_and_the_log(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    url = f"{demo_server}/drift/toast?kind=plain"
    learn_the_price(browser, store, url, first='click button "Close"\n')

    result = Executor(store, browser).run(domain_of(url), task="the price")

    assert result.ok, result.reason
    assert result.decisions == [
        'step 2: skipped (click button "Close"): it only clears something away, that was not '
        "on the page this time"
    ]
    assert 'decided on its own: step 2: skipped (click button "Close")' in logged()


def test_a_replay_that_decided_nothing_says_nothing(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    session = Session(browser, store)
    cold_run(session, demo_server)
    session.save(TASK, domain=domain_of(demo_server))

    result = Executor(store, browser).run(domain_of(demo_server), task=TASK)

    assert result.ok, result.reason
    assert result.decisions == []
