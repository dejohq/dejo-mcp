"""Running programs: many steps in one call, stopping at the first that fails, saving itself.

Every test drives the real demo site through a real browser, because what matters here is
what a program leaves behind: the trail replay will follow, the draft a later call resumes,
and how many times the shop's "Pay now" really ran.
"""

from __future__ import annotations

import re

import pytest
from tests.demo_site.app import ORDERS

from dejo import program, view
from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.models import Locator
from dejo.operations import Session, TraceEntry
from dejo.runner import RAW_FROM_LINES, Outcome, Runner, _raw_from, drop_detours
from dejo.snapshot import Element
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


# ------------------------------------------------------------------- repair in place

INVOICE_AND_MONTH = "download the invoice and say its month"


def learn_invoice_and_month(browser: Browser, store: DejoStore, demo_server: str):
    """Seven steps whose sixth is the one variant b breaks, so a fix has a step after it."""
    outcome = run(
        runner_for(browser, store, INVOICE_AND_MONTH),
        f"go {demo_server}/\n"
        'fill label "Email" "finance@acme.com"\n'
        'fill label "Password" "hunter2"\n'
        'click button "Sign in"\n'
        'click link "September 2026"\n'
        'click link "Download"\n'
        'read css "h1" as month\n',
    )
    assert outcome.ok and outcome.saved is not None, outcome.text()
    domain = domain_of(demo_server)
    # One clean replay, so the old ways have a record to be kept as backups by.
    assert Executor(store, browser).run(domain, task=INVOICE_AND_MONTH).ok
    broken = Executor(store, browser).run(
        domain, task=INVOICE_AND_MONTH, start_url=f"{demo_server}/?variant=b"
    )
    assert broken.repair is not None and broken.repair.step_index == 6
    return domain, broken


def fixer(browser: Browser, store: DejoStore, domain: str, task: str, broken) -> Runner:
    runner = runner_for(browser, store, task)
    playbook = store.load_playbook(domain, task)
    runner.fix_from(domain, playbook, broken.repair.step_index, answers=broken.answers)
    return runner


