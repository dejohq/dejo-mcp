"""An old frameset page, with no body at all, can be looked at and worked in.

Such a page is only `<frameset>` and `<frame>`s. Every look asked Playwright to describe the
body, and on this page that failed with "Selector body does not match any element", so the
agent saw an error instead of the page (the-internet.herokuapp.com/nested_frames, in the
reliability benchmark on 2 Nov 2026).
"""

from __future__ import annotations

from dejo import program
from dejo.browser import Browser
from dejo.operations import Session
from dejo.runner import Runner
from dejo.store import DejoStore


def runner_for(browser: Browser, store: DejoStore) -> Runner:
    return Runner(Session(browser=browser, store=store), task="the deep text", store=store)


def test_a_frameset_page_is_drawn_with_what_its_frames_hold(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = runner_for(browser, store).run(program.parse(f"go {demo_server}/frameset\nlook\n"))
    assert outcome.ok, outcome.text()
    assert "Deep inside" in outcome.text()


def test_a_read_inside_a_frameset_frame_works(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = runner_for(browser, store).run(
        program.parse(f'go {demo_server}/frameset\nread css "#deep" as deep\n')
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers["deep"] == "Deep inside"
