"""The cold path: the three verbs a host AI drives.

    look()    what is on this page?
    act()     do one thing, and tell me what changed
    verify()  did the thing I expected actually happen?

There is no model in this file and there never will be. The AI calling these verbs is
somebody else's — normally the user's Claude Code, through `mcp/`. Dejo's job is to make
each call cheap to reason about and to write down what happened, so that the same task
never needs a model again.

`act()` records four independent descriptors of whatever it touched. That redundancy is
the entire reason a redesign is usually survivable: lose the CSS id, keep the link target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any, get_args
from urllib.parse import parse_qsl, urlparse

from playwright.sync_api import Error as PlaywrightError

from . import actions, reads
from . import snapshot as aria
from .browser import LATEST_TAB, Browser, Element, Snapshot, domain_of
from .events import Emitter, MemoryWrite
from .models import (
    Control,
    Locator,
    LocatorKind,
    PageMemory,
    Playbook,
    Postcondition,
    SiteKnowledge,
    SiteMap,
    link_target,
    page_path,
    utc_now,
)
from .store import DejoStore

# Anything in the registry. Kept as a plain str so adding an action never means editing
# a type in a second file — `actions.spec_for` is what actually rejects a bad name.
Action = str

# A download event arrives slightly after the click returns. Poll for it rather than
# guessing one fixed delay: too short is flaky, too long makes every other step slow.
DOWNLOAD_GRACE_MS = 2000
DOWNLOAD_POLL_MS = 50

# How long a step that DID act gets for the page to show its check, before the step is
# called broken. Spent only when the check has already failed once, so a healthy replay
# never pays it.
SETTLE_MS = 3000
SETTLE_POLL_MS = 100

# A remembered read is a step whose job is to produce a value.
READ_ACTION = "read"

# How position is written when a control has no name to be called by. The same spelling
# Playwright uses, so one form covers both a stored locator and a plain CSS selector.
NTH_SUFFIX = " >> nth="

# How long a page whose controls have not changed may go without being written again.
#
# The map is stored as one body per site, so every write re-serialises the whole thing and
# Sibyl re-indexes it for search. Doing that on every single look, during an exploration
# that looks at one page twenty times, would be real time spent to record nothing new. A
# page whose controls CHANGED is always written immediately — this only delays repeat
# sightings of a page that looks exactly as it did before.
MAP_TOUCH_SECONDS = 300

# Actions that put text into a field, and so might be putting a password into one.
_TEXT_ENTRY = {"fill", "type"}


@dataclass
class TraceEntry:
    """One recorded move, with enough context for `distill` to write a step from it."""

    intent: str
    action: Action
    value: str | None = None
    element: Element | None = None
    secret: str | None = None
    dialog: dict[str, str] | None = None
    """The confirm box this step answered, if one appeared: its words and the answer."""
    url_before: str = ""
    url_after: str = ""
    text_gained: str = ""
    answer: str = ""
    """What a remembered READ produced when it was learned.

    Kept so a trail knows the read once had an answer. A replay that comes back empty on a
    step that used to answer is drift, not success — and reporting it as success is how a
    warm run "works" while handing back nothing."""
    download: str | None = None
    locators: list[Locator] | None = None
    """The ways to find the element chosen when the step ran, when they had to be
    narrowed. Replaces `element.locators()` in the trail. A read is narrowed to the
    locators that will still find it once its value has changed."""
    expect: Postcondition | None = None
    """The check the agent wrote for this step with an `expect` line. It replaces the one
    `distill` would infer, and it was proven true when the step ran."""
    risky: bool = False
    """Marked with `!`: the agent says this step buys, pays, sends, deletes or submits."""
    at: str = field(default_factory=utc_now)

    @property
    def navigated(self) -> bool:
        return self.url_before != self.url_after


class ActionFailed(RuntimeError):
    """The requested move could not be performed at all."""


class Session:
    """One cold run: a browser, a trace, and somewhere to save the result."""

    def __init__(
        self,
        browser: Browser,
        store: DejoStore | None = None,
        *,
        emitter: Emitter | None = None,
    ):
        self.browser = browser
        self.store = store
        self.events = emitter or Emitter()
        self.trace: list[TraceEntry] = []
        # The last read that was NOT marked as the answer, and where it happened. Kept
        # because a caller that never marks one still needs its trail to answer — see
        # `_promote_the_last_read`.
        self._loose_read: tuple[int, TraceEntry] | None = None
        self._snapshot: Snapshot | None = None
        self.last_result: Any = None
        # Set by `save`. True when the trail's answer came from a read the caller never
        # marked, so the caller can be told rather than left to find out on the next run.
        self.answered_from_the_last_read = False
        # Set by `save`. How many elements on the page said the value the caller handed
        # over — 0 when none did, or when no value was given. See `_record_the_value`.
        self.answered_from_the_value_given = 0
        self.tool_calls = 0
        # The site map is read once per site and kept here, because it is one body for the
        # whole site and reloading it on every look would cost more than it saves.
        self._map: SiteMap | None = None
        self._map_written: float | None = None

    # ------------------------------------------------------------------ look

    def look(self) -> dict[str, Any]:
        """Return the page as a short list of controls.

        Deliberately small. The whole cost Dejo removes is a host AI reading pages, so
        handing back raw HTML here would defeat the point of the project.
        """
        self.tool_calls += 1
        self._snapshot = self.browser.snapshot()
        self.remember_page(self._snapshot)
        return self._snapshot.to_dict()

    # ------------------------------------------------------------------- act

    def act(
        self,
        intent: str,
        action: Action,
        *,
        ref: str | None = None,
        value: str | None = None,
        to: str | None = None,
    ) -> dict[str, Any]:
        """Do one thing and report what changed.

        `intent` is the caller's own words for why. It is stored verbatim, because when a
        step breaks a year later, "pick this month" is far more useful to whoever repairs
        it than a CSS selector is.
        """
        self.tool_calls += 1
        spec = self._spec(action)
        element: Element | None = None
        second: Element | None = None
        if not spec.session_handled:
            # `evaluate` and `screenshot` may name an element without requiring one.
            if spec.needs_target or ref is not None:
                element = self._element_for(ref)
            if spec.needs_second_target:
                second = self._element_for(to)
        return self.act_on(intent, action, element=element, value=value, second=second)

    def act_on(
        self,
        intent: str,
        action: Action,
        *,
        element: Element | None = None,
        value: str | None = None,
        second: Element | None = None,
        expect: Postcondition | None = None,
        risky: bool = False,
    ) -> dict[str, Any]:
        """Do one thing to an element that has already been found, and report what changed.

        `act` finds the element from a ref or a selector first. A program finds its elements
        its own way (by place in a list, by role, strictly one match) and then comes here,
        so both write exactly the same trace entry."""
        url_before = self.browser.page.url if action != "goto" else ""
        text_before = self.browser.text() if action != "goto" else ""
        self.browser.flush_downloads()
        self.browser.last_download = None
        self.browser.last_download_path = None
        self.browser.last_dialog = None
        self.last_result = None

        element, lasting = self._perform(action, element=element, value=value, second=second)

        # An anchor was clicked and the address has not moved. Either it went nowhere, or
        # this is a single-page app that will change the URL in a moment — a React Router
        # <Link> does exactly that. Waiting a little costs nothing when it really did go
        # nowhere, and is the difference between recording the right address and the wrong
        # one when it did not.
        if element is not None and element.href and self.browser.page.url == url_before:
            self.browser.await_url_change(url_before)
        # Enter in a form field submits it, and the browser starts loading the answer only
        # after the key press has returned. Without this wait the next line ran on the page
        # being replaced: `read css "h1"` found nothing on CI on all three systems (23 Oct).
        if (
            action == "press"
            and (value or "").lower() == "enter"
            and (self.browser.await_url_change(url_before))
        ):
            self.browser.settle()

        # A password is remembered as "there is a password here", never as the password.
        secret = secret_name(element) if action in _TEXT_ENTRY else None

        text_after = self.browser.text()

        # Catch stragglers LAST, immediately before the entry is written. The download
        # event can arrive after the click returns, and reading the page takes long enough
        # for it to land there — so flushing any earlier queued the file without ever
        # saving it, and the step reported a download that was not on disk.
        self.browser.flush_downloads()

        entry = TraceEntry(
            intent=intent,
            action=action,
            value=None if secret else value,
            secret=secret,
            element=element,
            url_before=url_before,
            url_after=self.browser.page.url,
            text_gained=_first_new_line(text_before, text_after),
            download=self.browser.last_download,
            dialog=self.browser.last_dialog,
            expect=expect,
            risky=risky,
            locators=lasting,
        )
        # An action that changes nothing is not a step. Replaying `highlight` would draw a
        # box for nobody and then have its postcondition checked anyway.
        if actions.spec_for(action).recordable:
            self.trace.append(entry)
        self._snapshot = None

        return {
            "ok": True,
            "intent": intent,
            "url": entry.url_after,
            "navigated": entry.navigated,
            "download": entry.download,
            "dialog": entry.dialog,
            # `evaluate` and `screenshot` answer something; every other action answers None.
            "result": self.last_result,
            "saved_to": self.browser.last_download_path,
            "secret": secret,
            "note": (
                f"This was a {secret} field, so Dejo did not remember what was typed. "
                f"On a later run it will look the value up on this machine."
                if secret
                else None
            ),
        }

    def _spec(self, action: Action) -> actions.ActionSpec:
        try:
            return actions.spec_for(action)
        except actions.UnknownAction as unknown:
            raise ActionFailed(str(unknown)) from unknown

    def _perform(
        self,
        action: Action,
        *,
        element: Element | None,
        value: str | None,
        second: Element | None = None,
    ) -> tuple[Element | None, list[Locator] | None]:
        """Describe the element, then hand the doing to the registry.

        Finding things is Dejo's job because a durable descriptor has to be recorded at the
        same moment. Performing is Playwright's job. This method is the seam between them.
        Returns the described element, and the ways of finding it the trail should keep.
        """
        spec = self._spec(action)
        if spec.session_handled:
            self._do_here(action, value)
            return None, None
        if action == "goto":
            # Through the browser, as replay does, so the page's HTTP status is kept. The
            # registry's goto dropped it, so an error page (or a 403 from a site that turns
            # automated browsers away) was learned on as if it were the page (22 Oct 2026).
            self.browser.goto(value or "")
            self.browser.settle()
            return None, None

        # Describe before acting. The durable descriptors have to be read while the
        # element is still on the page as it was — a click can navigate away, and then
        # there is nothing left to describe.
        element = self.browser.describe(element) if element is not None else None
        lasting = self._only_ones(element)
        target = self.browser.locate(element) if element else None
        second_target = self.browser.locate(second) if second is not None else None

        try:
            self.last_result = actions.perform(
                action, page=self.browser.page, target=target, value=value, second=second_target
            )
        except actions.ActionNeedsMore as incomplete:
            raise ActionFailed(str(incomplete)) from incomplete

        # Every action, not a chosen few. A download event can arrive after the click has
        # already returned, and a select can navigate just as a click can.
        self.browser.settle()
        return element, lasting

    def _only_ones(self, element: Element | None) -> list[Locator] | None:
        """The ways of finding this element that match it and nothing else on the page.

        Read before the step changes the page. A way that matches several elements finds
        whichever comes first on replay: on catalog.ccv.edu every menu link points at
        `/content.php`, so the stored link target of "Courses" clicked "Associate Degrees"
        (real-site bench, 22 Oct 2026). None when nothing needs dropping, or when nothing
        would be left: the css path is built to match one element, so that is rare, and a
        step with no way back at all would be worse than an ambiguous one."""
        if element is None or element.by_place:
            return None
        found = element.locators()
        unique = [locator for locator in found if self._matches_once(locator)]
        return unique if unique and len(unique) < len(found) else None

    def _matches_once(self, locator: Locator) -> bool:
        try:
            matched = self.browser.matches(locator)
            return matched is not None and matched.count() == 1
        except PlaywrightError:
            return False

    def _do_here(self, action: str, value: str | None) -> None:
        """The few actions that need Dejo's own state rather than just the page."""
        if action == "switch_tab":
            self.browser.switch_tab(value or LATEST_TAB)
            self._snapshot = None
            return
        if action == "new_tab":
            self.browser.new_tab(value or None)
            self._snapshot = None
            return
        if action == "dismiss_when_seen":
            if not value:
                raise ActionFailed("dismiss_when_seen needs a CSS selector")
            self.remember_overlay(value)
            return
        if action == "restart_trail":
            self.trace.clear()
            self._loose_read = None
            return
        if action == "set_time":
            if not value:
                raise ActionFailed('set_time needs a date, such as "2026-09-15"')
            self.browser.set_time(value)
            return
        raise ActionFailed(f"{action} is marked session-handled but nothing handles it")

    def remember_overlay(self, selector: str) -> None:
        """Clear an overlay from now on, and write it down so later runs do the same.

        Site knowledge rather than a step, because an overlay appears whenever the site
        decides to — not at a fixed point in a flow. Pinning it to a step would be
        recording an accident.
        """
        self.browser.dismiss_when_seen(selector)
        if self.store is None:
            # A session with no memory still gets the overlay cleared; there is simply
            # nowhere to write it down. `Session(browser)` is a supported shape and used
            # by anything driving the browser without wanting to remember.
            return
        domain = domain_of(self.browser.page.url)
        knowledge = self.store.load_site_knowledge(domain) or SiteKnowledge(domain=domain)
        self.store.save_site_knowledge(knowledge.merge(overlay=selector))
        self.events.emit(
            MemoryWrite(
                category="site_knowledge",
                name=domain,
                detail=f"dismiss {selector} whenever it appears",
            )
        )

    def remember_page(self, snapshot: Snapshot) -> None:
        """Write down the page that was just looked at, and what was on it.

        This is the cheapest memory in Dejo: the snapshot has already been built, already
        been paid for, and was about to be thrown away. Keeping it costs no extra page
        read, no extra second and no extra token.

        It exists because Dejo used to remember only the route it was asked for. Walking
        to the requests page to submit a request meant SEEING the list, the view button and
        the other six sidebar items — and binning all of it, so that "view a request"
        started blind the next day on a page Dejo had already stood on.

        Never allowed to break a run. Somebody's task failing because a note about it could
        not be filed would be a bad trade in every possible case.
        """
        if self.store is None:
            return
        try:
            self._record(snapshot)
        except Exception as ignored:  # noqa: BLE001 - a note must never fail the task
            self.events.emit(
                MemoryWrite(
                    category="site_map",
                    name=snapshot.url,
                    detail=f"not recorded: {ignored}",
                )
            )

    def _record(self, snapshot: Snapshot) -> None:
        """Merge one sighting into the site's map, and write it if it said anything new."""
        domain = domain_of(snapshot.url)
        if not domain:
            return
        if self._map is None or self._map.domain != domain:
            self._map = self.store.load_site_map(domain) or SiteMap(domain=domain)
            self._map_written = None

        controls = controls_in(snapshot)
        if not controls:
            # Nothing worth remembering, and recording it would be worse than saying
            # nothing: PyPI answered a bot challenge page under the real URL, and a map
            # that kept it would tell a later run this page has nothing on it.
            return

        path = page_path(snapshot.url)
        before = _fingerprint(self._map.page(path))
        self._map.merge(url=snapshot.url, title=snapshot.title, controls=controls)
        after = _fingerprint(self._map.page(path))

        if before == after and not self._due_a_write():
            return

        self.store.save_site_map(self._map)
        self._map_written = monotonic()
        self.events.emit(
            MemoryWrite(
                category="site_map",
                name=domain,
                detail=f"{path} — {len(self._map.page(path).controls)} controls",
            )
        )

    def _due_a_write(self) -> bool:
        """Has enough time passed to bother re-writing an unchanged page?"""
        if self._map_written is None:
            return True
        return (monotonic() - self._map_written) >= MAP_TOUCH_SECONDS

    def _element_for(self, ref: str | None, *, one: bool = True) -> Element:
        """Find what the caller means, by ref or by CSS selector.

        A dashboard keeps its numbers in plain `div`s with no role, and those are correctly
        not offered as controls — so they have no ref, and a selector is the only handle
        there is. Refusing one meant the numbers could not be read at all.
        """
        if ref is None:
            raise ActionFailed("this action needs a ref from the page, or a CSS selector")

        if aria.is_ref(ref):
            if self._snapshot is None:
                self._snapshot = self.browser.snapshot()
            element = self._snapshot.by_ref(ref)
            if element is None:
                raise ActionFailed(f"no element {ref} on this page — look at it again")
            return element

        remembered = _as_stored_locator(ref)
        if remembered is not None:
            return self._element_by_memory(ref, remembered)

        return self.element_by_selector(ref, one=one)

    def _element_by_memory(self, wording: str, locator: Locator) -> Element:
        """Find a control by what the MAP calls it, rather than by a ref from this page.

        The map stores what a trail stores — a role and a name, a link target — because
        those are what survive. Without this, the map could only ever be a hint: an AI
        would know a "Sign in" button was on this page and still have to read the whole
        page to get a ref before it could press it, which is the cost the map exists to
        remove.

        The resolver is the same one replay uses, so a control reached this way is reached
        exactly as a remembered step reaches it.
        """
        found = self.browser.resolve(locator)
        if found is None:
            raise ActionFailed(
                f"nothing on this page matches {wording!r}. The map says what was here "
                f"last time, so look at the page again: it may have moved."
            )
        # `describe` reads the real page a moment later and overwrites these with what is
        # actually there, so the saved step gets all nine durable locators exactly as a
        # snapshot element would. These are only what the element looks like in between.
        role, _, name = locator.value.partition("|") if locator.kind == "role" else ("", "", "")
        return Element(ref=wording, role=role, name=name or wording, found_by=locator)

    def element_by_selector(self, selector: str, *, one: bool = True) -> Element:
        """Build an element from a CSS selector the caller wrote themselves.

        Refuses an AMBIGUOUS selector rather than quietly taking the first match. This was
        the worst bug Dejo has had: on a table with a menu button in every row,
        `button[aria-haspopup="menu"]` matched them all, Dejo clicked row one's, and
        reported success. The caller then spent eight calls hunting a bug in their own
        application. Worse, a wrong click that reports success gets written into a trail by
        `dejo_save` and replayed for ever.

        Playwright refuses the same selector for the same reason. Silence is the only
        genuinely unsafe answer here: too many matches is a question, and a question
        deserves to be asked rather than guessed at.
        """
        try:
            found = self.browser.page.locator(selector)
            matches = found.count()
        except PlaywrightError as bad:
            raise ActionFailed(_not_a_selector(selector)) from bad

        if matches == 0:
            raise ActionFailed(_nothing_matches(selector))
        if one and matches > 1:
            raise ActionFailed(_too_many(selector, matches, found))

        return Element(ref=selector, role="", name="", selector=selector, css=selector)

    # ------------------------------------------------------------------ read

    def read(
        self,
        kind: str,
        *,
        ref: str | None = None,
        attribute: str | None = None,
        remember: bool = False,
        intent: str = "",
    ) -> Any:
        """Look at the page without changing it.

        This is the half of the job that is not clicking. "How many unpaid invoices are
        there", "did the total change", "is the submit button live yet" — all of it is a
        read, and none of it was possible before.

        Exploring reads are not written down — most of them are just looking around, and
        replaying those would achieve nothing.

        `remember=True` makes this read a step. Use it for the read that IS the answer:
        the number the task was about. Without it a saved trail walks to a page and then
        stops, and the caller has to work the answer out again every single time.
        """
        self.tool_calls += 1
        spec = self._read_spec(kind)
        # `count` and `all_text` are ABOUT matching many, so ambiguity is not an error for
        # them. Every other read is about one element, and reading the first of several
        # silently is how a caller ends up believing the wrong number.
        element = self._element_for(ref, one=not spec.many) if spec.needs_target else None
        return self.read_on(
            kind, element=element, attribute=attribute, remember=remember, intent=intent
        )

    def read_on(
        self,
        kind: str,
        *,
        element: Element | None = None,
        attribute: str | None = None,
        remember: bool = False,
        intent: str = "",
    ) -> Any:
        """Read from an element that has already been found. See `act_on` for why."""
        spec = self._read_spec(kind)
        element = self.browser.describe(element) if element is not None else None
        target = self.browser.locate(element, one=not spec.many) if element else None
        try:
            answer = reads.read(kind, page=self.browser.page, target=target, attribute=attribute)
        except reads.ReadNeedsMore as incomplete:
            raise ActionFailed(str(incomplete)) from incomplete

        self._keep(kind, intent, element, attribute, answer, marked=remember)
        return answer

    def _read_spec(self, kind: str) -> reads.ReadSpec:
        try:
            return reads.spec_for(kind)
        except reads.UnknownRead as unknown:
            raise ActionFailed(str(unknown)) from unknown

    def _keep(
        self,
        kind: str,
        intent: str,
        element: Element | None,
        attribute: str | None,
        answer: Any,
        *,
        marked: bool,
    ) -> None:
        """Write a read into the trail, or hold on to it in case nothing better comes.

        Most reads are just looking around and replaying them would achieve nothing, so
        only a read the caller MARKS becomes a step. That was the whole rule, and it fails
        the same way every time: measured on 2026-09-05 against four public sites, the
        caller never marked one. The trail walked to the page and stopped, so every later
        run read the page again — which is the entire cost Dejo exists to remove, and it
        made Dejo more expensive than a browser tool with no memory at all.

        Telling the caller harder did not work; the tool description already shouts it. So
        the unmarked read is kept aside, and `save` uses it only if the trail would
        otherwise have no answer in it at all.
        """
        entry = self._read_entry(kind, intent, element, attribute, answer)
        if marked:
            self.trace.append(entry)
            return
        # Nothing read is not an answer, and neither is a whole-page dump — remembering
        # that would hand back thousands of characters on every future run, which the read
        # tool warns against by name.
        if entry.answer and element is not None:
            self._loose_read = (len(self.trace), entry)

    def _read_entry(
        self,
        kind: str,
        intent: str,
        element: Element | None,
        attribute: str | None,
        answer: Any = None,
    ) -> TraceEntry:
        """One read, in the shape a trail stores it."""
        return TraceEntry(
            intent=intent or f"read the {kind}",
            action=READ_ACTION,
            value=f"{kind}:{attribute}" if attribute else kind,
            element=element,
            answer="" if answer is None else str(answer).strip(),
            url_before=self.browser.page.url,
            url_after=self.browser.page.url,
        )

    # ---------------------------------------------------------------- verify

    def verify(self, kind: str, value: str, *, target: str | None = None) -> bool:
        """Check a postcondition. Same code the warm path uses, so what we record is
        exactly what will later be enforced."""
        self.tool_calls += 1
        return check_postcondition(
            self.browser,
            Postcondition(kind=kind, value=value, target=target),  # type: ignore[arg-type]
        )

    # ------------------------------------------------------------------ save

    def save(self, task: str, *, domain: str | None = None, answer: str | None = None) -> Playbook:
        """Turn the trace into a playbook and write it to memory.

        This is the moment a slow, exploratory run becomes a fast one forever after.
        """
        from .distill import distill  # local import keeps the module graph acyclic

        if not self.trace:
            raise ActionFailed("nothing to save — the trace is empty")

        self.answered_from_the_last_read = self._promote_the_last_read()
        self.answered_from_the_value_given = self._record_the_value(answer, task)
        site = domain or domain_of(self.trace[0].url_after or self.browser.page.url)
        playbook = distill(self.trace, domain=site, task=task)

        if self.store is not None:
            self.store.save_playbook(playbook)
            self.events.emit(
                MemoryWrite(
                    category="playbook",
                    name=site,
                    detail=f"{len(playbook.steps)} steps from a cold run",
                )
            )
        return playbook

    def _record_the_value(self, answer: str | None, task: str) -> int:
        """Turn the value the caller is about to report into the trail's answer step.

        The last hole, and the one no amount of instruction closed. Measured 2026-09-05 on
        books.toscrape.com: the price lives in `.price_color`, which matches SEVEN elements
        on that page, so the read was refused — correctly; guessing would report another
        book's price forever. The refusal names the matches, so the caller reads the value
        out of the refusal itself, answers, and never makes a successful read. The trail
        then walks three pages and hands back nothing, on every run, for ever.

        The caller always HAS the value at that point. So `dejo_save(answer=...)` takes
        it, and Dejo does the part it is good at: find which element on this page says
        exactly that, and write down every durable way of finding that element again.
        It costs the caller no extra call. Returns how many elements said it, so the
        caller can be told when it was more than one.
        """
        if not answer or any(entry.action == READ_ACTION for entry in self.trace):
            return 0
        matches, element = self.browser.showing(answer.strip())
        if element is None:
            return 0
        self.trace.append(self._read_entry("text", task, element, None, answer.strip()))
        return matches

    def _promote_the_last_read(self) -> bool:
        """If nothing in this trail answers anything, keep the last read that did.

        A trail with no read is a real and correct thing — plenty of tasks are about
        doing, not reading — so this only ever fires when the caller read SOMETHING and
        marked none of it. In that case the last read is the answer, near enough always:
        it is what the caller went on to report.

        It is put back where it happened, not on the end, because acts can follow a read
        and a step out of order would replay in the wrong place.
        """
        if self._loose_read is None or any(e.action == READ_ACTION for e in self.trace):
            return False
        where, entry = self._loose_read
        self.trace.insert(min(where, len(self.trace)), entry)
        self._loose_read = None
        return True


