"""The same task, the same sites, through four different browser tools.

Run it yourself (needs Node for the two npx servers):

    .venv/Scripts/python benchmarks/benchmark_tools.py

Every tool is driven the way a host AI drives it: as an MCP server over stdio, counting the
calls it has to make and measuring the bytes it hands back. That is the fair lens, because
it is the only thing the model actually pays for.

WHAT THIS IS NOT. Playwright MCP and Chrome DevTools MCP are not trying to remember
anything, and nothing here suggests they are broken. They are excellent at what they do.
The comparison is narrow and stated plainly:

    Run 1: everyone is about the same.
    Run 2: everyone pays it again. Dejo does not.

That is the whole claim, and the second row is the only one where the tools differ.

The steps for each tool are written by hand, identically: open the page, look at it, read
one value. A real model takes MORE calls than this on every tool, so the numbers are a
floor for all of them equally.

`browser-use` is measured separately, because it needs an API key and real money; its
numbers and the exact command are in the results file rather than pretended to here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import mkdtemp

# Pinned so a rerun measures the same thing. An unpinned npx would quietly change the
# comparison between one run and the next.
PLAYWRIGHT_MCP = "@playwright/mcp@0.0.80"
DEVTOOLS_MCP = "chrome-devtools-mcp@1.8.0"

SETTLE_SECONDS = 3.0


@dataclass(frozen=True)
class Site:
    domain: str
    url: str
    task: str
    selector: str


# Chosen for a spread of page WEIGHT, because that is what decides the cost of looking.
# pkg.go.dev offers over 1,800 controls; quotes.toscrape.com offers 55.
SITES = [
    Site(
        "quotes.toscrape.com",
        "https://quotes.toscrape.com/",
        "read the first quote",
        ".quote .text",
    ),
    Site("books.toscrape.com", "https://books.toscrape.com/", "read the page heading", "h1"),
    Site(
        "news.ycombinator.com",
        "https://news.ycombinator.com/",
        "read the top story",
        ".titleline a",
    ),
    Site(
        "en.wikipedia.org",
        "https://en.wikipedia.org/wiki/Web_scraping",
        "read the article title",
        "h1",
    ),
    Site(
        "developer.mozilla.org",
        "https://developer.mozilla.org/en-US/docs/Web/API/fetch",
        "read the API name",
        "h1",
    ),
    Site("pkg.go.dev", "https://pkg.go.dev/net/http", "read the package heading", "h1"),
]


@dataclass
class Run:
    tool: str
    site: str
    run: int
    calls: int = 0
    bytes_to_model: int = 0
    seconds: float = 0.0
    answer: str = ""
    ok: bool = False
    note: str = ""


class Stdio:
    """The smallest MCP client that can drive a server honestly."""

    def __init__(self, command: list[str], env: dict[str, str] | None = None, name: str = "?"):
        self.name = name
        merged = dict(os.environ)
        merged.update(env or {})
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
        self._id = 0
        self.errors: list[str] = []
        threading.Thread(target=self._drain, daemon=True).start()
        self._send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "dejo-benchmark", "version": "1"},
            },
        )
        self._send("notifications/initialized", {}, notify=True)

    def _drain(self) -> None:
        for line in self.proc.stderr:
            self.errors.append(line.rstrip())

    def _send(self, method: str, params: dict | None = None, *, notify: bool = False):
        message: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notify:
            self._id += 1
            message["id"] = self._id
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(f"{self.name} stopped:\n" + "\n".join(self.errors[-12:]))
            try:
                reply = json.loads(line)
            except json.JSONDecodeError:
                continue
            if reply.get("id") == self._id:
                return reply

    def call(self, tool: str, **arguments) -> dict:
        """The whole result, so its size is what a model would really receive."""
        return self._send("tools/call", {"name": tool, "arguments": arguments}).get("result", {})

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=15)
        except Exception:  # noqa: BLE001 - a benchmark must not die tidying up
            self.proc.kill()


def _size(payload: object) -> int:
    return len(json.dumps(payload, default=str))


def _answered(payload: dict) -> str:
    """The text a model would actually get out of one tool result, or "" if it failed.

    MCP servers answer in two shapes — a structured object, or content blocks — and the
    three servers here do not agree on which. Reading both is what makes "did it work"
    mean the same thing for all of them.

    The `isError` check is not defensive tidiness; leaving it out produced a false
    benchmark. Every Chrome DevTools call failed on a missing argument, each returned a
    488-byte error string, and because an error message IS text this file reported six
    successful sites at 2,928 bytes — a number that would have beaten every other tool by
    making the one that never ran look the cheapest. Exactly the failure Dejo itself was
    fixed for twice today: reporting success for a result that is not there.
    """
    if payload.get("isError"):
        return ""
    structured = payload.get("structuredContent")
    if isinstance(structured, dict):
        for key in ("value", "result", "answers", "text"):
            if structured.get(key):
                return str(structured[key])
        return json.dumps(structured)
    for block in payload.get("content", []) or []:
        if block.get("text"):
            return str(block["text"])
    return ""


def _selected_page(payload: dict) -> int:
    """The page id Chrome DevTools MCP just opened, out of its plain-text listing.

    It answers with lines like `2: Quotes to Scrape (https://…) [selected]`, so the id has
    to be read back out of prose. Nothing else offers it.
    """
    for line in _answered(payload).splitlines():
        if "[selected]" in line and ":" in line:
            with suppress(ValueError):
                return int(line.split(":", 1)[0].strip())
    return 1


def _npx() -> str | None:
    """Node's runner, under whichever name this machine has for it."""
    return shutil.which("npx") or shutil.which("npx.cmd")


