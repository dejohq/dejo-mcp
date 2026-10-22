"""Dejo as MCP tools. This is the product.

Your own AI (Claude Code, Cursor, Codex) is the brain. Dejo gives it a browser and a memory.
There is no model call anywhere in this file or anything it imports.

Five tools, because every turn an agent takes re-reads the whole conversation, and the tool
list is part of it. Measured on 20 Oct 2026: sixteen tools were 29,024 characters of
definitions, and a learning run took 8-12 turns where Playwright MCP took 4-7. Now:

    dejo_run      everything on a website: replay a known task, show a new page, run the
                  steps the agent sends, save. Loaded up front in Claude Code, so it can be
                  called on the very first turn.
    dejo_login    the user signs in by hand, in a visible window.
    dejo_profile  several signed-in roles side by side.
    dejo_memory   read what Dejo remembers.
    dejo_manage   change what Dejo remembers.

Every reply is one block of plain text. A JSON object with a dozen keys costs more to read
and Codex drops a text block whenever structured content is set, so there is none.

Every tool is a few lines that call into the `dejo` package. If something here starts
needing real logic, that logic belongs in the engine instead.

Never print to stdout: stdio is the MCP transport and a stray print corrupts it.
"""

from __future__ import annotations

import contextlib
import functools
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from dejo import program
from dejo.browser import (
    DEFAULT_PROFILE,
    DEFAULT_PROFILE_NAME,
    DEFAULT_PROFILES_DIR,
    NoDisplay,
    ProfileUnavailable,
    domain_of,
    profile_named,
)
from dejo.executor import Executor, NeedsTask, NoTrailError, ReplayResult
from dejo.home import setting
from dejo.models import SiteKnowledge
from dejo.operations import Session
from dejo.runner import Runner
from dejo.store import DejoStore, TrailAlreadyHere, rank_tasks
from dejo.worker import BrowserWorker
from mcp import types
from mcp.server.lowlevel import Server

# Who was in use last, kept beside the profiles it names so an agent with its own
# DEJO_PROFILES_DIR keeps its own answer. A file, not a folder, so listing profiles never
# sees it.
ACTIVE_PROFILE_FILE = ".active"

# How many rows a memory listing shows. A site with sixty mapped pages would otherwise be a
# wall of text in front of the line that matters.
MAX_LISTED = 25

# Claude Code loads a tool marked with this key before the first turn, instead of waiting
# for the agent to search for it. One search turn costs about 28k tokens of re-read context,
# and the agent needs `dejo_run` on every website task, so it is loaded up front. Other
# clients ignore keys they do not know. https://code.claude.com/docs/en/mcp.md
ALWAYS_LOAD = {"anthropic/alwaysLoad": True}

# Read by every client on every turn, so every word is paid for again and again. Codex
# reads only the first 512 characters, so everything that matters is in those.
INSTRUCTIONS = (
    "Dejo is a real browser with memory. Use dejo_run for ANY website task: read a value, "
    "fill a form, download a file, check a dashboard. Use it instead of curl, fetch or "
    "WebFetch: those cannot sign in or click, and nothing they do is remembered. One "
    "dejo_run call replays a task Dejo knows, with no page reading. On a new task it returns "
    "the page; send the steps in the next dejo_run call and Dejo saves them. If the user must "
    "sign in: dejo_login. Several roles on one site: dejo_profile."
)

RUN_DESCRIPTION = (
    "Use for ANY website task: read a value, fill a form, download, check a page. A "
    "real browser with memory: a task done once is replayed later with no page "
    "reading.\n"
    "\n"
    "Call with site, task and url. Known task: Dejo replays it and returns the "
    "answer. New task: Dejo opens the url and returns the page, one line per element,"
    " each with a ref (e12). Then call again with steps, one per line. They run in "
    "order. Dejo stops at the first step that fails and returns the page there.\n"
    "\n"
    "Steps:\n"
    "go URL\n"
    'click T | fill T "text" | select T "option" | check T | press Enter\n'
    "read T as name   (the value you will report)\n"
    'expect url "part" | expect text "words" | expect see T\n'
    "look words       (show the page, these words first)\n"
    'Also: back, hover T, wait T, upload T "file", tab N.\n'
    'T is a ref, or role "name" (link "Travel"), text "...", label "...", css "...". '
    "Add first, last or nth 3 to mean that place in a list, not that item.\n"
    "Write click! (or fill! etc.) for a step that buys, pays, sends, deletes or "
    "submits.\n"
    "\n"
    "Passed steps are kept. When all steps pass and one is a read (or a file "
    "downloads), the task is saved. done=true saves a task that reads nothing."
)

