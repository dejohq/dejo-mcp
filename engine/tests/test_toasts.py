"""A step that closes a toast, on visits where the toast is different.

`/drift/toast` runs a three-visit cycle: the toast is on show (visit 1, where the trail is
learned), not there at all (visit 2), there but already faded out by itself (visit 3), and on
show again (visit 4). A step that only closed the toast is skipped when there is nothing to
close, said in the reply, and pressed when the toast is back. A step with its own check is
never skipped.
"""

from __future__ import annotations

import pytest

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.operations import Session
from dejo.runner import Runner
from dejo.store import DejoStore

TASK = "the price"
CLOSE = 'step 2 (click button "Close")'


def learn(browser: Browser, store: DejoStore, url: str, *, check: str = "") -> None:
    runner = Runner(Session(browser=browser, store=store), task=TASK, store=store)
    outcome = runner.run(
        program.parse(
            f'go {url}\nclick button "Close"\n{check}'
            'click button "Show the price"\nread css "#price" as price'
        )
    )
    assert outcome.ok, outcome.text()


def replay(browser: Browser, store: DejoStore, url: str):
    return Executor(store, browser).run(domain_of(url), task=TASK)


@pytest.mark.parametrize("kind", ["plain", "fade", "say"])
def test_a_toast_close_is_skipped_when_the_toast_is_not_there(
    browser: Browser, store: DejoStore, demo_server: str, kind: str
) -> None:
    """fade: Playwright calls an element at opacity 0 visible, so the close looked as if it
    did nothing. say: "Dismissed" was taken for words the press gained on the page."""
    url = f"{demo_server}/drift/toast?kind={kind}"
    learn(browser, store, url)
    trail = store.load_playbook(domain_of(url), TASK)
    assert trail is not None and trail.steps[1].clears_away, f"{kind}: not seen as a close"

    absent = replay(browser, store, url)
    assert absent.ok, absent.reason
    assert absent.skipped == [CLOSE]
    assert absent.answers == {"price": "£12 a month"}


@pytest.mark.parametrize("kind", ["plain", "say"])
def test_a_toast_that_faded_out_by_itself_is_not_pressed(
    browser: Browser, store: DejoStore, demo_server: str, kind: str
) -> None:
    """Visit 3: the toast is in the page and already faded out. Nobody can see it, so there
    is nothing to close."""
    url = f"{demo_server}/drift/toast?kind={kind}"
    learn(browser, store, url)
    replay(browser, store, url)  # visit 2

    faded = replay(browser, store, url)

    assert faded.ok, faded.reason
    assert faded.skipped == [CLOSE]


def test_a_toast_on_show_again_is_closed_by_its_step(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    url = f"{demo_server}/drift/toast?kind=fade"
    learn(browser, store, url)
    for _ in range(2):
        replay(browser, store, url)  # visits 2 and 3

    shown = replay(browser, store, url)

    assert shown.ok, shown.reason
    assert shown.skipped == []
    # It fades over 0.2 s, so wait for the fade rather than read it half way.
    browser.page.wait_for_function("getComputedStyle(toast).opacity === '0'", timeout=2000)


def test_a_close_with_its_own_check_is_never_skipped(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    url = f"{demo_server}/drift/toast?kind=plain"
    learn(browser, store, url, check='expect gone css "#toast"\n')

    absent = replay(browser, store, url)

    assert not absent.ok
    assert absent.skipped == []
    assert absent.repair is not None and absent.repair.step_index == 2
