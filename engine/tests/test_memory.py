"""Dejo's own memory, and the one-time move off Sibyl.

Dejo kept its memory in Sibyl until October 2026. Sibyl's free tier stops writing at 5 MB
of database, and a real user's memory was already past 1.2 MB after five sites, most of it
search indexes Dejo never read. These tests pin the replacement: a plain SQLite file that
keeps what Dejo needs, gives every owner a wall, forgets without erasing, and brings an
existing Sibyl memory across without losing a trail.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from dejo import memory
from dejo.memory import COMMONS, DEFAULT_OWNER, Database, import_sibyl
from dejo.models import Playbook
from dejo.store import DejoStore, OldMemoryUnreadable, adopt_old_memory, open_memory

DOMAIN = "acme.com"
TASK = "read the invoice total"


@pytest.fixture
def database(tmp_path) -> Database:
    return Database(tmp_path / "memory.db")


class TestEntries:
    def test_what_is_put_comes_back(self, database: Database) -> None:
        mine = database.owner(DEFAULT_OWNER)
        mine.put("playbook", "a", {"steps": [1, 2]})

        assert mine.get("playbook", "a") == {"steps": [1, 2]}

    def test_putting_again_replaces(self, database: Database) -> None:
        mine = database.owner(DEFAULT_OWNER)
        mine.put("playbook", "a", {"version": 1})
        mine.put("playbook", "a", {"version": 2})

        assert mine.items("playbook") == [("a", {"version": 2})]

    def test_owners_cannot_see_each_other(self, database: Database) -> None:
        database.owner("agent:alice").put("playbook", "a", {"x": 1})

        assert database.owner("agent:bob").get("playbook", "a") is None
        assert database.owner(COMMONS).names("playbook") == []

    def test_it_survives_closing_the_file(self, tmp_path) -> None:
        first = Database(tmp_path / "memory.db")
        first.owner(DEFAULT_OWNER).put("site_map", DOMAIN, {"pages": []})
        first.close()

        again = Database(tmp_path / "memory.db")
        assert again.owner(DEFAULT_OWNER).get("site_map", DOMAIN) == {"pages": []}


class TestForgettingArchivesRatherThanErases:
    def test_an_archived_entry_is_out_of_reach(self, database: Database) -> None:
        mine = database.owner(DEFAULT_OWNER)
        mine.put("playbook", "a", {"x": 1})

        assert mine.archive("playbook", "a", reason="dejo forget") is True
        assert mine.get("playbook", "a") is None
        assert mine.names("playbook") == []

    def test_but_it_is_not_erased(self, database: Database) -> None:
        mine = database.owner(DEFAULT_OWNER)
        mine.put("playbook", "a", {"x": 1})
        mine.archive("playbook", "a", reason="dejo forget")

        kept = database.run("SELECT body, reason FROM archive WHERE name = 'a'")
        assert kept == [(json.dumps({"x": 1}), "dejo forget")]

    def test_archiving_nothing_says_so(self, database: Database) -> None:
        assert database.owner(DEFAULT_OWNER).archive("playbook", "nope", reason="x") is False


class TestHistory:
    def test_newest_first(self, database: Database) -> None:
        mine = database.owner(DEFAULT_OWNER)
        mine.record(acted=["first"], extra={"kind": "run"})
        mine.record(acted=["second"], extra={"kind": "repair"})

        assert [event["acted"] for event in mine.history()] == [["second"], ["first"]]
        assert mine.history()[0]["extra"] == {"kind": "repair"}

    def test_it_cannot_grow_without_end(self, database: Database, monkeypatch) -> None:
        """History is the one thing that grows with every run, so it is the one ceiling."""
        monkeypatch.setattr(memory, "MAX_HISTORY", 5)
        mine = database.owner(DEFAULT_OWNER)
        for number in range(12):
            mine.record(acted=[f"run {number}"])

        kept = mine.history(limit=100)
        assert len(kept) == 5
        assert kept[0]["acted"] == ["run 11"], "the newest are the ones kept"

    def test_one_owners_ceiling_never_trims_another(self, database, monkeypatch) -> None:
        monkeypatch.setattr(memory, "MAX_HISTORY", 3)
        database.owner(COMMONS).record(acted=["shared once"])
        for number in range(10):
            database.owner(DEFAULT_OWNER).record(acted=[f"run {number}"])

        assert len(database.owner(COMMONS).history()) == 1


def test_many_threads_at_once_lose_nothing(database: Database) -> None:
    """The MCP server writes from several threads at the same time."""
    failures: list[BaseException] = []

    def write(number: int) -> None:
        try:
            for step in range(20):
                database.owner(f"agent:{number}").put("playbook", f"t{step}", {"n": step})
        except BaseException as failed:  # noqa: BLE001 - collected and asserted on below
            failures.append(failed)

    threads = [threading.Thread(target=write, args=(number,)) for number in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert all(len(database.owner(f"agent:{n}").names("playbook")) == 20 for n in range(8))


# ------------------------------------------------------------------ the move off Sibyl


def a_sibyl_memory(path: Path) -> Path:
    """A Sibyl file with exactly the shapes Dejo wrote there, made by Sibyl's own client."""
    from sibyl_memory_client import MemoryClient

    nameless = MemoryClient.local(path, tenant_id=memory.SIBYL_DEFAULT_TENANT)
    nameless.set_entity("playbook", f"{DOMAIN}::read-the-invoice-total", {"task": TASK})
    nameless.set_entity("site_knowledge", DOMAIN, {"domain": DOMAIN, "notes": ["needs a login"]})
    nameless.set_entity("playbook", "gone.com", {"task": "old"})
    nameless.archive_entity("playbook", "gone.com", reason="cairn forget")
    nameless.write_event(acted=["warm run on acme.com"], extra={"kind": "run"})
    # Something else using Sibyl, in the same unnamed tenant. Not Dejo's to take.
    nameless.set_entity("plugin_note", "x", {"from": "another program"})
    nameless.write_event(acted=["another program did a thing"])

    bob = MemoryClient(nameless.storage, tenant_id=memory.SIBYL_AGENT_PREFIX + "bob")
    bob.set_entity("playbook", "github.com", {"task": "count open issues"})
    commons = MemoryClient(nameless.storage, tenant_id=memory.SIBYL_COMMONS_TENANT)
    commons.set_entity("shared_playbook", "github.com::count::bob", {"domain": "github.com"})
    return path


