"""Every way Dejo can read something off a page.

Without this Dejo can click but never look, so "check my dashboard numbers" is impossible
— which is half the reason anyone would want the tool. Reading is also what postconditions
are made of: `read(value)` is how we prove a `fill` actually landed.

Same shape as `actions.py`, and for the same reasons: one registry, so the tool description
an AI reads is generated from the code rather than written beside it and left to rot.
Nothing here resolves an element; a locator is handed in already.

What is deliberately absent — `inner_html`, `bounding_box`, `evaluate` — and why, is in
`docs/BROWSING.md`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator as PWLocator
from playwright.sync_api import Page

from .home import HOME

# Reads should answer or give up quickly. The default 30 seconds is right for an action
# that is waiting for a page to settle, but a question about the current page either has an
# answer now or does not.
READ_TIMEOUT_MS = 5000


# The word after `screenshot` that asks for the whole length of the page, not just the
# part on screen.
FULL_PAGE = "full"

# Where pictures and PDFs go when a page was never told: the browser tells each page its own
# folder (see `Browser._watch`), and this is only for a page Dejo did not open.
CAPTURES = HOME / "captures"

# The most of a response body handed back. An API answer can be megabytes; past this it
# is no longer one answer, and it would crowd the reply.
LONGEST_BODY = 20_000

# A markdown heading: `## Pricing`.
_HEADING = re.compile(r"^(#{1,6})\s")

# What a field shows a person: a box's value, a dropdown's chosen words. Null for anything
# else, which is read for its text. A password box is never read this way: what is typed in
# one is not an answer to hand back.
_FIELD_TEXT_JS = """
el => {
  if (el.tagName === "SELECT") return [...el.selectedOptions].map((o) => o.label).join(", ");
  if (el.tagName === "TEXTAREA") return el.value;
  if (el.tagName === "INPUT" && !["password", "checkbox", "radio", "hidden"].includes(el.type)) {
    return el.value;
  }
  return null;
}
"""


@dataclass(frozen=True)
class ReadSpec:
    """One question Dejo can answer about a page."""

    name: str
    summary: str
    returns: str
    needs_target: bool = True
    needs_attribute: bool = False
    attribute_means: str = "the attribute name, like: read attr href e4"
    """What the extra word a read needs is, for a message about it missing."""
    optional_target: bool = False
    """Takes an element when one is named, and the whole page when not."""
    optional_attribute: bool = False
    """Takes the extra word when one is given, and reads everything when not."""
    many: bool = False
    """Does this read WANT more than one match?

    Most reads are about one element, and a selector matching several is an ambiguity that
    has to be refused — silently reading the first is how a caller ends up acting on the
    wrong thing. Counting and reading every line are the exceptions: matching many is the
    entire point of them."""

    def describe(self) -> str:
        parts = [f"{self.name} — {self.summary}", f"gives back {self.returns}"]
        if self.needs_attribute:
            parts.append(f"needs {self.attribute_means}")
        if not self.needs_target:
            parts.append("no ref needed")
        return "; ".join(parts)


READS: dict[str, ReadSpec] = {
    "text": ReadSpec(
        "text",
        "the words inside one element — a number, a status, an error message. THE ONE YOU "
        "USUALLY WANT. `ref` takes a CSS selector as well as a ref, so this works even for "
        "something with no ref of its own",
        "text",
    ),
    "all_text": ReadSpec(
        "all_text",
        "the words inside every matching element, for reading a table or a list in one go "
        "instead of one call per row",
        "a list of text",
        many=True,
    ),
    "value": ReadSpec(
        "value",
        "what is currently typed in a field",
        "text",
    ),
    "checked": ReadSpec(
        "checked",
        "whether a checkbox or radio button is ticked",
        "true or false",
    ),
    "visible": ReadSpec(
        "visible",
        "whether something is on the page and can be seen. Use it to check a dialog closed",
        "true or false",
    ),
    "enabled": ReadSpec(
        "enabled",
        "whether a control can be used, rather than being greyed out",
        "true or false",
    ),
    "editable": ReadSpec(
        "editable",
        "whether a field can be typed into. A field can be enabled but still read-only",
        "true or false",
    ),
    "attribute": ReadSpec(
        "attribute",
        "one attribute of an element, such as href or aria-expanded",
        "text, or nothing if the attribute is absent",
        needs_attribute=True,
    ),
    "passage": ReadSpec(
        "passage",
        "the part of one long text that holds some words: the section under a heading that "
        "says them, or the paragraph that does. For a page that is one long text, such as a "
        "markdown file, which is far too long to read whole",
        "text",
        needs_attribute=True,
        attribute_means='the words, like: read passage "Pricing" e1 as pricing',
    ),
    "fields": ReadSpec(
        "fields",
        "several fields of every matching element at once, as JSON: one object per element. "
        "The fields are a JSON object of NAME: CSS inside the element, @attr for an "
        "attribute and . for the element itself. Without an element, one object for the page",
        "JSON",
        needs_target=False,
        optional_target=True,
        needs_attribute=True,
        attribute_means=(
            'the fields, like: read fields \'{"name": "h3", "price": ".price", "link": '
            '"a@href"}\' css "article" as products'
        ),
        many=True,
    ),
    "table": ReadSpec(
        "table",
        "a whole table as JSON: one object per row, named by the table's headings",
        "JSON",
        many=True,
    ),
    "metrics": ReadSpec(
        "metrics",
        "how fast this page loaded, as the browser measured it: first byte, first and "
        "largest paint, page ready, layout shift, requests and bytes. For a speed check; "
        "record performance gives the whole trace",
        "text",
        needs_target=False,
    ),
    "downloads": ReadSpec(
        "downloads",
        "the files this tab has downloaded, where they were saved",
        "a list of paths",
        needs_target=False,
    ),
    "workers": ReadSpec(
        "workers",
        "the scripts the page runs in the background (web workers), by address",
        "a list of addresses",
        needs_target=False,
    ),
    "box": ReadSpec(
        "box",
        "where an element is on the screen and how big: X Y WIDTH HEIGHT in pixels from the top "
        "left, the numbers mouse click X Y uses",
        "text",
    ),
    "html": ReadSpec(
        "html",
        "the HTML of one element, for markup no other read shows. Long markup is cut",
        "text",
    ),
    "count": ReadSpec(
        "count",
        'how many elements match — "there are 3 unpaid invoices"',
        "a number",
        many=True,
    ),
    # ---- page level: these ask about the whole page, so they take no element -------
    "url": ReadSpec(
        "url",
        "the address of the current page",
        "text",
        needs_target=False,
    ),
    "title": ReadSpec(
        "title",
        "the title of the current page",
        "text",
        needs_target=False,
    ),
    "console_errors": ReadSpec(
        "console_errors",
        "the errors the page itself reported. When a run fails for no visible reason, this "
        "is usually why — read it before guessing",
        "a list of messages",
        needs_target=False,
    ),
    "console": ReadSpec(
        "console",
        "every message the page wrote to its console, newest last, not only the errors",
        "a list of messages",
        needs_target=False,
    ),
    "requests": ReadSpec(
        "requests",
        "every request the page made, as METHOD STATUS ADDRESS. With words, only those whose "
        'address has them: read requests "/api/" as calls',
        "a list of requests",
        needs_target=False,
        optional_attribute=True,
    ),
    "response": ReadSpec(
        "response",
        "the body of the latest answer to an address with these words in it, such as the "
        "JSON a page draws its table from",
        "text",
        needs_target=False,
        needs_attribute=True,
        attribute_means='words in the address, like: read response "/api/orders" as orders',
    ),
    "failed_requests": ReadSpec(
        "failed_requests",
        "the requests the page made that came back broken. A dashboard that stays empty "
        "is usually one failed request, not a missing element",
        "a list of urls with their status",
        needs_target=False,
    ),
    "cookies": ReadSpec(
        "cookies",
        "this page's cookies, as NAME=VALUE (site). With words, only cookies whose name or "
        "site has them. A cookie the page itself cannot read (httpOnly) shows no value",
        "a list of cookies",
        needs_target=False,
        optional_attribute=True,
    ),
    "storage": ReadSpec(
        "storage",
        "this page's local storage, as KEY=VALUE; with a key, only its value",
        "a list, or text for one key",
        needs_target=False,
        optional_attribute=True,
    ),
    "tabs": ReadSpec(
        "tabs",
        "every open tab: its number for `tab N`, its title and address, and which is in use",
        "a list of tabs",
        needs_target=False,
    ),
    "dialog": ReadSpec(
        "dialog",
        "the words of the last alert, confirm or prompt box this page showed",
        "text",
        needs_target=False,
    ),
    "screenshot": ReadSpec(
        "screenshot",
        "a picture of what is on screen, of one element, or with full of the whole page. "
        "Saved as a file, and taken again on every replay",
        "the path of the picture",
        needs_target=False,
        optional_target=True,
    ),
    "pdf": ReadSpec(
        "pdf",
        "the page saved as a PDF, as it would print. Taken again on every replay",
        "the path of the PDF",
        needs_target=False,
    ),
    "page_text": ReadSpec(
        "page_text",
        "the readable text of the WHOLE page. ALMOST NEVER THE RIGHT ANSWER. If you "
        "remember this one, the trail's answer becomes thousands of characters of "
        "navigation and tables with the real number buried inside, handed back on every "
        "future run for you to search again. If what you want has no `ref` — a dashboard "
        "number is usually a plain div and will not have one — pass a CSS SELECTOR as "
        "`ref` instead, such as \"[data-attr='visitors-tile'] .big\". Use this kind only "
        "to look around while exploring",
        "text",
        needs_target=False,
    ),
}


class UnknownRead(ValueError):
    """Asked for a kind of read that does not exist."""


class ReadNeedsMore(ValueError):
    """The read was understood but something it requires was not given."""


def spec_for(kind: str) -> ReadSpec:
    try:
        return READS[kind]
    except KeyError:
        known = ", ".join(sorted(READS))
        raise UnknownRead(f"cannot read {kind!r}. Known kinds: {known}") from None


def catalogue() -> str:
    """The whole read list as one block of text, for the MCP tool description."""
    return "\n".join(f"  {spec.describe()}" for spec in READS.values())


def read(
    kind: str,
    *,
    page: Page,
    target: PWLocator | None = None,
    attribute: str | None = None,
) -> Any:
    """Answer one question about the page.

    Never raises when the honest answer is "no": a missing element reads as not visible,
    not checked, and a count of zero. Only the reads that have no sensible empty answer —
    the text or value of something that is not there — fail.
    """
    spec = spec_for(kind)

    if spec.needs_target and target is None:
        raise ReadNeedsMore(f"reading {kind} needs an element")
    if spec.needs_attribute and not attribute:
        raise ReadNeedsMore("reading an attribute needs its name, such as href")

    return _READERS[kind](page, target, attribute)


def _text(page: Page, t: PWLocator, attribute: str | None) -> str:
    # A field has no text of its own: its words are what it holds. `read` of a box full of
    # text said "the read found nothing there" (launchingnext.com), so a field is read for
    # its value, and a dropdown for the option it shows.
    held = t.evaluate(_FIELD_TEXT_JS, timeout=READ_TIMEOUT_MS)
    if held is not None:
        return str(held).strip()
    return t.inner_text(timeout=READ_TIMEOUT_MS).strip()


def _passage(page: Page, t: PWLocator, attribute: str | None) -> str:
    return passage_of(t.inner_text(timeout=READ_TIMEOUT_MS), attribute or "")


def passage_of(text: str, words: str) -> str:
    """The section under the first markdown heading that says `words`, to the next heading
    as high as it; else the first paragraph that says them; else "".

    Seen on market.lobehub.com: a 48k guide served as plain text was one element, too long to
    read whole, with nothing smaller on the page to read."""
    wanted = " ".join(words.split()).lower()
    lines = text.splitlines()
    for start, line in enumerate(lines):
        heading = _HEADING.match(line)
        if heading is None or wanted not in line.lower():
            continue
        level = len(heading.group(1))
        end = next(
            (
                at
                for at in range(start + 1, len(lines))
                if (later := _HEADING.match(lines[at])) and len(later.group(1)) <= level
            ),
            len(lines),
        )
        return "\n".join(lines[start:end]).strip()
    for paragraph in re.split(r"\n\s*\n", text):
        if wanted in " ".join(paragraph.split()).lower():
            return paragraph.strip()
    return ""


def _all_text(page: Page, t: PWLocator, attribute: str | None) -> list[str]:
    # `or ""` because a node can genuinely have no text — an `svg` inside a button is the
    # normal case — and Playwright hands back None for those. Without the guard this
    # crashed with "'NoneType' object has no attribute 'strip'" on a perfectly ordinary
    # icon button, which tells the caller nothing about what to do next.
    return [(line or "").strip() for line in t.all_inner_texts()]


def _value(page: Page, t: PWLocator, attribute: str | None) -> str:
    return t.input_value(timeout=READ_TIMEOUT_MS)


def _checked(page: Page, t: PWLocator, attribute: str | None) -> bool:
    # An element that is not there is not ticked. That is the useful answer, not an error.
    if t.count() == 0:
        return False
    return t.is_checked(timeout=READ_TIMEOUT_MS)


def _visible(page: Page, t: PWLocator, attribute: str | None) -> bool:
    return t.is_visible()


def _enabled(page: Page, t: PWLocator, attribute: str | None) -> bool:
    if t.count() == 0:
        return False
    return t.is_enabled(timeout=READ_TIMEOUT_MS)


def _editable(page: Page, t: PWLocator, attribute: str | None) -> bool:
    if t.count() == 0:
        return False
    return t.is_editable(timeout=READ_TIMEOUT_MS)


def _attribute(page: Page, t: PWLocator, attribute: str | None) -> str | None:
    return t.get_attribute(attribute or "", timeout=READ_TIMEOUT_MS)


def _count(page: Page, t: PWLocator, attribute: str | None) -> int:
    return t.count()


def _url(page: Page, t: PWLocator | None, attribute: str | None) -> str:
    return page.url


def _title(page: Page, t: PWLocator | None, attribute: str | None) -> str:
    return page.title()


def _page_text(page: Page, t: PWLocator | None, attribute: str | None) -> str:
    return page.inner_text("body")


def _console_errors(page: Page, t: PWLocator | None, attribute: str | None) -> list[str]:
    return list(getattr(page, "_dejo_console", []))


def _failed_requests(page: Page, t: PWLocator | None, attribute: str | None) -> list[str]:
    return list(getattr(page, "_dejo_failures", []))


def _cookies(page: Page, t: PWLocator | None, attribute: str | None) -> list[str]:
    said = []
    # Only the cookies this page's address would send: a task on one site never sees, or
    # keeps in its trail, the cookies another site left in the same profile.
    for cookie in page.context.cookies(page.url):
        if attribute and attribute not in cookie["name"] and attribute not in cookie["domain"]:
            continue
        # A cookie the site marked httpOnly is one its own page cannot read: a sign-in. Its
        # value stays in the browser, here as there.
        value = "(hidden: httpOnly)" if cookie.get("httpOnly") else cookie["value"]
        said.append(f"{cookie['name']}={value} ({cookie['domain']})")
    return said


def _storage(page: Page, t: PWLocator | None, attribute: str | None) -> list[str] | str:
    if attribute:
        return page.evaluate("(k) => localStorage.getItem(k) || ''", attribute)
    return page.evaluate(
        "() => Object.keys(localStorage).sort().map((k) => k + '=' + localStorage.getItem(k))"
    )


def _tabs(page: Page, t: PWLocator | None, attribute: str | None) -> list[str]:
    live = [tab for tab in page.context.pages if not tab.is_closed()]
    return [
        f"{at} {tab.title() or '(no title)'} {tab.url}" + (" (in use)" if tab is page else "")
        for at, tab in enumerate(live)
    ]


# One element's fields: each a CSS selector inside it, `@attr` for an attribute of what it
# finds, `.` for the element itself. A field that finds nothing is null, not an error: a
# card with no sale price is a real answer.
_FIELDS_JS = """
(el, fields) => {
  const one = {};
  for (const [name, written] of Object.entries(fields)) {
    const [where, attr] = written.split("@");
    const found = !where.trim() || where.trim() === "." ? el : el.querySelector(where);
    if (!found) { one[name] = null; continue; }
    const said = attr ? found.getAttribute(attr) : (found.innerText ?? found.textContent ?? "");
    one[name] = said === null ? null : said.replace(/\\s+/g, " ").trim();
  }
  return one;
}
"""

# A table's rows as objects named by its headings: the <th> of its head, or of its first row.
_TABLE_JS = """
(table) => {
  const text = (cell) => (cell.innerText || cell.textContent || "").replace(/\\s+/g, " ").trim();
  const rows = [...table.querySelectorAll("tr")];
  const headRow = table.querySelector("thead tr") || rows.find((r) => r.querySelector("th"));
  const names = headRow ? [...headRow.children].map(text) : [];
  return rows.filter((r) => r !== headRow).map((r) => {
    const cells = [...r.children].map(text);
    const row = {};
    cells.forEach((cell, at) => { row[names[at] || `column ${at + 1}`] = cell; });
    return row;
  }).filter((row) => Object.values(row).some(Boolean));
}
"""


def _fields(page: Page, t: PWLocator | None, attribute: str | None) -> str:
    try:
        fields = json.loads(attribute or "")
    except json.JSONDecodeError:
        fields = None
    if not isinstance(fields, dict) or not all(isinstance(v, str) for v in fields.values()):
        raise ReadNeedsMore(
            'the fields are a JSON object of NAME: CSS, like {"name": "h3", "link": "a@href"}'
        )
    if t is None:
        # The page as a whole is the document itself; nothing is searched for.
        whole = page.evaluate(
            f"(fields) => ({_FIELDS_JS})(document.documentElement, fields)", fields
        )
        return json.dumps(whole, ensure_ascii=False)
    found = [one.evaluate(_FIELDS_JS, fields) for one in t.all()]
    return json.dumps(found, ensure_ascii=False)


def _table(page: Page, t: PWLocator, attribute: str | None) -> str:
    return json.dumps(t.first.evaluate(_TABLE_JS), ensure_ascii=False)


# The browser's own measurements of this page's load. Largest paint and layout shift come
# only from an observer, so it is asked for what it already buffered and given one frame.
_METRICS_JS = """
() => new Promise((done) => {
  const nav = performance.getEntriesByType("navigation")[0] || {};
  const paints = Object.fromEntries(
    performance.getEntriesByType("paint").map((p) => [p.name, p.startTime]));
  const resources = performance.getEntriesByType("resource");
  const seen = {lcp: 0, cls: 0};
  const watch = (type, take) => {
    try {
      new PerformanceObserver((list) => list.getEntries().forEach(take))
        .observe({type, buffered: true});
    } catch (e) {}
  };
  watch("largest-contentful-paint", (e) => { seen.lcp = Math.max(seen.lcp, e.startTime); });
  watch("layout-shift", (e) => { if (!e.hadRecentInput) seen.cls += e.value; });
  requestAnimationFrame(() => setTimeout(() => done({
    first_byte_ms: nav.responseStart || 0,
    first_paint_ms: paints["first-paint"] || 0,
    first_contentful_paint_ms: paints["first-contentful-paint"] || 0,
    largest_contentful_paint_ms: seen.lcp,
    dom_ready_ms: nav.domContentLoadedEventEnd || 0,
    load_ms: nav.loadEventEnd || 0,
    layout_shift: seen.cls,
    requests: resources.length + 1,
    bytes: resources.reduce((all, r) => all + (r.transferSize || 0), nav.transferSize || 0),
  }), 0));
})
"""


def _metrics(page: Page, t: PWLocator | None, attribute: str | None) -> str:
    measured = page.evaluate(_METRICS_JS)
    parts = [
        f"{name.removesuffix('_ms').replace('_', ' ')} {round(value)} ms"
        for name, value in measured.items()
        if name.endswith("_ms") and value
    ]
    parts.append(f"layout shift {measured['layout_shift']:.3f}")
    parts.append(f"{measured['requests']} requests, {measured['bytes'] / 1024:.0f} KB")
    return ", ".join(parts)


def _downloads(page: Page, t: PWLocator | None, attribute: str | None) -> list[str]:
    return list(getattr(page, "_dejo_downloads", []))


def _workers(page: Page, t: PWLocator | None, attribute: str | None) -> list[str]:
    return [worker.url for worker in page.workers]


def _box(page: Page, t: PWLocator, attribute: str | None) -> str:
    found = t.bounding_box(timeout=READ_TIMEOUT_MS)
    if found is None:
        return ""
    return " ".join(str(round(found[side])) for side in ("x", "y", "width", "height"))


def _html(page: Page, t: PWLocator, attribute: str | None) -> str:
    markup = t.evaluate("el => el.outerHTML", timeout=READ_TIMEOUT_MS)
    if len(markup) > LONGEST_BODY:
        return markup[:LONGEST_BODY] + f" ... ({len(markup):,} characters in all)"
    return markup


def _dialog(page: Page, t: PWLocator | None, attribute: str | None) -> str:
    return getattr(page, "_dejo_dialog", "")


def _screenshot(page: Page, t: PWLocator | None, attribute: str | None) -> str:
    where = _capture_path(page, "png")
    if t is not None:
        t.screenshot(path=where, timeout=READ_TIMEOUT_MS)
    else:
        page.screenshot(path=where, full_page=attribute == FULL_PAGE)
    return str(where)


def _pdf(page: Page, t: PWLocator | None, attribute: str | None) -> str:
    where = _capture_path(page, "pdf")
    try:
        page.pdf(path=where)
    except PlaywrightError as refused:
        if "headless" not in str(refused).lower():
            raise
        # Chromium prints to PDF only when it has no window. Said plainly, with the fix.
        raise ReadNeedsMore(
            "a PDF can only be made by a browser with no window, and this one has a window. "
            "Run it without DEJO_HEADED, or take a screenshot instead."
        ) from refused
    return str(where)


def _capture_path(page: Page, suffix: str) -> Path:
    """A new file for a picture or PDF of this page: the site and the moment, never reused,
    so a trail replayed every morning keeps every morning's picture."""
    folder = Path(getattr(page, "_dejo_captures", CAPTURES))
    folder.mkdir(parents=True, exist_ok=True)
    site = (urlparse(page.url).hostname or "page").replace(":", "-")
    moment = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return folder / f"{site}-{moment}.{suffix}"


