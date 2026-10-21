"""Running programs: many steps in one call, stopping at the first that fails, saving itself.

Every test drives the real demo site through a real browser, because what matters here is
what a program leaves behind: the trail replay will follow, the draft a later call resumes,
and how many times the shop's "Pay now" really ran.
"""

from __future__ import annotations

import pytest
from tests.demo_site.app import ORDERS

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.operations import Session, TraceEntry
from dejo.runner import Outcome, Runner, drop_detours
from dejo.store import DejoStore

TASK = "download this month's invoice"


def runner_for(browser: Browser, store: DejoStore, task: str = TASK) -> Runner:
    return Runner(Session(browser=browser, store=store), task=task, store=store)


def run(runner: Runner, text: str, **options) -> Outcome:
    return runner.run(program.parse(text), **options)


def ref_of(runner: Runner, name: str) -> str:
    """The ref the latest view printed for an element with this name."""
    assert runner._view is not None
    for ref, target in runner._view.targets.items():
        if target.node.name == name:
            return ref
    raise AssertionError(f"no {name!r} in the view")


# ------------------------------------------------------------------- learn in one call


def test_a_blind_program_learns_a_task_and_replays_it(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The whole invoice task in ONE program, written without looking at a single page.
    It ends in a download, so the trail saves itself with no save call."""
    runner = runner_for(browser, store)
    outcome = run(
        runner,
        f"go {demo_server}/\n"
        'fill label "Email" "finance@acme.com"\n'
        'fill label "Password" "hunter2"\n'
        'click button "Sign in"\n'
        'click link "September 2026"\n'
        'click link "Download"\n',
    )
    assert outcome.ok, outcome.text()
    assert outcome.saved is not None
    assert len(outcome.saved.steps) == 6
    assert "hunter2" not in str(outcome.saved.to_dict()), "a password reached memory"

    replay = Executor(store, browser).run(domain_of(demo_server), task=TASK)
    assert replay.ok, replay


def test_a_program_that_reads_saves_its_answer(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    runner = runner_for(browser, store, "the price of the first book")
    outcome = run(
        runner,
        f"go {demo_server}/books\n"
        'click css "article.book h3 a" first\n'
        'read css "#price" as price\n',
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers == {"price": "£40.00"}
    assert "price = £40.00" in outcome.text()
    assert 'saved "the price of the first book"' in outcome.text()

    replay = Executor(store, browser).run(
        domain_of(demo_server), task="the price of the first book"
    )
    assert replay.answers == {"price": "£40.00"}


# ------------------------------------------------------------------- stop and continue


def test_a_failing_line_stops_keeps_the_good_part_and_shows_the_page(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    runner = runner_for(browser, store)
    first = run(
        runner,
        f"go {demo_server}/\n"
        'fill label "Email" "finance@acme.com"\n'
        'click button "Log me in"\n'
        'click link "September 2026"\n',
    )
    assert not first.ok
    assert first.stopped_at is not None and first.stopped_at.line == 3
    assert [step.line for step in first.passed] == [1, 2]
    assert [step.line for step in first.not_run] == [4]
    assert first.view is not None and "Sign in" in first.view.text, "no page to fix it from"
    text = first.text()
    assert text.startswith('stopped at line 3 of 4: click button "Log me in" -> nothing on')
    assert "done (kept in the draft): 1 go" in text

    draft = store.load_draft(domain_of(demo_server), TASK)
    assert draft is not None and len(draft.steps) == 2

    second = run(
        runner,
        'fill label "Password" "hunter2"\n'
        'click button "Sign in"\n'
        'click link "September 2026"\n'
        'click link "Download"\n',
    )
    assert second.ok, second.text()
    assert second.saved is not None and len(second.saved.steps) == 6
    assert store.load_draft(domain_of(demo_server), TASK) is None, "the draft outlived its trail"


def test_a_ref_from_a_page_that_has_gone_is_refused(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    runner = runner_for(browser, store)
    run(runner, f"go {demo_server}/\nlook")
    sign_in = ref_of(runner, "Sign in")

    outcome = run(runner, f"go {demo_server}/books\nclick {sign_in}")

    assert outcome.stopped_at is not None and outcome.stopped_at.line == 2
    assert "is from the page before" in outcome.reason


# ------------------------------------------------------------------- strict and by place


def test_an_ambiguous_target_is_refused_with_its_matches(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    runner = runner_for(browser, store, "open a book")
    outcome = run(runner, f'go {demo_server}/books\nclick css "article.book h3 a"')
    assert not outcome.ok
    assert outcome.next_step.startswith("add first, last or nth N") or "first" in outcome.reason


def test_first_is_stored_by_place_and_replays_on_the_new_first_row(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Learned while "It's Only the Himalayas" was first; replayed after the list reversed,
    it must open what is first THEN. Stored by title, it would open the old book again."""
    task = "the title of the first book"
    runner = runner_for(browser, store, task)
    run(runner, f"go {demo_server}/books\nlook")
    first_link = ref_of(runner, "It's Only the Himalayas")
    outcome = run(runner, f'click {first_link} first\nread css "#title" as title')
    assert outcome.ok, outcome.text()
    assert outcome.answers["title"] == "It's Only the Himalayas"
    assert "(by place)" in outcome.text()

    replay = Executor(store, browser).run(
        domain_of(demo_server), task=task, start_url=f"{demo_server}/books?order=b"
    )
    assert replay.answers["title"] == "Vagabonding"


def test_first_on_a_ref_that_is_not_first_is_refused(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    runner = runner_for(browser, store, "open a book")
    run(runner, f"go {demo_server}/books\nlook")
    second = ref_of(runner, "Full Moon over Noah's Ark")

    outcome = run(runner, f"click {second} first")

    assert "is number 2 of 4 in its list, not first" in outcome.reason


# ------------------------------------------------------------------- risky steps


def test_an_unmarked_payment_is_not_made(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    placed = ORDERS["placed"]
    runner = runner_for(browser, store, "pay for the order")
    outcome = run(runner, f'go {demo_server}/shop\nclick button "Pay now"')

    assert not outcome.ok
    assert "submits a form that sends data (POST)" in outcome.reason
    assert "click!" in outcome.next_step
    assert ORDERS["placed"] == placed, "the payment ran without being marked"


def test_a_marked_payment_runs_once_and_a_retry_does_not_pay_again(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    placed = ORDERS["placed"]
    runner = runner_for(browser, store, "pay for the order")
    first = run(
        runner,
        f'go {demo_server}/shop\nclick! button "Pay now"\nread css "#no-such-receipt" as receipt',
    )
    assert not first.ok, "the read was meant to fail"
    assert ORDERS["placed"] == placed + 1

    retry = run(runner, 'click! button "Pay now"\nread css "#receipt" as receipt')

    assert not retry.ok
    assert "does not run twice" in retry.reason
    assert ORDERS["placed"] == placed + 1, "a retry paid a second time"


def test_a_search_form_is_not_risky_even_when_its_button_says_submit(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    runner = runner_for(browser, store, "search the shop")
    outcome = run(
        runner,
        f'go {demo_server}/shop\nfill label "Search" "atlas"\nclick button "Submit"\n'
        'read css "h1" as heading',
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers["heading"] == "Results for atlas"


def test_a_sign_in_form_is_not_risky(browser: Browser, store: DejoStore, demo_server: str) -> None:
    """Nearly every sign-in POSTs. Stopping there would cost every learning run a turn."""
    runner = runner_for(browser, store)
    outcome = run(runner, f'go {demo_server}/\nclick button "Sign in"\nlook')
    assert outcome.ok, outcome.text()


def test_a_saved_risky_step_is_named_in_the_reply(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    runner = runner_for(browser, store, "pay for the order")
    outcome = run(
        runner, f'go {demo_server}/shop\nclick! button "Pay now"\nread css "#receipt" as receipt'
    )
    assert outcome.ok, outcome.text()
    assert outcome.saved is not None and outcome.saved.steps[1].risky
    assert "this task does step 2" in outcome.text()


# ------------------------------------------------------------------- detours and drafts


def test_a_wrong_turn_and_back_is_dropped_from_the_trail(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    runner = runner_for(browser, store, "the price of the first book")
    outcome = run(
        runner,
        f"go {demo_server}/books\n"
        'click link "Full Moon over Noah\'s Ark"  # the wrong book\n'
        "back\n"
        'click css "article.book h3 a" first\n'
        'read css "#price" as price\n',
    )
    assert outcome.ok, outcome.text()
    assert outcome.saved is not None
    assert [step.action for step in outcome.saved.steps] == ["goto", "click", "read"]
    assert "the wrong book" in " ".join(outcome.dropped)


def test_a_draft_survives_a_new_session_and_resumes(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    first = runner_for(browser, store)
    run(first, f'go {demo_server}/\nfill label "Email" "finance@acme.com"\nclick button "No"')

    browser.page.goto("about:blank")
    later = runner_for(browser, store)
    said = later.resume(domain_of(demo_server))
    assert said.startswith("draft: 2 steps kept")

    outcome = run(
        later,
        'fill label "Password" "hunter2"\nclick button "Sign in"\n'
        'click link "September 2026"\nclick link "Download"',
    )
    assert outcome.ok, outcome.text()
    assert outcome.saved is not None and len(outcome.saved.steps) == 6


def test_a_program_with_no_read_shows_the_page_and_says_how_to_finish(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    runner = runner_for(browser, store, "open the books")
    outcome = run(runner, f"go {demo_server}/books")
    assert outcome.ok and outcome.saved is None
    assert outcome.view is not None
    assert "Answering from this view saves nothing" in outcome.next_step


def test_done_saves_a_task_that_reads_nothing(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    runner = runner_for(browser, store, "open the books")
    outcome = run(runner, f"go {demo_server}/books", done=True)
    assert outcome.saved is not None


# ------------------------------------------------------------------- detour rules, no browser


def entry(action: str, before: str, after: str, intent: str = "") -> TraceEntry:
    return TraceEntry(intent=intent or action, action=action, url_before=before, url_after=after)


def test_back_drops_itself_and_the_step_it_undid() -> None:
    trace = [
        entry("goto", "", "/books"),
        entry("click", "/books", "/books/1", "wrong book"),
        entry("back", "/books/1", "/books"),
        entry("click", "/books", "/books/0", "right book"),
    ]
    kept, dropped = drop_detours(trace)
    assert [e.intent for e in kept] == ["goto", "right book"]
    assert dropped == ["wrong book", "back"]


def test_a_goto_drops_the_wandering_before_it() -> None:
    trace = [
        entry("goto", "", "/"),
        entry("click", "/", "/a", "menu"),
        entry("click", "/a", "/b", "submenu"),
        entry("goto", "/b", "/target"),
    ]
    kept, dropped = drop_detours(trace)
    assert [e.intent for e in kept] == ["goto"]
    assert dropped == ["goto", "menu", "submenu"]


def test_a_goto_never_drops_a_step_that_changed_something() -> None:
    trace = [
        entry("goto", "", "/"),
        entry("fill", "/", "/", "type the email"),
        entry("click", "/", "/a", "menu"),
        entry("goto", "/a", "/target"),
    ]
    kept, _ = drop_detours(trace)
    assert [e.intent for e in kept] == ["goto", "type the email", "goto"]


@pytest.mark.parametrize("action", ["fill", "select", "check"])
def test_state_changes_stop_the_drop(action: str) -> None:
    trace = [entry(action, "/", "/"), entry("goto", "/", "/x")]
    kept, dropped = drop_detours(trace)
    assert len(kept) == 2 and dropped == []


# ------------------------------------------------- what the 21 Oct benchmark found


def test_an_ambiguous_css_says_first_not_the_old_syntax(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The old read tool's hint (`" >> nth=0"`) leaked into programs and was copied back."""
    runner = runner_for(browser, store, "open a book")
    outcome = run(runner, f'go {demo_server}/books\nread css "p.price" as price')
    assert "4 matches" in outcome.reason
    assert ">> nth" not in outcome.text()
    assert outcome.next_step.startswith("add first, last or nth N")


def test_a_control_the_site_redrew_is_found_again_by_role_and_name(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Seen on GitHub: the page redrew a part after the view was printed, so the ref died."""
    runner = runner_for(browser, store, "open the first book")
    run(runner, f"go {demo_server}/books\nlook")
    himalayas = ref_of(runner, "It's Only the Himalayas")
    browser.page.evaluate(
        "() => { const a = document.querySelector('article h3 a'); a.replaceWith(a.cloneNode(true)); }"
    )

    outcome = run(runner, f'click {himalayas}\nread css "#title" as title')

    assert outcome.ok, outcome.text()
    assert outcome.answers["title"] == "It's Only the Himalayas"


def test_a_stop_says_not_to_resend_the_lines_that_ran(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """An agent resent a whole program, and an old ref pressed a different element."""
    runner = runner_for(browser, store, "open a book")
    outcome = run(runner, f'go {demo_server}/books\nclick button "Nope"')
    assert "Do not send lines 1-1 again" in outcome.next_step


def test_a_read_that_could_never_replay_is_not_saved(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """A paragraph with no id among look-alike paragraphs: today it gets a body-anchored
    path, and if no path at all can be built the read stops rather than saving a trail
    that breaks on every replay."""
    runner = runner_for(browser, store, "read the second line")
    browser.page.goto(f"{demo_server}/books")
    browser.page.evaluate("() => { document.body.innerHTML = '<p>one</p><p>two</p>'; }")
    run(runner, "look")
    second = ref_of_text(runner, "two")
    outcome = run(runner, f"read {second} as line")
    assert outcome.ok and outcome.saved is not None
    assert outcome.saved.steps[-1].locators, "a saved read must be findable again"


def ref_of_text(runner: Runner, text: str) -> str:
    assert runner._view is not None
    for ref, target in runner._view.targets.items():
        if text in (target.node.trailing, target.node.name):
            return ref
    raise AssertionError(f"no line saying {text!r}")


def test_a_read_still_answers_when_the_value_changes(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """GitHub, 21 Oct: the read was stored by the link's name "Open (172)" and by a React id
    made up for that page load, so the replay found nothing once the count moved."""
    task = "count the open tickets"
    runner = runner_for(browser, store, task)
    run(runner, f"go {demo_server}/tickets?open=3\nlook")
    count = ref_of(runner, "Open (3)")
    learned = run(runner, f"read {count} as open")
    assert learned.ok, learned.text()
    stored = [loc.value for loc in learned.saved.steps[-1].locators]
    assert stored and not any("3" in value and "Open" in value for value in stored), stored
    assert not any("_r_" in value for value in stored), stored

    replay = Executor(store, browser).run(
        domain_of(demo_server), task=task, start_url=f"{demo_server}/tickets?open=5"
    )

    assert replay.ok, replay.reason
    assert replay.answers["open"] == "Open (5)"
