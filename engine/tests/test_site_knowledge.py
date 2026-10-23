"""Site facts, and the stale rule that makes them matter.

These two are one feature, not two. Throwing away a mostly-broken trail is only a good
idea because the facts about the site survive it — "needs a login", "sends a code to your
phone", "use the finance account". Relearning with those in hand is much cheaper than a
first visit: declare the playbook stale, but KEEP site knowledge.
"""

from __future__ import annotations

import pytest
from tests.conftest import TASK, cold_run

from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.models import Locator, Playbook, Postcondition, SiteKnowledge, Step
from dejo.operations import Session
from dejo.store import DejoStore


class TestFactsAddUp:
    """Facts arrive one at a time, from different visits. Nothing may overwrite the rest."""

    def test_a_fact_is_kept(self):
        knowledge = SiteKnowledge(domain="acme.com")

        knowledge.merge(fact="locks you out after five wrong passwords")

        assert knowledge.notes == ["locks you out after five wrong passwords"]

    def test_a_second_fact_does_not_erase_the_first(self):
        knowledge = SiteKnowledge(domain="acme.com")

        knowledge.merge(fact="the invoice only appears after the 3rd")
        knowledge.merge(fact="the export takes about two minutes")

        assert len(knowledge.notes) == 2

    def test_the_same_fact_twice_is_stored_once(self):
        knowledge = SiteKnowledge(domain="acme.com")

        knowledge.merge(fact="needs the finance login")
        knowledge.merge(fact="  needs the finance login  ")

        assert knowledge.notes == ["needs the finance login"]

    def test_flags_and_facts_live_together(self):
        knowledge = SiteKnowledge(domain="acme.com")

        knowledge.merge(fact="slow on Monday mornings", needs_login=True)
        knowledge.merge(needs_2fa=True, account_hint="finance@acme.com")

        assert knowledge.needs_login is True
        assert knowledge.needs_2fa is True
        assert knowledge.account_hint == "finance@acme.com"
        assert knowledge.notes == ["slow on Monday mornings"]

    def test_the_summary_reads_like_advice_to_a_person(self):
        knowledge = SiteKnowledge(
            domain="acme.com",
            notes=["the invoice only appears after the 3rd"],
            needs_login=True,
            needs_2fa=True,
            account_hint="finance@acme.com",
        )

        summary = knowledge.summary()

        assert "the invoice only appears after the 3rd" in summary
        assert any("login" in line for line in summary)
        assert any("code" in line for line in summary)
        assert any("finance@acme.com" in line for line in summary)

    def test_facts_survive_being_written_and_read_back(self, store: DejoStore):
        store.save_site_knowledge(
            SiteKnowledge(domain="acme.com").merge(fact="needs a login", needs_login=True)
        )

        loaded = store.load_site_knowledge("acme.com")

        assert loaded is not None
        assert loaded.notes == ["needs a login"]
        assert loaded.needs_login is True


class TestDeadLocatorsAreDropped:
    """Sites rarely go back to an old design, so a route that failed with no track record
    is just weight in the trail."""

    def test_a_locator_that_never_worked_and_then_failed_is_dead(self):
        assert Locator("css", "#gone", hits=0, misses=1).is_dead is True

    def test_a_proven_locator_survives_one_failure(self):
        """A network blip must not throw away something that has worked ten times."""
        assert Locator("structural", "href=/file", hits=10, misses=1).is_dead is False

    def test_a_locator_that_worked_once_survives_its_first_miss(self):
        """A miss weighs twice a hit, so this one's confidence is zero. It is still the way
        that worked, and a repair keeps it as a backup."""
        assert Locator("css", "#download-btn", hits=1, misses=1).is_dead is False

    def test_a_locator_that_misses_more_than_it_ever_hit_is_dead(self):
        assert Locator("css", "#download-btn", hits=1, misses=2).is_dead is True

    def test_an_untried_locator_is_not_dead(self):
        assert Locator("css", "#new").is_dead is False

    def test_repairing_drops_the_dead_routes(self, store: DejoStore, browser: Browser):
        playbook = Playbook(
            domain="acme.com",
            task="t",
            steps=[
                Step(
                    index=1,
                    intent="download",
                    action="click",
                    postcondition=Postcondition("download", "f.pdf"),
                    locators=[
                        Locator("css", "#dead-one", misses=2),
                        Locator("text", "Download", misses=1),
                        Locator("structural", "href=/f", hits=9, misses=1),
                    ],
                )
            ],
        )
        store.save_playbook(playbook)

        Executor(store, browser).apply_repair("acme.com", 1, Locator("css", "#get-pdf"))

        kept = [loc.value for loc in store.load_playbook("acme.com").steps[0].locators]
        assert "#get-pdf" in kept, "the new route is kept"
        assert "href=/f" in kept, "the proven route is kept as a fallback"
        assert "#dead-one" not in kept
        assert "Download" not in kept


