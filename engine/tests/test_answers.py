"""A trail has to produce the answer, not just arrive at the page.

Found on GitHub, 2026-09-02, the first real site Dejo ever touched. Asked "how many open
issues does microsoft/playwright have", it explored, got 151, and saved a trail of exactly
one step: the `goto`. The number came from a read, and reads were not recorded.

So the saved trail navigated somewhere and stopped. Every later run still had to read the
page and work the number out again — which is the entire cost the project exists to remove.
"""

from __future__ import annotations

import pytest

from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.operations import READ_ACTION, Session
from dejo.store import DejoStore

COUNTING = """
<!doctype html>
<title>invoices</title>
<a href="/invoices" id="open">Invoices</a>
<p id="total">1,240.00</p>
<ul>
  <li class="row">August</li>
  <li class="row">September</li>
  <li class="row">October</li>
</ul>
"""


@pytest.fixture
def counted(browser: Browser, store: DejoStore, demo_server: str) -> Session:
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    browser.page.set_content(COUNTING)
    return session


def ref_for(session: Session, name: str) -> str:
    for element in session.look()["elements"]:
        if element["name"] == name:
            return element["ref"]
    raise AssertionError(f"no control named {name!r}")


# --------------------------------------------------- what gets written down


def test_an_exploring_read_is_not_a_step(counted: Session) -> None:
    """Most reads are just looking around. Replaying those would achieve nothing."""
    before = len(counted.trace)
    counted.read("text", ref=ref_for(counted, "Invoices"))
    assert len(counted.trace) == before


def test_a_remembered_read_is_a_step(counted: Session) -> None:
    counted.read(
        "text",
        ref=ref_for(counted, "Invoices"),
        remember=True,
        intent="read the invoices link",
    )
    entry = counted.trace[-1]
    assert entry.action == READ_ACTION
    assert entry.intent == "read the invoices link"


def test_a_remembered_read_carries_durable_locators(counted: Session) -> None:
    """A read step is replayed by finding its element again, exactly like a click. Without
    locators it could never be replayed at all."""
    counted.read("text", ref=ref_for(counted, "Invoices"), remember=True)
    element = counted.trace[-1].element
    assert element is not None
    assert element.locators()


def test_a_remembered_read_gets_a_postcondition(counted: Session, demo_server: str) -> None:
    """A read changes nothing, so what must still be true is that the thing being read is
    there at all. If it vanished, the answer would be silently wrong."""
    counted.read("text", ref=ref_for(counted, "Invoices"), remember=True)
    playbook = counted.save("read the invoice total")

    read_step = next(step for step in playbook.steps if step.action == READ_ACTION)
    assert read_step.postcondition.kind == "element_present"


def test_the_read_still_answers_while_being_recorded(counted: Session) -> None:
    answer = counted.read("text", ref=ref_for(counted, "Invoices"), remember=True)
    assert answer == "Invoices"


# ------------------------------------------------- and what replay gives back


