"""The warm path. Deterministic replay, with ZERO model calls.

This file is the product. Everything else supports it.

Replaying a step means: try the stored locators in confidence order, do the action, then
check the postcondition. Three outcomes:

  lands on the first locator   the common case, costs nothing
  lands on a later locator     the site changed cosmetically; we re-rank and move on,
                               still with no model involved
  every locator misses         a real break. Dejo stops, and hands back ONE step for the
                               host AI to work out. Not the whole task, one step.

`model_calls` is hard-coded to 0 in the metrics for a replay, because there is no code
path here that could make one. If that ever stops being true, this docstring is a lie and
the deletion gate is worthless.

THE WARM PATH NEVER READS THE COMMONS. Not once, not as a fallback, not to peek.
Replay may only follow a trail this agent holds in its own memory, because that is
exactly what `dejo forget` takes away — and if replay could reach into the shared
memory instead, `test_deletion_gate.py` would be proving nothing at all. Another
agent's trail has to be deliberately borrowed first, which copies it here, which is
what makes it forgettable.
"""

from __future__ import annotations

import copy
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlparse

from playwright.sync_api import Error as PlaywrightError

from . import actions, reads
from .browser import ACCEPT, Browser
from .events import (
    DriftDetected,
    Emitter,
    MemoryRead,
    MemoryWrite,
    RepairNeeded,
    RepairSaved,
    RunFinished,
    RunStarted,
    StepFailed,
    StepPassed,
    StepStarted,
)
from .models import (
    Locator,
    Playbook,
    Postcondition,
    RunMetrics,
    SiteMap,
    Step,
    href_path,
    page_path,
)
from .operations import READ_ACTION, check_postcondition, controls_in, settles_into
from .secrets import MissingSecret
from .secrets import resolve as resolve_secret
from .store import DejoStore, swapped_subject

# A step is considered past saving when this share of the trail is already broken.
STALE_SHARE = 0.5

# HTTP statuses from here up mean the server did not give us the page (not found, forbidden,
# server error). Below it, 2xx and 3xx, the page arrived.
HTTP_ERROR_FROM = 400

# How long to let the site finish moving after a trail's LAST action before saying the run
# is done. Spent only by trails that end by pressing something — a trail ending in a read
# has nothing in flight — and only in full by a page that never stops calling home.
SETTLE_AFTER_LAST_STEP_MS = 4000


# Actions that put text into a field, so the value may be a secret held on this machine
# rather than in the trail.
_TEXT_ENTRY = {"fill", "type"}

# Actions that cannot, on their own, take the browser to a different page. Only these let
# `pages_along` carry an expectation forward. Deliberately a short allowlist rather than a
# list of the ones that DO navigate: a new action added to the registry then defaults to
# "this might have moved us", which costs a check and never costs a false accusation.
_STAYS_PUT = frozenset({READ_ACTION, "fill", "type", "hover", "select_option", "check"})


@dataclass
class RepairRequest:
    """Everything a host AI needs to fix one step, and nothing more.

    This is deliberately small. Handing back the whole page would put us right back to
    paying page-reading costs on every run.
    """

    domain: str
    step_index: int
    intent: str
    action: str
    tried: list[str] = field(default_factory=list)
    url: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "step_index": self.step_index,
            "intent": self.intent,
            "action": self.action,
            "tried": self.tried,
            "url": self.url,
            "candidates": self.candidates,
        }


@dataclass
class ReplayResult:
    ok: bool
    metrics: RunMetrics
    repair: RepairRequest | None = None
    reason: str = ""
    saved_files: list[str] = field(default_factory=list)
    """Files this run actually wrote to disk. A "download the invoice" task is not done
    until there is a real file, so replay reports paths rather than just filenames."""

    answers: dict[str, Any] = field(default_factory=dict)
    """What the remembered reads said, keyed by the intent they were recorded under.

    This is what makes a warm run *answer* rather than merely arrive. A trail for "how many
    open issues" that navigates to the page and stops is worth almost nothing — the caller
    still has to read the number itself, which was the whole cost we set out to remove."""

    stale: bool = False
    """The trail is past repairing — the site was rebuilt, not tweaked."""

    needs_login: bool = False
    """We were bounced to a sign-in page. Nothing is wrong with the trail; the session
    simply ran out and a person has to sign in again."""

    wrong_place: bool = False
    """The trail is fine; the page it starts from is not the page we are on.

    Deliberately NOT `needs_repair`. Replaying a sign-in while already signed in lands on
    the dashboard, where none of the controls is the one the step wants — and a repair
    offered there would bind a working step to whatever happened to be lying around."""

    already_done: bool = False
    """The trail's effect is already in place, so there was nothing left to do.

    Reported with `ok=True`, because from the caller's side the task IS done — asking to
    sign in when you are already signed in is not a failure, and answering it with an
    error is the thing that makes an agent go looking for a bug that does not exist.

    Only claimed with evidence. Dejo navigates to the page the trail starts on and is
    redirected away a second time; a site that refuses to show its sign-in page is telling
    us we are signed in. Never claimed for a trail with a READ step in it, because that
    trail owes the caller an answer and we do not have one."""

    aimed_at: tuple[str, str] | None = None
    """The subject this run was pointed at instead of the one the trail was saved for.

    `("ankush", "riya")` means the stored route ran with every mention of ankush replaced.
    Always reported, never assumed: the caller asked about a different thing and has to be
    able to see that Dejo worked that out rather than being told about it.

    A run with this set never writes the trail back. The route is the trail's; the values
    are this caller's, and folding one run's outcome into the other's health would let a
    question about pannly quietly rot the trail that belongs to vouchley."""

    unverified_steps: list[int] = field(default_factory=list)
    """Substituted steps where nothing on the page could confirm the new subject landed.

    The step did what it was told and its own check passed — but that check never mentioned
    the subject, so passing it proves the page moved, not that it moved to the right place.
    Named so the caller can look, rather than left for it to assume."""

    blocked: bool = False
    """A human check — a captcha — stood in the way. Deliberately NOT `needs_repair`:
    there is nothing to repair, and nothing an AI can do about it either. Reporting it as
    drift would mark good locators dead for a page the trail never actually reached."""

    page_error: int | None = None
    """The site answered a step's address with an error status (404, 403, 500...), so
    the page the trail reads from is not there. Without this a whole-page read ran on the
    error page and reported success: a Google Doc that had gone came back `ok` with
    "404. That's an error." as its answer. Not drift either — the controls did not move,
    the page is missing — so nothing is marked broken and no repair is offered."""

    site_facts: list[str] = field(default_factory=list)
    """What is still known about the site after a stale trail is thrown away. This is why
    relearning is cheaper than a first visit."""

    @property
    def needs_repair(self) -> bool:
        return self.repair is not None