def _too_many(selector: str, matches: int, found: Any) -> str:
    """Say how many, say which, and say how to mean one of them."""
    names = []
    for index in range(min(matches, 4)):
        try:
            words = (found.nth(index).inner_text() or "").strip().replace("\n", " ")[:40]
        except PlaywrightError:
            words = ""
        names.append(f"{index}: {words or '(no text)'}")
    return (
        f"{selector!r} matches {matches} elements on this page, so Dejo will not guess "
        f"which one you mean. The first few are — {'; '.join(names)}. "
        f'Say which you mean. The shortest way is to add " >> nth=0" to the end for the '
        f'first, " >> nth=-1" for the last; or narrow the selector with a parent; or use '
        f"a ref from the page; or a `use` string from the site map such as "
        f'"role=button|Save changes".'
    )


def _nothing_matches(selector: str) -> str:
    """Nothing matched — and the likeliest reason is that this was never a selector.

    "Export Vendors CSV" is perfectly valid CSS: three tag names in a descendant chain. So
    Playwright does not reject it, it simply finds nothing, and the old message stopped at
    "nothing on this page matches" — true, useless, and silent about the one form that
    would have worked. A visible label is the most natural thing to reach for, so this
    happens again and again until the message says what to do about it.
    """
    hint = ""
    if _reads_like_a_label(selector):
        hint = (
            f" That looks like a LABEL rather than a selector. Say it as "
            f'"role=button|{selector}" — or role=link, role=textbox, whichever it is.'
        )
    return (
        f"nothing on this page matches {selector!r}.{hint} Look at the page again for fresh "
        'refs, or name it: role "name", text "...", label "..." or css "...".'
    )