def _console(page: Page, t: PWLocator | None, attribute: str | None) -> list[str]:
    return list(getattr(page, "_dejo_messages", []))


def _requests(page: Page, t: PWLocator | None, attribute: str | None) -> list[str]:
    said = []
    for entry in getattr(page, "_dejo_requests", []):
        request = entry["request"]
        if attribute and attribute not in request.url:
            continue
        response = entry["response"]
        status = str(response.status) if response is not None else entry["failed"] or "waiting"
        said.append(f"{request.method} {status} {request.url}")
    return said


def _response(page: Page, t: PWLocator | None, attribute: str | None) -> str:
    for entry in reversed(getattr(page, "_dejo_requests", [])):
        response = entry["response"]
        if response is None or (attribute or "") not in entry["request"].url:
            continue
        try:
            body = response.text()
        except PlaywrightError:
            # A body is gone once its page has moved on. Said plainly: the fix is to read it
            # straight after the step that fetched it.
            raise ReadNeedsMore(
                f"the answer from {response.url} can no longer be read: the page has moved on "
                "since. Read it in the line right after the step that fetched it."
            ) from None
        if len(body) > LONGEST_BODY:
            return body[:LONGEST_BODY] + f" ... ({len(body):,} characters in all)"
        return body
    return ""


_READERS: dict[str, Any] = {
    "text": _text,
    "all_text": _all_text,
    "value": _value,
    "checked": _checked,
    "visible": _visible,
    "enabled": _enabled,
    "editable": _editable,
    "attribute": _attribute,
    "passage": _passage,
    "count": _count,
    "url": _url,
    "title": _title,
    "page_text": _page_text,
    "console_errors": _console_errors,
    "failed_requests": _failed_requests,
    "console": _console,
    "requests": _requests,
    "response": _response,
    "dialog": _dialog,
    "tabs": _tabs,
    "box": _box,
    "downloads": _downloads,
    "workers": _workers,
    "html": _html,
    "metrics": _metrics,
    "fields": _fields,
    "table": _table,
    "cookies": _cookies,
    "storage": _storage,
    "screenshot": _screenshot,
    "pdf": _pdf,
}


def sanity_check() -> None:
    """Every read in the registry has a reader, and every reader is in the registry."""
    missing_reader = sorted(set(READS) - set(_READERS))
    missing_spec = sorted(set(_READERS) - set(READS))
    if missing_reader or missing_spec:
        raise AssertionError(
            f"read registry out of step — no reader for {missing_reader}, "
            f"no spec for {missing_spec}"
        )
