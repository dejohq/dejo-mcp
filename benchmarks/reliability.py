"""How reliably Dejo picks and uses page elements on real websites, with no model anywhere.

Run it from the repo root, inside the project's virtualenv:

    python benchmarks/reliability.py                     # every task, Dejo only
    python benchmarks/reliability.py --reference         # also run plain Playwright
    python benchmarks/reliability.py --only R01,R30      # a few tasks

Every task in `reliability_tasks.py` is a FIXED program in the step language `dejo_run`
takes, written once by hand after looking at the page, and ending in a `read`. Nothing
decides anything while the benchmark runs, so a failure is Dejo's, or the site's, and never
a model's bad day. Tasks only open pages, read, search and click links, tabs and filters:
nothing is sent, bought, posted or signed into.

Each task runs in its own process with a fresh, empty browser and a throwaway memory, so one
site that hangs or crashes the browser cannot take the next task with it.

`--reference` runs the same programs through plain Playwright as well, the way a person
using Playwright would write them: `link "Travel"` is `get_by_role("link", name="Travel")`
with Playwright's own default matching. A task Playwright passes and Dejo fails is the gap
this benchmark exists to find. Playwright has no refs and no memory, so the reference does
the actions and reads, and nothing else.

The result is written to `benchmarks/reliability-<date>.json`, and the last line printed is
"Dejo passed N of M". The exit code is 0 whenever the run finished, whatever the score, so a
scheduler can tell "the benchmark broke" (non-zero) from "Dejo did badly" (read the JSON).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from reliability_tasks import TASKS, Task  # noqa: E402 - the path above makes it importable

# One task is a handful of page loads. Ninety seconds is several times the slowest seen
# while writing them, so a task that takes longer is stuck, not slow.
TASK_TIMEOUT_S = 90

# Tasks run side by side, each in its own browser. Four keeps a laptop responsive and stays
# far below anything a site could take for a crawl: no site has more than three tasks.
WORKERS = 4

# How much of Dejo's reply at the failing step is kept. Enough for the reason and the top
# of the page it showed, which is what a person reading the JSON needs to see why.
REPLY_CHARS = 1500

# How much of the page a failing step stopped on is searched for signs of a block or a
# server error: its title and the first lines, where an error page says what it is.
PAGE_TOP_CHARS = 300

# How much of the page's text is searched for the accepted answer, to tell "read the wrong
# element" from "the site's answer changed".
PAGE_TEXT_CHARS = 200_000

# A Playwright call that names no timeout of its own waits this long in the reference run,
# the same patience Dejo's browser has by default.
REFERENCE_TIMEOUT_MS = 15_000

# Marks an accepted answer that is a regular expression rather than words.
PATTERN = "re:"

# Why a task failed. A fixed list, so a week-on-week comparison counts like with like.
NOT_FOUND = "element not found"
WRONG_ELEMENT = "wrong element"
NOT_READY = "page not ready"
BLOCKED = "site blocked or captcha"
ANSWER_CHANGED = "answer changed on the site"
OTHER = "other"
CAUSES = (NOT_FOUND, WRONG_ELEMENT, NOT_READY, BLOCKED, ANSWER_CHANGED, OTHER)

# The words a stop reason, or the top of the page it stopped on, use for each cause, checked
# in this order. Blocked comes first: a captcha page also has "nothing on this page is" the
# link that was asked for. A server error or a refused certificate is the site, or the road
# to it, not Dejo, so it counts as blocked too. A page that is gone (404) means the site
# changed under the task.
_SIGNS = (
    (
        BLOCKED,
        re.compile(
            r"human check|captcha|\b403\b|\b429\b|access denied|forbidden|ERR_CERT|"
            r"ERR_CONNECTION|ERR_NAME_NOT_RESOLVED|ERR_TUNNEL|ERR_PROXY|ERR_TIMED_OUT|"
            r"too many requests|security verification|just a moment|\b50[234]\b|"
            r"gateway time-?out|bad gateway|service unavailable|connection is not private",
            re.IGNORECASE,
        ),
    ),
    (ANSWER_CHANGED, re.compile(r"\bHTTP 404\b|\bHTTP 410\b|page not found", re.IGNORECASE)),
    (
        WRONG_ELEMENT,
        re.compile(r"\b\d+ matches for\b|resolved to \d+ elements|strict mode", re.I),
    ),
    (
        NOT_FOUND,
        re.compile(
            r"nothing on this page|no element|not on this page|there is no|there are only|"
            r"matches nothing|no .* has \"|never appeared|not something this page|"
            r"is not a target",
            re.IGNORECASE,
        ),
    ),
    (
        NOT_READY,
        re.compile(r"timeout|timed out|not visible|not enabled|not stable|detached", re.I),
    ),
)


@dataclass
class Result:
    """One task, run once by one engine."""

    id: str
    site: str
    covers: str
    engine: str
    passed: bool
    seconds: float
    answer: str = ""
    expected: list[str] = field(default_factory=list)
    failed_line: int | None = None
    failed_step: str = ""
    reply: str = ""
    cause: str = ""


# --------------------------------------------------------------------------- scoring


def normalised(text: str) -> str:
    """Text as compared: case, dashes, quotes and runs of spaces do not count."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[‐-―−]", "-", text)
    text = re.sub(r"[‘’]", "'", text)
    text = re.sub(r"[“”]", '"', text)
    return " ".join(text.split())


