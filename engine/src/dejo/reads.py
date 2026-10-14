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

from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Locator as PWLocator
from playwright.sync_api import Page

# Reads should answer or give up quickly. The default 30 seconds is right for an action
# that is waiting for a page to settle, but a question about the current page either has an
# answer now or does not.
READ_TIMEOUT_MS = 5000


@dataclass(frozen=True)
class ReadSpec:
    """One question Dejo can answer about a page."""

    name: str
    summary: str
    returns: str
    needs_target: bool = True
    needs_attribute: bool = False
    many: bool = False
    """Does this read WANT more than one match?

    Most reads are about one element, and a selector matching several is an ambiguity that
    has to be refused — silently reading the first is how a caller ends up acting on the
    wrong thing. Counting and reading every line are the exceptions: matching many is the
    entire point of them."""

    def describe(self) -> str:
        parts = [f"{self.name} — {self.summary}", f"gives back {self.returns}"]
        if self.needs_attribute:
            parts.append("needs `attribute`, e.g. href")
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
    "failed_requests": ReadSpec(
        "failed_requests",
        "the requests the page made that came back broken. A dashboard that stays empty "
        "is usually one failed request, not a missing element",
        "a list of urls with their status",
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
    return t.inner_text(timeout=READ_TIMEOUT_MS).strip()


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


_READERS: dict[str, Any] = {
    "text": _text,
    "all_text": _all_text,
    "value": _value,
    "checked": _checked,
    "visible": _visible,
    "enabled": _enabled,
    "editable": _editable,
    "attribute": _attribute,
    "count": _count,
    "url": _url,
    "title": _title,
    "page_text": _page_text,
    "console_errors": _console_errors,
    "failed_requests": _failed_requests,
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