class TestTheStaleRule:
    """Over half the trail broken means the site was rebuilt, not tweaked."""

    def broken_playbook(self, domain: str) -> Playbook:
        def step(index: int, healthy: bool) -> Step:
            return Step(
                index=index,
                intent=f"step {index}",
                action="click",
                postcondition=Postcondition("url_contains", "/x"),
                locators=[
                    Locator("css", f"#s{index}", hits=5)
                    if healthy
                    else Locator("css", f"#s{index}", misses=5)
                ],
            )

        return Playbook(
            domain=domain,
            task="t",
            steps=[step(1, False), step(2, False), step(3, False), step(4, True)],
        )

    def test_a_mostly_broken_trail_is_retired_instead_of_repaired(
        self, store: DejoStore, browser: Browser
    ):
        store.save_playbook(self.broken_playbook("acme.com"))

        result = Executor(store, browser).run("acme.com")

        assert result.stale is True
        assert result.needs_repair is False, "no point repairing one step of a dead trail"
        assert "rebuilt" in result.reason

    def test_the_trail_is_gone_afterwards(self, store: DejoStore, browser: Browser):
        store.save_playbook(self.broken_playbook("acme.com"))

        Executor(store, browser).run("acme.com")

        assert store.load_playbook("acme.com", "t") is None

    def test_but_the_site_facts_are_kept_and_handed_back(self, store: DejoStore, browser: Browser):
        """This is the whole point of retiring rather than forgetting."""
        store.save_playbook(self.broken_playbook("acme.com"))
        store.save_site_knowledge(
            SiteKnowledge(domain="acme.com").merge(
                fact="the invoice only appears after the 3rd", needs_login=True
            )
        )

        result = Executor(store, browser).run("acme.com")

        assert store.load_site_knowledge("acme.com") is not None
        assert "the invoice only appears after the 3rd" in result.site_facts
        assert any("login" in fact for fact in result.site_facts)

    def test_retiring_is_written_to_the_journal(self, store: DejoStore, browser: Browser):
        store.save_playbook(self.broken_playbook("acme.com"))

        Executor(store, browser).run("acme.com")

        kinds = [entry.get("extra", {}).get("kind") for entry in store.read_journal(limit=20)]
        assert "retired" in kinds

    def test_a_healthy_trail_is_never_retired(
        self, store: DejoStore, browser: Browser, demo_server: str
    ):
        session = Session(browser, store)
        cold_run(session, demo_server)
        session.save(TASK, domain=domain_of(demo_server))

        result = Executor(store, browser).run(domain_of(demo_server), start_url=f"{demo_server}/")

        assert result.stale is False
        assert result.ok is True

    def test_relearning_after_a_retirement_works(
        self, store: DejoStore, browser: Browser, demo_server: str
    ):
        """The fast path can be earned back, and the facts were never lost."""
        domain = domain_of(demo_server)
        store.save_playbook(self.broken_playbook(domain))
        store.save_site_knowledge(SiteKnowledge(domain=domain).merge(needs_login=True))

        assert Executor(store, browser).run(domain).stale is True

        session = Session(browser, store)
        cold_run(session, demo_server)
        session.save(TASK, domain=domain)

        result = Executor(store, browser).run(domain, start_url=f"{demo_server}/")
        assert result.ok is True
        assert store.load_site_knowledge(domain).needs_login is True


class TestForgetStillWipesEverything:
    """Retiring keeps the facts. Forgetting must not — that is the gate."""

    def test_forget_removes_the_facts_too(self, store: DejoStore):
        store.save_playbook(Playbook(domain="acme.com", task="t"))
        store.save_site_knowledge(SiteKnowledge(domain="acme.com").merge(needs_login=True))

        store.forget_site("acme.com")

        assert store.load_playbook("acme.com") is None
        assert store.load_site_knowledge("acme.com") is None


@pytest.fixture
def store(tmp_path) -> DejoStore:
    return DejoStore(db_path=str(tmp_path / "memory.db"))