def answer_matches(answer: str, accepted: tuple[str, ...] | list[str]) -> bool:
    """True when the read holds one of the accepted answers. A read of a whole table cell
    or a sentence that contains the answer counts: the task asked for that element. An
    accepted answer written `re:...` is a pattern, for answers that move with the date."""
    said = normalised(answer)
    return bool(said) and any(_holds(said, good) for good in accepted)


def _holds(said: str, good: str) -> bool:
    if good.startswith(PATTERN):
        return re.search(good[len(PATTERN) :], said, re.IGNORECASE) is not None
    return normalised(good) in said


def cause_of(reason: str, page_top: str = "") -> str:
    """The cause class for a step that stopped, from the words of its reason and the top of
    the page it stopped on. Only the top: a long page says "403" somewhere for any reason."""
    for cause, sign in _SIGNS:
        if sign.search(reason) or (cause == BLOCKED and sign.search(page_top)):
            return cause
    return OTHER


def cause_of_wrong_answer(page_text: str, accepted: tuple[str, ...] | list[str]) -> str:
    """Every step ran, but the read said something else. If the page still shows an
    accepted answer, the read took the wrong element; if not, the site's answer moved."""
    return WRONG_ELEMENT if answer_matches(page_text, accepted) else ANSWER_CHANGED


# --------------------------------------------------------------------------- one task, Dejo


def run_with_dejo(task: Task) -> Result:
    """The task's program, through the same runner `dejo_run` uses, in a clean browser."""
    from dejo import program
    from dejo.browser import Browser
    from dejo.operations import Session
    from dejo.runner import Runner
    from dejo.store import DejoStore

    started = time.monotonic()
    result = _blank(task, "dejo")
    with tempfile.TemporaryDirectory(prefix="dejo-reliability-") as scratch:
        where = Path(scratch)
        store = DejoStore(db_path=str(where / "memory.db"))
        browser = Browser(headless=True, downloads=where / "downloads").start()
        try:
            runner = Runner(Session(browser=browser, store=store), task=task.id, store=store)
            outcome = runner.run(program.parse(task.steps))
            if outcome.stopped_at is not None:
                result.failed_line = outcome.stopped_at.line
                result.failed_step = outcome.stopped_at.text
                result.reply = outcome.text()[:REPLY_CHARS]
                result.cause = cause_of(outcome.reason, _page_top(browser))
            else:
                result.answer = _last_answer(outcome.answers)
                _score(result, task, lambda: browser.text()[:PAGE_TEXT_CHARS])
                if not result.passed:
                    result.reply = outcome.text()[:REPLY_CHARS]
        finally:
            browser.stop()
    result.seconds = round(time.monotonic() - started, 1)
    return result


def _page_top(browser: Any) -> str:
    try:
        return f"{browser.page.title()}\n{browser.text()[:PAGE_TOP_CHARS]}"
    except Exception:  # noqa: BLE001 - a page that cannot be read has no top to judge by
        return ""


def _last_answer(answers: dict[str, Any]) -> str:
    return str(list(answers.values())[-1]) if answers else ""


def _score(result: Result, task: Task, page_text: Any) -> None:
    result.passed = answer_matches(result.answer, task.answers)
    if result.passed:
        return
    try:
        result.cause = cause_of_wrong_answer(page_text(), task.answers)
    except Exception:  # noqa: BLE001 - a page that cannot be read leaves the cause unknown
        result.cause = OTHER


