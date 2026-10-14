"""The escape hatch, and the three gaps a hatch does not cover.

Decided on 2026-09-02. The ask was for all 177 Playwright methods as named
actions; I argued for this instead, and he agreed to try it first.

The argument, kept here because it is the reason the rest stays unbuilt: Dejo already
HAS all of Playwright — it is an installed dependency and every method is callable. The
registry does not decide what Dejo *can* do, only what gets written into a trail. So
instead of 94 more names for an AI to choose between, one `evaluate` covers everything
nobody thought of, and it is deliberately never recorded.
"""

from __future__ import annotations

import pytest

from dejo import actions, reads
from dejo.browser import Browser
from dejo.operations import Session
from dejo.store import DejoStore

NOISY = """
<!doctype html>
<title>noisy page</title>
<button id="total" data-cents="124000">1,240.00</button>
<div id="host"></div>
<script>
  console.log('just chatter');
  console.warn('a warning');
  console.error('something broke');
  fetch('/nope-does-not-exist');
  document.getElementById('host').attachShadow({mode: 'open'}).innerHTML =
    '<span id="deep">hidden treasure</span>';
</script>
"""


@pytest.fixture
def noisy(browser: Browser, store: DejoStore, demo_server: str) -> Session:
    session = Session(browser=browser, store=store)
    session.act("open the noisy page", "goto", value=f"{demo_server}/")
    browser.page.set_content(NOISY)
    browser.page.wait_for_timeout(400)
    return session


# ------------------------------------------------------------ the escape hatch


def test_evaluate_runs_on_the_page(noisy: Session) -> None:
    outcome = noisy.act("read the title", "evaluate", value="() => document.title")
    assert outcome["result"] == "noisy page"


def test_evaluate_runs_on_one_element(noisy: Session) -> None:
    """With a ref it runs on that element, given as `el`."""
    page = noisy.look()
    ref = next(e["ref"] for e in page["elements"] if e["name"] == "1,240.00")
    outcome = noisy.act("read the raw amount", "evaluate", ref=ref, value="el => el.dataset.cents")
    assert outcome["result"] == "124000"


def test_evaluate_reaches_what_no_action_covers(noisy: Session) -> None:
    """The whole point. Nothing in the registry can read inside a closed shadow root, and
    nothing needs to — the AI writes the four lines itself."""
    outcome = noisy.act(
        "read inside the shadow root",
        "evaluate",
        value="() => document.getElementById('host').shadowRoot.getElementById('deep').textContent",
    )
    assert outcome["result"] == "hidden treasure"


def test_evaluate_can_change_the_page(noisy: Session) -> None:
    noisy.act("rename the page", "evaluate", value="() => { document.title = 'renamed'; }")
    assert noisy.browser.page.title() == "renamed"


def test_evaluate_is_never_written_into_the_trail(noisy: Session) -> None:
    """A step made of code cannot be repaired. Repair works by finding an element again,
    and a blob of JavaScript has no element — so it could only ever break."""
    before = len(noisy.trace)
    noisy.act("poke around", "evaluate", value="() => document.title")

    assert len(noisy.trace) == before
    assert not actions.ACTIONS["evaluate"].recordable


def test_the_description_warns_that_it_is_not_remembered() -> None:
    """An AI that does not know this would build a trail of code blobs that all break on
    the first redesign."""
    summary = actions.ACTIONS["evaluate"].summary
    assert "NOT REMEMBERED" in summary
    assert "ESCAPE HATCH" in summary


def test_a_broken_script_says_what_broke(noisy: Session) -> None:
    from playwright.sync_api import Error as PlaywrightError

    with pytest.raises(PlaywrightError):
        noisy.act("write nonsense", "evaluate", value="() => notAThing()")


# ------------------------------------------------------------- diagnostics


