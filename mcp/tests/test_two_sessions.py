"""The same task, on the same profile, from two places at once.

A profile is one browser, and a browser profile can be open in one process at a time. A
second Dejo session (another agent, another terminal) asking for a profile the first one
holds cannot use it. That is not built around here: the second session is told who holds
the profile and what to do, and nothing it started is half-written into memory. Two calls
inside ONE session share its browser and wait their turn.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from dejo.browser import domain_of

from dejo_mcp.server import build_server
from helpers import call

TASK = "what is due"


def a_server(tmp_path, db: str):
    return build_server(
        db_path=db,
        headless=True,
        downloads=str(tmp_path / "downloads"),
        profile=str(tmp_path / "default-profile"),
        profiles_dir=str(tmp_path / "profiles"),
    )


@pytest.fixture
def two_sessions(tmp_path):
    db = str(tmp_path / "memory.db")
    first, second = a_server(tmp_path, db), a_server(tmp_path, db)
    yield first, second
    first.dejo_tools.close()
    second.dejo_tools.close()


def learn(server, demo_server: str) -> str:
    call(server, "dejo_run", site=demo_server, task=TASK, url=f"{demo_server}/drift/session")
    return call(server, "dejo_run", site=demo_server, task=TASK, steps='read css "#due" as due')


def test_the_second_session_is_told_what_to_do(two_sessions, demo_server):
    first, second = two_sessions
    assert "due = 48,200 due" in learn(first, demo_server)

    said = call(second, "dejo_run", site=demo_server, task="another task", url=demo_server)

    assert "in use by" in said, said
    assert "dejo_profile" in said, "it says how to go on: another profile"
    assert "Traceback" not in said


def test_nothing_the_second_session_started_is_half_written(two_sessions, demo_server):
    first, second = two_sessions
    learn(first, demo_server)

    call(second, "dejo_run", site=demo_server, task=TASK, steps='read css "#due" as other')
    call(second, "dejo_run", site=demo_server, task="another task", url=demo_server)

    store = first.dejo_tools.store
    key = domain_of(demo_server)
    trail = store.load_playbook(key, TASK)
    assert trail is not None and [step.intent for step in trail.steps][-1] == "due"
    assert store.load_draft(key, TASK) is None
    assert store.load_draft(key, "another task") is None
    assert store.trails_for(key) == [TASK]


def test_two_calls_in_one_session_take_turns(tmp_path, demo_server):
    server = a_server(tmp_path, str(tmp_path / "memory.db"))
    try:
        learn(server, demo_server)
        with ThreadPoolExecutor(max_workers=2) as both:
            replies = list(
                both.map(lambda _: call(server, "dejo_run", site=demo_server, task=TASK), range(2))
            )
        for said in replies:
            assert "due = 48,200 due" in said, said
        trail = server.dejo_tools.store.load_playbook(domain_of(demo_server), TASK)
        assert trail is not None and trail.runs == 2, "a run's record was lost"
    finally:
        server.dejo_tools.close()