class NoTrailError(RuntimeError):
    """There is nothing in memory for this site.

    Raised after `dejo forget`. This is the deletion gate doing its job: with the memory
    gone there is no fast path left, and Dejo says so instead of quietly improvising.
    """


class NeedsTask(NoTrailError):
    """The site is remembered, but the caller did not say which of its tasks it wants.

    Deliberately NOT the same as `NoTrailError`. "Which one?" and "never been here" are
    opposite situations that demand opposite responses, and reporting the second when the
    first was true made a host AI re-explore a site it already knew — overwriting what was
    there. Subclassing keeps old handlers working while letting new ones tell them apart.
    """

    def __init__(self, message: str, *, tasks: list[str]):
        super().__init__(message)
        self.tasks = tasks


def _said_nothing(step: Step) -> str:
    """Why an empty answer is reported as a broken step rather than a quiet success."""
    return (
        f"{step.intent!r} used to answer and came back empty. The element is still there, "
        f"so nothing looks broken — but the thing this step exists to read is gone or has "
        f"moved to another element on the page."
    )


def _same_page(here: str, recorded: str) -> bool:
    """Two addresses that mean the same page.

    Ids are generalised away, so `/invoices/2026-09` and `/invoices/2026-10` are one page,
    and a trailing slash is not a different place — a site that answers both
    `/admin/sign-in` and `/admin/sign-in/` has not moved anything.
    """
    return page_path(here).rstrip("/") == page_path(recorded).rstrip("/")


def _leaves_out_of(url: str, playbook: Playbook) -> bool:
    """Is `url` this trail's own first address with parts left out?

    Agents pass the address they were given, usually a site's front page or a list's first
    page, while the trail starts deeper, at `/pages/forms/?page_num=5`. Taken as the start,
    that url sent the replay to page 1, where it read the first team and said done
    (real-site bench, 22 Oct 2026). A url that adds or changes something is a real new
    start, `?variant=b` on the demo site for one, and is kept."""
    first = playbook.steps[0] if playbook.steps else None
    if first is None or first.action != "goto" or not first.value:
        return False
    given, own = urlparse(url), urlparse(first.value)
    if given.netloc and given.netloc.removeprefix("www.") != own.netloc.removeprefix("www."):
        return False
    asked = [part for part in given.path.split("/") if part]
    mine = [part for part in own.path.split("/") if part]
    if asked != mine[: len(asked)]:
        return False
    have = set(parse_qsl(own.query, keep_blank_values=True))
    return set(parse_qsl(given.query, keep_blank_values=True)) <= have


def _trail_origin(playbook: Playbook) -> str | None:
    """Where this trail's site starts: the scheme and host of its first address."""
    for step in playbook.steps:
        if step.action == "goto" and step.value:
            parts = urlparse(step.value)
            if parts.scheme in ("http", "https") and parts.netloc:
                return f"{parts.scheme}://{parts.netloc}/"
    return None


def _redirected_there(landed: str, asked_for: str) -> bool:
    """Did we arrive, allowing for the site rewriting the address on the way?

    Real sites canonicalise constantly: MDN answers /Web/API/fetch with
    /Web/API/Window/fetch, others add a locale, a trailing slash or a www. The path we
    asked for is then nowhere in the URL we landed on, and a strict path check calls a
    perfectly good page a failure — while naming a `goto` step as the thing to repair,
    which cannot be repaired, because a goto has no control to point at.

    Being on the host we asked for is the honest signal that navigation worked. If the
    page is actually wrong, the very next step fails on the thing it cannot find, which is
    a far more useful place to be told.
    """
    if not asked_for:
        return False
    return bool(urlparse(landed).netloc) and urlparse(landed).netloc == urlparse(asked_for).netloc


def _reaim(text: str | None, was: str, now: str) -> tuple[str | None, bool]:
    """Swap one whole word for another, leaving anything it merely sits inside alone.

    Whole words only, or "ana" quietly rewrites "anastasia". Alphanumerics are the word,
    so `vouchley` still matches inside `https://vouchley.example.com/` — a dot is a
    boundary, and that URL is exactly the place the subject usually hides.
    """
    if not text:
        return text, False
    # A percent-escape counts as a boundary too. `%2Fvouchley` puts an `F` immediately
    # before the subject, so a plain word check calls it part of a longer word and the
    # subject goes unseen — inside an encoded URL, which is exactly where it usually is.
    pattern = re.compile(
        rf"(?:(?<![0-9A-Za-z])|(?<=%[0-9A-Fa-f]{{2}})){re.escape(was)}(?![0-9A-Za-z])",
        re.IGNORECASE,
    )
    swapped, count = pattern.subn(now, text)
    return swapped, count > 0


def with_subject(
    playbook: Playbook, was: str, now: str
) -> tuple[Playbook, dict[int, set[str]]] | None:
    """The same trail, aimed at a different subject. A COPY — memory is never touched.

    "message ankush" and "message riya" are one route. So are the same numbers for two
    different projects. Storing a separate trail per person or per project is not memory,
    it is a filing cabinet, and it means the second one costs full price forever.

    `None` when the old subject appears nowhere in the trail's own data. That matters:
    "tell me the quote" against "read the quote" also differs by one word, but `read`
    is not written into any step, so it is a rephrasing rather than a new target and the
    ordinary matcher should handle it untouched.

    Returns the aimed copy and, per step, WHERE the swap landed — which is what decides
    how that step gets verified.
    """
    aimed = copy.deepcopy(playbook)
    touched: dict[int, set[str]] = {}
    for step in aimed.steps:
        where: set[str] = set()
        step.intent, _ = _reaim(step.intent, was, now)
        step.value, hit = _reaim(step.value, was, now)
        if hit:
            where.add("value")
        step.postcondition.value, hit = _reaim(step.postcondition.value, was, now)
        if hit:
            where.add("check")
        step.page, hit = _reaim(step.page, was, now)
        if hit:
            where.add("page")
        for locator in step.locators:
            locator.value, hit = _reaim(locator.value, was, now)
            if hit:
                where.add("locator")
        if where:
            touched[step.index] = where
    return (aimed, touched) if touched else None


