"""The browser context: permissions, position, tabs, and one place for patience.

Most of Playwright's `BrowserContext` is deliberately absent — cookies and storage are
already handled by keeping a whole browser profile, which is stronger than replaying a
saved blob. What is here is the short list that changes whether a real site works at all.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator

import pytest

from dejo import actions
from dejo.browser import GEOLOCATION, Browser
from dejo.waits import DEFAULT_WAIT_MS

# Asks for a permission the moment it loads, then reports what it was told.
ASKS = """
<!doctype html>
<title>permission</title>
<p id="log">asking…</p>
<script>
  Notification.requestPermission().then(state => {
    document.getElementById('log').textContent = 'notifications:' + state;
  });
</script>
"""

WHERE = """
<!doctype html>
<title>where am I</title>
<p id="log">locating…</p>
<script>
  navigator.geolocation.getCurrentPosition(
    pos => {
      document.getElementById('log').textContent =
        pos.coords.latitude.toFixed(2) + ',' + pos.coords.longitude.toFixed(2);
    },
    err => { document.getElementById('log').textContent = 'denied'; }
  );
</script>
"""


@pytest.fixture
def located(tmp_path) -> Iterator[Browser]:
    """A browser that has been told where it is. Kolkata."""
    with Browser(
        headless=True,
        downloads=tmp_path / "downloads",
        geolocation=(22.57, 88.36),
    ) as running:
        yield running


# ------------------------------------------------------------- permissions


def test_nothing_is_granted_by_default(browser: Browser) -> None:
    """A site asking for notifications puts a prompt over the page, and a prompt over the
    page blocks everything behind it. Denying is silent, and an unattended agent needs
    silence rather than a dialog nobody is there to answer."""
    assert browser.permissions == []


def test_a_permission_request_is_refused_without_blocking(browser: Browser) -> None:
    browser.page.set_content(ASKS)
    browser.page.wait_for_function(
        "document.getElementById('log').textContent !== 'asking…'", timeout=5000
    )
    assert browser.page.locator("#log").inner_text() == "notifications:denied"


def test_a_permission_can_be_granted_when_a_site_genuinely_needs_one(tmp_path) -> None:
    with Browser(
        headless=True, downloads=tmp_path / "downloads", permissions=["notifications"]
    ) as allowed:
        assert allowed.permissions == ["notifications"]


# ------------------------------------------------------------- geolocation


def test_geolocation_grants_its_own_permission(located: Browser) -> None:
    """Granting geolocation without also setting a position makes a site wait forever for
    a fix that never arrives, so the two always travel together."""
    assert GEOLOCATION in located.permissions


def test_a_site_is_told_where_it_is(located: Browser, demo_server: str) -> None:
    # Chrome only hands out a position on a secure origin, and `about:blank` is not one.
    # 127.0.0.1 counts as secure, so the demo server is a real origin to ask from.
    located.page.goto(f"{demo_server}/")
    located.page.set_content(WHERE)
    located.page.wait_for_function(
        "document.getElementById('log').textContent !== 'locating…'", timeout=5000
    )
    assert located.page.locator("#log").inner_text() == "22.57,88.36"


def test_location_is_refused_when_none_was_set(browser: Browser, demo_server: str) -> None:
    browser.page.goto(f"{demo_server}/")
    browser.page.set_content(WHERE)
    browser.page.wait_for_function(
        "document.getElementById('log').textContent !== 'locating…'", timeout=5000
    )
    assert browser.page.locator("#log").inner_text() == "denied"


# ----------------------------------------------------------------- patience


def test_there_is_one_timeout(browser: Browser) -> None:
    assert browser.timeout_ms == DEFAULT_WAIT_MS


def test_patience_can_be_changed_for_a_slow_site(browser: Browser) -> None:
    browser.set_timeout(2000)
    assert browser.timeout_ms == 2000


def test_the_timeout_actually_applies(browser: Browser) -> None:
    """If the default were ignored, a missing element would hang for Playwright's own 30
    seconds instead of giving up when we said to."""
    from playwright.sync_api import TimeoutError as PWTimeout

    browser.set_timeout(400)
    browser.page.set_content("<p>nothing here</p>")
    with pytest.raises(PWTimeout):
        browser.page.locator("#never").click()


def test_a_slow_timeout_can_be_set_at_launch(tmp_path) -> None:
    with Browser(headless=True, downloads=tmp_path / "downloads", timeout_ms=45000) as patient:
        assert patient.timeout_ms == 45000


# --------------------------------------------------------------------- tabs


def test_new_tab(browser: Browser, demo_server: str) -> None:
    """A tab we asked for, unlike one the site opened. Switching to it is not a guess."""
    first = browser.page
    opened = browser.new_tab(f"{demo_server}/")

    assert opened is not first
    assert browser.page is opened
    assert len(browser.tabs) == 2
    assert demo_server in browser.page.url


def test_new_tab_can_be_blank(browser: Browser) -> None:
    browser.new_tab()
    assert len(browser.tabs) == 2


def test_a_tab_we_opened_is_watched_like_any_other(browser: Browser) -> None:
    """Its dialogs and downloads have to reach the same handlers, or a flow that continues
    in a new tab quietly loses both."""
    browser.new_tab()
    browser.page.set_content("<button id='go' onclick=\"confirm('Sure?')\">Go</button>")
    browser.page.locator("#go").click()
    assert browser.last_dialog is not None
    assert browser.last_dialog["message"] == "Sure?"


def test_going_back_to_the_first_tab(browser: Browser, demo_server: str) -> None:
    first = browser.page
    browser.new_tab(f"{demo_server}/")
    browser.switch_tab("main")
    assert browser.page is first


def test_new_tab_is_session_handled() -> None:
    assert actions.ACTIONS["new_tab"].session_handled


def test_new_tab_needs_no_value() -> None:
    """A blank tab is a perfectly ordinary thing to want."""
    actions.spec_for("new_tab")
    assert "new_tab" in actions._VALUE_OPTIONAL


# ------------------------------------------------ signing in, for real (P0)


class TestTheBrowserDoesNotAnnounceItself:
    """Google refused a sign-in with "This browser or app may not be secure".

    Playwright's bundled Chromium sets `navigator.webdriver = true` and launches with
    `--enable-automation`, and Google blocks OAuth in anything that says so. The person
    signs in themselves, with their own hands, in a window they can see, to their own
    account — so what those flags claimed was simply not true, and it cost the user the one
    thing Dejo cannot do for them.
    """

    def test_it_is_not_flagged_as_driven_by_a_program(self, browser: Browser) -> None:
        assert browser.page.evaluate("() => navigator.webdriver") is False

    def test_the_login_window_is_not_flagged_either(self, tmp_path) -> None:
        """The headed window is the one that matters — it is where a person signs in.

        A headed browser needs a display, and a Linux CI runner has none — so this skips
        there and runs for real on a developer machine, which is also where the sign-in
        window is actually used. It used to launch regardless, fail, and leave the
        Playwright driver running, which made the next five tests fail with "Sync API
        inside the asyncio loop" instead of their own reasons.
        """
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
            pytest.skip("a headed browser needs a display, and this machine has none")

        with Browser(headless=False, downloads=tmp_path / "d") as visible:
            assert visible.page.evaluate("() => navigator.webdriver") is False

    def test_it_does_not_say_it_is_headless(self, browser: Browser) -> None:
        """Some sites refuse "HeadlessChrome" on sight. Whether a screen is being watched
        is a fact about the screen, not about who is typing."""
        assert "Headless" not in browser.page.evaluate("() => navigator.userAgent")

    def test_it_prefers_the_real_chrome_on_this_machine(self, browser: Browser) -> None:
        """Sites that gate sign-in treat Chromium as suspicious however it behaves."""
        from dejo.browser import REAL_CHROME

        assert browser._channel in (REAL_CHROME, None)

    def test_a_missing_chrome_is_a_downgrade_not_a_failure(self, tmp_path, monkeypatch) -> None:
        """A browser that starts is worth more than one that is perfectly disguised."""
        from playwright.sync_api import Error as PlaywrightError

        running = Browser(headless=True, downloads=tmp_path / "d")
        real_launch = None

        def only_bundled_works(**options):
            if options.get("channel"):
                raise PlaywrightError("Chromium distribution 'chrome' is not found")
            return real_launch(**options)

        with running:
            real_launch = running._playwright.chromium.launch
            monkeypatch.setattr(running._playwright.chromium, "launch", only_bundled_works)
            running._channel = "chrome"
            fallback = running._launch()

            assert running._channel is None
            fallback.close()


class TestAProfileBelongsToOneBrowser:
    """A silent fallback threw away a sign-in that had been done by hand an hour earlier.

    Measured on the real profile:

        channel='chrome'  FAILED: Target page, context or browser has been closed
        channel=None      opened OK -> us.posthog.com/login?next=...

    The fallback was written for "Chrome is not installed" but caught every failure,
    including "another window has this profile". Chromium cannot read a session Chrome
    wrote, so it produced a browser that looked fine and was signed out — after the one
    thing Dejo asks a person to do themselves.
    """

    def test_the_owner_is_written_into_the_profile(self, tmp_path) -> None:
        from dejo.browser import PROFILE_OWNER

        profile = tmp_path / "profile"
        with Browser(headless=True, profile=profile, downloads=tmp_path / "d"):
            pass

        marker = profile / PROFILE_OWNER
        assert marker.is_file()
        assert marker.read_text(encoding="utf-8").strip() in ("chrome", "chromium")

    def test_a_chromium_profile_is_never_opened_with_chrome(self, tmp_path) -> None:
        """The direction that loses a login."""
        from dejo.browser import BUNDLED, PROFILE_OWNER

        profile = tmp_path / "profile"
        profile.mkdir()
        (profile / PROFILE_OWNER).write_text(BUNDLED, encoding="utf-8")

        with Browser(headless=True, profile=profile, downloads=tmp_path / "d") as running:
            assert running._channel is None

    def test_a_chrome_profile_stays_on_chrome_or_says_it_could_not(self, tmp_path) -> None:
        """A profile Chrome made is opened by Chrome — and where that is impossible, the
        swap is reported rather than done quietly.

        This used to assert `_channel == REAL_CHROME` flatly, which is only true on a
        machine that HAS real Chrome. On a Linux CI runner there is none, Dejo correctly
        falls back to bundled Chromium, and the test failed on behaviour that was right.
        The rule worth pinning is not "always Chrome" — it is "never a silent swap", and
        that one holds everywhere.
        """
        from dejo.browser import PROFILE_OWNER, REAL_CHROME

        profile = tmp_path / "profile"
        profile.mkdir()
        (profile / PROFILE_OWNER).write_text(REAL_CHROME, encoding="utf-8")

        with Browser(headless=True, profile=profile, downloads=tmp_path / "d") as running:
            if running._channel == REAL_CHROME:
                assert running.profile_note is None, "its owner opened it; nothing to report"
            else:
                assert running.profile_note is not None, "a swap must never be silent"
                assert "Chrome would not open" in running.profile_note

    def test_only_a_missing_browser_counts_as_missing(self) -> None:
        """The failure that started this said "Target page, context or browser has been
        closed". Reading that as "Chrome is not installed" is what did the damage."""
        from playwright.sync_api import Error as PlaywrightError

        from dejo.browser import _is_missing_browser

        missing = PlaywrightError("Chromium distribution 'chrome' is not found")
        busy = PlaywrightError("Target page, context or browser has been closed")

        assert _is_missing_browser(missing)
        assert not _is_missing_browser(busy)

    @staticmethod
    def _stub(tmp_path, chromium):
        """A Browser wired to a fake Playwright, so no real browser is launched."""
        profile = tmp_path / "profile"
        # start() makes this before opening; the stub skips start(), so it makes it here.
        profile.mkdir(parents=True, exist_ok=True)
        running = Browser(headless=True, profile=profile, downloads=tmp_path / "d")
        running._playwright = type("PW", (), {"chromium": chromium})()
        running._profile = profile
        running._headless = True
        running._touch = False
        running._timeout_ms = 1000
        running._geolocation = None
        running._permissions = []
        return running

    def test_a_profile_no_browser_will_open_does_not_guess_why(self, tmp_path) -> None:
        """Playwright says the same words for a busy profile and a broken one. Claiming
        one of them sent people looking for a window that was never open."""
        from playwright.sync_api import Error as PlaywrightError

        from dejo.browser import ProfileUnavailable

        class Refuses:
            def launch_persistent_context(self, *args, **kwargs):
                raise PlaywrightError("Target page, context or browser has been closed")

        running = self._stub(tmp_path, Refuses())

        with pytest.raises(ProfileUnavailable) as raised:
            running._open_profile()
        said = str(raised.value)
        assert "still has the profile open" in said
        assert "no browser will accept" in said
        assert "Target page, context or browser has been closed" in said

    def test_the_other_browser_is_tried_before_giving_up(self, tmp_path) -> None:
        """A profile Chrome refuses is worth more opened by Chromium than not at all.
        Measured on a real profile: the sign-ins survive the swap."""
        from playwright.sync_api import Error as PlaywrightError

        tried: list[str | None] = []

        class OnlyChromium:
            def launch_persistent_context(self, *args, **kwargs):
                tried.append(kwargs.get("channel"))
                if kwargs.get("channel") == "chrome":
                    raise PlaywrightError("Target page, context or browser has been closed")
                return "opened"

        running = self._stub(tmp_path, OnlyChromium())

        assert running._open_profile() == "opened"
        assert tried == ["chrome", None]

    @staticmethod
    def _only_chromium():
        from playwright.sync_api import Error as PlaywrightError

        class OnlyChromium:
            def launch_persistent_context(self, *args, **kwargs):
                if kwargs.get("channel") == "chrome":
                    raise PlaywrightError("Target page, context or browser has been closed")
                return "opened"

        return OnlyChromium()

    def test_and_the_swap_is_reported_rather_than_silent(self, tmp_path) -> None:
        """Being signed out with no explanation is the failure this must never repeat."""
        running = self._stub(tmp_path, self._only_chromium())
        (running._profile / ".dejo-browser").write_text("chrome", encoding="utf-8")

        running._open_profile()

        assert running.profile_note is not None
        assert "Chrome would not open" in running.profile_note
        assert "sign in again" in running.profile_note

    def test_but_a_never_opened_profile_says_nothing(self, tmp_path) -> None:
        """No marker means no sign-ins yet, so the swap costs nothing and warning is noise."""
        running = self._stub(tmp_path, self._only_chromium())

        running._open_profile()

        assert running.profile_note is None

    def test_a_machine_with_no_browser_is_told_to_install_one(self, tmp_path) -> None:
        """The very first thing a stranger following the README does is install Dejo and
        run it. Before this, that person was told their profile was unusable and invited to
        delete it — on a machine that had simply never downloaded a browser.

        `_is_missing_browser` existed the whole time; it was only ever consulted on the
        clean-mode path, and profile mode is the default.
        """
        from playwright.sync_api import Error as PlaywrightError

        from dejo.browser import ProfileUnavailable

        class NothingInstalled:
            def launch_persistent_context(self, *args, **kwargs):
                raise PlaywrightError(
                    "Chromium distribution 'chrome' is not found at /opt/google/chrome/chrome"
                )

        running = self._stub(tmp_path, NothingInstalled())

        with pytest.raises(ProfileUnavailable) as raised:
            running._open_profile()

        said = str(raised.value)
        assert "playwright install chromium" in said
        assert "Nothing is wrong with your profile" in said
        assert "delet" not in said.lower(), "never send somebody to delete a profile that is fine"