def _blank(task: Task, engine: str) -> Result:
    return Result(
        id=task.id,
        site=task.site,
        covers=task.covers,
        engine=engine,
        passed=False,
        seconds=0.0,
        expected=list(task.answers),
    )


# --------------------------------------------------------------------------- one task, Playwright


def run_with_playwright(task: Task) -> Result:
    """The same program through plain Playwright calls, written the way its docs teach.

    The browser is started by Dejo's own `Browser`, so both engines meet a site with the
    same browser, window size and user agent, and only the way elements are found and used
    differs. Everything after the start is plain Playwright on that page."""
    from dejo import program
    from dejo.browser import Browser

    started = time.monotonic()
    result = _blank(task, "playwright")
    written = program.parse(task.steps)
    with tempfile.TemporaryDirectory(prefix="dejo-reliability-") as scratch:
        browser = Browser(headless=True, downloads=Path(scratch)).start()
        context = browser.page.context
        context.set_default_timeout(REFERENCE_TIMEOUT_MS)
        # Dejo's browser answers dialogs on its own; the reference answers its own, as a
        # Playwright script does.
        browser.page.remove_listener("dialog", browser._answer_dialog)  # noqa: SLF001
        state = _Reference(browser.page, context, devices=browser._devices())  # noqa: SLF001
        try:
            for step in written.steps:
                try:
                    state.run(step)
                except Exception as failed:  # noqa: BLE001 - any failure stops the program
                    result.failed_line = step.line
                    result.failed_step = step.text
                    reason = str(failed).splitlines()[0] if str(failed) else repr(failed)
                    result.reply = reason[:REPLY_CHARS]
                    result.cause = cause_of(str(failed), _reference_top(state.page))
                    break
            else:
                result.answer = state.answer
                _score(result, task, lambda: state.page.inner_text("body")[:PAGE_TEXT_CHARS])
        finally:
            browser.stop()
    result.seconds = round(time.monotonic() - started, 1)
    return result


def _reference_top(page: Any) -> str:
    try:
        return f"{page.title()}\n{page.inner_text('body')[:PAGE_TOP_CHARS]}"
    except Exception:  # noqa: BLE001 - a page that cannot be read has no top to judge by
        return ""