def _reads_like_a_label(selector: str) -> bool:
    """Is this the words on a control rather than CSS?

    Real selectors are built out of punctuation — a dot, a hash, brackets, a combinator.
    Words with spaces and none of that are almost always what somebody read off the screen.
    """
    return " " in selector.strip() and not any(mark in selector for mark in ".#[]>+~:=*")


def _not_a_selector(selector: str) -> str:
    """The message for something that is not CSS at all — usually a name, not a selector."""
    return (
        f"{selector!r} is not a selector this page understands. If that is the NAME of a "
        f'control rather than CSS, say it as "role=button|{selector}" — that is the form '
        f"the site map hands back, and Dejo resolves it the same way replay does. "
        f"Otherwise use a ref from the page."
    )


def _as_stored_locator(ref: str) -> Locator | None:
    """Is this a control named the way MEMORY names one, rather than a ref or a selector?

    `role=button|Sign in`, `test_id=data-qa=submit`, `href=/payments` — the same vocabulary
    a trail stores, so what the map hands back can be acted on directly.

    Anything else is left alone and treated as a CSS selector, as before. A real selector
    never begins with one of these words followed by `=`: `[data-x=1]` starts with `[`, and
    `a[href="/x"]` splits at `a[href`.
    """
    kind, separator, value = ref.partition("=")
    if not separator or not value:
        return None

    # `role=button >> nth=3` — how the map names a control that has no name of its own.
    # A CSS selector carrying the same suffix is left alone: its kind is not a locator
    # kind, so it falls through and Playwright reads `>> nth=` itself.
    index = None
    if NTH_SUFFIX in value:
        value, _, written = value.partition(NTH_SUFFIX)
        try:
            index = int(written)
        except ValueError:
            return None

    if kind == "href":
        # Stored as a `structural` locator, whose value keeps the `href=` in front of it.
        return Locator(kind="structural", value=ref, nth=index)
    if kind in get_args(LocatorKind):
        return Locator(kind=kind, value=value, nth=index)  # type: ignore[arg-type]
    return None


