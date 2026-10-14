"""Dejo's memory: one SQLite file on this machine, `~/.dejo/memory.db`.

Nothing here knows what a trail is. This file is the database; `store.py` is the only file
that uses it, and the only place that decides what gets remembered.

Three shapes, the ones Dejo has always needed:

    entries   current truth, one per (owner, category, name), replaced as it improves
    archive   where a forgotten entry goes. Out of reach of replay, but not erased
    history   an append-only record of what happened: every run, repair, share and forget

An owner is whose memory it is: `default` for an agent with no name, `agent:<name>` for a
named one, and `commons` for what agents leave for each other. Every read and write names
its owner, so one agent can never see into another's memory by accident.

Python's own `sqlite3`, so remembering needs no extra package and no account. Dejo used
Sibyl Memory until October 2026. Sibyl's free tier stops writing at 5 MB of database, and
most of that went on search indexes Dejo never used; a real user would have hit it after a
few dozen sites. Sibyl is still available as a backend (`DEJO_MEMORY=sibyl`), and an existing
Sibyl memory is imported once, the first time Dejo starts.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .home import HOME

DEFAULT_PATH = HOME / "memory.db"
SIBYL_PATH = Path.home() / ".sibyl-memory" / "memory.db"

DEFAULT_OWNER = "default"
COMMONS = "commons"
AGENT_OWNER_PREFIX = "agent:"

# Bumped whenever the tables below change shape, so a later version can tell what it is
# opening instead of guessing.
SCHEMA_VERSION = 1

# How much history one owner keeps. History grows with every run and nothing else here
# does, so it is the one thing that needs a ceiling. Ten thousand runs is years of daily use.
MAX_HISTORY = 10_000

# How long to wait for another process holding the file, in seconds. Two agents sharing one
# memory is a supported setup, and a write that fails on a moment's contention would lose a
# trail for nothing.
BUSY_TIMEOUT_S = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    owner      TEXT NOT NULL,
    category   TEXT NOT NULL,
    name       TEXT NOT NULL,
    body       TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (owner, category, name)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS archive (
    id          INTEGER PRIMARY KEY,
    owner       TEXT NOT NULL,
    category    TEXT NOT NULL,
    name        TEXT NOT NULL,
    body        TEXT NOT NULL,
    archived_at TEXT NOT NULL,
    reason      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS history (
    id        INTEGER PRIMARY KEY,
    owner     TEXT NOT NULL,
    at        TEXT NOT NULL,
    evaluated TEXT,
    acted     TEXT,
    extra     TEXT
);
CREATE INDEX IF NOT EXISTS history_by_owner ON history (owner, id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Database:
    """One memory file. Safe to share between threads, and between processes."""

    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection, guarded by a lock: the MCP server calls in from its browser thread
        # and from worker threads at once, and sqlite3 connections are not thread-safe alone.
        self._lock = threading.Lock()
        self._db = sqlite3.connect(
            self.path, timeout=BUSY_TIMEOUT_S, check_same_thread=False, isolation_level=None
        )
        with self._lock:
            # WAL lets one process read while another writes: two agents on one memory.
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(_SCHEMA)
            self._db.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def owner(self, name: str) -> Memory:
        """One owner's memory, inside this file."""
        return Memory(self, name)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def run(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def run_together(self, *statements: tuple[str, tuple[Any, ...]]) -> None:
        """Several writes that must all happen or none: archiving is a copy then a delete."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for sql, params in statements:
                    self._db.execute(sql, params)
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")


class Memory:
    """What one owner remembers. Every call is scoped to that owner, and only that owner."""

    def __init__(self, database: Database, owner: str):
        self.database = database
        self.owner = owner

    # ------------------------------------------------------------------ entries

    def put(self, category: str, name: str, body: dict[str, Any]) -> None:
        """Remember something, replacing whatever was there under that name."""
        self.database.run(
            "INSERT INTO entries (owner, category, name, body, updated_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (owner, category, name)"
            " DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at",
            (self.owner, category, name, json.dumps(body), now()),
        )

    def get(self, category: str, name: str) -> dict[str, Any] | None:
        """What is remembered under a name, or None. Something forgotten is None too."""
        rows = self.database.run(
            "SELECT body FROM entries WHERE owner = ? AND category = ? AND name = ?",
            (self.owner, category, name),
        )
        return json.loads(rows[0][0]) if rows else None

    def items(self, category: str) -> list[tuple[str, dict[str, Any]]]:
        """Everything remembered in one category, as (name, body), in name order."""
        rows = self.database.run(
            "SELECT name, body FROM entries WHERE owner = ? AND category = ? ORDER BY name",
            (self.owner, category),
        )
        return [(name, json.loads(body)) for name, body in rows]

    def names(self, category: str) -> list[str]:
        rows = self.database.run(
            "SELECT name FROM entries WHERE owner = ? AND category = ? ORDER BY name",
            (self.owner, category),
        )
        return [name for (name,) in rows]

    def archive(self, category: str, name: str, *, reason: str) -> bool:
        """Forget one entry: moved out of reach, never erased. False if nothing was there."""
        where = (self.owner, category, name)
        found = self.database.run(
            "SELECT body FROM entries WHERE owner = ? AND category = ? AND name = ?", where
        )
        if not found:
            return False
        self.database.run_together(
            (
                "INSERT INTO archive (owner, category, name, body, archived_at, reason)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (*where, found[0][0], now(), reason),
            ),
            ("DELETE FROM entries WHERE owner = ? AND category = ? AND name = ?", where),
        )
        return True

    # ------------------------------------------------------------------ history

    def record(
        self,
        *,
        evaluated: list[str] | None = None,
        acted: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Add one event to history. History is only ever appended to, never edited."""
        self.database.run(
            "INSERT INTO history (owner, at, evaluated, acted, extra) VALUES (?, ?, ?, ?, ?)",
            (
                self.owner,
                now(),
                _json_or_none(evaluated),
                _json_or_none(acted),
                _json_or_none(extra),
            ),
        )
        self.database.run(
            "DELETE FROM history WHERE owner = ? AND id <= ("
            " SELECT id FROM history WHERE owner = ? ORDER BY id DESC LIMIT 1 OFFSET ?)",
            (self.owner, self.owner, MAX_HISTORY),
        )

    def history(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """The most recent events, newest first."""
        rows = self.database.run(
            "SELECT at, evaluated, acted, extra FROM history WHERE owner = ?"
            " ORDER BY id DESC LIMIT ?",
            (self.owner, limit),
        )
        return [
            {
                "at": at,
                "evaluated": _loaded(evaluated) or [],
                "acted": _loaded(acted) or [],
                "extra": _loaded(extra) or {},
            }
            for at, evaluated, acted, extra in rows
        ]


def _json_or_none(value: Any) -> str | None:
    return json.dumps(value) if value is not None else None


def _loaded(text: str | None) -> Any:
    return json.loads(text) if text else None


# ----------------------------------------------------------------- the old memory

# Sibyl's names for the owners Dejo (then Cairn) wrote. Only ever read, by the import.
SIBYL_DEFAULT_TENANT = "00000000-0000-0000-0000-000000000001"
SIBYL_COMMONS_TENANT = "cairn-commons"
SIBYL_AGENT_PREFIX = "cairn-agent-"

# The only categories Dejo ever wrote. A Sibyl file can hold other programs' memory too —
# Sibyl's own plugin writes there — and none of that is Dejo's to take.
DEJO_CATEGORIES = ("playbook", "site_knowledge", "site_map", "shared_playbook", "forgotten")


class OldMemoryUnreadable(RuntimeError):
    """The old Sibyl memory file exists but cannot be read as a database."""


def owner_for_sibyl_tenant(tenant: str) -> str | None:
    """The Dejo owner one Sibyl tenant becomes, or None if it was never Dejo's."""
    if tenant == SIBYL_DEFAULT_TENANT:
        return DEFAULT_OWNER
    if tenant == SIBYL_COMMONS_TENANT:
        return COMMONS
    if tenant.startswith(SIBYL_AGENT_PREFIX):
        return AGENT_OWNER_PREFIX + tenant[len(SIBYL_AGENT_PREFIX) :]
    return None


def import_sibyl(source: Path, into: Database) -> int:
    """Copy everything Dejo wrote into a Sibyl memory file. Returns how many things came.

    Reads Sibyl's file directly, read-only, so the import needs no Sibyl package and can
    never change the original. Live entries, the archive of forgotten ones, and the history
    all come across, under Dejo's own owner names.
    """
    try:
        with contextlib.closing(sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)) as old:
            entries = _rows(old, "SELECT tenant_id, category, name, body, updated_at FROM entities")
            archived = _rows(
                old,
                "SELECT tenant_id, category, name, body, archived_at, archive_reason"
                " FROM archived_entities",
            )
            events = _rows(
                old,
                "SELECT tenant_id, ts, evaluated, acted, extra FROM journal_events ORDER BY ts",
            )
    except sqlite3.DatabaseError as broken:
        raise OldMemoryUnreadable(
            f"Dejo could not read your old Sibyl memory at {source}: {broken}. Dejo starts "
            "with a fresh memory instead, and that file is left exactly as it was."
        ) from broken

    writes: list[tuple[str, tuple[Any, ...]]] = []
    for tenant, category, name, body, updated in entries:
        owner = owner_for_sibyl_tenant(tenant)
        if owner and category in DEJO_CATEGORIES:
            writes.append(
                (
                    "INSERT OR REPLACE INTO entries (owner, category, name, body, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (owner, category, name, body, updated),
                )
            )
    for tenant, category, name, body, at, reason in archived:
        owner = owner_for_sibyl_tenant(tenant)
        if owner and category in DEJO_CATEGORIES and body:
            writes.append(
                (
                    "INSERT INTO archive (owner, category, name, body, archived_at, reason)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (owner, category, name, body, at, reason or "forgotten"),
                )
            )
    for tenant, at, evaluated, acted, extra in events:
        owner = owner_for_sibyl_tenant(tenant)
        # The unnamed tenant is shared with anything else using Sibyl. Dejo's own events
        # always say what kind they are, so those are the ones that come across.
        if owner and (owner != DEFAULT_OWNER or (_loaded(extra) or {}).get("kind")):
            writes.append(
                (
                    "INSERT INTO history (owner, at, evaluated, acted, extra)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (owner, at, evaluated, acted, extra),
                )
            )
    # All of it or none of it: a half-imported memory would look complete and not be.
    into.run_together(*writes)
    return len(writes)


def _rows(db: sqlite3.Connection, sql: str) -> list[tuple[Any, ...]]:
    try:
        return db.execute(sql).fetchall()
    except sqlite3.OperationalError:
        # A Sibyl file too old or too new to have this table holds nothing of it to bring.
        return []


# ------------------------------------------------------------ Sibyl, if chosen

# How many entries one listing may return. Sibyl's own default is 100, and it truncates
# silently, so a caller that never passes one stops seeing sites past a hundred trails.
SIBYL_MAX_LISTED = 5000


class MemoryBackendMissing(RuntimeError):
    """A memory backend was asked for whose package is not installed."""


class SibylDatabase:
    """Sibyl Memory behind the same interface, for anyone who wants their memory there.

    Chosen with `DEJO_MEMORY=sibyl`, and needs `pip install "dejo[sibyl]"`. Uses the exact
    tenant names Dejo wrote to Sibyl before it had its own memory, so a Sibyl file that
    already holds Dejo's trails keeps working. Sibyl's free tier stops writing at 5 MB.
    """

    def __init__(self, path: str | Path = SIBYL_PATH):
        try:
            from sibyl_memory_client import MemoryClient, NotFoundError
        except ImportError as missing:
            raise MemoryBackendMissing(
                'DEJO_MEMORY=sibyl needs the Sibyl package: pip install "dejo[sibyl]"'
            ) from missing
        self._client = MemoryClient
        self.not_found = NotFoundError
        self.path = Path(path).expanduser()
        self._storage = MemoryClient.local(self.path).storage

    def owner(self, name: str) -> SibylMemory:
        return SibylMemory(self, self._client(self._storage, tenant_id=_sibyl_tenant(name)), name)


def _sibyl_tenant(owner: str) -> str:
    if owner == DEFAULT_OWNER:
        return SIBYL_DEFAULT_TENANT
    if owner == COMMONS:
        return SIBYL_COMMONS_TENANT
    return SIBYL_AGENT_PREFIX + owner.removeprefix(AGENT_OWNER_PREFIX)


class SibylMemory:
    """One owner's memory, kept in Sibyl. The same calls as `Memory`, translated."""

    def __init__(self, database: SibylDatabase, client: Any, owner: str):
        self.database = database
        self.owner = owner
        self._client = client

    def put(self, category: str, name: str, body: dict[str, Any]) -> None:
        self._client.set_entity(category, name, body)

    def get(self, category: str, name: str) -> dict[str, Any] | None:
        try:
            entity = self._client.get_entity(category, name)
        except self.database.not_found:
            return None
        body = entity.get("body") if isinstance(entity, dict) and _live(entity) else None
        return body if isinstance(body, dict) else None

    def items(self, category: str) -> list[tuple[str, dict[str, Any]]]:
        found = self._client.list_entities(category=category, limit=SIBYL_MAX_LISTED)
        return sorted(
            (entity["name"], entity["body"])
            for entity in found
            if _live(entity) and isinstance(entity.get("body"), dict)
        )

    def names(self, category: str) -> list[str]:
        return [name for name, _ in self.items(category)]

    def archive(self, category: str, name: str, *, reason: str) -> bool:
        try:
            self._client.archive_entity(category, name, reason=reason)
        except self.database.not_found:
            return False
        return True

    def record(
        self,
        *,
        evaluated: list[str] | None = None,
        acted: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._client.write_event(evaluated=evaluated, acted=acted, extra=extra)

    def history(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return [
            {
                "at": event.get("ts", ""),
                "evaluated": event.get("evaluated") or [],
                "acted": event.get("acted") or [],
                "extra": event.get("extra") or {},
            }
            for event in self._client.read_events(limit=limit)
        ]


def _live(entity: dict[str, Any]) -> bool:
    return str(entity.get("status") or "").lower() != "archived"