LOGIN_DESCRIPTION = (
    "Sign in to a website, website login, SSO, Google sign-in, one-time code. Opens a "
    "visible browser window so the USER signs in; never type a password you were not given. "
    "Call with site, tell the user to sign in there, then call again with done=true. Signs "
    "in the current profile only, and it stays signed in."
)

PROFILE_DESCRIPTION = (
    "Website profiles and roles: customer, vendor, admin. A profile is a whole signed-in "
    "browser; several stay signed in side by side. With a name: switch to it (made on first "
    "use). Without: list them. Trails are shared by every profile."
)

MEMORY_DESCRIPTION = (
    "What Dejo remembers about websites. Read only. what=sites lists every trail and its "
    "health; what=show gives one trail's steps; what=map lists pages seen on a site (with "
    "path: that page's controls); what=commons lists trails other agents shared."
)

MANAGE_DESCRIPTION = (
    "Change what Dejo remembers about a website. do=forget removes a site (or one task) for "
    "good; do=note keeps a fact that is not a step (needs 2FA, use the finance account); "
    "do=share offers a trail to other agents (typed values never leave); do=borrow takes a "
    "shared trail."
)


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


# The order is fixed: a client that caches the tool list between turns keeps hitting it.
TOOLS = [
    types.Tool(
        name="dejo_run",
        description=RUN_DESCRIPTION,
        inputSchema=_schema(
            {
                "site": {"type": "string", "description": "domain or URL"},
                "task": {
                    "type": "string",
                    "description": "the job in plain words; the trail's name",
                },
                "url": {"type": "string", "description": "where to start"},
                "steps": {"type": "string", "description": "step lines, see above"},
                "done": {"type": "boolean"},
                "profile": {
                    "type": "string",
                    "description": "signed-in role to use, e.g. admin",
                },
            },
            ["site", "task"],
        ),
        _meta=ALWAYS_LOAD,
    ),
    types.Tool(
        name="dejo_login",
        description=LOGIN_DESCRIPTION,
        inputSchema=_schema(
            {
                "site": {"type": "string"},
                "done": {"type": "boolean", "description": "the user says they are signed in"},
                "confirmed": {
                    "type": "boolean",
                    "description": "user insists, though a sign-in page still shows",
                },
            },
            ["site"],
        ),
    ),
    types.Tool(
        name="dejo_profile",
        description=PROFILE_DESCRIPTION,
        inputSchema=_schema({"name": {"type": "string"}}, []),
    ),
    types.Tool(
        name="dejo_memory",
        description=MEMORY_DESCRIPTION,
        inputSchema=_schema(
            {
                "what": {"type": "string", "enum": ["sites", "show", "map", "commons"]},
                "site": {"type": "string"},
                "task": {"type": "string"},
                "path": {"type": "string"},
            },
            ["what"],
        ),
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="dejo_manage",
        description=MANAGE_DESCRIPTION,
        inputSchema=_schema(
            {
                "do": {"type": "string", "enum": ["forget", "note", "share", "borrow"]},
                "site": {"type": "string"},
                "task": {"type": "string"},
                "text": {"type": "string", "description": "the fact, for note"},
            },
            ["do", "site"],
        ),
        annotations=types.ToolAnnotations(destructiveHint=True),
    ),
]


def log(message: str) -> None:
    """stderr only. stdout belongs to the MCP transport."""
    print(f"[dejo] {message}", file=sys.stderr, flush=True)


@dataclass
class Reply:
    """What one tool call says back: plain text, and whether nothing could run at all.

    A program that stopped at a failing step is NOT an error. It ran, it reports where it
    stopped, and the agent carries on from there."""

    text: str
    error: bool = False