def controls_in(snapshot: Snapshot) -> list[Control]:
    """The controls on a page, in the form the map keeps them.

    The UNNAMED ones are kept too, numbered by their position among controls of the same
    role. They were left out at first, on the reasoning that something with no name cannot
    be found by name later — which was true and beside the point. On an admin table the
    unnamed controls are the icon buttons in every row: view, approve, reject, suspend. The
    map listed the sidebar and the search box and none of the things anybody wanted to
    click, on exactly the page where it should have saved the most work.

    No `ref` travels: a ref only means anything inside the snapshot that produced it.
    """
    seen = utc_now()
    unnamed_so_far: dict[str, int] = {}
    controls = []
    for element in snapshot.elements:
        position = None
        if not element.name:
            position = unnamed_so_far.get(element.role, 0)
            unnamed_so_far[element.role] = position + 1
        controls.append(
            Control(
                role=element.role,
                name=element.name,
                href=_where_it_goes(element.href),
                nth=position,
                last_seen=seen,
            )
        )
    return controls


def _where_it_goes(href: str | None) -> str | None:
    """A link's destination, or nothing when it does not have one.

    A fragment-only target — `#main-content` on PostHog, `#start-of-content` on GitHub —
    is a jump inside the page a screen reader uses, not a place. The map is about places,
    so recording it would offer an AI somewhere to go that is where it already is.

    The CONTROL is still kept. A site can perfectly well hang `href="#"` on a real button,
    and dropping those would lose things worth clicking.
    """
    if not href or href.startswith("#"):
        return None
    return link_target(href)


