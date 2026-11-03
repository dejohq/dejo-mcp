"""A plain log of what Dejo did and why: one line a step, one file a day.

The reply an agent reads says what happened in that call. A person who wants to know what
their agent did all morning, or why last night's replay broke, should not have to ask the
agent. This writes every learned line and every replayed step to `~/.dejo/logs/DATE.log`,
in words, as the events Dejo already emits arrive. `DEJO_LOG=off` turns it off.

Never allowed to break a run: a log line that cannot be written is dropped.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import home
from .events import (
    Emitter,
    Event,
    RepairNeeded,
    RunFinished,
    RunStarted,
    StepFailed,
    StepPassed,
    StepSkipped,
)

LOG_SETTING = "DEJO_LOG"
OFF = "off"

# How each kind of run is named in the log.
MODES = {"warm": "replay", "learn": "learn"}


def folder() -> Path:
    """Read when needed, so a test that moves the home folder moves the logs too."""
    return home.HOME / "logs"


def attach(emitter: Emitter) -> None:
    """Write this emitter's events to the log, once, unless the log is off."""
    if (home.setting(LOG_SETTING) or "").strip().lower() == OFF:
        return
    if getattr(emitter, "_dejo_logged", False):
        return
    emitter.subscribe(StepLog())
    emitter._dejo_logged = True  # type: ignore[attr-defined]


class StepLog:
    """Turns events into lines. Remembers which run they belong to, since a step's own
    event does not say."""

    def __init__(self) -> None:
        self._run = ""
        self._learning = False

    def __call__(self, event: Event) -> None:
        line = self._line(event)
        if line:
            _write(line)

    def _line(self, event: Event) -> str:
        if isinstance(event, RunStarted):
            self._run = f'{MODES.get(event.mode, event.mode)} {event.domain} "{event.task}"'
            self._learning = event.mode == "learn"
            return f"{self._run}: started"
        if isinstance(event, StepPassed):
            how = f", found by {event.matched_by}" if event.matched_by else ""
            took = f", {event.duration_ms} ms" if event.duration_ms else ""
            return f"{self._run}: step {event.index} done: {event.intent}{how}{took}"
        if isinstance(event, StepFailed):
            return f"{self._run}: step {event.index} failed: {event.intent}: {event.reason}"
        if isinstance(event, StepSkipped):
            return f"{self._run}: step {event.index} skipped: {event.intent}: {event.reason}"
        if isinstance(event, RepairNeeded):
            return f"{self._run}: step {event.index} needs a fix: {event.intent}, on {event.url}"
        if isinstance(event, RunFinished):
            result = "finished" if event.succeeded else "stopped"
            if self._learning:
                # The agent did the thinking for these lines, so there is no count of model
                # calls to give, and the time is the agent's as much as Dejo's.
                return f"{self._run}: {result} after {event.steps_replayed} lines"
            return (
                f"{self._run}: {result} after {event.steps_replayed} steps in "
                f"{event.duration_ms} ms, {event.model_calls} model calls"
            )
        return ""


def _write(line: str) -> None:
    now = datetime.now()
    where = folder() / f"{now:%Y-%m-%d}.log"
    try:
        where.parent.mkdir(parents=True, exist_ok=True)
        with where.open("a", encoding="utf-8") as log:
            log.write(f"{now:%H:%M:%S} {line}\n")
    except OSError:
        # A full disk or a locked file costs the log a line, never the run its task.
        return