class DejoTools:
    """Holds this connection's browsers, its one memory store, and the tasks being learned.

    Browsers, plural. A profile is a whole signed-in browser (its own cookies, session and
    Chrome process) and Dejo keeps as many as are asked for, side by side. That is what lets
    a customer, a vendor and an admin be signed in AT ONCE, without the order of the work
    starting to matter.
    """

    def __init__(
        self,
        *,
        db_path: str | None = None,
        headless: bool = True,
        downloads: str | None = None,
        profile: str | None = None,
        profiles_dir: str | None = None,
        agent: str | None = None,
    ):
        self.store = DejoStore(db_path=db_path, agent=agent)
        # What `default` means on this machine: whatever was already in use, so naming
        # profiles never moves an existing sign-in.
        self.profile = profile if profile is not None else str(DEFAULT_PROFILE)
        self.profiles_dir = Path(profiles_dir) if profiles_dir else DEFAULT_PROFILES_DIR
        # Whoever was in use last time, not `default`; see `_remember_active`.
        self.active = self._remembered_active()
        self.downloads = downloads
        self.headless = headless
        self._workers: dict[str, BrowserWorker] = {}
        self._runners: dict[tuple[str, str, str], Runner] = {}
        self._login_worker: BrowserWorker | None = None

    def path_for(self, name: str) -> str:
        """The browser folder one profile uses."""
        where = profile_named(name, default=self.profile, root=self.profiles_dir)
        return str(where) if where else ""

    @property
    def worker(self) -> BrowserWorker:
        """The browser for the profile in use, started the first time it is needed."""
        running = self._workers.get(self.active)
        if running is None:
            running = BrowserWorker(
                headless=self.headless,
                downloads=self.downloads,
                profile=self.path_for(self.active),
            )
            self._workers[self.active] = running
        return running

    def runner(self, domain: str, task: str) -> Runner:
        """The learning run for one task, in the profile in use, kept for this connection.

        One per task and profile: a trace belongs to the browser that made it, and two
        tasks learned in turn must not mix their steps into one trail."""
        key = (self.active, domain, task)
        existing = self._runners.get(key)
        if existing is None:
            self.worker.start()
            session = Session(self.worker.browser, self.store)  # type: ignore[arg-type]
            existing = Runner(session, task=task, store=self.store)
            self._runners[key] = existing
        return existing

    def carry_on(self, domain: str, task: str, ran: str) -> Runner:
        """The runner for the trail `ran`, reachable by the words the agent used too.

        The agent asks in its own words and a trail with other words answers ("the same
        job"). Its next call uses its own words again, and if that found no runner, a fix
        meant for the trail started a new task of its own instead."""
        runner = self.runner(domain, ran)
        self._runners[(self.active, domain, task)] = runner
        return runner

    def learning(self, domain: str, task: str) -> bool:
        return (self.active, domain, task) in self._runners

    def forget_runs(self, domain: str) -> None:
        """Drop the learning runs for a site that was just forgotten."""
        for key in [key for key in self._runners if key[1] == domain]:
            del self._runners[key]

    @property
    def secrets_profile(self) -> str:
        """Which profile a password is looked up under. Always a name, `default` included,
        so a missing-secret message can say which profile it looked in."""
        return self.active

    def use(self, name: str) -> str:
        """Work as a different profile from now on. Made on first use, and remembered."""
        self.active = name.strip() or DEFAULT_PROFILE_NAME
        self._remember_active()
        return self.active

    def _remember_active(self) -> None:
        """Write down who is in use, so a restart does not silently become somebody else.

        An MCP server restarts whenever its client does. Losing the profile there meant a
        run that had been an admin for an hour came back as `default`, signed in to nothing.
        Failing to write it is not worth stopping a run for."""
        with contextlib.suppress(OSError):
            self.profiles_dir.mkdir(parents=True, exist_ok=True)
            (self.profiles_dir / ACTIVE_PROFILE_FILE).write_text(self.active, encoding="utf-8")

    def _remembered_active(self) -> str:
        marker = self.profiles_dir / ACTIVE_PROFILE_FILE
        try:
            name = marker.read_text(encoding="utf-8").strip()
        except OSError:
            return DEFAULT_PROFILE_NAME
        return name or DEFAULT_PROFILE_NAME

    def known_profiles(self) -> list[dict[str, Any]]:
        """Every profile this machine has, and whether its browser is up."""
        names = {DEFAULT_PROFILE_NAME, self.active} | set(self._workers)
        if self.profiles_dir.exists():
            names |= {folder.name for folder in self.profiles_dir.iterdir() if folder.is_dir()}
        return [
            {
                "name": name,
                "active": name == self.active,
                "open": name in self._workers and self._workers[name].running,
            }
            for name in sorted(names)
        ]

    def take_profile_note(self) -> str | None:
        """Hand over the one-time note about a browser swap, and clear it."""
        browser = self.worker.browser
        note = getattr(browser, "profile_note", None) if browser is not None else None
        if note:
            browser.profile_note = None
        return note

    def open_login_window(self, url: str) -> None:
        """Show a real browser window so a person can sign in themselves.

        Chrome allows one process per profile, so the working browser lets go of it first.
        Only the profile being signed into lets go; the others stay open and signed in."""
        self.worker.stop()
        for key in [key for key in self._runners if key[0] == self.active]:
            del self._runners[key]
        self._login_worker = BrowserWorker(
            headless=False, downloads=self.downloads, profile=self.path_for(self.active)
        )
        self._login_worker.start()
        self._login_worker.submit(lambda browser: browser.goto(url))

    def login_window(self) -> tuple[str, bool] | None:
        """Where the sign-in window is, and whether it still shows a sign-in page. None
        when there is no window to ask."""
        if self._login_worker is None:
            return None
        try:
            return self._login_worker.submit(lambda browser: browser.sign_in_window())
        except Exception:  # noqa: BLE001 - a window that cannot be asked is a window that is gone
            return None

    def finish_login(self) -> None:
        if self._login_worker is None:
            return
        self._login_worker.stop()
        self._login_worker = None

    @property
    def signing_in(self) -> bool:
        return self._login_worker is not None

    def close(self) -> None:
        if self._login_worker is not None:
            self._login_worker.stop()
            self._login_worker = None
        for running in self._workers.values():
            running.stop()
        self._workers.clear()
        self._runners.clear()


