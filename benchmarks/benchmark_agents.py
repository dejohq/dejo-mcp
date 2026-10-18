"""The real benchmark: one model, one task, four browser tools, three runs each.

    .venv/Scripts/python benchmarks/benchmark_agents.py --sites 1 --runs 3     # a pilot
    .venv/Scripts/python benchmarks/benchmark_agents.py                        # the sweep

Everything before this measured Dejo against ITSELF — cold versus warm — which is a
before-and-after, not a benchmark. Here every tool is driven by the same real model doing
the same real job, so the rows are comparable the way a model card's rows are.

    Playwright MCP        driven by Claude
    Chrome DevTools MCP   driven by Claude
    Dejo                  driven by Claude
    Playwright CLI        driven by Claude, through Bash and the CLI's own skill (--tools)
    Claude in Chrome      driven by Claude, in the person's own Chrome (--tools)
    browser-use           driven by its own model (below)

The axis is REPETITION, because that is what actually happens: a daily invoice check, a
test suite on every commit, a dashboard read every morning. Nobody does a web task once.
Run 1 is where Dejo loses — it pays an extra call to write the trail down — and the
number worth reading is which run it overtakes on.

`browser-use` is the odd row on purpose. It brings its own model, so it is the only one
that cannot answer without thinking, and the only one with a `model calls` column that is
not zero. It runs on OpenRouter; everything else runs on Claude.

A plain Playwright script is deliberately NOT here. It scores zero forever, but only
because a person wrote the selectors by hand and rewrites them when the site moves — which
is a different activity, not a better score.

Needs: the `claude` CLI signed in, Node for the two npx servers, and OPENROUTER_API_KEY
for the browser-use row only.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

# The model every tool-driving row shares. Named, because a benchmark whose model can
# change underneath it is measuring two things at once.
# Sonnet rather than Opus on purpose. What this measures is TOKENS, and tokens barely move
# with the model: Playwright MCP pushes a 500 KB page snapshot into the context whichever
# model is reading it, so a smarter model would buy nothing here and cost several times as
# much. Medium effort rather than low, because the model has to actually follow each tool's
# instructions — Dejo's "call dejo_run first" among them — and a row where the model
# ignored the tool is a rerun, not a result.
MODEL = "claude-sonnet-5"
EFFORT = "medium"

# Pinned, so a rerun measures the same servers.
PLAYWRIGHT_MCP = "@playwright/mcp@0.0.80"
DEVTOOLS_MCP = "chrome-devtools-mcp@1.8.0"
# Playwright CLI is not an MCP server: the agent runs it through Bash, guided by the skill it
# installs. It must be on PATH at exactly this version: npm install -g @playwright/cli@0.1.22
PLAYWRIGHT_CLI_VERSION = "0.1.22"

# Every row the script knows. The first three are the published head-to-head; the last two
# are the ways Claude Code users drive a browser without an MCP server of their own.
MCP_TOOLS = ["dejo", "playwright", "chrome-devtools"]
ALL_TOOLS = [*MCP_TOOLS, "playwright-cli", "claude-in-chrome"]
BROWSER_USE_MODEL = "google/gemini-2.5-flash-lite"

DEJO_MCP = str(Path(sys.executable).with_name("dejo-mcp.exe"))
RUN_TIMEOUT_S = 300

# A sweep is 90 real browser sessions back to back, which turns a laptop into a heater and
# makes it useless to its owner for an hour. Two things fix that without changing a single
# measured number: every child runs BELOW normal priority, so anything the person is doing
# wins the CPU, and there is a gap between runs for the fans to catch up. The work is
# already sequential — one session at a time — so nothing here is about parallelism.
COOLDOWN_S = 4.0
BELOW_NORMAL = 0x00004000  # Windows CREATE_NO_WINDOW-adjacent flag: BELOW_NORMAL_PRIORITY_CLASS


def _gently() -> dict[str, Any]:
    """Start a child process without letting it fight the user for the machine."""
    if sys.platform == "win32":
        return {"creationflags": BELOW_NORMAL}
    # POSIX: nice the child, which its own children inherit.
    return {"preexec_fn": lambda: os.nice(10)}  # noqa: PLW1509


# The job is "use this browser tool". Anything else that can reach a website, read a file
# or run a command is a way of not doing that.
BUILT_INS = [
    "WebFetch",
    "WebSearch",
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "Task",
    "NotebookEdit",
]


def _cli(name: str) -> str:
    """A Node CLI's real filename. On Windows the bare name is a shell shim that
    `subprocess` cannot start, and `npx`/`claude` are both installed that way."""
    return shutil.which(name) or shutil.which(f"{name}.cmd") or name


@dataclass(frozen=True)
class Site:
    domain: str
    url: str
    asked: str


# Four, chosen for a spread of page weight: the
# cost of looking at a page is what separates these tools, and pkg.go.dev offers over
# 1,800 controls where quotes.toscrape.com offers 55.
SITES = [
    Site(
        "quotes.toscrape.com",
        "https://quotes.toscrape.com/",
        "tell me the exact text of the first quote on the page",
    ),
    Site(
        "news.ycombinator.com",
        "https://news.ycombinator.com/",
        "tell me the title of the top story",
    ),
    Site(
        "developer.mozilla.org",
        "https://developer.mozilla.org/en-US/docs/Web/API/fetch",
        "tell me the main heading of the page",
    ),
    Site(
        "pkg.go.dev",
        "https://pkg.go.dev/net/http",
        "tell me the main heading of the page",
    ),
    # Chosen 2026-09-05, BEFORE any of them was measured, and every one of them is
    # published whatever it says. Picking sites after seeing their numbers is how a
    # benchmark becomes an advertisement.
    #
    # stackoverflow.com and npmjs.com were deliberately left out: both put up bot walls,
    # and a run that fails for that reason measures nothing and still costs money.
    Site(
        "en.wikipedia.org",
        "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "tell me the main heading of the page",
    ),
    Site(
        "github.com",
        "https://github.com/microsoft/playwright",
        "tell me the main heading of the page",
    ),
    Site(
        "docs.python.org",
        "https://docs.python.org/3/library/os.html",
        "tell me the main heading of the page",
    ),
    Site(
        "pypi.org",
        "https://pypi.org/project/requests/",
        "tell me the main heading of the page",
    ),
    Site(
        "huggingface.co",
        "https://huggingface.co/google-bert/bert-base-uncased",
        "tell me the main heading of the page",
    ),
]

# The six above are all the same shape: open one page, read one line off it. That is the
# CHEAPEST thing a browser tool ever does — two or three calls for anybody — so memory has
# almost nothing to save, and the six-site table came out at 188 calls against 206. A 9%
# saving is a true number and a useless one.
#
# Real work has steps. Open the site, find the section, open the item, read the value. A
# tool with no memory pays to look at the page again at EVERY step, on EVERY run, forever.
# A trail costs one call whether it is two steps or twenty. These journeys measure that,
# through the same real Claude session as everything else — Dejo is an MCP server, so a
# hand-written script would measure a floor that no user ever experiences.
JOURNEYS = [
    Site(
        "github.com",
        "https://github.com/microsoft/playwright",
        "open the Issues tab and tell me how many open issues the repository has",
    ),
    Site(
        "books.toscrape.com",
        "http://books.toscrape.com/",
        "open the Travel category, open the first book listed, and tell me its price",
    ),
    Site(
        "quotes.toscrape.com",
        "https://quotes.toscrape.com/",
        "open the About page of the first quote's author and tell me the date they were born",
    ),
]


def ask(site: Site, tool: str = "") -> str:
    """The identical job, worded the same for every tool.

    One exception. An MCP server's tools are the only browser Claude can see, so "open it
    in the browser" is enough. Playwright CLI is a skill on top of Bash, and a pilot given
    the plain wording never opened it: it tried curl, was refused, and gave up. Its README
    tells people to name it in the request, so that row gets the sentence its own docs say
    to add, and nothing else."""
    job = (
        f"Open {site.url} in the browser and {site.asked}. "
        f"Reply with only that text and nothing else."
    )
    return f"{job} Use playwright-cli." if tool == "playwright-cli" else job


@dataclass
class Run:
    tool: str
    site: str
    run: int
    ok: bool = False
    answer: str = ""
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    model_calls: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    note: str = ""
    called: list[str] = field(default_factory=list)
    """Which tools, in order. The only way to see WHY a row cost what it cost — a warm
    run that explored anyway looks identical to a slow one until you read this."""

    @property
    def tokens(self) -> int:
        """Everything the model had to be given or produced, cache included.

        The cache columns are counted because they are real tokens the model reads. A tool
        that hands back a 500 KB page snapshot pays for it whether or not the bytes were
        cached from a previous turn."""
        return self.input_tokens + self.output_tokens + self.cache_read + self.cache_write


# ------------------------------------------------------------------ claude-driven rows


def _config(name: str, server: dict, where: Path) -> Path:
    path = where / f"mcp-{name}.json"
    path.write_text(json.dumps({"mcpServers": {name: server}}), encoding="utf-8")
    return path


def _server(name: str, memory: str) -> dict:
    """How each MCP server is started, and nothing else about it."""
    npx = _cli("npx")
    if name == "dejo":
        # A clean browser profile, and one memory per SITE so that run 1 is genuinely
        # cold and runs 2 and 3 are genuinely warm.
        return {"command": DEJO_MCP, "env": {"DEJO_PROFILE": "", "DEJO_DB": memory}}
    if name == "playwright":
        return {"command": npx, "args": ["-y", PLAYWRIGHT_MCP, "--headless", "--isolated"]}
    return {"command": npx, "args": ["-y", DEVTOOLS_MCP, "--headless"]}


def _tool_args(name: str, memory: str, where: Path) -> list[str]:
    """The flags that hand Claude exactly one browser tool and take every other way away.

    Everything a model could use to SHORTCUT the browser must be taken away, or the
    benchmark measures nothing. The first pilot spent two of three runs on WebFetch — it
    fetched the page over HTTP and answered — while being recorded as a browser-tool
    result. `--allowedTools` permits a tool; it does not forbid the built-in ones, and a
    model reaches for the cheapest thing that works."""
    if name == "playwright-cli":
        # The CLI is driven through Bash and reports pages as snapshot files the model
        # reads, so Bash (only `playwright-cli` commands) and Read stay. A denied rule
        # outranks an allowed one, so Bash cannot also sit in the disallowed list; in
        # print mode any other command is refused anyway, because nobody is there to
        # approve it.
        kept = {"Bash", "Read"}
        allowed = ["Bash(playwright-cli:*)", "Read", "Skill"]
        return [
            "--allowedTools",
            *allowed,
            "--disallowedTools",
            *[t for t in BUILT_INS if t not in kept],
        ]
    if name == "claude-in-chrome":
        # Anthropic's extension in the person's own Chrome: no server to configure.
        return [
            "--chrome",
            "--allowedTools",
            "mcp__claude-in-chrome",
            "--disallowedTools",
            *BUILT_INS,
        ]
    config = _config(name, _server(name, memory), where)
    return [
        "--mcp-config",
        str(config),
        "--allowedTools",
        f"mcp__{name}",
        "--disallowedTools",
        *BUILT_INS,
    ]


def _fresh_cli_workspace(where: Path, attempt: int) -> Path:
    """A new folder with the CLI's skill installed, so every session starts from nothing,
    exactly like a new Claude Code session in a project that uses the CLI."""
    folder = where / f"cli-run-{attempt}-{time.monotonic_ns()}"
    folder.mkdir()
    subprocess.run(
        [_cli("playwright-cli"), "install", "--skills"],
        cwd=folder,
        capture_output=True,
        check=True,
        **_gently(),
    )
    return folder


def with_claude(name: str, site: Site, attempt: int, memory: str, where: Path) -> Run:
    """One real Claude session, given one browser tool and one job."""
    row = Run(tool=name, site=site.domain, run=attempt)
    if name == "playwright-cli":
        where = _fresh_cli_workspace(where, attempt)
    command = [
        _cli("claude"),
        "-p",
        ask(site, name),
        *_tool_args(name, memory, where),
        # Only the server this row names. Without it Claude also loads every MCP server
        # the person has configured for themselves: a Playwright CLI pilot ignored the CLI
        # and called a user-wide Dejo instead, and was recorded as a CLI result.
        "--strict-mcp-config",
        "--model",
        MODEL,
        "--effort",
        EFFORT,
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    began = time.perf_counter()
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_S,
            cwd=where,
            encoding="utf-8",
            errors="replace",
            **_gently(),
        )
    except subprocess.TimeoutExpired:
        row.note = "timed out"
        row.seconds = time.perf_counter() - began
        return row
    finally:
        if name == "playwright-cli":
            # A headless CLI browser outlives the session for an hour by default, and the
            # next run must not find it open.
            subprocess.run(
                [_cli("playwright-cli"), "close-all"], cwd=where, capture_output=True, **_gently()
            )
    row.seconds = time.perf_counter() - began
    _read_stream(row, done.stdout)
    if not row.ok and not row.note:
        row.note = (done.stderr or "no result event")[:90]
    return row


def _read_stream(row: Run, output: str) -> None:
    """Pull the tool calls and the token bill out of Claude's own event stream."""
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if event.get("type") == "assistant":
            body = event.get("message", {})
            row.model_calls += 1
            for block in body.get("content", []) or []:
                if block.get("type") == "tool_use":
                    row.tool_calls += 1
                    row.called.append(str(block.get("name", "?")).replace("mcp__", ""))

        if event.get("type") == "result":
            usage = event.get("usage", {}) or {}
            row.input_tokens = usage.get("input_tokens", 0)
            row.output_tokens = usage.get("output_tokens", 0)
            row.cache_read = usage.get("cache_read_input_tokens", 0)
            row.cache_write = usage.get("cache_creation_input_tokens", 0)
            row.cost_usd = event.get("total_cost_usd", 0.0) or 0.0
            row.answer = str(event.get("result", ""))[:90]
            row.ok = not event.get("is_error", False) and bool(row.answer)