def _fingerprint(page: PageMemory | None) -> tuple[str, tuple[tuple[str, str], ...]] | None:
    """What makes one sighting of a page different from another.

    The title and which controls are on it. Not their order, and not when they were seen —
    those move for reasons that do not mean the page has changed.
    """
    if page is None:
        return None
    return (page.title, tuple(sorted(control.identity for control in page.controls)))


def secret_name(element: Element | None) -> str | None:
    """Is this a field whose value must never be written down?"""
    if element is None:
        return None
    if (element.type or "").lower() == "password":
        return (element.name or "password").strip().lower().replace(" ", "_") or "password"
    return None


def settles_into(browser: Browser, expected: Postcondition, timeout_ms: int | None = None) -> bool:
    """Does the page reach its check, given a moment? For a step that has already acted.

    A page keeps changing after an action returns: data loads, a redirect lands, a list
    redraws. Found on a busy machine: a click was learned while a slow panel was still
    filling in, so its saved check was that panel's text. On replay the click ran before the
    panel filled, the check failed at once, and a working step was reported broken.
    """
    if expected.kind == "download":
        # Already waits for the file itself. Looping over that wait would multiply it.
        return check_postcondition(browser, expected)
    limit = SETTLE_MS if timeout_ms is None else timeout_ms
    waited = 0
    while not check_postcondition(browser, expected):
        if waited >= limit:
            return False
        browser.page.wait_for_timeout(SETTLE_POLL_MS)
        waited += SETTLE_POLL_MS
    return True