# ----------------------------------------------------------------------------- dejo_run


def dejo_run(
    tools: DejoTools,
    *,
    site: str,
    task: str,
    url: str | None = None,
    steps: str | None = None,
    done: bool = False,
    profile: str | None = None,
) -> Reply:
    if profile:
        tools.use(profile)
    key = domain_of(site)
    # Only an explicit `url` moves where a remembered trail starts. A site written as an
    # address is where a NEW task opens, and nothing more: taking it as an override sent the
    # replay of "open the payments page" to the home page.
    first_page = url or (site if "://" in site else None)
    if steps is not None or done:
        return _run_steps(tools, key, task, steps or "", done, first_page)
    if tools.learning(key, task) and tools.store.load_playbook(key, task) is None:
        # Called again without steps while the task is still being learned and nothing is
        # saved yet: show the page where learning stands. A saved trail always replays.
        return _first_look(tools, key, task, first_page, again=True)
    return _replay_or_look(tools, key, task, url, first_page)


def _run_steps(
    tools: DejoTools, key: str, task: str, steps: str, done: bool, first_page: str | None
) -> Reply:
    try:
        written = program.parse(steps) if steps.strip() else program.Program()
    except program.ProgramError as wrong:
        return Reply(f"nothing ran: {wrong}", error=True)
    fresh = not tools.learning(key, task)
    runner = tools.runner(key, task)
    resumed = ""
    if fresh:
        resumed = tools.worker.submit(
            lambda _browser: runner.resume(key, profile=tools.secrets_profile)
        )
        # Steps sent with a url on the very first call mean "start there, then do these".
        # Only then: an agent that repeats the url on a later call must not be sent back
        # to the start in the middle of a task.
        if first_page and not resumed.startswith("draft:"):
            written = program.parse(f"go {first_page}\n{steps}")
    outcome = tools.worker.submit(lambda _browser: runner.run(written, done=done))
    said = outcome.text()
    if outcome.tail is not None and not outcome.tail.ok:
        # The fix held and the rest of the trail stopped later on. Why it stopped is said
        # exactly as for any replay, including a second "broke at step".
        said += "\n" + _after_replay(tools, key, task, outcome.tail).text
    return Reply(_with_header(tools, said, resumed))


def _replay_or_look(
    tools: DejoTools, key: str, task: str, url: str | None, first_page: str | None
) -> Reply:
    try:
        result = tools.worker.submit(
            lambda browser: Executor(tools.store, browser, profile=tools.secrets_profile).run(
                key, task=task, start_url=url
            )
        )
    except NeedsTask as other:
        known = rank_tasks(task, other.tasks, domain=key)
        return _first_look(tools, key, task, first_page, known=known)
    except NoTrailError:
        return _first_look(tools, key, task, first_page)
    if url and result.wrong_place:
        # The agent named a url, often just the site's front page, but the trail starts
        # somewhere else and could not begin there. Seen 21 Oct: a trail that starts on the
        # Issues page was sent to the repo page, and the agent then read the wrong count off
        # that page. One more replay from the trail's own start costs no model turn.
        result = tools.worker.submit(
            lambda browser: Executor(tools.store, browser, profile=tools.secrets_profile).run(
                key, task=task
            )
        )
    return _after_replay(tools, key, task, result)


