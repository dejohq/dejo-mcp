"""One agent's trail, followed by another that has never seen the site.

A dejo is a pile of stones one hiker leaves for the next one. Until now Dejo only helped
the same hiker come back. These tests are about the next hiker.

Nothing here needs a browser. The claim being tested is about memory: what crosses between
two agents, what deliberately does not, and what happens to the deletion gate when the
memory is shared.
"""

from __future__ import annotations

import threading

import pytest

from dejo.models import Locator, Playbook, Postcondition, SiteKnowledge, Step
from dejo.store import (
    COMMONS_TENANT,
    DEFAULT_TENANT,
    DejoStore,
    TrailAlreadyHere,
    agent_tenant,
    offer_key,
)

DOMAIN = "acme.com"
TASK = "read the invoice total"

# Deliberately unlike each other. "private task 0" and "private task 1" share every word
# that carries meaning, so `best_match` treats them as the same job — correctly.
_PRIVATE = [
    "download the annual accounts",
    "cancel the subscription",
    "export every customer record",
    "check the delivery address",
    "rename the workspace",
    "archive last quarter",
]


def _private_task(number: int) -> str:
    return _PRIVATE[number]


def a_trail(*, task: str = TASK, runs: int = 4) -> Playbook:
    """A login-then-read trail, which is the shape that carries something personal."""
    return Playbook(
        domain=DOMAIN,
        task=task,
        runs=runs,
        steps=[
            Step(
                index=1,
                intent="open the portal",
                action="goto",
                value=f"https://{DOMAIN}/",
                postcondition=Postcondition("url_contains", "/"),
            ),
            Step(
                index=2,
                intent="type the account email",
                action="fill",
                value="alice@acme.com",
                postcondition=Postcondition("value_is", "alice@acme.com"),
                locators=[Locator("label", "Email", hits=9)],
            ),
            Step(
                index=3,
                intent="read the total",
                action="read",
                value="text",
                postcondition=Postcondition("element_present", "#total"),
                locators=[Locator("css", "#total", hits=4)],
            ),
        ],
    )


def some_facts() -> SiteKnowledge:
    return SiteKnowledge(
        domain=DOMAIN,
        notes=["the badge is cached, trust the Open tab"],
        needs_login=True,
        account_hint="rohit",
        overlays=["#accept-cookies"],
    )


@pytest.fixture
def shared_db(tmp_path) -> str:
    """One database, the way a team pointing at one file would have it."""
    return str(tmp_path / "memory.db")


@pytest.fixture
def alice(shared_db) -> DejoStore:
    store = DejoStore(db_path=shared_db, agent="alice")
    store.save_playbook(a_trail())
    store.save_site_knowledge(some_facts())
    return store


@pytest.fixture
def bob(shared_db) -> DejoStore:
    """An agent that has never seen anything."""
    return DejoStore(db_path=shared_db, agent="bob")


# ------------------------------------------------------------------ identity


class TestAgentIdentity:
    def test_an_agent_with_no_name_uses_the_memory_that_was_already_there(self, shared_db):
        """The migration guard. Every trail learned before agents existed lives in Sibyl's
        own default tenant, and must still be there afterwards."""
        nameless = DejoStore(db_path=shared_db)

        assert nameless.agent is None
        assert nameless._memory.get_tenant() == DEFAULT_TENANT

    def test_the_agent_name_comes_from_the_environment_when_none_is_given(
        self, shared_db, monkeypatch
    ):
        """`run_stdio` takes no arguments, so an environment variable is the only channel
        an MCP config has."""
        monkeypatch.setenv("DEJO_AGENT", "from-the-environment")

        assert DejoStore(db_path=shared_db).agent == "from-the-environment"

    def test_two_agents_in_one_database_cannot_see_each_others_trails(self, alice, bob):
        assert alice.list_sites() == [DOMAIN]
        assert bob.list_sites() == []
        assert bob.load_playbook(DOMAIN, TASK) is None

    def test_an_agent_is_never_the_commons_by_accident(self):
        """An agent literally called "commons" must not land on the shared tenant."""
        assert agent_tenant("commons") != COMMONS_TENANT

    @pytest.mark.parametrize("bad", ['sql"injection', "up|pipe", "back`tick", "dot..dot", "  "])
    def test_a_name_sibyl_would_refuse_is_refused_here_first(self, bad):
        """Otherwise the agent is silently partitioned into a tenant nobody can reach."""
        with pytest.raises(ValueError):
            agent_tenant(bad)

    def test_passing_both_a_client_and_a_name_is_refused(self, shared_db):
        """Quietly ignoring the name would put the agent in the wrong memory."""
        ready_made = DejoStore(db_path=shared_db)._memory

        with pytest.raises(ValueError, match="not both"):
            DejoStore(ready_made, agent="alice")


