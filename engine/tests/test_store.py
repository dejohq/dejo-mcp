"""Tests for the one file that touches memory.

The important one is `test_survives_a_completely_fresh_process`. Dejo's whole claim is
"close your editor, come back tomorrow, it still remembers". A test that writes and reads
in the same process would prove nothing about that, because the data could be sitting in
an in-process cache. So that test spawns a genuinely separate Python interpreter.

Every test uses its own temporary database, so running the suite never touches the real
memory at ~/.dejo/memory.db.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest

from dejo.models import Locator, Playbook, Postcondition, RunMetrics, SiteKnowledge, Step
from dejo.store import DejoStore

DOMAIN = "billing.example.com"
TASK = "download this month's invoice"


@pytest.fixture
def db_path(tmp_path) -> str:
    """A throwaway memory database, one per test."""
    return str(tmp_path / "memory.db")


@pytest.fixture
def store(db_path: str) -> DejoStore:
    return DejoStore(db_path=db_path)


def make_playbook() -> Playbook:
    return Playbook(
        domain=DOMAIN,
        task=TASK,
        steps=[
            Step(
                index=1,
                intent="open the billing page",
                action="goto",
                value=f"https://{DOMAIN}/invoices",
                postcondition=Postcondition("url_contains", "/invoices"),
                locators=[Locator("css", "body", hits=3)],
            ),
            Step(
                index=2,
                intent="download the PDF",
                action="click",
                postcondition=Postcondition("download", "invoice.pdf"),
                locators=[
                    Locator("role", "button:Download", hits=9, misses=1),
                    Locator("css", "#dl-btn", hits=2, misses=6),
                ],
            ),
        ],
    )


class TestPlaybookRoundTrip:
    def test_saves_and_loads_a_playbook(self, store: DejoStore):
        store.save_playbook(make_playbook())

        loaded = store.load_playbook(DOMAIN)

        assert loaded is not None
        assert loaded.domain == DOMAIN
        assert loaded.task == TASK
        assert len(loaded.steps) == 2
        assert loaded.steps[1].intent == "download the PDF"

    def test_unknown_site_returns_none(self, store: DejoStore):
        assert store.load_playbook("never-visited.example.com") is None

    def test_locators_keep_their_scores(self, store: DejoStore):
        store.save_playbook(make_playbook())

        step = store.load_playbook(DOMAIN).steps[1]

        best = step.ranked_locators()[0]
        assert best.kind == "role", "the locator with the better record should rank first"
        assert best.hits == 9
        assert best.misses == 1

    def test_one_site_can_hold_several_trails(self, store: DejoStore):
        """This test used to assert the opposite, and the opposite was a bug.

        Trails were keyed by domain alone, so a second task overwrote the first. It looked
        like a design choice until GitHub: asking about a second repository destroyed the
        trail for the first one.
        """
        store.save_playbook(make_playbook())

        second = make_playbook()
        second.task = "download last year's invoice"
        store.save_playbook(second)

        # One site, still. Two trails on it.
        assert store.list_sites() == [DOMAIN]
        assert store.trails_for(DOMAIN) == sorted([TASK, "download last year's invoice"])

        assert store.load_playbook(DOMAIN, TASK).task == TASK
        assert store.load_playbook(DOMAIN, second.task).task == second.task

    def test_saving_the_same_task_twice_overwrites_it(self, store: DejoStore):
        """Improving a trail must replace it, not pile up copies of it."""
        store.save_playbook(make_playbook())
        again = make_playbook()
        again.steps = again.steps[:1]
        store.save_playbook(again)

        assert store.trails_for(DOMAIN) == [TASK]
        assert len(store.load_playbook(DOMAIN, TASK).steps) == 1

    def test_a_site_with_one_trail_needs_no_task(self, store: DejoStore):
        """A caller that does not name a task can only mean the single one that exists."""
        store.save_playbook(make_playbook())
        assert store.load_playbook(DOMAIN).task == TASK

    def test_a_site_with_several_trails_needs_to_be_asked_properly(self, store: DejoStore):
        """Guessing between two tasks would run the wrong one, which is worse than asking."""
        store.save_playbook(make_playbook())
        second = make_playbook()
        second.task = "download last year's invoice"
        store.save_playbook(second)

        assert store.load_playbook(DOMAIN) is None

    def test_forgetting_a_site_forgets_every_trail_on_it(self, store: DejoStore):
        """The gate has to mean all of them, or a site is only half forgotten."""
        store.save_playbook(make_playbook())
        second = make_playbook()
        second.task = "download last year's invoice"
        store.save_playbook(second)

        assert store.forget_site(DOMAIN) is True
        assert store.trails_for(DOMAIN) == []
        assert store.load_playbook(DOMAIN, TASK) is None
        assert store.load_playbook(DOMAIN, second.task) is None


class TestSiteKnowledge:
    def test_saves_and_loads(self, store: DejoStore):
        store.save_site_knowledge(
            SiteKnowledge(domain=DOMAIN, needs_login=True, needs_2fa=True, notes=["slow at 9am"])
        )

        knowledge = store.load_site_knowledge(DOMAIN)

        assert knowledge is not None
        assert knowledge.needs_2fa is True
        assert knowledge.notes == ["slow at 9am"]


class TestJournal:
    def test_runs_and_repairs_are_recorded_in_order(self, store: DejoStore):
        store.journal_run(
            RunMetrics(domain=DOMAIN, task=TASK, mode="cold", tool_calls=31, model_calls=31)
        )
        store.journal_repair(DOMAIN, 2, 'button "Download"', 'button "Get PDF"')

        kinds = [entry.get("extra", {}).get("kind") for entry in store.read_journal(limit=10)]

        assert "run" in kinds
        assert "repair" in kinds


class TestTheDeletionGate:
    """The deletion test: take the memory away and the fast path must be gone."""

    def test_forget_leaves_replay_with_nothing_to_follow(self, store: DejoStore):
        store.save_playbook(make_playbook())
        store.save_site_knowledge(SiteKnowledge(domain=DOMAIN, needs_login=True))
        assert store.load_playbook(DOMAIN) is not None, "precondition: the trail exists"

        forgotten = store.forget_site(DOMAIN)

        assert forgotten is True
        assert store.load_playbook(DOMAIN) is None, "the trail must be unfollowable"
        assert store.load_site_knowledge(DOMAIN) is None
        assert DOMAIN not in store.list_sites()

    def test_forgetting_an_unknown_site_is_harmless(self, store: DejoStore):
        assert store.forget_site("never-visited.example.com") is False


class TestFreshProcess:
    """Memory has to outlive the process that wrote it, or none of this works."""

    def test_survives_a_completely_fresh_process(self, db_path: str):
        DejoStore(db_path=db_path).save_playbook(make_playbook())

        reader = textwrap.dedent(
            f"""
            import json
            from dejo.store import DejoStore

            playbook = DejoStore(db_path={db_path!r}).load_playbook({DOMAIN!r})
            print(json.dumps({{
                "found": playbook is not None,
                "task": playbook.task if playbook else None,
                "steps": len(playbook.steps) if playbook else 0,
            }}))
            """
        )

        result = subprocess.run(
            [sys.executable, "-c", reader],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, f"reader process failed:\n{result.stderr}"
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report["found"] is True, "a fresh process could not read the trail back"
        assert report["task"] == TASK
        assert report["steps"] == 2

    def test_a_fresh_process_cannot_follow_a_forgotten_trail(self, db_path: str):
        store = DejoStore(db_path=db_path)
        store.save_playbook(make_playbook())
        store.forget_site(DOMAIN)

        reader = textwrap.dedent(
            f"""
            from dejo.store import DejoStore
            print(DejoStore(db_path={db_path!r}).load_playbook({DOMAIN!r}) is None)
            """
        )

        result = subprocess.run(
            [sys.executable, "-c", reader],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().splitlines()[-1] == "True"


class TestHealth:
    def test_a_mostly_broken_playbook_reports_itself_stale(self):
        playbook = make_playbook()
        playbook.steps.append(
            Step(
                index=3,
                intent="open the receipt",
                action="click",
                postcondition=Postcondition("url_contains", "/receipt"),
                locators=[Locator("css", "#receipt", hits=4)],
            )
        )
        for step in playbook.steps:
            step.locators = [Locator("css", "#gone", hits=0, misses=5)]

        assert playbook.is_stale is True

    def test_a_very_short_trail_is_never_declared_stale(self):
        """One broken step out of one is 100%, and retiring on that is how a healthy site
        gets declared rebuilt. Found on GitHub: asking about a different repository
        destroyed the trail for the whole site. A short trail is repaired instead, which
        is recoverable — retiring is not."""
        playbook = make_playbook()
        playbook.steps = playbook.steps[:1]
        playbook.steps[0].locators = [Locator("css", "#gone", hits=0, misses=5)]

        assert playbook.is_stale is False

    def test_a_working_playbook_is_not_stale(self):
        assert make_playbook().is_stale is False


class TestTheDebtPhase5aWouldHaveInherited:
    """Two bugs found by reading, not by anything failing.

    Both were invisible: one search function was never called (it has since been removed
    as dead code), and no test ever stored more than a handful of trails.
    """

    def test_a_listing_does_not_stop_at_a_hundred_sites(self, store: DejoStore):
        """Sibyl, Dejo's first memory, stopped at 100 in silence — no error, just a site
        that was quietly not there. Harmless for one agent; not for a shared commons."""
        for number in range(120):
            store.save_playbook(Playbook(domain=f"site{number:03d}.com", task=TASK))

        assert len(store.list_sites()) == 120

    def test_only_the_memory_file_uses_the_database(self):
        """The promise the README makes: every decision about memory is in store.py, and
        nothing else reaches the database underneath. Checked mechanically, so it cannot rot."""
        assert self._files_mentioning("from .memory import", "dejo.memory import") == [
            "engine/src/dejo/store.py"
        ], "memory calls have escaped store.py"

    def test_only_the_database_file_speaks_sql(self):
        assert self._files_mentioning("import sqlite3", "sibyl_memory_client") == [
            "engine/src/dejo/memory.py"
        ]

    @staticmethod
    def _files_mentioning(*words: str) -> list[str]:
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2]
        return sorted(
            path.relative_to(root).as_posix()
            for folder in ("engine/src", "mcp/src")
            for path in (root / folder).rglob("*.py")
            if any(word in path.read_text(encoding="utf-8") for word in words)
        )
