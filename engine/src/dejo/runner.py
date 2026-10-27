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
- After a replay broke at one step, a one-line program doing what that step did is its fix:
  the step is repaired in place and the rest of the trail replays in the same call.

There is no model here, and nothing an agent wrote is evaluated: `program.py` turned the
text into data before this file ever sees it.
"""

from __future__ import annotations

import json
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

from playwright.sync_api import Error as PlaywrightError

from . import program as language
from . import view as pageview
from . import waits
from .actions import PRESSES
from .browser import NoSuchElement, domain_of
from .distill import distill, locators_for, postcondition_for
from .models import Locator, Playbook, Postcondition, SiteKnowledge, Step, href_path, utc_now
from .operations import (
    READ_ACTION,
    ActionFailed,
    Session,
    TraceEntry,
    check_postcondition,
    settles_into,
)
from .program import Action, Expect, Look, Note, Pick, Program, Read
from .snapshot import Element, Snapshot
from .snapshot import parse as parse_controls
from .store import DejoStore

if TYPE_CHECKING:
    from .executor import ReplayResult

# A first page that answers with one of these is not a page to learn on.
HTTP_ERROR_FROM = 400
# Answers that mean "not you", not "not here". Told "check the address" for a 403, an agent
# tried four other addresses on a site that turns every automated browser away (22 Oct).
SIGN_IN_FIRST = 401
REFUSED = frozenset({403, 429})

# `look all` and `look raw` hand back far more than a normal view. Past this a client stores
# the reply in a file and the agent spends a turn opening it (Claude Code saves results
# over 25k tokens or 50k characters), so the reply is cut here instead.
LOOK_CAP_CHARS = 30_000

# `look raw from eN` stops at the end of eN's section: one of these, the nearest above it.
# A form is printed as one only when it has a name, so the cap below is what holds the rest.
SECTION_ROLES = frozenset(
    {"form", "dialog", "alertdialog", "region", "article", "main", "table", "contentinfo"}
)
# At most this many raw lines from a ref: a long form fits, a page's footer does not.
RAW_FROM_LINES = 80
_RAW_ROLE = re.compile(r"""^\s*- ['"]?([a-z]+)""")
_RAW_REF = re.compile(r"\[ref=([^\]]+)\]")

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

# Locator kinds made of an element's own words. Only these can contain the value being
# read; a css path's numbers are positions, not values.
_WORDED_LOCATORS = frozenset({"role", "text", "label", "title", "alt", "placeholder"})

# A css path that names something (an id, a class, an attribute), not only tags in order.
_PATH_MARKS = re.compile(r"[#.\[]")

# Locator kinds that find an element by what it is called, not where it is.
_NAMING_LOCATORS = _WORDED_LOCATORS | {"test_id", "structural"}

# Reads that hand back only a part of their element, so the element may be the whole page.
_PART_READS = frozenset({"passage"})

# Reads that answer about many elements at once, so several matches are the point.
_MANY_READS = {"count", "all_text"}

# A read is one value the user asked for: a price, a date, a name, a short note. Past this it
# is a section or the whole page, and every replay would hand all of it back. Seen 23 Oct:
# `read css "body"` was saved as the answer to "which BCP is about DNSSEC".
LONGEST_ANSWER = 2_000

# What a `js` line returned, as printed. Agents used to write it into document.title to see
# it at all (23 Oct), so it is shown; past this it would crowd out the page view.
JS_RESULT_LIMIT = 2_000
WHOLE_PAGE = frozenset({"body", "html", ":root"})

# Every reply that shows a page and saved nothing ends with this. Seen 21-22 Oct: a call that
# ended with `look` got only "send steps", the agent read the answer off that view, and the
# task was never saved, so the next run learned it again from nothing.
KEEP_THE_ANSWER = (
    "send more steps, one per line. If the answer is on this page, send read <ref> as "
    "<name>: that read is what Dejo keeps. Answering from this view saves nothing."
)


class _Stopped(Exception):
    """A line could not be done. The message says why, and how to fix it in a few words."""

    def __init__(self, reason: str, next_step: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.next_step = next_step


@dataclass
class _Broken:
    """A replay that stopped at one step, waiting for the line that fixes it."""

    step: Step
    answers: dict[str, str]
    """What the reads before the broken step said. The fix does not run them again."""
    profile: str | None = None


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
    repaired: Step | None = None
    """The trail step this program fixed in place, as it was saved."""
    unsaved: str = ""
    """Why steps that would have made a trail were kept only as a draft."""
    looks: list[str] = field(default_factory=list)
    """What the looks before the last line showed, in order."""
    after_sending: list[str] = field(default_factory=list)
    """For each `!` line, what the page said while it settled, which may be gone by now; and
    for any line that opened a tab, which tab."""
    js_result: str | None = None
    """What a `js` line returned, as JSON. Not an answer: it is never saved or replayed."""
    trail_total: int = 0
    tail: ReplayResult | None = None
    """The replay of the steps after the repaired one. When it did not finish, the reply
    about why is the server's, the same one a plain replay that stopped would get."""

    @property
    def ok(self) -> bool:
        return self.stopped_at is None

    def text(self) -> str:
        """The reply, always in the same order so an agent can read it at a glance."""
        if self.repaired is not None:
            return "\n".join(self._repaired_lines())
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
            if self.unsaved:
                lines.append(self.unsaved)
        lines.extend(self._answer_lines())
        lines.extend(self.after_sending)
        if self.js_result is not None:
            lines.append(f"js returned: {_capped_line(self.js_result, JS_RESULT_LIMIT)}")
        if self.looks:
            # All the looks together stay under the one cap a reply has (see LOOK_CAP_CHARS).
            room = LOOK_CAP_CHARS - len(self.raw or (self.view.text if self.view else ""))
            lines.append(_capped("\n".join(self.looks), max(room, 0)))
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

    def _repaired_lines(self) -> list[str]:
        assert self.repaired is not None
        step = self.repaired
        lines = [
            f"repaired step {step.index} of {self.trail_total} ({step.intent}): the new way "
            "goes first and the old ones stay as backups."
        ]
        if self.tail is not None and not self.tail.ok:
            return lines
        if self.tail is not None:
            lines.append(
                f"done: steps {step.index + 1}-{self.trail_total} replayed in "
                f"{self.tail.metrics.duration_ms} ms, no page reading."
            )
            lines.extend(f"saved file: {path}" for path in self.tail.saved_files)
        lines.extend(self._answer_lines())
        lines.append(
            "next: report the answer and stop."
            if self.answers
            else "next: the task is done, and the trail is saved with the fix."
        )
        return lines

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
        self._broken: _Broken | None = None
        """Set while a replay that broke waits for its fix. See `fix_from`."""
        self._changed_by_code: list[str] = []
        """The `js` lines that changed the page since the trail began. See `_code_in_the_way`."""

    # ------------------------------------------------------------------- looking

    def look(
        self, *, mode: str = "page", argument: str = "", focus: str = ""
    ) -> pageview.View | str:
        """Draw the page for the agent, and remember which refs this view handed out.

        Returns a View, or for `raw` Playwright's own snapshot text. Every look also goes
        into the site's map, exactly as `Session.look` does."""
        raw, frames = self.browser.raw_snapshot()
        url, title = self.browser.page.url, self.browser.page.title()
        icons = self.browser.icon_names(pageview.nameless_controls(raw))
        modal = self.browser.modal_dialogs(pageview.dialogs(raw))
        self.domain = self.domain or domain_of(url)
        controls = parse_controls(raw, frames=frames)
        self.session.remember_page(Snapshot(url=url, title=title, elements=controls))
        self._controls = {element.aria_ref: element for element in controls}
        self._token = self.browser.mark_view()
        if mode == "raw":
            self._view = pageview.render(
                raw, url=url, title=title, frames=frames, icons=icons, modal=modal
            )
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
            find=argument if mode == "words" else "",
            icons=icons,
            modal=modal,
        )
        return self._view

    # ------------------------------------------------------------------- running

    def run(self, written: Program, *, done: bool = False) -> Outcome:
        """Run every line in order. Stop at the first that fails. Save when finished."""
        outcome = Outcome(task=self.task, domain=self.domain, total=len(written.steps))
        steps = list(written.steps)
        fixing = self._fix_for(written)
        read_something = False
        trace_before = len(self.session.trace)
        for at, step in enumerate(steps):
            try:
                if isinstance(step, Look) and at < len(steps) - 1:
                    # Agents write "look, then read". The page is shown when the program ends
                    # or stops anyway, so a plain look in the middle has nothing to add, and
                    # refusing it cost a whole turn (real-site bench, 21-23 Oct 2026). A look
                    # that asks for something (`look g2`, `look raw from e5`) is shown where
                    # it stands: only the last one used to be.
                    if step.mode != "page":
                        outcome.looks.append(self._shown(step))
                    outcome.passed.append(step)
                    continue
                if isinstance(step, Look):
                    self._finish_with_look(step, outcome)
                    outcome.passed.append(step)
                    break
                written, was = len(self.session.trace), self.browser.page.url
                self._run_one(step, steps[at - 1] if at else None, outcome)
                if isinstance(step, Action) and self.browser.page.url != was:
                    self._refuse_a_human_check(written)
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
        if fixing is not None and outcome.ok:
            self._repair(fixing, outcome)
        elif outcome.ok and (read_something or downloaded or done) and self._has_steps():
            if self._changed_by_code:
                self._code_in_the_way(outcome)
            else:
                self._save(outcome)
        else:
            outcome.kept_in_draft = self._write_draft()
            if outcome.ok and outcome.view is None and not outcome.raw:
                self._show_page(outcome)
            if outcome.ok:
                outcome.next_step = KEEP_THE_ANSWER
        return outcome

    def _fix_for(self, written: Program) -> _Broken | None:
        """The broken step this program fixes in place, if it is one line doing what that
        step did: the same action on a new target, with the same value. Anything else, a
        different action or several lines, replaces the steps from the broken one on."""
        broken = self._broken
        if broken is None or len(written.steps) != 1:
            return None
        line, step = written.steps[0], broken.step
        if isinstance(line, Read) and line.target is not None:
            kind = f"{line.kind}:{line.attribute}" if line.attribute else line.kind
            return broken if step.action == READ_ACTION and step.value == kind else None
        if isinstance(line, Action) and line.target is not None and line.action == step.action:
            # A password is never stored, so a fill of a secret matches whatever was typed.
            same_value = step.secret is not None or (line.value or None) == (step.value or None)
            return broken if same_value else None
        return None

    def _repair(self, broken: _Broken, out: Outcome) -> None:
        """Write the line that just ran into the broken step, then walk the rest of the trail.

        Only that step changes. The new ways of finding its element go first, the old ones
        that ever worked stay behind them as backups (a site that moves back finds them
        again), and the steps before it do not run again: a risky one among them already
        happened once. Before this, a fix was a second call that replayed from step 1."""
        from .executor import Executor  # local import keeps the module graph acyclic

        assert self.store is not None
        entry, step = self.session.trace[-1], broken.step
        # The old check stays when it still holds. A read is checked by its element's css
        # path, often the very thing that moved, and then the check is taken from what the
        # fix did, as a newly learned step's would be.
        holds = check_postcondition(self.browser, step.postcondition)
        executor = Executor(self.store, self.browser, profile=broken.profile)
        playbook = executor.apply_repair(
            self.domain,
            step.index,
            locators_for(entry),
            task=self.task,
            postcondition=None if holds else postcondition_for(entry),
        )
        self.store.drop_draft(self.domain, self.task)
        self._broken = None
        out.answers = {**broken.answers, **out.answers}
        out.repaired = next(saved for saved in playbook.steps if saved.index == step.index)
        out.trail_total = len(playbook.steps)
        if step.index < len(playbook.steps):
            tail = executor.run(self.domain, task=self.task, resume_at=step.index + 1)
            out.answers.update({name: str(value) for name, value in tail.answers.items()})
            # A tail that breaks again waits for its own fix, and must still hand every
            # answer so far to the reply that finally finishes the task.
            tail.answers = dict(out.answers)
            out.tail = tail
            if not tail.ok:
                return
        saved = self.store.load_playbook(self.domain, self.task) or playbook
        self.continue_from(self.domain, saved.steps)

    def _run_one(self, step: language.Step, before: language.Step | None, out: Outcome) -> None:
        if isinstance(step, Action):
            self._act(step, out)
        elif isinstance(step, Expect):
            self._expect(step, before)
        elif isinstance(step, Read):
            self._read(step, out)
        elif isinstance(step, Note):
            self._note(step)

    def _act(self, step: Action, out: Outcome) -> None:
        if step.risky:
            self._refuse_a_repeat(step)
        waiting = step.action == "wait_for" and step.target is not None
        if waiting and step.target.kind != "ref":
            self._wait_to_appear(step.target)
        element = self._element(step.target, many=waiting) if step.target else None
        if element is not None and not element.name and not element.selector:
            # Read now, so the step can say what it is: `click button in "AI agents"`, not
            # `click button`, which reads as any button at all.
            element = self.browser.describe(element)
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
        before = self.browser.page_state() if step.action == "evaluate" else ""
        title = self.browser.page.title() if step.action == "evaluate" else ""
        did = self.session.act_on(
            step.reason or _intent_of(step, element),
            step.action,
            element=element,
            value=value,
            second=second,
            risky=step.risky,
        )
        self._last_entry = self.session.trace[-1] if len(self.session.trace) > written else None
        if step.action == "evaluate":
            out.js_result = _as_text(did["result"])
            if self.browser.page_state() != before:
                self._changed_by_code.append(_short(step))
            self._put_the_title_back(title, out)
        if step.risky:
            self._risky_ran[step.text] = datetime.now(UTC)
            out.after_sending.append(_after_sending(step, did))
        for tab in did.get("opened") or []:
            out.after_sending.append(
                f"line {step.line} opened a new tab: {tab}. This call stayed in the tab it was "
                "in; to work in the new one, send: tab latest"
            )
        self.domain = self.domain or domain_of(self.browser.page.url)
        if self.browser.page.url != was:
            self._map_this_page()
        status = self.browser.last_status or 0
        if step.action == "goto" and status == SIGN_IN_FIRST:
            raise _Stopped(
                "the site answered HTTP 401: it wants a sign-in first",
                "call dejo_login so the user signs in, then run this again",
            )
        if step.action == "goto" and status in REFUSED:
            raise _Stopped(
                f"the site refused this browser (HTTP {status})",
                "it is not the address: this site turns automated browsers away. Tell the "
                "user, and do not try other addresses on it",
            )
        if step.action == "goto" and status >= HTTP_ERROR_FROM:
            raise _Stopped(
                f"the page answered HTTP {status} instead of the page",
                "check the address; nothing on an error page is worth learning",
            )

    def _put_the_title_back(self, title: str, out: Outcome) -> None:
        """Undo a `js` line's write to the page's title.

        Before `js` results were shown, agents wrote them into document.title to see them,
        and every later reply named the page by that ("read from pre on 'B:Free=flex-1…'",
        launchit.site). What a `js` line returns is shown now, so the title is the page's."""
        if self.browser.page.title() == title:
            return
        with suppress(PlaywrightError):
            self.browser.page.evaluate("(title) => { document.title = title; }", title)
        out.after_sending.append(
            "the js line changed the page's title; its own title was put back. What js "
            "returns is shown in the reply, so nothing needs writing to the title"
        )

    def _wait_to_appear(self, target: language.Target) -> None:
        """Wait up to the usual timeout for what a `wait` line names, before it is looked up.

        A wait is for something that is not there yet. Looked up first, the way every other
        line is, `wait css "..."` failed at once with "nothing on this page matches" while
        saashub.com's list still said "Loading..."."""
        found = self.browser.matches(
            Locator("css", target.value) if target.kind == "css" else _locator_for(target)
        )
        try:
            if found is None:
                raise PlaywrightError("not a target this page can be asked for")
            found.first.wait_for(state="visible", timeout=waits.DEFAULT_WAIT_MS)
        except PlaywrightError:
            raise _Stopped(
                f"waited {waits.DEFAULT_WAIT_MS // 1000} s for {_target_words(target)} and it "
                "never appeared",
                "look at the page below for what it shows instead",
            ) from None

    def _refuse_a_human_check(self, written: int) -> None:
        """Stop the moment a step lands on a human check instead of the page.

        Seen 22 Oct on three real sites: Cloudflare's "Performing security verification" was
        shown to the agent as if it were the site, the agent sent `wait` three times, and
        the waits went into the draft. Nothing done on that page is a step."""
        if self.browser.captcha_on_page() is None:
            return
        del self.session.trace[written:]
        raise _Stopped("the site showed a human check instead of the page")

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
        if step.kind not in _MANY_READS and _whole_page(element, answer, part=step.kind):
            if self.session.trace:
                self.session.trace.pop()
            if step.kind in _PART_READS:
                raise _Stopped(
                    f"that part is {len(str(answer)):,} characters, more than one answer may "
                    f"be ({LONGEST_ANSWER:,})",
                    "name a smaller part: a lower heading, or words from the one paragraph "
                    "that answers",
                )
            raise _Stopped(
                f"that read is the whole page ({len(str(answer)):,} characters), and every "
                "replay would hand all of it back",
                "read the element that holds the answer instead, or only the part of this "
                f'one that does: read passage "a heading or words in it" '
                f"{_target_line(step.target)} as {step.name}",
            )
        entry = self.session.trace[-1] if self.session.trace else None
        kept = entry.element if entry is not None else None
        if entry is not None and kept is not None and step.kind not in _MANY_READS:
            entry.locators = self._lasting(kept.locators(), answer)
        if (
            element is not None
            and kept is not None
            and not (
                entry.locators
                if entry is not None and entry.locators is not None
                else kept.locators()
            )
        ):
            # A read nobody can find again would be saved, report success, and break on
            # every replay. Seen 21 Oct on a paragraph with no id and no unique path.
            self.session.trace.pop()
            raise _Stopped(
                f"read {step.target.value if step.target else ''} worked, but Dejo found no "
                "way to find that element again, so it would not replay",
                'name it with css instead, like: read css ".author-born-date" as born',
            )
        out.answers[step.name] = ", ".join(answer) if isinstance(answer, list) else str(answer)
        where = _css_hint(element) if element is not None else step.kind
        out.sources[step.name] = f'read from {where} on "{self.browser.page.title()}"'

    def _lasting(self, found: list[Locator], answer: Any) -> list[Locator]:
        """The ways of finding a read's element that will still find it tomorrow.

        A read is stored to answer again when the value has CHANGED, which is the point of
        reading it. GitHub's open-issue link is named "Open (172)", and stored by that name
        it found nothing the day the count was 174. So a locator that contains the value is
        dropped, and so is one that matched more than one element when it was learned:
        on replay it would read whichever came first."""
        said = " ".join(str(answer).split())
        numbers = re.findall(r"\d+", said)
        kept = []
        for locator in found:
            words = " ".join(locator.value.split())
            names_it = locator.kind in _WORDED_LOCATORS
            if names_it and ((said and said in words) or any(n in words for n in numbers)):
                continue
            matched = self.browser.matches(replace(locator, nth=locator.nth))
            if matched is not None and matched.count() == 1:
                kept.append(locator)
        return kept

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

    def _shown(self, step: Look) -> str:
        """What a look in the middle of a program shows, as text."""
        try:
            shown = self.look(mode=step.mode, argument=step.argument)
        except pageview.ViewError as wrong:
            raise _Stopped(str(wrong)) from None
        return shown if isinstance(shown, str) else shown.text

    # ------------------------------------------------------------------- finding

    def _element(self, target: language.Target, *, many: bool = False) -> Element:
        """What a line points at, found strictly: one match, unless it picks one or reads
        many. A guess here is a wrong click written into a trail and replayed for ever."""
        if target.kind == "ref":
            return self._by_ref(target)
        if target.kind == "css" and target.pick is None:
            self._one_css_match(target, many=many)
            return self.session.element_by_selector(target.value, one=not many)
        return self._by_locator(target, many=many)

    def _one_css_match(self, target: language.Target, *, many: bool) -> None:
        """Refuse a css target that matches several elements, in this language's words.

        The session's own refusal tells a caller to add `" >> nth=0"`, which is how the old
        read tool spelt it; an agent writing steps copied that into a program and failed
        again (21 Oct benchmark). Here the fix is `first`, `last` or `nth N`."""
        if many:
            return
        try:
            matched = self.browser.page.locator(target.value)
            count = matched.count()
        except PlaywrightError:
            raise _Stopped(f"{target.value!r} is not a CSS selector the browser accepts") from None
        if count > 1:
            raise _Stopped(_too_many(target, count, matched), "add first, last or nth N")

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
        shown = self._view.find(target.value)
        if shown is None:
            raise _Stopped(f"there is no {target.value} on this page", "use a ref below")
        element = self._controls.get(shown.aria_ref) or Element(
            ref=shown.ref,
            role=shown.node.role,
            name=shown.node.name[:80],
            aria_ref=shown.aria_ref,
            href=shown.node.href,
            frame=shown.frame,
        )
        if not self._still_there(shown.aria_ref):
            element = self._redrawn(element, target.value)
        if target.pick is None:
            return element
        if target.pick.kind == "has":
            raise _Stopped("has goes with a kind of element, not a ref", 'like: row has "Lagos"')
        return self._by_place(element, target.pick)

    def _still_there(self, aria_ref: str) -> bool:
        try:
            return self.browser.page.locator(f"aria-ref={aria_ref}").count() > 0
        except PlaywrightError:
            return False

    def _redrawn(self, element: Element, ref: str) -> Element:
        """The page is the same document, but the site drew this element again, so its ref
        no longer resolves. Seen on GitHub on 21 Oct: a read of a counter timed out.

        It is found again only by its role and name, and only when exactly one element on
        the page has both: that is the same control drawn twice, not a look-alike."""
        gone = _Stopped(
            f"{ref} is gone: the site redrew that part of the page",
            'look again for fresh refs, or name it: role "name" or css',
        )
        if not element.role or not element.name:
            raise gone
        again = Locator("role", f"{element.role}|{element.name}", frame=element.frame)
        matched = self.browser.matches(again)
        if matched is None or matched.count() != 1:
            raise gone
        return Element(
            ref=element.ref,
            role=element.role,
            name=element.name,
            found_by=again,
            frame=element.frame,
        )

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
        if out.passed:
            # Seen 21 Oct: an agent resent the whole program, and `click e15` from the old
            # page pressed a different e15 on the new one, which was then saved as a step.
            out.next_step += (
                f". Do not send lines 1-{step.line - 1} again: they ran and are kept, and "
                "the refs below are for the page as it is now"
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
        steps = _latest_reads([*self._kept, *fresh])
        if steps and steps[0].action != "goto" and not self._kept:
            # A trail that does not open its own page starts wherever the browser happens to
            # be, which on replay is a blank page (real-site bench, 23 Oct 2026).
            start = next((e.url_before for e in entries if e.url_before.startswith("http")), "")
            if start:
                steps.insert(0, _go_to(start))
        for index, step in enumerate(steps, start=1):
            step.index = index
        return steps, dropped

    def _save(self, out: Outcome) -> None:
        self._broken = None
        self._changed_by_code = []
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
        if out.answers:
            # Seen 23 Oct: the saved read said 205 (the wrong column), the agent answered 261
            # from the view, and every replay then answered 205.
            said = "; ".join(f"{name} = {value}" for name, value in out.answers.items())
            out.next_step = (
                f"every replay will answer {_capped_line(said)}. If that is the answer, report "
                "it exactly as read and stop. If it is not, send the right read now with the "
                "same name: it replaces this one."
            )

    def _code_in_the_way(self, out: Outcome) -> None:
        """Keep the steps as a draft and say why they are not a trail.

        A `js` line is never part of a trail: code cannot be checked or repaired when the
        site changes. When one changed the page, a trail saved without it would replay up to
        where that change was needed and stop there (launchit.site: Python was set only by
        `js`, and the saved trail would have stopped at a disabled Continue)."""
        out.kept_in_draft = self._write_draft()
        lines = " · ".join(self._changed_by_code)
        out.unsaved = (
            f"not saved: the page was changed by code ({lines}), and a trail cannot replay "
            "code, so every replay would stop where that change was needed."
        )
        out.next_step = (
            "do that change with steps Dejo can replay (fill, select, check, click), starting "
            "with restart if the order matters. If only code can do it, tell the user this "
            "task cannot be saved, and report the answer above"
        )

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
        self._changed_by_code = []
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
        self._broken = None

    def fix_from(
        self,
        domain: str,
        playbook: Playbook,
        index: int,
        *,
        answers: dict[str, Any],
        profile: str | None = None,
    ) -> None:
        """A replay of `playbook` broke at step `index`, and the browser stands there.

        Steps before it ran and are kept. The next program, if it is one line doing what
        that step did, repairs the step and replays the rest (`_repair`); several lines
        replace the steps from `index` on, exactly as learning would."""
        self.continue_from(domain, playbook.steps[: index - 1])
        step = next(step for step in playbook.steps if step.index == index)
        self._broken = _Broken(
            step=Step.from_dict(step.to_dict()),
            answers={name: str(value) for name, value in answers.items()},
            profile=profile,
        )

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
    3. A field typed into again removes the first try and the key presses and clicks after
       it, when all of them stayed on the same page and none is risky: the second try
       replaces the first. Seen 23 Oct on a shop: one search typed twice, with a click on the
       "Searched for:" heading between, all kept, and the replay landed on the wrong product.
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
    index = 0
    while index < len(kept):
        again = _typed_again(kept, index)
        if again is not None:
            dropped.extend(entry.intent for entry in kept[index:again])
            del kept[index:again]
            continue
        index += 1
    return kept, dropped


def _typed_again(trace: list[TraceEntry], first: int) -> int | None:
    """Where the same field is typed into again after `trace[first]`, if only key presses
    and clicks that stayed on the page come between. None otherwise."""
    entry = trace[first]
    if entry.action not in ("fill", "type") or entry.element is None or entry.risky:
        return None
    page = href_path(entry.url_before)
    for later in range(first + 1, len(trace)):
        other = trace[later]
        if (
            other.action == entry.action
            and other.element is not None
            and (other.element.css == entry.element.css)
        ):
            return later
        same_page = href_path(other.url_after) == page and href_path(other.url_before) == page
        if other.risky or other.action not in ("press", "click") or not same_page:
            return None
    return None


def _latest_reads(steps: list[Step]) -> list[Step]:
    """Each read name once: a read sent again under the same name replaces the earlier one."""
    later: set[str] = set()
    kept: list[Step] = []
    for step in reversed(steps):
        if step.action == READ_ACTION:
            if step.intent in later:
                continue
            later.add(step.intent)
        kept.append(step)
    return kept[::-1]


def _go_to(url: str) -> Step:
    """The first step of a trail that did not begin with one: open the page its first step
    was taken on."""
    return Step(
        index=0,
        intent=f"go {url}",
        action="goto",
        value=url,
        postcondition=Postcondition("url_contains", href_path(url)),
    )


def _after_sending(step: Action, did: dict[str, Any]) -> str:
    """What a `!` line's page said while it settled, for the reply."""
    said = " · ".join(f'"{message}"' for message in did.get("said") or [])
    told = [f"the page said: {said}" if said else "no message appeared"]
    failed = did.get("failed_requests") or []
    if failed:
        told.append("requests that failed: " + " · ".join(failed))
    elif not said:
        told[0] += " and no request failed; the page below shows where it stands"
    return f"after line {step.line} ({_short(step)}): " + "; ".join(told)


def _whole_page(element: Element | None, answer: Any, *, part: str = "") -> bool:
    """Is this read the whole page? A `passage` of the page is not, while it stays short."""
    whole = element is not None and (element.css or "").strip().lower() in WHOLE_PAGE
    if whole and part not in _PART_READS:
        return True
    return len(str(answer)) > LONGEST_ANSWER


def _as_text(value: Any) -> str:
    """A script's return as JSON, the way it would print in a browser console."""
    return json.dumps(value, ensure_ascii=False, default=str)


def _capped_line(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


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
    """How a saved step finds its element, said truly: a css path alone is a place in the
    page, and launchit.site's chip cross saved that way read "(by name)"."""
    only = step.locators[0] if len(step.locators) == 1 else None
    if only is not None and only.nth is not None:
        return " (by place)"
    if any(locator.kind in _NAMING_LOCATORS for locator in step.locators):
        return " (by name)"
    if any(":has-text(" in locator.value for locator in step.locators):
        return " (by the words beside it)"
    if any(_PATH_MARKS.search(locator.value) for locator in step.locators):
        return " (by css)"
    if step.locators:
        return " (by position)"
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
        if not element.name and element.beside:
            called = f'{element.role or "it"} in "{element.beside}"'.lstrip()
        text = text.replace(step.target.value, called or step.target.value, 1)
    if step.action in ("fill", "type") and step.value is not None:
        verb = text.split(" ", 1)[0]
        return f"{verb} {_target_words(step.target)}" if step.target else verb
    return text


def _target_line(target: language.Target | None) -> str:
    """A target as a line writes it."""
    if target is None:
        return ""
    return target.value if target.kind == "ref" else f'{target.kind} "{target.value}"'


def _short(step: language.Step) -> str:
    return step.text if len(step.text) <= 80 else step.text[:79] + "…"


def _capped(text: str, limit: int = LOOK_CAP_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n+ cut here. Use look raw from <ref> for the rest."


def _raw_from(raw: str, view: pageview.View, ref: str) -> str:
    """The raw page from `ref` to the end of the section it sits in, at most RAW_FROM_LINES
    lines, ending with where the rest starts.

    It used to run to the end of the page: from a form's first field on mcpserver.dev that
    was the whole footer, about 200 lines, when only the form was wanted."""
    shown = view.find(ref)
    if shown is None:
        raise pageview.ViewError(f"there is no {ref} on this page")
    lines = raw.splitlines()
    marker = f"[ref={shown.aria_ref}]"
    start = next((at for at, line in enumerate(lines) if marker in line), 0)
    end = _end_of_section(lines, start)
    if end - start > RAW_FROM_LINES:
        end, more = start + RAW_FROM_LINES, "+ more: look raw from {}"
    else:
        more = "the page goes on: look raw from {}"
    following = _first_ref(lines[end:], view)
    tail = [more.format(following)] if following else []
    return "\n".join([*lines[start:end], *tail])


def _end_of_section(lines: list[str], start: int) -> int:
    """Where the section holding line `start` ends: the next line no deeper than the
    nearest SECTION_ROLES line above it. The end of the page when there is none."""
    depth = _indent(lines[start])
    for above in range(start - 1, -1, -1):
        indent = _indent(lines[above])
        if indent >= depth:
            continue
        depth = indent
        role = _RAW_ROLE.match(lines[above])
        if role is not None and role.group(1) in SECTION_ROLES:
            return next(
                (at for at in range(start + 1, len(lines)) if _indent(lines[at]) <= indent),
                len(lines),
            )
    return len(lines)


def _first_ref(lines: list[str], view: pageview.View) -> str:
    """The first ref an agent can use in these raw lines, as Dejo prints it."""
    dejo_ref = {target.aria_ref: ref for ref, target in view.known.items()}
    for line in lines:
        for aria_ref in _RAW_REF.findall(line):
            if aria_ref in dejo_ref:
                return dejo_ref[aria_ref]
    return ""


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _covering(message: str) -> str:
    for line in message.splitlines():
        if "intercepts pointer events" in line:
            return line.strip()[:120]
    return "another element"
