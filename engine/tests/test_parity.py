"""What other browser tools can do, done by Dejo on the parity page, learned AND replayed.

A capability only counts when it survives memory: a trail that uses it is saved, and the
replay does it again with no model involved. So almost every test here learns a short
program on `/parity` and then replays it, and checks the page shows the step really ran.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.demo_site.parity import DATA

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor, ReplayResult
from dejo.operations import Session
from dejo.runner import Outcome, Runner
from dejo.store import DejoStore

# How every PNG file starts.
PNG = b"\x89PNG"


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


# ------------------------------------------------------------------------------ dialogs


def test_a_dismissed_confirm_box_is_dismissed_again_on_replay(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Dejo accepts every box unless told. Told to cancel one, the trail keeps the choice."""
    outcome = learn(
        browser,
        store,
        "keep the draft",
        f"go {demo_server}/parity\n"
        "dialog dismiss\n"
        'click button "Reset draft"\n'
        'read css "#log" as log\n',
    )
    assert outcome.answers == {"log": "kept"}
    assert "dismissed it" in outcome.text()
    assert replay(browser, store, demo_server, "keep the draft").answers == {"log": "kept"}


def test_an_answer_typed_into_a_prompt_is_typed_again_on_replay(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = learn(
        browser,
        store,
        "give my name",
        f"go {demo_server}/parity\n"
        'dialog accept "Rohit"\n'
        'click button "Ask my name"\n'
        'read css "#log" as log\n',
    )
    assert outcome.answers == {"log": "name: Rohit"}
    assert replay(browser, store, demo_server, "give my name").answers == {"log": "name: Rohit"}


def test_the_words_of_an_alert_can_be_read_and_replayed(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = learn(
        browser,
        store,
        "what the save says",
        f'go {demo_server}/parity\nclick button "Save"\nread dialog as said\n',
    )
    assert outcome.answers == {"said": "Saved!"}
    assert replay(browser, store, demo_server, "what the save says").answers == {"said": "Saved!"}


# ------------------------------------------------------------------ screenshots and PDF


def test_a_screenshot_is_kept_and_a_new_one_is_taken_on_every_replay(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = learn(
        browser,
        store,
        "picture of the chart",
        f'go {demo_server}/parity\nscreenshot css "#chart" as chart\n',
    )
    first = Path(outcome.answers["chart"])
    assert first.is_file() and first.read_bytes().startswith(PNG)
    again = Path(replay(browser, store, demo_server, "picture of the chart").answers["chart"])
    assert again.is_file() and again != first, "a replay must take a new picture"


def test_a_whole_page_screenshot_and_a_pdf(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = learn(
        browser,
        store,
        "keep the page",
        f"go {demo_server}/parity\nscreenshot full as page\npdf as printout\n",
    )
    assert Path(outcome.answers["page"]).read_bytes().startswith(PNG)
    assert Path(outcome.answers["printout"]).read_bytes().startswith(b"%PDF")
    result = replay(browser, store, demo_server, "keep the page")
    assert Path(result.answers["printout"]).read_bytes().startswith(b"%PDF")


def test_pictures_are_kept_beside_the_downloads(browser: Browser, tmp_path: Path) -> None:
    """Everything Dejo writes lives in one folder: ~/.dejo, or wherever downloads were sent."""
    assert browser.captures == tmp_path / "captures"


# ------------------------------------------------------------------------------ network


def test_waiting_for_a_response_then_reading_it_replays(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The page fills itself in from its own API a moment after the click. Waiting for that
    answer is the real wait; reading the answer itself gives the data without the page."""
    task = "the weather data"
    outcome = learn(
        browser,
        store,
        task,
        f"go {demo_server}/parity\n"
        'click button "Load slowly"\n'
        "wait response:/parity/slow-data\n"
        'read response "/parity/slow-data" as data\n'
        'read css "#log" as log\n',
    )
    assert json.loads(outcome.answers["data"]) == DATA
    assert outcome.answers["log"] == "weather: Pune 31"
    result = replay(browser, store, demo_server, task)
    assert json.loads(result.answers["data"]) == DATA
    assert result.answers["log"] == "weather: Pune 31"


def test_the_requests_and_console_of_a_page_can_be_read(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    task = "what the page asked for"
    outcome = learn(
        browser,
        store,
        task,
        f"go {demo_server}/parity\n"
        'click button "Ask for nothing"\n'
        "wait request:/parity/missing\n"
        'click button "Talk"\n'
        'read requests "/parity/missing" as calls\n'
        "read console as said\n",
    )
    assert re.search(r"GET (404|waiting) http://\S+/parity/missing", outcome.answers["calls"])
    assert "log: hello from the page" in outcome.answers["said"]
    result = replay(browser, store, demo_server, task)
    assert len(result.answers["calls"]) == 1, "only this page's requests, not the last page's"
    assert "/parity/missing" in result.answers["calls"][0]


# ------------------------------------------------------------------ mouse and keyboard


def centre_of(browser: Browser, demo_server: str, selector: str) -> tuple[int, int]:
    """Where an element sits on the screen, read before learning, as an agent reads it off
    `look image`. The window is always the same size, so the spot is the same on replay."""
    browser.page.goto(f"{demo_server}/parity")
    box = browser.page.locator(selector).bounding_box()
    assert box is not None
    return round(box["x"] + box["width"] / 2), round(box["y"] + box["height"] / 2)


def corner_of(browser: Browser, demo_server: str, selector: str) -> tuple[int, int]:
    browser.page.goto(f"{demo_server}/parity")
    box = browser.page.locator(selector).bounding_box()
    assert box is not None
    return round(box["x"]), round(box["y"])


def test_a_click_at_a_place_on_a_canvas_replays(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """A chart has nothing inside it to name: only the place clicked says what was hit."""
    left, top = corner_of(browser, demo_server, "#chart")
    x, y = left + 100, top + 60  # inside the red box the chart draws at 50-150, 30-90
    learn(
        browser,
        store,
        "hit the box",
        f'go {demo_server}/parity\nmouse click {x} {y}\nread css "#log" as log\n',
    )
    assert replay(browser, store, demo_server, "hit the box").answers == {"log": "hit the box"}


def test_a_click_at_a_spot_on_an_element_replays(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    learn(
        browser,
        store,
        "miss the box",
        f'go {demo_server}/parity\nclick css "#chart" at=10,10\nread css "#log" as log\n',
    )
    assert replay(browser, store, demo_server, "miss the box").answers == {"log": "missed the box"}


def test_a_right_click_and_a_click_with_shift_held_replay(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = learn(
        browser,
        store,
        "right and shift",
        f"go {demo_server}/parity\n"
        'click css "#menu-zone" button=right\n'
        'read css "#log" as first\n'
        'click button "Shift me" keys=Shift\n'
        'read css "#log" as second\n'
        "keydown Shift\n"
        'click button "Shift me"\n'
        "keyup Shift\n"
        'read css "#log" as third\n',
    )
    wanted = {"first": "right clicked", "second": "shift clicked", "third": "shift clicked"}
    assert outcome.answers == wanted
    assert replay(browser, store, demo_server, "right and shift").answers == wanted


def test_typing_speed_is_kept(browser: Browser, store: DejoStore, demo_server: str) -> None:
    learn(
        browser,
        store,
        "type slowly",
        f'go {demo_server}/parity\ntype label "Keys" "abcd" delay=150\nread css "#gaps" as gaps\n',
    )
    gaps = replay(browser, store, demo_server, "type slowly").answers["gaps"]
    assert int(gaps.split()[-1]) >= 120, gaps


def test_a_mouse_drag_between_two_places_replays(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    x, y = centre_of(browser, demo_server, "#drag")
    to_x, to_y = centre_of(browser, demo_server, "#zone")
    learn(
        browser,
        store,
        "drag by hand",
        f'go {demo_server}/parity\nmouse drag {x} {y} to {to_x} {to_y}\nread css "#log" as log\n',
    )
    assert replay(browser, store, demo_server, "drag by hand").answers == {"log": "dropped"}


# --------------------------------------------------------------- scrolling inside a box


def test_scrolling_inside_one_element_replays(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """A list in its own box scrolls while the page stays still: the page scroll cannot
    reach it, and `scroll T` only brings the box into view."""
    learn(
        browser,
        store,
        "scroll the box",
        f"go {demo_server}/parity\n"
        'scroll css "#scroller" down 300\n'
        'scroll css "#scroller" right 120\n'
        'read css "#scrolled" as at\n',
    )
    assert replay(browser, store, demo_server, "scroll the box").answers == {"at": "120,300"}
