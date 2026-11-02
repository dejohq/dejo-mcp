"""A target names an element by words in its name, the way Playwright's get_by_role does.

On real shops a whole product card is one link, so the link is called "Belt Sander $73.59"
and a filter is called "Sander (2)". An agent writes `link "Belt Sander"`. Dejo used to
match names only exactly and answered "nothing on this page is link ...", which was 16 of
the 50 failures in the reliability benchmark (2 Nov 2026). These run on `/tools` of the
demo site, which is laid out like those shops.
"""

from __future__ import annotations

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.models import Locator
from dejo.operations import Session
from dejo.runner import Outcome, Runner
from dejo.store import DejoStore

TASK = "the price of the belt sander"


def run(browser: Browser, store: DejoStore, text: str, task: str = TASK) -> Outcome:
    runner = Runner(Session(browser=browser, store=store), task=task, store=store)
    return runner.run(program.parse(text))


def test_a_link_is_found_by_the_words_at_the_start_of_its_name(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = run(
        browser,
        store,
        f'go {demo_server}/tools\nclick link "Belt Sander"\nread css "#price" as price\n',
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers["price"] == "$73.59"


def test_the_trail_it_saves_replays_by_the_same_words(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = run(
        browser,
        store,
        f'go {demo_server}/tools\nclick link "Belt Sander"\nread css "#price" as price\n',
    )
    assert outcome.saved is not None, outcome.text()
    clicked = outcome.saved.steps[1]
    assert any(not locator.exact for locator in clicked.locators), clicked.locators

    replay = Executor(store, browser).run(domain_of(demo_server), task=TASK)
    assert replay.ok, replay
    assert replay.answers["price"] == "$73.59"


def test_case_does_not_matter_when_the_words_are_part_of_a_name(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = run(
        browser,
        store,
        f'go {demo_server}/tools\nclick link "belt sander"\nread css "#title" as name\n',
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers["name"] == "Belt Sander"


def test_a_heading_and_a_checkbox_are_found_by_part_of_their_name(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = run(
        browser,
        store,
        f"go {demo_server}/tools\n"
        'check checkbox "Sander"\n'
        'read heading "Package: tools" as version\n',
        task="the tools package version",
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers["version"] == "Package: tools (1:1.0.51-13)"


def test_an_exact_name_wins_over_names_that_only_contain_the_words(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """`link "5"` is the page-5 link. "15" also contains a 5, and must not make it ambiguous."""
    outcome = run(
        browser,
        store,
        f'go {demo_server}/tools\nclick link "5"\nread url as where\n',
        task="page five",
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers["where"].endswith("/tools?page=5")


def test_words_in_two_names_are_refused_not_guessed(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = run(
        browser,
        store,
        f'go {demo_server}/tools\nclick link "Sander"\nread css "#price" as price\n',
        task="a sander",
    )
    assert not outcome.ok
    assert "2 matches" in outcome.reason
    assert browser.page.url.endswith("/tools")


def test_a_wait_for_a_late_card_accepts_words_in_its_name(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = run(
        browser,
        store,
        f"go {demo_server}/tools?late=1\n"
        'wait link "Belt Sander"\n'
        'click link "Belt Sander"\n'
        'read css "#price" as price\n',
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers["price"] == "$73.59"


def test_a_loose_locator_keeps_its_looseness_in_memory() -> None:
    loose = Locator("role", "link|Belt Sander", exact=False)
    assert Locator.from_dict(loose.to_dict()).exact is False
    assert "exact" not in Locator("role", "link|Belt Sander").to_dict()
    assert Locator.from_dict({"kind": "text", "value": "Sander"}).exact is True


def test_a_link_a_site_hid_from_screen_readers_but_shows_is_still_found(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """doververmont.com draws its news carousel inside `aria-hidden="true"`. The view shows
    those links, so a target must find them; the copy hidden for everyone stays out."""
    task = "the hammer in the news"
    outcome = run(
        browser,
        store,
        f'go {demo_server}/tools\nclick link "Hammer news"\nread css "#title" as name\n',
        task=task,
    )
    assert outcome.ok, outcome.text()
    assert outcome.answers["name"] == "Claw Hammer"

    replay = Executor(store, browser).run(domain_of(demo_server), task=task)
    assert replay.ok, replay
    assert replay.answers["name"] == "Claw Hammer"


def test_a_hidden_locator_keeps_its_rule_in_memory() -> None:
    hidden = Locator("role", "link|Hammer news", exact=False, include_hidden=True)
    assert Locator.from_dict(hidden.to_dict()).include_hidden is True
    assert "include_hidden" not in Locator("role", "link|x").to_dict()