def address_to_check(url: str, wanted: str) -> str:
    """The part of the current address an expected address is compared with.

    Without its query string, unless the expectation has one of its own. A sign-in page
    carries the page you asked for in its query (Google sends a document to
    accounts.google.com/...?continue=https://docs.google.com/document/d/...), so checking
    the whole address said a sign-in page WAS the document, and the run read the sign-in
    page as its answer.
    """
    if "?" in wanted or "#" in wanted:
        return url
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.netloc else url


def at_address(url: str, wanted: str) -> bool:
    """Is `url` the address a check expects?

    `wanted` is a path, or a path and the query values that told the page apart from the
    one before it (`/books?price=50-`). Those values are compared one by one, so the site
    adding a parameter of its own, or writing them in another order, does not fail it."""
    path, _, query = wanted.partition("?")
    if not query or "#" in wanted:
        return wanted in address_to_check(url, wanted)
    if path not in address_to_check(url, path):
        return False
    have = set(parse_qsl(urlparse(url).query, keep_blank_values=True))
    return set(parse_qsl(query, keep_blank_values=True)) <= have


def check_postcondition(browser: Browser, expected: Postcondition) -> bool:
    """Did the page actually end up where it should have?

    This is the line between Dejo and a macro recorder — a recorder clicks and hopes.
    It lives in one place and both the cold and the warm path call it.

    Everything that looks at an element goes through `reads.read`, so a check can never
    disagree with the read an AI would have done by hand.
    """
    if expected.kind == "url_contains":
        # `target` holds the OTHER acceptable URL when a step navigated through a
        # redirect. Arriving at either end of that redirect is arriving.
        here = browser.page.url
        return at_address(here, expected.value) or bool(
            expected.target and at_address(here, expected.target)
        )
    if expected.kind == "text_present":
        return expected.value.lower() in browser.text().lower()
    if expected.kind == "text_gone":
        return expected.value.lower() not in browser.text().lower()
    if expected.kind == "element_present":
        return _count_matching(browser, expected) > 0
    if expected.kind == "element_gone":
        return _count_matching(browser, expected) == 0
    if expected.kind == "count_is":
        return _count_matching(browser, expected) == _as_number(expected.value)
    if expected.kind == "value_is":
        return _read_for(browser, expected, "value") == expected.value
    if expected.kind == "checked_is":
        return _read_for(browser, expected, "checked") is _as_bool(expected.value)
    if expected.kind == "attribute_is":
        name, _, wanted = expected.value.partition("=")
        found = _read_for(browser, expected, "attribute", attribute=name.strip())
        return (found or "") == wanted
    if expected.kind == "download":
        # Wait only as long as it actually takes. Returns the moment the file arrives.
        waited = 0
        while browser.last_download is None and waited < DOWNLOAD_GRACE_MS:
            browser.page.wait_for_timeout(DOWNLOAD_POLL_MS)
            waited += DOWNLOAD_POLL_MS
        browser.flush_downloads()
        return browser.last_download is not None
    return False