def _first_look(
    tools: DejoTools,
    key: str,
    task: str,
    start: str | None,
    *,
    known: list[str] | None = None,
    again: bool = False,
) -> Reply:
    """A task Dejo has not learned: open the page and show it, so the agent can send steps
    in its very next call. The "not known" turn and the first look are one reply."""
    lines = [] if again else _about_the_site(tools, key, task, known or [])
    offered = not tools.store.was_forgotten(key) and tools.store.offers_for(key)
    if offered and start is None and not again:
        # Somebody already walked this site. Opening the page would invite learning it
        # all over again, so the reply stops at the offer. A `url` says "learn it myself".
        lines.append(
            "next: borrow it with dejo_manage do=borrow, then dejo_run with that task. "
            "Only if it is not the job, call dejo_run again with url to learn it yourself."
        )
        return Reply("\n".join(lines))
    runner = tools.runner(key, task)
    resumed = (
        ""
        if again
        else tools.worker.submit(lambda _browser: runner.resume(key, profile=tools.secrets_profile))
    )
    if resumed.startswith("draft:") or again:
        written = program.parse("look")
    else:
        written = program.parse(f"go {start or 'https://' + key + '/'}\nlook")
    outcome = tools.worker.submit(lambda _browser: runner.run(written))
    if outcome.ok and outcome.view is not None:
        lines.extend(filter(None, [resumed, outcome.view.text]))
        lines.append(
            "next: send steps, one per line, in the next dejo_run call. End with read <ref> "
            "as <name>, EVEN IF the answer is already on this page: that read is what Dejo "
            "saves, so next time this task is one call with no page reading. Refs work until "
            "the page changes."
        )
        return Reply(_with_note(tools, "\n".join(lines)))
    return Reply(_with_header(tools, outcome.text(), "\n".join(lines)))


def _about_the_site(tools: DejoTools, key: str, task: str, known: list[str]) -> list[str]:
    lines = [f'new task "{task}" on {key} (profile {tools.active}). Nothing saved for it yet.']
    knowledge = tools.store.load_site_knowledge(key)
    if knowledge is not None and knowledge.summary():
        lines.append("site facts: " + "; ".join(knowledge.summary()))
    if known:
        listed = ", ".join(f'"{name}"' for name in known[:MAX_LISTED])
        lines.append(
            f"other tasks Dejo knows here: {listed}. If one of these is the job, call "
            "dejo_run again with that task; it costs one call and no page reading."
        )
    offers = [] if tools.store.was_forgotten(key) else tools.store.offers_for(key)
    if offers:
        first = offers[0]
        lines.append(
            f'another agent shared a trail here: "{first["task"]}" (by {first["shared_by"]}). '
            "To use it instead of learning: dejo_manage do=borrow."
        )
    if tools.store.was_forgotten(key):
        lines.append(f"{key} was forgotten on purpose, so nothing shared is offered back.")
    return lines


def _after_replay(tools: DejoTools, key: str, task: str, result: ReplayResult) -> Reply:
    ran = result.metrics.task
    if result.ok and result.already_done:
        return Reply(
            f'done: nothing to do. {key} is already in the state "{ran}" creates. '
            "Do not repair anything; carry on with what the user asked."
        )
    if result.ok:
        return Reply(_with_note(tools, _replayed(tools, key, task, result)))
    if result.blocked:
        return Reply(
            "stopped: a captcha is in the way. The trail is fine and nothing was marked "
            "broken. Ask the user to open the site, clear the check, and say when to try again."
        )
    if result.page_error is not None:
        return Reply(
            f"stopped: the page answered HTTP {result.page_error}, so nothing was read. Tell "
            "the user it could not be opened (deleted, moved, or not shared with this account)."
        )
    if result.needs_login:
        return Reply(
            f"stopped: {key} wants a sign-in. Do not guess a password: call dejo_login, ask "
            "the user to sign in in the window, then dejo_login done=true, then dejo_run again."
        )
    if result.wrong_place:
        return Reply(
            f"stopped: {result.reason} Nothing is broken; the trail starts from a page you "
            "are not on. If it is a sign-in and you are signed in, the work is done."
        )
    if result.aimed_at:
        was, now = result.aimed_at
        return Reply(
            f'stopped: this trail is for "{was}" and you asked about "{now}". Dejo followed '
            f'the same route aimed at "{now}" and could not see it on the page. Nothing is '
            "broken; it may not exist here, or it is reached another way."
        )
    if result.stale:
        return _first_look(tools, key, task, None)
    if result.repair is not None:
        return _broke(tools, key, task, result)
    return Reply(f"stopped: {result.reason}", error=True)


def _replayed(tools: DejoTools, key: str, task: str, result: ReplayResult) -> str:
    ran = result.metrics.task
    playbook = tools.store.load_playbook(key, ran)
    if playbook is not None:
        tools.carry_on(key, task, ran).continue_from(key, playbook.steps)
    lines = [
        f'done: "{ran}" on {key} (profile {tools.active}), {result.metrics.steps_replayed} '
        f"steps replayed in {result.metrics.duration_ms} ms, no page reading."
    ]
    if task != ran:
        lines.append(f'you asked for "{task}"; this is the trail "{ran}", the same job.')
    lines.extend(f"{name} = {value}" for name, value in result.answers.items())
    lines.extend(f"saved file: {path}" for path in result.saved_files)
    if playbook is not None:
        risky = [f"step {s.index} ({s.intent})" for s in playbook.steps if s.risky]
        if risky:
            lines.append("this task does " + ", ".join(risky) + " every time it runs")
    if result.answers:
        lines.append(
            "next: report the answer exactly as read and stop. Every step was checked as it ran."
        )
    else:
        lines.append(
            "next: the trail reads no value. If the task needs one, send steps: read T as "
            "name. It is added to this trail. If the task was only to DO something, it is done."
        )
    return "\n".join(lines)


