"""A pop-up nobody told Dejo about, on the visit after the one the trail was learned on.

Each lab page in `demo_site/drift.py` shows its pop-up only from the second visit on, so
learning is visit one and the replay meets something new, exactly as on a real site. Every
test checks three things: the replay got through, it said what it cleared, and it never
pressed anything that subscribes.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.operations import Session
from dejo.popups import PRESS_ESCAPE
from dejo.runner import Runner
from dejo.store import DejoStore

TASK = "the price"

# Short, so the one test where nothing safe clears the pop-up does not wait out the usual
# fifteen seconds for every way it knows of finding the button.
SHORT_TIMEOUT_MS = 1500


def learn(browser: Browser, store: DejoStore, url: str) -> None:
    runner = Runner(Session(browser=browser, store=store), task=TASK, store=store)
    outcome = runner.run(
        program.parse(f'go {url}\nclick button "Show the price"\nread css "#price" as price')
    )
    assert outcome.ok, outcome.text()


def replay(browser: Browser, store: DejoStore, url: str):
    return Executor(store, browser).run(domain_of(url), task=TASK)


def lab(browser: Browser, name: str) -> object:
    return browser.page.evaluate(f"window.lab && window.lab.{name}")


def test_a_newsletter_box_is_closed_by_its_no_thanks_and_remembered(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    url = f"{demo_server}/drift/newsletter"
    learn(browser, store, url)

    result = replay(browser, store, url)

    assert result.ok, result.reason
    assert result.answers == {"price": "£12 a month"}
    assert result.cleared == ['step 2: "Join our newsletter" closed by its "No thanks" control']
    assert lab(browser, "subscribed") is None, "the newsletter's Subscribe was pressed"
    knowledge = store.load_site_knowledge(domain_of(url))
    assert knowledge is not None and len(knowledge.overlays) == 1

    again = replay(browser, store, url)
    assert again.ok, again.reason
    assert again.cleared == [], "a known pop-up should be cleared up front, not met again"
    assert again.decisions == [f"step 2: cleared a known pop-up ({knowledge.overlays[0]})"]


def test_a_box_with_nothing_to_click_is_closed_with_escape(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    url = f"{demo_server}/drift/escape"
    learn(browser, store, url)

    result = replay(browser, store, url)

    assert result.ok, result.reason
    assert result.cleared == ['step 2: "Enjoying Plans?" closed with the Escape key']
    assert lab(browser, "rated") is None, "a star was pressed to get rid of the box"
    knowledge = store.load_site_knowledge(domain_of(url))
    assert knowledge is not None and knowledge.overlays == [f"{PRESS_ESCAPE}#rate-us"]

    again = replay(browser, store, url)
    assert again.ok and again.cleared == [], again.reason


@pytest.mark.parametrize("kind", ["platform", "words"])
def test_a_consent_banner_is_declined_rather_than_accepted(
    browser: Browser, store: DejoStore, demo_server: str, kind: str
) -> None:
    url = f"{demo_server}/drift/consent?kind={kind}"
    learn(browser, store, url)

    result = replay(browser, store, url)

    assert result.ok, result.reason
    assert lab(browser, "consent") == "rejected"
    assert len(result.cleared) == 1 and "consent banner" in result.cleared[0]


@pytest.fixture
def impatient(tmp_path) -> Iterator[Browser]:
    with Browser(
        headless=True, downloads=tmp_path / "downloads", timeout_ms=SHORT_TIMEOUT_MS
    ) as running:
        yield running


def test_a_box_whose_only_way_out_subscribes_stops_the_replay_as_before(
    impatient: Browser, store: DejoStore, demo_server: str
) -> None:
    url = f"{demo_server}/drift/locked"
    learn(impatient, store, url)

    result = replay(impatient, store, url)

    assert not result.ok
    assert result.repair is not None and result.repair.step_index == 2
    assert result.cleared == []
    assert lab(impatient, "subscribed") is None, "Subscribe was pressed to get past the box"


def test_a_pop_up_met_while_learning_is_cleared_said_and_kept(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    url = f"{demo_server}/drift/newsletter"
    browser.goto(url)  # the first visit: from now on the box is shown

    runner = Runner(Session(browser=browser, store=store), task=TASK, store=store)
    outcome = runner.run(
        program.parse(f'go {url}\nclick button "Show the price"\nread css "#price" as price')
    )

    assert outcome.ok, outcome.text()
    assert 'line 2: cleared a pop-up first: "Join our newsletter" closed by its' in outcome.text()
    assert outcome.saved is not None and len(outcome.saved.steps) == 3, "the close became a step"
    assert lab(browser, "subscribed") is None
    knowledge = store.load_site_knowledge(domain_of(url))
    assert knowledge is not None and len(knowledge.overlays) == 1


def test_a_remembered_close_never_closes_a_dialog_the_trail_opens(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """demoqa.com: the small dialog's close was remembered as "any dialog's Close", so the
    large dialog the task opened on purpose was closed again before it could be read."""
    url = f"{demo_server}/drift/dialogs"
    runner = Runner(Session(browser=browser, store=store), task="the title", store=store)
    outcome = runner.run(
        program.parse(
            f'go {url}\nclick button "Open small"\nclick button "Open large"\n'
            'read css "#large-title" as title'
        )
    )

    assert outcome.ok, outcome.text()
    assert "line 3: cleared a pop-up first" in outcome.text()
    knowledge = store.load_site_knowledge(domain_of(url))
    assert knowledge is not None
    assert knowledge.overlays == ['[aria-labelledby="small-title"] [aria-label="Close"]']

    again = Executor(store, browser).run(domain_of(url), task="the title")
    assert again.ok, again.reason
    assert again.answers == {"title": "Large dialog"}


# A consent platform that asks inside its own frame (Sourcepoint on theguardian.com and
# spiegel.de, 10 Nov): the page shows a fixed box holding an iframe, and every button is in
# the frame. Searching only the page itself found nothing and the step stopped.
_FRAMED_CONSENT = """
<button id="go" onclick="document.title='went'">Sport</button>
<div id="sp_message_container" style="position:fixed;inset:0;z-index:9">
  <iframe id="sp_message_iframe_1482255" title="consent message" style="width:100%;height:100%"
    srcdoc="<p>We use cookies.</p>
      <button onclick=&quot;parent.document.getElementById('sp_message_container').remove()&quot;>Yes, I accept</button>
      <button onclick=&quot;parent.document.title='rejected';parent.document.getElementById('sp_message_container').remove()&quot;>No, thank you</button>
      <button onclick=&quot;parent.document.title='paid'&quot;>Subscribe now</button>"></iframe>
</div>
"""


def test_a_consent_box_inside_a_frame_is_answered_inside_the_frame(browser: Browser) -> None:
    from dejo import popups

    browser.page.set_content(_FRAMED_CONSENT)
    browser.page.frame_locator("#sp_message_iframe_1482255").locator("button").first.wait_for()
    cleared = popups.clear_the_way(browser.page, browser.page.locator("#go"))
    assert cleared is not None and cleared.done, cleared
    assert "No, thank you" in cleared.what
    assert browser.page.title() == "rejected", "the reject choice, never accept or subscribe"
    browser.page.locator("#go").click(timeout=2000)
    assert browser.page.title() == "went"
