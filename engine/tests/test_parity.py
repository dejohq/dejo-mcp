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


# ----------------------------------------------------------------------------- tabs


def test_closing_a_tab_and_listing_tabs_replay(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    task = "close the books tab"
    outcome = learn(
        browser,
        store,
        task,
        f"go {demo_server}/parity\n"
        'click link "Open the books in a new tab"\n'
        "tab latest\n"
        "read tabs as before\n"
        "tab close\n"
        "read tabs as after\n",
    )
    assert len(outcome.answers["before"].split(", ")) == 2
    assert outcome.answers["after"].endswith("/parity (in use)")
    result = replay(browser, store, demo_server, task)
    assert browser.page.url.endswith("/parity")
    assert not any("/books" in tab for tab in result.answers["after"])


# ---------------------------------------------------------------------------- emulation

SETTINGS = (
    'click button "Show settings"\n'
    'wait "text:settings shown"\n'
    'read css "#size" as size\n'
    'read css "#tz" as zone\n'
    'read css "#lang" as language\n'
    'read css "#scheme" as scheme\n'
    'read css "#online" as online\n'
)


def test_emulating_another_browser_is_kept_and_replayed(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    task = "the page in Tokyo"
    wanted = {
        "size": "500x700",
        "zone": "Asia/Tokyo",
        "language": "de-DE",
        "scheme": "dark",
        "online": "offline",
    }
    outcome = learn(
        browser,
        store,
        task,
        f"go {demo_server}/parity\n"
        "emulate viewport 500x700\n"
        "emulate timezone Asia/Tokyo\n"
        "emulate locale de-DE\n"
        "emulate color dark\n"
        "emulate offline on\n" + SETTINGS,
    )
    assert outcome.answers == wanted
    browser.clear_emulation()
    assert replay(browser, store, demo_server, task).answers == wanted


def test_a_replay_starts_from_the_browser_as_it_is(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """A trail that emulated nothing must not run in the time zone the last one set."""
    learn(browser, store, "settings", f"go {demo_server}/parity\n" + SETTINGS)
    browser.emulate("timezone Asia/Tokyo")
    browser.emulate("offline on")
    answers = replay(browser, store, demo_server, "settings").answers
    assert answers["zone"] != "Asia/Tokyo"
    assert answers["online"] == "online"


def test_a_phone_a_slow_network_a_slow_computer_and_a_place(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    task = "the page on a phone"
    outcome = learn(
        browser,
        store,
        task,
        f"go {demo_server}/parity\n"
        'emulate device "iPhone 13"\n'
        "emulate network fast3g\n"
        "emulate cpu 2\n"
        "emulate geolocation 18.52,73.85\n"
        'click button "Show settings"\n'
        "wait text:18.52\n"
        'read css "#mobile" as mobile\n'
        'read css "#where" as where\n',
    )
    assert outcome.answers == {"mobile": "mobile", "where": "18.52,73.85"}
    assert browser.emulating["device"] == "iPhone 13"
    assert replay(browser, store, demo_server, task).answers == outcome.answers


def test_no_network_makes_the_page_s_own_requests_fail(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = learn(
        browser,
        store,
        "load with no network",
        f"go {demo_server}/parity\n"
        "emulate network offline\n"
        'click button "Load data"\n'
        "wait 1\n"
        'read requests "/parity/data" as calls\n',
    )
    assert "ERR_INTERNET_DISCONNECTED" in outcome.answers["calls"]


# ------------------------------------------------------- cookies, storage, sign-in state


def test_cookies_and_storage_are_read_and_a_read_of_them_replays(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    task = "what the page keeps"
    outcome = learn(
        browser,
        store,
        task,
        f"go {demo_server}/parity\n"
        'read cookies "flavour" as cookies\n'
        'read storage "theme" as theme\n',
    )
    assert outcome.answers == {"cookies": "flavour=ginger (127.0.0.1)", "theme": "green"}
    assert replay(browser, store, demo_server, task).answers["theme"] == "green"


def test_setting_and_clearing_cookies_and_storage_is_done_but_not_kept(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """A cookie's value is often a sign-in. The reply says the line is not kept, and why."""
    outcome = learn(
        browser,
        store,
        "change what the page keeps",
        f"go {demo_server}/parity\n"
        'cookie set colour "blue"\n'
        'storage set theme "red"\n'
        "cookie clear flavour\n"
        "read cookies as cookies\n"
        'read storage "theme" as theme\n',
    )
    assert outcome.answers["theme"] == "red"
    assert "colour=blue" in outcome.answers["cookies"]
    assert "flavour" not in outcome.answers["cookies"]
    assert "is not kept in the trail, because a cookie's value is often a sign-in" in outcome.text()
    assert outcome.saved is not None
    assert [step.action for step in outcome.saved.steps] == ["goto", "read", "read"]


def test_a_saved_state_is_written_to_a_file_and_loads_back(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The way a sign-in moves to another machine, or comes from another tool: Playwright's
    own storage-state file, written by name, loaded by name or by path."""
    runner = Runner(Session(browser=browser, store=store), task="keep it", store=store)
    saved = browser.states / "team.json"
    outcome = runner.run(program.parse(f"go {demo_server}/parity\nstate save team\n"))
    assert f"saved to {saved}" in outcome.text()
    assert "flavour" in saved.read_text()
    outcome = runner.run(
        program.parse(
            "cookie clear\n"
            "storage clear\n"
            f'state load "{saved}"\n'
            f"go {demo_server}/blank\n"
            'read cookies "flavour" as cookies\n'
            'read storage "theme" as theme\n'
        )
    )
    assert outcome.answers == {"cookies": "flavour=ginger (127.0.0.1)", "theme": "green"}
