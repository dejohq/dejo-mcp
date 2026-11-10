"""What the agent reads when it asks a saved task with other values (see the engine's
test_changed_values.py for the replay itself)."""

from __future__ import annotations

from helpers import call

SAVED = "flights from Delhi to Mumbai on 5 Dec"
STEPS = (
    'fill label "From" "Delhi"\n'
    'fill label "To" "Mumbai"\n'
    'fill label "Date" "5 Dec"\n'
    'click button "Search"\n'
    'read css "#result" as flights'
)


def learn(mcp_server, demo_server: str) -> None:
    call(mcp_server, "dejo_run", site=demo_server, task=SAVED, url=f"{demo_server}/safety/flights")
    said = call(mcp_server, "dejo_run", site=demo_server, task=SAVED, steps=STEPS)
    assert "flights = Delhi to Mumbai on 5 Dec: 3 flights" in said, said


def test_every_new_value_is_used_and_named(mcp_server, demo_server):
    learn(mcp_server, demo_server)

    said = call(
        mcp_server, "dejo_run", site=demo_server, task="flights from Kolkata to Pune on 9 Dec"
    )

    assert "flights = Kolkata to Pune on 9 Dec: 3 flights" in said, said
    assert "aimed at 'Kolkata' instead of 'Delhi'" in said, said


def test_a_value_with_no_place_stops_and_is_named(mcp_server, demo_server):
    learn(mcp_server, demo_server)

    said = call(
        mcp_server,
        "dejo_run",
        site=demo_server,
        task="flights from Kolkata to Pune on 9 Dec in business class",
    )

    assert said.startswith('stopped before step 1: you asked for "business", "class"'), said
    assert "Delhi" not in said.split("trail")[0]
    # The page is in the same reply, so the agent can send the new task's steps at once.
    assert "\npage " in said and "next: send steps" in said, said


def test_a_restart_after_a_match_by_other_words_never_replaces_that_trail(mcp_server, demo_server):
    """pub.dev, 10 Nov: a task asked in other words replayed a saved trail, the agent sent
    `restart` and the steps of its own task, and they were saved under the saved trail's
    name. That trail's route was gone, and its next replay answered the other task."""
    learn(mcp_server, demo_server)
    reworded = "show flights from Delhi to Mumbai on 5 Dec"
    said = call(mcp_server, "dejo_run", site=demo_server, task=reworded)
    assert "the same job" in said, said

    steps = f"restart\ngo {demo_server}/safety/flights\n{STEPS}"
    said = call(mcp_server, "dejo_run", site=demo_server, task=reworded, steps=steps)

    assert f'saved "{reworded}"' in said, said
    tasks = call(mcp_server, "dejo_memory", what="sites")
    assert f'"{SAVED}"' in tasks and f'"{reworded}"' in tasks, tasks
    again = call(mcp_server, "dejo_run", site=demo_server, task=SAVED)
    assert "flights = Delhi to Mumbai on 5 Dec: 3 flights" in again, again