class _Reference:
    """Plain Playwright for each kind of step line. Only what the tasks use."""

    def __init__(self, page: Any, context: Any, devices: Any = None) -> None:
        self.page = page
        self.context = context
        self.devices = devices or {}
        self.answer = ""
        self.dialog_said = ""
        self.dialog_answer: tuple[str, str | None] = ("accept", None)
        self.responses: list[Any] = []
        self._watch(page)

    def _watch(self, page: Any) -> None:
        """What a Playwright script listens for: every dialog, answered as told, and every
        response, so one that came back before the script asked can still be found."""
        page.on("dialog", self._answer)
        page.on("response", lambda response: self.responses.append(response))

    def _answer(self, dialog: Any) -> None:
        self.dialog_said = dialog.message
        choice, typed = self.dialog_answer
        self.dialog_answer = ("accept", None)
        if choice == "dismiss":
            dialog.dismiss()
        elif typed is not None:
            dialog.accept(typed)
        else:
            dialog.accept()

    def run(self, step: Any) -> None:
        kind = type(step).__name__
        if kind == "Action":
            self._act(step)
        elif kind == "Read":
            self._read(step)
        elif kind == "Expect":
            self._expect(step)

    def _act(self, step: Any) -> None:
        name, value = step.action, step.value
        if name == "goto":
            self.page.goto(urljoin(self.page.url, value))
            return
        if name == "wait":
            self.page.wait_for_timeout(float(value) * 1000)
            return
        if name == "back":
            self.page.go_back()
            return
        if name == "switch_tab":
            if value == "latest" and len(self.context.pages) == 1:
                # A click that opens a tab returns before the tab exists.
                self.context.wait_for_event("page")
            pages = self.context.pages
            self.page = pages[-1] if value == "latest" else pages[int(value)]
            self.page.wait_for_load_state()
            self.page.bring_to_front()
            return
        if name == "scroll":
            self.page.mouse.wheel(0, 3000 if value in ("down", "bottom") else -3000)
            return
        if name == "press" and step.target is None:
            self.page.keyboard.press(value)
            return
        if name == "dialog":
            typed = value[len("answer:") :] if value.startswith("answer:") else None
            self.dialog_answer = ("dismiss" if value == "dismiss" else "accept", typed)
            return
        if name == "close_tab":
            self.page.close()
            self.page = self.context.pages[-1]
            return
        if name == "wait_for" and value and value.startswith("response:"):
            wanted = value[len("response:") :]
            if not any(wanted in response.url for response in self.responses):
                self.page.wait_for_event("response", lambda r: wanted in r.url)
            return
        if name == "emulate":
            self._emulate(value)
            return
        target = self._locate(step.target)
        if name == "click":
            target.click(button=dict(step.options).get("button", "left"))
        elif name == "fill":
            target.fill(value)
        elif name == "type":
            target.press_sequentially(value)
        elif name == "select":
            target.select_option(label=value)
        elif name == "hover":
            target.hover()
        elif name == "check":
            target.check()
        elif name == "press":
            target.press(value)
        elif name == "scroll_to":
            target.scroll_into_view_if_needed()
        elif name == "wait_for":
            target.wait_for()
        else:
            raise RuntimeError(f"the reference run has no {name}")

    def _emulate(self, value: str) -> None:
        """A Playwright script sets these when it makes its context, so the reference makes
        a new one with them and carries on there, at the same address."""
        kind, _, setting = value.partition(" ")
        browser = self.context.browser
        options = {"locale": setting} if kind == "locale" else dict(self.devices[setting])
        options.pop("default_browser_type", None)
        here = self.page.url
        self.context = browser.new_context(**options)
        self.page = self.context.new_page()
        self._watch(self.page)
        self.page.goto(here)

    def _read(self, step: Any) -> None:
        if step.kind == "dialog":
            self.answer = self.dialog_said
            return
        if step.kind == "response":
            found = [r for r in self.responses if step.attribute in r.url]
            self.answer = found[-1].text() if found else ""
            return
        if step.kind == "cookies":
            self.answer = str(
                [
                    f"{c['name']}={c['value']} ({c['domain']})"
                    for c in self.context.cookies()
                    if step.attribute in c["name"]
                ]
            )
            return
        if step.kind == "pdf":
            self.answer = str(Path(tempfile.mkdtemp()) / "page.pdf")
            self.page.pdf(path=self.answer)
            return
        if step.kind in ("table", "fields"):
            self.answer = json.dumps(self._json(step), ensure_ascii=False)
            return
        if step.kind == "title":
            self.answer = self.page.title()
        elif step.kind == "url":
            self.answer = self.page.url
        elif step.kind == "value":
            self.answer = self._locate(step.target).input_value()
        elif step.kind == "attribute":
            self.answer = self._locate(step.target).get_attribute(step.attribute) or ""
        elif step.kind == "count":
            self.answer = str(self._locate(step.target, many=True).count())
        else:
            self.answer = self._locate(step.target).inner_text()

    def _json(self, step: Any) -> Any:
        """What a Playwright script does for a table or a list of cards: read each one."""
        found = self._locate(step.target, many=True)
        if step.kind == "table":
            rows = found.first.locator("tr").all()
            names = [cell.inner_text().strip() for cell in rows[0].locator("th").all()]
            return [dict(zip(names, _cells(row), strict=False)) for row in rows[1:]]
        fields = json.loads(step.attribute)
        cards = []
        for card in found.all():
            one = {}
            for name, written in fields.items():
                where, _, attr = written.partition("@")
                part = card.locator(where).first
                one[name] = part.get_attribute(attr) if attr else part.inner_text().strip()
            cards.append(one)
        return cards

    def _expect(self, step: Any) -> None:
        if step.kind == "url_contains":
            self.page.wait_for_url(re.compile(re.escape(step.value)))
        elif step.kind == "text_present":
            self.page.get_by_text(step.value).first.wait_for()
        else:
            self._locate(step.target).wait_for()

    def _locate(self, target: Any, *, many: bool = False) -> Any:
        """The target on the page, or inside the first frame that has it.

        Playwright locators stop at an iframe. Playwright MCP's snapshot does not: it gives
        refs inside frames, so an agent using it reaches them. The reference does the same
        by trying each frame when the page itself has no match."""
        for scope in [self.page, *[frame for frame in self.page.frames[1:]]]:
            found = _picked(_base(scope, target), target)
            if many or found.count() > 0:
                return found
        return _picked(_base(self.page, target), target)


def _cells(row: Any) -> list[str]:
    return [cell.inner_text().strip() for cell in row.locator("td").all()]


