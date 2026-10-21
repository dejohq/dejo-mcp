"""Running a program: the steps an agent sent in one call, done one after another.

Learning a task used to cost one model turn per action, and a turn re-reads the whole
conversation (about 28k tokens in Claude Code before any tool says a word). A program lets
the agent send everything it can already see in one call. This file runs one:

- Each line runs through the same `Session` code a single `dejo_act` uses, so the trace a
  program leaves is exactly the trace hand-driven calls would have left.
- It stops at the FIRST line that fails, keeps the lines that passed (the "draft"), and
  hands back the page as it is now, so the agent's next call sends only the rest.
- A program that ends with a read saves the trail by itself. Nobody has to remember a save
  call: on 20 Oct 2026 an agent finished a task, never saved, and the next run explored the
  site from scratch.
- A step that buys, pays, sends, deletes or submits runs only when the agent marked it with
  `!`, and never runs twice on its own.

There is no model here, and nothing an agent wrote is evaluated: `program.py` turned the
text into data before this file ever sees it.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import Error as PlaywrightError

from . import program as language
from . import view as pageview
from .browser import NoSuchElement, domain_of
from .distill import distill
from .models import Locator, Playbook, Postcondition, SiteKnowledge, Step, utc_now
from .operations import ActionFailed, Session, TraceEntry, settles_into
from .program import Action, Expect, Look, Note, Pick, Program, Read
from .snapshot import Element, Snapshot
from .snapshot import parse as parse_controls
from .store import DejoStore

# A first page that answers with one of these is not a page to learn on.
HTTP_ERROR_FROM = 400

# `look all` and `look raw` hand back far more than a normal view. Past this a client stores
# the reply in a file and the agent spends a turn opening it (Claude Code saves results
# over 25k tokens or 50k characters), so the reply is cut here instead.
LOOK_CAP_CHARS = 30_000

# How many matches a "too many" stop names before saying "+N more".
MATCHES_SHOWN = 4

# A risky step that ran stays remembered this long. A retry of the whole program inside
# this window is almost always the agent resending lines after a later one failed, which
# must not pay or send a second time.
RISKY_MEMORY = timedelta(minutes=15)

# Stored locator kinds for the target words of the language. `testid` is stored as the
# attribute and value together (see `models.Locator`), so it is handled where it is built.
_LOCATOR_KIND = {"text": "text", "label": "label", "placeholder": "placeholder", "alt": "alt"}
_LOCATOR_KIND |= {"title": "title", "css": "css"}

# Actions that press something, so they can buy, send or delete. The rest only move,
# type or look.
PRESSES = frozenset({"click", "double_click", "tap", "dispatch_event"})

# Reads that answer about many elements at once, so several matches are the point.
_MANY_READS = {"count", "all_text"}


class _Stopped(Exception):
    """A line could not be done. The message says why, and how to fix it in a few words."""

    def __init__(self, reason: str, next_step: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.next_step = next_step


@dataclass
class Outcome:
    """What one program did. `text()` is the reply the agent reads."""

    task: str
    domain: str
    total: int
    passed: list[language.Step] = field(default_factory=list)
    stopped_at: language.Step | None = None
    reason: str = ""
    next_step: str = ""
    not_run: list[language.Step] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    saved: Playbook | None = None
    dropped: list[str] = field(default_factory=list)
    kept_in_draft: int = 0
    view: pageview.View | None = None
    raw: str = ""
    risky_steps: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.stopped_at is None

    def text(self) -> str:
        """The reply, always in the same order so an agent can read it at a glance."""
        lines: list[str] = []
        if self.stopped_at is not None:
            lines.append(
                f"stopped at line {self._number(self.stopped_at)} of {self.total}: "
                f"{_short(self.stopped_at)} -> {self.reason}"
            )
            if self.passed:
                done = " · ".join(f"{self._number(s)} {_short(s)}" for s in self.passed)
                lines.append(f"done (kept in the draft): {done}")
            if self.not_run:
                waiting = " · ".join(f"{self._number(s)} {_short(s)}" for s in self.not_run)
                lines.append(f"not run: {waiting}")
        elif self.saved is not None:
            lines.extend(self._saved_lines())
        elif self.passed:
            lines.append(
                f"done: {len(self.passed)} lines. Nothing saved yet ({self.kept_in_draft}"
                " steps in the draft)."
            )
        lines.extend(self._answer_lines())
        if self.raw:
            lines.append(self.raw)
        elif self.view is not None:
            lines.append(self.view.text)
        if self.next_step:
            lines.append(f"next: {self.next_step}")
        return "\n".join(lines)

    def _number(self, step: language.Step) -> int:
        return step.line

    def _saved_lines(self) -> list[str]:
        assert self.saved is not None
        steps = " · ".join(
            f"{step.index} {step.intent}{_stored_how(step)}" for step in self.saved.steps
        )
        found = [
            f'saved "{self.task}" on {self.domain}. {len(self.saved.steps)} steps. '
            "Next time: one dejo_run call.",
            f"steps: {steps}",
        ]
        if self.dropped:
            found.append("dropped as detours: " + " · ".join(self.dropped))
        if self.risky_steps:
            found.append("this task " + "; ".join(self.risky_steps) + " every time it runs")
        return found

    def _answer_lines(self) -> list[str]:
        return [
            f"{name} = {value}" + (f"  ({self.sources[name]})" if name in self.sources else "")
            for name, value in self.answers.items()
        ]


class Runner:
    """Runs programs for one task, in one browser, keeping the draft between them."""

    def __init__(self, session: Session, *, task: str, store: DejoStore | None = None) -> None:
        self.session = session
        self.browser = session.browser
        self.store = store if store is not None else session.store
        self.task = task
        self.domain = ""
        self._kept: list[Step] = []
        """Steps resumed from an earlier session's draft, which come before this session's
        own trace when the trail is saved."""
        self._view: pageview.View | None = None
        self._token = ""
        self._controls: dict[str, Element] = {}
        self._risky_ran: dict[str, datetime] = {}
        self._last_failure: tuple[str, str] | None = None
        self._last_entry: TraceEntry | None = None
        """The trace entry the latest action wrote, which an `expect` line right after it
        gives its check to."""

    # ------------------------------------------------------------------- looking

    def look(
        self, *, mode: str = "page", argument: str = "", focus: str = ""
    ) -> pageview.View | str:
        """Draw the page for the agent, and remember which refs this view handed out.

        Returns a View, or for `raw` Playwright's own snapshot text. Every look also goes
        into the site's map, exactly as `Session.look` does."""
        raw, frames = self.browser.raw_snapshot()
        url, title = self.browser.page.url, self.browser.page.title()
        self.domain = self.domain or domain_of(url)
        controls = parse_controls(raw, frames=frames)
        self.session.remember_page(Snapshot(url=url, title=title, elements=controls))
        self._controls = {element.aria_ref: element for element in controls}
        self._token = self.browser.mark_view()
        if mode == "raw":
            self._view = pageview.render(raw, url=url, title=title, frames=frames)
            return _capped(raw if not argument else _raw_from(raw, self._view, argument))
        words = " ".join(filter(None, [self.task, focus, argument if mode == "words" else ""]))
        self._view = pageview.render(
            raw,
            url=url,
            title=title,
            focus=words,
            frames=frames,
            start=argument if mode == "from" else "",
            group=argument if mode == "group" else "",
            everything=mode == "all",
        )
        return self._view

    # ------------------------------------------------------------------- running

    def run(self, written: Program, *, done: bool = False) -> Outcome:
        """Run every line in order. Stop at the first that fails. Save when finished."""
        outcome = Outcome(task=self.task, domain=self.domain, total=len(written.steps))
        steps = list(written.steps)
        read_something = False
        trace_before = len(self.session.trace)
        for at, step in enumerate(steps):
            try:
                if isinstance(step, Look):
                    self._finish_with_look(step, outcome)
                    outcome.passed.append(step)
                    break
                self._run_one(step, steps[at - 1] if at else None, outcome)
                read_something = read_something or isinstance(step, Read)
                outcome.passed.append(step)
            except _Stopped as stop:
                self._stop(outcome, step, stop, steps[at + 1 :])
                break
            except (ActionFailed, NoSuchElement, PlaywrightError, ValueError) as failed:
                self._stop(outcome, step, self._explain(failed), steps[at + 1 :])
                break

        outcome.domain = self.domain
        # Only what THIS program did. A download from an earlier program has already been
        # saved, and counting it again saved a later look as a new step.
        downloaded = any(entry.download for entry in self.session.trace[trace_before:])
        if outcome.ok and (read_something or downloaded or done) and self._has_steps():
            self._save(outcome)
        else:
            outcome.kept_in_draft = self._write_draft()
            if outcome.ok and outcome.view is None and not outcome.raw:
                self._show_page(outcome)
                outcome.next_step = (
                    "send more steps. If the answer is on this page, send read <ref> as "
                    "<name>: that read is what Dejo keeps. Answering from this view saves "
                    "nothing."
                )
        return outcome

    def _run_one(self, step: language.Step, before: language.Step | None, out: Outcome) -> None:
        if isinstance(step, Action):
            self._act(step)
        elif isinstance(step, Expect):
            self._expect(step, before)
        elif isinstance(step, Read):
            self._read(step, out)
        elif isinstance(step, Note):
            self._note(step)

    def _act(self, step: Action) -> None:
        if step.risky:
            self._refuse_a_repeat(step)
        element = self._element(step.target) if step.target else None
        second = self._element(step.second) if step.second else None
        value = step.value
        if step.action == "goto" and value:
            value = urljoin(self.browser.page.url, value)
        if step.action == "wait_for" and element is not None:
            value, element = f"element:{self._css_of(element)}", None
        if step.action == "restart_trail":
            self._start_over()
        if element is not None and not step.risky:
            self._refuse_unmarked_risk(step, element)
        written = len(self.session.trace)
        was = self.browser.page.url
        self.session.act_on(
            step.reason or _intent_of(step, element),
            step.action,
            element=element,
            value=value,
            second=second,
            risky=step.risky,
        )
        self._last_entry = self.session.trace[-1] if len(self.session.trace) > written else None
        if step.risky:
            self._risky_ran[step.text] = datetime.now(UTC)
        self.domain = self.domain or domain_of(self.browser.page.url)
        if self.browser.page.url != was:
            self._map_this_page()
        if step.action == "goto" and (self.browser.last_status or 0) >= HTTP_ERROR_FROM:
            raise _Stopped(
                f"the page answered HTTP {self.browser.last_status} instead of the page",
                "check the address; nothing on an error page is worth learning",
            )

    def _map_this_page(self) -> None:
        """Write the page a step just arrived on into the site's map, without showing it.

        A program walks through pages nobody looks at. Before programs, every page was
        looked at, so every page reached the map, and the map is what lets the NEXT task on
        a site start from known pages instead of from nothing. This keeps that: it costs a
        moment of browser time and no model tokens, since nothing here goes to the agent."""
        try:
            raw, frames = self.browser.raw_snapshot()
            controls = parse_controls(raw, frames=frames)
            page = self.browser.page
            self.session.remember_page(
                Snapshot(url=page.url, title=page.title(), elements=controls)
            )
        except PlaywrightError:
            return

    def _expect(self, step: Expect, before: language.Step | None) -> None:
        check = self._postcondition(step)
        if not settles_into(self.browser, check):
            raise _Stopped(
                f"{_describe_check(check)} did not hold",
                "the step before it may have done something else; look at the page below",
            )
        if isinstance(before, Action) and self._last_entry is not None:
            self._last_entry.expect = check
        self._last_entry = None

    def _read(self, step: Read, out: Outcome) -> None:
        element = None
        if step.target is not None:
            element = self._element(step.target, many=step.kind in _MANY_READS)
        answer = self.session.read_on(
            step.kind,
            element=element,
            attribute=step.attribute,
            remember=True,
            intent=step.name,
        )
        if answer in (None, "", []):
            raise _Stopped(
                "the read found nothing there",
                "the value may sit in another element; look at the page below",
            )
        out.answers[step.name] = ", ".join(answer) if isinstance(answer, list) else str(answer)
        where = _css_hint(element) if element is not None else step.kind
        out.sources[step.name] = f'read from {where} on "{self.browser.page.title()}"'

    def _note(self, step: Note) -> None:
        if self.store is None or not self.domain:
            return
        knowledge = self.store.load_site_knowledge(self.domain) or SiteKnowledge(domain=self.domain)
        self.store.save_site_knowledge(knowledge.merge(fact=step.fact))

    def _finish_with_look(self, step: Look, out: Outcome) -> None:
        try:
            shown = self.look(mode=step.mode, argument=step.argument)
        except pageview.ViewError as wrong:
            raise _Stopped(str(wrong)) from None
        if isinstance(shown, str):
            out.raw = shown
        else:
            out.view = shown
        out.next_step = "send steps, one per line. Refs work until the page changes."

    # ------------------------------------------------------------------- finding

    def _element(self, target: language.Target, *, many: bool = False) -> Element:
        """What a line points at, found strictly: one match, unless it picks one or reads
        many. A guess here is a wrong click written into a trail and replayed for ever."""
        if target.kind == "ref":
            return self._by_ref(target)
        if target.kind == "css" and target.pick is None:
            return self.session.element_by_selector(target.value, one=not many)
        return self._by_locator(target, many=many)

    def _by_ref(self, target: language.Target) -> Element:
        if self._view is None:
            raise _Stopped(
                f"{target.value} is a ref, but no view has been shown yet",
                'start with look, or use a target like link "Sign in"',
            )
        if not self.browser.view_is_current(self._token):
            raise _Stopped(
                f"{target.value} is from the page before an earlier line moved to a new page",
                "use the refs below, or a role, text or css target",
            )
        shown = self._view.targets.get(target.value)
        if shown is None:
            raise _Stopped(f"there is no {target.value} in the latest view", "use a ref below")
        element = self._controls.get(shown.aria_ref) or Element(
            ref=shown.ref,
            role=shown.node.role,
            name=shown.node.name[:80],
            aria_ref=shown.aria_ref,
            href=shown.node.href,
            frame=shown.frame,
        )
        if target.pick is None:
            return element
        if target.pick.kind == "has":
            raise _Stopped("has goes with a kind of element, not a ref", 'like: row has "Lagos"')
        return self._by_place(element, target.pick)

    def _by_place(self, element: Element, pick: Pick) -> Element:
        """`e145 first`: the first row's link, whichever book that is on the day."""
        assert self._view is not None
        found = _group_of(self._view, element.ref)
        if found is None:
            raise _Stopped(
                f"{element.ref} is not in a list, so {_pick_words(pick)} means nothing for it",
                f'drop {_pick_words(pick)}, or name the list with css "..." {_pick_words(pick)}',
            )
        peers = [self.browser.page.locator(f"aria-ref={ref}") for ref in found]
        place = self.browser.place_of(self.browser.locate(element), peers)
        if place is None:
            raise _Stopped(
                f"{element.ref} is in a list, but no one path finds its place in every row",
                f'write the path yourself: css "..." {_pick_words(pick)}',
            )
        wanted = _wanted_index(pick, place["count"])
        if place["index"] != wanted:
            raise _Stopped(
                f"{element.ref} is number {place['index'] + 1} of {place['count']} in its "
                f"list, not {_pick_words(pick)}",
                f"use the ref of the one that is {_pick_words(pick)}, or nth {place['index'] + 1}",
            )
        stored = Locator("css", place["selector"], nth=_stored_nth(pick), frame=element.frame)
        element.found_by = stored
        element.by_place = True
        return element

    def _by_locator(self, target: language.Target, *, many: bool) -> Element:
        base = _locator_for(target)
        matched = self.browser.matches(base)
        self.browser.resolve(base, visible=False)  # waits for a late element, briefly
        count = matched.count() if matched is not None else 0
        if count == 0:
            raise _Stopped(
                f"nothing on this page is {_target_words(target)}",
                "look at the page below for what it is called",
            )
        pick = target.pick
        if pick is None or pick.kind == "has":
            if pick is not None:
                base.has_text = pick.text
                narrowed = self.browser.matches(base)
                count = narrowed.count() if narrowed is not None else 0
                matched = narrowed
                if count == 0:
                    raise _Stopped(f'no {_target_words(target)} has "{pick.text}"')
            if count > 1 and not many:
                raise _Stopped(_too_many(target, count, matched), "add first, last or nth N")
            return Element(
                ref=_target_words(target), role=_role(target), name=target.value, found_by=base
            )
        wanted = _wanted_index(pick, count)
        if not 0 <= wanted < count:
            raise _Stopped(f"there are only {count} of {_target_words(target)}")
        base.nth = _stored_nth(pick)
        return Element(
            ref=_target_words(target),
            role=_role(target),
            name=target.value,
            found_by=base,
            by_place=True,
        )

    def _css_of(self, element: Element) -> str:
        if element.selector:
            return element.selector
        return self.browser.describe(element).css

    def _postcondition(self, step: Expect) -> Postcondition:
        if step.kind in ("url_contains", "text_present", "text_gone"):
            return Postcondition(step.kind, step.value)  # type: ignore[arg-type]
        assert step.target is not None
        if step.kind == "element_gone" and step.target.kind not in ("css",):
            raise _Stopped(
                "expect gone needs css or text: a ref points at something that may not be "
                "there any more",
                'like: expect gone css ".spinner", or expect gone text "Loading"',
            )
        if step.target.kind == "css":
            selector = step.target.value
        else:
            selector = self._css_of(self._element(step.target, many=step.kind == "count_is"))
        if step.kind in ("element_present", "element_gone"):
            return Postcondition(step.kind, selector)  # type: ignore[arg-type]
        return Postcondition(step.kind, step.value, target=selector)  # type: ignore[arg-type]

    # ------------------------------------------------------------------- risky

    def _refuse_unmarked_risk(self, step: Action, element: Element) -> None:
        """Stop BEFORE a press that buys, pays, sends, deletes or submits, unless the agent
        said so with `!`. Checked on the real element, so the agent's wording of the line
        cannot talk its way past it."""
        enter = step.action == "press" and (step.value or "").lower() == "enter"
        if step.action not in PRESSES and not enter:
            return
        risk = self.browser.risk_of(self.browser.locate(element), pressing_enter=enter)
        if risk:
            verb = step.text.split(" ", 1)[0]
            raise _Stopped(
                f"this {risk}, so it was not done",
                f"if the user asked for that, send it again as {verb}! with nothing after it "
                "except expect, read or look",
            )

    def _refuse_a_repeat(self, step: Action) -> None:
        ran = self._risky_ran.get(step.text)
        if ran is not None and datetime.now(UTC) - ran < RISKY_MEMORY:
            raise _Stopped(
                f"this already ran at {ran.astimezone().strftime('%H:%M')}, and it is marked "
                "! so it does not run twice",
                "send only the lines after it",
            )

    # ------------------------------------------------------------------- stopping

    def _stop(
        self, out: Outcome, step: language.Step, stop: _Stopped, rest: list[language.Step]
    ) -> None:
        out.stopped_at = step
        out.reason = stop.reason
        out.not_run = rest
        here = (step.text, self.browser.page.url)
        twice = self._last_failure == here
        self._last_failure = here
        out.next_step = (
            stop.next_step or "send the rest, starting with a fixed version of that line"
        )
        if twice:
            out.next_step += (
                ". It failed twice the same way: try look all, look raw, or a one-line "
                'js "..." program to see the page another way'
            )
        if self.browser.captcha_on_page():
            out.reason += "; a captcha is in the way"
            out.next_step = "ask the user to solve it in a signed-in window (dejo_login)"
        try:
            self._show_page(out, focus=step.text)
        except PlaywrightError:
            out.view = None

    def _show_page(self, out: Outcome, focus: str = "") -> None:
        shown = self.look(focus=focus)
        out.view = shown if isinstance(shown, pageview.View) else None

    def _explain(self, failed: Exception) -> _Stopped:
        text = str(failed).splitlines()[0] if str(failed) else type(failed).__name__
        if "intercepts pointer events" in str(failed):
            return _Stopped(
                "something covers it: " + _covering(str(failed)),
                'click that first, or dismiss css "..." to clear it every time',
            )
        return _Stopped(text)

    # ------------------------------------------------------------------- memory

    def _has_steps(self) -> bool:
        return bool(self._kept or self.session.trace)

    def _steps(self) -> tuple[list[Step], list[str]]:
        entries, dropped = drop_detours(self.session.trace)
        fresh = distill(entries, domain=self.domain, task=self.task).steps if entries else []
        steps = [*self._kept, *fresh]
        for index, step in enumerate(steps, start=1):
            step.index = index
        return steps, dropped

    def _save(self, out: Outcome) -> None:
        steps, dropped = self._steps()
        playbook = Playbook(domain=self.domain, task=self.task, steps=steps)
        if self.store is not None:
            self.store.save_playbook(playbook)
            self.store.drop_draft(self.domain, self.task)
        out.saved = playbook
        out.dropped = dropped
        out.risky_steps = [
            f"does step {step.index} ({step.intent})" for step in steps if step.risky
        ]

    def _write_draft(self) -> int:
        if self.store is None or not self.domain or not self._has_steps():
            return 0
        steps, _ = self._steps()
        draft = Playbook(domain=self.domain, task=self.task, steps=steps)
        draft.updated_at = utc_now()
        self.store.save_draft(draft)
        return len(steps)

    def _start_over(self) -> None:
        self._kept = []
        if self.store is not None and self.domain:
            self.store.drop_draft(self.domain, self.task)

    def continue_from(self, domain: str, steps: list[Step]) -> None:
        """Carry on from steps that have just run in this browser, without running them again.

        Two cases put the browser at the end of known steps: a trail that replayed (the agent
        may now add a read to it), and a trail that broke at step k (steps 1 to k-1 ran and
        held). Either way the next save must keep those steps, or a one-line addition would
        replace the whole trail with that one line."""
        self.domain = domain
        self._kept = [Step.from_dict(step.to_dict()) for step in steps]
        self.session.trace.clear()

    def resume(self, domain: str, *, profile: str | None = None) -> str:
        """Walk an earlier session's draft back to where it stopped, with no model calls.

        Replayed against a throwaway copy of memory: replay writes its run statistics back
        to the store, and doing that against the real one would turn a half-learned draft
        into a trail. Returns one line for the reply, or "" when there is no draft."""
        from .executor import Executor  # local import keeps the module graph acyclic

        self.domain = domain
        draft = self.store.load_draft(domain, self.task) if self.store is not None else None
        if draft is None or not draft.steps:
            return ""
        risky = next((step for step in draft.steps if step.risky), None)
        if risky is not None:
            return (
                f"draft not resumed: its step {risky.index} ({risky.intent}) already did "
                "something that must not happen twice. Continue from the page below by hand."
            )
        with tempfile.TemporaryDirectory(prefix="dejo-draft-") as scratch:
            throwaway = DejoStore(db_path=str(Path(scratch) / "draft.db"))
            try:
                throwaway.save_playbook(Playbook(domain=domain, task=self.task, steps=draft.steps))
                result = Executor(throwaway, self.browser, profile=profile).run(
                    domain, task=self.task
                )
            finally:
                throwaway.close()
        if not result.ok:
            self._start_over()
            return "the draft could not be walked again (the site changed), so it was dropped"
        self._kept = [Step.from_dict(step.to_dict()) for step in draft.steps]
        return (
            f"draft: {len(self._kept)} steps kept from {draft.updated_at[11:16]} UTC, "
            "continuing from here"
        )


