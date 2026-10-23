"""THE GATE.

Memory must be load-bearing: take it away, and the project must stop doing what it
claims. This file is that test, automated.

It runs with NO API key, because Dejo needs none. Anyone can clone this repo and run:

    pytest engine/tests/test_deletion_gate.py -v

The shape of the proof is deliberately blunt:

    learn a site      ->  replay is fast and needs no model
    dejo forget      ->  replay has nothing to follow and says so
    learn it again    ->  the fast path comes back

If someone deleted `store.py` and stubbed the memory out, the middle step would pass
silently and the last step would fail. That is the point.
"""

from __future__ import annotations

import pytest
from tests.conftest import TASK, cold_run

from dejo.browser import Browser, domain_of
from dejo.events import Emitter
from dejo.executor import Executor, NoTrailError
from dejo.operations import Session
from dejo.store import DejoStore


@pytest.fixture
def learned_site(browser: Browser, store: DejoStore, demo_server: str) -> str:
    """Walk the site once, so there is something to take away."""
    session = Session(browser, store)
    cold_run(session, demo_server)
    session.save(TASK, domain=domain_of(demo_server))
    return domain_of(demo_server)


class TestTheDeletionGate:
    def test_before_forgetting_the_fast_path_works(
        self, learned_site: str, store: DejoStore, browser: Browser, demo_server: str
    ):
        result = Executor(store, browser).run(learned_site, start_url=f"{demo_server}/")

        assert result.ok is True
        assert result.metrics.steps_replayed == 6
        assert result.metrics.model_calls == 0

    def test_after_forgetting_there_is_nothing_left_to_follow(
        self, learned_site: str, store: DejoStore, browser: Browser, demo_server: str
    ):
        """The whole gate, in five lines."""
        assert store.load_playbook(learned_site) is not None

        store.forget_site(learned_site)

        with pytest.raises(NoTrailError):
            Executor(store, browser).run(learned_site, start_url=f"{demo_server}/")

    def test_it_says_so_out_loud_rather_than_improvising(
        self, learned_site: str, store: DejoStore, browser: Browser, demo_server: str
    ):
        """Failing loudly matters. Quietly falling back to guessing would hide the gate."""
        store.forget_site(learned_site)

        with pytest.raises(NoTrailError) as raised:
            Executor(store, browser).run(learned_site, start_url=f"{demo_server}/")

        message = str(raised.value).lower()
        assert "nothing remembered" in message
        assert learned_site in str(raised.value)

    def test_the_memory_read_is_what_fails(
        self, learned_site: str, store: DejoStore, browser: Browser, demo_server: str
    ):
        """Proves the failure comes from memory being gone, not from the browser."""
        store.forget_site(learned_site)
        emitter = Emitter()

        with pytest.raises(NoTrailError):
            Executor(store, browser, emitter=emitter).run(learned_site)

        reads = emitter.of_kind("memory_read")
        assert reads, "it should still have tried to read memory"
        assert reads[0].to_dict()["found"] is False

    def test_the_site_itself_is_untouched(
        self, learned_site: str, store: DejoStore, browser: Browser, demo_server: str
    ):
        """Forgetting removes what Dejo learned, not the ability to browse.

        Dejo degrades to an ordinary browser tool — slow again, exactly as it was on
        day one. That is the honest claim, and this pins it.
        """
        store.forget_site(learned_site)

        browser.goto(f"{demo_server}/")
        snapshot = browser.snapshot()

        assert snapshot.elements, "the browser still works perfectly well"
        assert any(element.name == "Sign in" for element in snapshot.elements)

    def test_the_fast_path_can_be_earned_back(
        self, learned_site: str, store: DejoStore, browser: Browser, demo_server: str
    ):
        """Walk it again and the trail returns. Forgetting is not damage."""
        store.forget_site(learned_site)

        session = Session(browser, store)
        cold_run(session, demo_server)
        session.save(TASK, domain=learned_site)

        result = Executor(store, browser).run(learned_site, start_url=f"{demo_server}/")
        assert result.ok is True
        assert result.metrics.steps_replayed == 6

    def test_the_map_of_the_site_goes_too(
        self, learned_site: str, store: DejoStore, browser: Browser, demo_server: str
    ):
        """Dejo also remembers the pages it looked at on the way, not just the route.

        That memory has to fall to the same command. Anyone who deletes the memory and
        finds Dejo still knows the site's shape — its pages, its buttons — has found a
        gate that does not hold, whatever the trail says.
        """
        walked = store.load_site_map(learned_site)
        assert walked is not None and not walked.is_empty, "the walk should have been mapped"

        store.forget_site(learned_site)

        assert store.load_site_map(learned_site) is None
        assert learned_site not in store.mapped_sites()

    def test_a_half_learned_task_goes_too(self, learned_site: str, store: DejoStore):
        """A draft is a task being learned. If it survived, the next run would resume it,
        which is a site being remembered after it was forgotten."""
        from dejo.models import Playbook

        store.save_draft(Playbook(domain=learned_site, task="pay the bill"))
        store.save_draft(Playbook(domain="other.example.com", task="pay the bill"))

        store.forget_site(learned_site)

        assert store.load_draft(learned_site, "pay the bill") is None
        assert store.load_draft("other.example.com", "pay the bill") is not None

    def test_forgetting_one_site_leaves_the_others_alone(
        self, learned_site: str, store: DejoStore, demo_server: str
    ):
        from dejo.models import Playbook

        store.save_playbook(Playbook(domain="other.example.com", task="something else"))

        store.forget_site(learned_site)

        assert store.load_playbook("other.example.com") is not None
        assert store.load_playbook(learned_site) is None


