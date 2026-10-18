"""Dejo as MCP tools. This is the product.

Your own AI — Claude Code, Cursor, Codex — becomes the brain. Dejo gives it a browser and
a memory. There is no model call anywhere in this file or anything it imports.

Two paths, and the tool descriptions exist to make the host AI pick the right one:

    cold   dejo_act / dejo_read / dejo_save
           Slow. Many calls. Done ONCE per site, ever.

    warm   dejo_run
           One call. Deterministic replay of what was learned. No thinking required.

Every tool is a few lines that call into the `dejo` package. If something here starts
needing real logic, that logic belongs in the engine instead.

Never print to stdout — stdio is the MCP transport and a stray print corrupts it.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import Any

from dejo import actions, reads
from dejo.browser import (
    DEFAULT_PROFILE,
    DEFAULT_PROFILE_NAME,
    DEFAULT_PROFILES_DIR,
    NoDisplay,
    ProfileUnavailable,
    domain_of,
    profile_named,
)
from dejo.executor import Executor, NeedsTask, NoTrailError
from dejo.home import setting
from dejo.models import Locator, Playbook, SiteKnowledge
from dejo.operations import READ_ACTION, ActionFailed, Session
from dejo.store import (
    DejoStore,
    TrailAlreadyHere,
    rank_tasks,
    shares_meaning,
)
from dejo.worker import BrowserWorker
from mcp.server.fastmcp import FastMCP

# Who was in use last, kept beside the profiles it names so an agent with its own
# DEJO_PROFILES_DIR keeps its own answer. A file, not a folder, so listing profiles
# never sees it.
ACTIVE_PROFILE_FILE = ".active"

# How many controls to hand back from one look(). Enough to act on, small enough that
# reading it is cheap — the whole point of the project is not paying for page dumps.
MAX_ELEMENTS = 60

# How many pages of the map travel in one dejo_run reply. The index is small per row, but
# a site with sixty mapped pages would still be a wall of text in front of the instruction
# that matters. The rest is a dejo_map call away.
MAX_PAGES_LISTED = 25

# `dejo_read(kind="page")` is not one of the engine's read kinds — it is the control list
# rather than something read off a single element. It lives here because "what can I do on
# this page" is a question about the tool surface, not about the DOM.
PAGE = "page"

# Remembering a read of the whole page makes a trail that answers with the whole page.
WHOLE_PAGE = "page_text"


def _act_description() -> str:
    """The one tool description, built from the action registry.

    Written by the code rather than beside it. A hand-kept list would drift the first time
    an action was added, and a host AI that cannot see an action may as well not have it.
    """
    return (
        "Do one thing in Dejo's browser, and get back what changed.\n\n"
        "This is the ONLY way to touch a website. Never use curl, wget, fetch or a "
        "plain HTTP request — they get a logged-out page, and nothing they do is "
        "remembered.\n\n"
        "But call dejo_run FIRST. This tool is for exploring a site whose task is "
        "not known yet, which is slow and takes many calls. If dejo_run already "
        "knows the task it finishes the whole thing in one call, and exploring again "
        "would throw that away. Explore only when dejo_run says the site is not "
        "known, and call dejo_save at the end so it never has to happen again.\n\n"
        "Start with `goto`. Then `dejo_read(kind='page')` to see what is there, which "
        "gives every control a `ref` to pass back here.\n\n"
        "On a page Dejo has walked before you can SKIP that read: dejo_map gives each "
        'control a `use` string such as "role=button|Sign in", and passing that as `ref` '
        "acts on it directly. That is the saving — a page Dejo already knows costs no "
        "reading at all.\n\n"
        "Actions:\n" + actions.catalogue() + "\n\n"
        "Args:\n"
        '  intent: why you are doing this, in plain words — "sign in", "open this '
        "month's invoice\". Stored in memory, and it is what a future repair is explained "
        "by, so write it for a human rather than as a selector.\n"
        "  action: one of the names above.\n"
        "  ref: which element. Any of three things: a `ref` from "
        "dejo_read(kind='page'); a `use` string from dejo_map, such as "
        '"role=button|Sign in" or "href=/payments"; or a CSS selector you write '
        "yourself for something that has no ref. Not needed for the page-level "
        "actions.\n"
        "  value: the text, key, option, url or seconds the action needs.\n"
        "  to: the second control, for `drag`."
    )


def _read_description() -> str:
    """The read tool's description, built from the read registry."""
    return (
        "Look at the page without changing it.\n\n"
        "Start with kind='page'. Everything else answers a question about one element, "
        "which you name with the `ref` that kind='page' gave you.\n\n"
        "Kinds:\n"
        f"  {PAGE} — the controls on this page, each with a `ref` to act on; "
        "gives back a list; no ref needed\n" + reads.catalogue() + "\n\n"
        "REMEMBER THE READ THAT IS THE ANSWER. Pass remember=True and an `intent` in "
        "plain words for the read that actually answers the task — the number, the "
        "status, the total. Without it the saved trail walks to the page and stops, and "
        "the next run has to work the answer out all over again. Ordinary looking-around "
        "reads should leave it off.\n\n"
        "Args:\n"
        "  kind: one of the names above.\n"
        "  ref: which element. Either a `ref` from kind='page', OR a CSS selector "
        "you write yourself. A selector that matches SEVERAL elements is refused "
        'rather than guessed at — add " >> nth=0" for the first of them, or '
        '" >> nth=-1" for the last. A dashboard keeps its numbers in plain divs with no '
        "role, so those get no ref at all — name them with a selector such as "
        "\"[data-attr='visitors-tile'] .big\". Do that rather than page_text, which "
        "hands back the entire page for you to search through on every future run.\n"
        "  attribute: the attribute name, only for kind='attribute'.\n"
        "  remember: keep this read in the trail, so dejo_run returns it next time.\n"
        "  intent: why you are reading it, in plain words. This is the name the answer "
        "comes back under."
    )


def log(message: str) -> None:
    """stderr only. stdout belongs to the MCP transport."""
    print(f"[dejo] {message}", file=sys.stderr, flush=True)


def _facts_for(tools: DejoTools, domain: str) -> list[str]:
    """What Dejo still knows about a site, in plain sentences."""
    knowledge = tools.store.load_site_knowledge(domain)
    return knowledge.summary() if knowledge else []


def _pages_for(tools: DejoTools, domain: str) -> list[dict[str, Any]]:
    """The pages Dejo has already looked at on this site.

    Handed over on every branch where the host AI is about to explore, because that is the
    moment it would otherwise start hunting for a page Dejo has already stood on. The
    index only — paths, titles, how many controls, how long ago. The controls themselves
    are fetched one page at a time with dejo_map, since a whole map cannot travel inside
    every reply and most of it is irrelevant to any one task.
    """
    site_map = tools.store.load_site_map(domain)
    return site_map.index()[:MAX_PAGES_LISTED] if site_map else []


