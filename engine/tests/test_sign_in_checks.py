"""Two things a signed-in browser must never get wrong about itself.

1. **Saying a person is signed in when they are not.** `dejo login` and `dejo_login_done`
   used to take "I am done" as proof. Called on Google while the window still sat on the
   identifier page, it answered "Signed in" and wrote that into memory as a fact.
2. **Blaming the website for a broken profile.** A profile went bad and every page in it
   spun forever, while the same Chrome on a fresh profile loaded the site in a second. The
   only symptom was a timeout, which reads exactly like a slow site.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from dejo import browser as browser_module
from dejo.browser import Browser, ProfileStuck

SHORT_MS = 1500


class TestTheWindowIsCheckedBeforeAnyoneIsBelieved:
    def test_a_visible_password_box_is_still_signing_in(self, browser: Browser) -> None:
        browser.page.set_content('<input type="email"><input type="password">')

        assert browser.still_on_sign_in() is True

    def test_a_hidden_password_box_is_not(self, browser: Browser) -> None:
        """Signed-in pages often carry one for a change-password dialog."""
        browser.page.set_content(
            '<h1>Dashboard</h1><div style="display:none"><input type="password"></div>'
        )

        assert browser.still_on_sign_in() is False

    def test_a_sign_in_address_is_still_signing_in(self, browser: Browser, demo_server) -> None:
        """Google's first step asks for an email only, so the address is what gives it
        away: there is no password box yet."""
        browser.page.route("**/signin/identifier*", lambda route: route.fulfill(body="email?"))
        browser.goto(f"{demo_server}/signin/identifier?flow=1")

        assert browser.still_on_sign_in() is True

    def test_a_page_past_the_sign_in_is_done(self, browser: Browser, demo_server) -> None:
        browser.page.route("**/dashboard", lambda route: route.fulfill(body="<h1>Dashboard</h1>"))
        browser.goto(f"{demo_server}/dashboard")

        assert browser.sign_in_window() == (f"{demo_server}/dashboard", False)

    def test_a_closed_window_is_not_mistaken_for_a_signed_in_one(self, browser: Browser) -> None:
        """A closed page still reports its last address. Asked anything else, it would
        read as "no password box here, so signed in"."""
        browser.page.set_content('<input type="password">')
        browser.page.close()

        assert browser.sign_in_window() is None


@pytest.fixture
def silent_address() -> Iterator[str]:
    """An address that accepts a connection and never answers: a site that is down."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        yield f"http://127.0.0.1:{listener.getsockname()[1]}/"


@pytest.fixture
def profiled(tmp_path, monkeypatch) -> Iterator[Browser]:
    monkeypatch.setattr(browser_module, "FRESH_CHECK_MS", SHORT_MS * 4)
    with Browser(headless=True, profile=tmp_path / "profile", timeout_ms=SHORT_MS) as running:
        yield running


class TestAStuckProfileIsToldApartFromADownSite:
    def test_a_profile_where_nothing_loads_is_named(self, profiled: Browser, demo_server) -> None:
        # Every request in this profile hangs, the way they did in the real stuck one.
        profiled.page.context.route("**/*", lambda route: None)

        with pytest.raises(ProfileStuck) as stuck:
            profiled.goto(f"{demo_server}/")

        said = str(stuck.value)
        assert "this profile is stuck" in said
        assert str(profiled._profile) in said, "it must say which folder"
        assert "dejo_profile" in said, "and how to get out of it"

    def test_a_site_that_is_down_everywhere_is_still_a_timeout(
        self, profiled: Browser, silent_address: str
    ) -> None:
        """Blaming the profile for a dead site would send someone to delete their sign-ins
        for nothing."""
        with pytest.raises(PlaywrightTimeout):
            profiled.goto(silent_address)

    def test_a_site_that_answers_with_an_error_page_is_not_loading_fine(
        self, profiled: Browser, demo_server
    ) -> None:
        """mcp.directory, origin down: the profile timed out, the fresh browser got
        Cloudflare's 522 page, counted that as "loads fine", and Dejo told the user to delete
        a profile signed in to about fifteen sites."""
        profiled.page.context.route("**/*", lambda route: None)

        with pytest.raises(PlaywrightTimeout):
            profiled.goto(f"{demo_server}/down")

    def test_one_slow_load_in_the_profile_is_tried_again_before_anything_is_blamed(
        self, profiled: Browser, demo_server
    ) -> None:
        first = []

        def hang_once(route) -> None:
            if not first:
                first.append(route)
                return
            route.continue_()

        profiled.page.context.route("**/news", hang_once)

        profiled.goto(f"{demo_server}/news")

        assert profiled.page.locator("#headline").inner_text() == "Rates hold for September"

    def test_a_stuck_profile_is_not_sent_to_be_deleted_first(
        self, profiled: Browser, demo_server
    ) -> None:
        profiled.page.context.route("**/*", lambda route: None)

        with pytest.raises(ProfileStuck) as stuck:
            profiled.goto(f"{demo_server}/")

        said = str(stuck.value)
        assert said.index("dejo_profile") < said.index("delete"), said
        assert "do not delete it" in said

    def test_without_a_profile_there_is_nothing_to_blame(
        self, tmp_path, silent_address: str
    ) -> None:
        with (
            Browser(headless=True, downloads=tmp_path / "d", timeout_ms=SHORT_MS) as clean,
            pytest.raises(PlaywrightTimeout),
        ):
            clean.goto(silent_address)


class WindowThatChanges:
    """Shows one state per look, the way a real window moves on as a person signs in."""

    def __init__(self, *states: tuple[str, bool] | None) -> None:
        self.states = list(states)

    def sign_in_window(self) -> tuple[str, bool] | None:
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]


class TestTheLoginCommandChecksToo:
    def answers(self, monkeypatch, *typed: str) -> None:
        replies = iter(typed)
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(replies))

    def test_enter_on_a_finished_sign_in_is_enough(self, monkeypatch) -> None:
        from dejo.cli import _wait_until_signed_in

        self.answers(monkeypatch, "")

        assert _wait_until_signed_in(WindowThatChanges(("https://a.com/home", False))) == (
            "https://a.com/home"
        )

    def test_enter_too_early_is_caught_and_asked_again(self, monkeypatch, capsys) -> None:
        from dejo.cli import _wait_until_signed_in

        self.answers(monkeypatch, "", "")
        window = WindowThatChanges(("https://a.com/login", True), ("https://a.com/home", False))

        assert _wait_until_signed_in(window) == "https://a.com/home"
        assert "still shows a sign-in page" in capsys.readouterr().out

    def test_the_person_can_say_yes(self, monkeypatch) -> None:
        from dejo.cli import _wait_until_signed_in

        self.answers(monkeypatch, "", "yes")

        assert _wait_until_signed_in(WindowThatChanges(("https://a.com/auth/ok", True))) == (
            "https://a.com/auth/ok"
        )

    def test_a_closed_window_is_reported_not_believed(self, monkeypatch) -> None:
        from dejo.cli import _wait_until_signed_in

        self.answers(monkeypatch, "")

        assert _wait_until_signed_in(WindowThatChanges(None)) is None