# ----------------------------------------------------------------------- detours


def drop_detours(trace: list[TraceEntry]) -> tuple[list[TraceEntry], list[str]]:
    """Take wrong turns out of a trace before it becomes a trail, by fixed rules only.

    Only lines that passed are ever in the trace, but a passed line can still be a wrong
    turn, and a saved wrong turn is replayed for ever. Two rules, and nothing else is dropped:

    1. `back` removes itself and the step before it, when it returns to the page that step
       started on.
    2. A `goto` removes the run of pure navigation just before it (link clicks that moved,
       goto, back, forward), as long as nothing in that run changed anything: a goto names
       its own destination, so the way there was never needed.
    """
    kept = list(trace)
    dropped: list[str] = []
    index = 1
    while index < len(kept):
        entry, before = kept[index], kept[index - 1]
        if entry.action == "back" and before.navigated and entry.url_after == before.url_before:
            dropped.extend([before.intent, entry.intent])
            del kept[index - 1 : index + 1]
            index = max(index - 1, 1)
            continue
        index += 1
    index = 0
    while index < len(kept):
        if kept[index].action == "goto":
            start = index
            while start > 0 and _pure_navigation(kept[start - 1]):
                start -= 1
            if start < index:
                dropped.extend(entry.intent for entry in kept[start:index])
                del kept[start:index]
                index = start
        index += 1
    return kept, dropped