class TestAFailedStartLeavesNothingBehind:
    """The bug that turned one CI failure into six.

    `sync_playwright().start()` brings up a driver owning an asyncio loop in this thread.
    Leave it running after a failed launch and every LATER browser anywhere in the process
    dies with "Sync API inside the asyncio loop" — a message that names neither the test
    that broke nor the reason. On CI, one browser that could not open produced five
    unrelated failures and three errors, and none of them mentioned the display.
    """

    @staticmethod
    def _refusing_browser(tmp_path, monkeypatch) -> Browser:
        from playwright.sync_api import Error as PlaywrightError

        def will_not_open(self) -> Browser:
            raise PlaywrightError("Looks like you launched a headed browser without an XServer")

        monkeypatch.setattr(Browser, "_open", will_not_open)
        return Browser(headless=True, downloads=tmp_path / "d")

    def test_the_driver_is_stopped(self, tmp_path, monkeypatch) -> None:
        from playwright.sync_api import Error as PlaywrightError

        broken = self._refusing_browser(tmp_path, monkeypatch)

        with pytest.raises(PlaywrightError):
            broken.start()

        assert broken._playwright is None, "a failed start must not leave a driver running"

    def test_and_the_next_browser_still_works(self, tmp_path, monkeypatch) -> None:
        """The half that actually bit us: the damage showed up in unrelated tests."""
        from playwright.sync_api import Error as PlaywrightError

        broken = self._refusing_browser(tmp_path, monkeypatch)
        with pytest.raises(PlaywrightError):
            broken.start()
        monkeypatch.undo()

        with Browser(headless=True, downloads=tmp_path / "after") as recovered:
            assert recovered.page.evaluate("() => 1 + 1") == 2

    def test_the_real_reason_survives(self, tmp_path, monkeypatch) -> None:
        """Cleaning up must not swallow or replace what actually went wrong."""
        from playwright.sync_api import Error as PlaywrightError

        broken = self._refusing_browser(tmp_path, monkeypatch)

        with pytest.raises(PlaywrightError, match="XServer"):
            broken.start()