def _broke(tools: DejoTools, key: str, task: str, result: ReplayResult) -> Reply:
    """Replay broke at one step: keep the steps before it and show the page there.

    The browser stays where it broke, so the agent's next call is a fix for that step and
    nothing more: one line repairs it in place and Dejo replays the rest itself."""
    assert result.repair is not None
    broken, ran = result.repair, result.metrics.task
    at = broken.step_index
    playbook = tools.store.load_playbook(key, ran)
    total = len(playbook.steps) if playbook is not None else at
    runner = tools.carry_on(key, task, ran)
    if playbook is not None:
        runner.fix_from(key, playbook, at, answers=result.answers, profile=tools.secrets_profile)
    view = tools.worker.submit(lambda _browser: runner.look(focus=broken.intent))
    shown = view.text if hasattr(view, "text") else str(view)
    tried = f" (tried {len(broken.tried)} ways)" if broken.tried else ""
    lines = [f"broke at step {at} of {total}: {broken.intent}{tried}"]
    if at > 1:
        lines.append(f"steps 1-{at - 1} passed and are kept.")
    rest = f"runs steps {at + 1}-{total} itself" if at < total else "saves the trail with the fix"
    lines += [
        shown,
        f"next: send ONE line that does step {at} on this page: the same action, aimed at "
        f"what replaced it. Dejo keeps the old ways as backups and {rest}. Several lines "
        f"replace steps {at}-{total} instead.",
    ]
    return Reply(_with_note(tools, "\n".join(lines)))


def _with_header(tools: DejoTools, text: str, header: str) -> str:
    return _with_note(tools, "\n".join(filter(None, [header, text])))


def _with_note(tools: DejoTools, text: str) -> str:
    note = tools.take_profile_note()
    return f"{text}\nnote: {note}" if note else text


# ----------------------------------------------------------------------------- the rest


def dejo_login(
    tools: DejoTools, *, site: str, done: bool = False, confirmed: bool = False
) -> Reply:
    key = domain_of(site)
    if not done:
        target = site if "://" in site else f"https://{site}"
        try:
            tools.open_login_window(target)
        except (NoDisplay, ProfileUnavailable) as cannot:
            return Reply(str(cannot), error=True)
        return Reply(
            f"a browser window is open on {target} (profile {tools.active}). Tell the user to "
            "sign in there however the site asks, and to say when they are done. Then call "
            "dejo_login with done=true. Call no other Dejo tool until then: the window holds "
            "the browser."
        )
    if not tools.signing_in:
        return Reply("no sign-in window is open: call dejo_login first", error=True)
    window = tools.login_window()
    if window is None:
        tools.finish_login()
        return Reply(
            "the sign-in window was closed before Dejo could check it, so it cannot tell "
            "whether the sign-in finished. Call dejo_run; if the site still asks, call "
            "dejo_login again and leave the window open until the user is done."
        )
    _, still_signing_in = window
    if still_signing_in and not confirmed:
        return Reply(
            "the window still shows a sign-in page, so it is still open. Ask the user to "
            "finish and tell you, then call again. If they say they ARE signed in, call with "
            "confirmed=true."
        )
    tools.finish_login()
    knowledge = tools.store.load_site_knowledge(key) or SiteKnowledge(domain=key)
    knowledge.merge(
        fact="signed in by hand; Dejo keeps the session in its browser profile", needs_login=True
    )
    tools.store.save_site_knowledge(knowledge)
    return Reply(
        f"signed in to {key} and the window is closed. No password or code was kept, only the "
        "browser session, the way a browser keeps it. Call dejo_run again."
    )


def dejo_profile(tools: DejoTools, *, name: str | None = None) -> Reply:
    if name is None:
        rows = [
            f"{p['name']}{' (in use)' if p['active'] else ''}{' open' if p['open'] else ''}"
            for p in tools.known_profiles()
        ]
        return Reply("profiles: " + ", ".join(rows) + ". Call with a name to switch.")
    was, now = tools.active, tools.use(name)
    return Reply(
        f"now working as {now} (was {was}). If this profile is not signed in to the site yet, "
        "call dejo_login once; it stays signed in."
    )