def _answer_note(
    playbook: Playbook, guessed: bool, from_value: int, offered: bool
) -> dict[str, str]:
    """Say what the saved trail will hand back next time, when that is not obvious.

    Two things go wrong quietly here, and both were measured on 2026-09-05.

    A trail with NO read arrives at the page and stops. Every later run has to read the
    page again, which is the whole cost this project removes — and it happens whenever the
    caller answers from `dejo_read(kind="page")`, because the control list is exploration,
    not a read of one value. Recording that list as a step would be worse: replay would
    hand back the entire page every time. So the only honest move is to say it plainly and
    say how to fix it.

    A trail whose answer was CHOSEN rather than marked is fine, but only the caller knows
    whether the right read was picked.
    """
    if from_value:
        crowd = (
            f" {from_value} elements on that page say exactly that, and the FIRST was "
            f"kept — if that is the wrong one, read the right one with dejo_read and "
            f"save again."
            if from_value > 1
            else ""
        )
        return {
            "note": (
                "Dejo found the value you gave on the page and stored where it lives, so "
                "dejo_run hands it back from now on without reading anything." + crowd
            )
        }
    if not any(step.action == READ_ACTION for step in playbook.steps):
        if offered:
            return {
                "warning": (
                    "The `answer` you gave matches no element on this page, so it was "
                    "NOT recorded and this trail answers nothing. Check the text is "
                    "exactly as the page shows it, or read the value with "
                    "dejo_read(kind='text', ref=...) — a selector matching several "
                    'elements needs " >> nth=0" on the end — then save again.'
                )
            }
        return {
            "warning": (
                "This trail goes to the page and answers NOTHING. If you answered from "
                "dejo_read(kind='page'), that is the control list, not a saved value — "
                "every future run will have to read the page again and cost full price. "
                "Read the value itself with dejo_read(kind='text', ref=...) using a ref "
                "from the page list, then call dejo_save again."
            )
        }
    if guessed:
        return {
            "note": (
                "No read was marked as the answer, so the LAST thing you read was kept as "
                "it — that is what dejo_run will hand back from now on. If a different "
                "read was the real answer, read it again with remember=True and an "
                "`intent`, then save once more."
            )
        }
    return {}


def _explore_advice(pages: list[dict[str, Any]]) -> str:
    """What to tell an AI that has a map, instead of letting it start from nothing."""
    if not pages:
        return ""
    return (
        f" Dejo has ALREADY looked at {len(pages)} page(s) on this site — they are in "
        "`pages_known`, newest first. Start there rather than hunting: go straight to the "
        "path that matches what you were asked for, and call dejo_map with that path to "
        "see the controls that were on it. This is what Dejo saw LAST time, so verify as "
        "you go — the site may have moved since."
    )


def err(problem: BaseException | str) -> dict[str, Any]:
    """A readable message, never a stack trace."""
    return {"ok": False, "error": str(problem)}