class TestTheSibylMemoryComesAcross:
    def test_every_owner_lands_under_its_dejo_name(self, tmp_path, database) -> None:
        import_sibyl(a_sibyl_memory(tmp_path / "sibyl.db"), database)

        mine = database.owner(DEFAULT_OWNER)
        assert mine.get("playbook", f"{DOMAIN}::read-the-invoice-total") == {"task": TASK}
        assert mine.get("site_knowledge", DOMAIN) == {"domain": DOMAIN, "notes": ["needs a login"]}
        assert database.owner("agent:bob").names("playbook") == ["github.com"]
        assert database.owner(COMMONS).names("shared_playbook") == ["github.com::count::bob"]

    def test_history_and_the_archive_come_too(self, tmp_path, database) -> None:
        import_sibyl(a_sibyl_memory(tmp_path / "sibyl.db"), database)

        assert database.owner(DEFAULT_OWNER).history()[0]["extra"] == {"kind": "run"}
        assert database.run("SELECT name FROM archive") == [("gone.com",)]

    def test_another_programs_memory_is_left_where_it_is(self, tmp_path, database) -> None:
        import_sibyl(a_sibyl_memory(tmp_path / "sibyl.db"), database)

        assert database.owner(DEFAULT_OWNER).names("plugin_note") == []
        acted = [event["acted"] for event in database.owner(DEFAULT_OWNER).history()]
        assert ["another program did a thing"] not in acted

    def test_no_old_name_survives_the_move(self, tmp_path, database) -> None:
        import_sibyl(a_sibyl_memory(tmp_path / "sibyl.db"), database)

        owners = {owner for (owner,) in database.run("SELECT DISTINCT owner FROM entries")}
        assert owners == {DEFAULT_OWNER, "agent:bob", COMMONS}

    def test_the_sibyl_file_is_never_changed(self, tmp_path, database) -> None:
        source = a_sibyl_memory(tmp_path / "sibyl.db")
        before = source.read_bytes()

        import_sibyl(source, database)

        assert source.read_bytes() == before