def dejo_memory(
    tools: DejoTools,
    *,
    what: str,
    site: str | None = None,
    task: str | None = None,
    path: str | None = None,
) -> Reply:
    if what == "sites":
        return Reply(_sites(tools))
    if what == "commons":
        offers = tools.store.every_offer()
        if not offers:
            return Reply("no agent has shared a trail yet")
        return Reply(
            "\n".join(f'{o["domain"]} · "{o["task"]}" · by {o["shared_by"]}' for o in offers)
        )
    if not site:
        return Reply(f"what={what} needs a site", error=True)
    key = domain_of(site)
    if what == "show":
        return Reply(_show(tools, key, task))
    return Reply(_map(tools, key, path))


def _sites(tools: DejoTools) -> str:
    rows = []
    for domain in tools.store.list_sites():
        for name in tools.store.trails_for(domain) or [None]:
            playbook = tools.store.load_playbook(domain, name)
            if playbook is not None:
                rows.append(
                    f'{domain} · "{playbook.task}" · {len(playbook.steps)} steps · '
                    f"{playbook.runs} runs · health {playbook.health:.2f}"
                )
    return "\n".join(rows) if rows else "Dejo remembers no trails yet."


def _show(tools: DejoTools, key: str, task: str | None) -> str:
    playbook = tools.store.load_playbook(key, task)
    knowledge = tools.store.load_site_knowledge(key)
    facts = ("\nsite facts: " + "; ".join(knowledge.summary())) if knowledge else ""
    if playbook is None:
        tasks = tools.store.trails_for(key)
        if tasks:
            listed = ", ".join(f'"{name}"' for name in tasks)
            return f"{key} has {len(tasks)} trails: {listed}. Name one with task.{facts}"
        return f"no trail remembered for {key}.{facts}"
    steps = [f"{s.index}. {s.intent}{' (risky)' if s.risky else ''}" for s in playbook.steps]
    return f'"{playbook.task}" on {key}:\n' + "\n".join(steps) + facts


def _map(tools: DejoTools, key: str, path: str | None) -> str:
    site_map = tools.store.load_site_map(key)
    if site_map is None or site_map.is_empty:
        return f"Dejo has not looked at any page on {key} yet."
    if path is None:
        rows = [f"{row['path']} · {row['title']}" for row in site_map.index()[:MAX_LISTED]]
        return "pages seen:\n" + "\n".join(rows) + "\ncall again with path for one page."
    page = site_map.page(path)
    if page is None:
        return f"Dejo has not looked at {path} on {key}."
    controls = [
        f'{c.role} "{c.name}"' if c.name else f"{c.role} nth {(c.nth or 0) + 1}"
        for c in page.controls
    ]
    return (
        f"{page.path} ({page.title}), seen {page.last_seen}. These work as step targets "
        "without looking first:\n" + "\n".join(controls)
    )


def dejo_manage(
    tools: DejoTools, *, do: str, site: str, task: str | None = None, text: str | None = None
) -> Reply:
    key = domain_of(site)
    if do == "note":
        if not text:
            return Reply("do=note needs text: the fact to keep", error=True)
        knowledge = tools.store.load_site_knowledge(key) or SiteKnowledge(domain=key)
        knowledge.merge(fact=text)
        tools.store.save_site_knowledge(knowledge)
        return Reply(f"kept for {key}: " + "; ".join(knowledge.summary()))
    if do == "share":
        published = tools.store.share_trail(key, task)
        if published is None:
            return Reply(f"no trail for {key} to share yet", error=True)
        return Reply(
            f'shared "{published["task"]}" on {key}. Typed values never leave. Facts shared: '
            + ("; ".join(published.get("site_facts") or []) or "none")
        )
    if do == "borrow":
        try:
            borrowed = tools.store.borrow_trail(key, task)
        except TrailAlreadyHere as clash:
            return Reply(f"{clash} Forget yours first (do=forget) to take theirs.", error=True)
        if borrowed is None:
            return Reply(f"nobody has shared a trail for {key}", error=True)
        needed = [step.secret for step in borrowed.steps if step.secret]
        asks = f" It will ask for: {', '.join(needed)}." if needed else ""
        return Reply(f'borrowed "{borrowed.task}" on {key}. Run it with that task.{asks}')
    return Reply(_forget(tools, key, task))


