"""A button inside an iframe, learned after the browser has navigated, must replay.

Found by the 20 Oct 2026 lab on real pages. Once a page has navigated, Playwright numbers
the main page's refs too (`f3e2` for a plain button) and the frame's refs differently again
(`f4e2`). Dejo read that number as "which iframe", so the button inside the frame was
recorded with no frame at all, and a stored locator with no frame finds nothing:
`page.locator` does not look inside iframes. The trail saved fine and could never replay.
"""

from __future__ import annotations

from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.operations import Session
from dejo.store import DejoStore

TASK = "pay at checkout and read the status"


def element_named(session: Session, name: str) -> dict:
    for element in session.look()["elements"]:
        if element["name"] == name:
            return element
    raise AssertionError(f"no control named {name!r}")


def learn(session: Session, demo_server: str) -> None:
    # Two navigations first: the first page alone does not show the bug.
    session.act("open the billing portal", "goto", value=f"{demo_server}/")
    session.act("open the checkout", "goto", value=f"{demo_server}/checkout")
    pay = element_named(session, "Pay now")
    session.act("press pay in the card widget", "click", ref=pay["ref"])
    session.read("text", ref="#status", remember=True, intent="read the payment status")


def test_the_button_in_the_frame_knows_its_frame(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    session = Session(browser=browser, store=store)
    session.act("open the billing portal", "goto", value=f"{demo_server}/")
    session.act("open the checkout", "goto", value=f"{demo_server}/checkout")

    pay = element_named(session, "Pay now")

    assert pay["ref"] == "f1" + pay["ref"][pay["ref"].index("e") :], "a frame ref, numbered by Dejo"
    assert pay.get("frame"), "the element lost its iframe after a navigation"


def test_a_step_inside_a_frame_learned_after_navigating_replays(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    session = Session(browser=browser, store=store)
    learn(session, demo_server)
    assert browser.page.locator("#status").inner_text() == "Paid", "the click did not land"
    session.save(TASK)

    result = Executor(store, browser).run(domain_of(demo_server), task=TASK)

    assert result.ok, result
    assert result.answers["read the payment status"] == "Paid"