class TestTheThreeThingsAUserActuallyHits:
    """Edge cases found by walking through a real install rather than the test suite.

    None of these is exotic: a server with no screen, a site that shows a captcha, and a
    site that is merely slow. The third is the dangerous one — it fails quietly.
    """

    def test_a_machine_with_no_screen_is_told_what_to_do_instead(self, tmp_path) -> None:
        """`dejo login` over SSH used to end in a raw Playwright X server error."""
        from playwright.sync_api import Error as PlaywrightError

        from dejo.browser import NoDisplay

        class NoScreen:
            def launch(self, **options):
                raise PlaywrightError(
                    "Looks like you launched a headed browser without having a XServer "
                    "running.\nMissing X server or $DISPLAY"
                )

        visible = Browser(headless=False, downloads=tmp_path / "d")
        visible._playwright = type("PW", (), {"chromium": NoScreen()})()
        visible._channel = "chrome"
        visible._headless = False

        with pytest.raises(NoDisplay) as raised:
            visible._launch()

        said = str(raised.value)
        assert "no screen" in said
        assert "ssh -X" in said
        assert "browser-profile" in said, "it should say how to move a signed-in profile"

    def test_and_a_profile_open_is_not_blamed_for_it(self, tmp_path) -> None:
        """The profile advice would send somebody deleting sign-ins over a missing screen."""
        from playwright.sync_api import Error as PlaywrightError

        from dejo.browser import _why_refused

        no_screen = PlaywrightError("Missing X server or $DISPLAY")

        said = _why_refused(tmp_path, no_screen, bundled_failure=no_screen)

        assert "no screen" in said
        assert "already open" not in said
        assert "delet" not in said.lower()

    def test_a_captcha_is_spotted_rather_than_guessed_at(self, browser: Browser) -> None:
        """A human check is not drift, and no amount of repairing gets past one."""
        browser.page.set_content(
            "<h1>Are you a robot?</h1>"
            "<iframe src='https://www.google.com/recaptcha/api2/anchor'></iframe>"
        )

        assert browser.captcha_on_page() is not None

    def test_an_ordinary_page_is_not_mistaken_for_one(self, browser: Browser) -> None:
        browser.page.set_content("<h1>Invoices</h1><button id='download'>Download</button>")

        assert browser.captcha_on_page() is None

    def test_a_slow_page_is_looked_at_twice_before_being_called_drift(
        self, browser: Browser, tmp_path
    ) -> None:
        """THE DANGEROUS ONE. A slow site used to be recorded as drift, which quietly
        drags good locators toward dead and invites a repair that changes nothing.

        The button here does not exist when the step first looks, and appears shortly
        after — exactly what a JavaScript app does.
        """
        from dejo.executor import Executor
        from dejo.models import Locator, Postcondition, Step
        from dejo.store import DejoStore

        browser.page.set_content(
            """<h1>slow</h1>
            <script>
              setTimeout(() => {
                const b = document.createElement('button');
                b.id = 'late'; b.textContent = 'Late';
                document.body.appendChild(b);
              }, 2200);
            </script>"""
        )

        step = Step(
            index=1,
            intent="click the late button",
            action="click",
            postcondition=Postcondition("element_present", "#late"),
            locators=[Locator("css", "#late", hits=5)],
        )
        store = DejoStore(db_path=str(tmp_path / "slow-memory.db"))
        executor = Executor(store, browser)
        executor._domain = "slow.example.com"
        executor.answers = {}

        outcome = executor._replay_step(step, start_url=None)

        assert outcome.matched_by is not None, "the second look should have found it"
        assert step.locators[0].misses == 0, "a slow page must not be recorded as a miss"