def test_one_line_repairs_the_step_and_replays_the_rest_in_the_same_call(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    domain, broken = learn_invoice_and_month(browser, store, demo_server)
    runner = fixer(browser, store, domain, INVOICE_AND_MONTH, broken)

    fixed = run(runner, 'click link "Get PDF"')

    assert fixed.ok and fixed.repaired is not None, fixed.text()
    assert fixed.text().startswith("repaired step 6 of 7"), fixed.text()
    assert "done: steps 7-7 replayed" in fixed.text()
    assert fixed.answers == {"month": "September 2026"}
    step = store.load_playbook(domain, INVOICE_AND_MONTH).steps[5]
    assert step.repairs == 1
    assert step.locators[0].value == "href=/invoices/2026-09/download", step.locators[0]
    kept = {loc.value for loc in step.locators}
    assert "href=/invoices/2026-09/file" in kept, "the way that had worked is the backup"
    assert "#download-btn" not in kept, "a way that never once worked is dropped"


def test_after_a_fix_both_the_new_site_and_the_old_one_replay(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The old ways stay as backups, so a site that moves back costs nothing either."""
    domain, broken = learn_invoice_and_month(browser, store, demo_server)
    run(fixer(browser, store, domain, INVOICE_AND_MONTH, broken), 'click link "Get PDF"')

    for variant in ("b", "a"):
        again = Executor(store, browser).run(
            domain, task=INVOICE_AND_MONTH, start_url=f"{demo_server}/?variant={variant}"
        )
        assert again.ok, (variant, again.reason)
        assert again.answers["month"] == "September 2026"


def test_a_fixed_read_gets_a_check_that_holds(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """A read is checked by its element's css path. Kept after a fix, that check named the
    element that had gone, and the very next replay called the fixed step broken."""
    task = "pay and read the receipt"
    placed = ORDERS["placed"]
    learned = run(
        runner_for(browser, store, task),
        f'go {demo_server}/shop\nclick! button "Pay now"\nread css "#receipt" as receipt',
    )
    assert learned.ok, learned.text()
    domain = domain_of(demo_server)
    broken = Executor(store, browser).run(
        domain, task=task, start_url=f"{demo_server}/shop?variant=b"
    )
    assert broken.repair is not None and broken.repair.step_index == 3
    assert ORDERS["placed"] == placed + 2

    fixed = run(fixer(browser, store, domain, task, broken), 'read css "#order-receipt" as receipt')

    assert fixed.ok and fixed.repaired is not None, fixed.text()
    assert ORDERS["placed"] == placed + 2, "the fix paid again"
    assert fixed.answers["receipt"] == f"Order {placed + 2} placed"
    again = Executor(store, browser).run(
        domain, task=task, start_url=f"{demo_server}/shop?variant=b"
    )
    assert again.ok, again.reason


def test_several_lines_replace_the_steps_from_the_broken_one(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    domain, broken = learn_invoice_and_month(browser, store, demo_server)
    runner = fixer(browser, store, domain, INVOICE_AND_MONTH, broken)

    replaced = run(runner, 'click link "Get PDF"\nread css "h1" as month')

    assert replaced.ok and replaced.repaired is None, replaced.text()
    assert replaced.saved is not None and len(replaced.saved.steps) == 7
    assert replaced.saved.steps[5].repairs == 0, "a replaced step is new, not repaired"


def test_one_line_of_another_action_is_not_taken_as_a_fix(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    domain, broken = learn_invoice_and_month(browser, store, demo_server)
    runner = fixer(browser, store, domain, INVOICE_AND_MONTH, broken)

    other = run(runner, 'read css "h1" as month')

    assert other.repaired is None
    assert other.saved is not None and len(other.saved.steps) == 6, other.text()


# ------------------------------------------------------------------- the query part of an address


def test_a_site_that_serves_every_page_at_one_path_replays_the_right_link(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """catalog.ccv.edu, 22 Oct: every menu link is /content.php?navoid=N. The trail stored
    "Courses" by that path, replay clicked the first menu link, and the check, also only the
    path, passed on the wrong page."""
    task = "the heading of the courses page"
    learned = run(
        runner_for(browser, store, task),
        f'go {demo_server}/catalog\nclick link "Courses"\nread css "#heading" as heading',
    )
    assert learned.ok, learned.text()
    step = learned.saved.steps[1]
    assert "href=/catalog" not in [loc.value for loc in step.locators], step.locators
    assert step.postcondition.value == "/catalog?nav=2", step.postcondition

    replay = Executor(store, browser).run(domain_of(demo_server), task=task)

    assert replay.ok, replay.reason
    assert replay.answers["heading"] == "Courses"


def test_a_url_that_leaves_out_part_of_the_trail_start_does_not_replace_it(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """scrapethissite, 22 Oct: a trail that starts on page 5 was replayed with page 1's
    address, read page 1's first team and said done."""
    task = "the first book in reverse order"
    learned = run(
        runner_for(browser, store, task),
        f'go {demo_server}/books?order=b\nread css "article.book h3 a" first as title',
    )
    assert learned.ok, learned.text()

    replay = Executor(store, browser).run(
        domain_of(demo_server), task=task, start_url=f"{demo_server}/books"
    )

    assert replay.ok, replay.reason
    assert replay.answers["title"] == "Vagabonding"


def test_a_call_that_ends_with_look_says_how_to_keep_the_answer(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """21-22 Oct: "look" ended a call, the agent read the answer off that view, and nothing
    was saved."""
    outcome = run(runner_for(browser, store, "the price"), f"go {demo_server}/books/0\nlook")

    assert outcome.ok and outcome.saved is None
    assert "that read is what Dejo keeps" in outcome.next_step


# ------------------------------------------------------------------- walls and bare keys


def test_a_human_check_stops_the_first_call_and_keeps_nothing(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """22 Oct: Cloudflare's check page was shown as if it were the site, the agent sent
    `wait` three times, and the waits went into the draft."""
    runner = runner_for(browser, store, "the bus fare")
    outcome = run(runner, f"go {demo_server}/challenge\nlook")

    assert not outcome.ok
    assert "human check" in outcome.reason
    assert "dejo_login" in outcome.next_step
    assert runner.session.trace == [], "nothing done on a check page is a step"
    assert store.load_draft(domain_of(demo_server), "the bus fare") is None


def test_a_refusal_is_not_called_a_wrong_address(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = run(runner_for(browser, store, "the decoy date"), f"go {demo_server}/refused\nlook")

    assert not outcome.ok
    assert "refused this browser (HTTP 403)" in outcome.reason
    assert "do not try other addresses" in outcome.next_step


def test_a_bare_press_enter_replays(browser: Browser, store: DejoStore, demo_server: str) -> None:
    """22 Oct: `press Enter` names no element, and replay only knew how to find elements,
    so every trail with one broke at that step."""
    task = "search the shop for atlas"
    learned = run(
        runner_for(browser, store, task),
        f'go {demo_server}/shop\nfill label "Search" "atlas"\npress Enter\n'
        'read css "h1" as heading',
    )
    assert learned.ok, learned.text()

    replay = Executor(store, browser).run(domain_of(demo_server), task=task)

    assert replay.ok, replay.reason
    assert replay.answers["heading"] == "Results for atlas"


# ------------------------------------------------------------------- re-run findings, 23 Oct


def test_a_look_in_the_middle_is_skipped_not_refused(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = run(
        runner_for(browser, store, "the price"),
        f'go {demo_server}/books/0\nlook price\nread css "#price" as price',
    )
    assert outcome.ok and outcome.saved is not None, outcome.text()


def test_a_read_of_the_whole_page_is_refused(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """23 Oct: `read css "body"` was saved as the answer, and every replay handed back the
    whole page."""
    outcome = run(
        runner_for(browser, store, "the price"),
        f'go {demo_server}/books/0\nread css "body" as page',
    )
    assert not outcome.ok and outcome.saved is None
    assert "whole page" in outcome.reason


def test_a_saved_read_says_what_replays_will_answer_and_can_be_replaced(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """23 Oct: the saved read was the wrong column; the agent answered from the view and
    every replay answered the wrong number."""
    runner = runner_for(browser, store, "the price")
    first = run(runner, f'go {demo_server}/books/0\nread css "#title" as price')
    assert "every replay will answer price = It's Only the Himalayas" in first.next_step

    fixed = run(runner, 'read css "#price" as price')

    reads = [step for step in fixed.saved.steps if step.action == "read"]
    assert [step.intent for step in reads] == ["price"], "the later read replaces the earlier"
    replay = Executor(store, browser).run(domain_of(demo_server), task="the price")
    assert replay.answers == {"price": "£40.00"}


def test_a_trail_that_did_not_open_its_page_gets_a_start(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """23 Oct: a slow site's first `go` failed, the agent went on from the page anyway, and
    the trail began with a click, so every replay started on a blank page."""
    task = "the heading of the courses page"
    browser.goto(f"{demo_server}/catalog")
    learned = run(
        runner_for(browser, store, task), 'click link "Courses"\nread css "#heading" as heading'
    )
    assert learned.ok, learned.text()
    assert learned.saved.steps[0].action == "goto"
    assert learned.saved.steps[0].value == f"{demo_server}/catalog"

    browser.goto("about:blank")
    replay = Executor(store, browser).run(domain_of(demo_server), task=task)
    assert replay.ok, replay.reason
    assert replay.answers["heading"] == "Courses"


def typed(css: str, before: str = "/shop", after: str = "/shop", intent: str = "") -> TraceEntry:
    field = Element(ref="e1", role="textbox", name="Search", css=css)
    return TraceEntry(
        intent=intent or "fill", action="fill", element=field, url_before=before, url_after=after
    )


def test_a_field_typed_into_again_drops_the_first_try() -> None:
    """23 Oct, a shop: the same search typed twice with a click between, all kept."""
    trace = [
        entry("goto", "", "/shop"),
        typed("#q", intent="first try"),
        entry("press", "/shop", "/shop", "enter"),
        entry("click", "/shop", "/shop", "the heading"),
        typed("#q", intent="second try"),
        entry("press", "/shop", "/shop", "enter again"),
    ]
    kept, dropped = drop_detours(trace)
    assert [e.intent for e in kept] == ["goto", "second try", "enter again"]
    assert dropped == ["first try", "enter", "the heading"]


def test_a_field_typed_again_after_moving_on_is_kept() -> None:
    trace = [
        typed("#q", intent="search"),
        entry("click", "/shop", "/shop/search", "result page"),
        typed("#q", "/shop/search", "/shop/search", intent="search again"),
    ]
    kept, _ = drop_detours(trace)
    assert len(kept) == 3


# ------------------------------------------------------------------- a banner seen once


def _learn_past_the_banner(browser: Browser, store: DejoStore, demo_server: str) -> None:
    outcome = run(
        runner_for(browser, store, "the headline"),
        f'go {demo_server}/news\nclick button "Accept cookies"\nread css "#headline" as headline',
    )
    assert outcome.ok, outcome.text()


def test_a_banner_shown_again_is_cleared_again(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The click removes its own button, so "the button is still there" could never hold."""
    _learn_past_the_banner(browser, store, demo_server)
    browser._context.clear_cookies()  # a new visitor: the banner is back

    replay = Executor(store, browser).run(domain_of(demo_server), task="the headline")

    assert replay.ok, replay.reason
    assert replay.skipped == []
    assert replay.answers == {"headline": "Rates hold for September"}


def test_a_banner_not_shown_is_skipped_and_not_called_drift(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Bench T07: the banner was accepted once, so every later replay broke at its click."""
    _learn_past_the_banner(browser, store, demo_server)

    replay = Executor(store, browser).run(domain_of(demo_server), task="the headline")

    assert replay.ok, replay.reason
    assert replay.skipped == ['step 2 (click button "Accept cookies")']
    assert replay.answers == {"headline": "Rates hold for September"}
    saved = store.load_playbook(domain_of(demo_server), "the headline")
    assert saved is not None
    assert all(locator.misses == 0 for locator in saved.steps[1].locators)


def test_a_missing_click_the_next_step_needs_still_breaks(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Skipping is only for a step the trail can do without."""
    _learn_past_the_banner(browser, store, demo_server)
    trail = store.load_playbook(domain_of(demo_server), "the headline")
    assert trail is not None
    trail.steps[2].locators = [Locator("css", "#not-there")]
    store.save_playbook(trail)

    replay = Executor(store, browser).run(domain_of(demo_server), task="the headline")

    assert not replay.ok
    assert replay.repair is not None and replay.repair.step_index == 2


def _refused(browser: Browser, store: DejoStore, demo_server: str, line: str) -> str:
    """Why `line` was refused on the launch page, or "" when it ran."""
    outcome = run(runner_for(browser, store, "launch"), f"go {demo_server}/launch\n{line}")
    return "" if outcome.ok else outcome.reason


def test_a_link_named_submit_only_opens_a_page(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """mcpmarket.com: the footer link to /submit was refused as risky. A link opens a page."""
    assert _refused(browser, store, demo_server, 'click link "Submit"') == ""
    assert browser.page.url.endswith("/submit")


def test_a_link_that_deletes_and_a_button_that_sends_are_still_risky(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    deletes = _refused(browser, store, demo_server, 'click link "Delete launch"')
    assert 'is "delete"' in deletes
    assert 'is "send"' in _refused(browser, store, demo_server, 'click button "Send"')


def test_a_tab_named_publish_only_switches_the_view(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """lobehub.com/mcp: `click tab "Publish"` was refused as risky. A tab shows a panel."""
    assert _refused(browser, store, demo_server, 'click tab "Publish"') == ""
    assert browser.page.locator("#panel").inner_text() == "Publish view"


def test_removing_a_tag_chip_from_an_unsent_form_is_not_risky(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """launchit.site: each "Remove javascript" chip needed its own `click!` call."""
    assert _refused(browser, store, demo_server, 'click button "Remove javascript"') == ""
    assert browser.page.locator("#chip-js").count() == 0


def test_removing_a_row_outside_any_form_is_still_risky(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    said = _refused(browser, store, demo_server, 'click button "Remove"')
    assert 'is "remove"' in said


# ------------------------------------------------------------------- dropdowns


def test_a_hidden_dropdown_behind_the_sites_own_menu_is_chosen_from(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """fewservers.com: `select` on the Category dropdown timed out, by its words and by its
    label, while a `js` line that set the value worked. The real <select> was hidden behind
    the site's own menu, and Playwright waited for it to be seen."""
    runner = runner_for(browser, store, "list a tool")
    outcome = run(
        runner,
        f'go {demo_server}/directory\nselect label "Category" "AI agents"\n'
        'read css "#picked" as category',
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers == {"category": "AI agents"}

    replay = Executor(store, browser).run(domain_of(demo_server), task="list a tool")
    assert replay.ok, replay.reason


def test_a_disabled_dropdown_says_so(browser: Browser, store: DejoStore, demo_server: str) -> None:
    outcome = run(
        runner_for(browser, store, "pick a region"),
        f'go {demo_server}/directory\nselect css "#region" "Asia"',
    )
    assert not outcome.ok
    assert "disabled" in outcome.reason
    assert "Timeout" not in outcome.reason


# ------------------------------------------------------------------- styled checkboxes


def test_a_checkbox_its_own_label_covers_is_ticked_through_the_label(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """agenticskills.io: `check` failed with "something covers it: <label ...>". The cover
    was the checkbox's own label, which is what a person clicks."""
    runner = runner_for(browser, store, "pick clients")
    outcome = run(
        runner,
        f'go {demo_server}/clients\ncheck checkbox "Claude Code"\ncheck label "Cursor"\n'
        'read css "#chosen" as chosen',
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers == {"chosen": "claude, cursor"}

    browser.page.reload()
    replay = Executor(store, browser).run(domain_of(demo_server), task="pick clients")
    assert replay.ok, replay.reason
    assert replay.answers == {"chosen": "claude, cursor"}


# ------------------------------------------------------------------- refs


def test_a_ref_in_a_folded_row_can_be_used(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """agenticskills.io: rows 4-7 of a folded group were refused ("there is no e72 in the
    latest view"), even right after `look g2`, though the page had them."""
    runner = runner_for(browser, store, "fourth")
    shown = run(runner, f"go {demo_server}/books\nlook").view
    assert shown is not None and "+1 more" in shown.text
    raw, _ = browser.raw_snapshot()
    last = re.search(r'link "Vagabonding" \[ref=(e\d+)\]', raw)
    assert last is not None and f"{last.group(1)} " not in shown.text, "the row is folded away"

    outcome = run(runner, f'click {last.group(1)}\nread css "#title" as title')

    assert outcome.ok, outcome.text()
    assert outcome.answers == {"title": "Vagabonding"}


# ------------------------------------------------------------------- look raw from


def _page_with_a_form_and_a_long_footer() -> str:
    links = "\n".join(f'    - link "Footer link {n}" [ref=e{100 + n}]' for n in range(200))
    return (
        "- main [ref=e1]:\n"
        '  - heading "Submit" [level=1] [ref=e2]\n'
        "  - form [ref=e3]:\n"
        '    - textbox "Name" [ref=e4]\n'
        '    - textbox "Website" [ref=e5]\n'
        '    - button "Submit" [ref=e6]\n'
        '  - paragraph [ref=e7]: "Reviewed within a week"\n'
        "- contentinfo [ref=e8]:\n"
        f"{links}\n"
    )


def test_look_raw_from_a_ref_stops_at_the_end_of_its_section() -> None:
    """mcpserver.dev: `look raw from eN` printed the whole footer, ~200 lines, when only the
    form was wanted."""
    raw = _page_with_a_form_and_a_long_footer()
    seen = view.render(raw, url="https://example.com/", title="Submit")

    shown = _raw_from(raw, seen, "e4")

    assert 'textbox "Name"' in shown and 'button "Submit"' in shown
    assert "Footer link" not in shown
    assert shown.endswith("the page goes on: look raw from e7")


def test_look_raw_from_a_ref_with_no_section_is_cut_and_says_where_to_go_on() -> None:
    raw = _page_with_a_form_and_a_long_footer()
    seen = view.render(raw, url="https://example.com/", title="Submit")

    shown = _raw_from(raw, seen, "e101")

    assert "Footer link 1" in shown
    assert len(shown.splitlines()) <= RAW_FROM_LINES + 1
    assert re.search(r"\+ more: look raw from e\d+$", shown)


def test_a_new_line_written_in_a_fill_breaks_the_line_in_a_text_area(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """launchingnext.com: `\\n` in a description went in as a backslash and an n."""
    outcome = run(
        runner_for(browser, store, "describe the tool"),
        f'go {demo_server}/directory\nfill label "About it" "One line.\\nAnother line."\n'
        'fill label "Tool name" "a\\nb"',
    )
    assert outcome.ok, outcome.text()
    assert browser.page.input_value("#about") == "One line.\nAnother line."
    assert browser.page.input_value("#tool") == "a\\nb", "a one-line box keeps what was written"


def test_a_read_of_a_field_reads_what_it_holds(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """launchingnext.com: `read e58` on a box holding text said "the read found nothing
    there". A field's words are its value; a dropdown's are the option on show."""
    outcome = run(
        runner_for(browser, store, "what was entered"),
        f'go {demo_server}/directory\nfill label "Tool name" "Dejo"\n'
        'select label "Category" "AI agents"\n'
        'read label "Tool name" as tool\nread css "#category" as category',
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers == {"tool": "Dejo", "category": "AI agents"}


def test_wait_waits_for_what_is_not_there_yet(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """saashub.com: `wait css "..."` failed at once with "nothing on this page matches"
    while the list still said "Loading..."."""
    outcome = run(
        runner_for(browser, store, "the first category"),
        f'go {demo_server}/categories\nwait css "li.choice"\nwait text "AI agents"\n'
        'read css "li.choice" first as first',
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers == {"first": "Developer tools"}


# ------------------------------------------------------------------- one long text


def test_a_long_plain_text_page_is_read_by_the_part_that_answers(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """market.lobehub.com/s/publish-mcp: a 48k markdown file was one element, `read e1` was
    refused as the whole page, and there was no smaller element to read."""
    runner = runner_for(browser, store, "the price of publishing")
    run(runner, f"go {demo_server}/publish.md\nlook")
    whole = run(runner, "read e1 as guide")
    assert not whole.ok
    assert 'read passage "' in whole.next_step

    outcome = run(runner, 'read passage "Pricing" e1 as pricing')

    assert outcome.ok, outcome.text()
    assert outcome.answers == {
        "pricing": "## Pricing\n\nPublishing is free for open source servers."
    }
    replay = Executor(store, browser).run(domain_of(demo_server), task="the price of publishing")
    assert replay.ok, replay.reason
    assert replay.answers["pricing"].endswith("free for open source servers.")


def test_look_words_shows_the_passages_of_a_long_text(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    runner = runner_for(browser, store, "zz")
    outcome = run(runner, f"go {demo_server}/publish.md\nlook open source")
    assert outcome.view is not None
    assert "Publishing is free for open source servers." in outcome.view.text


def test_a_click_into_a_single_page_app_shows_the_page_it_drew(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """lobehub.com: a click into a listing returned while only the footer was drawn; the
    next look had the page."""
    outcome = run(
        runner_for(browser, store, "zz"), f'go {demo_server}/spa\nclick link "Dejo server"'
    )
    assert outcome.ok, outcome.text()
    assert outcome.view is not None
    assert "A browser your agent remembers." in outcome.view.text


def test_an_icon_button_says_what_its_icon_is(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """devhunt.org: the GitHub and Google sign-in buttons were bare `button` lines, in the
    view and in raw."""
    shown = run(runner_for(browser, store, "zz"), f"go {demo_server}/sign-up\nlook").view
    assert shown is not None
    assert re.search(r"e\d+ (button )?\[icon: github\]", shown.text), shown.text
    assert re.search(r"e\d+ (button )?\[icon: google\]", shown.text)
    assert re.search(r"e\d+ (button )?\[icon, no name\]", shown.text)


def test_a_nameless_button_is_named_by_the_words_it_shows_first() -> None:
    """devhunt.org: Playwright printed "Continue with Github" as a bare `button`."""
    from dejo.browser import _icon_name

    assert _icon_name("Continue with Github", "", "lucide-github") == 'shows "Continue with Github"'
    assert _icon_name("", "Close dialog", "") == "icon: Close dialog"
    assert _icon_name("", "", "lucide lucide-github h-5") == "icon: github"
    assert _icon_name("", "", "#000") == ""


# ------------------------------------------------------------------- uploads


def test_an_upload_the_page_refused_says_so(
    browser: Browser, store: DejoStore, demo_server: str, tmp_path
) -> None:
    """devhunt.org: `upload` onto "Select an image" said done, and nothing on the page
    changed: the file box had thrown the file away."""
    text = tmp_path / "logo.txt"
    text.write_text("not a picture", encoding="utf-8")
    picture = tmp_path / "logo.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n")
    runner = runner_for(browser, store, "set the logo")

    refused = run(runner, f'go {demo_server}/logo\nupload button "Select an image" "{text}"')
    assert not refused.ok
    assert "did not keep" in refused.reason and "image/png" in refused.reason

    taken = run(
        runner, f'upload button "Select an image" "{picture}"\nread css "#chosen" as chosen'
    )
    assert taken.ok, taken.text()
    assert taken.answers == {"chosen": "logo.png"}


def test_an_upload_onto_something_that_opens_no_chooser_says_so(
    browser: Browser, store: DejoStore, demo_server: str, tmp_path
) -> None:
    picture = tmp_path / "logo.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n")
    outcome = run(
        runner_for(browser, store, "set the logo"),
        f'go {demo_server}/logo\nupload css "#chosen" "{picture}"',
    )
    assert not outcome.ok
    assert "opened no file chooser" in outcome.reason


# ------------------------------------------------------------------- slow pages


def _slow_snapshots(browser: Browser, monkeypatch, failures: int) -> None:
    """The next `failures` snapshots time out, as on a page too heavy to draw in time."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    real, left = browser._aria_snapshot, [failures]

    def slow() -> str:
        if left[0]:
            left[0] -= 1
            raise PlaywrightTimeout("Locator.aria_snapshot: Timeout 15000ms exceeded.")
        return real()

    monkeypatch.setattr(browser, "_aria_snapshot", slow)


def test_a_page_too_slow_to_draw_once_is_looked_at_again(
    browser: Browser, store: DejoStore, demo_server: str, monkeypatch
) -> None:
    """fazier.com: `Locator.aria_snapshot: Timeout 15000ms exceeded.` reached the agent."""
    runner = runner_for(browser, store, "zz")
    run(runner, f"go {demo_server}/books")
    _slow_snapshots(browser, monkeypatch, failures=1)

    outcome = run(runner, "look")

    assert outcome.ok, outcome.text()


def test_a_page_that_never_draws_says_so_in_words(
    browser: Browser, store: DejoStore, demo_server: str, monkeypatch
) -> None:
    runner = runner_for(browser, store, "zz")
    run(runner, f"go {demo_server}/books")
    _slow_snapshots(browser, monkeypatch, failures=10)

    outcome = run(runner, "look")

    assert not outcome.ok
    assert "did not finish drawing" in outcome.reason
    assert "Timeout" not in outcome.text()


def test_go_while_the_page_moves_by_itself_still_gets_there(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Right after Google's consent "Continue": `Page.goto: net::ERR_ABORTED`."""
    outcome = run(
        runner_for(browser, store, "zz"),
        f'go {demo_server}/consent\nclick button "Continue"\ngo {demo_server}/slow\n'
        'read css "h1" as heading',
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers == {"heading": "Slow page"}
