"""A task asked with two or more new values gets every one of them, or a stop.

Saved: "flights from Delhi to Mumbai on 5 Dec". Asked: "flights from Kolkata to Pune on 9 Dec".
Every word of the shape is the same, so the saved trail is the job; but replaying it as
saved answers Delhi to Mumbai, which looks exactly like a right answer. Each changed value
is swapped into the steps, or Dejo stops and says which values it could not place.
"""

from __future__ import annotations

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.operations import Session
from dejo.runner import Runner
from dejo.store import DejoStore

SAVED = "flights from Delhi to Mumbai on 5 Dec"


def learn(browser: Browser, store: DejoStore, demo_server: str) -> None:
    runner = Runner(Session(browser=browser, store=store), task=SAVED, store=store)
    outcome = runner.run(
        program.parse(
            f"go {demo_server}/safety/flights\n"
            'fill label "From" "Delhi"\n'
            'fill label "To" "Mumbai"\n'
            'fill label "Date" "5 Dec"\n'
            'click button "Search"\n'
            'read css "#result" as flights'
        )
    )
    assert outcome.ok, outcome.text()


def replay(browser: Browser, store: DejoStore, demo_server: str, task: str):
    browser.goto("about:blank")
    return Executor(store, browser).run(domain_of(demo_server), task=task)


def test_every_changed_value_is_swapped_in_or_named(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    learn(browser, store, demo_server)

    later = replay(browser, store, demo_server, "flights from Kolkata to Pune on 9 Dec")

    if later.ok:
        assert later.answers["flights"] == "Kolkata to Pune on 9 Dec: 3 flights", later.answers
    else:
        assert all(word in later.reason for word in ("Kolkata", "Pune", "9")), later.reason
    assert "Delhi" not in str(later.answers)


def test_the_saved_values_still_replay_as_saved(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    learn(browser, store, demo_server)

    same = replay(browser, store, demo_server, SAVED)

    assert same.ok, same.reason
    assert same.answers["flights"] == "Delhi to Mumbai on 5 Dec: 3 flights"


def test_a_new_value_with_no_place_in_the_trail_stops_and_says_so(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Business class is not a field this trail fills, so there is nowhere to put it."""
    learn(browser, store, demo_server)

    later = replay(
        browser, store, demo_server, "flights from Kolkata to Pune on 9 Dec in business class"
    )

    assert not later.ok
    assert "business" in later.reason
    assert later.answers == {}


def test_the_trail_keeps_its_own_values(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    learn(browser, store, demo_server)

    replay(browser, store, demo_server, "flights from Kolkata to Pune on 9 Dec")

    kept = store.load_playbook(domain_of(demo_server), SAVED)
    assert kept is not None
    assert [step.value for step in kept.steps if step.action == "fill"] == [
        "Delhi",
        "Mumbai",
        "5 Dec",
    ]