def _forget(tools: DejoTools, key: str, task: str | None) -> str:
    if task:
        gone = tools.store.retire_playbook(key, task)
        tools.store.drop_draft(key, task)
        tools.forget_runs(key)
        return f'forgot "{task}" on {key}.' if gone else f'no trail "{task}" on {key}.'
    withdrawn = len(tools.store.my_offers_for(key))
    elsewhere = len(tools.store.offers_for(key)) - withdrawn
    forgotten = tools.store.forget_site(key)
    tools.forget_runs(key)
    if not forgotten:
        return f"nothing was remembered for {key}."
    said = f"forgot {key}: its trails, drafts, map and facts. dejo_run starts from zero."
    if withdrawn:
        said += f" Withdrawn from the commons: {withdrawn}."
    if elsewhere > 0:
        # Said plainly: this is a boundary Dejo cannot cross, and a guarantee only if told.
        said += (
            f" {elsewhere} other agent(s) still hold their own copy; Dejo cannot reach into "
            "another agent's memory and will not offer theirs back unless asked on purpose."
        )
    return said


# ----------------------------------------------------------------------------- the server

HANDLERS: dict[str, Callable[..., Reply]] = {
    "dejo_run": dejo_run,
    "dejo_login": dejo_login,
    "dejo_profile": dejo_profile,
    "dejo_memory": dejo_memory,
    "dejo_manage": dejo_manage,
}


class DejoServer:
    """The MCP server: five tools over one `DejoTools`.

    Built on the SDK's low-level `Server` rather than FastMCP, so each tool's description,
    schema, annotations and `_meta` are exactly what is written above, byte for byte. FastMCP
    builds the schema from Python signatures and adds fields no model needs to read."""

    def __init__(self, tools: DejoTools) -> None:
        self.dejo_tools = tools
        self.server: Server = Server("dejo", instructions=INSTRUCTIONS)
        self.server.list_tools()(self._list)
        self.server.call_tool(validate_input=True)(self._call)

    @property
    def instructions(self) -> str:
        return INSTRUCTIONS

    async def _list(self) -> list[types.Tool]:
        return TOOLS

    async def _call(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        handler = HANDLERS.get(name)
        if handler is None:
            return _result(Reply(f"no tool called {name}", error=True))
        work = functools.partial(handler, self.dejo_tools, **arguments)
        try:
            reply = await anyio.to_thread.run_sync(work)
        except Exception as failure:  # noqa: BLE001 - a person reads this, never a stack trace
            reply = Reply(f"{type(failure).__name__}: {failure}", error=True)
        return _result(reply)

    async def list_tools(self) -> list[types.Tool]:
        """What a client sees, through the same request path a client uses."""
        handler = self.server.request_handlers[types.ListToolsRequest]
        answer = await handler(types.ListToolsRequest(method="tools/list"))
        return answer.root.tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        """One tool call, through the same request path a client uses, input checks
        included."""
        handler = self.server.request_handlers[types.CallToolRequest]
        request = types.CallToolRequest(
            method="tools/call", params=types.CallToolRequestParams(name=name, arguments=arguments)
        )
        answer = await handler(request)
        return answer.root

    def run(self) -> None:
        """Serve over stdio until the client goes away."""
        from mcp.server.stdio import stdio_server

        async def serve() -> None:
            async with stdio_server() as (reading, writing):
                await self.server.run(reading, writing, self.server.create_initialization_options())

        anyio.run(serve)


def _result(reply: Reply) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=reply.text)], isError=reply.error
    )


def build_server(
    *,
    db_path: str | None = None,
    headless: bool = True,
    downloads: str | None = None,
    profile: str | None = None,
    profiles_dir: str | None = None,
    agent: str | None = None,
) -> DejoServer:
    """Wire the tools. Kept in a function so tests can build a server without running it."""
    return DejoServer(
        DejoTools(
            db_path=db_path,
            profiles_dir=profiles_dir,
            headless=headless,
            downloads=downloads,
            profile=profile,
            agent=agent,
        )
    )


def run_stdio() -> None:
    """Entry point for `dejo-mcp` and `python -m dejo_mcp`.

    Configured entirely by environment, because that is the only channel an `.mcp.json`
    entry has.

        DEJO_AGENT    who this agent is. Unset means the memory that already exists.
        DEJO_PROFILE  where the DEFAULT profile keeps its browser data. Two agents cannot
                      share one: Chrome allows a single process per profile.
        DEJO_PROFILES_DIR  where named profiles live. Default ~/.dejo/profiles.
        DEJO_DB       which memory database. Agents share this on purpose; it is how a
                      trail gets from one to the other.

    The old CAIRN_ names are still read when the DEJO_ one is not set.
    """
    server = build_server(
        agent=setting("DEJO_AGENT"),
        profile=setting("DEJO_PROFILE"),
        profiles_dir=setting("DEJO_PROFILES_DIR"),
        db_path=setting("DEJO_DB"),
    )
    who = setting("DEJO_AGENT") or "the default agent"
    log(f"ready as {who}, profile {server.dejo_tools.active!r}")
    try:
        server.run()
    finally:
        server.dejo_tools.close()