def test_console_errors_are_collected(noisy: Session) -> None:
    """When a run fails for no visible reason, this is usually why."""
    problems = noisy.read("console_errors")
    assert any("something broke" in line for line in problems)


def test_ordinary_chatter_is_ignored(noisy: Session) -> None:
    """A busy site logs hundreds of harmless lines. Keeping them would bury the one that
    matters."""
    problems = noisy.read("console_errors")
    assert not any("just chatter" in line for line in problems)


def test_warnings_are_kept(noisy: Session) -> None:
    assert any("a warning" in line for line in noisy.read("console_errors"))


def test_failed_requests_are_collected(noisy: Session) -> None:
    """A dashboard that stays empty is usually one failed request, not a missing element."""
    failures = noisy.read("failed_requests")
    assert any("nope-does-not-exist" in line for line in failures)


def test_a_page_with_nothing_wrong_reports_nothing(browser: Browser, store: DejoStore) -> None:
    session = Session(browser=browser, store=store)
    browser.page.set_content("<p>all is well</p>")
    assert session.read("console_errors") == []
    assert session.read("failed_requests") == []


def test_diagnostics_are_capped(noisy: Session) -> None:
    """A long-running session must not grow without limit."""
    from dejo.browser import MAX_DIAGNOSTICS

    noisy.act(
        "make a lot of noise",
        "evaluate",
        value="() => { for (let i = 0; i < 200; i++) console.error('boom ' + i); }",
    )
    noisy.browser.page.wait_for_timeout(300)

    kept = noisy.read("console_errors")
    assert len(kept) <= MAX_DIAGNOSTICS
    # The newest is the useful one, so it is the oldest that gets dropped.
    assert any("boom 199" in line for line in kept)


# ------------------------------------------------------------------- clock


def test_the_page_can_be_told_a_different_date(noisy: Session) -> None:
    """A dashboard whose numbers depend on today is otherwise unreplayable: a trail
    recorded in September reads the wrong month in October, and nothing about that looks
    like a broken step."""
    noisy.act("pretend it is September", "set_time", value="2026-09-15T10:00:00")
    seen = noisy.act(
        "read the date the page sees",
        "evaluate",
        value="() => new Date().toISOString().slice(0, 10)",
    )
    assert seen["result"] == "2026-09-15"


def test_set_time_without_a_date_says_so(noisy: Session) -> None:
    from dejo.operations import ActionFailed

    with pytest.raises(ActionFailed) as raised:
        noisy.act("freeze time", "set_time")
    assert "2026" in str(raised.value)


# -------------------------------------------------------------- screenshot


def test_screenshot_saves_a_file(noisy: Session, tmp_path) -> None:
    where = tmp_path / "page.png"
    outcome = noisy.act("take a picture", "screenshot", value=str(where))

    assert outcome["result"] == str(where)
    assert where.is_file()
    assert where.stat().st_size > 0


def test_screenshot_of_one_element(noisy: Session, tmp_path) -> None:
    page = noisy.look()
    ref = next(e["ref"] for e in page["elements"] if e["name"] == "1,240.00")
    where = tmp_path / "total.png"
    noisy.act("picture of the total", "screenshot", ref=ref, value=str(where))
    assert where.is_file()


def test_a_screenshot_is_never_a_step(noisy: Session, tmp_path) -> None:
    before = len(noisy.trace)
    noisy.act("take a picture", "screenshot", value=str(tmp_path / "x.png"))
    assert len(noisy.trace) == before


# ------------------------------------------------------------------ wiring


def test_the_new_actions_are_in_the_catalogue() -> None:
    listed = actions.catalogue()
    for name in ("evaluate", "screenshot", "set_time"):
        assert name in listed


def test_the_new_reads_are_in_the_catalogue() -> None:
    listed = reads.catalogue()
    for name in ("console_errors", "failed_requests"):
        assert name in listed


def test_the_registries_still_agree() -> None:
    actions.sanity_check()
    reads.sanity_check()
