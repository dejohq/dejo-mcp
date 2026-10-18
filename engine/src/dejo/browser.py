"""The hands. Playwright, wrapped so the rest of Dejo never touches it directly.

Three things here matter more than the rest:

1. **A snapshot is a short list of controls, not the page HTML.** Handing a host AI 200 kB
   of markup is exactly the cost Dejo exists to remove. `snapshot()` returns the handful
   of things you can actually act on, with four different ways to find each one.

2. **There are two browser modes, and the difference is deliberate.**

   *Profile mode* (the default in real use) keeps one Chrome profile at
   `~/.dejo/browser-profile`, so you stay signed in between runs exactly as you do in
   your own browser. Some logins — Google, Microsoft, anything with a one-time code —
   cannot be automated at all, and should not be: you sign in once by hand and the session
   is kept.

   *Clean mode* (`profile=None`) throws the browser away every time. Tests use it, and so
   does any demo where the login itself must be shown happening rather than assumed.

3. **Being signed in is not the same as remembering.** The profile holds who you are. Sibyl
   memory holds what Dejo knows about a site. Delete the memory and Dejo is still logged
   in, but has no idea what to click and has to explore again — the deletion test is
   untouched by any of this.
"""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator as PWLocator
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from . import snapshot as aria
from .home import HOME, PROFILE_OWNER
from .models import Locator
from .snapshot import Element, Snapshot
from .waits import DEFAULT_WAIT_MS, LOCATOR_WAIT_MS, QUIET_WAIT_MS

# Nothing is granted unless a caller asks for it. A site that wants notifications or
# your location puts a prompt over the page, and a prompt over the page blocks the run.
# Denying is silent, and silence is what an unattended agent needs.
NO_PERMISSIONS: list[str] = []

# Granting geolocation without also setting a position makes the site wait forever for a
# fix that never arrives, so the two always travel together.
GEOLOCATION = "geolocation"

# How many console errors and failed requests to keep per page. Enough to explain a
# failure, small enough that a long-running session does not grow without limit.
MAX_DIAGNOSTICS = 50

# Requests at or above this status are worth reporting. A dashboard that stays empty is
# usually one failed request rather than a missing element.
FAILED_STATUS = 400

# The real Chrome on this machine, not Playwright's bundled Chromium. Sites that gate
# sign-in — Google above all — treat Chromium as suspicious no matter how it behaves.
REAL_CHROME = "chrome"
BUNDLED = "chromium"

# Playwright says this, and only this, when the browser is not installed. Every other
# failure is a different problem and must not be mistaken for it.
NOT_INSTALLED = "is not found"

# What a machine with no screen says when asked for a visible window. A server reached
# over SSH is the ordinary case here, not an exotic one, and the raw Playwright error
# tells a person nothing about what to do instead.
NO_SCREEN_TELLS = ("xserver", "missing x server", "$display")

# How a captcha announces itself. Matched against the page, not guessed at from a failure:
# a step that fails because a human check appeared is not drift, and asking an AI to
# repair its way past one wastes a run and teaches the trail nonsense.
CAPTCHA_MARKERS = (
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "iframe[src*='challenges.cloudflare.com']",
    "iframe[title*='captcha' i]",
    ".g-recaptcha",
    ".h-captcha",
    ".cf-turnstile",
    "#challenge-running",
)

# Stops the browser advertising that a program is driving it. Without these,
# `navigator.webdriver` is true and Google refuses to let the USER sign in by hand, which
# is the one thing Dejo cannot do for them.
QUIET_ARGS = ["--disable-blink-features=AutomationControlled"]
NOISY_DEFAULTS = ["--enable-automation"]

# Headless Chrome puts "HeadlessChrome" in its user agent, which some sites refuse on
# sight. The window is genuinely not being watched by anyone; that is a fact about the
# screen, not about who is typing, and it is no business of the site's.
HEADLESS_TELL = "HeadlessChrome"

# What to do with a confirm box. Accepting is the default because Playwright's own
# default — dismissing — silently cancels saves and submits.
ACCEPT = "accept"
DISMISS = "dismiss"

# Which tab to continue in.
LATEST_TAB = "latest"
MAIN_TAB = "main"

# A tab opened by the SITE arrives on an event, not on the call that caused it, so there is
# a gap between `window.open` returning and Dejo knowing the tab exists. Poll for it
# rather than guessing one fixed delay — the same shape as the download grace period, and
# for the same reason. macOS CI found this: a 300 ms sleep in a test was enough on Linux
# and Windows and not enough there, which means it was never long enough anywhere, only
# lucky.
TAB_GRACE_MS = 3000
TAB_POLL_MS = 50

# A single-page app navigates by changing the URL itself, after its click handler has
# returned. Nothing loads, so `domcontentloaded` fires instantly and tells you nothing —
# every React Router <Link> in every admin sidebar behaves this way. Wait a little for the
# address to catch up, and return the moment it does.
SPA_NAV_GRACE_MS = 700
SPA_NAV_POLL_MS = 25

# How much visible page text one look() may return. Enough to read a heading, an amount
# and an error message; not so much that a caller pays for the whole page every time.
MAX_TEXT_CHARS = 1200

# A fixed window for every run. Site layout depends on width - below a breakpoint the
# nav collapses into a hamburger button, so a trail recorded at one size cannot be
# replayed at another. Whatever this is, it must not change between runs.
VIEWPORT = {"width": 1280, "height": 800}

# How long a fresh browser gets to prove an address loads, once the profile's own attempt
# has timed out. Shorter than the real wait: it is a second opinion, and a person is
# already waiting.
FRESH_CHECK_MS = 10_000

# Where downloaded files land unless a caller says otherwise. A default matters: a task
# like "download this month's invoice" is not done if the file only existed inside a
# temporary browser profile that gets deleted when the context closes.
DEFAULT_DOWNLOADS = HOME / "downloads"

# One shared Chrome profile for every site, so signing in to one does not sign you out of
# another. Shared rather than per-site on purpose: Google and friends check that the
# browser looks like the same browser each visit, and a throwaway profile gets challenged
# every single time.
DEFAULT_PROFILE = HOME / "browser-profile"

