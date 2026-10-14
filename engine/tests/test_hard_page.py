"""Every awkward thing on one page, handled.

The demo site proves the memory loop works. It proves nothing about a real website, because
it has clean HTML, stable ids, no JavaScript rendering and no cookie banner. This page has
the nine things that actually break recorded flows, and every one of them is exercised here
through the same verbs a host AI would use.

The last test is the one that matters: the whole page, start to finish, in one go.
"""

from __future__ import annotations

import pytest

from dejo.browser import Browser
from dejo.operations import Session
from dejo.store import DejoStore


@pytest.fixture
def hard(browser: Browser, store: DejoStore, demo_server: str) -> Session:
    """The hard page, open, with the cookie banner already learned about."""
    session = Session(browser=browser, store=store)
    session.act("open the hard page", "goto", value=f"{demo_server}/hard")
    return session


def ref_for(session: Session, name: str) -> str:
    page = session.look()
    for element in page["elements"]:
        if element["name"] == name:
            return element["ref"]
    seen = [element["name"] for element in page["elements"]]
    raise AssertionError(f"no control named {name!r}. saw: {seen}")


def log_says(session: Session) -> str:
    return session.browser.page.locator("#log").inner_text()


def clear_the_banner(session: Session) -> None:
    """Learned once, then never a step again."""
    session.act("learn the cookie banner", "dismiss_when_seen", value="#accept-cookies")


# --------------------------------------------------- 5. the cookie banner


def test_the_banner_covers_the_page_to_begin_with(hard: Session) -> None:
    """Proves the obstacle is real. Without this the next test proves nothing."""
    assert hard.browser.page.locator("#cookies").count() == 1


def test_the_banner_is_cleared_without_ever_being_a_step(hard: Session) -> None:
    """A banner appears whenever the site feels like it, not at a fixed point in a flow.
    Registered against the site, it never enters the trail at all."""
    clear_the_banner(hard)
    hard.act("pick a month", "click", ref=ref_for(hard, "Choose a month"))

    assert hard.browser.page.locator("#cookies").count() == 0
    assert all("cookie" not in entry.intent.lower() for entry in hard.trace)


# ------------------------------------------------- 1. the div "dropdown"


def test_a_dropdown_made_of_divs(hard: Session) -> None:
    """There is no `<select>` on this page. `select` would find nothing; this is two
    clicks, exactly as a person would do it."""
    clear_the_banner(hard)
    hard.act("open the month menu", "click", ref=ref_for(hard, "Choose a month"))
    hard.act("choose September", "click", ref=ref_for(hard, "September 2026"))

    assert log_says(hard) == "picked sep"


# ---------------------------------------------------- 2. the shadow DOM


def test_a_button_inside_a_shadow_root(hard: Session) -> None:
    clear_the_banner(hard)
    hard.act("press the shadow button", "click", ref=ref_for(hard, "Button in a shadow root"))
    assert log_says(hard) == "shadow button clicked"


# -------------------------------------------------------- 3. the iframe


def test_a_button_inside_an_iframe(hard: Session) -> None:
    clear_the_banner(hard)
    hard.act("press the button in the frame", "click", ref=ref_for(hard, "Button in a frame"))

    inside = hard.browser.page.frame_locator("#widget").locator("body")
    assert inside.get_attribute("data-clicked") == "yes"


def test_a_locator_recorded_inside_a_frame_names_its_frame(hard: Session) -> None:
    """Without the frame, the stored locator is unresolvable on the next run."""
    clear_the_banner(hard)
    hard.act("press the button in the frame", "click", ref=ref_for(hard, "Button in a frame"))

    element = hard.trace[-1].element
    assert element is not None
    assert element.frame == "#widget"
    assert all(locator.frame == "#widget" for locator in element.locators())


# --------------------------------------------------- 4. the late content


def test_content_that_has_not_arrived_yet(hard: Session) -> None:
    """`wait_for`, not a guessed number of seconds. This is the single most likely reason
    a run fails on a real dashboard."""
    clear_the_banner(hard)
    assert hard.browser.page.locator("#total").count() == 0

    hard.act("wait for the figures", "wait_for", value="element:#total")
    assert hard.read("text", ref=ref_for(hard, "Continue")) == "Continue"
    assert hard.browser.page.locator("#total").inner_text() == "1,240.00"


# -------------------------------------------------------- 6. the confirm


def test_a_confirm_box_is_answered_rather_than_hanging_the_run(hard: Session) -> None:
    clear_the_banner(hard)
    hard.act("delete the report", "click", ref=ref_for(hard, "Delete the report"))

    assert log_says(hard) == "report deleted"
    assert hard.browser.last_dialog is not None
    assert hard.browser.last_dialog["message"] == "Delete the report?"