class TestTheFirstStart:
    def test_it_brings_the_memory_across_once(self, tmp_path) -> None:
        sibyl = a_sibyl_memory(tmp_path / "sibyl.db")
        into = tmp_path / ".dejo" / "memory.db"
        into.parent.mkdir()

        assert adopt_old_memory(into, sibyl) > 0
        assert DejoStore(db_path=str(into)).list_sites() == [DOMAIN]
        assert adopt_old_memory(into, sibyl) == 0, "never twice"

    def test_an_existing_dejo_memory_is_never_overwritten(self, tmp_path) -> None:
        into = tmp_path / "memory.db"
        DejoStore(db_path=str(into)).save_playbook(Playbook(domain="mine.com", task=TASK))

        adopt_old_memory(into, a_sibyl_memory(tmp_path / "sibyl.db"))

        assert DejoStore(db_path=str(into)).list_sites() == ["mine.com"]

    def test_nothing_happens_without_a_sibyl_memory(self, tmp_path) -> None:
        into = tmp_path / "memory.db"

        assert adopt_old_memory(into, tmp_path / "missing.db") == 0
        assert not into.exists()

    def test_a_sibyl_file_with_nothing_of_dejos_leaves_no_file(self, tmp_path) -> None:
        """Otherwise an empty memory would claim an import happened."""
        from sibyl_memory_client import MemoryClient

        other = tmp_path / "sibyl.db"
        MemoryClient.local(other).set_entity("plugin_note", "x", {"from": "elsewhere"})
        into = tmp_path / "memory.db"

        assert adopt_old_memory(into, other) == 0
        assert not into.exists()
        assert not (tmp_path / "memory.db.partial").exists()

    def test_a_broken_sibyl_file_leaves_no_half_memory(self, tmp_path) -> None:
        broken = tmp_path / "sibyl.db"
        broken.write_bytes(b"this is not a database")
        into = tmp_path / "memory.db"

        with pytest.raises(OldMemoryUnreadable) as said:
            adopt_old_memory(into, broken)

        assert "fresh memory" in str(said.value), "it says what happens next"
        assert not into.exists(), "a failed import must not look like a finished one"
        assert not (tmp_path / "memory.db.partial").exists()
        assert broken.read_bytes() == b"this is not a database"


class TestSibylAsAChosenBackend:
    """Kept for anyone who wants their memory in Sibyl. Same store, same behaviour."""

    def test_the_store_works_the_same_on_sibyl(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DEJO_MEMORY", "sibyl")
        store = DejoStore(db_path=str(tmp_path / "sibyl.db"))
        store.save_playbook(Playbook(domain=DOMAIN, task=TASK))
        store.journal_repair(DOMAIN, 1, "css:#old", "css:#new")

        assert type(store._memory).__name__ == "SibylMemory"
        assert store.load_playbook(DOMAIN, TASK) is not None
        assert store.read_journal()[0]["extra"]["kind"] == "repair"

        assert store.forget_site(DOMAIN) is True
        assert store.load_playbook(DOMAIN, TASK) is None
        assert store.was_forgotten(DOMAIN) is True

    def test_dejos_own_memory_is_the_default(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("DEJO_MEMORY", raising=False)
        monkeypatch.delenv("CAIRN_MEMORY", raising=False)

        assert isinstance(open_memory(tmp_path / "memory.db"), Database)