def _pure_navigation(entry: TraceEntry) -> bool:
    if entry.risky:
        return False
    if entry.action in ("goto", "back", "forward"):
        return True
    return entry.action == "click" and entry.navigated and not entry.download


# ----------------------------------------------------------------------- small helpers


def _group_of(view: pageview.View, ref: str) -> list[str] | None:
    """Playwright refs of the elements in the same place as `ref` in every OTHER row of the
    list it sits in, or None when it is in no list."""
    for group in view.groups.values():
        for row in group.rows:
            for column, item in enumerate(row):
                if item.ref != ref:
                    continue
                peers = []
                for other in group.rows:
                    if other is row:
                        continue
                    if len(other) <= column or other[column].kind != item.kind:
                        return None
                    peers.append(other[column].node.aria_ref)
                return peers
    return None


def _wanted_index(pick: Pick, count: int) -> int:
    if pick.kind == "first":
        return 0
    if pick.kind == "last":
        return count - 1
    return pick.number - 1


def _stored_nth(pick: Pick) -> int:
    """Stored the way `Locator.nth` counts: 0 is the first, -1 the last."""
    if pick.kind == "first":
        return 0
    if pick.kind == "last":
        return -1
    return pick.number - 1


def _pick_words(pick: Pick) -> str:
    return f"nth {pick.number}" if pick.kind == "nth" else pick.kind