# ----------------------------------------------------------------- the four tools


def with_dejo(site: Site, memory: str) -> list[Run]:
    """Run 1 explores and saves. Run 2 is one call, because it was remembered."""
    import sys

    server = Stdio(
        [sys.executable, "-m", "dejo_mcp"],
        env={"DEJO_DB": memory, "DEJO_PROFILE": ""},
        name="dejo",
    )
    runs = []
    try:
        first = Run(tool="dejo", site=site.domain, run=1)
        began = time.perf_counter()
        first.bytes_to_model += _size(
            server.call("dejo_act", intent="open the site", action="goto", value=site.url)
        )
        time.sleep(SETTLE_SECONDS)
        first.bytes_to_model += _size(server.call("dejo_read", kind="page"))
        got = server.call(
            "dejo_read", kind="text", ref=site.selector, remember=True, intent=site.task
        )
        first.bytes_to_model += _size(got)
        first.bytes_to_model += _size(server.call("dejo_save", task=site.task))
        first.calls = 4
        first.seconds = time.perf_counter() - began
        first.answer = _answered(got)[:90]
        first.ok = bool(first.answer)
        runs.append(first)

        second = Run(tool="dejo", site=site.domain, run=2)
        began = time.perf_counter()
        replayed = server.call("dejo_run", site=site.domain, task=site.task, url=site.url)
        second.seconds = time.perf_counter() - began
        second.calls = 1
        second.bytes_to_model = _size(replayed)
        second.answer = _answered(replayed)[:90]
        # It only counts as a run if it came back with the ANSWER. A replay that finishes
        # and returns nothing is a failure wearing a success.
        second.ok = bool(second.answer) and "error" not in second.answer.lower()[:20]
        runs.append(second)
    finally:
        server.close()
    return runs


def with_playwright_mcp(site: Site) -> list[Run]:
    """Microsoft's browser MCP. It does not remember, so run 2 is run 1 again."""
    npx = _npx()
    if npx is None:
        return [Run(tool="playwright-mcp", site=site.domain, run=1, note="npx not on PATH")]
    runs = []
    for attempt in (1, 2):
        server = Stdio(
            [npx, "-y", PLAYWRIGHT_MCP, "--headless", "--isolated"], name="playwright-mcp"
        )
        row = Run(tool="playwright-mcp", site=site.domain, run=attempt)
        try:
            began = time.perf_counter()
            row.bytes_to_model += _size(server.call("browser_navigate", url=site.url))
            time.sleep(SETTLE_SECONDS)
            row.bytes_to_model += _size(server.call("browser_snapshot"))
            got = server.call(
                "browser_evaluate",
                function=f"() => document.querySelector({json.dumps(site.selector)})?.innerText",
            )
            row.bytes_to_model += _size(got)
            row.calls = 3
            row.seconds = time.perf_counter() - began
            row.answer = _answered(got)[:90]
            row.ok = bool(row.answer)
        except Exception as failed:  # noqa: BLE001 - a refusal is a result
            row.note = f"{type(failed).__name__}: {str(failed)[:70]}"
        finally:
            server.close()
        runs.append(row)
    return runs


