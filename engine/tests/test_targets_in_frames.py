"""A target that names something inside an iframe finds it there, and so does its replay.

The view draws the inside of every iframe, and Playwright MCP's refs reach into them, but a
`css`, `role` or `text` target only ever looked at the page itself. An editor, a date picker
or a widget demo inside an iframe was drawn, and then "nothing on this page" was all a
target found there: 6 of the 50 real-site tasks in the reliability benchmark (2 Nov 2026).
"""

from __future__ import annotations

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.operations import Session
from dejo.runner import Outcome, Runner
from dejo.store import DejoStore


def run(browser: Browser, store: DejoStore, text: str, task: str) -> Outcome:
    runner = Runner(Session(browser=browser, store=store), task=task, store=store)
    return runner.run(program.parse(text))


def test_a_css_target_fills_and_reads_a_field_inside_an_iframe(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = run(
        browser,
        store,
        f'go {demo_server}/framed\nfill css "#city" "Lagos"\nread value css "#city" as city\n',
        "type a city",
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers["city"] == "Lagos"


def test_a_role_target_reads_a_heading_inside_an_iframe(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = run(
        browser,
        store,
        f'go {demo_server}/framed\nread heading "Inside the frame" as heading\n',
        "the frame heading",
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers["heading"] == "Inside the frame"


def test_a_target_is_found_in_a_frame_inside_a_frame(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = run(
        browser, store, f'go {demo_server}/framed\nread css "#deep" as deep\n', "the deep text"
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers["deep"] == "Deep inside"


def test_a_trail_that_works_inside_frames_replays(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    task = "the cities"
    outcome = run(
        browser,
        store,
        f'go {demo_server}/framed\nclick link "Show the city list"\nread css "#cities" as cities\n',
        task,
    )
    assert outcome.saved is not None, outcome.text()
    assert outcome.answers["cities"] == "Lagos, Lima"

    replay = Executor(store, browser).run(domain_of(demo_server), task=task)
    assert replay.ok, replay
    assert replay.answers["cities"] == "Lagos, Lima"


def test_the_deep_read_replays_from_memory(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    task = "the deep text"
    outcome = run(browser, store, f'go {demo_server}/framed\nread css "#deep" as deep\n', task)
    assert outcome.saved is not None, outcome.text()

    replay = Executor(store, browser).run(domain_of(demo_server), task=task)
    assert replay.ok, replay
    assert replay.answers["deep"] == "Deep inside"


def test_the_page_itself_is_searched_before_its_frames(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = run(
        browser, store, f'go {demo_server}/framed\nread heading "Framed" as title\n', "title"
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers["title"] == "Framed"
