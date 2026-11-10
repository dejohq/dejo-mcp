"""A site that shows version A on one visit and version B on the next, as an A/B test does.

The same control has other words, another class and another place in each version. Once
Dejo has seen both, a replay works on either, and fixing it for one version must not undo
the fix for the other: no flip-flop. Measured over six alternating replays.
"""

from __future__ import annotations

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.operations import Session
from dejo.runner import Runner
from dejo.store import DejoStore

TASK = "what is the basket total"

# Replays after learning: B, A, B, A, B, A.
ALTERNATING_RUNS = 6

# The fix an agent sends when a version breaks the step: the same click, on its own words.
FIX_FOR = {True: 'click button "See the total"', False: 'click button "Show total"'}


def learn(browser: Browser, store: DejoStore, demo_server: str) -> None:
    runner = Runner(Session(browser=browser, store=store), task=TASK, store=store)
    outcome = runner.run(
        program.parse(
            f'go {demo_server}/safety/ab\nclick button "Show total"\nread css "#total" as total'
        )
    )
    assert outcome.ok, outcome.text()


def run_or_fix(browser: Browser, store: DejoStore, domain: str) -> tuple[bool, str]:
    """One replay; when it breaks, the agent's one-line fix. Says whether a fix was needed
    and what the task answered in the end."""
    result = Executor(store, browser).run(domain, task=TASK)
    assert not browser.page.evaluate("Boolean(window.lab.removed)"), "it removed the item"
    if result.ok:
        return False, str(result.answers.get("total"))
    assert result.repair is not None, result.reason
    runner = Runner(Session(browser=browser, store=store), task=TASK, store=store)
    runner.fix_from(
        domain,
        store.load_playbook(domain, TASK),
        result.repair.step_index,
        answers=result.answers,
    )
    on_b = browser.page.get_by_text("See the total").count() > 0
    fixed = runner.run(program.parse(FIX_FOR[on_b]))
    assert fixed.ok, fixed.text()
    return True, str(fixed.answers.get("total"))


def test_both_versions_replay_once_each_has_been_seen(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    learn(browser, store, demo_server)
    domain = domain_of(demo_server)

    runs = [run_or_fix(browser, store, domain) for _ in range(ALTERNATING_RUNS)]

    fixes = [needed for needed, _ in runs]
    assert fixes[0], "the first visit to version B is new, and asks for its fix"
    assert not any(fixes[1:]), f"a fix undid another (fix needed per run: {fixes})"
    assert all(answer == "£31.40" for _, answer in runs), runs


def test_neither_version_s_way_is_thrown_away(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    learn(browser, store, demo_server)
    domain = domain_of(demo_server)
    for _ in range(ALTERNATING_RUNS):
        run_or_fix(browser, store, domain)

    kept = store.load_playbook(domain, TASK)
    assert kept is not None
    ways = {locator.value for locator in kept.steps[1].locators}
    assert "button|Show total" in ways and "button|See the total" in ways, ways


def test_a_control_that_only_sits_where_the_old_one_sat_is_never_pressed(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Version B puts "Remove item" first. The step's way of finding "Show total" by its
    place finds it there, and pressing it removed the item and called the step stale."""
    learn(browser, store, demo_server)

    on_b = Executor(store, browser).run(domain_of(demo_server), task=TASK)

    assert not on_b.ok and on_b.repair is not None
    assert not browser.page.evaluate("Boolean(window.lab.removed)")
    assert "Remove item" in on_b.reason, on_b.reason