def _locator_for(target: language.Target) -> Locator:
    if target.kind == "testid":
        return Locator("test_id", f"data-testid={target.value}")
    if target.kind in _LOCATOR_KIND:
        return Locator(_LOCATOR_KIND[target.kind], target.value)  # type: ignore[arg-type]
    return Locator("role", f"{target.kind}|{target.value}")


def _role(target: language.Target) -> str:
    return "" if target.kind in _LOCATOR_KIND or target.kind == "testid" else target.kind


def _target_words(target: language.Target) -> str:
    return f'{target.kind} "{target.value}"' if target.value else target.kind


def _too_many(target: language.Target, count: int, matched: Any) -> str:
    shown = []
    for index in range(min(count, MATCHES_SHOWN)):
        try:
            words = " ".join(matched.nth(index).inner_text().split())[:40]
        except PlaywrightError:
            words = ""
        shown.append(f'"{words}"' if words else f"#{index + 1}")
    more = f", +{count - MATCHES_SHOWN}" if count > MATCHES_SHOWN else ""
    return f"{count} matches for {_target_words(target)}: {', '.join(shown)}{more}"


def _describe_check(check: Postcondition) -> str:
    if check.target:
        return f"{check.kind} {check.value!r} at {check.target}"
    return f"{check.kind} {check.value!r}"


