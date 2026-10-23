"""The handoff between agents, through the tools a host AI actually sees.

The engine tests prove the memory moves. These prove the agent is told the right thing at
the right moment, which decides whether the handoff happens at all.
"""

from __future__ import annotations

import pytest
from dejo.models import Playbook, Postcondition, Step
from dejo.store import DejoStore

from helpers import call, result

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
    """An MCP server that is agent bob, sharing alice's memory and nothing else. A profile
    of bob's own: Chrome allows one process per profile, and a shared one would mean bob is
    already signed in to everything alice is."""
    from dejo_mcp.server import build_server

    server = build_server(
        db_path=shared_db,
        headless=True,
        downloads=str(tmp_path / "downloads"),
        profile="",
        profiles_dir=str(tmp_path / "profiles"),
        agent="bob",
    )
    yield server
    server.dejo_tools.close()


# ------------------------------------------------------- being told it exists


def test_an_unknown_site_somebody_else_walked_offers_their_trail(alice_knows, bob_server):
    alice_knows.share_trail(SITE)

    said = call(bob_server, "dejo_run", site=SITE, task=TASK)

    assert f'another agent shared a trail here: "{TASK}" (by alice)' in said
    assert "dejo_manage do=borrow" in said


def test_and_the_page_is_not_opened_to_learn_it_again(alice_knows, bob_server):
    """Opening the page would invite the agent to learn the site all over again."""
    alice_knows.share_trail(SITE)

    said = call(bob_server, "dejo_run", site=SITE, task=TASK)

    assert "page " not in said and "next: borrow it" in said


def test_a_url_says_learn_it_myself(alice_knows, bob_server, demo_server):
    alice_knows.share_trail(SITE)

    said = call(bob_server, "dejo_run", site=SITE, task=TASK, url=f"{demo_server}/")

    assert "another agent shared a trail here" in said
    assert 'button "Sign in"' in said


# ------------------------------------------------------------- borrowing


def test_borrowing_hands_back_the_exact_wording_to_run_with(alice_knows, bob_server):
    alice_knows.share_trail(SITE)

    borrowed = call(bob_server, "dejo_manage", do="borrow", site=SITE)

    assert borrowed == f'borrowed "{TASK}" on {SITE}. Run it with that task.'


def test_borrowing_when_nobody_shared_anything_says_so(bob_server):
    said = result(bob_server, "dejo_manage", do="borrow", site="nobody-has-been-here.com")

    assert said.isError
    assert "nobody has shared" in said.content[0].text


def test_after_borrowing_the_site_is_the_borrowers_own(alice_knows, bob_server):
    alice_knows.share_trail(SITE)
    call(bob_server, "dejo_manage", do="borrow", site=SITE)

    assert SITE in call(bob_server, "dejo_memory", what="sites")


def test_borrowing_refuses_to_flatten_a_repaired_trail(alice_knows, bob_server, shared_db):
    mine = a_trail()
    mine.repairs = 2
    DejoStore(db_path=shared_db, agent="bob").save_playbook(mine)
    alice_knows.share_trail(SITE)

    refused = result(bob_server, "dejo_manage", do="borrow", site=SITE)

    assert refused.isError
    assert "do=forget" in refused.content[0].text


# --------------------------------------------------------------- sharing


def test_sharing_a_site_this_agent_never_walked_says_so(bob_server):
    said = result(bob_server, "dejo_manage", do="share", site="nobody-has-been-here.com")
    assert said.isError
    assert "no trail" in said.content[0].text


def test_sharing_says_typed_values_never_leave(alice_knows, bob_server):
    DejoStore(db_path=str(alice_knows.where), agent="bob").save_playbook(a_trail())

    shared = call(bob_server, "dejo_manage", do="share", site=SITE)

    assert shared.startswith(f'shared "{TASK}" on {SITE}. Typed values never leave.')


def test_the_commons_lists_what_other_agents_have_left(alice_knows, bob_server):
    alice_knows.share_trail(SITE)

    shelf = call(bob_server, "dejo_memory", what="commons")

    assert shelf == f'{SITE} · "{TASK}" · by alice'


# ------------------------------------------------------------- the gate


def test_a_forgotten_site_is_not_quietly_offered_back(alice_knows, bob_server, demo_server):
    """Forgetting has to mean something. Answering "somebody else still has it" one message
    later would make it meaningless."""
    alice_knows.share_trail(SITE)
    call(bob_server, "dejo_manage", do="borrow", site=SITE)
    call(bob_server, "dejo_manage", do="forget", site=SITE)

    said = call(bob_server, "dejo_run", site=SITE, task=TASK, url=f"{demo_server}/")

    assert "another agent shared" not in said
    assert "forgotten on purpose" in said


def test_but_it_can_still_be_asked_for_on_purpose(alice_knows, bob_server):
    """Refusing to volunteer it is not the same as refusing to give it."""
    alice_knows.share_trail(SITE)
    call(bob_server, "dejo_manage", do="borrow", site=SITE)
    call(bob_server, "dejo_manage", do="forget", site=SITE)

    assert call(bob_server, "dejo_manage", do="borrow", site=SITE).startswith("borrowed")


def test_forget_says_what_it_withdrew(alice_knows, bob_server):
    alice_knows.share_trail(SITE)
    call(bob_server, "dejo_manage", do="borrow", site=SITE)
    call(bob_server, "dejo_manage", do="share", site=SITE)

    said = call(bob_server, "dejo_manage", do="forget", site=SITE)

    assert "Withdrawn from the commons: 1." in said


def test_forget_says_what_it_cannot_reach(alice_knows, bob_server):
    """Said plainly rather than left to be discovered: another agent's memory is a boundary
    Dejo cannot cross, which is a guarantee only if somebody says so."""
    alice_knows.share_trail(SITE)
    call(bob_server, "dejo_manage", do="borrow", site=SITE)

    said = call(bob_server, "dejo_manage", do="forget", site=SITE)

    assert "1 other agent(s) still hold their own copy" in said
    assert "cannot reach into another agent's memory" in said


def test_a_bad_call_answers_with_a_message_not_a_stack_trace(bob_server):
    said = result(bob_server, "dejo_manage", do="teleport", site=SITE)
    assert said.isError
    assert "Traceback" not in said.content[0].text