def pages_along(steps: list[Step], start_url: str | None = None) -> dict[int, str]:
    """Where each step expects to be standing, worked out from the trail itself.

    `Step.page` only exists on trails learned after it was added, and nothing backfills it,
    so every trail saved before then opted out of the wrong-page check silently and forever.
    That is not a gap worth papering over with a migration: the trail already knows the
    answer and we were simply not reading it.

    Step one is `goto /admin/sign-in`; steps two, three and four follow it with no
    navigation in between, so they can only have run on `/admin/sign-in`. Walking the steps
    in order and carrying that forward reconstructs the whole trail's geography from data
    that is already in memory — no writes, no re-walk, and it works on the oldest trail
    there is.

    The value carried forward is what the navigation ASKED FOR, never where it landed.
    Using the landing address would compare a page with itself and detect nothing, which is
    exactly the failure this exists to catch: the site answering /admin/sign-in with
    /admin/dashboard is the signal, not noise to be normalised away.

    Steps before the first navigation have nothing to inherit and are simply absent.
    """
    expected: dict[int, str] = {}
    asked: str | None = None
    for step in steps:
        if asked:
            expected[step.index] = asked
        if step.action == "goto":
            # The caller can point step one somewhere else; then THAT is what was asked
            # for, and every step after it belongs on the new page rather than the saved
            # one. Without this the redirected-demo replay would report itself off-trail.
            override = start_url if (start_url and step.index == 1) else None
            asked = override or step.value or asked
        elif step.postcondition.kind == "url_contains" and step.postcondition.value:
            # A click that navigates. Most trails reach their page this way rather than
            # by a goto, so leaving it out would cover only the minority shape.
            asked = step.postcondition.value
        elif step.action not in _STAYS_PUT:
            # Anything that can move the page and did not SAY where it was going leaves us
            # genuinely not knowing. Carrying the old page forward past it is worse than
            # knowing nothing: a sign-in ends by pressing a button, the app redirects to a
            # dashboard, and every later step then looks off-trail on a run that is going
            # perfectly. Forgetting here is the honest answer.
            asked = None
    return expected


