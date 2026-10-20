"""What a LEARNING run costs, turn by turn, and whether it actually learned.

    .venv/Scripts/python benchmarks/benchmark_learning.py --runs 3
    .venv/Scripts/python benchmarks/benchmark_learning.py --runs 3 --tools playwright

`benchmark_agents.py` answers "which tool is cheaper over ten repeats". This one answers the
question it could not: what does the FIRST run cost, and where do its tokens go. On 20 Oct a
Dejo learning run took 8-12 model turns where Playwright MCP took 4-7, and every turn
re-reads the whole context, so turns decide the bill. Every run here records:

- each turn's tokens, not only the total (see transcript.py);
- every tool call, with the size of what it sent and what came back;
- for Dejo, whether a trail was really saved, read straight from the run's own memory file.
  A learning run that answers but saves nothing has learned nothing: on 20 Oct one agent
  skipped `dejo_save`, and the next run explored from scratch;
- whether the answer is RIGHT, not only whether one came back. The older script counted
  "1170" as a success when the page said 170;
- for Dejo, a second session on the same memory, which must answer in one `dejo_run` call.

Every run gets its own memory file and its own empty browser profile, so run 1 is cold and
nothing a developer signed in to leaks in.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

from benchmark_agents import (
    ALL_TOOLS,
    COOLDOWN_S,
    EFFORT,
    JOURNEYS,
    MODEL,
    PLAYWRIGHT_MCP,
    Site,
    run_claude,
)
from transcript import Transcript, parse

HERE = Path(__file__).parent
DEJO_PREFIX = "mcp__dejo__"
# Claude Code loads MCP tools on demand through this built-in. It is a real turn, so it is
# counted, but it is not a browser call, so it is left out when judging "one call".
TOOL_SEARCH = "ToolSearch"
# A thousands separator, so "1,170" and "1170" read as the same number.
THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
# How long the script itself waits for a live answer to appear on the page. GitHub's issue
# count is drawn by script after the document loads, in a few seconds on a normal line.
LIVE_WAIT_S = 20
LIVE_POLL_MS = 500


@dataclass(frozen=True)
class Task:
    """A job with a known right answer.

    `truth` is fixed text for pages that do not change. `live_url` is for a page whose answer
    moves, like an open-issue count: the script opens that page itself just before and just
    after the session, takes the first group of `live_pattern` in the page's text, and either
    value counts as right. It reads the page the task points at, not a summary of it: GitHub's
    repo tab said 175 open issues while the Issues page said 173, and every agent, correctly,
    answered 173."""

    site: Site
    truth: tuple[str, ...] = ()
    live_url: str = ""
    live_pattern: str = ""


def _journey(domain: str) -> Site:
    return next(site for site in JOURNEYS if site.domain == domain)


# The three 20 Oct journeys, so the baseline lines up with what was measured that day. Tasks
# for the real-world bench are added here as rows, with their answers written down BEFORE
# any tool is run on them.
TASKS = [
    # The Issues page shows "Open" and then the count, to a signed-out visitor as well.
    Task(
        _journey("github.com"),
        live_url="https://github.com/microsoft/playwright/issues",
        live_pattern=r"\bOpen\s+(\d[\d,]*)",
    ),
    Task(_journey("books.toscrape.com"), truth=("£45.17",)),
    Task(_journey("quotes.toscrape.com"), truth=("March 14, 1879",)),
]


@dataclass
class Attempt:
    """One session, reduced to what a learning benchmark needs."""

    tool: str
    site: str
    run: int
    phase: str  # "learn", or "replay" for Dejo's second session on the same memory
    answer: str = ""
    correct: bool = False
    accepted: list[str] = field(default_factory=list)
    turns: int = 0
    tokens: int = 0
    reported_tokens: int | None = None
    context_per_turn: list[int] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    seconds: float = 0.0
    cost_usd: float = 0.0
    trails: dict[str, list[str]] = field(default_factory=dict)
    one_call: bool | None = None
    note: str = ""


def read_live(task: Task) -> str:
    """Read the right answer off the page with plain Playwright, no model involved.

    It waits for the ANSWER to appear, not for the page to go quiet: GitHub keeps requests
    open, so waiting for "networkidle" timed out and stopped a whole sweep. An empty string
    means the answer could not be read, and the run is marked unjudged rather than wrong."""
    from playwright.sync_api import Error, sync_playwright

    pattern = re.compile(task.live_pattern)
    try:
        with sync_playwright() as driver:
            browser = driver.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(task.live_url, wait_until="domcontentloaded")
                deadline = time.monotonic() + LIVE_WAIT_S
                while time.monotonic() < deadline:
                    match = pattern.search(page.locator("body").inner_text())
                    if match:
                        return THOUSANDS.sub("", match.group(1))
                    page.wait_for_timeout(LIVE_POLL_MS)
            finally:
                browser.close()
    except Error:
        return ""
    return ""


def is_correct(answer: str, accepted: list[str]) -> bool:
    """True when one accepted value appears in the answer as a whole value: "170" is in
    "170 open issues" but not in "1170"."""
    text = THOUSANDS.sub("", answer)
    return any(
        re.search(rf"(?<![\w.]){re.escape(value)}(?![\w])", text) for value in accepted if value
    )


def trails_in(memory: str) -> dict[str, list[str]]:
    """Every trail the run left in its own memory file, read through the store as Dejo
    itself would read it."""
    from dejo.store import DejoStore

    store = DejoStore(db_path=memory)
    return {domain: store.trails_for(domain) for domain in store.list_sites()}


def _fill(attempt: Attempt, transcript: Transcript, accepted: list[str]) -> None:
    attempt.answer = transcript.answer[:200]
    attempt.accepted = accepted
    attempt.correct = not transcript.is_error and is_correct(transcript.answer, accepted)
    attempt.turns = len(transcript.turns)
    attempt.tokens = transcript.tokens
    attempt.reported_tokens = transcript.reported_tokens
    attempt.context_per_turn = [turn.context for turn in transcript.turns]
    attempt.calls = [asdict(call) for call in transcript.calls]
    attempt.cost_usd = transcript.cost_usd


def session(tool: str, task: Task, run: int, phase: str, memory: str, where: Path) -> Attempt:
    attempt = Attempt(tool=tool, site=task.site.domain, run=run, phase=phase)
    before = read_live(task) if task.live_url else ""
    done = run_claude(tool, task.site, run, memory, where)
    after = read_live(task) if task.live_url else ""
    attempt.seconds = round(done.seconds, 1)
    if done.timed_out:
        attempt.note = "timed out"
        return attempt
    accepted = sorted({before, after} - {""}) if task.live_url else list(task.truth)
    transcript = parse(done.stdout.splitlines())
    _fill(attempt, transcript, accepted)
    if not accepted:
        attempt.note = "right answer could not be read from the page; not judged"
        return attempt
    if not transcript.answer:
        attempt.note = (done.stderr or "no result event")[:200]
    return attempt


def browser_calls(attempt: Attempt) -> list[str]:
    return [
        call["name"].removeprefix(DEJO_PREFIX)
        for call in attempt.calls
        if call["name"] != TOOL_SEARCH
    ]


def run_task(tool: str, task: Task, run: int, replay: bool) -> list[Attempt]:
    """One cold learning session, then for Dejo one warm session on the same memory."""
    folder = Path(mkdtemp(prefix="dejo-learning-"))
    memory = str(folder / "memory.db")
    learned = session(tool, task, run, "learn", memory, folder)
    found = [learned]
    if tool != "dejo":
        return found
    learned.trails = trails_in(memory)
    if replay:
        time.sleep(COOLDOWN_S)
        again = session(tool, task, run, "replay", memory, folder)
        again.one_call = again.correct and browser_calls(again) == ["dejo_run"]
        found.append(again)
    return found


def _git_commit() -> str:
    done = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=HERE, capture_output=True, text=True
    )
    return done.stdout.strip() or "unknown"


def _dejo_version() -> str:
    import dejo

    return dejo.__version__


def show(attempts: list[Attempt]) -> None:
    print(f"\n  {'tool':12}{'site':22}{'phase':8}{'run':>4}{'turns':>7}{'tokens':>10}  result")
    print("  " + "-" * 82)
    for a in attempts:
        verdict = "right" if a.correct else f"WRONG {a.note}".strip()
        extra = ""
        if a.phase == "learn" and a.tool == "dejo":
            extra = "  trail saved" if any(a.trails.values()) else "  NO TRAIL SAVED"
        if a.one_call is not None:
            extra = "  one call" if a.one_call else "  NOT one call"
        print(
            f"  {a.tool:12}{a.site:22}{a.phase:8}{a.run:>4}{a.turns:>7}{a.tokens:>10,}"
            f"  {verdict}{extra}"
        )


def _earlier_runs(out: Path, meta: dict[str, str]) -> list[dict[str, Any]]:
    """The runs a stopped sweep already wrote, refused if they were measured differently.
    Rows from another model, effort, Dejo version or commit do not belong in one table."""
    if not out.exists():
        return []
    found = json.loads(out.read_text(encoding="utf-8"))
    differs = {k for k in ("model", "effort", "dejo", "commit") if found["meta"].get(k) != meta[k]}
    if differs:
        raise SystemExit(f"{out} was measured with a different {', '.join(sorted(differs))}")
    return list(found["runs"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--tools", default="dejo", help=f"comma-separated, from {ALL_TOOLS}")
    parser.add_argument("--site", default="", help="only tasks whose domain contains this")
    parser.add_argument("--no-replay", action="store_true", help="skip Dejo's second session")
    parser.add_argument("--out", default="", help="results file (default: dated, beside this)")
    parser.add_argument(
        "--append",
        action="store_true",
        help="keep the runs already in --out and add these, for a sweep that was stopped",
    )
    args = parser.parse_args()

    tools = args.tools.split(",")
    unknown = set(tools) - set(ALL_TOOLS)
    if unknown:
        parser.error(f"unknown tool {sorted(unknown)}, have: {ALL_TOOLS}")
    tasks = [t for t in TASKS if args.site in t.site.domain]
    if not tasks:
        parser.error(f"no task matching {args.site!r}")

    out = Path(args.out) if args.out else HERE / f"benchmark-learning-{date.today()}.json"
    meta = {
        "date": str(date.today()),
        "model": MODEL,
        "effort": EFFORT,
        "dejo": _dejo_version(),
        "commit": _git_commit(),
        "playwright_mcp": PLAYWRIGHT_MCP,
    }
    earlier = _earlier_runs(out, meta) if args.append else []
    attempts: list[Attempt] = []
    for task in tasks:
        for tool in tools:
            for run in range(1, args.runs + 1):
                if attempts:
                    time.sleep(COOLDOWN_S)
                attempts.extend(run_task(tool, task, run, replay=not args.no_replay))
                show(attempts[-2:] if tool == "dejo" and not args.no_replay else attempts[-1:])
                # Written after every run, so a sweep stopped halfway keeps what it paid for.
                runs = earlier + [asdict(a) for a in attempts]
                out.write_text(json.dumps({"meta": meta, "runs": runs}, indent=1), encoding="utf-8")
    print("\n  all runs:")
    show(attempts)
    print(f"\n  Written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
