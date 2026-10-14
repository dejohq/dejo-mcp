"""Waiting, and the page events that hang a run if nobody handles them.

These are not element actions. If a dialog is never answered, the browser simply stops and
every later step waits forever. If a cookie banner is never cleared, it covers the button
the trail wants. This is the part of a real site that a demo site never teaches you.
"""

from __future__ import annotations

import pytest

from dejo import actions, waits
from dejo.browser import ACCEPT, DISMISS, Browser, NoSuchTab
from dejo.models import Locator, Postcondition, SiteKnowledge, Step

# Content arrives 300ms late, the way a dashboard's data does.
LATE = """
<!doctype html>
<title>late page</title>
<div id="spinner">Loading…</div>
<div id="content"></div>
<script>
  setTimeout(() => {
    document.getElementById('spinner').remove();
    document.getElementById('content').innerHTML =
      '<p id="total">1,240.00</p><button id="go">Continue</button>';
  }, 300);
</script>
"""

DIALOGS = """
<!doctype html>
<title>dialogs</title>
<p id="log">nothing yet</p>
<button id="save" onclick="if (confirm('Save changes?')) log('saved'); else log('cancelled')">
  Save
</button>
<button id="delete" onclick="if (confirm('Delete 400 rows?')) log('deleted'); else log('kept')">
  Delete
</button>
<button id="tell" onclick="alert('Done')">Tell me</button>
<script>
  function log(m) { document.getElementById('log').textContent = m; }
</script>
"""

BANNER = """
<!doctype html>
<title>cookie banner</title>
<style>
  #banner { position: fixed; inset: 0; background: rgba(0,0,0,.8); z-index: 9; }
  #accept { margin: 40vh auto; display: block; }
</style>
<p id="log">nothing yet</p>
<button id="real" onclick="document.getElementById('log').textContent = 'clicked'">
  Do the thing
</button>
<div id="banner">
  <button id="accept" onclick="document.getElementById('banner').remove()">Accept cookies</button>
</div>
"""


def do(browser: Browser, action: str, selector: str | None = None, **kwargs) -> None:
    target = browser.page.locator(selector).first if selector else None
    actions.perform(action, page=browser.page, target=target, **kwargs)


def log_says(browser: Browser) -> str:
    return browser.page.locator("#log").inner_text()


# ------------------------------------------------------------------ waiting


def test_registry_and_waiters_agree() -> None:
    waits.sanity_check()


def test_catalogue_lists_every_wait() -> None:
    text = waits.catalogue()
    for name in waits.WAITS:
        assert name in text


def test_unknown_wait_says_what_is_known() -> None:
    with pytest.raises(waits.UnknownWait) as raised:
        waits.parse("vibes:soon")
    assert "element" in str(raised.value)


def test_a_wait_that_needs_a_subject_is_refused() -> None:
    with pytest.raises(waits.WaitNeedsMore):
        waits.parse("element")


def test_idle_needs_no_subject() -> None:
    assert waits.parse("idle") == ("idle", "")


def test_parse_defaults_to_idle() -> None:
    assert waits.parse("") == ("idle", "")


def test_wait_for_element(browser: Browser) -> None:
    """Content that arrives late is the single most common reason a real run fails."""
    browser.page.set_content(LATE)
    assert browser.page.locator("#total").count() == 0
    do(browser, "wait_for", value="element:#total")
    assert browser.page.locator("#total").inner_text() == "1,240.00"


def test_wait_for_gone(browser: Browser) -> None:
    browser.page.set_content(LATE)
    do(browser, "wait_for", value="gone:#spinner")
    assert browser.page.locator("#spinner").count() == 0


def test_wait_for_text(browser: Browser) -> None:
    browser.page.set_content(LATE)
    do(browser, "wait_for", value="text:1,240.00")
    assert browser.page.locator("#total").count() == 1


def test_wait_for_idle(browser: Browser, demo_server: str) -> None:
    do(browser, "goto", value=f"{demo_server}/")
    do(browser, "wait_for", value="idle")


def test_wait_for_url(browser: Browser, demo_server: str) -> None:
    do(browser, "goto", value=f"{demo_server}/")
    do(browser, "wait_for", value="url:/")


def test_waiting_too_long_says_what_never_happened(browser: Browser) -> None:
    browser.page.set_content(LATE)
    with pytest.raises(waits.WaitedTooLong) as raised:
        waits.wait_for("element:#never", page=browser.page, timeout_ms=300)
    assert "#never" in str(raised.value)