class TestNeitherClientEverMoves:
    """One client per tenant, built once. The alternative — switching tenant around each
    shared operation — has a window in which another thread's playbook is written into the
    shared tenant, silently. The MCP server does call this object from two threads."""

    def test_the_agents_own_client_stays_on_its_own_tenant(self, alice):
        before = alice._memory.get_tenant()

        alice.share_trail(DOMAIN)
        alice.offers_for(DOMAIN)
        alice.every_offer()

        assert alice._memory.get_tenant() == before
        assert alice._shared.get_tenant() == COMMONS_TENANT

    def test_sharing_from_several_threads_at_once_never_crosses_over(self, alice, shared_db):
        """The failure this design exists to make impossible."""
        errors: list[BaseException] = []

        def hammer(number: int) -> None:
            try:
                worker = DejoStore(db_path=shared_db, agent=f"agent{number}")
                worker.save_playbook(a_trail(task=_private_task(number)))
                worker.share_trail(DOMAIN, _private_task(number))
                assert worker.load_playbook(DOMAIN, _private_task(number)) is not None
            except BaseException as broke:  # noqa: BLE001 - reported, not swallowed
                errors.append(broke)

        threads = [threading.Thread(target=hammer, args=(n,)) for n in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors, errors
        # Every private trail is still private to the agent that wrote it.
        for number in range(6):
            others = DejoStore(db_path=shared_db, agent=f"agent{(number + 1) % 6}")
            assert others.load_playbook(DOMAIN, _private_task(number)) is None


# ------------------------------------------------------------------- sharing


class TestSharing:
    def test_sharing_puts_the_trail_where_another_agent_can_find_it(self, alice, bob):
        alice.share_trail(DOMAIN)

        offers = bob.offers_for(DOMAIN)
        assert [offer["task"] for offer in offers] == [TASK]
        assert offers[0]["shared_by"] == "alice"

    def test_sharing_leaves_the_agents_own_trail_exactly_where_it_was(self, alice):
        alice.share_trail(DOMAIN)

        mine = alice.load_playbook(DOMAIN, TASK)
        assert mine is not None
        assert mine.runs == 4
        assert mine.steps[1].value == "alice@acme.com"

    def test_a_shared_trail_says_who_left_it(self, alice, bob):
        alice.share_trail(DOMAIN)

        assert bob.offers_for(DOMAIN)[0]["shared_by"] == "alice"

    def test_sharing_a_site_this_agent_does_not_know_shares_nothing(self, bob):
        assert bob.share_trail("never-been-here.com") is None
        assert bob.every_offer() == []

    def test_two_agents_can_offer_the_same_task_without_overwriting_each_other(
        self, alice, bob, shared_db
    ):
        """Keyed by task alone, the second publisher would silently destroy the first."""
        bob.save_playbook(a_trail(runs=1))
        alice.share_trail(DOMAIN)
        bob.share_trail(DOMAIN)

        carol = DejoStore(db_path=shared_db, agent="carol")
        assert sorted(offer["shared_by"] for offer in carol.offers_for(DOMAIN)) == [
            "alice",
            "bob",
        ]

    def test_withdrawing_removes_only_what_this_agent_published(self, alice, bob, shared_db):
        bob.save_playbook(a_trail(runs=1))
        alice.share_trail(DOMAIN)
        bob.share_trail(DOMAIN)

        assert bob.unshare_trail(DOMAIN) is True

        carol = DejoStore(db_path=shared_db, agent="carol")
        assert [offer["shared_by"] for offer in carol.offers_for(DOMAIN)] == ["alice"]

    def test_an_agent_cannot_withdraw_another_agents_offer(self, alice, bob):
        alice.share_trail(DOMAIN)

        assert bob.unshare_trail(DOMAIN) is False
        assert len(bob.offers_for(DOMAIN)) == 1


# --------------------------------------------------------- what never leaves


class TestWhatNeverLeaves:
    """A shared trail carries the route. It does not carry the person."""

    def test_the_email_typed_into_the_login_form_is_not_published(self, alice, bob):
        alice.share_trail(DOMAIN)
        borrowed = bob.borrow_trail(DOMAIN)

        assert "alice@acme.com" not in str(borrowed.to_dict())

    def test_a_shared_login_step_asks_the_borrower_for_its_own_value(self, alice, bob):
        """Not merely safer — more correct. Bob should be signing in as Bob."""
        alice.share_trail(DOMAIN)
        borrowed = bob.borrow_trail(DOMAIN)

        typing = borrowed.steps[1]
        assert typing.value is None
        assert typing.secret == "email"

    def test_the_account_hint_never_leaves_the_agent_that_learned_it(self, alice, bob):
        alice.share_trail(DOMAIN)
        bob.borrow_trail(DOMAIN)

        assert alice.load_site_knowledge(DOMAIN).account_hint == "rohit"
        assert bob.load_site_knowledge(DOMAIN).account_hint is None

    def test_sharing_reports_every_note_it_published(self, alice):
        """Nothing goes out unseen: the caller is shown the notes, not told about them."""
        published = alice.share_trail(DOMAIN)

        assert published["notes_published"] == ["the badge is cached, trust the Open tab"]

    def test_sharing_reports_which_values_it_held_back(self, alice):
        published = alice.share_trail(DOMAIN)

        assert published["values_withheld"] == ["type the account email"]

    def test_the_hard_won_notes_do_travel(self, alice, bob):
        """Usually worth more than the steps — an hour of somebody's afternoon."""
        alice.share_trail(DOMAIN)
        bob.borrow_trail(DOMAIN)

        assert "the badge is cached, trust the Open tab" in bob.load_site_knowledge(DOMAIN).notes

    def test_the_overlays_a_site_pops_up_travel_because_they_belong_to_the_site(self, alice, bob):
        alice.share_trail(DOMAIN)
        bob.borrow_trail(DOMAIN)

        assert bob.load_site_knowledge(DOMAIN).overlays == ["#accept-cookies"]


# ----------------------------------------------------------------- borrowing


class TestBorrowing:
    def test_an_agent_that_has_never_seen_a_site_ends_up_holding_the_trail(self, alice, bob):
        alice.share_trail(DOMAIN)

        assert bob.list_sites() == []
        borrowed = bob.borrow_trail(DOMAIN)

        assert borrowed.task == TASK
        assert bob.list_sites() == [DOMAIN]
        assert bob.load_playbook(DOMAIN, TASK) is not None

    def test_the_evidence_earned_elsewhere_comes_with_it(self, alice, bob):
        """This is what makes borrowing worth more than copying: the borrower's very first
        replay tries the route somebody else already proved."""
        alice.share_trail(DOMAIN)
        borrowed = bob.borrow_trail(DOMAIN)

        assert borrowed.steps[1].locators[0].hits == 9

    def test_the_run_counters_do_not_come_with_it(self, alice, bob):
        """Inheriting them would make the borrower's own journal claim runs it never made."""
        alice.share_trail(DOMAIN)
        borrowed = bob.borrow_trail(DOMAIN)

        assert borrowed.runs == 0
        assert borrowed.inherited_runs == 4

    def test_a_borrowed_trail_records_who_first_walked_the_site(self, alice, bob):
        alice.share_trail(DOMAIN)
        borrowed = bob.borrow_trail(DOMAIN)

        assert borrowed.origin_agent == "alice"
        assert borrowed.borrowed_from == "alice"

    def test_borrowing_survives_being_written_down(self, alice, bob):
        alice.share_trail(DOMAIN)
        bob.borrow_trail(DOMAIN)

        reloaded = bob.load_playbook(DOMAIN, TASK)
        assert reloaded.origin_agent == "alice"
        assert reloaded.inherited_runs == 4

    def test_borrowing_matches_a_task_worded_differently(self, alice, bob):
        """Nobody words a request the same way twice."""
        alice.share_trail(DOMAIN)

        assert bob.borrow_trail(DOMAIN, "what is the total on the invoice") is not None

    def test_borrowing_from_an_empty_commons_returns_nothing(self, bob):
        assert bob.borrow_trail("nobody-shared-this.com") is None

    def test_borrowing_does_not_flatten_a_trail_the_borrower_already_repaired(self, alice, bob):
        alice.share_trail(DOMAIN)
        repaired = a_trail(runs=1)
        repaired.repairs = 2
        bob.save_playbook(repaired)

        with pytest.raises(TrailAlreadyHere, match="repaired"):
            bob.borrow_trail(DOMAIN)

    def test_it_can_be_flattened_when_that_is_what_you_mean(self, alice, bob):
        alice.share_trail(DOMAIN)
        repaired = a_trail(runs=1)
        repaired.repairs = 2
        bob.save_playbook(repaired)

        assert bob.borrow_trail(DOMAIN, force=True) is not None

    def test_both_sides_of_the_handoff_are_written_down(self, alice, bob):
        alice.share_trail(DOMAIN)
        bob.borrow_trail(DOMAIN)

        kinds = [event["extra"]["kind"] for event in bob.read_journal() if event.get("extra")]
        assert "borrowed" in kinds


class TestTheCommonsRemembersWhatHappened:
    """Without this the commons is a pile of files. With it, what is stored changes
    because agents used it — which is the whole of "dynamic storage"."""

    def test_it_counts_how_many_agents_took_a_trail(self, alice, bob):
        alice.share_trail(DOMAIN)
        bob.borrow_trail(DOMAIN)

        assert alice.offers_for(DOMAIN)[0]["borrows"] == 1

    def test_an_agent_can_say_the_trail_worked(self, alice, bob):
        alice.share_trail(DOMAIN)
        bob.borrow_trail(DOMAIN)
        bob.record_outcome(DOMAIN, TASK, worked=True)

        assert alice.offers_for(DOMAIN)[0]["worked_for"] == 1

    def test_an_agent_can_say_it_did_not(self, alice, bob):
        alice.share_trail(DOMAIN)
        bob.record_outcome(DOMAIN, TASK, worked=False)

        assert alice.offers_for(DOMAIN)[0]["failed_for"] == 1

    def test_a_trail_that_worked_for_others_is_offered_first(self, alice, bob, shared_db):
        """Ranked by what happened, not by who published it."""
        bob.save_playbook(a_trail(runs=1))
        alice.share_trail(DOMAIN)
        bob.share_trail(DOMAIN)

        carol = DejoStore(db_path=shared_db, agent="carol")
        carol.record_outcome(DOMAIN, TASK, worked=True)  # lands on the first offer listed

        best = carol.offers_for(DOMAIN)[0]
        assert best["worked_for"] == 1

    def test_re_sharing_keeps_the_record_of_who_it_worked_for(self, alice, bob):
        """The trail may have improved. What it has done for people is still true."""
        alice.share_trail(DOMAIN)
        bob.record_outcome(DOMAIN, TASK, worked=True)
        alice.share_trail(DOMAIN)

        assert alice.offers_for(DOMAIN)[0]["worked_for"] == 1


class TestTheTrailGetsBetterAcrossAgents:
    def test_a_fix_made_by_the_borrower_reaches_the_agent_that_shared_it(self, alice, bob):
        alice.share_trail(DOMAIN)
        bob.borrow_trail(DOMAIN)

        fixed = bob.load_playbook(DOMAIN, TASK)
        fixed.steps[2].locators = [Locator("test_id", "data-testid=total", hits=1)]
        fixed.steps[2].repairs = 1
        bob.save_playbook(fixed)

        assert bob.contribute_repair(DOMAIN, TASK) is True

        offered = Playbook.from_dict(
            alice.offers_for(DOMAIN)[0]
            and alice._offer(offer_key(DOMAIN, TASK, "alice"))["playbook"]
        )
        assert offered.steps[2].locators[0].kind == "test_id"

    def test_contributing_does_not_take_authorship_from_the_first_agent(self, alice, bob):
        alice.share_trail(DOMAIN)
        bob.borrow_trail(DOMAIN)
        fixed = bob.load_playbook(DOMAIN, TASK)
        fixed.steps[2].repairs = 1
        bob.save_playbook(fixed)
        bob.contribute_repair(DOMAIN, TASK)

        offer = alice._offer(offer_key(DOMAIN, TASK, "alice"))
        assert offer["shared_by"] == "alice"
        assert Playbook.from_dict(offer["playbook"]).origin_agent == "alice"

    def test_the_offer_names_everyone_who_improved_it(self, alice, bob):
        alice.share_trail(DOMAIN)
        bob.borrow_trail(DOMAIN)
        fixed = bob.load_playbook(DOMAIN, TASK)
        fixed.steps[2].repairs = 1
        bob.save_playbook(fixed)
        bob.contribute_repair(DOMAIN, TASK)

        assert alice.offers_for(DOMAIN)[0]["contributors"] == ["bob"]


# ---------------------------------------------------------------- the gate


class TestTheGateWithACommons:
    """The commons is memory too. These are the tests that keep "delete it and the project
    stops working" true rather than nearly true."""

    def test_forgetting_also_withdraws_what_this_agent_shared(self, alice, bob):
        alice.share_trail(DOMAIN)
        assert bob.offers_for(DOMAIN)

        alice.forget_site(DOMAIN)

        assert bob.offers_for(DOMAIN) == []

    def test_forgetting_does_not_reach_into_another_agents_memory(self, alice, bob):
        """A real isolation guarantee, and one that has to be said out loud rather than
        discovered: Sibyl offers no way to enumerate tenants."""
        alice.share_trail(DOMAIN)
        bob.borrow_trail(DOMAIN)

        alice.forget_site(DOMAIN)

        assert bob.load_playbook(DOMAIN, TASK) is not None

    def test_a_forgotten_site_is_remembered_as_forgotten(self, alice):
        alice.forget_site(DOMAIN)

        assert alice.was_forgotten(DOMAIN) is True

    def test_a_site_that_was_never_forgotten_is_not_marked(self, alice):
        assert alice.was_forgotten(DOMAIN) is False

    def test_walking_the_site_again_lifts_the_refusal(self, alice):
        alice.forget_site(DOMAIN)
        assert alice.was_forgotten(DOMAIN) is True

        alice.save_playbook(a_trail())

        assert alice.was_forgotten(DOMAIN) is False

    def test_forgetting_still_works_when_the_commons_cannot_be_written_to(self, alice):
        """A full or broken shared memory must never be able to stop a forget."""

        class Broken:
            def __getattr__(self, _name):
                def boom(*args, **kwargs):
                    raise RuntimeError("the commons is unavailable")

                return boom

        alice._shared = Broken()

        assert alice.forget_site(DOMAIN) is True
        assert alice.load_playbook(DOMAIN, TASK) is None


class TestTheWholeClaim:
    """Agent B finishes a task on a site it has never opened, because agent A left a trail.

    Everything above this point moves dictionaries around. This runs a real browser against
    a real page, in a genuinely separate operating-system process, because "two agents" that
    are one process holding two strings is not two agents.
    """

    def test_an_agent_finishes_a_task_on_a_site_it_never_saw(self, browser, shared_db, demo_server):
        from dejo.browser import domain_of
        from dejo.executor import Executor
        from dejo.operations import Session

        site = domain_of(demo_server)

        # Agent A walks it once, the slow way, and leaves the trail behind.
        first = DejoStore(db_path=shared_db, agent="alice")
        walking = Session(browser, first)
        walking.act("open the billing portal", "goto", value=f"{demo_server}/")
        walking.read(
            "text",
            ref=next(
                element["ref"]
                for element in walking.look()["elements"]
                if element["name"] == "Sign in"
            ),
            remember=True,
            intent="read the sign in button",
        )
        walking.save("read the sign in button")
        first.share_trail(site)

        # Agent B has never been here.
        second = DejoStore(db_path=shared_db, agent="bob")
        assert second.list_sites() == []

        borrowed = second.borrow_trail(site)
        assert borrowed is not None

        result = Executor(second, browser).run(site, task=borrowed.task)

        assert result.ok, result.reason
        assert result.answers["read the sign in button"] == "Sign in"
        assert result.metrics.model_calls == 0
        assert borrowed.origin_agent == "alice"

    def test_a_separate_process_can_follow_a_borrowed_trail(self, shared_db, tmp_path):
        """The claim in the form a sceptic would check it: a different OS process, a
        different agent, and memory as the only thing between them."""
        import json
        import subprocess
        import sys
        import textwrap

        DejoStore(db_path=shared_db, agent="alice").save_playbook(a_trail())
        DejoStore(db_path=shared_db, agent="alice").share_trail(DOMAIN)

        elsewhere = textwrap.dedent(f"""
            import json
            from dejo.store import DejoStore

            bob = DejoStore(db_path={shared_db!r}, agent="bob")
            before = bob.list_sites()
            borrowed = bob.borrow_trail({DOMAIN!r})
            print(json.dumps({{
                "knew_nothing": before == [],
                "task": borrowed.task,
                "from": borrowed.borrowed_from,
                "steps": len(borrowed.steps),
            }}))
        """)
        finished = subprocess.run(
            [sys.executable, "-c", elsewhere],
            capture_output=True,
            text=True,
            check=True,
        )

        got = json.loads(finished.stdout.strip().splitlines()[-1])
        assert got["knew_nothing"] is True
        assert got["task"] == TASK
        assert got["from"] == "alice"
        assert got["steps"] == 3