# Named profiles live beside it, one folder each. A profile is a whole signed-in browser:
# its own cookies, its own session, its own Chrome process. That is what lets a customer, a
# vendor and an admin all be signed in AT ONCE instead of a suite signing out and back in
# between roles — which is slow, and makes the order of the tests matter.
DEFAULT_PROFILES_DIR = HOME / "profiles"

# The profile that was there before named ones existed. It keeps the ORIGINAL folder, so
# every sign-in made until now is still exactly where it was.
DEFAULT_PROFILE_NAME = "default"

# A page that wants a password, or an address that reads like a sign-in, means the session
# has run out. Used only after a step has already failed, so a login page we navigated to
# on purpose is never mistaken for one.
_SIGNED_OUT_HINTS = ("/login", "/signin", "/sign-in", "/sign_in", "/auth", "/sso", "/oauth")

# Reads the durable descriptors for ONE element, the ones a locator is built from.
#
# Only ever run for an element actually being acted on. Reading these for every element on
# every look would cost a round trip per element, and most elements are never touched.
_DESCRIBE_JS = """
(el) => {
  // How far up to look for a unique path. Five was not nearly enough: PostHog's real
  // path to one button was fifteen levels deep.
  const MAX_DEPTH = 15;

  const testIdOf = (node) => {
    const names = ['data-testid', 'data-test-id', 'data-test', 'data-qa', 'data-cy'];
    for (const name of names) {
      const found = node.getAttribute(name);
      if (found) return name + '=' + found;
    }
    return null;
  };

  const labelOf = (node) => {
    const doc = node.ownerDocument;
    const forId = node.id && doc.querySelector(`label[for="${CSS.escape(node.id)}"]`);
    if (forId) return (forId.innerText || '').trim();
    const wrapping = node.closest('label');
    if (wrapping) return (wrapping.innerText || '').trim();
    const aria = node.getAttribute('aria-label');
    return aria ? aria.trim() : null;
  };

  // Walks up until the path matches exactly ONE element, and gives up rather than
  // returning one that matches several. A selector that finds the wrong element is worse
  // than no selector: replay takes the first match and clicks something else entirely.
  const cssOf = (node) => {
    const doc = node.ownerDocument;
    if (node.id && doc.querySelectorAll(`#${CSS.escape(node.id)}`).length === 1) {
      return `#${CSS.escape(node.id)}`;
    }
    if (node.name && node.tagName === 'INPUT') {
      const sel = `${node.tagName.toLowerCase()}[name="${node.name}"]`;
      if (doc.querySelectorAll(sel).length === 1) return sel;
    }

    const parts = [];
    let walker = node;
    while (walker && walker.nodeType === 1 && parts.length < MAX_DEPTH) {
      const tag = walker.tagName.toLowerCase();
      const parent = walker.parentElement;

      // An id anywhere up the chain anchors everything below it in one step.
      if (walker !== node && walker.id
          && doc.querySelectorAll(`#${CSS.escape(walker.id)}`).length === 1) {
        parts.unshift(`#${CSS.escape(walker.id)}`);
        return parts.join(' > ');
      }

      if (tag === 'html' || tag === 'body' || !parent) break;

      const siblings = Array.from(parent.children).filter(c => c.tagName === walker.tagName);
      const index = siblings.indexOf(walker) + 1;
      parts.unshift(siblings.length > 1 ? `${tag}:nth-of-type(${index})` : tag);

      // As soon as it picks out one element, it is done. Going further only adds
      // brittleness — every extra level is another thing a redesign can move.
      const built = parts.join(' > ');
      try {
        if (doc.querySelectorAll(built).length === 1) return built;
      } catch (bad) {
        return '';
      }

      walker = parent;
    }
    return '';
  };

  const type = (el.getAttribute('type') || '').toLowerCase();
  let value = null;
  if ('value' in el && typeof el.value === 'string') {
    // Never report what is typed in a password box, not even back to the caller.
    value = type === 'password' ? (el.value ? '(filled)' : '') : el.value.slice(0, 120);
  }

  return {
    tag: el.tagName.toLowerCase(),
    css: cssOf(el),
    type: el.getAttribute('type'),
    href: el.getAttribute('href'),
    test_id: testIdOf(el),
    label: labelOf(el),
    placeholder: el.getAttribute('placeholder'),
    title: el.getAttribute('title'),
    alt: el.getAttribute('alt'),
    value: value,
  };
}
"""


def _is_missing_browser(problem: BaseException) -> bool:
    """Is this "the browser is not installed", or something else entirely?

    Everything else — a profile already open, a crash on startup — needs its own handling.
    Treating them all as "Chrome is missing" is what silently signed a user out.
    """
    return NOT_INSTALLED in str(problem)


def _keep(kept: list[str], line: str) -> None:
    """Add to a capped list, dropping the oldest. The newest failure is the useful one."""
    kept.append(line)
    if len(kept) > MAX_DIAGNOSTICS:
        del kept[0]


def profile_named(
    name: str,
    *,
    default: Path | str | None = DEFAULT_PROFILE,
    root: Path | None = None,
) -> Path | str | None:
    """Where a named profile keeps its browser data.

    `default` is answered with whatever this machine was already using, so naming profiles
    does not quietly move somebody's sign-ins to a new folder and log them out of
    everything.
    """
    if name == DEFAULT_PROFILE_NAME:
        return default
    return (root or DEFAULT_PROFILES_DIR) / profile_slug(name)