class DejoTools:
    """Holds this connection's browsers and its one memory store.

    Browsers, plural. A profile is a whole signed-in browser — its own cookies, its own
    session, its own Chrome process — and Dejo keeps as many as are asked for, side by
    side. That is what lets a customer, a vendor and an admin be signed in AT ONCE.

    With one profile, a suite testing three roles has to sign out and back in between them.
    That is slow, and worse, it makes the ORDER of the tests matter: one that forgets to
    sign out breaks the next. Profiles remove both problems.

    Memory is deliberately NOT split by profile. The site is one site however many logins
    reach it, and what the admin saw is worth knowing when the customer arrives — which is
    the same reason the map is one merged map per site.
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
        # Whoever was in use last time, not `default` — see `_remember_active`. Every
        # reply names it, so coming back as somebody is never a surprise.
        self.active = self._remembered_active()
        self.downloads = downloads
        self.headless = headless
        self._workers: dict[str, BrowserWorker] = {}
        self._sessions: dict[str, Session] = {}
        self._login_worker: BrowserWorker | None = None

    def path_for(self, name: str) -> str:
        """The browser folder one profile uses."""
        where = profile_named(name, default=self.profile, root=self.profiles_dir)
        return str(where) if where else ""

    @property
    def worker(self) -> BrowserWorker:
        """The browser for the profile in use, started the first time it is needed.

        A property rather than a field so that every existing caller keeps working: they
        ask for `tools.worker` and get whichever profile is active, without knowing that
        profiles exist at all.
        """
        running = self._workers.get(self.active)
        if running is None:
            running = BrowserWorker(
                headless=self.headless,
                downloads=self.downloads,
                profile=self.path_for(self.active),
            )
            self._workers[self.active] = running
        return running

    def session(self) -> Session:
        """The cold-path session for the profile in use, started when first needed.

        One per profile, because a trace belongs to the browser that made it. Sharing one
        would mix an admin's steps into a customer's trail.
        """
        existing = self._sessions.get(self.active)
        if existing is None:
            self.worker.start()
            existing = Session(self.worker.browser, self.store)  # type: ignore[arg-type]
            self._sessions[self.active] = existing
        return existing

    def reset_session(self) -> None:
        self._sessions.pop(self.active, None)

    @property
    def secrets_profile(self) -> str:
        """Which profile a password is looked up under. Always a name, `default` included.

        This used to answer None for the default, to spare people who had never heard of
        profiles from seeing one named in an error. That was a mistake: the missing-secret
        message then said "your secrets file has no password for this site" when the
        password WAS in the file, under `admin`, and the active profile had quietly gone
        back to `default`. The lookup was right; the message hid the only fact that
        explained it.

        Naming `default` costs nothing — a domain-wide entry is still found, because
        `secrets.resolve` falls back to it after the profile's own places.
        """
        return self.active

    def use(self, name: str) -> str:
        """Work as a different profile from now on. Made on first use, and remembered.

        Switching costs nothing: the browser it belongs to stays open and signed in, so
        going back and forth between roles is free.
        """
        self.active = name.strip() or DEFAULT_PROFILE_NAME
        self._remember_active()
        return self.active

    def _remember_active(self) -> None:
        """Write down who is in use, so a restart does not silently become somebody else.

        An MCP server restarts whenever its client does. Losing the profile there meant a
        run that had been an admin for an hour came back as `default`, signed in to
        nothing, with no message saying so — and the next failure looked like a broken
        trail or a missing password.

        It lives beside the profiles it names, so an agent given its own DEJO_PROFILES_DIR
        keeps its own answer. Failing to write it is not worth stopping a run for; the
        cost is only that the next start says `default`.
        """
        with contextlib.suppress(OSError):
            self.profiles_dir.mkdir(parents=True, exist_ok=True)
            (self.profiles_dir / ACTIVE_PROFILE_FILE).write_text(self.active, encoding="utf-8")

    def _remembered_active(self) -> str:
        """Who was in use when this machine last ran. `default` if nobody has switched."""
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
                "signed_in_data": bool(self.path_for(name)) and Path(self.path_for(name)).exists(),
            }
            for name in sorted(names)
        ]

    def take_profile_note(self) -> str | None:
        """Hand over the one-time note about a browser swap, and clear it.

        The engine records the swap but cannot report it — printing from library code is
        not allowed. Somebody has to say it out loud, or "sign-ins are kept, and if a site
        asks you to sign in again this is why" is a promise nobody ever reads. Once, not
        on every call: a person needs telling, not reminding.
        """
        browser = self.worker.browser
        note = getattr(browser, "profile_note", None) if browser is not None else None
        if note:
            browser.profile_note = None
        return note

    def open_login_window(self, url: str) -> None:
        """Show a real browser window so a person can sign in themselves.

        Chrome allows one process per profile, so the working browser has to let go of it
        first. It starts again by itself on the next call.
        """
        # Only the profile being signed into lets go. The others stay open and signed in,
        # which is the whole point of having them.
        self.worker.stop()
        self._sessions.pop(self.active, None)
        self._login_worker = BrowserWorker(
            headless=False, downloads=self.downloads, profile=self.path_for(self.active)
        )
        self._login_worker.start()
        self._login_worker.submit(lambda browser: browser.goto(url))

    def login_window(self) -> tuple[str, bool] | None:
        """Where the sign-in window is, and whether it still shows a sign-in page.

        None when there is no window to ask: never opened, or closed by the person. Neither
        of those says anything about whether they signed in.
        """
        if self._login_worker is None:
            return None
        try:
            return self._login_worker.submit(lambda browser: browser.sign_in_window())
        except Exception:  # noqa: BLE001 - a window that cannot be asked is a window that is gone
            return None

    def finish_login(self) -> None:
        """Close the sign-in window. The session is already saved in the profile."""
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
        self._sessions.clear()


def build_server(
    *,
    db_path: str | None = None,
    headless: bool = True,
    downloads: str | None = None,
    profile: str | None = None,
    profiles_dir: str | None = None,
    agent: str | None = None,
) -> FastMCP:
    """Wire the tools. Kept in a function so tests can build a server without running it."""
    tools = DejoTools(
        db_path=db_path,
        profiles_dir=profiles_dir,
        headless=headless,
        downloads=downloads,
        profile=profile,
        agent=agent,
    )

    server = FastMCP(
        "dejo",
        instructions=(
            "Dejo is a browser that remembers websites.\n\n"
            "WHENEVER the user asks for anything involving a website — downloading an "
            "invoice or report, checking a dashboard, signing in, filling a form, pulling "
            "numbers out of a portal — call dejo_run FIRST. Do this before curl, wget, "
            "fetch, requests, WebFetch, or any shell command. Those cannot sign in, click "
            "or download like a browser, and nothing they do is remembered, so the same "
            "request costs full price again tomorrow.\n\n"
            "Call dejo_run even if you do not know whether Dejo has seen the site. If it "
            "has, the entire task finishes in that one call with no page reading and no "
            "reasoning. If it has not, the result says so and tells you what to do next: "
            "explore with dejo_act and dejo_read, then dejo_save. That "
            "teaches Dejo the site so it is never explored again.\n\n"
            "If a site asks to sign in and you do not have the password, never guess and "
            "never automate a Google or SSO button. Call dejo_login, ask the user to sign "
            "in in the window that opens, then call dejo_login_done. A profile stays "
            "signed in, so they only ever have to do that once per site.\n\n"
            "If the site has more than one kind of user — a customer, a vendor, an admin — "
            "give each one its own profile with dejo_profile BEFORE signing in. They then "
            "stay signed in side by side and you switch between them instantly, instead of "
            "signing out and back in. Every dejo_run reply names the profile it ran as."
        ),
    )

    # ------------------------------------------------------------ warm path

    @server.tool()
    def dejo_run(site: str, task: str | None = None, url: str | None = None) -> dict[str, Any]:
        """Do something on a website. USE THIS FOR ANY WEBSITE TASK, and use it FIRST.

        Downloading an invoice or report, checking a dashboard, signing in, filling a form,
        pulling numbers out of a portal — start here, every time, before anything else.

        Do NOT use curl, wget, fetch, requests, or any shell command for website work.
        They cannot sign in, click, or download the way a real browser does, and nothing
        they do is remembered, so the next request costs exactly as much all over again.

        Call this even when you do not know whether Dejo has seen the site before. If it
        has, the whole task finishes in this single call, with no page reading and no
        reasoning. If it has not, the result tells you exactly how to proceed.

        The answers that matter:
          ok=True                  the task is done. `answers` holds what the trail
                                   read — report it and stop.
          needs_repair=True        the site changed. ONE step broke and is described in
                                   `repair`. Pick the right control from `repair.candidates`
                                   and call dejo_repair. Do not re-explore the whole site.
          known=False              Dejo has never been here. Explore with
                                   dejo_act and dejo_read, then dejo_save.
          needs_task=True          the site is known but this task is not named yet. Use a
                                   trail from `tasks` if one fits; otherwise it is a new
                                   task on a familiar site.

        Whenever you are about to explore, `pages_known` lists the pages Dejo has ALREADY
        looked at on this site. Start from those instead of hunting, and use dejo_map to
        see what was on one of them.

        Args:
            site: The site, as a domain or a full URL (e.g. "billing.acme.com").
            task: Which task, in the same plain words it was saved under. Only needed when
                a site has more than one — the result says so and lists them.
            url: Optional. Where the first step should go, if it differs from what was
                learned — useful when the same site is reached by a different entry URL.
        """
        key = domain_of(site)
        try:
            result = tools.worker.submit(
                lambda browser: Executor(tools.store, browser, profile=tools.secrets_profile).run(
                    key, task=task, start_url=url
                )
            )
        except NeedsTask as ambiguous:
            # NOT "unknown". Saying that made a host AI explore a site it already knew and
            # save over the trail that was there.
            #
            # This branch is also where a genuinely NEW task on a known site arrives, and
            # the instruction used to end "Do NOT explore — the trail is already there",
            # which is simply wrong when none of `tasks` is what was asked for. Now it says
            # both halves: use a trail if one fits, and if none does, start from the map
            # rather than from nothing.
            pages = _pages_for(tools, key)
            ranked = (
                rank_tasks(task or "", ambiguous.tasks, domain=key) if task else ambiguous.tasks
            )
            nearest = ranked[0] if ranked else ""
            # Ranking always returns EVERY task, so a non-empty list proves nothing — the
            # top of it can still share not one word with what was asked for. Whether the
            # exploration advice is withheld turns on whether the nearest trail is
            # PLAUSIBLE, which is a different question and the one that matters.
            fits = bool(task and nearest and shares_meaning(task, nearest, key))
            return {
                "ok": False,
                "known": True,
                "needs_task": True,
                "site": key,
                "profile": tools.active,
                "tasks": ranked,
                "closest": nearest,
                "pages_known": pages,
                "message": str(ambiguous),
                # This reply used to lose an argument with the model. The retry was
                # conditional and hedged, and directly beneath it sat a concrete
                # exploration plan with real page paths — so the model explored, every
                # time, on a site whose answer was already in memory. Measured.
                #
                # So: the retry comes first, it is specific, it is priced, and the
                # exploration advice is withheld while a trail plainly fits.
                "next": (
                    (
                        f"Dejo knows this site. `tasks` is ordered closest-first — "
                        f"{nearest!r} is the nearest to what you asked for. "
                        f"DO THIS FIRST: call dejo_run again with task={nearest!r}, or "
                        f"with no `task` at all. That costs one call and no browsing — "
                        f"Dejo answers from memory before the browser even moves. "
                        f"Only if none of `tasks` is the job you were asked for is this a "
                        f"NEW task. Exploring costs dozens of calls, so be sure first."
                    )
                    if fits
                    else (
                        "Dejo knows this site but not this task by name. Look at `tasks`: "
                        "if one of them is the job you were asked for, call dejo_run again "
                        "with that wording — one call, no browsing. If none of them is, "
                        "this is a NEW task on a site Dejo already knows, so explore it "
                        "and call dejo_save when it works." + _explore_advice(pages)
                    )
                ),
            }
        except NoTrailError as unknown:
            facts = _facts_for(tools, key)
            pages = _pages_for(tools, key)
            offers = [] if tools.store.was_forgotten(key) else tools.store.offers_for(key)

            if offers:
                # Somebody else has already walked this. Exploring now would throw their
                # work away, so the instruction is REPLACED, not added to.
                return {
                    "ok": False,
                    "known": False,
                    "site": key,
                    "profile": tools.active,
                    "message": str(unknown),
                    "site_facts": facts,
                    "pages_known": pages,
                    "shared_trails": offers,
                    "next": (
                        f"Do NOT explore. Another agent has already walked {key} and left "
                        f"a trail: {offers[0]['task']!r}, shared by "
                        f"{offers[0]['shared_by']!r}. Call dejo_borrow to take it, then "
                        f"dejo_run again with `task` set to exactly that wording."
                    ),
                }

            if tools.store.was_forgotten(key):
                return {
                    "ok": False,
                    "known": False,
                    "site": key,
                    "profile": tools.active,
                    "message": str(unknown),
                    "site_facts": facts,
                    "pages_known": pages,
                    "was_forgotten": True,
                    "next": (
                        f"You told Dejo to forget {key}. Another agent may still have a "
                        f"trail for it, and Dejo will not quietly follow one — that would "
                        f"make forgetting meaningless. Either walk the site again, or say "
                        f"plainly that you want somebody else's trail and call "
                        f"dejo_borrow."
                    ),
                }

            return {
                "ok": False,
                "known": False,
                "site": key,
                "profile": tools.active,
                "message": str(unknown),
                "site_facts": facts,
                "pages_known": pages,
                "next": (
                    "Dejo has not walked this site. Explore it once with "
                    "dejo_act and dejo_read, then call dejo_save so this "
                    "never has to happen again."
                    + (
                        " site_facts is what Dejo still knows about this site from before "
                        "— use it so you do not rediscover the same things."
                        if facts
                        else " While exploring, call dejo_note for anything worth "
                        "remembering that is not a step, such as needing a login, a code "
                        "sent to a phone, or a limit on how often you may try."
                    )
                    + _explore_advice(pages)
                ),
            }
        except Exception as failure:  # noqa: BLE001 - reported, not raised at the client
            return err(failure)

        if result.already_done:
            # Reported as a success, because it is one. Dejo walked to the page the trail
            # starts on and the site sent it away again, which is the site saying the state
            # this trail creates is already there. Handing an AI an error here is what makes
            # it go hunting for a broken step and "repair" a healthy one.
            return {
                "ok": True,
                "known": True,
                "already_done": True,
                "site": key,
                "profile": tools.active,
                "message": result.reason,
                "next": (
                    "Nothing to do and nothing to repair — the task was already in the "
                    "state this trail creates. Carry on with what the user actually asked "
                    "for. Do NOT call dejo_repair and do NOT explore the site."
                ),
            }

        if result.needs_repair and result.aimed_at:
            was, now = result.aimed_at
            return {
                "ok": False,
                "known": True,
                "aimed_at": {"was": was, "now": now},
                "site": key,
                "profile": tools.active,
                "message": result.reason,
                "next": (
                    f"Do NOT call dejo_repair. This trail is for {was!r} and you asked "
                    f"about {now!r}. Dejo followed the same route aimed at {now!r} and "
                    f"stopped because it could not see {now!r} on the page — so there is "
                    f"nothing broken to fix, and binding this step to whatever is here "
                    f"would wreck a working trail. Either {now!r} does not exist on this "
                    f"site, or it is reached a different way: explore it and dejo_save it "
                    f"as its own task."
                ),
            }

        if result.wrong_place:
            return {
                "ok": False,
                "known": True,
                "wrong_place": True,
                "site": key,
                "profile": tools.active,
                "message": result.reason,
                "next": (
                    "Do NOT call dejo_repair. Nothing is broken — this trail starts from "
                    "a page you are not on, and the controls it needs are not here to be "
                    "bound to. Binding one would destroy a working trail. "
                    "If the trail is a sign-in and you are already signed in, the work is "
                    "done: carry on with the task. Otherwise get to the trail's starting "
                    "page first — sign out, or open the site fresh — and call dejo_run "
                    "again."
                ),
            }

        if result.blocked:
            return {
                "ok": False,
                "known": True,
                "blocked": True,
                "site": key,
                "profile": tools.active,
                "message": result.reason,
                "next": (
                    "STOP. Do not call dejo_repair and do not explore. A captcha is a "
                    "human check and there is nothing here you can do about it — the trail "
                    "is fine and nothing was marked broken. Tell the user to open the site "
                    "themselves, clear the check, and say when to try again."
                ),
            }

        if result.page_error is not None:
            return {
                "ok": False,
                "known": True,
                "page_error": result.page_error,
                "site": key,
                "profile": tools.active,
                "message": result.reason,
                "next": (
                    "STOP. Do not call dejo_repair: the controls did not move, the page is "
                    f"missing (HTTP {result.page_error}). Nothing was read, so do not report "
                    "an answer. Tell the user the page could not be opened and why it may "
                    "be (deleted, moved, or not shared with this account). If they give a "
                    "new address, walk the task there and call dejo_save."
                ),
            }

        if result.needs_login:
            return {
                "ok": False,
                "known": True,
                "needs_login": True,
                "site": key,
                "profile": tools.active,
                "message": result.reason,
                "next": (
                    "Do not try to repair this and do not guess a password. Ask the user to "
                    "sign in: call dejo_login, tell them to sign in in the window that "
                    "opens, and when they say they are done call dejo_login_done. Then "
                    "call dejo_run again."
                ),
            }

        if result.stale:
            pages = _pages_for(tools, key)
            return {
                "ok": False,
                "known": False,
                "stale": True,
                "site": key,
                "profile": tools.active,
                "message": result.reason,
                "site_facts": result.site_facts,
                "pages_known": pages,
                "next": (
                    "The site was rebuilt, so the old trail was thrown away but everything "
                    "Dejo knows about the site was kept. Explore it again "
                    "with dejo_act and dejo_read — use site_facts so you "
                    "do not rediscover what is already known — then call "
                    "dejo_save." + _explore_advice(pages)
                ),
            }

        if result.needs_repair and result.repair is not None:
            repair = result.repair.to_dict()
            repair["candidates"] = repair["candidates"][:MAX_ELEMENTS]
            return {
                "ok": False,
                "known": True,
                "needs_repair": True,
                "site": key,
                "profile": tools.active,
                "steps_replayed": result.metrics.steps_replayed,
                "repair": repair,
                "next": (
                    "Only this one step broke; everything before it still worked. Choose "
                    "the control from repair.candidates that matches repair.intent, then "
                    "call dejo_repair with its REF. Then call dejo_run again."
                ),
            }

        ran = result.metrics.task
        # A fuzzy match must never be silent. Asking for one wording and getting another
        # trail is fine — it is the whole point of matching by meaning — but the caller
        # has to be able to see that it happened.
        rephrased = bool(task) and task != ran
        return {
            "ok": result.ok,
            "known": True,
            "site": key,
            "profile": tools.active,
            "task": ran,
            "matched_task": ran,
            "asked_for": task,
            # The route was the trail's; the subject was this caller's. Never left implicit
            # — asking about one project and being handed another project's number is the
            # exact failure this exists to prevent.
            "aimed_at": (
                {"was": result.aimed_at[0], "now": result.aimed_at[1]} if result.aimed_at else None
            ),
            "unverified_steps": result.unverified_steps,
            "steps_replayed": result.metrics.steps_replayed,
            "duration_ms": result.metrics.duration_ms,
            "model_calls": 0,
            "pages_read": 0,
            "saved_files": result.saved_files,
            # What the remembered reads said. This is the answer — report it and stop.
            "answers": result.answers,
            "next": (
                (
                    f"You asked for {task!r} and Dejo ran its trail {ran!r} — the same job "
                    f"under different words. "
                    if rephrased and not result.aimed_at
                    else ""
                )
                + (
                    f"This is the trail {ran!r}, aimed at {result.aimed_at[1]!r} instead of "
                    f"{result.aimed_at[0]!r}. Dejo checked that {result.aimed_at[1]!r} was "
                    f"really on the page before acting on it. Check the answer names the "
                    f"thing you asked about. "
                    if result.aimed_at
                    else ""
                )
                + (
                    f"Steps {result.unverified_steps} took the new subject but nothing on "
                    f"the page could confirm it — their own checks never mentioned it. "
                    if result.unverified_steps
                    else ""
                )
                + (
                    "Done. `answers` holds what the trail read: report it and stop. Do not "
                    "open the page to check — the trail verified every step as it went."
                    if result.answers
                    # An answerless trail used to come back as a plain success, so the
                    # caller read the page itself — every run, forever. Measured on
                    # pypi.org: ten runs, ten page readings, ten replies saying "ok".
                    # Some trails genuinely answer nothing (a download, a form), so this
                    # says what happened and lets the caller decide, rather than failing.
                    else "The trail ran and every step passed, but it reads no value, so "
                    "`answers` is empty. If this task needs a value from the page, that is "
                    "why: read it now with dejo_read(kind='text', ref=...) and call "
                    "dejo_save again with the same task. One extra call today, and this "
                    "site is one call forever after. If the task was only to DO something, "
                    "nothing is wrong — it is done."
                )
            ),
        }

    @server.tool()
    def dejo_repair(
        site: str,
        step_index: int,
        ref: str | None = None,
        css: str | None = None,
        task: str | None = None,
    ) -> dict[str, Any]:
        """Teach Dejo the new way to find ONE step that broke, then remember it forever.

        Call this only after dejo_run came back with needs_repair.

        PASS `ref`, NOT `css`. Give the `ref` of the control you picked from
        repair.candidates. Dejo then looks that element up and stores every durable way of
        finding it — its test id, its link target, its label, its role, its text — exactly
        as it would if the step were being learned for the first time. A repair that stores
        one CSS path leaves the step more fragile than when it started, which is backwards.

        `css` still works for the rare case where the control you want is not in the
        candidate list at all.

        Args:
            site: The same site you passed to dejo_run.
            step_index: repair.step_index from the dejo_run result.
            ref: The `ref` of your chosen control, from repair.candidates. Preferred.
            css: A CSS selector instead, when nothing in the candidates fits.
            task: Which task, if the site has more than one trail.
        """
        key = domain_of(site)
        if not ref and not css:
            return err("say which control to use: a `ref` from repair.candidates, or a `css`")

        try:
            if ref:
                playbook = tools.worker.submit(
                    lambda browser: Executor(
                        tools.store, browser, profile=tools.secrets_profile
                    ).repair_from_ref(key, step_index, ref, task=task)
                )
            else:
                playbook = tools.worker.submit(
                    lambda browser: Executor(
                        tools.store, browser, profile=tools.secrets_profile
                    ).apply_repair(key, step_index, Locator("css", css or ""), task=task)
                )
        except Exception as failure:  # noqa: BLE001
            return err(failure)

        step = next((s for s in playbook.steps if s.index == step_index), None)
        return {
            "ok": True,
            "site": key,
            "step_index": step_index,
            "ways_to_find_it": [locator.describe() for locator in step.locators] if step else [],
            "repairs_total": playbook.repairs,
            "next": "Fixed and saved. Call dejo_run again to finish the task.",
        }

    @server.tool()
    def dejo_share(site: str, task: str | None = None) -> dict[str, Any]:
        """Leave a trail where other agents can pick it up.

        Call this once a task works, if the trail is worth somebody else having. They get
        the route; they do not get you.

        WHAT LEAVES YOUR MACHINE: the steps, every way of finding each control, the checks,
        and the notes saved with dejo_note — the result below lists those notes in full,
        so read it. WHAT NEVER LEAVES: anything typed into a field, and the account hint.
        A shared login step asks whoever follows it for their own credentials.

        Anyone who can read this memory can read what you share here.

        Args:
            site: The site, as a domain or full URL.
            task: Which task, if this site has more than one trail.
        """
        key = domain_of(site)
        try:
            published = tools.store.share_trail(key, task)
        except Exception as failure:  # noqa: BLE001
            return err(failure)

        if published is None:
            return err(
                f"you have no trail for {key} to share. Run the task once and call dejo_save first."
            )
        return {"ok": True, **published, "next": "Another agent can now call dejo_borrow."}

    @server.tool()
    def dejo_borrow(site: str, task: str | None = None, force: bool = False) -> dict[str, Any]:
        """Take a trail another agent left for a site you have never walked.

        Use this when dejo_run comes back with `shared_trails`. The trail is copied into
        your own memory, so from then on it is yours: you can run it, repair it, and be
        made to forget it.

        It arrives with the evidence it earned elsewhere — the locators that are already
        known to work are tried first — but not with the other agent's run counts.

        A step that types something arrives asking YOU for the value, because it was never
        given theirs.

        Args:
            site: The site, as a domain or full URL.
            task: Which trail, if several were shared. Left out, you get the one that has
                worked for the most agents.
            force: Take it even though you have a trail here you already repaired.
        """
        key = domain_of(site)
        try:
            borrowed = tools.store.borrow_trail(key, task, force=force)
        except TrailAlreadyHere as clash:
            return err(f"{clash} Call again with force=true if that is what you mean.")
        except Exception as failure:  # noqa: BLE001
            return err(failure)

        if borrowed is None:
            return err(f"nobody has shared a trail for {key}.")

        needed = [step.secret for step in borrowed.steps if step.secret]
        return {
            "ok": True,
            "site": key,
            # The EXACT wording to pass to dejo_run. A paraphrase may not match.
            "task": borrowed.task,
            "left_by": borrowed.borrowed_from,
            "first_walked_by": borrowed.origin_agent,
            "steps": len(borrowed.steps),
            "clean_runs_behind_it": borrowed.inherited_runs,
            "you_must_supply": needed,
            "next": (
                f"It is yours now. Call dejo_run with site={key!r} and task="
                f"{borrowed.task!r} — exactly that wording."
                + (
                    f" It will ask you for: {', '.join(needed)}. Those were never shared."
                    if needed
                    else ""
                )
            ),
        }

    @server.tool()
    def dejo_commons() -> dict[str, Any]:
        """Every trail any agent has shared, and who left it.

        Answers "what does this team already know how to do?" — including sites this agent
        has never opened.
        """
        try:
            offers = tools.store.every_offer()
        except Exception as failure:  # noqa: BLE001
            return err(failure)
        return {
            "ok": True,
            "count": len(offers),
            "shared_trails": offers,
            "you_are": tools.store.who,
        }

    @server.tool()
    def dejo_sites() -> dict[str, Any]:
        """List every website Dejo remembers, with how well each trail is holding up.

        Useful for answering "what do you already know how to do?".
        """
        try:
            # One row per TRAIL, not per site. A site can hold several tasks, and
            # listing by site alone would hide every one after the first.
            sites = []
            for domain in tools.store.list_sites():
                for task in tools.store.trails_for(domain) or [None]:
                    playbook = tools.store.load_playbook(domain, task)
                    if playbook is None:
                        continue
                    sites.append(
                        {
                            "site": domain,
                            "task": playbook.task,
                            "steps": len(playbook.steps),
                            "runs": playbook.runs,
                            "health": round(playbook.health, 2),
                        }
                    )
            return {"ok": True, "count": len(sites), "sites": sites}
        except Exception as failure:  # noqa: BLE001
            return err(failure)

    @server.tool()
    def dejo_show(site: str) -> dict[str, Any]:
        """Show the remembered trail for one site, step by step.

        Use when the user asks what Dejo will actually do, or why a step keeps breaking.

        Args:
            site: Domain or full URL.
        """
        key = domain_of(site)
        playbook = tools.store.load_playbook(key)
        facts = _facts_for(tools, key)
        if playbook is None:
            # A site with SEVERAL trails and no task named falls through every branch of
            # load_playbook, and saying "nothing remembered" about a site with three trails
            # is worse than unhelpful — it is the tool you reach for to debug exactly this,
            # answering that there is nothing to debug.
            tasks = tools.store.trails_for(key)
            if tasks:
                return {
                    "ok": True,
                    "known": True,
                    "site": key,
                    "tasks": tasks,
                    "site_facts": facts,
                    "message": (f"{key} has {len(tasks)} trails. Name one to see its steps."),
                }
            return {
                "ok": False,
                "known": False,
                "site": key,
                "site_facts": facts,
                "message": "no trail remembered for this site",
            }
        return {
            "ok": True,
            "site": key,
            "playbook": playbook.to_dict(),
            "site_facts": facts,
        }

    @server.tool()
    def dejo_map(site: str, path: str | None = None) -> dict[str, Any]:
        """What Dejo already saw on a site: which pages, and what was on them.

        Call this BEFORE exploring a site Dejo has walked before. dejo_run hands back
        `pages_known` when a task is new; this is how you open one of those pages and see
        the controls that were on it, without loading the page to find out.

        That is the saving. A site is one site however many tasks you have on it, and
        everything Dejo saw while doing the first task is here — the sidebar, the buttons,
        the links — so a new task starts from a map instead of from nothing.

        THIS IS WHAT DEJO SAW LAST TIME, NOT WHAT IS THERE NOW. Every page says when it
        was seen. Treat it the way you would treat directions from someone who walked the
        route last month: go straight to the right place, then check.

        Args:
            site: Domain or full URL.
            path: One page, e.g. "/vendor/requests". Leave it out for the list of pages.
                Ids are generalised, so "/invoices/2026-09" is stored as "/invoices/:id".
        """
        key = domain_of(site)
        site_map = tools.store.load_site_map(key)

        if site_map is None or site_map.is_empty:
            return {
                "ok": False,
                "known": False,
                "site": key,
                "message": f"Dejo has not looked at any page on {key} yet.",
                "next": (
                    "Explore with dejo_act and dejo_read. Every page you look at is "
                    "recorded here automatically, so the next task on this site starts "
                    "with a map."
                ),
            }

        if path is None:
            return {
                "ok": True,
                "site": key,
                "pages": site_map.index()[:MAX_PAGES_LISTED],
                "next": (
                    "Call dejo_map again with `path` set to the page you want, to see the "
                    "controls that were on it."
                ),
            }

        page = site_map.page(path)
        if page is None:
            return {
                "ok": False,
                "site": key,
                "message": f"Dejo has not looked at {path} on {key}.",
                "pages": [row["path"] for row in site_map.index()][:MAX_PAGES_LISTED],
                "next": "Pick one of `pages`, or explore this page and it will be recorded.",
            }

        return {
            "ok": True,
            "site": key,
            "path": page.path,
            "title": page.title,
            "last_seen": page.last_seen,
            "controls": [
                {
                    "role": control.role,
                    "name": control.name,
                    "href": control.href,
                    # Pass this straight back as dejo_act's `ref`. Without it the map
                    # would only ever be a hint: you would know the button is there and
                    # still have to read the whole page to get a ref before pressing it.
                    #
                    # A control with no name of its own — the icon buttons in an admin
                    # table's rows — is said by position instead, "role=button >> nth=3".
                    "use": control.use,
                }
                for control in page.controls
            ],
            "next": (
                "Act on these WITHOUT reading the page: pass a control's `use` string as "
                "dejo_act's `ref`. That is the saving — this page costs no reading at "
                "all. They were here when Dejo last looked, so if one does not resolve "
                "the page has moved: call dejo_read(kind='page') and carry on from there."
            ),
        }

    @server.tool()
    def dejo_forget(site: str) -> dict[str, Any]:
        """Make Dejo forget one website completely.

        After this, dejo_run has nothing left to follow and the site would have to be
        explored from scratch again. Use it when the user asks Dejo to forget a site, or
        to prove that the memory is what makes the fast path work.

        Args:
            site: Domain or full URL.
        """
        key = domain_of(site)
        try:
            # Counted before it happens, because forgetting withdraws them.
            withdrawn = len(tools.store.my_offers_for(key))
            still_offered = len(tools.store.offers_for(key)) - withdrawn
            forgotten = tools.store.forget_site(key)
        except Exception as failure:  # noqa: BLE001
            return err(failure)

        if not forgotten:
            return {"ok": False, "site": key, "message": "nothing was remembered for this site"}

        message = (
            "Forgotten. The trail is archived, so dejo_run has nothing to follow and this "
            "site would have to be learned again from scratch."
        )
        if withdrawn:
            message += f" Withdrawn from the shared memory: {withdrawn} offer(s)."
        if still_offered > 0:
            # Said plainly rather than left to be discovered. Sibyl gives no way to
            # enumerate tenants, so this really is a boundary Dejo cannot cross — which
            # is a guarantee, not a shortcoming, but only if somebody says so.
            message += (
                f" {still_offered} other agent(s) still hold their own copy. Dejo cannot "
                f"reach into another agent's memory, and will not offer you theirs back "
                f"unless you ask for it on purpose."
            )
        return {
            "ok": True,
            "site": key,
            "withdrawn_from_commons": withdrawn,
            "other_agents_still_have_it": still_offered,
            "message": message,
        }

    @server.tool()
    def dejo_note(
        site: str,
        fact: str | None = None,
        needs_login: bool | None = None,
        needs_2fa: bool | None = None,
        account: str | None = None,
    ) -> dict[str, Any]:
        """Remember a fact about a website that is not a step.

        Steps break when a site is redesigned. Facts do not. "It locks you out after five
        wrong passwords", "the invoice only appears after the 3rd", "the export takes two
        minutes", "use the finance login, not the admin one" — these stay true through any
        redesign, and Dejo hands them back the next time this site has to be learned.

        Call this whenever you notice something while exploring that a person would want
        told before doing this task themselves. Each call ADDS; nothing is overwritten, so
        call it as many times as you like.

        Args:
            site: Domain or full URL.
            fact: One thing worth remembering, in plain words.
            needs_login: True if this site requires signing in.
            needs_2fa: True if it asks for a code or a second factor.
            account: Which account is used here, e.g. "finance@acme.com".
        """
        key = domain_of(site)
        if fact is None and needs_login is None and needs_2fa is None and account is None:
            return err("give at least one of: fact, needs_login, needs_2fa, account")

        try:
            knowledge = tools.store.load_site_knowledge(key) or SiteKnowledge(domain=key)
            knowledge.merge(
                fact=fact,
                needs_login=needs_login,
                needs_2fa=needs_2fa,
                account_hint=account,
            )
            tools.store.save_site_knowledge(knowledge)
        except Exception as failure:  # noqa: BLE001
            return err(failure)

        return {
            "ok": True,
            "site": key,
            "known_facts": knowledge.summary(),
            "message": (
                "Saved. This survives a redesign, and comes back if the site ever has to "
                "be learned again."
            ),
        }

    @server.tool()
    def dejo_profile(name: str | None = None) -> dict[str, Any]:
        """Work as a different signed-in identity. Call with no name to see them all.

        A profile is a WHOLE SIGNED-IN BROWSER — its own cookies, its own session, its own
        window. Dejo keeps them side by side, so a customer, a vendor and an admin can all
        be signed in at the same time and you switch between them instantly.

        USE ONE PROFILE PER ROLE when a site has more than one kind of user. Without that
        you have to sign out and back in between roles, which is slow and, worse, makes the
        ORDER of your work matter — anything that forgets to sign out breaks whatever runs
        next.

        A profile is made the first time you name it, empty and signed in to nothing. Sign
        it in ONCE with dejo_login and it stays that way.

        Everything after this call — dejo_run, dejo_act, dejo_read, dejo_login — uses
        the profile you switched to, until you switch again.

        Memory is NOT split by profile, on purpose. The site is one site however many
        logins reach it, so what one role learned is there for the next.

        Args:
            name: What to call it — "vendor", "admin", "customer". Leave it out to list
                the profiles this machine has and say which one is in use.
        """
        if name is None:
            return {
                "ok": True,
                "active": tools.active,
                "profiles": tools.known_profiles(),
                "next": (
                    "Call dejo_profile with a `name` to switch. A name Dejo has not seen "
                    "before is made on the spot, signed in to nothing."
                ),
            }

        was = tools.active
        now = tools.use(name)
        return {
            "ok": True,
            "active": now,
            "was": was,
            "profiles": tools.known_profiles(),
            "next": (
                f"Everything from here on happens as {now!r}. If this profile is not signed "
                f"in to the site yet, call dejo_login — once is enough, it stays signed in."
            ),
        }

    @server.tool()
    def dejo_login(site: str) -> dict[str, Any]:
        """Open a real browser window so the USER can sign in to a site themselves.

        Use this when a site needs a login that you cannot or should not do: a "Sign in
        with Google" button, a company SSO page, or anything that sends a one-time code.
        Never try to type those yourself and never guess a password.

        A visible Chrome window opens on that site. Tell the user to sign in there, in
        their own time. When they say they are done, call dejo_login_done.

        This signs in the profile you are CURRENTLY using, and that profile only. Once
        signed in it stays signed in, so this is a once-per-site, once-per-profile job.

        If a site has several kinds of user — a customer, a vendor, an admin — switch with
        dejo_profile FIRST and sign each one in separately. They then stay signed in side
        by side, and you move between them without signing out of anything.

        Args:
            site: The site to open, as a full URL where possible.
        """
        target = site if "://" in site else f"https://{site}"
        try:
            tools.open_login_window(target)
        except (NoDisplay, ProfileUnavailable) as cannot:
            # Both of these end in a sentence naming what to do. A raw Playwright error
            # about an X server tells a host AI nothing it can act on or relay.
            return err(cannot)
        except Exception as failure:  # noqa: BLE001
            return err(failure)

        return {
            "ok": True,
            "site": domain_of(target),
            "opened": target,
            "profile": tools.active,
            "next": (
                "A browser window is now open. Tell the user: sign in there however the "
                "site asks — password, Google, a code on your phone — and say when you are "
                "done. Then call dejo_login_done. Do not call any other Dejo tool until "
                "then, because the sign-in window is holding the browser."
            ),
        }

    @server.tool()
    def dejo_login_done(site: str, confirmed: bool = False) -> dict[str, Any]:
        """Close the sign-in window once the user says they are signed in.

        Dejo looks at the window first. If it still shows a sign-in page, nothing is
        closed and nothing is saved: tell the user to finish, then call this again.

        Dejo saves nothing about how they signed in — no password, no code. It simply
        keeps the browser session, the same way their own browser does, so later runs
        start already signed in.

        Args:
            site: The same site passed to dejo_login.
            confirmed: Only when the user has looked and says they ARE signed in although
                Dejo reported the page still looks like a sign-in page.
        """
        key = domain_of(site)
        if not tools.signing_in:
            return err("no sign-in window is open — call dejo_login first")

        window = tools.login_window()
        if window is None:
            # The person closed the window. Whether they signed in first cannot be seen
            # from here, so nothing is claimed and nothing is written down.
            tools.finish_login()
            return err(
                "the sign-in window was closed before Dejo could check it, so Dejo cannot "
                "tell whether the sign-in finished. Call dejo_run: if the site still asks "
                "for a sign-in, call dejo_login again and leave the window open until the "
                "user says they are done."
            )
        ended_at, still_signing_in = window
        if still_signing_in and not confirmed:
            # Saying "signed in" here wrote a false fact into memory for good: found when
            # this was called twice on Google while the window sat on the identifier page.
            return {
                "ok": False,
                "site": key,
                "signed_in": False,
                "window_at": ended_at,
                "next": (
                    "The window still shows a sign-in page, so the user has not finished. "
                    "It is still open. Ask them to finish signing in there and tell you, "
                    "then call dejo_login_done again. If they have looked and say they ARE "
                    "signed in, call dejo_login_done with confirmed=true."
                ),
            }

        try:
            tools.finish_login()
            knowledge = tools.store.load_site_knowledge(key) or SiteKnowledge(domain=key)
            knowledge.merge(
                fact="signed in by hand; Dejo keeps the session in its browser profile",
                needs_login=True,
            )
            tools.store.save_site_knowledge(knowledge)
        except Exception as failure:  # noqa: BLE001
            return err(failure)

        return {
            "ok": True,
            "site": key,
            "signed_in": True,
            "ended_at": ended_at,
            "known_facts": knowledge.summary(),
            "next": (
                "Signed in and the window is closed. Call dejo_run again — and if the "
                "site is still unknown, explore it now and call dejo_save."
            ),
        }

    # ------------------------------------------------------------ cold path

    @server.tool(description=_act_description())
    def dejo_act(
        intent: str,
        action: str,
        ref: str | None = None,
        value: str | None = None,
        to: str | None = None,
    ) -> dict[str, Any]:
        try:
            session = tools.session()
            outcome = tools.worker.submit(
                lambda _browser: session.act(intent, action, ref=ref, value=value, to=to)
            )
            note = tools.take_profile_note()
            return {"ok": True, **outcome, **({"note": note} if note else {})}
        except (ActionFailed, actions.UnknownAction, actions.ActionNeedsMore) as refused:
            return err(refused)
        except Exception as failure:  # noqa: BLE001
            return err(failure)

    @server.tool(description=_read_description())
    def dejo_read(
        kind: str = PAGE,
        ref: str | None = None,
        attribute: str | None = None,
        remember: bool = False,
        intent: str = "",
    ) -> dict[str, Any]:
        try:
            session = tools.session()
            if kind == PAGE:
                page = tools.worker.submit(lambda _browser: session.look())
                page["elements"] = page["elements"][:MAX_ELEMENTS]
                note = tools.take_profile_note()
                return {"ok": True, "kind": PAGE, **page, **({"note": note} if note else {})}

            answer = tools.worker.submit(
                lambda _browser: session.read(
                    kind, ref=ref, attribute=attribute, remember=remember, intent=intent
                )
            )
            reply: dict[str, Any] = {
                "ok": True,
                "kind": kind,
                "ref": ref,
                "value": answer,
                "remembered": remember,
            }
            # A read is the moment the caller has its answer and is about to reply, which
            # is exactly when it forgets to save. Measured on 2026-09-05: on one of four
            # sites the whole task was explored, answered, and never written down, so all
            # three runs paid full price. One sentence, at the only moment it lands.
            if session.trace:
                reply["next"] = (
                    "If that answers the task, call dejo_save now — otherwise this site "
                    "costs exactly as much again next time."
                )
            # Said at the moment it happens, not only in the tool description. A host AI
            # remembered a whole-page read on PostHog despite the description, because the
            # tiles had no ref and page_text looked like the only way through.
            if remember and kind == WHOLE_PAGE:
                reply["warning"] = (
                    "This trail's answer is now the entire page, and every future run will "
                    "hand back thousands of characters for you to search. If you can name "
                    "what you actually want with a CSS selector — pass it as `ref` — read "
                    "that instead and remember that one."
                )
            return reply
        except (ActionFailed, reads.UnknownRead, reads.ReadNeedsMore) as refused:
            return err(refused)
        except Exception as failure:  # noqa: BLE001
            return err(failure)

    @server.tool()
    def dejo_save(task: str, answer: str | None = None) -> dict[str, Any]:
        """Remember everything you just did, so this task never needs exploring again.

        Call this once the task is finished. Dejo turns what you did into a trail with a
        check on every step, and stores it. From now on the same task is one dejo_run
        call with no thinking at all.

        EVERYTHING you did is written down, including the parts that went wrong. If you
        took a wrong turn, undid something, or clicked your way out of a stuck menu, those
        become steps too — and a saved mistake is replayed forever. Before saving, call
        dejo_act(action="restart_trail") and walk the task once, cleanly. The result below
        lists every step it kept, so check it says what you meant to do.

        IF THE TASK HAD AN ANSWER, PASS IT AS `answer` — the exact text you are about to
        report, copied character for character. Dejo finds which element on the page says
        that, and stores every durable way of finding it again, so the answer comes back
        on every future run. It costs you no extra call. Without it a trail can walk three
        pages and hand back nothing, and every later run has to read the page all over
        again. Text that matches no element is not recorded, and you are told so.

        Args:
            task: What was accomplished, in plain words, e.g. "download this month's
                invoice".
            answer: The value this task produced, exactly as it appears on the page — the
                price, the count, the status. Leave it out only when the task produced no
                value, such as a download or a form submission.
        """

        try:
            session = tools.session()
            playbook = tools.worker.submit(lambda _browser: session.save(task, answer=answer))
            guessed = session.answered_from_the_last_read
            from_value = session.answered_from_the_value_given
        except ActionFailed as refused:
            return err(refused)
        except Exception as failure:  # noqa: BLE001
            return err(failure)

        tools.reset_session()
        return {
            "ok": True,
            "site": playbook.domain,
            "task": playbook.task,
            "steps": len(playbook.steps),
            # Shown so the AI can see whether its own fumbling got written down. On
            # PostHog a saved trail began "close the stuck context menu", which failed on
            # the first replay and took the whole run with it.
            "trail": [f"{s.index}. {s.action} — {s.intent}" for s in playbook.steps],
            # Never silent, either way. If the answer step was chosen rather than marked,
            # only the caller can tell whether the right read was picked — and if the trail
            # answers nothing at all, saying so now is the difference between a one-call
            # replay and paying to read the page forever.
            **_answer_note(playbook, guessed, from_value, bool(answer)),
            "message": (
                f"Learned {playbook.domain} in {len(playbook.steps)} steps. "
                f"Next time, one dejo_run call does all of it: "
                f"dejo_run(site={playbook.domain!r}, task={playbook.task!r}). "
                f"Close wording is matched too, so it does not have to be word for word."
            ),
        }

    server.dejo_tools = tools  # type: ignore[attr-defined]
    return server


def run_stdio() -> None:
    """Entry point for `dejo-mcp` and `python -m dejo_mcp`.

    Configured entirely by environment, because that is the only channel an `.mcp.json`
    entry has — this function takes no arguments and nothing calls it with any.

        DEJO_AGENT    who this agent is. Unset means the memory that already exists.
        DEJO_PROFILE  where the DEFAULT profile keeps its browser data. Two agents cannot
                       share one: Chrome allows a single process per profile, and a shared
                       profile would also mean the second agent is already signed in to
                       everything the first one is — which is not what "an agent that has
                       never seen this site" should mean.
                       Inside ONE agent, extra profiles are made by name with
                       dejo_profile, and all of them stay signed in at once.
        DEJO_PROFILES_DIR  where those named profiles live. Rarely set; the default is
                       ~/.dejo/profiles.
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
    # The profile is said out loud on every start, because it survives a restart now. A
    # remembered identity that nobody announces is worse than one that resets.
    using = server.dejo_tools.active  # type: ignore[attr-defined]
    log(f"ready as {who}, profile {using!r} — dejo_run first, explore only if unknown")
    try:
        server.run()
    finally:
        server.dejo_tools.close()  # type: ignore[attr-defined]