class Executor:
    """Replays a remembered trail. Reads memory, writes back what it learned."""

    def __init__(
        self,
        store: DejoStore,
        browser: Browser,
        *,
        emitter: Emitter | None = None,
        profile: str | None = None,
    ):
        self.store = store
        self.browser = browser
        self.events = emitter or Emitter()
        # Which signed-in identity this replay is. Only secrets need it: one domain can
        # have a customer, a vendor and an admin sign-in, each with its own password.
        self.profile = profile

    _domain: str = ""
    _expected: dict[int, str] = {}
    """Where each step of the trail being replayed expects to be. See `pages_along`."""
    _went_back: bool = False
    """Has this run already tried to get itself back onto the trail? Once only."""
    _aim: tuple[str, str] | None = None
    """The subject swap in force for this run, if any. See `with_subject`."""
    _aimed: dict[int, set[str]] = {}
    """Per step, where the swap landed: value, check, page or locator."""
    _unverified: list[int] = []
    """Substituted steps nothing on the page could confirm."""

    def run(
        self,
        domain: str,
        *,
        task: str | None = None,
        start_url: str | None = None,
        resume_at: int = 1,
    ) -> ReplayResult:
        """Walk the remembered trail for one task on one site.

        `start_url` overrides the first step's destination. That is how the demo points a
        trail learned on the normal site at the redesigned one, without editing memory.

        `resume_at` starts the walk at that step, for a browser that already stands where
        the step before it left off: a replay broke at step k, the agent fixed step k in
        place, and steps k+1 to the end are all that is left. Running 1 to k again would
        cost time, and would press a risky step before k a second time.
        """
        self._domain = domain
        self.answers: dict[str, Any] = {}
        self._went_back = False
        self._unverified = []
        playbook = self._load(domain, task)
        if start_url and _leaves_out_of(start_url, playbook):
            start_url = None

        # Same route, different subject. "message riya" against a trail saved as "message
        # ankush" is not a rephrasing and must not be replayed unchanged — that is how a
        # message reaches the wrong person, and how a question about one project comes back
        # with another project's numbers.
        self._aim = None
        self._aimed = {}
        swap = swapped_subject(task, playbook.task, domain) if task else None
        if swap:
            reaimed = with_subject(playbook, *swap)
            if reaimed:
                playbook, self._aimed = reaimed
                self._aim = swap

        self._expected = pages_along(playbook.steps, start_url)
        started = time.perf_counter()
        self.browser.saved_files.clear()
        self.browser.last_download = None
        self.browser.last_download_path = None

        # A trail that is mostly broken is not worth repairing one step at a time.
        if playbook.is_stale:
            return self._retire(playbook, started)

        self._arm_overlays(domain)
        self.events.emit(RunStarted(domain=domain, task=playbook.task, mode="warm"))

        metrics = RunMetrics(
            domain=domain,
            task=playbook.task,
            mode="warm",
            steps_total=len(playbook.steps),
            tool_calls=1,  # the whole run is one call from the caller's side
            model_calls=0,  # nothing in this file can make one
        )

        for step in playbook.steps:
            if step.index < resume_at:
                continue
            self.events.emit(StepStarted(index=step.index, intent=step.intent))
            outcome = self._replay_step(step, start_url=start_url)

            if outcome.matched_by is not None:
                metrics.steps_replayed += 1
                self._note_if_unproven(step)
                self.events.emit(
                    StepPassed(
                        index=step.index,
                        intent=step.intent,
                        matched_by=outcome.matched_by,
                        duration_ms=outcome.duration_ms,
                    )
                )
                continue

            # The site answered with an error page. Some sites send 401 or 403 to a
            # signed-out visitor, so that case is a sign-in, not a missing page.
            if outcome.error_status is not None:
                return self._page_missing(playbook, metrics, started, step, outcome)

            # Decided BEFORE the repair request is built. Building it takes a snapshot of
            # the wrong page and writes it into the site map, and emits RepairNeeded to
            # every listener — all of it about a page this trail has nothing to do with.
            if outcome.off_trail is not None:
                belongs, here = outcome.off_trail

                # Usually this only means the browser was left somewhere else. Walking back
                # to the page the step belongs on fixes that without telling anyone, which
                # is the whole difference between a tool that recovers and one that hands
                # its user an error to read.
                # A trail may hold its pages as bare paths, and Playwright needs a whole
                # address. A path is resolved against the TRAIL's own site, never against
                # wherever the browser happens to be: signed out of Google, a document
                # path was joined onto accounts.google.com, which answered 404, and that
                # error page was read as the document. An absolute URL stays as written.
                target = urljoin(_trail_origin(playbook) or self.browser.page.url, belongs)
                if urlparse(target).scheme in ("http", "https") and self._can_walk_back(
                    playbook, step
                ):
                    self._went_back = True
                    self.browser.goto(target)
                    status = self.browser.last_status
                    if status is not None and status >= HTTP_ERROR_FROM:
                        missing = self._StepOutcome(
                            error_status=status,
                            reason=f"{target} answered with HTTP {status} instead of the page",
                        )
                        return self._page_missing(playbook, metrics, started, step, missing)
                    retry = self._replay_step(step, start_url=None)
                    if retry.matched_by is not None:
                        metrics.steps_replayed += 1
                        self.events.emit(
                            StepPassed(
                                index=step.index,
                                intent=step.intent,
                                matched_by=retry.matched_by,
                                duration_ms=retry.duration_ms,
                            )
                        )
                        continue
                    if retry.off_trail is not None:
                        belongs, here = retry.off_trail

                self.events.emit(
                    StepFailed(index=step.index, intent=step.intent, reason=outcome.reason)
                )
                self._finish(playbook, metrics, started, succeeded=False)

                # We asked for the page and were sent away from it a second time. A site
                # that refuses to show its own sign-in page is telling us we are signed in,
                # and answering "the trail is broken" to that sends an agent hunting a bug
                # that does not exist. Only claimed for a trail that owes no answer — one
                # with a READ in it has to come back with something, and we have nothing.
                if self._went_back and not self._reads_anything(playbook):
                    return ReplayResult(
                        ok=True,
                        metrics=metrics,
                        already_done=True,
                        reason=(
                            f"Already done — nothing to do. {playbook.domain} sends "
                            f"{belongs} to {here}, so the state this trail creates is "
                            f"already in place. The trail is untouched and healthy."
                        ),
                        saved_files=list(self.browser.saved_files),
                    )

                return ReplayResult(
                    ok=False,
                    metrics=metrics,
                    wrong_place=True,
                    reason=(
                        f"Step {step.index} ({step.intent!r}) belongs on {belongs}, and we "
                        f"are on {here}. Nothing is broken — the trail's starting state is "
                        f"not met. The commonest reason is that the work is already done: "
                        f"replaying a sign-in while signed in lands on the dashboard. Do "
                        f"NOT repair this step. There is nothing on this page for it to be "
                        f"bound to, and binding it would destroy a working trail."
                    ),
                    saved_files=list(self.browser.saved_files),
                )

            self.events.emit(
                StepFailed(index=step.index, intent=step.intent, reason=outcome.reason)
            )

            # An aimed run that stops has found nothing wrong with the trail. It followed a
            # route built for one subject, pointed at another, and could not see the new one
            # — so the page in front of it has no business being bound to this step. Decided
            # here rather than only in the reply, so the CLI cannot offer the repair either.
            if self._aim is not None:
                was, now = self._aim
                self._finish(playbook, metrics, started, succeeded=False)
                return ReplayResult(
                    ok=False,
                    metrics=metrics,
                    aimed_at=self._aim,
                    reason=(
                        f"This trail is for {was!r} and you asked about {now!r}. Dejo "
                        f"followed the same route aimed at {now!r} and stopped at step "
                        f"{step.index} ({step.intent!r}) because it could not see {now!r} "
                        f"there. Nothing is broken — do NOT repair it. Either {now!r} is "
                        f"not on this site, or it is reached another way, and that is a "
                        f"task of its own to walk and save."
                    ),
                    saved_files=list(self.browser.saved_files),
                )

            request = self._repair_request(playbook, step, outcome.tried)
            self.events.emit(
                RepairNeeded(
                    index=step.index,
                    intent=step.intent,
                    tried=outcome.tried,
                    url=request.url,
                )
            )
            # Being on the wrong page looks exactly like a broken step, and this is the
            # most dangerous of the lookalikes. Replaying "sign in as admin" while ALREADY
            # signed in sends /admin/sign-in to /admin/dashboard, so there is no email
            # field to fill — and the repair offered twenty-three dashboard controls, not
            # one of them an email field. An agent following that instruction literally
            # would bind the step to a nav link and destroy a trail that was never broken.
            # A human check looks exactly like a broken step too, and it is the one thing
            # neither Dejo nor a host AI can repair its way past. Say what happened and
            # stop, rather than handing back a page with no way through it.
            standing_in_the_way = self.browser.captcha_on_page()
            if standing_in_the_way is not None:
                self._finish(playbook, metrics, started, succeeded=False)
                return ReplayResult(
                    ok=False,
                    metrics=metrics,
                    blocked=True,
                    reason=(
                        f"{playbook.domain} put a human check in the way, so the run "
                        f"stopped. The trail is not broken and nothing was repaired — "
                        f"a captcha cannot be automated past. Open the site yourself, "
                        f"clear the check, and run again."
                    ),
                    saved_files=list(self.browser.saved_files),
                )

            # Being signed out looks exactly like a broken step, and asking an AI to
            # repair its way past a login page would waste a run and teach it nonsense.
            if self.browser.looks_signed_out():
                self._finish(playbook, metrics, started, succeeded=False)
                return ReplayResult(
                    ok=False,
                    metrics=metrics,
                    needs_login=True,
                    reason=(
                        f"{playbook.domain} asked to sign in again. The trail is fine — "
                        f"the session ran out."
                    ),
                    saved_files=list(self.browser.saved_files),
                )

            # That step's locators just took a miss. If that tipped the whole trail past
            # half broken, stop asking for repairs and relearn instead.
            if playbook.is_stale:
                self.store.save_playbook(playbook)
                return self._retire(playbook, started)

            self._finish(playbook, metrics, started, succeeded=False)
            return ReplayResult(
                ok=False,
                metrics=metrics,
                repair=request,
                reason=outcome.reason,
                saved_files=list(self.browser.saved_files),
                # Reads before the broken step did answer. The fix carries on from that
                # step, so these are the only copy of them the final reply will have.
                answers=dict(self.answers),
                # A run that stopped BECAUSE it was aimed somewhere new has to say so.
                # Without this the caller sees "this step went stale" and repairs a trail
                # that is perfectly healthy — it was simply pointed at a subject that is
                # not on this page.
                aimed_at=self._aim,
            )

        self._let_the_last_step_land(playbook)
        self._finish(playbook, metrics, started, succeeded=True)
        return ReplayResult(
            ok=True,
            metrics=metrics,
            saved_files=list(self.browser.saved_files),
            answers=dict(self.answers),
            aimed_at=self._aim,
            unverified_steps=list(self._unverified),
        )

    def _let_the_last_step_land(self, playbook: Playbook) -> None:
        """Do not hand back a finished run while the site is still moving.

        A sign-in trail ends by pressing a button, and the app redirects a moment later.
        Dejo used to return the instant the last step's check passed, so a caller reading
        the URL straight afterwards saw the sign-in page and concluded the trail had
        failed — then went and re-explored a site Dejo already knew, which is the exact
        cost this whole project exists to remove.

        Only for a trail that ends in an ACTION. Most trails end with a read — the answer —
        and there is nothing in flight after one of those, so the common case and the
        benchmark pay nothing at all.
        """
        if not playbook.steps or playbook.steps[-1].action == READ_ACTION:
            return
        self.browser.settle()
        # Network quiet, not a timer. A sign-in that POSTs and then navigates takes as
        # long as it takes, and any fixed number is a guess that is too short on a slow
        # day — the first attempt at this waited 400ms and still handed back the sign-in
        # page. `wait_until_quiet` returns the moment the site stops calling home, so
        # the whole budget is only ever spent by a page that never goes quiet.
        self.browser.wait_until_quiet(SETTLE_AFTER_LAST_STEP_MS)
        # Quiet network is not the end of it: an app that redirects on a timer sends no
        # request, so the address has to have stopped moving too. Then once more for the
        # network, in case the page it moved to is still loading its data.
        self.browser.wait_until_address_still(timeout_ms=SETTLE_AFTER_LAST_STEP_MS)
        self.browser.wait_until_quiet(SETTLE_AFTER_LAST_STEP_MS)

    # ------------------------------------------------------------ one step

    @dataclass
    class _StepOutcome:
        matched_by: str | None = None
        tried: list[str] = field(default_factory=list)
        reason: str = ""
        duration_ms: int = 0
        error_status: int | None = None
        """The HTTP error a `goto` was answered with, when the page itself is missing."""
        off_trail: tuple[str, str] | None = None
        """Where this step belongs, and where we actually are — when they differ.

        Set INSTEAD of trying the locators, so a replay in the wrong place marks nothing
        as drift. That mattered more than the wrong repair it also prevents: every wrong-
        place replay used to record a miss against a perfectly good locator, and a few of
        them dragged the trail's health under half, at which point it was retired. The
        trail destroyed itself for being replayed at the wrong moment."""

    def _value_for(self, step: Step, domain: str) -> str:
        """What to type. A secret is fetched from this machine, never from memory."""
        if step.secret:
            return resolve_secret(domain, step.secret, profile=self.profile)
        return step.value or ""

    def _replay_step(self, step: Step, *, start_url: str | None) -> _StepOutcome:
        began = time.perf_counter()

        # Forget any earlier download before acting. Without this a "did it download?"
        # check could be satisfied by a file fetched minutes ago in the same browser, and
        # the step would report success having downloaded nothing.
        self.browser.last_download = None
        self.browser.last_download_path = None

        # Are we even on the page this step belongs to? Asked FIRST, before a single
        # locator is tried, because everything that follows assumes we are.
        astray = self._off_trail(step)
        if astray is not None:
            return self._StepOutcome(off_trail=astray)

        if step.action == "goto":
            sent_elsewhere = bool(start_url) and step.index == 1
            destination = start_url if sent_elsewhere else step.value
            self.browser.goto(destination or "")

            # An error page sits at the address we asked for, so the address check below
            # would pass it. Asked first, and recorded as neither a hit nor a miss: the
            # step is fine, the page it goes to is not there.
            status = self.browser.last_status
            if status is not None and status >= HTTP_ERROR_FROM:
                return self._StepOutcome(
                    error_status=status,
                    reason=f"{destination} answered with HTTP {status} instead of the page",
                )

            # When the caller redirects the first step, the stored check is about the old
            # address and cannot apply. Checking it anyway reported `needs_repair` on a
            # page that had loaded perfectly — and the step it named could not be repaired,
            # because a `goto` has no control to point at.
            expected = (
                Postcondition("url_contains", href_path(destination or ""))
                if sent_elsewhere
                else step.postcondition
            )
            # A canonicalising redirect still counts as arriving. Walking into the WRONG
            # page is caught by the next step, which knows which page it belongs on.
            passed = check_postcondition(self.browser, expected) or _redirected_there(
                self.browser.page.url, destination or ""
            )

            elapsed = int((time.perf_counter() - began) * 1000)

            # A goto's own check is usually about the section, not the subject —
            # `/search-console` is true of every project on it. So when the subject was
            # swapped into this address, the address that came back has to show the NEW
            # one. Sites answer an unknown id by quietly returning you to the default,
            # which passes the stored check and then reads the wrong project's numbers.
            if passed and self._aim and "value" in self._aimed.get(step.index, set()):
                _, landed = _reaim(self.browser.page.url, self._aim[1], self._aim[1])
                if not landed:
                    return self._StepOutcome(
                        reason=(
                            f"asked for {self._aim[1]!r} and the address came back as "
                            f"{self.browser.page.url} — the site did not go there"
                        )
                    )

            if passed:
                step.record_hit()
                return self._StepOutcome(matched_by="url", duration_ms=elapsed)
            step.record_miss()
            return self._StepOutcome(reason="the page did not arrive where it should have")

        # A read of the whole page — its title, its url, the errors it logged — names no
        # element, so there is nothing to find and nothing that can go stale.
        if step.action == READ_ACTION and not step.locators:
            spoke = self._read_answer(step, None)
            elapsed = int((time.perf_counter() - began) * 1000)
            if not spoke:
                step.record_miss()
                return self._StepOutcome(reason=_said_nothing(step))
            step.record_hit()
            return self._StepOutcome(matched_by="page", duration_ms=elapsed)

        # An action aimed at no element (Enter in the field that has focus, a scroll of the
        # page) has nothing to find either. It is done to the page and judged by its check.
        # Treated as "no locator matched", it could never replay: a trail with a bare
        # `press Enter` broke at that step every time (real-site bench, 22 Oct 2026).
        if not step.locators:
            return self._do_to_the_page(step, began)

        outcome = self._StepOutcome()
        # A step that answered a confirm box last time expects the same wording this time.
        self.browser.dialog_policy = step.dialog_choice or ACCEPT
        self.browser.last_dialog = None

        settled, found_anything, missed = self._try_locators(step, outcome, began=began)
        if settled is not None:
            self._blame(missed, step)
            return settled

        # Nothing on the page matched. Before calling that drift, take the other
        # explanation seriously: the page may simply not have finished drawing. A slow
        # site marked as drift is the worst outcome there is — it costs no error, quietly
        # drags good locators toward dead, and invites a "repair" that replaces working
        # locators with identical ones.
        #
        # Only worth a second look when NOTHING resolved. If something did resolve and the
        # action or the check then failed, that is real, and repeating it could click the
        # same button twice.
        #
        # A READ is the exception, and it is safe to be: reading twice changes nothing.
        # A JavaScript-rendered page routinely hands over an element that is present and
        # still empty — the cold run had a settle before it looked and replay did not, so
        # the trail read a heading that was there and blank. Letting a read settle and try
        # again is the difference between working on a modern site and not.
        if not found_anything or step.action == READ_ACTION:
            self.browser.wait_until_quiet()
            outcome.tried.clear()
            settled, _, missed = self._try_locators(step, outcome, began=began)
            if settled is not None:
                self._blame(missed, step)
                return settled

        self._blame(missed, step)
        outcome.reason = "every remembered way of finding this went stale"
        return outcome

    def _do_to_the_page(self, step: Step, began: float) -> _StepOutcome:
        try:
            self._do(step, None, domain=self._domain)
        except PlaywrightError as failed:
            step.record_miss()
            return self._StepOutcome(reason=str(failed).splitlines()[0])
        if not settles_into(self.browser, step.postcondition):
            step.record_miss()
            return self._StepOutcome(reason="the page did not change the way it did when learned")
        step.record_hit()
        elapsed = int((time.perf_counter() - began) * 1000)
        return self._StepOutcome(matched_by="page", duration_ms=elapsed)

    def _note_if_unproven(self, step: Step) -> None:
        """A step took the new subject, passed, and nothing on the page vouched for it.

        The step's own check said the page moved. It did not say the page moved to the
        right subject, because that check never mentioned one. Worth naming rather than
        leaving the caller to assume the swap was confirmed everywhere it was applied.
        """
        where = self._aimed.get(step.index)
        if not self._aim or not where:
            return
        proven = "locator" in where or "check" in where or step.action == "goto"
        if not proven:
            self._unverified.append(step.index)

    @staticmethod
    def _shows(target: Any, subject: str) -> bool:
        """Does this one element say the subject — in its text, its value, or its address?

        Deliberately narrow. It asks about the element the step resolved to and nothing
        else on the page, because "is it somewhere on screen" is the question that lets a
        name in a sidebar vouch for the wrong conversation being open.
        """
        for read in ("inner_text", "input_value"):
            try:
                said = getattr(target, read)(timeout=1500)
            except (PlaywrightError, AttributeError):
                continue
            if said and _reaim(said, subject, subject)[1]:
                return True
        try:
            href = target.get_attribute("href", timeout=1500) or ""
        except (PlaywrightError, AttributeError):
            href = ""
        return bool(href) and _reaim(href, subject, subject)[1]

    def _try_locators(
        self, step: Step, outcome: _StepOutcome, *, began: float
    ) -> tuple[_StepOutcome | None, bool, list[tuple[Locator, str]]]:
        """One pass over a step's locators, collecting misses instead of recording them.

        Handing the misses back rather than applying them is the whole point. A page that
        has not rendered yet makes every locator look dead, and writing that down would
        damage a trail that is perfectly fine. Only the pass that actually decides the
        step's fate gets to blame anything.

        Returns the finished outcome if the step resolved either way, whether any locator
        found an element at all, and the misses this pass would like recorded.
        """
        missed: list[tuple[Locator, str]] = []
        found_anything = False

        for locator in step.ranked_locators():
            label = f"{locator.kind}:{locator.value}"
            outcome.tried.append(label)

            # A read only needs the element to BE there. Insisting it be visible is what
            # made a hidden heading unreplayable on a page it had been recorded from.
            target = self.browser.resolve(locator, visible=step.action != READ_ACTION)
            if target is None:
                missed.append((locator, label))
                continue

            found_anything = True

            # The promise: Dejo will aim a route at a new subject, but it will not ACT
            # until it can see that subject on the thing it is about to act on. Checking
            # the whole page is not enough — riya sitting in the conversation list while
            # ankush's thread is open would pass, and the message would go to ankush.
            aimed_here = self._aim and "locator" in self._aimed.get(step.index, set())
            if aimed_here and not self._shows(target, self._aim[1]):
                outcome.reason = (
                    f"this step was aimed at {self._aim[1]!r}, and what it found on the "
                    f"page does not say {self._aim[1]!r}. Stopping before it acts, because "
                    f"the route would otherwise carry on against the wrong one."
                )
                outcome.duration_ms = int((time.perf_counter() - began) * 1000)
                return outcome, found_anything, missed

            try:
                spoke = self._do(step, target, domain=self._domain)
            except MissingSecret:
                raise
            except PlaywrightError:
                # Only the browser's own failures are drift. A bug of ours — an unknown
                # action, a malformed step — has to surface as itself instead of being
                # filed away as "this locator stopped matching", which is where a real
                # fault would go to die quietly.
                missed.append((locator, label))
                continue

            if not spoke:
                # This locator found an element, and reading it produced nothing where it
                # once produced an answer. Treat it as a MISS rather than a failure, so
                # the next locator gets its turn — on a real product listing, where a
                # stored link matched nine cards, that is exactly what finds the right one.
                missed.append((locator, label))
                continue

            changed = self._dialog_changed(step)
            if changed:
                # Never answer a box whose words have changed. A step that recorded
                # "click OK" on "Save changes?" must not blindly accept one that now
                # reads "delete 400 rows?". Stop and let a human or the caller look.
                outcome.reason = changed
                outcome.duration_ms = int((time.perf_counter() - began) * 1000)
                return outcome, found_anything, missed

            if settles_into(self.browser, step.postcondition):
                locator.record_hit()
                outcome.matched_by = label
                outcome.duration_ms = int((time.perf_counter() - began) * 1000)
                return outcome, found_anything, missed

            # It clicked something, but the page did not move the way it should have.
            # That is drift, not success — this is the check a macro recorder skips.
            missed.append((locator, label))

        return None, found_anything, missed

    def _page_missing(
        self,
        playbook: Playbook,
        metrics: RunMetrics,
        started: float,
        step: Step,
        outcome: _StepOutcome,
    ) -> ReplayResult:
        """The site answered with an error page, so there is nothing to read or repair.

        Some sites send 401 or 403 to a signed-out visitor, so that case is reported as a
        sign-in, which is the thing the person can actually fix.
        """
        self.events.emit(StepFailed(index=step.index, intent=step.intent, reason=outcome.reason))
        self._finish(playbook, metrics, started, succeeded=False)
        if self.browser.looks_signed_out():
            return ReplayResult(
                ok=False,
                metrics=metrics,
                needs_login=True,
                reason=(
                    f"{playbook.domain} asked to sign in again. The trail is fine — "
                    f"the session ran out."
                ),
                saved_files=list(self.browser.saved_files),
            )
        return ReplayResult(
            ok=False,
            metrics=metrics,
            page_error=outcome.error_status,
            reason=(
                f"Step {step.index} ({step.intent!r}): {outcome.reason}. The page this trail "
                f"reads from is not there (deleted, moved, or not shared with this profile). "
                f"Nothing was read and nothing is marked broken. Check the address in a "
                f"browser; if the page moved, walk the task again and save it."
            ),
            saved_files=list(self.browser.saved_files),
        )

    def _can_walk_back(self, playbook: Playbook, step: Step) -> bool:
        """May this run navigate back to where the step belongs, and try once more?

        Once per run, and only while nothing has been changed yet. The loop is sequential,
        so every step before this one has already run. Re-navigating after a form is half
        filled would throw that work away to fix a problem the caller never had — a `goto`
        and a `read` change nothing, so up to the first fill or click it is free, and after
        it never is.
        """
        if self._went_back:
            return False
        return all(
            earlier.action in ("goto", READ_ACTION)
            for earlier in playbook.steps
            if earlier.index < step.index
        )

    @staticmethod
    def _reads_anything(playbook: Playbook) -> bool:
        """Does this trail owe the caller an answer?

        A trail that only changes state can honestly report "already done" when the site
        says the state is already there. One with a READ in it cannot: it was asked for a
        number, and "it was already true" is not a number.
        """
        return any(step.action == READ_ACTION for step in playbook.steps)

    def _off_trail(self, step: Step) -> tuple[str, str] | None:
        """Is this step being replayed somewhere it was never recorded?

        A `goto` names its own destination, so it can never be in the wrong place. Every
        other step was recorded on a particular page, and if we are not on it the step is
        not broken — the trail's starting state simply is not met. Replaying "sign in as
        admin" while already signed in is the everyday version: the site sends
        /admin/sign-in to /admin/dashboard, and the email field the step wants was never
        going to be there.

        A `goto` names its own destination, so it is never in the wrong place.

        `Step.page` is the authority when the trail has it. When it does not — every trail
        saved before that field existed, and nothing ever backfills it — the page is worked
        out from the trail itself by `pages_along`. Reading only the stored field is what
        made this check silently do nothing on real trails for three attempted fixes.
        """
        if step.action == "goto":
            return None
        belongs = step.page or self._expected.get(step.index, "")
        if not belongs:
            return None
        here = self.browser.page.url
        if _same_page(here, belongs):
            return None
        return (belongs, here)

    def _blame(self, missed: list[tuple[Locator, str]], step: Step) -> None:
        """Write down the misses from the pass that actually decided the step."""
        for locator, label in missed:
            locator.record_miss()
            self.events.emit(DriftDetected(index=step.index, locator=label))

    def _read_answer(self, step: Step, target) -> bool:
        """Replay a remembered read and keep what it said. False if it said nothing.

        This is what makes a warm run *answer* rather than merely arrive. A trail for
        "how many open issues" is worth nothing if it navigates to the page and stops.

        Emptiness is a failure when this read ANSWERED at the time it was learned. The
        element still being there is not enough: on a real product listing a stored link
        matched nine cards, replay read the one with no text, every check passed
        and the run reported success while handing back "". A step that used to answer and
        now does not is the page moving underneath the trail, which is drift, and drift is
        repairable — silence is not.
        """
        kind, _, attribute = (step.value or "text").partition(":")
        answer = reads.read(
            kind, page=self.browser.page, target=target, attribute=attribute or None
        )
        self.answers[step.intent] = answer
        return not (step.answered and not str(answer).strip())

    def _dialog_changed(self, step: Step) -> str | None:
        """Did a confirm box appear whose wording is not what was recorded?

        Answered dialogs are the one thing replay must not treat as routine. The choice
        was made once, for a specific question; the same click can mean something
        completely different behind a different question.
        """
        seen = self.browser.last_dialog
        if seen is None or not step.dialog_message:
            return None
        if seen["message"].strip() == step.dialog_message.strip():
            return None
        return (
            f"this step answered {step.dialog_message.strip()!r} before, but the site now "
            f"asks {seen['message'].strip()!r} — stopping rather than answering it"
        )

    def _arm_overlays(self, domain: str) -> None:
        """Re-arm the overlays this site is known for, before the trail starts.

        This is what makes "learned once" mean anything. Without it the banner is cleared
        on the run that met it and covers the page again on every run after.
        """
        knowledge = self.store.load_site_knowledge(domain)
        if knowledge is None:
            return
        for selector in knowledge.overlays:
            self.browser.dismiss_when_seen(selector)
        if knowledge.overlays:
            self.events.emit(
                MemoryRead(
                    category="site_knowledge",
                    name=domain,
                    found=True,
                )
            )

    def _do(self, step: Step, target, *, domain: str) -> bool:
        """Replay one recorded action. False when a remembered read came back empty.

        The value comes from `_value_for`, so a password field is filled from this machine
        rather than from memory — memory never held it.
        """
        if step.action == READ_ACTION:
            return self._read_answer(step, target)

        spec = actions.spec_for(step.action)
        value = self._value_for(step, domain) if spec.name in _TEXT_ENTRY else step.value
        was = self.browser.page.url
        actions.perform(
            step.action,
            page=self.browser.page,
            target=target,
            value=value,
        )
        self.browser.settle()
        # This step is recorded as one that changes the address. If it has not changed
        # yet, the app may be doing it itself a moment later — which is how every
        # single-page sidebar link works. Cheap when it was going to change anyway.
        # The address moving is the start of the load, not the end of it.
        moved = step.postcondition.kind == "url_contains" and self.browser.page.url == was
        if moved and self.browser.await_url_change(was):
            self.browser.settle()
        return True

    def _retire(self, playbook: Playbook, started: float) -> ReplayResult:
        """Throw the trail away, keep what is known about the site, and say so.

        This is the plan's rule: over half the steps broken means the site was rebuilt,
        not adjusted. Repairing step by step from there is slower than walking it again,
        and each repair would be built on a trail that is mostly wrong anyway.
        """
        broken = sum(1 for step in playbook.steps if step.health < 0.5)
        self.store.retire_playbook(playbook.domain, playbook.task)
        self.events.emit(
            MemoryWrite(
                category="playbook",
                name=playbook.domain,
                detail=f"retired as stale ({broken} of {len(playbook.steps)} steps broken)",
            )
        )

        knowledge = self.store.load_site_knowledge(playbook.domain)
        self.events.emit(
            MemoryRead(
                category="site_knowledge",
                name=playbook.domain,
                found=knowledge is not None,
            )
        )

        metrics = RunMetrics(
            domain=playbook.domain,
            task=playbook.task,
            mode="warm",
            steps_total=len(playbook.steps),
            trail_repairs=playbook.repairs,
            tool_calls=1,
            model_calls=0,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        self.store.journal_run(metrics)
        self.events.emit(
            RunFinished(
                domain=playbook.domain,
                succeeded=False,
                duration_ms=metrics.duration_ms,
                steps_replayed=0,
                trail_repairs=playbook.repairs,
                model_calls=0,
            )
        )

        return ReplayResult(
            ok=False,
            metrics=metrics,
            stale=True,
            reason=(
                f"{broken} of {len(playbook.steps)} steps no longer match this site. "
                f"It was rebuilt, not tweaked, so the trail has been retired."
            ),
            site_facts=knowledge.summary() if knowledge else [],
        )

    # -------------------------------------------------------------- repair

    def _repair_request(self, playbook: Playbook, step: Step, tried: list[str]) -> RepairRequest:
        """Describe the one broken step, with the current page's controls as candidates.

        The candidates are described in full rather than left as bare refs. Whoever repairs
        this step has to write down a locator that will still work next month, and a ref is
        good for one snapshot only — so the durable descriptors have to travel with it.
        """
        snapshot = self.browser.snapshot()
        self._remember_page(playbook.domain, snapshot)
        return RepairRequest(
            domain=playbook.domain,
            step_index=step.index,
            intent=step.intent,
            action=step.action,
            tried=tried,
            url=snapshot.url,
            candidates=[self.browser.describe(element).to_dict() for element in snapshot.elements],
        )

    def _remember_page(self, domain: str, snapshot: Any) -> None:
        """Keep the page this snapshot came from in the site's map.

        The only place the warm path touches the map, and deliberately so. Replay reads no
        pages at all — that is the whole claim — so there is normally no snapshot to keep.
        A broken step is the exception: one has just been built to describe the candidates,
        it is free, and it is taken at exactly the moment the page is KNOWN to have moved,
        which is when a stale map is worth correcting.

        Never allowed to break a run, for the same reason as on the cold path.
        """
        try:
            site_map = self.store.load_site_map(domain) or SiteMap(domain=domain)
            self.store.save_site_map(
                site_map.merge(
                    url=snapshot.url,
                    title=snapshot.title,
                    controls=controls_in(snapshot),
                )
            )
        except Exception:  # noqa: BLE001 - a note must never fail the task
            return
        self.events.emit(
            MemoryWrite(category="site_map", name=domain, detail=f"{snapshot.url} after drift")
        )

    def repair_from_ref(
        self, domain: str, step_index: int, ref: str, *, task: str | None = None
    ) -> Playbook:
        """Fix a step by pointing at the control that should have been used.

        Better than handing over one selector: the element is described in full, so the
        step gets back every durable way of finding it — test id, link target, label, role,
        text — exactly as a fresh recording would. A repair that stored a single positional
        path left the step more fragile than when it was first learned.
        """
        snapshot = self.browser.snapshot()
        element = snapshot.by_ref(ref)
        if element is None:
            raise NoTrailError(f"no control {ref!r} on this page — look at it again")

        found = self.browser.describe(element).locators()
        if not found:
            raise NoTrailError(f"{ref!r} offers no durable way of being found again")
        return self.apply_repair(domain, step_index, found, task=task)

    def apply_repair(
        self,
        domain: str,
        step_index: int,
        locator: Locator | list[Locator],
        *,
        task: str | None = None,
        postcondition: Postcondition | None = None,
    ) -> Playbook:
        """Save the fix the host AI worked out, for that one step only.

        The new locators go to the front with a hit already recorded, and the dead ones
        are kept rather than dropped — a locator that fails today may be the one that
        works again after the site is reverted, and its miss count is evidence.

        `postcondition` replaces the step's check, for a fix after which the old check no
        longer holds. A read is checked by its element's css path, and that path is often
        exactly what moved: kept, it would call the repaired step broken on the next run.
        """
        fresh = [locator] if isinstance(locator, Locator) else list(locator)
        if not fresh:
            raise NoTrailError("a repair needs at least one way of finding the element")

        playbook = self._load(domain, task)
        step = next(s for s in playbook.steps if s.index == step_index)
        before = step.ranked_locators()[0].value if step.locators else "(nothing)"

        # Drop the routes that just failed and had nothing to show for themselves.
        # A locator with a real track record survives one miss and stays as a fallback.
        step.locators = [existing for existing in step.locators if not existing.is_dead]

        # Only the first is credited with the hit — it is the one actually confirmed.
        fresh[0].record_hit()
        step.locators = fresh + step.locators
        if postcondition is not None:
            step.postcondition = postcondition
        step.repairs += 1
        playbook.repairs += 1
        playbook.touch()

        after = fresh[0].value
        self.store.save_playbook(playbook)
        self.store.journal_repair(domain, step_index, before, after)
        self.events.emit(RepairSaved(index=step_index, before=before, after=after))
        self.events.emit(
            MemoryWrite(category="playbook", name=domain, detail=f"repaired step {step_index}")
        )
        return playbook

    # -------------------------------------------------------------- shared

    def _load(self, domain: str, task: str | None = None) -> Playbook:
        playbook = self.store.load_playbook(domain, task)
        self.events.emit(MemoryRead(category="playbook", name=domain, found=playbook is not None))
        if playbook is not None:
            return playbook

        # A site can hold several trails. "Which one?" and "never been here" are opposite
        # situations that demand opposite responses, so they must never share an error.
        # Reporting the second when the first was true is what made a host AI re-explore
        # a site it already knew, and save over what was there.
        known = self.store.trails_for(domain)
        if known:
            raise NeedsTask(
                f"{domain} is remembered, but not this task. Say which one you mean.",
                tasks=known,
            )
        raise NoTrailError(
            f"nothing remembered for {domain} — there is no trail to follow. "
            f"Explore it once and save, or restore the memory."
        )

    def _finish(
        self,
        playbook: Playbook,
        metrics: RunMetrics,
        started: float,
        *,
        succeeded: bool,
    ) -> None:
        metrics.duration_ms = int((time.perf_counter() - started) * 1000)
        metrics.succeeded = succeeded
        metrics.trail_repairs = playbook.repairs

        # Locator hit/miss counts were updated in place while replaying, so saving here
        # is what makes the trail get better every time it is walked.
        #
        # An aimed run is the exception, and it must never be written back. The playbook in
        # hand is a COPY with somebody else's subject in it: saving would overwrite the
        # trail that belongs to vouchley with pannly's addresses, and fold a run against a
        # different target into the health of a trail that was never asked to do it.
        playbook.runs += 1
        if self._aim is None:
            self.store.save_playbook(playbook)
        self.store.journal_run(metrics)

        self.events.emit(
            MemoryWrite(
                category="playbook",
                name=playbook.domain,
                detail=(
                    "scores updated"
                    if self._aim is None
                    else f"not written — this run was aimed at {self._aim[1]!r}"
                ),
            )
        )
        self.events.emit(
            RunFinished(
                domain=playbook.domain,
                succeeded=succeeded,
                duration_ms=metrics.duration_ms,
                steps_replayed=metrics.steps_replayed,
                trail_repairs=metrics.trail_repairs,
                model_calls=0,
            )
        )
