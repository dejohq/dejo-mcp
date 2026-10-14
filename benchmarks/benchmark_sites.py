"""Two dozen real websites, learned once, then replayed from memory.

Run it yourself:

    .venv/Scripts/python benchmarks/benchmark_sites.py

Every site here is PUBLIC and needs no login, so anyone can rerun this and get their own
numbers. That is the point: a benchmark nobody can reproduce is a claim, not evidence.

What is measured, and what each number honestly means:

- **tool calls** — what the AI has to issue. The thing it actually pays attention to.
- **page reads** — how many times a whole control list was handed over. This is the
  expensive half of using a website with a model.
- **bytes to model** — how much text the tool hands back across the task. The nearest
  honest proxy for tokens. We do not claim token counts: measuring those needs a model,
  and this file deliberately uses none.
- **model calls** — zero throughout. Replay is plain Python.
- **seconds** — the least interesting column. There is no model thinking in here, and
  thinking time is the cost memory actually removes.

The cold run is SCRIPTED: the steps a host AI would take, written by hand. A real model
takes more calls than this, not fewer, because it has to read the page to decide what to do
next. So the cold numbers are a FLOOR, and the saving shown is the smallest one honestly
available.

Sites move, and some block automated browsers outright. Failures are printed in the table
rather than dropped — a table with only successes in it is marketing.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import mkdtemp

from dejo.browser import Browser
from dejo.executor import Executor
from dejo.operations import Session
from dejo.store import DejoStore

# How long to let a real site settle before reading it. Generous on purpose: these are
# other people's websites over somebody's home connection, and calling a slow site a
# failure would be a lie about the tool.
SETTLE_MS = 3500
PAGE_TIMEOUT_MS = 30000


@dataclass(frozen=True)
class Site:
    """One site, and one real thing to read on it."""

    domain: str
    url: str
    task: str
    selector: str


# `>> nth=0` is Playwright's "the first of these" and it is written out on purpose. Dejo
# refuses a selector that matches several things rather than guessing, and this benchmark
# is not exempt from that — six of these selectors were quietly reading the first of many
# until the check was added, `.titleline a` matching sixty elements among them.
#
# Three kinds on purpose: sites built for automation (nobody can object to those), public
# developer sites that are stable, and busy real-world pages where the control lists are
# enormous — which is exactly where reading a page costs the most.
SITES = [
    Site("books.toscrape.com", "https://books.toscrape.com/", "read the page heading", "h1"),
    Site(
        "quotes.toscrape.com",
        "https://quotes.toscrape.com/",
        "read the first quote",
        ".quote .text >> nth=0",
    ),
    Site(
        "the-internet.herokuapp.com",
        "https://the-internet.herokuapp.com/",
        "read the heading",
        "h1.heading",
    ),
    Site(
        "demoblaze.com",
        "https://www.demoblaze.com/",
        "read the first product name",
        ".card-title a >> nth=0",
    ),
    Site("httpbin.org", "https://httpbin.org/", "read the service version", "h2.title"),
    Site(
        "webscraper.io",
        "https://webscraper.io/test-sites/e-commerce/allinone",
        "read the page title",
        "h1",
    ),
    Site(
        "www.scrapethissite.com",
        "https://www.scrapethissite.com/pages/simple/",
        "read the page heading",
        "h1",
    ),
    Site(
        "developer.mozilla.org",
        "https://developer.mozilla.org/en-US/docs/Web/API/fetch",
        "read the API name",
        "h1",
    ),
    Site(
        "docs.python.org",
        "https://docs.python.org/3/library/pathlib.html",
        "read the module heading",
        "h1",
    ),
    Site(
        "en.wikipedia.org",
        "https://en.wikipedia.org/wiki/Web_scraping",
        "read the article title",
        "h1",
    ),
    Site("pkg.go.dev", "https://pkg.go.dev/net/http", "read the package heading", "h1"),
    Site("crates.io", "https://crates.io/crates/serde", "read the crate name", "h1 span"),
    Site(
        "www.npmjs.com",
        "https://www.npmjs.com/package/playwright",
        "read the docs heading",
        "main h2 >> nth=0",
    ),
    Site("huggingface.co", "https://huggingface.co/models", "read the page heading", "h1"),
    Site(
        "github.com",
        "https://github.com/microsoft/playwright",
        "count open issues",
        "#issues-repo-tab-count",
    ),
    Site(
        "news.ycombinator.com",
        "https://news.ycombinator.com/",
        "read the top story",
        ".titleline a >> nth=0",
    ),
    Site("realpython.com", "https://realpython.com/", "read the latest article", "h2 >> nth=0"),
    Site("archive.org", "https://archive.org/", "read the tagline", "h1 >> nth=0"),
    Site("playwright.dev", "https://playwright.dev/", "read the tagline", "h1"),
    Site("www.python.org", "https://www.python.org/", "read the introduction", ".introduction"),
    Site("nodejs.org", "https://nodejs.org/en", "read the tagline", "h1"),
    Site("go.dev", "https://go.dev/", "read the tagline", "h1"),
    Site("www.rust-lang.org", "https://www.rust-lang.org/", "read the heading", "h1"),
    Site("fastapi.tiangolo.com", "https://fastapi.tiangolo.com/", "read the heading", "h1"),
    # Kept in deliberately. Both have refused an automated browser before, and a benchmark
    # that quietly drops the sites it loses on is not a benchmark.
    Site(
        "stackoverflow.com",
        "https://stackoverflow.com/questions/tagged/playwright",
        "read the heading",
        "h1",
    ),
    Site(
        "pypi.org",
        "https://pypi.org/project/requests/",
        "read the package name",
        ".package-header__name",
    ),
]


@dataclass
class Measured:
    """What one task cost, cold and then warm."""

    site: str
    task: str
    ok: bool = False
    note: str = ""
    cold_calls: int = 0
    cold_reads: int = 0
    cold_bytes: int = 0
    cold_seconds: float = 0.0
    warm_calls: int = 0
    warm_reads: int = 0
    warm_bytes: int = 0
    warm_seconds: float = 0.0
    model_calls: int = 0
    answer: str = ""
    answer_again: str = ""
    steps: int = 0
    controls_on_page: int = 0
    extras: dict = field(default_factory=dict)


def _size(payload: object) -> int:
    """How much text this result would put in front of a model."""
    return len(json.dumps(payload, default=str))


def learn(browser: Browser, store: DejoStore, site: Site) -> Measured:
    """The cold run: what the task costs with nothing remembered."""
    row = Measured(site=site.domain, task=site.task)
    session = Session(browser, store)
    began = time.perf_counter()

    session.act("open the site", "goto", value=site.url)
    browser.wait_until_quiet(SETTLE_MS)

    page = session.look()
    row.cold_reads += 1
    row.cold_bytes += _size(page)
    row.controls_on_page = len(page.get("elements", []))

    answer = session.read("text", ref=site.selector, remember=True, intent=site.task)
    row.cold_bytes += _size(answer)
    row.answer = str(answer).strip().replace("\n", " ")[:70]
    if not row.answer:
        raise RuntimeError(f"nothing readable at {site.selector}")

    playbook = session.save(site.task, domain=site.domain)
    row.steps = len(playbook.steps)
    row.cold_calls = session.tool_calls
    row.cold_seconds = time.perf_counter() - began
    return row


def replay(browser: Browser, store: DejoStore, site: Site, row: Measured) -> Measured:
    """The warm run: one call, nothing read, no model."""
    began = time.perf_counter()
    result = Executor(store, browser).run(site.domain, task=site.task, start_url=site.url)
    row.warm_seconds = time.perf_counter() - began
    row.warm_calls = 1
    row.warm_reads = 0
    row.warm_bytes = _size(
        {
            "ok": result.ok,
            "steps_replayed": result.metrics.steps_replayed,
            "answers": result.answers,
            "duration_ms": result.metrics.duration_ms,
        }
    )
    row.answer_again = str(next(iter(result.answers.values()), ""))[:70]
    row.ok = result.ok and bool(row.answer_again)
    if not row.ok:
        row.note = "replayed but returned nothing"
    return row


def measure(site: Site) -> Measured:
    """One site, learned then replayed, in its own memory so cold is genuinely cold."""
    store = DejoStore(db_path=str(Path(mkdtemp()) / "memory.db"))
    with Browser(headless=True, timeout_ms=PAGE_TIMEOUT_MS) as browser:
        row = learn(browser, store, site)
        return replay(browser, store, site, row)


def _print_table(rows: list[Measured]) -> None:
    worked = [row for row in rows if row.ok]
    print(f"\n\n  {len(worked)} of {len(rows)} sites: learned once, then replayed from memory\n")
    print(f"  {'site':28}{'calls':>12}{'page reads':>14}{'bytes to model':>18}{'seconds':>14}")
    print(f"  {'':28}{'cold warm':>12}{'cold warm':>14}{'cold      warm':>18}{'cold  warm':>14}")
    print("  " + "-" * 88)
    for row in rows:
        if not row.ok:
            print(f"  {row.site:28}  {row.note}")
            continue
        print(
            f"  {row.site:28}{row.cold_calls:>7}{row.warm_calls:>5}"
            f"{row.cold_reads:>9}{row.warm_reads:>5}"
            f"{row.cold_bytes:>12,}{row.warm_bytes:>6,}"
            f"{row.cold_seconds:>10.1f}{row.warm_seconds:>6.1f}"
        )

    if not worked:
        return
    cold_bytes = sum(row.cold_bytes for row in worked)
    warm_bytes = sum(row.warm_bytes for row in worked)
    print("  " + "-" * 88)
    print(
        f"  {'TOTAL':28}{sum(r.cold_calls for r in worked):>7}"
        f"{sum(r.warm_calls for r in worked):>5}"
        f"{sum(r.cold_reads for r in worked):>9}{0:>5}"
        f"{cold_bytes:>12,}{warm_bytes:>6,}"
        f"{sum(r.cold_seconds for r in worked):>10.1f}"
        f"{sum(r.warm_seconds for r in worked):>6.1f}"
    )
    print(
        f"\n  Model calls: 0, every run, every site — replay is plain Python.\n"
        f"  Page reads: {sum(r.cold_reads for r in worked)} became 0.\n"
        f"  Text handed to the model: {1 - warm_bytes / cold_bytes:.1%} less on the second run.\n"
    )


def main() -> int:
    rows: list[Measured] = []
    for site in SITES:
        try:
            rows.append(measure(site))
        except Exception as refused:  # noqa: BLE001 - a refusal is a result, not a crash
            rows.append(
                Measured(
                    site=site.domain,
                    task=site.task,
                    note=f"{type(refused).__name__}: {str(refused).splitlines()[0][:60]}",
                )
            )
        print(f"  {rows[-1].site:28} {'ok' if rows[-1].ok else 'FAILED — ' + rows[-1].note}")

    _print_table(rows)
    Path("benchmark-sites.json").write_text(
        json.dumps([asdict(row) for row in rows], indent=2), encoding="utf-8"
    )
    print("  Written to benchmark-sites.json\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
