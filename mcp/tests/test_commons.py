"""The handoff, through the tools a host AI actually sees.

The engine tests prove the memory moves. These prove the AI is told the right thing at the
right moment — which is the part that decides whether the handoff happens at all. On the
first live test of this project a host AI ignored Dejo entirely and reached for `curl`,
so what the descriptions say is not decoration.
"""

from __future__ import annotations

import asyncio

import pytest
from dejo.models import Playbook, Postcondition, Step
from dejo.store import DejoStore

from helpers import call

SITE = "acme.com"
TASK = "read the invoice total"


def a_trail() -> Playbook:
    return Playbook(
        domain=SITE,
        task=TASK,
        runs=3,
        steps=[
            Step(
                index=1,
                intent="open the portal",
                action="goto",
                value=f"https://{SITE}/",
                postcondition=Postcondition("url_contains", "/"),
            )
        ],
    )


@pytest.fixture
def shared_db(tmp_path) -> str:
    return str(tmp_path / "memory.db")


@pytest.fixture
def alice_knows(shared_db) -> DejoStore:
    """An agent that has already learned the site, ready to share it."""
    store = DejoStore(db_path=shared_db, agent="alice")
    store.save_playbook(a_trail())
    return store


@pytest.fixture
def bob_server(shared_db, tmp_path):
    """An MCP server that is agent bob, sharing alice's memory and nothing else."""
    from dejo_mcp.server import build_server

    server = build_server(
        db_path=shared_db,
        headless=True,
        downloads=str(tmp_path / "downloads"),
        # A profile of bob's own. Two agents cannot share one — Chrome allows a single
        # process per profile, and a shared one would mean bob is already signed in to
        # everything alice is, which is not what "never seen this site" should mean.
        profile="",
        profiles_dir=str(tmp_path / "profiles"),
        agent="bob",
    )
    yield server
    server.dejo_tools.close()


def described(server) -> dict[str, str]:
    return {t.name: t.description or "" for t in asyncio.run(server.list_tools())}


# ------------------------------------------------------- being told it exists


def test_an_unknown_site_that_somebody_else_walked_says_so(alice_knows, bob_server):
    alice_knows.share_trail(SITE)

    result = call(bob_server, "dejo_run", site=SITE)

    assert result["known"] is False
    assert result["shared_trails"][0]["task"] == TASK
    assert result["shared_trails"][0]["shared_by"] == "alice"


def test_and_tells_the_ai_to_borrow_rather_than_explore(alice_knows, bob_server):
    """The whole instruction is REPLACED, not added to. Left as it was, it would say
    "explore this site" and "do not explore this site" in the same breath."""
    alice_knows.share_trail(SITE)

    nudge = call(bob_server, "dejo_run", site=SITE)["next"]

    assert "Do NOT explore" in nudge
    assert "dejo_borrow" in nudge


def test_an_unknown_site_nobody_walked_still_says_explore(bob_server):
    result = call(bob_server, "dejo_run", site="nobody-has-been-here.com")

    assert "shared_trails" not in result
    assert "Explore it once" in result["next"]


# ------------------------------------------------------------- borrowing


def test_borrowing_hands_back_the_exact_wording_to_run_with(alice_knows, bob_server):
    """A paraphrase may not match, and the money shot is not a round trip about wording."""
    alice_knows.share_trail(SITE)

    borrowed = call(bob_server, "dejo_borrow", site=SITE)

    assert borrowed["task"] == TASK
    assert TASK in borrowed["next"]


def test_borrowing_says_who_left_it(alice_knows, bob_server):
    alice_knows.share_trail(SITE)

    borrowed = call(bob_server, "dejo_borrow", site=SITE)

    assert borrowed["left_by"] == "alice"
    assert borrowed["first_walked_by"] == "alice"
    assert borrowed["clean_runs_behind_it"] == 3


def test_borrowing_when_nobody_shared_anything_says_so(bob_server):
    result = call(bob_server, "dejo_borrow", site="nobody-has-been-here.com")

    assert result["ok"] is False
    assert "nobody has shared" in result["error"]


