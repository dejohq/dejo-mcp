"""Waiting for a page to be ready.

This is what modern sites need most. A React dashboard is blank until its data arrives, so
a `look()` that happens too early sees an empty page and the trail records nothing useful.
Guessing a number of seconds is the alternative, and a guess is either too short and flaky
or too long and slow on every single run forever.

Every wait here has a subject: a URL, an element, some text, the network going quiet. None
of them is a sleep. The one real sleep Dejo has is the `wait` action, whose own
description tells the caller to prefer these.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PWTimeout

# How long any wait is allowed to take before it gives up. One number, in one place: a wait
# that never returns is indistinguishable from a hung agent.
DEFAULT_WAIT_MS = 15000

# How long to wait for one element to appear when replaying a stored locator. Shorter,
# because replay tries several locators in turn and a miss is expected information.
LOCATOR_WAIT_MS = 1500

# How long to let a page go quiet before deciding a control is genuinely gone. Only ever
# spent when EVERY locator missed, which on a slow site usually means the page had not
# finished drawing rather than that the site changed. Bounded, because a page that polls
# in the background never goes quiet at all.
QUIET_WAIT_MS = 5000

MS_PER_SECOND = 1000

# The tags that hold a page of their own. Waiting for one of these is waiting for a page.
FRAME_TAGS = ("IFRAME", "FRAME")

# Anything on screen inside a frame's page. `:visible` is Playwright's own filter.
VISIBLE_CONTENT = "body *:visible"

# Waiting inside a frame names two things. "|" splits them because it never appears in an
# ordinary CSS selector, and Dejo's own refs already use it the same way.
IN_FRAME = "in_frame"
FRAME_SPLIT = "|"


@dataclass(frozen=True)
class WaitSpec:
    """One thing that can be waited for."""

    name: str
    summary: str
    needs_value: bool = True

    def describe(self) -> str:
        line = f"{self.name} — {self.summary}"
        return line if self.needs_value else f"{line} (no value needed)"


WAITS: dict[str, WaitSpec] = {
    "element": WaitSpec(
        "element",
        "wait until something is on screen and has stopped moving. The right way to wait "
        "for content that loads late. Waiting for an iframe also waits for its page to load",
    ),
    "in_frame": WaitSpec(
        "in_frame",
        "wait until something INSIDE an iframe is on screen, written as "
        "in_frame:<the iframe>|<what is inside it>, e.g. in_frame:iframe.picker|#upload-tab. "
        "Use this when a frame fills itself in after it appears, as file pickers do",
    ),
    "gone": WaitSpec(
        "gone",
        "wait until something disappears — a spinner, a saving message, an overlay",
    ),
    "text": WaitSpec(
        "text",
        "wait until some words appear anywhere on the page",
    ),
    "url": WaitSpec(
        "url",
        "wait until the address contains this. Single-page apps change the address without "
        "loading a new page, so this is often the only signal that a move happened",
    ),
    "idle": WaitSpec(
        "idle",
        "wait until the network goes quiet. Use for a dashboard that is blank until its "
        "data arrives",
        needs_value=False,
    ),
}


class UnknownWait(ValueError):
    """Asked to wait for something that is not a kind of wait."""


class WaitNeedsMore(ValueError):
    """The wait was understood but something it requires was not given."""


class WaitedTooLong(TimeoutError):
    """The thing never happened. This is information — usually that the site changed."""


def spec_for(kind: str) -> WaitSpec:
    try:
        return WAITS[kind]
    except KeyError:
        known = ", ".join(sorted(WAITS))
        raise UnknownWait(f"cannot wait for {kind!r}. Known kinds: {known}") from None


def catalogue() -> str:
    """The whole wait list as one block of text, for the tool description."""
    return "\n".join(f"  {spec.describe()}" for spec in WAITS.values())


def parse(value: str) -> tuple[str, str]:
    """Split a written wait into its kind and its subject.

    Written as `kind:subject` — `element:#total`, `url:/dashboard`, `idle`. One string
    keeps this to a single argument on a single tool, which is the whole point of having
    one `dejo_act`.
    """
    kind, _, subject = value.partition(":")
    kind = kind.strip() or "idle"
    spec = spec_for(kind)
    subject = subject.strip()
    if spec.needs_value and not subject:
        raise WaitNeedsMore(f"waiting for {kind} needs something to wait for, as {kind}:...")
    if kind == IN_FRAME and not all(part.strip() for part in subject.partition(FRAME_SPLIT)[::2]):
        raise WaitNeedsMore(
            "waiting inside a frame needs the frame and what is in it, as "
            "in_frame:<the iframe>|<what is inside it>"
        )
    return kind, subject


def wait_for(value: str, *, page: Page, timeout_ms: int = DEFAULT_WAIT_MS) -> None:
    """Wait for one thing, or raise `WaitedTooLong` saying what never happened."""
    kind, subject = parse(value)
    try:
        _WAITERS[kind](page, subject, timeout_ms)
    except (PWTimeout, PlaywrightError) as ran_out:
        raise WaitedTooLong(
            f"waited {timeout_ms / 1000:g}s for {kind}"
            f"{f' {subject!r}' if subject else ''} and it never happened"
        ) from ran_out


def _wait_element(page: Page, subject: str, timeout_ms: int) -> None:
    # "visible" and not "attached": attached only means the element exists in the page,
    # which can be true while it is still animating in and cannot yet be clicked.
    began = time.monotonic()
    found = page.locator(subject).first
    found.wait_for(state="visible", timeout=timeout_ms)

    # An iframe is on screen long before anything is in it. Found on Google's file picker:
    # the wait passed on the empty frame and the very next click had nothing to hit. So a
    # frame counts as arrived only once something inside it is visible. Not its body: an
    # empty frame's body already fills the frame, so it reads as visible from the start.
    if found.evaluate("el => el.tagName") in FRAME_TAGS:
        left = max(timeout_ms - (time.monotonic() - began) * MS_PER_SECOND, 0)
        content = page.frame_locator(subject).first.locator(VISIBLE_CONTENT).first
        content.wait_for(state="attached", timeout=left)


def _wait_in_frame(page: Page, subject: str, timeout_ms: int) -> None:
    frame, _, inside = subject.partition(FRAME_SPLIT)
    target = page.frame_locator(frame.strip()).first.locator(inside.strip()).first
    target.wait_for(state="visible", timeout=timeout_ms)


def _wait_gone(page: Page, subject: str, timeout_ms: int) -> None:
    page.locator(subject).first.wait_for(state="hidden", timeout=timeout_ms)


def _wait_text(page: Page, subject: str, timeout_ms: int) -> None:
    page.get_by_text(subject).first.wait_for(state="visible", timeout=timeout_ms)


def _wait_url(page: Page, subject: str, timeout_ms: int) -> None:
    page.wait_for_url(f"**{subject}**", timeout=timeout_ms)


def _wait_idle(page: Page, subject: str, timeout_ms: int) -> None:
    page.wait_for_load_state("networkidle", timeout=timeout_ms)


_WAITERS: dict[str, Any] = {
    "element": _wait_element,
    IN_FRAME: _wait_in_frame,
    "gone": _wait_gone,
    "text": _wait_text,
    "url": _wait_url,
    "idle": _wait_idle,
}


def sanity_check() -> None:
    """Every wait in the registry has a waiter, and every waiter is in the registry."""
    missing_waiter = sorted(set(WAITS) - set(_WAITERS))
    missing_spec = sorted(set(_WAITERS) - set(WAITS))
    if missing_waiter or missing_spec:
        raise AssertionError(
            f"wait registry out of step — no waiter for {missing_waiter}, "
            f"no spec for {missing_spec}"
        )