def _selector_of(expected: Postcondition) -> str:
    """Which element the check is about.

    The older kinds put their selector in `value` because they had nothing to compare it
    against. The newer ones need `value` for the expected answer, so they use `target`.
    Reading either way keeps every playbook already in memory loadable.
    """
    return expected.target or expected.value


def _count_matching(browser: Browser, expected: Postcondition) -> int:
    return reads.read(
        "count", page=browser.page, target=browser.page.locator(_selector_of(expected))
    )


def _read_for(
    browser: Browser, expected: Postcondition, kind: str, *, attribute: str | None = None
) -> Any:
    """Read one thing, treating a missing element as a failed check rather than a crash.

    A postcondition asks a yes/no question. If the element it names is gone, the honest
    answer is no — and that is drift, which the caller handles. It is not an error.
    """
    target = browser.page.locator(_selector_of(expected)).first
    try:
        return reads.read(kind, page=browser.page, target=target, attribute=attribute)
    except PlaywrightError:
        return None


def _as_number(value: str) -> int:
    try:
        return int(value.strip())
    except ValueError:
        return -1


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "on", "checked"}


def _first_new_line(before: str, after: str) -> str:
    """The first line of text that appeared, used to derive a postcondition.

    Cheap on purpose. A step only needs one honest signal that the page moved, not a diff.
    """
    seen = set(before.splitlines())
    for line in after.splitlines():
        stripped = line.strip()
        if stripped and stripped not in seen and len(stripped) > 3:
            return stripped[:80]
    return ""