def test_the_wording_of_the_confirm_is_recorded_with_the_step(hard: Session) -> None:
    """The choice alone is not safe to replay. A step that answered one question must not
    answer a different one."""
    clear_the_banner(hard)
    hard.act("delete the report", "click", ref=ref_for(hard, "Delete the report"))

    dialog = hard.trace[-1].dialog
    assert dialog is not None
    assert dialog["message"] == "Delete the report?"
    assert dialog["choice"] == "accept"


# --------------------------------------------------------- 7. the new tab


def test_a_link_that_opens_a_new_tab(hard: Session) -> None:
    """Noticed, listed, and not switched to until asked. Which tab a trail continues in is
    recorded, never guessed."""
    clear_the_banner(hard)
    first = hard.browser.page
    hard.act("open the statement", "click", ref=ref_for(hard, "Open the statement in a new tab"))
    hard.browser.page.wait_for_timeout(400)

    assert len(hard.browser.tabs) == 2
    assert hard.browser.page is first

    hard.act("continue in the new tab", "switch_tab", value="latest")
    assert hard.browser.page is not first
    assert "tab=2" in hard.browser.page.url


# ----------------------------------------------------- 8. the file input


def test_upload_with_no_visible_file_input(hard: Session, tmp_path) -> None:
    """The real input is hidden, so it cannot be attached to. Clicking the button opens
    the chooser instead — one verb covers both shapes."""
    clear_the_banner(hard)
    receipt = tmp_path / "receipt.pdf"
    receipt.write_text("not really a pdf")

    hard.act(
        "attach the receipt",
        "upload",
        ref=ref_for(hard, "Attach a receipt"),
        value=str(receipt),
    )
    assert log_says(hard) == "attached receipt.pdf"


# ------------------------------------------------- 9. the infinite scroll


def test_a_list_that_only_grows_as_you_scroll(hard: Session) -> None:
    clear_the_banner(hard)
    before = hard.browser.page.locator(".row").count()
    assert before == 10

    for _ in range(3):
        hard.act("scroll for more transactions", "scroll", value="bottom")

    assert hard.browser.page.locator(".row").count() > before


def test_reading_the_grown_list_in_one_call(hard: Session) -> None:
    """`all_text` is why this matters: one call for the whole list rather than one per row."""
    clear_the_banner(hard)
    hard.act("scroll for more transactions", "scroll", value="bottom")
    hard.act("wait for the new rows", "wait_for", value="element:.row")

    rows = hard.browser.page.locator(".row").all_inner_texts()
    assert rows[0] == "Transaction 1"
    assert len(rows) >= 10


# ------------------------------------------------------- the whole page


def test_the_whole_hard_page_in_one_journey(hard: Session, tmp_path) -> None:
    """Every awkward thing on one page, in one recorded flow.

    Nine obstacles, one run, no fixed sleeps and no model. Every one of these has broken a
    recorded flow on a real site, and before the browsing layer was rebuilt Dejo could not even see most of
    them — the snapshot found one element on a page like this.
    """
    receipt = tmp_path / "receipt.pdf"
    receipt.write_text("not really a pdf")

    # 5. The banner, learned once and never a step.
    clear_the_banner(hard)

    # 1. A dropdown with no <select> in it.
    hard.act("open the month menu", "click", ref=ref_for(hard, "Choose a month"))
    hard.act("choose September", "click", ref=ref_for(hard, "September 2026"))
    assert log_says(hard) == "picked sep"

    # 4. Content that was not there when the page loaded.
    hard.act("wait for the figures", "wait_for", value="element:#total")

    # 2. Shadow DOM.
    hard.act("press the shadow button", "click", ref=ref_for(hard, "Button in a shadow root"))
    assert log_says(hard) == "shadow button clicked"

    # 3. Inside an iframe.
    hard.act("press the button in the frame", "click", ref=ref_for(hard, "Button in a frame"))

    # 8. A hidden file input.
    hard.act(
        "attach the receipt", "upload", ref=ref_for(hard, "Attach a receipt"), value=str(receipt)
    )
    assert log_says(hard) == "attached receipt.pdf"

    # 6. A confirm box that would otherwise stop the browser dead.
    hard.act("delete the report", "click", ref=ref_for(hard, "Delete the report"))
    assert log_says(hard) == "report deleted"

    # 9. A list that only grows as you scroll.
    hard.act("scroll for more transactions", "scroll", value="bottom")

    # 7. A new tab, entered only when asked.
    hard.act("open the statement", "click", ref=ref_for(hard, "Open the statement in a new tab"))
    hard.browser.page.wait_for_timeout(400)
    hard.act("continue in the new tab", "switch_tab", value="latest")
    assert "tab=2" in hard.browser.page.url

    # Every step is on the trail, and the banner is not one of them.
    assert len(hard.trace) >= 10
    assert all("cookie" not in entry.intent.lower() for entry in hard.trace)


