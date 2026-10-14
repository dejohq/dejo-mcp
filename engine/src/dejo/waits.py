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
        "for content that loads late",
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
    page.locator(subject).first.wait_for(state="visible", timeout=timeout_ms)


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