# --------------------------------------------------------------------- browser-use row


def with_browser_use(site: Site, attempt: int, runner: str, where: Path) -> Run:
    """The one row that brings its own model, so its `model calls` are never zero."""
    row = Run(tool="browser-use", site=site.domain, run=attempt)
    script = where / "run_browser_use.py"
    script.write_text(_BROWSER_USE_RUNNER, encoding="utf-8")
    began = time.perf_counter()
    try:
        done = subprocess.run(
            [runner, str(script), ask(site), BROWSER_USE_MODEL],
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_S,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        row.note = "timed out"
        row.seconds = time.perf_counter() - began
        return row
    row.seconds = time.perf_counter() - began
    for line in reversed(done.stdout.splitlines()):
        if line.startswith("DEJO_BENCH "):
            got = json.loads(line[len("DEJO_BENCH ") :])
            row.input_tokens = got["input"]
            row.output_tokens = got["output"]
            row.model_calls = got["calls"]
            row.tool_calls = got["steps"]
            row.answer = str(got["answer"])[:90]
            row.ok = bool(row.answer)
            return row
    row.note = (done.stderr or "no result line")[:90]
    return row


_BROWSER_USE_RUNNER = '''"""Run one browser-use task and print its cost as one JSON line."""
import asyncio, json, os, sys
from browser_use import Agent
from browser_use.llm.openrouter.chat import ChatOpenRouter

async def main() -> None:
    task, model = sys.argv[1], sys.argv[2]
    key = os.environ["OPENROUTER_API_KEY"]
    agent = Agent(task=task, llm=ChatOpenRouter(model=model, api_key=key))
    history = await agent.run(max_steps=12)
    usage = history.usage
    print("DEJO_BENCH " + json.dumps({
        "input": getattr(usage, "total_prompt_tokens", 0),
        "output": getattr(usage, "total_completion_tokens", 0),
        "calls": getattr(usage, "entry_count", 0),
        "steps": history.number_of_steps() if hasattr(history, "number_of_steps") else 0,
        "answer": history.final_result() or "",
    }))

asyncio.run(main())
'''


# ------------------------------------------------------------------------- reporting


@dataclass
class Table:
    rows: list[Run] = field(default_factory=list)

    def by(self, tool: str, attempt: int) -> list[Run]:
        return [r for r in self.rows if r.tool == tool and r.run == attempt and r.ok]

    def show(self, runs: int) -> None:
        tools = sorted({r.tool for r in self.rows})
        print(f"\n\n  One model, one task, {len({r.site for r in self.rows})} sites\n")
        head = f"  {'tool':22}{'run':>4}{'tokens':>12}{'tool calls':>12}"
        print(head + f"{'model calls':>13}{'seconds':>10}  ok")
        print("  " + "-" * 78)
        for tool in tools:
            for attempt in range(1, runs + 1):
                these = self.by(tool, attempt)
                if not these:
                    continue
                print(
                    f"  {tool:22}{attempt:>4}{sum(r.tokens for r in these):>12,}"
                    f"{sum(r.tool_calls for r in these):>12}"
                    f"{sum(r.model_calls for r in these):>13}"
                    f"{sum(r.seconds for r in these):>10.1f}  {len(these)}"
                )
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", type=int, default=len(SITES))
    parser.add_argument("--site", default="", help="one domain, for a single-site curve")
    parser.add_argument(
        "--journeys", action="store_true", help="the multi-step tasks instead of the lookups"
    )
    # Every sweep used to write the same file, so a single-site re-measure silently
    # replaced a full head-to-head that cost real money to produce.
    parser.add_argument("--out", default="benchmark-agents.json", help="where to write it")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--tools",
        default=",".join(MCP_TOOLS),
        help=f"comma-separated rows to run, from: {', '.join(ALL_TOOLS)}. claude-in-chrome needs "
        "the extension connected to a Chrome on this machine, and opens real tabs in it",
    )
    parser.add_argument("--only", default="", help="one tool, for diagnosing a row")
    parser.add_argument("--skip-browser-use", action="store_true")
    parser.add_argument("--browser-use-python", default=os.environ.get("BROWSER_USE_PYTHON", ""))
    args = parser.parse_args()

    unknown = ({args.only} - {""} | set(args.tools.split(","))) - set(ALL_TOOLS)
    if unknown:
        parser.error(f"unknown tool {sorted(unknown)} — have: {ALL_TOOLS}")

    where = Path(mkdtemp())
    table = Table()
    pool = JOURNEYS if args.journeys else SITES
    chosen = [s for s in pool if args.site in s.domain] if args.site else pool[: args.sites]
    if not chosen:
        parser.error(f"no site matching {args.site!r} — have: {[s.domain for s in pool]}")

    for site in chosen:
        print(f"\n  {site.domain}")
        wanted = [args.only] if args.only else args.tools.split(",")
        for name in wanted:
            memory = str(Path(mkdtemp()) / "memory.db")
            for attempt in range(1, args.runs + 1):
                if table.rows:
                    time.sleep(COOLDOWN_S)
                row = with_claude(name, site, attempt, memory, where)
                table.rows.append(row)
                print(
                    f"    {name:16} run {attempt}  "
                    f"{'ok' if row.ok else 'FAILED ' + row.note}  "
                    f"{row.tokens:,} tokens, {row.tool_calls} calls, {row.seconds:.0f}s"
                )
        if not args.skip_browser_use and args.browser_use_python:
            for attempt in range(1, args.runs + 1):
                row = with_browser_use(site, attempt, args.browser_use_python, where)
                table.rows.append(row)
                print(
                    f"    {'browser-use':16} run {attempt}  "
                    f"{'ok' if row.ok else 'FAILED ' + row.note}  "
                    f"{row.tokens:,} tokens, {row.model_calls} model calls"
                )

    table.show(args.runs)
    spent = sum(r.cost_usd for r in table.rows)
    print(f"  Claude list cost for this sweep: ${spent:.2f}\n")
    Path(args.out).write_text(
        json.dumps([asdict(r) for r in table.rows], indent=2), encoding="utf-8"
    )
    print(f"  Written to {args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