def test_resolve_waits_for_visible_not_merely_attached(browser: Browser) -> None:
    """The live bug this fixed: `attached` is true while an element is still sliding into
    place and cannot receive a click. A locator that resolves must be usable."""
    browser.page.set_content("""
        <style>
          #late { opacity: 0; }
          .shown { opacity: 1 !important; }
        </style>
        <button id="late" style="display:none"
                onclick="document.title='clicked'">Go</button>
        <script>
          setTimeout(() => { document.getElementById('late').style.display = 'block'; }, 250);
        </script>
    """)
    found = browser.resolve(Locator("css", "#late"), timeout_ms=3000)
    assert found is not None
    found.click()
    assert browser.page.title() == "clicked"


# ------------------------------------------------------------------ dialogs


def test_a_confirm_is_answered_rather_than_hanging_the_run(browser: Browser) -> None:
    """An unanswered dialog blocks everything after it. Doing nothing is not an option."""
    browser.page.set_content(DIALOGS)
    do(browser, "click", "#save")
    assert log_says(browser) == "saved"


def test_accepting_is_the_default(browser: Browser) -> None:
    """Playwright's own default is to dismiss, which silently cancels a save — the run
    looks like it worked while nothing happened."""
    assert browser.dialog_policy == ACCEPT


def test_dismissing_can_be_chosen(browser: Browser) -> None:
    browser.page.set_content(DIALOGS)
    browser.dialog_policy = DISMISS
    do(browser, "click", "#save")
    assert log_says(browser) == "cancelled"


def test_the_message_and_the_choice_are_both_recorded(browser: Browser) -> None:
    browser.page.set_content(DIALOGS)
    do(browser, "click", "#save")
    assert browser.last_dialog == {
        "type": "confirm",
        "message": "Save changes?",
        "choice": ACCEPT,
    }


def test_an_alert_is_recorded_too(browser: Browser) -> None:
    browser.page.set_content(DIALOGS)
    do(browser, "click", "#tell")
    assert browser.last_dialog is not None
    assert browser.last_dialog["type"] == "alert"


def test_a_step_stores_both_the_words_and_the_answer() -> None:
    step = Step(
        index=1,
        intent="save it",
        action="click",
        postcondition=Postcondition(kind="text_present", value="saved"),
        dialog_message="Save changes?",
        dialog_choice=ACCEPT,
    )
    revived = Step.from_dict(step.to_dict())
    assert revived.dialog_message == "Save changes?"
    assert revived.dialog_choice == ACCEPT


def test_a_changed_dialog_message_stops_the_replay(browser: Browser) -> None:
    """The locked rule. A step that recorded "click OK" on "Save changes?" must never
    blindly accept a box that now reads "Delete 400 rows?"."""
    from dejo.executor import Executor

    browser.page.set_content(DIALOGS)
    step = Step(
        index=1,
        intent="save it",
        action="click",
        postcondition=Postcondition(kind="text_present", value="saved"),
        dialog_message="Save changes?",
        dialog_choice=ACCEPT,
    )

    replayer = Executor.__new__(Executor)
    replayer.browser = browser
    do(browser, "click", "#delete")

    complaint = replayer._dialog_changed(step)
    assert complaint is not None
    assert "Delete 400 rows?" in complaint
    assert "Save changes?" in complaint


def test_the_same_message_does_not_stop_the_replay(browser: Browser) -> None:
    from dejo.executor import Executor

    browser.page.set_content(DIALOGS)
    step = Step(
        index=1,
        intent="save it",
        action="click",
        postcondition=Postcondition(kind="text_present", value="saved"),
        dialog_message="Save changes?",
        dialog_choice=ACCEPT,
    )
    replayer = Executor.__new__(Executor)
    replayer.browser = browser
    do(browser, "click", "#save")
    assert replayer._dialog_changed(step) is None


def test_a_step_that_never_saw_a_dialog_is_unaffected(browser: Browser) -> None:
    from dejo.executor import Executor

    browser.page.set_content(DIALOGS)
    step = Step(
        index=1,
        intent="just click",
        action="click",
        postcondition=Postcondition(kind="text_present", value="saved"),
    )
    replayer = Executor.__new__(Executor)
    replayer.browser = browser
    do(browser, "click", "#save")
    assert replayer._dialog_changed(step) is None


# ------------------------------------------------------------------- tabs


def test_a_new_tab_is_noticed_but_not_switched_to(browser: Browser, demo_server: str) -> None:
    """Which tab a trail continues in is recorded, never guessed."""
    browser.page.goto(f"{demo_server}/")
    was = browser.page
    browser.page.evaluate("window.open(location.href, '_blank')")
    _wait_for_tabs(browser, 2)

    assert len(browser.tabs) == 2
    assert browser.page is was