def profile_slug(name: str) -> str:
    """A folder name from a person's name for a profile. "Vendor A" -> "vendor-a"."""
    cleaned = "".join(letter if letter.isalnum() else "-" for letter in name.strip().lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "profile"


def domain_of(url: str) -> str:
    """The memory key for a site. Port included, so a local demo does not collide.

    Anything that names a site has to land on the same key, because the key IS the memory.
    `urlparse` alone only strips a path when there is a scheme in front of it, so
    "github.com/microsoft/playwright" came back whole and became a key of its own. Dejo
    then learned the site under "github.com", looked it up under the long string, and
    found nothing — forever. Measured on 2026-09-05: ten runs on github.com, ten full
    explorations, not one warm replay. It was invisible because everything still worked;
    it was only slow.
    """
    parsed = urlparse(url if "://" in url else f"//{url}")
    return (parsed.netloc or url).lower()


class NoSuchElement(RuntimeError):
    """A control was named in a way this page cannot be asked for."""


class NoSuchTab(RuntimeError):
    """Asked to continue in a tab that is not open."""


class ProfileUnavailable(RuntimeError):
    """No browser would open Dejo's profile, and the reason is not knowable from here."""


class NoDisplay(RuntimeError):
    """A visible window was asked for on a machine that has no screen."""


class ProfileStuck(RuntimeError):
    """Nothing loads in this browser profile, while the same address loads without it.

    Seen for real: a profile in which every tab spun forever, a typed address included,
    while the same Chrome on a fresh profile loaded the site in about a second. Not the
    network, not a proxy, not a leftover process. Without this the only symptom is a
    timeout, which reads exactly like a slow or broken website.
    """


def _is_missing_display(problem: BaseException) -> bool:
    """Is this "there is nowhere to draw a window", rather than a browser problem?"""
    said = str(problem).lower()
    return any(tell in said for tell in NO_SCREEN_TELLS)


NO_SCREEN_ADVICE = (
    "Dejo cannot open a window here: this machine has no screen. Signing in happens in a "
    "window a person looks at and types into, so it is not something Dejo can do for you "
    "on a headless server.\n"
    "    Either run `dejo login` on a computer with a desktop and copy the folder "
    "~/.dejo/browser-profile across afterwards,\n"
    "    or forward a display over SSH with `ssh -X` and run it again."
)


def _stuck_profile_advice(profile: Path, url: str) -> str:
    """Say which profile is stuck, and both ways out of it."""
    return (
        f"Nothing loads in Dejo's browser profile at {profile}: {url} timed out there, but "
        "the same address loads in a fresh browser. The website is fine; this profile is "
        "stuck. Either switch to a new profile (dejo_profile with a new name, or "
        "`dejo --profile <name>`) and sign in there, or close every Dejo window and delete "
        f"{profile}, which signs that profile out of every site."
    )


def _browser_name(channel: str | None) -> str:
    """What to call a browser in a message meant for a person."""
    return "Chrome" if channel == REAL_CHROME else "the bundled Chromium"


def _why_refused(profile: Path, problem: BaseException, *, bundled_failure: BaseException) -> str:
    """Say what happened, without inventing a cause we cannot know.

    Playwright reports the same "target closed" words whether another browser already
    holds the profile or the profile itself is unusable. Naming one of those was a guess,
    and it sent people hunting for a browser window that was never open.

    The first case below is separate because it has a one-line fix and nothing to do with
    the profile. `_is_missing_browser` was only ever consulted on the clean-mode path, so
    somebody who had installed Dejo but not yet its browser — the very first thing a
    stranger following the README does — was told their profile was broken and invited to
    delete it. Only the BUNDLED attempt is checked: a machine can perfectly well have no
    real Chrome while Chromium works fine, and that is not this problem.
    """
    if _is_missing_display(problem) or _is_missing_display(bundled_failure):
        # Nothing to do with the profile at all. Said first, because the profile advice
        # below would send somebody deleting their sign-ins over a missing screen.
        return NO_SCREEN_ADVICE

    if _is_missing_browser(bundled_failure):
        return (
            "Dejo has no browser to drive yet. Chromium is a separate download from the "
            "Python package, so a fresh install needs one more command:\n"
            "    python -m playwright install chromium\n"
            "Nothing is wrong with your profile."
        )

    said = str(problem).split("Browser logs:")[0].strip().replace("\n", " ")
    return (
        f"Dejo could not open its browser profile at {profile}. Neither Chrome nor the "
        "bundled Chromium would take it. Two things cause this, and the browser does not "
        "say which: another Dejo run or a sign-in window still has the profile open, or "
        "the profile is in a state no browser will accept. Deleting the folder fixes the "
        f"second one, at the cost of signing you out everywhere. The browser said: {said}"
    )


class Browser:
    """A single browsing session. Always a fresh context, never a reused profile."""

    def __init__(
        self,
        *,
        headless: bool = True,
        downloads: Path | None = None,
        profile: Path | None = None,
        touch: bool = False,
        permissions: list[str] | None = None,
        geolocation: tuple[float, float] | None = None,
        timeout_ms: int = DEFAULT_WAIT_MS,
    ):
        """`profile=None` means a clean browser every time. Pass a path to stay signed in.

        `touch=True` makes this a touch device, which is what the `tap` action needs. It is
        off by default on purpose: some sites serve a different, mobile layout the moment
        they detect touch, and that would change what every other trail sees.

        `permissions` is empty unless asked for. A site that wants notifications or your
        location puts a prompt over the page, and that prompt blocks everything behind it.

        `geolocation` is a (latitude, longitude) pair, for dashboards that show different
        numbers by region. Passing one grants the geolocation permission automatically —
        granting it without a position makes a site wait forever for a fix that never
        comes.

        `timeout_ms` is the one place patience is set. It applies to every Playwright call
        that does not name its own, so there is a single number to change when a site is
        slow rather than a scattering of them.
        """
        self._headless = headless
        self._touch = touch
        self._timeout_ms = timeout_ms
        self._geolocation = geolocation
        self._permissions = list(permissions) if permissions else list(NO_PERMISSIONS)
        if geolocation is not None and GEOLOCATION not in self._permissions:
            self._permissions.append(GEOLOCATION)
        self._downloads = Path(downloads) if downloads is not None else DEFAULT_DOWNLOADS
        self._profile = Path(profile) if profile is not None else None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page: Page | None = None
        self.last_download: str | None = None
        self.last_download_path: str | None = None
        self.saved_files: list[str] = []
        self._pending_downloads: list[Any] = []
        self.dialog_policy: str = ACCEPT
        """What to do with a confirm box when one appears.

        Accepting by default is the deliberate choice. Playwright's own default is to
        dismiss every dialog, and dismissing silently cancels a save or a submit — the run
        appears to succeed while nothing happened. Whatever is chosen, the message and the
        choice are both recorded, and replay stops if the message has changed."""
        self.last_dialog: dict[str, str] | None = None
        self.last_status: int | None = None
        """The HTTP status the last `goto` was answered with. None when there was no
        response to read, which happens for a jump within the same page."""
        self.profile_note: str | None = None
        """Set when the profile had to be opened by the other browser. Worth passing on."""
        self.tabs: list[Page] = []
        self._watched: list[Page] = []
        self._overlays: list[str] = []
        self._armed: dict[Page, set[str]] = {}

    # ------------------------------------------------------------- lifecycle

    def start(self) -> Browser:
        """Open a browser, or leave nothing running behind the failure.

        The cleanup is the whole point of the shape here. `sync_playwright().start()`
        spins up a driver that owns an asyncio loop in this thread; if anything after it
        raises and that driver is left running, every LATER attempt to start a browser —
        anywhere in the process — dies with "Sync API inside the asyncio loop" instead of
        its own reason. On CI one browser that could not open turned into five unrelated
        failures and three errors, none of which named the real cause.
        """
        self._playwright = sync_playwright().start()
        self._channel: str | None = REAL_CHROME
        try:
            return self._open()
        except BaseException:
            self._playwright.stop()
            self._playwright = None
            raise

    def _open(self) -> Browser:
        """Everything after the driver is up. Never called except through `start`."""
        if self._profile is not None:
            self._profile.mkdir(parents=True, exist_ok=True)
            self._context = self._open_profile()
            self._browser = None
            pages = self._context.pages
            self._page = pages[0] if pages else self._context.new_page()
        else:
            self._browser = self._launch()
            honest = self._honest_user_agent()
            self._context = self._browser.new_context(
                accept_downloads=True,
                viewport=VIEWPORT,
                has_touch=self._touch,
                **({"user_agent": honest} if honest else {}),
                **self._context_options(),
            )
            self._page = self._context.new_page()

        # One place to control patience, rather than a timeout argument scattered across
        # every call site.
        self._context.set_default_timeout(self._timeout_ms)
        self._context.set_default_navigation_timeout(self._timeout_ms)

        self.tabs = [self._page]
        self._watch(self._page)
        # A tab opened by the site — "open in new tab", and most sign-in-with-Google
        # flows — arrives here. It is never switched to automatically: which tab a trail
        # continues in is a decision to record, not to guess.
        self._context.on("page", self._remember_tab)
        return self

    def _launch_options(self) -> dict[str, Any]:
        """How every browser Dejo starts is launched."""
        options: dict[str, Any] = {
            "headless": self._headless,
            "args": QUIET_ARGS,
            "ignore_default_args": NOISY_DEFAULTS,
        }
        if self._channel:
            options["channel"] = self._channel
        return options

    def _launch(self) -> Any:
        """Real Chrome if this machine has it, the bundled Chromium if not.

        Nothing is remembered in a browser with no profile, so downgrading quietly is fine
        here — a browser that starts is worth more than one that is perfectly disguised.
        """
        try:
            return self._playwright.chromium.launch(**self._launch_options())
        except PlaywrightError as refused:
            if _is_missing_display(refused):
                raise NoDisplay(NO_SCREEN_ADVICE) from refused
            if not _is_missing_browser(refused):
                raise
            self._channel = None
            return self._playwright.chromium.launch(**self._launch_options())

    def _open_profile(self) -> Any:
        """Open the saved profile, preferring the browser that made it.

        The other browser is a fallback, not a default: it is tried only after the owner
        refuses outright. This used to refuse instead, on the belief that Chromium cannot
        read a session Chrome wrote. Measured on a real profile, that is wrong — sign-ins
        live in cookies both browsers read, and a profile Chrome will not open is worth
        far more opened by Chromium than not opened at all.

        The swap is never silent. It is written to `profile_note` for the caller to pass
        on, because a person who is suddenly asked to sign in again deserves to know why.
        """
        owner = self._owner_of_profile()
        # A profile with no marker has never been opened, so it holds no sign-ins and the
        # swap costs nothing. Saying "you may have to sign in again" there would be noise.
        used_before = bool(self._profile and (self._profile / PROFILE_OWNER).is_file())
        try:
            return self._profile_opened_by(owner)
        except PlaywrightError as refused:
            spare = None if owner == REAL_CHROME else REAL_CHROME
            try:
                context = self._profile_opened_by(spare)
            except PlaywrightError as spare_refused:
                # Which of the two attempts used the bundled Chromium — the one
                # `playwright install` provides, and so the one that answers "is there a
                # browser on this machine at all?"
                bundled = spare_refused if spare is None else refused
                raise ProfileUnavailable(
                    _why_refused(self._profile, refused, bundled_failure=bundled)
                ) from refused
            if used_before:
                self.profile_note = (
                    f"{_browser_name(owner)} would not open Dejo's browser profile, so "
                    f"{_browser_name(spare)} opened it instead. Sign-ins are kept. If a "
                    "site does ask you to sign in again, this is why."
                )
            return context

    def _profile_opened_by(self, channel: str | None) -> Any:
        """Launch the saved profile with one named browser, and record which one won."""
        self._channel = channel
        settings = {
            **self._launch_options(),
            "accept_downloads": True,
            "viewport": VIEWPORT,
            "has_touch": self._touch,
            **self._context_options(),
        }
        context = self._playwright.chromium.launch_persistent_context(
            str(self._profile), **settings
        )
        self._remember_owner()
        return context

    def _owner_of_profile(self) -> str | None:
        """The browser this profile was made with, or Chrome for a profile with no history."""
        marker = self._profile / PROFILE_OWNER if self._profile else None
        if marker and marker.is_file():
            return None if marker.read_text(encoding="utf-8").strip() == BUNDLED else REAL_CHROME
        return REAL_CHROME

    def _remember_owner(self) -> None:
        """Write down which browser opened this profile, so the next run agrees."""
        if self._profile is None:
            return
        marker = self._profile / PROFILE_OWNER
        owner = self._channel or BUNDLED
        if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != owner:
            marker.write_text(owner, encoding="utf-8")

    def _honest_user_agent(self) -> str | None:
        """The browser's own user agent, minus the word that gets it turned away."""
        if not self._headless or self._browser is None:
            return None
        blank = self._browser.new_context()
        page = blank.new_page()
        reported = page.evaluate("() => navigator.userAgent")
        blank.close()
        return reported.replace(HEADLESS_TELL, "Chrome") if HEADLESS_TELL in reported else None

    def _context_options(self) -> dict[str, Any]:
        """The context settings that are the same however the browser was launched."""
        options: dict[str, Any] = {"permissions": self._permissions}
        if self._geolocation is not None:
            latitude, longitude = self._geolocation
            options["geolocation"] = {"latitude": latitude, "longitude": longitude}
        return options

    @property
    def permissions(self) -> list[str]:
        """What this browser has been allowed to do. Empty unless a caller asked."""
        return list(self._permissions)

    @property
    def timeout_ms(self) -> int:
        """How long any single Playwright call may take before giving up."""
        return self._timeout_ms

    def set_timeout(self, timeout_ms: int) -> None:
        """Change how patient the browser is, for a site that is genuinely slow."""
        self._timeout_ms = timeout_ms
        if self._context is not None:
            self._context.set_default_timeout(timeout_ms)
            self._context.set_default_navigation_timeout(timeout_ms)

    def new_tab(self, url: str | None = None) -> Page:
        """Open a tab of our own and continue in it.

        Unlike a tab the site opens, this one was asked for, so switching to it is not a
        guess.
        """
        if self._context is None:
            raise RuntimeError("the browser is not running")
        page = self._context.new_page()
        self._remember_tab(page)
        self._page = page
        if url:
            self.goto(url)
        return page

    def _watch(self, page: Page) -> None:
        """Attach the listeners every tab needs, including tabs the site opens itself.

        Once per page and never twice. A second download listener queues the same file
        twice, and saving an already-saved download fails — so the file silently never
        reaches disk.
        """
        if page in self._watched:
            return
        self._watched.append(page)
        page.on("download", self._remember_download)
        page.on("dialog", self._answer_dialog)

        # Diagnostics. Kept on the page itself so every tab has its own, and so `reads`
        # can find them without knowing anything about Dejo.
        page._dejo_console = []  # type: ignore[attr-defined]
        page._dejo_failures = []  # type: ignore[attr-defined]
        page.on("console", lambda message: self._remember_console(page, message))
        page.on("pageerror", lambda error: _keep(page._dejo_console, f"error: {error}"))  # type: ignore[attr-defined]
        page.on("response", lambda response: self._remember_failure(page, response))

        # Whatever this site is known to cover itself with, this tab gets it too.
        for selector in self._overlays:
            self._arm_overlay(page, selector)

    def _remember_console(self, page: Page, message: Any) -> None:
        """Only the errors and warnings. A chatty site logs hundreds of ordinary lines."""
        if message.type in ("error", "warning"):
            _keep(page._dejo_console, f"{message.type}: {message.text}")  # type: ignore[attr-defined]

    def _remember_failure(self, page: Page, response: Any) -> None:
        if response.status >= FAILED_STATUS:
            _keep(page._dejo_failures, f"{response.status} {response.url}")  # type: ignore[attr-defined]

    def set_time(self, when: str) -> None:
        """Tell every page it is a different date.

        A dashboard whose numbers depend on today is otherwise unreplayable: a trail
        recorded in September reads the wrong month in October, and nothing about that
        looks like a broken step.
        """
        for page in self.tabs:
            page.clock.set_fixed_time(when)

    def _remember_tab(self, page: Page) -> None:
        if page not in self.tabs:
            self.tabs.append(page)
        self._watch(page)

    def _answer_dialog(self, dialog: Any) -> None:
        """Answer a confirm box, and write down both the words and the answer.

        An unanswered dialog blocks every later step: the browser simply stops. So one of
        these must always run — doing nothing is not a neutral option.
        """
        self.last_dialog = {
            "type": dialog.type,
            "message": dialog.message,
            "choice": self.dialog_policy,
        }
        if self.dialog_policy == ACCEPT:
            dialog.accept()
        else:
            dialog.dismiss()

    # ------------------------------------------------------------------ tabs

    def switch_tab(self, which: str = LATEST_TAB) -> Page:
        """Continue in another tab. `latest`, `main`, or a number from 0."""
        # Asking for tab 1 says the caller believes a second tab exists. If it does not yet,
        # that is far more likely to be a tab still opening than a mistake, so wait for it
        # before saying it is not there.
        if which not in (LATEST_TAB, MAIN_TAB):
            with suppress(ValueError):
                self._await_tab(int(which) + 1)

        self.tabs = [page for page in self.tabs if not page.is_closed()]
        if not self.tabs:
            raise NoSuchTab("every tab has been closed")

        if which == LATEST_TAB:
            chosen = self.tabs[-1]
        elif which == MAIN_TAB:
            chosen = self.tabs[0]
        else:
            try:
                chosen = self.tabs[int(which)]
            except (ValueError, IndexError):
                raise NoSuchTab(
                    f"no tab {which!r}. There are {len(self.tabs)} open, numbered from 0"
                ) from None

        self._page = chosen
        chosen.bring_to_front()
        return chosen

    def _await_tab(self, count: int) -> None:
        """Give a tab that is still opening its moment to arrive.

        Returns as soon as there are enough tabs, so the only run that pays the full wait
        is one where the tab genuinely never appears.

        The sleeping is done through Playwright rather than `time.sleep` on purpose: the
        sync API delivers its events while a Playwright call is running, so a plain sleep
        would sit there and the tab would never be reported at all.
        """
        waited = 0
        while waited < TAB_GRACE_MS:
            live = [page for page in self.tabs if not page.is_closed()]
            if len(live) >= count:
                return
            if not live:
                return
            # Only ever wait for ONE tab that might still be opening. Asking for tab 7 with
            # one open is a mistake rather than a race, and a mistake should be told so at
            # once instead of after three seconds of hope.
            if count > len(live) + 1:
                return
            with suppress(PlaywrightError):
                live[0].wait_for_timeout(TAB_POLL_MS)
            waited += TAB_POLL_MS

    # -------------------------------------------------------------- overlays

    def dismiss_when_seen(self, selector: str) -> None:
        """Clear an overlay automatically, whenever it gets in the way.

        Cookie banners and "rate us" pop-ups do not appear at a fixed point in a flow —
        they appear whenever the site feels like it, which is why they break recorded
        trails so reliably. Playwright can watch for one and clear it the moment it blocks
        an action, so it never becomes a step at all.

        Registered against the site, not the step, and remembered in site knowledge.
        """
        if selector not in self._overlays:
            self._overlays.append(selector)
        for page in self.tabs:
            self._arm_overlay(page, selector)

    def _arm_overlay(self, page: Page, selector: str) -> None:
        """Register one overlay handler on one page.

        Playwright registers these per page, not per browser. A flow that continues in a
        new tab would otherwise meet the banner all over again, having "learned" it.
        """
        armed = self._armed.setdefault(page, set())
        if selector in armed:
            return
        armed.add(selector)
        page.add_locator_handler(page.locator(selector), lambda o: o.click(), times=None)

    @property
    def overlays(self) -> list[str]:
        """The overlays currently being watched for."""
        return list(self._overlays)

    def stop(self) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                closer.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = self._browser = self._context = self._page = None
        self.tabs = []
        self._watched = []
        self._overlays = []
        self._armed = {}

    def __enter__(self) -> Browser:
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("browser not started — call start() or use it as a context manager")
        return self._page

    def _remember_download(self, download) -> None:
        """Queue the download. Do NOT save it here.

        This runs inside Playwright's event callback, and calling `save_as` from there
        while another sync call is still in flight fails with "Download.save_as:
        canceled". So the file is only queued, and `flush_downloads` writes it once the
        action that triggered it has finished.
        """
        self.last_download = download.suggested_filename
        self._pending_downloads.append(download)

    def flush_downloads(self) -> None:
        """Write any queued downloads to disk.

        Playwright throws its temporary copy away when the context closes, so a download
        that is never saved is a download that never happened as far as the user is
        concerned. Called after every action that can trigger one.
        """
        while self._pending_downloads:
            download = self._pending_downloads.pop(0)
            self._downloads.mkdir(parents=True, exist_ok=True)
            destination = self._downloads / download.suggested_filename
            download.save_as(destination)
            self.last_download_path = str(destination)
            self.saved_files.append(str(destination))

    # ----------------------------------------------------------------- doing

    def goto(self, url: str) -> None:
        """Open an address. A timeout in a saved profile is checked against a fresh browser.

        A page that never loads has two very different causes: the site, or this profile.
        Only the second is worth a different sentence, and only a second browser can tell
        them apart, so it is asked once, and only after the real attempt has already failed.
        """
        self.last_status = None
        try:
            response = self.page.goto(url, wait_until="domcontentloaded")
            # Kept because an error page passes every address check: Google answers a
            # document that is gone with a 404 page at the document's own address.
            self.last_status = response.status if response is not None else None
        except PlaywrightTimeout as stuck:
            if self._profile is None or not self._loads_without_profile(url):
                raise
            raise ProfileStuck(_stuck_profile_advice(self._profile, url)) from stuck

    def _loads_without_profile(self, url: str) -> bool:
        """Does this address load in a throwaway browser with no profile at all?"""
        try:
            fresh = self._playwright.chromium.launch(**{**self._launch_options(), "headless": True})
        except PlaywrightError:
            # No second browser to compare with. Then nothing is known about the profile.
            return False
        try:
            fresh.new_page().goto(url, wait_until="domcontentloaded", timeout=FRESH_CHECK_MS)
            return True
        except PlaywrightError:
            return False
        finally:
            with suppress(PlaywrightError):
                fresh.close()

    def snapshot(self) -> Snapshot:
        """The page as a short list of things you can act on.

        Playwright's own accessibility snapshot, which sees through shadow roots and into
        iframes, and reports a pointer cursor — which is how a `div` acting as a button
        gets found at all.
        """
        raw = self.page.locator("body").aria_snapshot(mode="ai")
        return Snapshot(
            url=self.page.url,
            title=self.page.title(),
            elements=aria.parse(raw, frames=self._frame_selectors(raw)),
            text=self.readable_text(),
        )

    def _frame_selectors(self, raw: str) -> dict[str, str]:
        """Map each frame number to a selector for its iframe.

        An element inside an iframe cannot be found later by a plain selector, because
        `page.locator` does not look inside frames. The locator has to name the frame too,
        so the iframe itself needs a durable selector of its own.
        """
        selectors: dict[str, str] = {}
        for number, ref in enumerate(aria.iframe_refs(raw), start=1):
            described = self._describe_ref(ref)
            if described and described.get("css"):
                selectors[str(number)] = described["css"]
        return selectors

    def _describe_ref(self, ref: str) -> dict[str, Any] | None:
        return self._describe_locator(self.page.locator(f"aria-ref={ref}"))

    def _describe_locator(self, target: PWLocator) -> dict[str, Any] | None:
        try:
            return target.evaluate(_DESCRIBE_JS)
        except PlaywrightError:
            return None

    def describe(self, element: Element) -> Element:
        """Fill in the durable descriptors for one element, by reading the page.

        Done here rather than during `snapshot` because it costs a round trip each, and
        only the elements actually acted on ever need them. A ref is good for one snapshot;
        these are what get written down.
        """
        described = self._describe_locator(self.locate(element))
        if not described:
            return element

        # Never overwrite a selector the caller wrote themselves. Theirs is anchored to
        # meaning; the one computed here is a positional path like
        # `div > div > div:nth-of-type(2)`, which breaks the moment a tile is added above
        # it. Keep both, theirs first — that is the whole point of ranked locators.
        if element.selector:
            element.fallback_css = described.get("css") or ""
            described.pop("css", None)

        for key, value in described.items():
            if value is not None and hasattr(element, key):
                setattr(element, key, value)
        return element

    def showing(self, text: str) -> tuple[int, Element | None]:
        """How many elements say exactly this, and the first of them, described durably.

        Used at save time to answer a question Dejo cannot otherwise answer: the caller
        HAS the value — it is about to report it — but Dejo never saw a read that produced
        it, so the trail would arrive at the page and hand back nothing.

        Located by the text once, and then stored by STRUCTURE. The text is a price or a
        count and will be different tomorrow; the css path, the test id and the role will
        not. Storing "the element that said £45.17" would stop working the moment the price
        moved, which is the whole reason that value is worth reading.

        Several matches are reported rather than refused, and that is a deliberate
        difference from an ambiguous CLICK, which is always refused. A wrong click does
        something — it presses another row's delete button — while every element matching
        this text shows the SAME value today. A product page listing its price twice, once
        in the header and once in a tax table, is the ordinary case. The caller is told how
        many matched and which one was kept, so a wrong pick is visible and correctable;
        refusing instead would leave the trail answering nothing, which is certain to be
        useless rather than merely possibly wrong.
        """
        try:
            found = self.page.get_by_text(text, exact=True)
            matches = found.count()
        except PlaywrightError:
            return 0, None
        if matches == 0:
            return 0, None

        described = self._describe_locator(found.first)
        if not described:
            return matches, None

        # The text is deliberately NOT kept as the element's name. `distill` builds a
        # locator out of the name, so keeping it would store "the element reading £45.17"
        # — a locator that misses the moment the price changes, which is the day the value
        # is most worth reading. Structure only: css, test id, role, label.
        element = Element(ref="", role="", name="")
        for key, value in described.items():
            if value is not None and hasattr(element, key):
                setattr(element, key, value)
        return matches, element

    def readable_text(self, limit: int = MAX_TEXT_CHARS) -> str:
        """What the page says, tidied and cut short.

        Blank lines collapsed, and cut at a line break rather than mid-word so the result
        reads like text instead of a truncated blob.
        """
        newline = "\n"
        lines = [line.strip() for line in self.text().splitlines()]
        tidy = newline.join(line for line in lines if line)
        if len(tidy) <= limit:
            return tidy

        cut = tidy[:limit]
        edge = cut.rfind(newline)
        trimmed = cut[:edge] if edge > limit // 2 else cut
        return trimmed + newline + "…"

    def resolve(
        self,
        locator: Locator,
        *,
        timeout_ms: int = LOCATOR_WAIT_MS,
        visible: bool = True,
    ) -> PWLocator | None:
        """Turn a stored locator back into something on the page, or None if it misses.

        Returning None rather than raising is deliberate: a miss is normal and expected
        information here, not an error. It is how drift gets noticed.

        `visible=False` is for READING. You cannot click what you cannot see, but you can
        certainly read it — and requiring visibility for reads made a trail that could be
        RECORDED impossible to REPLAY. FastAPI's documentation hides its `h1` and draws a
        styled title elsewhere: the cold run read "FastAPI" happily, and every replay of
        that same step reported the trail had gone stale.
        """
        try:
            found = self._to_playwright(locator)
            if found is None:
                return None
            # "visible", not "attached", for anything being acted on. Attached only means
            # the element exists in the page — which is already true while it is sliding
            # into place and cannot yet receive a click. Visible also waits for it to
            # stop moving.
            found.first.wait_for(state="visible" if visible else "attached", timeout=timeout_ms)
            return found.first
        except PlaywrightError:
            # Playwright's own base error, which a timeout is a subclass of. This used to
            # read `(PWTimeout, Exception)`, where the second clause swallowed everything —
            # including a real bug in `_to_playwright` — and reported it as ordinary drift.
            return None

    def _to_playwright(self, locator: Locator) -> PWLocator | None:
        """Turn one stored locator back into a Playwright locator, refinements applied."""
        base = self._base_locator(locator)
        if base is None:
            return None
        if locator.has_text:
            base = base.filter(has_text=locator.has_text)
        if locator.nth is not None:
            base = base.nth(locator.nth)
        return base

    def _base_locator(self, locator: Locator) -> PWLocator | None:
        # An element inside an iframe is invisible to `page.locator`, so a locator that
        # named a frame has to be resolved through that frame.
        page: Any = self.page.frame_locator(locator.frame) if locator.frame else self.page
        if locator.kind == "css":
            return page.locator(locator.value)
        if locator.kind == "text":
            return page.get_by_text(locator.value, exact=True)
        if locator.kind == "label":
            return page.get_by_label(locator.value, exact=True)
        if locator.kind == "placeholder":
            return page.get_by_placeholder(locator.value, exact=True)
        if locator.kind == "title":
            return page.get_by_title(locator.value, exact=True)
        if locator.kind == "alt":
            return page.get_by_alt_text(locator.value, exact=True)
        if locator.kind == "test_id":
            # Not `get_by_test_id`: that reads one globally configured attribute name, and
            # real sites use data-testid, data-test-id, data-test, data-qa and data-cy. The
            # name is stored with the value, so this matches whichever the site actually
            # uses without any global setting.
            name, _, wanted = locator.value.partition("=")
            if not wanted:
                return None
            return page.locator(f"[{name}={json.dumps(wanted)}]")
        if locator.kind == "role":
            role, _, name = locator.value.partition("|")
            if not name:
                return page.get_by_role(role)  # type: ignore[arg-type]
            return page.get_by_role(role, name=name, exact=True)  # type: ignore[arg-type]
        if locator.kind == "structural" and locator.value.startswith("href="):
            path = locator.value[len("href=") :].replace('"', "")
            # Exact path, optionally followed by a query string or fragment.
            return page.locator(f'[href="{path}"], [href^="{path}?"], [href^="{path}#"]')
        return None

    def locate(self, element: Element, *, one: bool = True) -> PWLocator:
        """Turn an element into something Playwright can act on.

        `aria-ref` resolves through shadow roots and across frame boundaries on its own, so
        nothing here needs to know where the element lives. That is only true within the
        snapshot the ref came from — which is why acting always re-reads it, and why refs
        never reach memory.

        An element named by a CSS selector instead is resolved by that selector. Dashboards
        keep their numbers in plain `div`s with no role, which get no ref at all.

        `one=False` hands back EVERY match instead of the first. Only `count` and
        `all_text` ask for that, and they have to: taking `.first` for them meant `count`
        could never answer anything but 0 or 1, while its own description promised "how
        many elements match — there are 3 unpaid invoices". It had been quietly answering
        1 for every list on every page.
        """
        if element.found_by is not None:
            found = self._to_playwright(element.found_by)
            if found is None:
                raise NoSuchElement(f"{element.ref} is not something this page can be asked for")
            return found.first if one else found
        if element.selector:
            everything = self.page.locator(element.selector)
            return everything.first if one else everything
        return self.page.locator(f"aria-ref={element.ref}").first

    def await_url_change(self, was: str, timeout_ms: int = SPA_NAV_GRACE_MS) -> bool:
        """Give a client-side navigation time to show up in the address bar.

        A single-page app calls `preventDefault` and then `pushState`, so the URL changes
        AFTER the handler returns. Reading it immediately says nothing moved — which is how
        Dejo came to report `navigated: false` on a link that had worked perfectly, and
        would have recorded the old address as that step's postcondition, wrong for ever.

        Returns the moment the address differs, so a click that genuinely goes nowhere is
        the only one that pays the whole wait.
        """
        waited = 0
        while waited < timeout_ms:
            if self.page.url != was:
                return True
            with suppress(PlaywrightError):
                self.page.wait_for_timeout(SPA_NAV_POLL_MS)
            waited += SPA_NAV_POLL_MS
        return self.page.url != was

    def settle(self) -> None:
        """Let the page catch up after an action.

        Runs after every action rather than after a chosen few. The old code waited only
        after `click` and `press`, so a `select` that navigated was never waited for and
        the next snapshot could be read from the page being replaced.
        """
        # Navigating away mid-wait is normal, not a failure. The next call re-reads
        # whatever page we landed on.
        with suppress(PlaywrightError):
            self.page.wait_for_load_state("domcontentloaded")
        self.flush_downloads()

    def wait_until_quiet(self, timeout_ms: int = QUIET_WAIT_MS) -> None:
        """Wait for the page to stop working, not merely to have arrived.

        `settle()` waits for `domcontentloaded`, which fires long before a JavaScript app
        has drawn anything. That is enough after an action, but not when deciding whether
        a control is genuinely gone or the page simply has not rendered it yet — and
        getting that wrong marks good locators dead and invites a pointless repair.

        Bounded and suppressed on purpose: a page that polls forever never goes quiet,
        and waiting is only ever an improvement here, never a requirement.
        """
        with suppress(PlaywrightError):
            self.page.wait_for_load_state("networkidle", timeout=timeout_ms)

    def captcha_on_page(self) -> str | None:
        """The name of the human check standing in the way, if there is one.

        Only ever asked after a step has already failed. "Prove you are human" is not
        drift and cannot be repaired: the honest answer is to say what happened and stop,
        rather than hand an AI a page it has no way through.
        """
        for marker in CAPTCHA_MARKERS:
            try:
                found = self.page.locator(marker)
                # VISIBLE, not merely present. Plenty of ordinary pages carry a dormant
                # captcha widget for a newsletter box or a contact form — the FastAPI docs
                # do — and it sits in the markup invisible, blocking nothing. Counting
                # those made Dejo announce a human check and refuse to work on a site that
                # was answering perfectly well.
                if any(found.nth(index).is_visible() for index in range(found.count())):
                    return marker
            except PlaywrightError:
                # A closed or navigating page cannot be asked. That is not a captcha.
                return None
        return None

    def looks_signed_out(self) -> bool:
        """Does this look like we were bounced back to a sign-in page?

        Only ever asked after a step has already failed. A site we deliberately opened at
        its login page must not be mistaken for an expired session.
        """
        address = self.page.url.lower()
        if any(hint in address for hint in _SIGNED_OUT_HINTS):
            return True
        try:
            return self.page.locator('input[type="password"]').count() > 0
        except PlaywrightError:
            # A closed or navigating page cannot be asked. That is not a signed-out page.
            return False

    def sign_in_window(self) -> tuple[str, bool] | None:
        """Where a sign-in window is, and whether it still shows a sign-in page.

        None once the person has closed it. A closed page still reports its last address,
        so asking it anything else would read as "no password box here, signed in".
        """
        if self.page.is_closed():
            return None
        return self.page.url, self.still_on_sign_in()

    def still_on_sign_in(self) -> bool:
        """Is this window still showing a sign-in page? Asked when a person says they are done.

        Stricter than `looks_signed_out` about the password box: only a VISIBLE one counts.
        Here a wrong "not signed in" stops a person who has finished, and plenty of
        signed-in pages carry a hidden password field for a change-password dialog.
        """
        address = self.page.url.lower()
        if any(hint in address for hint in _SIGNED_OUT_HINTS):
            return True
        try:
            boxes = self.page.locator('input[type="password"]')
            return any(boxes.nth(index).is_visible() for index in range(boxes.count()))
        except PlaywrightError:
            # A closed or navigating page cannot be asked. That is not a sign-in page.
            return False

    def text(self) -> str:
        """Visible page text, used only for postcondition checks — never sent to a model."""
        try:
            return self.page.inner_text("body")
        except PlaywrightError:
            # Mid-navigation there is no body to read yet. An empty string fails the
            # postcondition, which is the right answer, rather than raising.
            return ""