def test_a_warm_run_hands_back_the_answer(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The whole point. Before this, a warm run arrived at the page and said nothing."""
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.read(
        "text",
        ref=ref_for(session, "Sign in"),
        remember=True,
        intent="read the sign in button",
    )
    session.save("read the sign in button")

    result = Executor(store, browser).run(domain_of(demo_server), task="read the sign in button")

    assert result.ok
    assert result.answers["read the sign in button"] == "Sign in"


def test_a_counting_read_replays_as_a_number(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """ "How many unpaid invoices" is the shape of the real use case."""
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.read(
        "count",
        ref=ref_for(session, "Sign in"),
        remember=True,
        intent="count the sign in buttons",
    )
    session.save("count the sign in buttons")

    result = Executor(store, browser).run(domain_of(demo_server), task="count the sign in buttons")
    assert result.answers["count the sign in buttons"] == 1


def test_a_run_with_no_remembered_reads_answers_nothing(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Not an error — plenty of tasks are about doing, not reading."""
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.save("just open the page")

    result = Executor(store, browser).run(domain_of(demo_server), task="just open the page")
    assert result.ok
    assert result.answers == {}


def test_two_tasks_on_one_site_do_not_collide(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The other half of what GitHub found: a second task used to overwrite the first."""
    domain = domain_of(demo_server)

    first = Session(browser=browser, store=store)
    first.act("open the billing page", "goto", value=f"{demo_server}/")
    first.read("text", ref=ref_for(first, "Sign in"), remember=True, intent="read the button")
    first.save("read the sign in button")

    second = Session(browser=browser, store=store)
    second.act("open the billing page", "goto", value=f"{demo_server}/")
    second.read("title", remember=True, intent="read the title")
    second.save("read the page title")

    assert sorted(store.trails_for(domain)) == [
        "read the page title",
        "read the sign in button",
    ]

    replay = Executor(store, browser)
    assert replay.run(domain, task="read the sign in button").answers == {
        "read the button": "Sign in"
    }
    assert "read the title" in replay.run(domain, task="read the page title").answers


# ------------------------------- health, after the second GitHub run (P0)


def test_a_step_with_no_locators_is_not_broken() -> None:
    """A `goto` carries its destination in the step, not in a locator. Scoring it zero —
    which is what "no locators" used to mean — made every trail containing one permanently
    part-broken, and dragged it towards being retired."""
    from dejo.models import Postcondition, Step

    step = Step(
        index=1,
        intent="open the page",
        action="goto",
        value="https://example.com/x",
        postcondition=Postcondition("url_contains", "/x"),
    )
    assert step.health == 0.5


def test_a_step_with_no_locators_earns_its_own_record() -> None:
    from dejo.models import Postcondition, Step

    step = Step(
        index=1,
        intent="open the page",
        action="goto",
        postcondition=Postcondition("url_contains", "/x"),
    )
    step.record_hit()
    step.record_hit()
    assert step.health == 1.0

    step.record_miss()
    assert step.health < 1.0


def test_a_fresh_trail_is_not_reported_half_broken(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The symptom: a brand new working trail reported health 0.25, because its `goto`
    scored zero."""
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.read("text", ref=ref_for(session, "Sign in"), remember=True, intent="read it")
    playbook = session.save("read the sign in button")

    assert playbook.health >= 0.5


def test_a_healthy_trail_gets_healthier_as_it_runs(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.read("text", ref=ref_for(session, "Sign in"), remember=True, intent="read it")
    session.save("read the sign in button")

    domain = domain_of(demo_server)
    before = store.load_playbook(domain, "read the sign in button").health
    Executor(store, browser).run(domain, task="read the sign in button")
    after = store.load_playbook(domain, "read the sign in button").health

    assert after > before


def test_starting_somewhere_else_checks_where_it_actually_went(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """`url` used to change where the first step went but not what it checked, so a page
    that loaded perfectly was reported as a broken step — and the step it named could not
    be repaired, because a `goto` has no control to point at."""
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.read("title", remember=True, intent="read the title")
    session.save("read the title")

    result = Executor(store, browser).run(
        domain_of(demo_server),
        task="read the title",
        start_url=f"{demo_server}/?variant=b",
    )
    assert result.ok, result.reason


# ----------------- finding the right trail, after the third GitHub run (P1)


def test_a_task_worded_differently_still_finds_its_trail(store: DejoStore) -> None:
    """Seen live: the trail was saved as "count open issues on microsoft/playwright" and a
    user asking "how many open issues does microsoft/playwright have" found nothing, so the
    host AI explored the site again and saved over what was there.

    Nobody words a request the same way twice."""
    from dejo.models import Playbook

    for task in (
        "count open issues on microsoft/playwright",
        "count open issues on elysiajs/elysia-openapi",
    ):
        store.save_playbook(Playbook(domain="github.com", task=task))

    found = store.load_playbook("github.com", "how many open issues does microsoft/playwright have")
    assert found is not None
    assert found.task == "count open issues on microsoft/playwright"


def test_the_right_one_of_two_similar_trails(store: DejoStore) -> None:
    from dejo.models import Playbook

    for task in (
        "count open issues on microsoft/playwright",
        "count open issues on elysiajs/elysia-openapi",
    ):
        store.save_playbook(Playbook(domain="github.com", task=task))

    found = store.load_playbook("github.com", "open issues for elysia-openapi")
    assert found.task == "count open issues on elysiajs/elysia-openapi"


def test_an_unrelated_task_matches_nothing(store: DejoStore) -> None:
    """Running the wrong trail is worse than admitting there is none."""
    from dejo.models import Playbook

    store.save_playbook(Playbook(domain="github.com", task="count open issues on playwright"))
    assert store.load_playbook("github.com", "cancel my subscription") is None


# ----------------- the site with ONE trail, after the agent benchmark (2026-09-05)
#
# Measured against Playwright MCP and Chrome DevTools MCP on four sites: Dejo cost MORE
# than tools that remember nothing, on every run. The trace said why. `dejo_run` was
# called with a task, did not match, and the model read the page itself instead — on a
# site with exactly one trail, which could only ever have been the one it wanted.
#
# The cause was one clause, `if len(keys) == 1 and not task`. Naming the task, which the
# tool description tells the model to do, was WORSE than saying nothing.


def test_one_trail_and_a_rewording_of_it_runs(store: DejoStore) -> None:
    from dejo.models import Playbook

    store.save_playbook(Playbook(domain="quotes.toscrape.com", task="read the first quote"))

    found = store.load_playbook("quotes.toscrape.com", "what is the quote at the top of the page")
    assert found is not None
    assert found.task == "read the first quote"


def test_one_trail_and_a_long_request_naming_the_site_runs(store: DejoStore) -> None:
    """The caller passes `site` separately, so repeating the domain in the task must not
    count against the match. It used to: every extra word divided the score."""
    from dejo.models import Playbook

    store.save_playbook(Playbook(domain="quotes.toscrape.com", task="read the first quote"))

    found = store.load_playbook(
        "quotes.toscrape.com",
        "find the top quote on quotes.toscrape.com and tell me who said it",
    )
    assert found is not None
    assert found.task == "read the first quote"


def test_one_trail_and_a_different_job_still_refuses(store: DejoStore) -> None:
    """The single-trail fallback is not "run whatever is there". Running the wrong trail
    is worse than admitting there is none, however few there are."""
    from dejo.models import Playbook

    store.save_playbook(Playbook(domain="shop.example.com", task="count open orders"))

    assert store.load_playbook("shop.example.com", "cancel my subscription") is None


def test_the_trail_that_ran_can_be_told_apart_from_the_words_asked_for(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """A fuzzy match must never be silent — the caller has to see WHICH trail ran."""
    domain = domain_of(demo_server)
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.save("open the billing page")

    result = Executor(store, browser).run(domain, task="show me billing")

    assert result.ok
    assert result.metrics.task == "open the billing page"


def test_matching_ignores_words_that_carry_no_meaning() -> None:
    from dejo.store import best_match

    known = ["download the invoice", "cancel the subscription"]
    assert best_match("please can you download my invoice", known) == "download the invoice"


def test_two_equally_good_matches_pick_neither() -> None:
    """Guessing between them would run the wrong task."""
    from dejo.store import best_match

    assert best_match("open issues", ["open issues here", "open issues there"]) is None


def test_a_site_with_trails_never_reports_itself_unknown(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """ "Which task?" and "never been here" demand opposite responses. Reporting the second
    when the first was true is what caused the re-exploration."""
    from dejo.executor import NeedsTask

    domain = domain_of(demo_server)
    for task in ("first task", "second task"):
        session = Session(browser=browser, store=store)
        session.act("open the billing page", "goto", value=f"{demo_server}/")
        session.save(task)

    with pytest.raises(NeedsTask) as raised:
        Executor(store, browser).run(domain)

    assert sorted(raised.value.tasks) == ["first task", "second task"]
    assert "remembered" in str(raised.value)


# ------------------------------ reaching a dashboard number, from PostHog (P0)

DASHBOARD = """
<!doctype html>
<title>web analytics</title>
<nav><a href="/home">Home</a><a href="/web">Web analytics</a></nav>
<div class="tile" data-attr="visitors-tile">
  <div class="label">Visitors</div>
  <div class="big">22</div>
  <div class="change">-37.0%</div>
</div>
<div class="tile" data-attr="views-tile">
  <div class="label">Page views</div>
  <div class="big">28</div>
</div>
<p>lots and lots of other page text nobody wants in an answer</p>
"""


@pytest.fixture
def dashboard(browser: Browser, store: DejoStore, demo_server: str) -> Session:
    session = Session(browser=browser, store=store)
    session.act("open the dashboard", "goto", value=f"{demo_server}/")
    browser.page.set_content(DASHBOARD)
    return session


def test_a_number_with_no_role_has_no_ref(dashboard: Session) -> None:
    """Not a bug — a plain div is not a control and should not be offered as one. But it
    means a selector is the only handle those numbers have."""
    names = [element["name"] for element in dashboard.look()["elements"]]
    assert "22" not in names


def test_a_css_selector_works_wherever_a_ref_does(dashboard: Session) -> None:
    """What the host AI reached for unprompted on PostHog, and did not get."""
    assert dashboard.read("text", ref='[data-attr="visitors-tile"] .big') == "22"


def test_a_selector_read_can_be_remembered(dashboard: Session) -> None:
    dashboard.read(
        "text",
        ref='[data-attr="visitors-tile"] .big',
        remember=True,
        intent="unique visitors, last 7 days",
    )
    element = dashboard.trace[-1].element
    assert element is not None
    assert element.locators()


def test_the_answer_is_the_number_not_the_whole_page(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The PostHog symptom. With no way to name the tile, the saved answer was the entire
    page — five thousand characters with the number somewhere inside — handed back on every
    single run for the model to search."""
    session = Session(browser=browser, store=store)
    session.act("open the dashboard", "goto", value=f"{demo_server}/")
    browser.page.set_content(DASHBOARD)
    session.read(
        "text",
        ref='[data-attr="visitors-tile"] .big',
        remember=True,
        intent="unique visitors, last 7 days",
    )
    playbook = session.save("get unique visitors from the last 7 days")

    # The trail names the tile, not the page.
    read_step = next(step for step in playbook.steps if step.action == READ_ACTION)
    assert read_step.locators
    assert "nobody wants" not in str(read_step.to_dict())


def test_a_selector_can_be_acted_on_too(dashboard: Session) -> None:
    dashboard.browser.page.set_content(
        '<div class="tile" onclick="document.title=\'tile clicked\'">Visitors</div>'
    )
    dashboard.act("press the tile", "click", ref=".tile")
    assert dashboard.browser.page.title() == "tile clicked"


def test_a_selector_that_matches_nothing_says_so(dashboard: Session) -> None:
    from dejo.operations import ActionFailed

    with pytest.raises(ActionFailed) as raised:
        dashboard.read("text", ref=".no-such-tile")
    assert "no-such-tile" in str(raised.value)


def test_nonsense_is_not_mistaken_for_a_selector(dashboard: Session) -> None:
    from dejo.operations import ActionFailed

    with pytest.raises(ActionFailed):
        dashboard.read("text", ref="((((")


def test_refs_and_selectors_are_told_apart() -> None:
    from dejo import snapshot as aria

    assert aria.is_ref("e4")
    assert aria.is_ref("f1e2")
    assert not aria.is_ref(".tile")
    assert not aria.is_ref('[data-attr="visitors-tile"] .big')
    assert not aria.is_ref("div.big")


def test_a_hand_written_selector_survives_being_described(dashboard: Session) -> None:
    """Seen on PostHog. The AI dug through the DOM with `evaluate`, built
    `...:has-text("Visitors") div.text-4xl`, and checked it matched exactly one element.

    Describing it then overwrote that with a positional path worked out from the page —
    `div > div > div:nth-of-type(2)` — which breaks the moment a tile is added above it.
    The careful selector was thrown away, silently, for a worse one.
    """
    picked = '.tile:has-text("Visitors") .big'
    dashboard.read("text", ref=picked, remember=True, intent="unique visitors")

    element = dashboard.trace[-1].element
    assert element is not None
    assert element.locators()[0].value == picked


def test_the_worked_out_path_is_kept_as_a_spare(dashboard: Session) -> None:
    """Two ways to find the same thing beats one. Theirs is anchored to meaning; ours
    still works the day the class names change."""
    dashboard.read("text", ref='.tile:has-text("Visitors") .big', remember=True, intent="v")

    element = dashboard.trace[-1].element
    css = [locator.value for locator in element.locators() if locator.kind == "css"]
    assert len(css) == 2
    assert css[0] != css[1]


def test_a_ref_element_is_unaffected(dashboard: Session) -> None:
    """Nothing changes for elements that came from a snapshot — they never had a selector
    of their own to protect."""
    ref = ref_for(dashboard, "Web analytics")
    dashboard.read("text", ref=ref, remember=True, intent="the link")

    element = dashboard.trace[-1].element
    assert element.fallback_css == ""


# ------------------- repair, after the third PostHog run (P0 and P1)

AMBIGUOUS = """
<!doctype html>
<title>two of the same</title>
<main><div><div><div><div><button id="real" onclick="document.title='right one'">Analytics</button></div></div></div></div></main>
<aside><section><nav><div><div><div><div><div>
  <button id="decoy" onclick="document.title='WRONG ONE'">Analytics</button>
</div></div></div></div></div></nav></section></aside>
"""


def test_a_stored_css_path_matches_exactly_one_element(browser: Browser) -> None:
    """Seen live on PostHog. `cssOf` walked five levels and stopped whether or not the
    result was unique — and five levels is nothing in a React app, where the real path was
    fifteen. The suffix matched two places, `locate` takes `.first`, and replay clicked the
    wrong control: a repaired step kept opening a "Remove from sidebar panel" menu that
    then blocked every read after it."""
    browser.page.set_content(AMBIGUOUS)

    for element in browser.snapshot().elements:
        described = browser.describe(element)
        if described.css:
            assert browser.page.locator(described.css).count() == 1, (
                f"{described.css} matches more than one element"
            )


def test_no_css_is_stored_rather_than_an_ambiguous_one(browser: Browser) -> None:
    """A selector that reliably finds the wrong thing is worse than having none."""
    browser.page.set_content("<div><span>a</span></div><div><span>a</span></div>")
    for element in browser.snapshot().elements:
        described = browser.describe(element)
        assert not described.css or browser.page.locator(described.css).count() == 1


def test_a_repair_stores_every_way_of_finding_the_control(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The host AI's own words, mid-run: "Dejo only takes plain CSS." It had a better
    locator in mind, could not express it, and fell back to a positional path that then
    matched the wrong element. A repair used to leave a step MORE fragile than when it was
    first learned."""
    from dejo.executor import Executor
    from dejo.models import Locator

    domain = domain_of(demo_server)
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.act("sign in", "click", ref=ref_for(session, "Sign in"))
    session.save("sign in")

    playbook = store.load_playbook(domain, "sign in")
    playbook.steps[1].locators = [Locator("css", "#long-gone", misses=9)]
    store.save_playbook(playbook)

    replay = Executor(store, browser)
    replay.browser.goto(f"{demo_server}/")
    ref = next(
        element["ref"]
        for element in Session(browser, store).look()["elements"]
        if element["name"] == "Sign in"
    )
    fixed = replay.repair_from_ref(domain, 2, ref, task="sign in")

    kinds = {locator.kind for locator in fixed.steps[1].locators}
    assert len(kinds) > 1, f"a repair stored only {kinds}"


def test_a_fumbled_step_can_be_dropped_before_saving(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Found by replaying a real PostHog trail. It began:

        1. press  close the stuck context menu
        2. click  open the Analytics section...

    Both were the AI getting out of a mess it had made. Step 1 failed on the first replay
    and took the whole run with it — six steps saved, zero replayed, no answer.
    """
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.act("get out of a stuck menu", "press", value="Escape")
    assert len(session.trace) == 2

    session.act("start the trail here", "restart_trail")
    assert session.trace == []

    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.read("title", remember=True, intent="read the title")
    playbook = session.save("read the title")

    assert [step.action for step in playbook.steps] == ["goto", "read"]
    assert all("stuck menu" not in step.intent for step in playbook.steps)


def test_restarting_leaves_the_browser_where_it_is(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Explore however you like, then walk the task cleanly from wherever you ended up."""
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    where = browser.page.url

    session.act("start the trail here", "restart_trail")
    assert browser.page.url == where


def test_restarting_is_never_a_step_itself(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.act("start the trail here", "restart_trail")
    session.act("open it again", "goto", value=f"{demo_server}/")

    assert [entry.action for entry in session.trace] == ["goto"]


# ----------------- the trail that walked to the page and stopped (2026-09-05)
#
# Measured against Playwright MCP and Chrome DevTools MCP on four public sites, three runs
# each. On three of the four, Dejo's SECOND run still read the page itself — because the
# saved trail had no answer in it. `remember=True` marks the read that is the answer, the
# read tool's description shouts about it in capitals, and the caller never passed it once
# in twelve runs.
#
# Telling it harder was not going to work. So a read that is not marked is kept aside, and
# used only if the trail would otherwise answer nothing at all.


def test_a_read_nobody_marked_still_becomes_the_answer(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.read("text", ref=ref_for(session, "Sign in"))

    session.save("read the sign in button")

    result = Executor(store, browser).run(
        domain_of(demo_server), task="read the sign in button", start_url=f"{demo_server}/"
    )
    assert result.answers, "a trail that read something must answer something"


def test_and_the_caller_is_told_it_was_chosen_rather_than_marked(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Guessing is fine. Guessing silently is not — only the caller knows if it picked the
    right read."""
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.read("text", ref=ref_for(session, "Sign in"))

    session.save("read the sign in button")

    assert session.answered_from_the_last_read is True


def test_a_marked_read_is_never_second_guessed(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The moment anything is marked, choosing stops. A caller that says what it wants is
    obeyed exactly."""
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.read("title", remember=True, intent="the page title")
    session.read("text", ref=ref_for(session, "Sign in"))

    playbook = session.save("read the title")

    assert session.answered_from_the_last_read is False
    assert [s.intent for s in playbook.steps if s.action == READ_ACTION] == ["the page title"]


def test_a_task_that_reads_nothing_still_saves_nothing(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Plenty of tasks are about doing, not reading. Inventing an answer step for those
    would put a read into a trail that never had one."""
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")

    playbook = session.save("just open the page")

    assert session.answered_from_the_last_read is False
    assert [s for s in playbook.steps if s.action == READ_ACTION] == []


def test_the_chosen_read_keeps_its_place_in_the_trail(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """A read that happened before a click has to replay before that click. Putting it on
    the end instead would answer from the wrong page."""
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.read("text", ref=ref_for(session, "Sign in"))
    session.act("go to the invoices", "goto", value=f"{demo_server}/invoices")

    playbook = session.save("look then move")

    kinds = [s.action for s in playbook.steps]
    assert kinds.index(READ_ACTION) < len(kinds) - 1, kinds


def test_a_whole_page_read_is_never_chosen_for_you(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """Remembering a page dump hands back thousands of characters on every future run.
    Marking one is the caller's business; nobody is opted into it."""
    session = Session(browser=browser, store=store)
    session.act("open the billing page", "goto", value=f"{demo_server}/")
    session.read("page_text")

    playbook = session.save("read the whole page")

    assert session.answered_from_the_last_read is False
    assert [s for s in playbook.steps if s.action == READ_ACTION] == []


def test_any_way_of_naming_a_site_reaches_the_same_memory() -> None:
    """The key IS the memory, so every spelling has to land on it.

    Measured on 2026-09-05: ten runs on github.com, ten full explorations, not one warm
    replay. The caller said `github.com/microsoft/playwright`, which has no scheme, so the
    path was never stripped and it became a key of its own. Dejo learned the site under
    `github.com` and looked it up under the long string, forever. Nothing failed; it was
    only slow, which is why it survived a benchmark, a test suite and eight real sites.
    """
    from dejo.browser import domain_of

    for spelling in (
        "github.com",
        "GitHub.com",
        "github.com/microsoft/playwright",
        "https://github.com/microsoft/playwright",
        "http://github.com/microsoft/playwright?tab=readme#top",
    ):
        assert domain_of(spelling) == "github.com", spelling


def test_a_port_still_separates_two_local_sites() -> None:
    """Two demo servers on one machine are two different sites, and always were."""
    from dejo.browser import domain_of

    assert domain_of("http://127.0.0.1:5000/a") == "127.0.0.1:5000"
    assert domain_of("localhost:8931/x") == "localhost:8931"


# ----------------- the answer the caller already has (2026-09-05)
#
# The last hole, and the one no wording closed. On books.toscrape.com the price lives in
# `.price_color`, which matches SEVEN elements, so the read is refused — correctly, since
# guessing would report another book's price for ever. But the refusal NAMES the matches,
# so the caller reads the value straight out of the refusal, answers the user, and never
# makes a successful read. The trail then walks three pages and hands back nothing, on
# every run, and the warm path costs as much as the cold one.
#
# The caller always has the value at that point. So `save` takes it, and Dejo does the
# part it is good at: find which element says exactly that, and write down every durable
# way of finding that element again.


class TestSavingTheAnswerTheCallerAlreadyHas:
    def test_a_trail_with_no_read_gets_its_answer_from_the_value_given(
        self, browser: Browser, store: DejoStore, demo_server: str
    ) -> None:
        session = Session(browser=browser, store=store)
        session.act("open the payments page", "goto", value=f"{demo_server}/payments")

        playbook = session.save("what is the next charge", answer="₹ 18,400")

        reads = [step for step in playbook.steps if step.action == READ_ACTION]
        assert len(reads) == 1
        assert reads[0].intent == "what is the next charge"

    def test_and_it_is_stored_by_structure_not_by_the_text(
        self, browser: Browser, store: DejoStore, demo_server: str
    ) -> None:
        """The value is a price or a count and will be different tomorrow. A locator that
        says "the element reading ₹ 18,400" would miss the day it changes — which is the
        day you most want to read it."""
        session = Session(browser=browser, store=store)
        session.act("open the payments page", "goto", value=f"{demo_server}/payments")

        playbook = session.save("what is the next charge", answer="₹ 18,400")

        found = [step for step in playbook.steps if step.action == READ_ACTION][0]
        assert found.locators
        assert not any("18,400" in locator.value for locator in found.locators)

    def test_and_replay_answers_it_in_one_call(
        self, browser: Browser, store: DejoStore, demo_server: str
    ) -> None:
        session = Session(browser=browser, store=store)
        session.act("open the payments page", "goto", value=f"{demo_server}/payments")
        session.save("what is the next charge", answer="₹ 18,400")

        result = Executor(store, browser).run(
            domain_of(demo_server), task="what is the next charge"
        )

        assert result.ok
        assert result.answers["what is the next charge"] == "₹ 18,400"

    def test_a_value_that_is_not_on_the_page_is_never_invented(
        self, browser: Browser, store: DejoStore, demo_server: str
    ) -> None:
        """Recording an answer nobody can point at would be a stored lie."""
        session = Session(browser=browser, store=store)
        session.act("open the payments page", "goto", value=f"{demo_server}/payments")

        playbook = session.save("what is the next charge", answer="£999.99")

        assert session.answered_from_the_value_given == 0
        assert [step for step in playbook.steps if step.action == READ_ACTION] == []

    def test_a_read_the_caller_marked_is_never_overruled(
        self, browser: Browser, store: DejoStore, demo_server: str
    ) -> None:
        """If the caller said which read is the answer, that is the answer. The value is
        only ever a fallback for a trail that would otherwise have none."""
        session = Session(browser=browser, store=store)
        session.act("open the payments page", "goto", value=f"{demo_server}/payments")
        session.read("text", ref="#cycle", remember=True, intent="the billing cycle")

        playbook = session.save("what is the next charge", answer="₹ 18,400")

        reads = [step for step in playbook.steps if step.action == READ_ACTION]
        assert [step.intent for step in reads] == ["the billing cycle"]

    def test_how_many_elements_said_it_is_reported(
        self, browser: Browser, store: DejoStore, demo_server: str
    ) -> None:
        """A product page shows its price in the header and again in a tax table. That is
        ordinary, not an error — but the caller has to be able to see it happened."""
        session = Session(browser=browser, store=store)
        session.act("open the payments page", "goto", value=f"{demo_server}/payments")

        session.save("what is the next charge", answer="₹ 18,400")

        assert session.answered_from_the_value_given >= 1
