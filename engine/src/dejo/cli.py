"""The terminal face of Dejo.

    dejo run    --site <url>        replay a remembered trail, no model involved
    dejo login  --site <url>        open a window and sign in yourself
    dejo sites                      what Dejo knows
    dejo show   <domain>            the trail, step by step
    dejo forget --site <domain>     THE DELETION GATE
    dejo export <domain>            the raw playbook as JSON
    dejo doctor                     check this machine and say what to fix

    dejo share  <site>              leave a trail for another agent
    dejo borrow <site>              take a trail another agent left
    dejo commons                    every trail any agent has shared

The first block is one agent. The second is several agents sharing one database.

`forget` is the one to try first. Run `run` twice to see it be fast, then `forget`, then
`run` again and watch it report that there is nothing left to follow.

Uses argparse rather than a CLI framework on purpose: `mcp/` imports this package, and the
fewer dependencies it drags along the easier it is to install with uvx. Reason logged in
PROGRESS.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .browser import (
    DEFAULT_PROFILE_NAME,
    Browser,
    NoDisplay,
    ProfileStuck,
    ProfileUnavailable,
    domain_of,
    profile_named,
)
from .doctor import cmd_doctor
from .events import Emitter, Event
from .executor import Executor, NoTrailError, ReplayResult
from .home import OldHomeNotMoved, adopt_old_home
from .models import SiteMap
from .store import DejoStore, OldMemoryUnreadable, TrailAlreadyHere, adopt_old_memory

TICK = "+"
CROSS = "!"
DOT = "-"


def render(event: Event) -> None:
    """Turn one event into one line a human can read."""
    kind = event.kind
    data = event.to_dict()

    if kind == "run_started":
        print(f"\n  dejo  {data['domain']}  ({data['mode']} run)")
        print(f"  task   {data['task']}\n")
    elif kind == "memory_read":
        state = "found" if data["found"] else "NOTHING FOUND"
        print(f"  {DOT} memory read   {data['category']}/{data['name']}  {state}")
    elif kind == "memory_write":
        print(f"  {DOT} memory write  {data['category']}/{data['name']}  {data['detail']}")
    elif kind == "step_passed":
        print(
            f"  {TICK} step {data['index']}  {data['intent']}"
            f"   [{data['matched_by']}]  {data['duration_ms']}ms"
        )
    elif kind == "drift_detected":
        print(f"  {DOT}   drift: {data['locator']} no longer matches")
    elif kind == "step_failed":
        print(f"  {CROSS} step {data['index']}  {data['intent']}  — {data['reason']}")
    elif kind == "repair_needed":
        print("\n  this one step needs your AI. Everything else stayed put.")
        print(f"  step {data['index']}: {data['intent']}")
        print(f"  at   {data['url']}")
    elif kind == "repair_saved":
        print(f"  {TICK} repaired step {data['index']}: {data['before']} -> {data['after']}")
    elif kind == "run_finished":
        state = "done" if data["succeeded"] else "stopped"
        # Mentioned only when it has actually happened. This line used to print
        # "0 repaired" on every run, because a run cannot repair anything: it stops at the
        # broken step and hands that one step back, and the fix arrives as a separate call.
        mended = data["trail_repairs"]
        history = f"  ·  repaired {mended}x before" if mended else ""
        print(
            f"\n  {state} in {data['duration_ms']}ms  ·  "
            f"{data['steps_replayed']} steps from memory  ·  "
            f"1 tool call  ·  "
            f"{data['model_calls']} model calls{history}\n"
        )
    elif kind == "forgotten":
        print(f"  {TICK} forgot {data['domain']}")


def _store(args: argparse.Namespace) -> DejoStore:
    """This agent's memory. Announced when it is not the usual one.

    An exported DEJO_AGENT that nobody remembers setting looks exactly like data loss —
    `dejo sites` goes quiet and the trails appear to be gone. So say who is asking.
    """
    store = DejoStore(db_path=args.db, agent=getattr(args, "agent", None))
    if store.agent:
        # `run --json` promises one line of JSON on stdout, so the notice goes elsewhere.
        out = sys.stderr if getattr(args, "json", False) else sys.stdout
        print(f"  (as agent {store.agent})", file=out)
    return store


def _profile_path(args: argparse.Namespace) -> Path | None:
    """Which browser folder this command should use.

    `default` answers with the original folder, so naming profiles never moves an existing
    sign-in somewhere new.
    """
    chosen = profile_named(getattr(args, "profile", DEFAULT_PROFILE_NAME))
    return Path(chosen) if chosen else None


def _site_key(value: str) -> str:
    """Accept either a domain or a full URL, so nobody has to think about which."""
    return domain_of(value) if urlparse(value).scheme else value


# ------------------------------------------------------------------ commands


# What `dejo run` exits with, by outcome. A scheduler acts on these, so they never change.
EXIT_CODES = {
    "done": 0,
    "already_done": 0,
    "failed": 1,
    "needs_repair": 1,
    "no_trail": 2,
    "stale": 2,
    "needs_login": 3,
    "blocked": 4,
    "wrong_place": 5,
}


def outcome_of(result: ReplayResult) -> str:
    """One word for how a run ended, checked in the same order the human report uses."""
    if result.already_done:
        return "already_done"
    if result.wrong_place:
        return "wrong_place"
    if result.blocked:
        return "blocked"
    if result.needs_login:
        return "needs_login"
    if result.stale:
        return "stale"
    if result.needs_repair and result.repair is not None:
        return "needs_repair"
    return "done" if result.ok else "failed"


def run_report(domain: str, result: ReplayResult) -> dict[str, Any]:
    """The `--json` line. A scheduled run has nobody watching the step-by-step output, so
    everything a script needs to act on is here: did it work, what did it read, what did it
    save, and if not, why."""
    outcome = outcome_of(result)
    return {
        "outcome": outcome,
        "ok": EXIT_CODES[outcome] == 0,
        "site": domain,
        "task": result.metrics.task,
        "answers": result.answers,
        "saved_files": result.saved_files,
        "duration_ms": result.metrics.duration_ms,
        "model_calls": result.metrics.model_calls,
        "reason": result.reason,
        "repair": result.repair.to_dict() if result.repair is not None else None,
    }


def cmd_run(args: argparse.Namespace) -> int:
    domain = _site_key(args.site)
    start_url = args.url or (args.site if urlparse(args.site).scheme else None)
    as_json = getattr(args, "json", False)

    emitter = Emitter()
    if not as_json:
        emitter.subscribe(render)
    store = _store(args)

    browser = Browser(headless=not args.headed, profile=_profile_path(args))
    try:
        browser.start()
        result = Executor(
            store,
            browser,
            emitter=emitter,
            # Named even when it is `default`, so a missing password says WHICH identity
            # it looked under. A domain-wide entry is still found either way.
            profile=getattr(args, "profile", DEFAULT_PROFILE_NAME),
        ).run(domain, task=args.task, start_url=start_url)
    except NoTrailError as gone:
        if as_json:
            gone_report = {"outcome": "no_trail", "ok": False, "site": domain, "reason": str(gone)}
            print(json.dumps(gone_report))
        else:
            print(f"\n  {CROSS} {gone}\n")
        return EXIT_CODES["no_trail"]
    finally:
        browser.stop()

    if as_json:
        print(json.dumps(run_report(domain, result), ensure_ascii=False))
        return EXIT_CODES[outcome_of(result)]

    for saved in result.saved_files:
        print(f"  {TICK} saved  {saved}")
    # The answer is the point of most runs ("how many open issues"). It used to be read and
    # then never shown, so a terminal run ended with no result on screen. Printed on one
    # line, because page text often arrives split across several; --json keeps it as read.
    for intent, answer in result.answers.items():
        print(f"  {TICK} {intent}:  {' '.join(str(answer).split())}")

    if result.aimed_at:
        was, now = result.aimed_at
        print()
        print(f"  {TICK} this is the trail for {was}, aimed at {now}")
        print(f"    memory was not changed — {was}'s trail is untouched")
        if result.unverified_steps:
            print(f"    steps {result.unverified_steps} could not confirm {now} on the page")

    if result.already_done:
        # Not a failure and must not read as one. Asking to sign in when you are already
        # signed in is a task that is finished, and exiting non-zero on it sends whatever
        # is driving Dejo looking for a bug that is not there.
        print()
        print(f"  {TICK} {result.reason}")
        print()
        return 0

    if result.wrong_place:
        # Printed nothing at all before this, so the run just ended with exit code 1 and
        # no explanation — the one outcome where the trail is perfectly fine.
        print()
        print(f"  {CROSS} {result.reason}")
        print("    nothing is broken. Get to the trail's starting page and run it again.")
        print()
        return 5

    if result.blocked:
        print()
        print(f"  {CROSS} {result.reason}")
        print()
        return 4

    if result.needs_login:
        print()
        print(f"  {CROSS} {result.reason}")
        print(f"    sign in again with:  dejo login --site {args.site}")
        print()
        return 3

    if result.stale:
        print()
        print(f"  {CROSS} {result.reason}")
        for fact in result.site_facts:
            print(f"    still known: {fact}")
        print("    walk it once more and it will be fast again.")
        print()
        return 2

    if result.needs_repair and result.repair is not None:
        print("  hand this to your AI:\n")
        print(json.dumps(result.repair.to_dict(), indent=2)[:1200])
        print()
        return 1
    return 0 if result.ok else 1


def cmd_login(args: argparse.Namespace) -> int:
    """Open a real window so a person can sign in themselves.

    Some logins cannot be automated and should not be: a Google button, a company SSO
    page, a code sent to a phone. Dejo opens the browser, waits, and keeps the session.
    It never sees the password.
    """
    target = args.site if "://" in args.site else f"https://{args.site}"

    print()
    print(f"  opening {target}")
    print("  sign in however the site asks — password, Google, a code on your phone.")

    browser = Browser(headless=False, profile=_profile_path(args))
    try:
        try:
            browser.start()
            browser.goto(target)
        except (NoDisplay, ProfileUnavailable, ProfileStuck) as cannot:
            # A raw Playwright traceback about an X server tells a person on a server
            # nothing they can act on. These all end in a sentence that does.
            print(f"\n  {CROSS} {cannot}\n")
            return 2
        print()
        where = _wait_until_signed_in(browser)
    finally:
        browser.stop()

    if where is None:
        print(f"\n  {CROSS} the window was closed before Dejo could check it.")
        print(f"    if the site still asks you to sign in, run:  dejo login --site {args.site}\n")
        return 2

    print()
    print(f"  {TICK} signed in. session kept for {domain_of(where)}")
    print("    Dejo saved no password and no code, only the session.")
    print(f"    now run:  dejo run --site {args.site}")
    print()
    return 0


def _wait_until_signed_in(browser: Browser) -> str | None:
    """Wait for the person, then check the window before believing them.

    Pressing Enter used to be taken as proof. A window still on the sign-in page then
    printed "signed in", and the next run failed with no clue why. Returns where the window
    ended up, or None if it was closed before it could be checked.
    """
    input("  press Enter here once you are signed in... ")
    while True:
        window = browser.sign_in_window()
        if window is None:
            return None
        where, still_signing_in = window
        if not still_signing_in:
            return where
        print(f"\n  {CROSS} that window still shows a sign-in page: {where}")
        answer = input("    finish there and press Enter, or type yes if you are signed in: ")
        if answer.strip().lower() == "yes":
            return where


def cmd_sites(args: argparse.Namespace) -> int:
    store = _store(args)
    sites = store.list_sites()
    # A site can be mapped without a trail: somebody explored it and never saved one.
    # Leaving those out would hide memory that genuinely exists, which reads exactly
    # like memory that does not.
    mapped_only = [site for site in store.mapped_sites() if site not in sites]
    if not sites and not mapped_only:
        print("\n  Dejo remembers nothing yet.\n")
        return 0

    print()
    for site in sites:
        # One row per TRAIL, not per site. This used to call `load_playbook(site)` with no
        # task, which returns None as soon as a site has more than one — and the loop then
        # skipped it in silence. A site with two tasks simply vanished from `dejo sites`,
        # which is the exact shape of site this tool is for.
        for task in store.trails_for(site) or [None]:
            playbook = store.load_playbook(site, task)
            if playbook is None:
                continue
            named = f"  {playbook.task}" if playbook.task else ""
            print(
                f"  {site:<24}{named:<34} {len(playbook.steps)} steps  "
                f"{playbook.runs} runs  health {playbook.health:.0%}"
            )
    for site in mapped_only:
        site_map = store.load_site_map(site)
        pages = len(site_map.pages) if site_map else 0
        print(f"  {site:<24}{'  (no trail yet)':<34} {pages} pages mapped")
    print()
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    """What Dejo saw while walking a site, rather than the route it walked.

    Doubles as the consent screen for sharing: this is exactly what would be published.
    """
    domain = _site_key(args.domain)
    store = _store(args)
    site_map = store.load_site_map(domain)

    if site_map is None or site_map.is_empty:
        print(f"\n  Dejo has not looked at any page on {domain} yet.\n")
        return 2

    if args.path:
        return _print_one_page(site_map, domain, args.path)

    print(f"\n  {domain} - {len(site_map.pages)} pages Dejo has looked at\n")
    for line in site_map.summary():
        print(f"    {line}")
    print("\n  This is what Dejo saw last time, not what is on the site now.\n")
    return 0


def _print_one_page(site_map: SiteMap, domain: str, path: str) -> int:
    """Everything known about one page."""
    page = site_map.page(path)
    if page is None:
        print(f"\n  Dejo has not looked at {path} on {domain}.")
        print(f"    run `dejo map {domain}` to see which pages it has.\n")
        return 2

    named = f" - {page.title}" if page.title else ""
    print(f"\n  {domain}{page.path}{named}\n")
    for control in page.controls:
        print(f"    {control.describe()}")
    print(f"\n  {len(page.controls)} controls, last seen {page.last_seen}.\n")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store = _store(args)
    key = _site_key(args.domain)
    playbook = store.load_playbook(key, getattr(args, "task", None))
    if playbook is None:
        # A site with several trails and no task named matches none of them. Saying
        # "nothing remembered" about a site holding three trails is the command you reach
        # for to inspect memory, telling you memory is empty.
        tasks = store.trails_for(key)
        if tasks:
            print(f"\n  {key} — {len(tasks)} trails. Name one to see its steps.\n")
            for task in tasks:
                print(f"    dejo show {key} --task {task!r}")
            print()
            return 0
        print(f"\n  nothing remembered for {args.domain}\n")
        return 2

    print(f"\n  {playbook.domain}")
    print(f"  {playbook.task}")
    print(f"  version {playbook.version}  ·  {playbook.runs} runs  ·  {playbook.repairs} repairs\n")
    for step in playbook.steps:
        best = step.ranked_locators()
        via = f"{best[0].kind}:{best[0].value}" if best else step.value or ""
        print(f"  {step.index}. {step.intent}")
        print(f"     {step.action:<7} {via}")
        print(
            f"     expects {step.postcondition.kind} = {step.postcondition.value}"
            f"   health {step.health:.0%}"
        )
    print()
    return 0


def cmd_forget(args: argparse.Namespace) -> int:
    """The deletion gate, as one command."""
    domain = _site_key(args.site)
    store = _store(args)

    if not store.forget_site(domain):
        print(f"\n  nothing to forget for {domain}\n")
        return 2

    print(f"\n  {TICK} forgot {domain}")
    print("    the trail is archived. replay has nothing left to follow.\n")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    store = _store(args)
    playbook = store.load_playbook(_site_key(args.domain))
    if playbook is None:
        print(f"nothing remembered for {args.domain}", file=sys.stderr)
        return 2
    print(json.dumps(playbook.to_dict(), indent=2))
    return 0


def cmd_share(args: argparse.Namespace) -> int:
    """Leave a trail where another agent can pick it up."""
    store = _store(args)
    published = store.share_trail(_site_key(args.site), args.task)
    if published is None:
        print(f"\n  {CROSS} no trail here to share. Run the task once first.\n")
        return 2

    print(f'\n  {TICK} shared "{published["task"]}" on {published["domain"]}')
    print(f"     {published['steps']} steps, as agent {published['shared_by']}")
    if published["notes_published"]:
        print("\n     these notes are now readable by every agent:")
        for note in published["notes_published"]:
            print(f"       - {note}")
    if published["pages_published"]:
        # Consent by inspection: whoever shares sees the exact list of pages that left,
        # the same way they already see every note. `dejo map` shows the contents.
        pages = published["pages_published"]
        print(f"\n     the map of {len(pages)} page(s) went with it:")
        for path in pages:
            print(f"       - {path}")
    if published["values_withheld"]:
        print("\n     what was typed here did NOT leave your machine:")
        for step in published["values_withheld"]:
            print(f"       - {step}")
    print()
    return 0


def cmd_borrow(args: argparse.Namespace) -> int:
    """Take a trail somebody else left for a site this agent has never walked."""
    store = _store(args)
    domain = _site_key(args.site)
    try:
        borrowed = store.borrow_trail(domain, args.task, force=args.force)
    except TrailAlreadyHere as clash:
        print(f"\n  {CROSS} {clash}\n     use --force if that is what you mean.\n")
        return 2

    if borrowed is None:
        print(f"\n  {CROSS} nobody has shared a trail for {domain}.\n")
        return 2

    print(f'\n  {TICK} borrowed "{borrowed.task}" from {borrowed.borrowed_from}')
    print(f"     {len(borrowed.steps)} steps, {borrowed.inherited_runs} clean runs behind it")
    needed = [step.secret for step in borrowed.steps if step.secret]
    if needed:
        print(f"     it will ask you for: {', '.join(needed)} — those were never shared")
    print(f'\n     now run:  dejo run "{borrowed.task}" --site {domain}\n')
    return 0


def cmd_commons(args: argparse.Namespace) -> int:
    """Everything any agent has shared, and who left it."""
    store = _store(args)
    offers = store.every_offer()
    if not offers:
        print("\n  nothing has been shared yet.\n")
        return 0

    print(f"\n  {len(offers)} shared trail(s):\n")
    for offer in offers:
        worked = f"worked for {offer['worked_for']}" if offer["worked_for"] else "untried"
        print(f"  {offer['domain']}")
        print(f'    "{offer["task"]}"')
        print(
            f"    left by {offer['shared_by']} · {offer['steps']} steps · "
            f"borrowed {offer['borrows']}x · {worked}"
        )
        if offer["contributors"]:
            print(f"    improved by {', '.join(offer['contributors'])}")
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dejo",
        description="A browser memory for AI agents. Learn a site once, replay it for free.",
    )
    parser.add_argument("--db", default=None, help="memory database (default: ~/.dejo/memory.db)")
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE_NAME,
        help="which signed-in browser to use. A profile is a whole browser of its own, so "
        "a vendor and an admin can both stay signed in. Made on first use",
    )
    parser.add_argument(
        "--agent",
        default=None,
        help="who is asking. Agents share one database and see only their own trails",
    )
    subs = parser.add_subparsers(dest="command", required=True)

    run = subs.add_parser("run", help="replay a remembered trail (no model calls)")
    run.add_argument(
        "task",
        nargs="?",
        default=None,
        help='what you want done, e.g. "download this month\'s invoice"',
    )
    run.add_argument("--site", required=True, help="domain or full url")
    run.add_argument("--url", default=None, help="override where the first step goes")
    run.add_argument("--headed", action="store_true", help="watch it happen")
    run.add_argument(
        "--json",
        action="store_true",
        help="print only the outcome, as one line of JSON, for scripts and schedulers",
    )
    run.set_defaults(func=cmd_run)

    login = subs.add_parser(
        "login", help="open a window and sign in yourself (Google, SSO, one-time codes)"
    )
    login.add_argument("--site", required=True, help="domain or full url")
    login.set_defaults(func=cmd_login)

    sites = subs.add_parser("sites", help="list every site Dejo remembers")
    sites.set_defaults(func=cmd_sites)

    show = subs.add_parser("show", help="print one trail, step by step")
    show.add_argument("domain")
    show.add_argument("--task", help="which trail, when the site has more than one")
    show.set_defaults(func=cmd_show)

    site_map = subs.add_parser("map", help="the pages Dejo has looked at on a site")
    site_map.add_argument("domain")
    site_map.add_argument(
        "--path",
        default=None,
        help="one page in full: its controls and when they were seen. "
        "The leading slash is optional, which matters on Git Bash — it rewrites "
        "/settings into a Windows path before Dejo ever sees it",
    )
    site_map.set_defaults(func=cmd_map)

    forget = subs.add_parser("forget", help="wipe one site from memory (the deletion gate)")
    forget.add_argument("--site", required=True)
    forget.set_defaults(func=cmd_forget)

    share = subs.add_parser("share", help="leave a trail for other agents to follow")
    share.add_argument("site", help="domain or full url")
    share.add_argument("--task", default=None, help="which trail, if the site has several")
    share.set_defaults(func=cmd_share)

    borrow = subs.add_parser("borrow", help="follow a trail another agent left")
    borrow.add_argument("site", help="domain or full url")
    borrow.add_argument("--task", default=None, help="which trail, if several were shared")
    borrow.add_argument(
        "--force", action="store_true", help="take it even over a trail you repaired"
    )
    borrow.set_defaults(func=cmd_borrow)

    commons = subs.add_parser("commons", help="every trail any agent has shared")
    commons.set_defaults(func=cmd_commons)

    doctor = subs.add_parser(
        "doctor", help="check this machine has everything Dejo needs, and say what to fix"
    )
    doctor.set_defaults(func=cmd_doctor)

    export = subs.add_parser("export", help="print the raw playbook as JSON")
    export.add_argument("domain")
    export.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


def console() -> int:
    """The `dejo` command. Brings an old ~/.cairn folder across once, then runs.

    Separate from `main` so tests, which call `main`, never touch the real home folder.
    """
    try:
        if adopt_old_home():
            print(f"\n  {TICK} moved your old ~/.cairn folder to ~/.dejo, so sign-ins are kept")
    except OldHomeNotMoved as stuck:
        print(f"\n  {CROSS} {stuck}\n")
        return 2
    try:
        if adopt_old_memory():
            print(f"  {TICK} brought your memory across from Sibyl, so every learned site is kept")
    except OldMemoryUnreadable as unreadable:
        print(f"\n  {CROSS} {unreadable}\n")
    return main()


if __name__ == "__main__":
    raise SystemExit(console())