def test_switch_to_the_latest_tab(browser: Browser, demo_server: str) -> None:
    browser.page.goto(f"{demo_server}/")
    browser.page.evaluate("window.open(location.href, '_blank')")
    _wait_for_tabs(browser, 2)

    browser.switch_tab("latest")
    assert browser.page is browser.tabs[-1]
    browser.switch_tab("main")
    assert browser.page is browser.tabs[0]


def test_switch_by_number(browser: Browser, demo_server: str) -> None:
    """Deliberately does NOT wait first: `switch_tab` has to do the waiting itself.

    This is the test macOS CI failed. It slept 300 ms and assumed the tab had arrived —
    enough on Linux and Windows, not enough there, which means it was never long enough
    anywhere, only lucky. A site opening a tab is exactly this race in real use.
    """
    browser.page.goto(f"{demo_server}/")
    browser.page.evaluate("window.open(location.href, '_blank')")

    browser.switch_tab("1")

    assert browser.page is browser.tabs[1]


def _wait_for_tabs(browser: Browser, count: int, timeout_ms: int = 5000) -> None:
    """Wait for the condition, never for a fixed number of milliseconds.

    A tab opened by the page arrives on an event, and how long that takes depends on the
    machine. Sleeping a guessed amount is how a suite passes on two operating systems and
    fails on the third.
    """
    waited = 0
    while len(browser.tabs) < count and waited < timeout_ms:
        browser.tabs[0].wait_for_timeout(50)
        waited += 50
    assert len(browser.tabs) >= count, f"only {len(browser.tabs)} tab(s) after {waited}ms"


def test_switching_to_a_tab_that_is_not_there(browser: Browser) -> None:
    with pytest.raises(NoSuchTab) as raised:
        browser.switch_tab("7")
    assert "numbered from 0" in str(raised.value)


def test_switch_tab_is_marked_session_handled() -> None:
    """It needs Dejo's list of tabs, which `actions.perform` deliberately cannot see."""
    assert actions.ACTIONS["switch_tab"].session_handled


# ----------------------------------------------------------------- overlays


def test_an_overlay_is_cleared_automatically(browser: Browser) -> None:
    """A cookie banner does not appear at a fixed point in a flow — it appears whenever the
    site feels like it. Registered once, it never becomes a step at all."""
    browser.page.set_content(BANNER)
    browser.dismiss_when_seen("#accept")

    do(browser, "click", "#real")
    assert log_says(browser) == "clicked"
    assert browser.page.locator("#banner").count() == 0


def test_registering_the_same_overlay_twice_is_harmless(browser: Browser) -> None:
    browser.page.set_content(BANNER)
    browser.dismiss_when_seen("#accept")
    browser.dismiss_when_seen("#accept")
    assert browser.overlays == ["#accept"]


def test_an_overlay_is_remembered_against_the_site_not_the_step() -> None:
    knowledge = SiteKnowledge(domain="example.com").merge(overlay="#accept")
    assert knowledge.overlays == ["#accept"]
    assert SiteKnowledge.from_dict(knowledge.to_dict()).overlays == ["#accept"]


def test_the_same_overlay_is_not_stored_twice() -> None:
    knowledge = SiteKnowledge(domain="example.com")
    knowledge.merge(overlay="#accept").merge(overlay="#accept")
    assert knowledge.overlays == ["#accept"]


# ------------------------------------------------------------ file chooser


def test_upload_through_a_button_that_opens_a_chooser(browser: Browser, tmp_path) -> None:
    """Plenty of sites hide the real file input and show a styled button, so attaching to
    the element directly is impossible. Clicking it opens the chooser instead."""
    browser.page.set_content("""
        <input type="file" id="hidden" style="display:none">
        <button id="pick" onclick="document.getElementById('hidden').click()">Choose file</button>
        <p id="log">nothing yet</p>
        <script>
          document.getElementById('hidden').addEventListener('change', e => {
            document.getElementById('log').textContent = e.target.files[0].name;
          });
        </script>
    """)
    receipt = tmp_path / "receipt.pdf"
    receipt.write_text("not really a pdf")

    do(browser, "upload", "#pick", value=str(receipt))
    assert log_says(browser) == "receipt.pdf"


def test_upload_still_works_on_a_plain_file_input(browser: Browser, tmp_path) -> None:
    browser.page.set_content('<input type="file" id="plain">')
    receipt = tmp_path / "receipt.pdf"
    receipt.write_text("x")
    do(browser, "upload", "#plain", value=str(receipt))
    assert browser.page.eval_on_selector("#plain", "el => el.files[0].name") == "receipt.pdf"


# ------------------------------------------------------------------ coverage

EXERCISED = {"element", "gone", "text", "url", "idle"}


def test_every_wait_kind_is_exercised() -> None:
    untested = sorted(set(waits.WAITS) - EXERCISED)
    assert not untested, f"these wait kinds have no test: {untested}"
