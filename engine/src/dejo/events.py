"""Typed events. Library code emits these; it never prints.

The CLI renders them for a human, the backend will stream them to the dashboard, and the
MCP server turns them into tool output. One source of truth for "what just happened",
three different audiences.

The memory events are not decoration. `MemoryRead` and `MemoryWrite` are how a watcher —
anyone — can see that memory is actually doing the work rather than being
carried along for show.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import utc_now


@dataclass
class Event:
    """Base for everything emitted. `kind` is what consumers switch on."""

    kind: str = field(init=False, default="event")
    at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        data = {k: v for k, v in self.__dict__.items()}
        data["kind"] = self.kind
        return data


@dataclass
class RunStarted(Event):
    kind = "run_started"
    domain: str = ""
    task: str = ""
    mode: str = "warm"


@dataclass
class RunFinished(Event):
    kind = "run_finished"
    domain: str = ""
    succeeded: bool = False
    duration_ms: int = 0
    steps_replayed: int = 0
    trail_repairs: int = 0
    model_calls: int = 0


@dataclass
class StepStarted(Event):
    kind = "step_started"
    index: int = 0
    intent: str = ""


@dataclass
class StepPassed(Event):
    kind = "step_passed"
    index: int = 0
    intent: str = ""
    matched_by: str = ""
    duration_ms: int = 0


@dataclass
class StepFailed(Event):
    kind = "step_failed"
    index: int = 0
    intent: str = ""
    reason: str = ""


@dataclass
class StepSkipped(Event):
    """A step that only clears something away found nothing to clear this time."""

    kind = "step_skipped"
    index: int = 0
    intent: str = ""
    reason: str = ""


@dataclass
class MemoryRead(Event):
    """A read from Sibyl. Seeing one of these is seeing the warm path work."""

    kind = "memory_read"
    category: str = ""
    name: str = ""
    found: bool = False


@dataclass
class MemoryWrite(Event):
    kind = "memory_write"
    category: str = ""
    name: str = ""
    detail: str = ""


@dataclass
class DriftDetected(Event):
    """A locator that used to match no longer does. The site moved under us."""

    kind = "drift_detected"
    index: int = 0
    locator: str = ""


@dataclass
class RepairNeeded(Event):
    """Every locator missed. This step goes back to the host AI, and only this step."""

    kind = "repair_needed"
    index: int = 0
    intent: str = ""
    tried: list[str] = field(default_factory=list)
    url: str = ""


@dataclass
class RepairSaved(Event):
    kind = "repair_saved"
    index: int = 0
    before: str = ""
    after: str = ""


@dataclass
class Forgotten(Event):
    kind = "forgotten"
    domain: str = ""


class Listener(Protocol):
    def __call__(self, event: Event) -> None: ...


class Emitter:
    """A tiny fan-out. No dependency, no framework, nothing to configure."""

    def __init__(self) -> None:
        self._listeners: list[Callable[[Event], None]] = []
        self.history: list[Event] = []

    def subscribe(self, listener: Callable[[Event], None]) -> None:
        self._listeners.append(listener)

    def emit(self, event: Event) -> Event:
        self.history.append(event)
        for listener in self._listeners:
            listener(event)
        return event

    def of_kind(self, kind: str) -> list[Event]:
        return [event for event in self.history if event.kind == kind]
