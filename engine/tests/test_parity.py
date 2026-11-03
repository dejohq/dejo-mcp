"""What other browser tools can do, done by Dejo on the parity page, learned AND replayed.

A capability only counts when it survives memory: a trail that uses it is saved, and the
replay does it again with no model involved. So almost every test here learns a short
program on `/parity` and then replays it, and checks the page shows the step really ran.
"""

from __future__ import annotations

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor, ReplayResult
from dejo.operations import Session
from dejo.runner import Outcome, Runner
from dejo.store import DejoStore


def learn(browser: Browser, store: DejoStore, task: str, text: str) -> Outcome:
    """Run one program as a new task, and insist it was saved."""
    runner = Runner(Session(browser=browser, store=store), task=task, store=store)
    outcome = runner.run(program.parse(text))
    assert outcome.ok, outcome.text()
    assert outcome.saved is not None, outcome.text()
    return outcome


def replay(browser: Browser, store: DejoStore, site: str, task: str) -> ReplayResult:
    """Replay a saved task from a blank tab, so nothing left over from learning helps."""
    browser.page.goto("about:blank")
    result = Executor(store, browser).run(domain_of(site), task=task)
    assert result.ok, result.reason
    return result


# ------------------------------------------------------------------------ drag and tabs


def test_a_drag_onto_another_element_replays(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The element dropped ONTO used to be forgotten, so replay dragged onto nothing."""
    learn(
        browser,
        store,
        "drop the card",
        f'go {demo_server}/parity\ndrag css "#drag" to css "#zone"\nread css "#log" as log\n',
    )
    assert replay(browser, store, demo_server, "drop the card").answers == {"log": "dropped"}


def test_a_step_into_a_new_tab_replays(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """`tab latest` was saved and then could not be done on replay at all."""
    learn(
        browser,
        store,
        "the books in the new tab",
        f"go {demo_server}/parity\n"
        'click link "Open the books in a new tab"\n'
        "tab latest\n"
        'read css "h1" as heading\n',
    )
    result = replay(browser, store, demo_server, "the books in the new tab")
    assert result.answers == {"heading": "Books"}
    assert browser.page.url.endswith("/books")
