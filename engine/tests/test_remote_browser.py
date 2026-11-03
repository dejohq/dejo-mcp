"""Driving a browser Dejo did not start, over CDP: a cloud browser, or the user's own Chrome."""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from dejo import program
from dejo.browser import Browser, ProfileUnavailable, domain_of
from dejo.executor import Executor
from dejo.operations import Session
from dejo.runner import Runner
from dejo.store import DejoStore

# How long a Chrome started by the test gets to say which port it listens on.
STARTUP_S = 20

_EXECUTABLE = (
    "from playwright.sync_api import sync_playwright\n"
    "with sync_playwright() as p: print(p.chromium.executable_path)"
)


@pytest.fixture
def running_chrome(tmp_path: Path) -> Iterator[str]:
    """A Chrome that someone else started, listening for CDP, as a cloud browser would be."""
    executable = subprocess.run(
        [sys.executable, "-c", _EXECUTABLE], capture_output=True, text=True, check=True
    ).stdout.strip()
    profile = tmp_path / "their-chrome"
    chrome = subprocess.Popen(
        [
            executable,
            "--headless=new",
            "--no-sandbox",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    port_file = profile / "DevToolsActivePort"
    began = time.monotonic()
    while not port_file.is_file() and time.monotonic() - began < STARTUP_S:
        time.sleep(0.1)
    try:
        assert port_file.is_file(), "Chrome never said which port it listens on"
        yield f"http://127.0.0.1:{port_file.read_text().split()[0]}"
    finally:
        chrome.terminate()
        chrome.wait(timeout=STARTUP_S)


def test_a_task_is_learned_and_replayed_in_a_browser_dejo_did_not_start(
    running_chrome: str, demo_server: str, tmp_path: Path
) -> None:
    store = DejoStore(db_path=str(tmp_path / "memory.db"))
    with Browser(cdp_url=running_chrome, downloads=tmp_path / "downloads") as theirs:
        assert theirs.remote
        runner = Runner(Session(browser=theirs, store=store), task="heading", store=store)
        outcome = runner.run(program.parse(f'go {demo_server}/parity\nread css "h1" as h\n'))
        assert outcome.ok and outcome.saved is not None, outcome.text()
        theirs.page.goto("about:blank")
        replayed = Executor(store, theirs).run(domain_of(demo_server), task="heading")
        assert replayed.answers == {"h": "Parity lab"}
    # Dejo only disconnected: the browser it drove is still there for its owner.
    with Browser(cdp_url=running_chrome, downloads=tmp_path / "downloads") as again:
        assert again.page is not None


def test_the_owners_tabs_are_left_as_they_were_and_dejos_own_tab_is_closed(
    running_chrome: str, demo_server: str, tmp_path: Path
) -> None:
    """Dejo works in a tab of its own. The owner's tab keeps its page, and when Dejo stops,
    only the owner's tabs are left."""
    with Browser(cdp_url=running_chrome, downloads=tmp_path / "d") as theirs:
        owners = [tab for tab in theirs.page.context.pages if tab is not theirs.page]
        assert [tab.url for tab in owners] == ["about:blank"]
        theirs.goto(f"{demo_server}/parity")
        assert [tab.url for tab in owners] == ["about:blank"]
    with Browser(cdp_url=running_chrome, downloads=tmp_path / "d") as again:
        left = [tab.url for tab in again.page.context.pages if tab is not again.page]
        assert left == ["about:blank"]


def test_a_browser_that_is_not_there_is_named_with_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(ProfileUnavailable, match="remote-debugging-port"):
        Browser(cdp_url="http://127.0.0.1:9", downloads=tmp_path / "d").start()