class TestTheGateSurvivesASharedMemory:
    """A commons is memory too, so it could quietly become a back door around the gate.

    These are the tests that keep "delete the memory and the project stops working" true
    rather than nearly true.
    """

    def test_replay_never_reads_the_commons(self):
        """The rule the whole gate rests on, checked mechanically.

        If `Executor` could fall back to a shared trail, this entire file would be proving
        nothing: a person would forget a site and replay would carry on regardless. Another
        agent's trail has to be deliberately borrowed first, which copies it into this
        agent's own memory, which is exactly what makes it forgettable.
        """
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1] / "src/dejo/executor.py").read_text(
            encoding="utf-8"
        )
        body = source.split('"""', 2)[-1]

        for reaching_out in (
            "offers_for",
            "borrow_trail",
            "every_offer",
            "_shared",
        ):
            assert reaching_out not in body, (
                f"executor.py touches the commons via {reaching_out} — the warm path must "
                f"only ever follow a trail this agent holds itself"
            )

        # And it must never reach for the network either. A replay that fetched a trail
        # mid-run would be neither deterministic, nor free, nor forgettable.
        for off_machine in ("requests", "httpx", "urllib.request", "socket"):
            assert off_machine not in body, (
                f"executor.py reaches off this machine via {off_machine} — replay must stay "
                f"offline, deterministic and free"
            )

    def test_forgetting_a_site_leaves_replay_with_nothing_even_when_others_shared_it(
        self, tmp_path, browser, demo_server
    ):
        from dejo.browser import domain_of
        from dejo.executor import Executor, NoTrailError
        from dejo.models import Playbook, Postcondition, Step
        from dejo.store import DejoStore

        shared_db = str(tmp_path / "memory.db")
        site = domain_of(demo_server)
        trail = Playbook(
            domain=site,
            task="open the portal",
            steps=[
                Step(
                    index=1,
                    intent="open the portal",
                    action="goto",
                    value=f"{demo_server}/",
                    postcondition=Postcondition("url_contains", "/"),
                )
            ],
        )

        alice = DejoStore(db_path=shared_db, agent="alice")
        alice.save_playbook(trail)
        alice.share_trail(site)

        bob = DejoStore(db_path=shared_db, agent="bob")
        bob.borrow_trail(site)
        assert Executor(bob, browser).run(site, task="open the portal").ok

        bob.forget_site(site)

        # Alice still offers it. That changes nothing for replay.
        assert bob.offers_for(site)
        with pytest.raises(NoTrailError):
            Executor(bob, browser).run(site, task="open the portal")
