"""Dejo — a browser memory for AI agents.

Learn a site once, then replay the trail with no model calls.
All Sibyl Memory access lives in `dejo.store`.
"""

from .browser import Browser, Element, Snapshot, domain_of
from .distill import distill
from .events import Emitter, Event
from .executor import Executor, NoTrailError, RepairRequest, ReplayResult
from .models import (
    Control,
    Locator,
    PageMemory,
    Playbook,
    Postcondition,
    RunMetrics,
    SiteKnowledge,
    SiteMap,
    Step,
)
from .operations import Session
from .store import DejoStore

__version__ = "0.3.0"

__all__ = [
    "Browser",
    "DejoStore",
    "Control",
    "Element",
    "Emitter",
    "Event",
    "Executor",
    "Locator",
    "NoTrailError",
    "PageMemory",
    "Playbook",
    "Postcondition",
    "RepairRequest",
    "ReplayResult",
    "RunMetrics",
    "Session",
    "SiteKnowledge",
    "SiteMap",
    "Snapshot",
    "Step",
    "distill",
    "domain_of",
    "__version__",
]