def _css_hint(element: Element) -> str:
    if element.by_place and element.found_by is not None:
        return f"{element.found_by.value} (by place)"
    return element.css or element.selector or element.ref


def _stored_how(step: Step) -> str:
    only = step.locators[0] if len(step.locators) == 1 else None
    if only is not None and only.nth is not None:
        return " (by place)"
    if step.locators:
        return " (by name)"
    return ""


def _intent_of(step: Action, element: Element | None) -> str:
    """The line as the step's intent, in words that still mean something next month.

    The intent is stored in the trail and shown to whoever repairs it. Two things in the
    line do not belong there: a ref (`e12` means nothing once this page is gone), which is
    replaced by what the element was called, and anything typed into a field. The line
    `fill label "Password" "hunter2"` written there would put the password in memory even
    though the value itself is kept as a secret."""
    text = step.text
    if step.target is not None and step.target.kind == "ref" and element is not None:
        called = f'{element.role} "{element.name}"' if element.name else element.role
        text = text.replace(step.target.value, called or step.target.value, 1)
    if step.action in ("fill", "type") and step.value is not None:
        verb = text.split(" ", 1)[0]
        return f"{verb} {_target_words(step.target)}" if step.target else verb
    return text


def _short(step: language.Step) -> str:
    return step.text if len(step.text) <= 80 else step.text[:79] + "…"


def _capped(text: str) -> str:
    if len(text) <= LOOK_CAP_CHARS:
        return text
    return text[:LOOK_CAP_CHARS] + "\n+ cut here. Use look raw from <ref> for the rest."


def _raw_from(raw: str, view: pageview.View, ref: str) -> str:
    shown = view.targets.get(ref)
    if shown is None:
        raise pageview.ViewError(f"there is no {ref} on this page")
    marker = f"[ref={shown.aria_ref}]"
    at = raw.find(marker)
    return raw[raw.rfind("\n", 0, at) + 1 :] if at >= 0 else raw


def _covering(message: str) -> str:
    for line in message.splitlines():
        if "intercepts pointer events" in line:
            return line.strip()[:120]
    return "another element"
