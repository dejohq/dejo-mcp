"""Every action in the registry, driven against a real browser.

The point of these tests is coverage of the list itself. `test_every_action_is_exercised`
fails if an action is added to `actions.py` and not tested here, so the registry cannot
quietly grow a member that has never been run.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from playwright.sync_api import Error as PlaywrightError

from dejo import actions
from dejo.browser import VIEWPORT, Browser

# Every control the action tests need, on one page. Written once and reused, so a failing
# test points at the action rather than at a page that was not set up right.
LAB = """
<!doctype html>
<title>action lab</title>
<style>
  body { font: 14px sans-serif; margin: 0; padding: 16px; }
  #tall { height: 3000px; }
  #far { margin-top: 2500px; }
  .zone { border: 1px solid #999; padding: 12px; min-height: 32px; }
</style>

<p id="log">nothing yet</p>

<button id="click-me" onclick="log('clicked')">Click me</button>
<button id="dbl" ondblclick="log('double clicked')">Double</button>
<button id="hover-me" onmouseenter="log('hovered')">Hover</button>
<button id="evented" onclick="log('evented')">Evented</button>

<input id="text" value="" oninput="log('typed:' + this.value)">
<input id="prefilled" value="already here">
<input id="key" onkeydown="log('key:' + event.key)">
<input id="focusable" onfocus="log('focused')" onblur="log('blurred')">

<input type="checkbox" id="box">
<input type="checkbox" id="box2" checked>

<select id="month">
  <option value="jan">January</option>
  <option value="sep">September</option>
  <option value="dec">December</option>
</select>
<select id="many" multiple>
  <option value="a">Alpha</option>
  <option value="b">Beta</option>
  <option value="c">Gamma</option>
</select>

<input type="file" id="upload">
<input type="file" id="upload-many" multiple>

<div id="drag" draggable="true">drag me</div>
<div id="zone" class="zone">drop here</div>

<p id="selectable">select this text</p>

<div id="tall"><button id="far" onclick="log('far clicked')">Far away</button></div>

<script>
  function log(message) { document.getElementById('log').textContent = message; }
  const zone = document.getElementById('zone');
  zone.addEventListener('dragover', e => e.preventDefault());
  zone.addEventListener('drop', e => { e.preventDefault(); log('dropped'); });
</script>
"""


@pytest.fixture
def lab(browser: Browser):
    """The lab page, loaded and ready."""
    browser.page.set_content(LAB)
    return browser


@pytest.fixture
def touch_browser(tmp_path) -> Iterator[Browser]:
    """A browser that reports a touchscreen, which is the only way `tap` works."""
    with Browser(headless=True, downloads=tmp_path / "downloads", touch=True) as running:
        yield running


def do(browser: Browser, action: str, selector: str | None = None, **kwargs) -> None:
    """Run one action the way `operations` does: resolve first, then perform."""
    target = browser.page.locator(selector).first if selector else None
    actions.perform(action, page=browser.page, target=target, **kwargs)


def log_says(browser: Browser) -> str:
    return browser.page.locator("#log").inner_text()


# --------------------------------------------------------------- the registry


def test_registry_and_runners_agree() -> None:
    actions.sanity_check()


def test_every_spec_names_itself() -> None:
    """The key and the spec's own name must match, or `catalogue` lies to the AI."""
    for key, spec in actions.ACTIONS.items():
        assert key == spec.name


def test_catalogue_lists_every_action() -> None:
    text = actions.catalogue()
    for name in actions.ACTIONS:
        assert name in text


def test_unknown_action_says_what_is_known() -> None:
    with pytest.raises(actions.UnknownAction) as raised:
        actions.spec_for("teleport")
    assert "click" in str(raised.value)


def test_missing_value_is_refused(lab: Browser) -> None:
    with pytest.raises(actions.ActionNeedsMore):
        do(lab, "fill", "#text")


def test_missing_target_is_refused(lab: Browser) -> None:
    with pytest.raises(actions.ActionNeedsMore):
        actions.perform("click", page=lab.page)


def test_drag_without_second_target_is_refused(lab: Browser) -> None:
    with pytest.raises(actions.ActionNeedsMore):
        do(lab, "drag", "#drag")


# ------------------------------------------------------------------- clicking


def test_click(lab: Browser) -> None:
    do(lab, "click", "#click-me")
    assert log_says(lab) == "clicked"


def test_double_click(lab: Browser) -> None:
    do(lab, "double_click", "#dbl")
    assert log_says(lab) == "double clicked"


def test_hover(lab: Browser) -> None:
    do(lab, "hover", "#hover-me")
    assert log_says(lab) == "hovered"


def test_tap_works_on_a_touch_device(touch_browser: Browser) -> None:
    touch_browser.page.set_content(LAB)
    do(touch_browser, "tap", "#click-me")
    assert log_says(touch_browser) == "clicked"


def test_tap_without_touch_explains_itself(lab: Browser) -> None:
    """The raw Playwright error mentions `hasTouch`, which means nothing to a user."""
    with pytest.raises(actions.ActionNeedsMore) as raised:
        do(lab, "tap", "#click-me")
    assert "touch" in str(raised.value).lower()


# --------------------------------------------------------------- text entry


def test_fill_replaces_what_was_there(lab: Browser) -> None:
    do(lab, "fill", "#prefilled", value="new value")
    assert lab.page.locator("#prefilled").input_value() == "new value"


def test_type_sends_real_keystrokes(lab: Browser) -> None:
    """This is why `type` exists: a search box that listens for keystrokes sees each one."""
    do(lab, "type", "#text", value="abc")
    assert lab.page.locator("#text").input_value() == "abc"
    assert log_says(lab) == "typed:abc"


def test_clear_empties_a_field(lab: Browser) -> None:
    do(lab, "clear", "#prefilled")
    assert lab.page.locator("#prefilled").input_value() == ""


def test_press(lab: Browser) -> None:
    do(lab, "press", "#key", value="Enter")
    assert log_says(lab) == "key:Enter"


def test_press_defaults_to_enter(lab: Browser) -> None:
    do(lab, "press", "#key")
    assert log_says(lab) == "key:Enter"


def test_select_text_then_type_replaces(lab: Browser) -> None:
    do(lab, "select_text", "#prefilled")
    do(lab, "type", "#prefilled", value="fresh")
    assert lab.page.locator("#prefilled").input_value() == "fresh"


# ---------------------------------------------------------------- checkboxes


def test_check_and_uncheck(lab: Browser) -> None:
    do(lab, "check", "#box")
    assert lab.page.locator("#box").is_checked()
    do(lab, "uncheck", "#box")
    assert not lab.page.locator("#box").is_checked()


def test_check_is_safe_to_repeat(lab: Browser) -> None:
    """A replay must not toggle something off by ticking it twice."""
    do(lab, "check", "#box")
    do(lab, "check", "#box")
    assert lab.page.locator("#box").is_checked()


@pytest.mark.parametrize(
    ("target", "wanted", "expected"),
    [("#box", "true", True), ("#box2", "false", False), ("#box2", "true", True)],
)
def test_set_checked_lands_on_the_value(
    lab: Browser, target: str, wanted: str, expected: bool
) -> None:
    """Unlike check/uncheck, this ends in a known state whatever it started in."""
    do(lab, "set_checked", target, value=wanted)
    assert lab.page.locator(target).is_checked() is expected


# ----------------------------------------------------------------- dropdowns


def test_select_by_value(lab: Browser) -> None:
    do(lab, "select", "#month", value="sep")
    assert lab.page.locator("#month").input_value() == "sep"


def test_select_by_label(lab: Browser) -> None:
    """The visible words change far less often than the value behind them."""
    do(lab, "select", "#month", value="label:September")
    assert lab.page.locator("#month").input_value() == "sep"


def test_select_by_index(lab: Browser) -> None:
    do(lab, "select", "#month", value="index:2")
    assert lab.page.locator("#month").input_value() == "dec"


def test_select_several(lab: Browser) -> None:
    do(lab, "select", "#many", value="a,c")
    chosen = lab.page.eval_on_selector("#many", "el => [...el.selectedOptions].map(o => o.value)")
    assert chosen == ["a", "c"]


def test_select_by_the_words_shown(lab: Browser) -> None:
    """The page view prints the words, so plain words that are not a value pick by them."""
    do(lab, "select", "#month", value="September")
    assert lab.page.locator("#month").input_value() == "sep"


def test_a_missing_option_stops_at_once_and_names_the_real_ones(lab: Browser) -> None:
    """It used to wait 15 s and raise Playwright's bare 'Timeout 15000ms exceeded'."""
    started = time.monotonic()
    with pytest.raises(actions.ActionNeedsMore) as refused:
        do(lab, "select", "#month", value="Octember")
    assert time.monotonic() - started < 2
    assert '"Octember"' in str(refused.value)
    assert '"January", "September", "December"' in str(refused.value)


def test_select_options_parsing() -> None:
    months = [("jan", "January"), ("sep", "September")]
    letters = [("a", "Alpha"), ("b", "Beta")]
    assert actions._select_options("sep", months) == {"value": ["sep"]}
    assert actions._select_options("September", months) == {"label": ["September"]}
    assert actions._select_options("label:September", months) == {"label": ["September"]}
    assert actions._select_options("index:1", months) == {"index": [1]}
    assert actions._select_options("value:sep", months) == {"value": ["sep"]}
    assert actions._select_options("a, b", letters) == {"value": ["a", "b"]}
    assert actions._select_options("a,label:Beta", letters) == {"value": ["a"], "label": ["Beta"]}
    for wrong in ("index:2", "value:September", "label:sep"):
        with pytest.raises(actions.ActionNeedsMore):
            actions._select_options(wrong, months)


def test_a_long_option_list_is_named_in_part() -> None:
    many = [(str(n), f"Country {n}") for n in range(249)]
    with pytest.raises(actions.ActionNeedsMore) as refused:
        actions._select_options("Atlantis", many)
    assert '"Country 29" and 219 more' in str(refused.value)


# -------------------------------------------------------------------- files


def test_upload(lab: Browser, tmp_path) -> None:
    invoice = tmp_path / "invoice.pdf"
    invoice.write_text("not really a pdf")
    do(lab, "upload", "#upload", value=str(invoice))
    name = lab.page.eval_on_selector("#upload", "el => el.files[0].name")
    assert name == "invoice.pdf"


def test_upload_several(lab: Browser, tmp_path) -> None:
    first = tmp_path / "one.txt"
    second = tmp_path / "two.txt"
    first.write_text("1")
    second.write_text("2")
    do(lab, "upload", "#upload-many", value=f"{first},{second}")
    count = lab.page.eval_on_selector("#upload-many", "el => el.files.length")
    assert count == 2


def test_upload_says_which_file_is_missing(lab: Browser, tmp_path) -> None:
    """Playwright's own error for this is a timeout, which hides the real cause."""
    with pytest.raises(actions.ActionNeedsMore) as raised:
        do(lab, "upload", "#upload", value=str(tmp_path / "nope.pdf"))
    assert "nope.pdf" in str(raised.value)


# ----------------------------------------------------------------- scrolling


def test_scroll_to_brings_an_element_into_view(lab: Browser) -> None:
    do(lab, "scroll_to", "#far")
    assert lab.page.locator("#far").is_visible()
    do(lab, "click", "#far")
    assert log_says(lab) == "far clicked"


def test_scroll_down_then_top(lab: Browser) -> None:
    do(lab, "scroll", value="down")
    assert lab.page.evaluate("window.scrollY") > 0
    do(lab, "scroll", value="top")
    assert lab.page.evaluate("window.scrollY") == 0


def test_scroll_by_pixels(lab: Browser) -> None:
    do(lab, "scroll", value="300")
    assert lab.page.evaluate("window.scrollY") == pytest.approx(300, abs=2)


def test_scroll_rejects_nonsense(lab: Browser) -> None:
    with pytest.raises(actions.ActionNeedsMore):
        do(lab, "scroll", value="sideways")


# ------------------------------------------------------------ focus and drag


def test_focus_and_blur(lab: Browser) -> None:
    do(lab, "focus", "#focusable")
    assert log_says(lab) == "focused"
    do(lab, "blur", "#focusable")
    assert log_says(lab) == "blurred"


def test_drag(lab: Browser) -> None:
    target = lab.page.locator("#zone").first
    actions.perform("drag", page=lab.page, target=lab.page.locator("#drag").first, second=target)
    assert log_says(lab) == "dropped"


def test_dispatch_event(lab: Browser) -> None:
    do(lab, "dispatch_event", "#evented", value="click")
    assert log_says(lab) == "evented"


def test_highlight_changes_nothing(lab: Browser) -> None:
    """It draws a box for a watching human. Replaying it later would mean nothing, which
    is why it is marked unrecordable."""
    do(lab, "highlight", "#click-me")
    do(lab, "hide_highlight")
    assert log_says(lab) == "nothing yet"
    assert not actions.ACTIONS["highlight"].recordable
    assert not actions.ACTIONS["hide_highlight"].recordable


# ------------------------------------------------------------------ the page


def test_goto_back_forward_reload(lab: Browser, demo_server: str) -> None:
    do(lab, "goto", value=f"{demo_server}/")
    first = lab.page.url
    do(lab, "goto", value=f"{demo_server}/?variant=b")
    assert lab.page.url != first

    do(lab, "back")
    assert lab.page.url == first
    do(lab, "forward")
    assert "variant=b" in lab.page.url
    do(lab, "reload")
    assert "variant=b" in lab.page.url


def test_wait(lab: Browser) -> None:
    do(lab, "wait", value="0.05")


def test_viewport_is_fixed(lab: Browser) -> None:
    """A trail recorded at one width is unreplayable at another, because the nav collapses
    into a hamburger below a breakpoint."""
    assert lab.page.viewport_size == VIEWPORT


# -------------------------------------------------------------- settle + seam


def test_settle_survives_a_navigation(lab: Browser, demo_server: str) -> None:
    """Waiting for load while the page is being replaced is normal, not a failure."""
    do(lab, "goto", value=f"{demo_server}/")
    lab.settle()
    assert lab.page.url


def test_actions_never_search_for_elements() -> None:
    """`actions.py` performs; it must never locate. If it starts calling `get_by_*` or
    `page.locator`, the seam that lets locators become frame-aware has been broken."""
    with open(actions.__file__, encoding="utf-8") as handle:
        source = handle.read()
    body = source.split(
        "# ------------------------------------------------------------------ performing"
    )[1]
    for forbidden in ("page.locator(", "get_by_role(", "get_by_text(", "query_selector("):
        assert forbidden not in body, f"actions.py should not resolve elements: {forbidden}"


# ------------------------------------------------------------------ coverage

# Actions proved by a test above. `test_every_action_is_exercised` compares this against
# the registry, so adding an action without a test fails the suite.
EXERCISED = {
    "click",
    "double_click",
    "hover",
    "tap",
    "fill",
    "type",
    "clear",
    "press",
    "select_text",
    "check",
    "uncheck",
    "set_checked",
    "select",
    "upload",
    "scroll_to",
    "scroll",
    "focus",
    "blur",
    "drag",
    "dispatch_event",
    "highlight",
    "hide_highlight",
    "goto",
    "back",
    "forward",
    "reload",
    "wait",
    # Covered in tests/test_page_events.py, which is where the browser events live.
    "wait_for",
    "switch_tab",
    # Covered in tests/test_context.py, with the rest of the browser-context work.
    "new_tab",
    # Covered in tests/test_hard_page.py, against a real cookie banner.
    "dismiss_when_seen",
    # Covered in tests/test_answers.py, against the PostHog trail that recorded its own
    # recovery from a stuck menu.
    "restart_trail",
    # Covered in tests/test_escape_hatch.py.
    "evaluate",
    "screenshot",
    "set_time",
}


def test_every_action_is_exercised() -> None:
    untested = sorted(set(actions.ACTIONS) - EXERCISED)
    assert not untested, f"these actions have no test: {untested}"


def test_playwright_error_is_still_raised(lab: Browser) -> None:
    """Dejo translates the errors it can explain better. Everything else must come
    through unchanged rather than being swallowed."""
    with pytest.raises(PlaywrightError):
        lab.page.set_default_timeout(300)
        do(lab, "click", "#does-not-exist")


def test_press_without_an_element_goes_to_the_page(lab: Browser) -> None:
    """Closing a modal or a stuck menu with Escape has nothing sensible to point at. On
    PostHog the host AI needed exactly this and had to aim it at some element instead."""
    lab.page.set_content(
        "<p id='log'>nothing yet</p>"
        "<script>document.addEventListener('keydown', e => "
        "{ document.getElementById('log').textContent = 'page key:' + e.key; });</script>"
    )
    actions.perform("press", page=lab.page, value="Escape")
    assert log_says(lab) == "page key:Escape"


def test_a_combobox_that_drew_nothing_says_so_with_no_empty_list() -> None:
    """launchit.site: a combobox with no options printed "Its options are ."."""
    said = actions._no_options_appeared("Go", "opens", [])
    assert said.startswith("opened it, and no options appeared, nor anything else to click")
    assert "options are" not in said