def test_after_borrowing_the_site_is_the_borrowers_own(alice_knows, bob_server):
    alice_knows.share_trail(SITE)
    call(bob_server, "dejo_borrow", site=SITE)

    assert SITE in [row["site"] for row in call(bob_server, "dejo_sites")["sites"]]


def test_borrowing_refuses_to_flatten_a_repaired_trail(alice_knows, bob_server, shared_db):
    mine = a_trail()
    mine.repairs = 2
    DejoStore(db_path=shared_db, agent="bob").save_playbook(mine)
    alice_knows.share_trail(SITE)

    refused = call(bob_server, "dejo_borrow", site=SITE)

    assert refused["ok"] is False
    assert "force=true" in refused["error"]


# --------------------------------------------------------------- sharing


def test_sharing_a_site_this_agent_never_walked_says_so(bob_server):
    result = call(bob_server, "dejo_share", site="nobody-has-been-here.com")

    assert result["ok"] is False
    assert "dejo_save" in result["error"]


def test_the_share_description_says_what_becomes_public(bob_server):
    """Nobody should learn what sharing publishes by discovering it afterwards."""
    text = described(bob_server)["dejo_share"]

    assert "NEVER LEAVES" in text
    assert "anything typed into a field" in text


def test_the_commons_lists_what_other_agents_have_left(alice_knows, bob_server):
    alice_knows.share_trail(SITE)

    shelf = call(bob_server, "dejo_commons")

    assert shelf["count"] == 1
    assert shelf["shared_trails"][0]["shared_by"] == "alice"
    assert shelf["you_are"] == "bob"


# ------------------------------------------------------------- the gate


def test_a_forgotten_site_is_not_quietly_offered_back(alice_knows, bob_server, shared_db):
    """Forgetting has to mean something. Answering "somebody else still has it" one
    message later would make it meaningless."""
    alice_knows.share_trail(SITE)
    call(bob_server, "dejo_borrow", site=SITE)
    call(bob_server, "dejo_forget", site=SITE)

    result = call(bob_server, "dejo_run", site=SITE)

    assert "shared_trails" not in result
    assert result["was_forgotten"] is True
    assert "forget" in result["next"].lower()


def test_but_it_can_still_be_asked_for_on_purpose(alice_knows, bob_server):
    """Refusing to volunteer it is not the same as refusing to give it."""
    alice_knows.share_trail(SITE)
    call(bob_server, "dejo_borrow", site=SITE)
    call(bob_server, "dejo_forget", site=SITE)

    assert call(bob_server, "dejo_borrow", site=SITE)["ok"] is True


# --------------------------------------------------------------- surface


def test_dejo_run_is_still_the_first_thing_the_instructions_name(bob_server):
    """Three more tools must not dislodge the one that has to be called first."""
    instructions = bob_server.instructions or ""

    assert "dejo_run FIRST" in instructions
    assert instructions.index("dejo_run") < instructions.index("dejo_act")


def test_the_new_tools_answer_with_a_message_not_a_stack_trace(bob_server):
    for tool in ("dejo_share", "dejo_borrow"):
        result = call(bob_server, tool, site="")
        assert result["ok"] is False
        assert "Traceback" not in str(result)


def test_forget_says_what_it_withdrew(alice_knows, bob_server):
    """Forgetting has to be legible: what it reached, and what it could not."""
    alice_knows.share_trail(SITE)
    call(bob_server, "dejo_borrow", site=SITE)
    call(bob_server, "dejo_share", site=SITE)

    result = call(bob_server, "dejo_forget", site=SITE)

    assert result["withdrawn_from_commons"] == 1
    assert "Withdrawn from the shared memory" in result["message"]


def test_forget_says_what_it_cannot_reach(alice_knows, bob_server):
    """Sibyl offers no way to enumerate tenants, so this is a real boundary — and a
    guarantee rather than a shortcoming, but only if somebody says so."""
    alice_knows.share_trail(SITE)
    call(bob_server, "dejo_borrow", site=SITE)

    result = call(bob_server, "dejo_forget", site=SITE)

    assert result["other_agents_still_have_it"] == 1
    assert "cannot reach into another agent's memory" in result["message"]