def with_devtools_mcp(site: Site) -> list[Run]:
    """Google's browser MCP. Also does not remember."""
    npx = _npx()
    if npx is None:
        return [Run(tool="chrome-devtools-mcp", site=site.domain, run=1, note="npx not on PATH")]
    runs = []
    for attempt in (1, 2):
        server = Stdio([npx, "-y", DEVTOOLS_MCP, "--headless"], name="chrome-devtools-mcp")
        row = Run(tool="chrome-devtools-mcp", site=site.domain, run=attempt)
        try:
            began = time.perf_counter()
            # This server wants a `pageId` on everything, and will not take a default —
            # its own description of the argument reads as optional, and it is not. So the
            # page has to be opened first and its id read out of the listing.
            opened = server.call("new_page", url=site.url)
            row.bytes_to_model += _size(opened)
            page_id = _selected_page(opened)
            time.sleep(SETTLE_SECONDS)
            row.bytes_to_model += _size(server.call("take_snapshot", pageId=page_id))
            got = server.call(
                "evaluate_script",
                pageId=page_id,
                function=f"() => document.querySelector({json.dumps(site.selector)})?.innerText",
            )
            row.bytes_to_model += _size(got)
            row.calls = 3
            row.seconds = time.perf_counter() - began
            row.answer = _answered(got)[:90]
            row.ok = bool(row.answer)
        except Exception as failed:  # noqa: BLE001 - a refusal is a result
            row.note = f"{type(failed).__name__}: {str(failed)[:70]}"
        finally:
            server.close()
        runs.append(row)
    return runs


# ----------------------------------------------------------------------- reporting


def _table(rows: list[Run]) -> None:
    tools = sorted({row.tool for row in rows})
    print(f"\n\n  The same task on {len({r.site for r in rows})} sites, through each tool\n")
    print(f"  {'tool':22}{'run':>5}{'calls':>8}{'bytes to model':>17}{'seconds':>10}   sites ok")
    print("  " + "-" * 74)
    for tool in tools:
        for attempt in (1, 2):
            these = [r for r in rows if r.tool == tool and r.run == attempt and r.ok]
            if not these:
                continue
            print(
                f"  {tool:22}{attempt:>5}{sum(r.calls for r in these):>8}"
                f"{sum(r.bytes_to_model for r in these):>17,}"
                f"{sum(r.seconds for r in these):>10.1f}"
                f"   {len(these)}"
            )
    print()
    warm = [r for r in rows if r.tool == "dejo" and r.run == 2 and r.ok]
    others = [r for r in rows if r.tool != "dejo" and r.run == 2 and r.ok]
    if warm and others:
        mine = sum(r.bytes_to_model for r in warm)
        theirs = sum(r.bytes_to_model for r in others) / len({r.tool for r in others})
        print(
            f"  On the SECOND run of the same task, Dejo handed the model "
            f"{mine:,} bytes.\n  The tools that cannot remember handed it "
            f"{theirs:,.0f} — the same as their first run, because for them there is no\n"
            f"  such thing as a second run.\n"
        )


def main() -> int:
    rows: list[Run] = []
    for site in SITES:
        print(f"\n  {site.domain}")
        memory = str(Path(mkdtemp()) / "memory.db")
        for name, runner in (
            ("dejo", lambda s=site, m=memory: with_dejo(s, m)),
            ("playwright-mcp", lambda s=site: with_playwright_mcp(s)),
            ("chrome-devtools-mcp", lambda s=site: with_devtools_mcp(s)),
        ):
            try:
                got = runner()
            except Exception as broke:  # noqa: BLE001 - report, never abort the sweep
                got = [Run(tool=name, site=site.domain, run=1, note=str(broke)[:80])]
            rows.extend(got)
            done = [r for r in got if r.ok]
            print(f"    {name:22} {len(done)}/2 runs ok")

    _table(rows)
    Path("benchmark-tools.json").write_text(
        json.dumps([asdict(row) for row in rows], indent=2), encoding="utf-8"
    )
    print("  Written to benchmark-tools.json\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