def _base(scope: Any, target: Any) -> Any:
    kind, value = target.kind, target.value
    if kind == "css":
        return scope.locator(value)
    if kind == "text":
        return scope.get_by_text(value)
    if kind == "label":
        return scope.get_by_label(value)
    if kind == "placeholder":
        return scope.get_by_placeholder(value)
    if kind == "alt":
        return scope.get_by_alt_text(value)
    if kind == "title":
        return scope.get_by_title(value)
    if kind == "testid":
        return scope.get_by_test_id(value)
    return scope.get_by_role(kind, name=value) if value else scope.get_by_role(kind)


def _picked(found: Any, target: Any) -> Any:
    pick = target.pick
    if pick is None:
        return found
    if pick.kind == "first":
        return found.first
    if pick.kind == "last":
        return found.last
    if pick.kind == "nth":
        return found.nth(pick.number - 1)
    return found.filter(has_text=pick.text)


# --------------------------------------------------------------------------- the whole run


ENGINES = {"dejo": run_with_dejo, "playwright": run_with_playwright}


def run_one_in_a_process(task_id: str, engine: str) -> Result:
    """Run one task in a child process, so a hang or a crash costs only that task."""
    task = next(task for task in TASKS if task.id == task_id)
    command = [sys.executable, str(Path(__file__).resolve()), "--child", task_id, engine]
    started = time.monotonic()
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=TASK_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired:
        result = _blank(task, engine)
        result.seconds = round(time.monotonic() - started, 1)
        result.cause = NOT_READY
        result.reply = f"the task was still running after {TASK_TIMEOUT_S} s and was stopped"
        return result
    for line in reversed(done.stdout.splitlines()):
        if line.startswith("{"):
            return Result(**json.loads(line))
    result = _blank(task, engine)
    result.seconds = round(time.monotonic() - started, 1)
    result.cause = OTHER
    result.reply = (done.stderr or done.stdout or "the task printed nothing")[-REPLY_CHARS:]
    return result


def run_all(tasks: list[Task], engines: list[str], workers: int) -> list[Result]:
    jobs = [(task.id, engine) for engine in engines for task in tasks]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        finished = list(pool.map(lambda job: run_one_in_a_process(*job), jobs))
    for result in finished:
        mark = "pass" if result.passed else f"FAIL ({result.cause})"
        print(f"{result.engine:10} {result.id} {result.site:40} {mark}", file=sys.stderr)
    return finished


def summary(results: list[Result], engine: str) -> dict[str, Any]:
    mine = [result for result in results if result.engine == engine]
    passed = sum(result.passed for result in mine)
    causes = Counter(result.cause for result in mine if not result.passed)
    return {
        "passed": passed,
        "total": len(mine),
        "failures_by_cause": {cause: causes[cause] for cause in CAUSES if causes[cause]},
    }


def write(results: list[Result], engines: list[str], out: Path) -> dict[str, Any]:
    from dejo import __version__

    report = {
        "date": date.today().isoformat(),
        "dejo_version": __version__,
        "task_timeout_s": TASK_TIMEOUT_S,
        "score": {engine: summary(results, engine) for engine in engines},
        "tasks": [asdict(result) for result in results],
    }
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="comma-separated task ids, e.g. R01,R30")
    parser.add_argument("--reference", action="store_true", help="also run plain Playwright")
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--out", help="where to write the JSON")
    parser.add_argument("--child", nargs=2, metavar=("TASK", "ENGINE"), help=argparse.SUPPRESS)
    options = parser.parse_args(argv)

    if options.child:
        task_id, engine = options.child
        task = next(task for task in TASKS if task.id == task_id)
        print(json.dumps(asdict(ENGINES[engine](task)), ensure_ascii=False))
        return 0

    wanted = set(options.only.split(",")) if options.only else None
    tasks = [task for task in TASKS if wanted is None or task.id in wanted]
    engines = ["dejo", "playwright"] if options.reference else ["dejo"]
    results = run_all(tasks, engines, options.workers)
    out = Path(options.out) if options.out else HERE / f"reliability-{date.today()}.json"
    report = write(results, engines, out)
    if options.reference:
        reference = report["score"]["playwright"]
        print(f"Playwright passed {reference['passed']} of {reference['total']}")
    score = report["score"]["dejo"]
    print(f"Dejo passed {score['passed']} of {score['total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