def test_every_step_of_that_journey_could_be_replayed(hard: Session, tmp_path) -> None:
    """A step with no way to find its element again is a step that cannot be replayed —
    which would make the journey above a demo rather than a memory."""
    clear_the_banner(hard)
    hard.act("open the month menu", "click", ref=ref_for(hard, "Choose a month"))
    hard.act("choose September", "click", ref=ref_for(hard, "September 2026"))
    hard.act("press the shadow button", "click", ref=ref_for(hard, "Button in a shadow root"))
    hard.act("press the button in the frame", "click", ref=ref_for(hard, "Button in a frame"))

    for entry in hard.trace:
        if entry.element is None:
            continue

        locators = entry.element.locators()
        assert locators, f"{entry.intent!r} recorded no way of finding its element again"

        # A ref is good for exactly one snapshot. One stored in a trail would resolve to
        # whatever happened to be in that position on the next run, which is worse than
        # failing.
        assert not any("aria-ref" in locator.value for locator in locators), (
            f"{entry.intent!r} stored a ref, which is only good for one snapshot"
        )


# ------------------------------------- learned once, on every later run


def test_the_banner_is_written_to_site_knowledge(hard: Session, store: DejoStore) -> None:
    """Registering it in the running browser is not enough — that is forgotten the moment
    the browser closes."""
    clear_the_banner(hard)
    knowledge = store.load_site_knowledge(hard.browser.page.url.split("/")[2])
    assert knowledge is not None
    assert "#accept-cookies" in knowledge.overlays


def test_learning_the_banner_is_never_a_step(hard: Session) -> None:
    """An overlay appears whenever the site decides to, not at a fixed point in a flow, so
    pinning it to a step would record an accident."""
    clear_the_banner(hard)
    assert hard.trace[-1].action == "goto"


def test_a_later_run_arms_the_banner_again(
    hard: Session, store: DejoStore, demo_server: str
) -> None:
    """The finish-line claim: dismissed automatically on EVERY later run.

    A fresh tab stands in for a later run — Playwright registers overlay handlers per page,
    so a new tab starts with none, exactly as a new browser would.
    """
    from dejo.executor import Executor

    clear_the_banner(hard)
    domain = hard.browser.page.url.split("/")[2]

    later = hard.browser.new_tab(f"{demo_server}/hard")
    assert later.locator("#cookies").count() == 1

    Executor(store, hard.browser)._arm_overlays(domain)
    later.locator("#month-button").click()
    assert later.locator("#cookies").count() == 0


def test_a_new_tab_inherits_what_the_site_is_known_for(hard: Session, demo_server: str) -> None:
    """Overlay handlers are registered per page. A flow that continues in a new tab would
    otherwise meet the banner all over again, having already "learned" it."""
    clear_the_banner(hard)

    later = hard.browser.new_tab(f"{demo_server}/hard")
    assert later.locator("#cookies").count() == 1

    later.locator("#month-button").click()
    assert later.locator("#cookies").count() == 0


# ------------------------------------ 10. a menu that only answers pointerdown


class TestAMenuThatIgnoresClick:
    """Radix opens its dropdown on `pointerdown`, never on `click`.

    shadcn/ui is built on Radix, so this is one of the most common menus on the web today.
    Reported against Dejo from a real marketplace: the menu would not open. Two things had
    to be told apart — a click that does not send real pointer events, and a selector that
    matched a menu button in every row of a table and quietly opened the wrong one.

    This pins the first. The second is pinned in test_ambiguous_selectors.py.
    """

    def test_dejo_click_sends_real_pointer_events(self, hard: Session) -> None:
        clear_the_banner(hard)
        hard.act("open the row menu", "click", ref=ref_for(hard, "Row actions"))

        opened = hard.read("attribute", ref="#pointer-menu-button", attribute="aria-expanded")
        assert opened == "true"

    def test_and_the_menu_items_are_then_there_to_act_on(self, hard: Session) -> None:
        clear_the_banner(hard)
        hard.act("open the row menu", "click", ref=ref_for(hard, "Row actions"))

        assert hard.read("visible", ref="#pointer-menu-edit") is True
