"""Every way Dejo can act on an element.

This is a registry, not a chain of `if` statements. Each action carries what it needs, what
its value means, and how to prove it landed — so the MCP tool description, the replay
dispatcher and the postcondition defaults all read from one place. Adding an action means
adding one entry.

Full audit of what is here and what was deliberately left out: `docs/BROWSING.md`.

Two rules hold throughout:

- **Nothing here resolves an element.** An action is handed an already-resolved Playwright
  locator. That keeps this file independent of how targets are found, which matters because
  the snapshot layer is being replaced underneath it.
- **An action that changes nothing is not recorded.** `highlight` draws a box for a human
  watching; replaying it later would be meaningless. Those are marked `recordable=False`.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator as PWLocator
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from . import waits

# What a step should check afterwards when the caller does not say. "observed" means work it
# out from what actually changed on the page, which is what `distill` already does.
OBSERVED = "observed"

DEFAULT_WAIT_SECONDS = 0.3
MS_PER_SECOND = 1000
SCREENS_PER_SCROLL = 0.9  # just under a full screen, so nothing scrolls past unseen
SCREENS_TO_REACH_END = 40  # far enough to hit either end of any ordinary page
FALLBACK_VIEWPORT_HEIGHT = 720

# A <select>'s options as [value, label] pairs, or null for anything that is not one.
_SELECT_OPTIONS_JS = (
    "el => el.tagName === 'SELECT' ? [...el.options].map(o => [o.value, o.label]) : null"
)
# Is this checkbox or radio hidden, or covered where it would be clicked, by its own label
# (or by something wrapping that label)? Then the label is the thing to click.
_COVERED_BY_OWN_LABEL_JS = """
el => {
  const labels = [...(el.labels || [])];
  const wrap = el.closest("label");
  if (wrap && !labels.includes(wrap)) labels.push(wrap);
  if (!labels.length) return false;
  const style = getComputedStyle(el);
  if (el.hidden || style.display === "none" || style.visibility === "hidden") return true;
  el.scrollIntoView({block: "center"});
  const box = el.getBoundingClientRect();
  if (!box.width || !box.height) return true;
  const top = el.ownerDocument.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
  if (!top || top === el || el.contains(top)) return false;
  return labels.some(label => label === top || label.contains(top) || top.contains(label));
}
"""
_CLICK_OWN_LABEL_JS = "el => (el.labels && el.labels[0] || el.closest('label')).click()"

# How a step writes a line break, and the fields that can hold one.
NEW_LINE = "\\n"
_HOLDS_LINES_JS = "el => el.tagName === 'TEXTAREA' || el.isContentEditable"

# How a dropdown that is not a <select> is chosen in: "typed" into (react-select's text
# box with role=combobox), "opens" when clicked (a button with role=combobox or a listbox
# popup), or null for anything else. How long its option gets to be drawn.
_COMBOBOX_JS = """
el => {
  const typed = el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable;
  const combo = (el.getAttribute("role") || "").toLowerCase() === "combobox"
    || el.getAttribute("aria-haspopup") === "listbox" || !!el.closest("[role=combobox]");
  return combo ? (typed ? "typed" : "opens") : null;
}
"""
OPTION_WAIT_MS = 3000
# The options a combobox shows: in the list it says it controls, else anywhere in its own
# document (react-select draws its menu beside the box, others in a portal at the end).
_OPTIONS_OF = """
const optionsOf = (el) => {
  const doc = el.ownerDocument;
  const id = el.getAttribute("aria-controls") || el.getAttribute("aria-owns");
  const list = (id && doc.getElementById(id)) || doc;
  return [...list.querySelectorAll("[role=option]")].filter((o) => o.getClientRects().length);
};
const said = (o) => (o.getAttribute("aria-label") || o.textContent || "").trim();
"""
# The option whose words are exactly `value`, once it is drawn, or null after `ms`.
_OPTION_JS = (
    "(el, [value, ms]) => {"
    + _OPTIONS_OF
    + """
  return new Promise((done) => {
    const began = Date.now();
    const look = () => {
      const hit = optionsOf(el).find((o) => said(o) === value);
      if (hit || Date.now() - began > ms) return done(hit || null);
      setTimeout(look, 50);
    };
    look();
  });
}"""
)
_OPTIONS_SHOWN_JS = "(el) => {" + _OPTIONS_OF + "return optionsOf(el).map(said).filter(Boolean); }"
# What a combobox may draw instead of options. launchit.site's "Built with" suggests plain
# buttons ("JavaScript +"), so only what can be clicked, and only what was not on show
# before the box was typed into, is what the box drew.
_SHOWN_CLICKABLES = """
const shown = (doc) => [...doc.querySelectorAll(
  "button, a[href], [role=button], [role=link], [role=menuitem]"
)].filter((c) => c.getClientRects().length);
"""
_NOTE_CLICKABLES_JS = (
    "(el) => {"
    + _SHOWN_CLICKABLES
    + "el.ownerDocument.defaultView.__dejoShownBefore = new WeakSet(shown(el.ownerDocument)); }"
)
_NEW_CLICKABLES_JS = (
    "(el) => {"
    + _SHOWN_CLICKABLES
    + """
  const before = el.ownerDocument.defaultView.__dejoShownBefore || new WeakSet();
  return shown(el.ownerDocument)
    .filter((c) => c !== el && !before.has(c))
    .map((c) => {
      const kind = c.matches("a[href], [role=link]") ? "link" : "button";
      const words = (c.getAttribute("aria-label") || c.innerText || c.textContent || "")
        .replace(/\\s+/g, " ").trim().slice(0, 60);
      return words ? `${kind} "${words}"` : "";
    })
    .filter(Boolean);
}"""
)

# Options named when the one asked for is not there: enough to see what kind of list it is.
OPTIONS_NAMED = 30

# Actions that press something, so they can buy, send or delete. The rest only move, type
# or look.
PRESSES = frozenset({"click", "double_click", "tap", "dispatch_event"})

# How long a click gets to open the file chooser. A site opens it at once, or never.
CHOOSER_WAIT_MS = 5000

# Resolves once the browser has drawn twice, which is when a scroll has been committed.
_TWO_FRAMES = "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"


@dataclass(frozen=True)
class ActionSpec:
    """One thing Dejo can do, and everything the rest of the code needs to know about it."""

    name: str
    summary: str
    needs_target: bool = True
    value_means: str | None = None
    needs_second_target: bool = False
    recordable: bool = True
    verifies_with: str = OBSERVED
    session_handled: bool = False
    """Carried out by the Session rather than here, because it needs something Playwright
    alone does not have — the list of tabs Dejo is keeping track of. Declared in the
    registry so one list still describes every action."""

    def describe(self) -> str:
        """One line for the tool description an AI reads."""
        parts = [f"{self.name} — {self.summary}"]
        if self.value_means:
            parts.append(f"value = {self.value_means}")
        if self.needs_second_target:
            parts.append("needs `to` as well as `ref`")
        if not self.needs_target:
            parts.append("no ref needed")
        return "; ".join(parts)


# ---------------------------------------------------------------- the registry

ACTIONS: dict[str, ActionSpec] = {
    "click": ActionSpec(
        "click",
        "click a link, button or anything clickable",
    ),
    "double_click": ActionSpec(
        "double_click",
        "double click, for grids and file lists that open on two clicks",
    ),
    "hover": ActionSpec(
        "hover",
        "move the pointer over something, for menus that only open on hover",
    ),
    "fill": ActionSpec(
        "fill",
        "put text into a field, replacing whatever is there",
        value_means="the text to put in",
        verifies_with="value_is",
    ),
    "type": ActionSpec(
        "type",
        "type one key at a time. Use instead of fill for search and autocomplete boxes, "
        "which ignore a value that appears all at once because they listen for keystrokes",
        value_means="the text to type",
        verifies_with="value_is",
    ),
    "clear": ActionSpec(
        "clear",
        "empty a field. Do this before typing into a field that already has something in "
        "it, or the two values run together",
        verifies_with="value_is",
    ),
    "press": ActionSpec(
        "press",
        "press a key. With a ref it goes to that element; without one it goes to the page, "
        "which is how you close a modal or a stuck menu with Escape",
        needs_target=False,
        value_means='a key such as "Enter", "Escape", "Tab", or a combination like "Control+A"',
    ),
    "check": ActionSpec(
        "check",
        "tick a checkbox or radio button. Does nothing if it is already ticked",
        verifies_with="checked_is",
    ),
    "uncheck": ActionSpec(
        "uncheck",
        "untick a checkbox. Does nothing if it is already unticked",
        verifies_with="checked_is",
    ),
    "set_checked": ActionSpec(
        "set_checked",
        "tick or untick to match a value, whatever state it started in",
        value_means='"true" or "false"',
        verifies_with="checked_is",
    ),
    "select": ActionSpec(
        "select",
        "choose from a dropdown",
        value_means=(
            "the option: plain text matches the value behind it, or else the words shown; "
            '"label:September" matches only the words, "index:2" the position, and commas '
            "pick several at once"
        ),
        verifies_with="value_is",
    ),
    "upload": ActionSpec(
        "upload",
        "attach a file to a file input",
        value_means="the full path to the file, or several paths separated by commas",
    ),
    "scroll_to": ActionSpec(
        "scroll_to",
        "scroll until something is on screen, for long or lazily loaded lists",
        verifies_with="element_visible",
    ),
    "drag": ActionSpec(
        "drag",
        "drag one element onto another, for reordering and kanban boards",
        needs_second_target=True,
    ),
    "focus": ActionSpec(
        "focus",
        "put the cursor in a field without typing. Some forms only validate on focus",
    ),
    "blur": ActionSpec(
        "blur",
        "take the cursor out of a field, which is what makes many forms validate",
    ),
    "tap": ActionSpec(
        "tap",
        "a touch tap rather than a mouse click. Only works when the browser is emulating "
        "a touch device",
    ),
    "select_text": ActionSpec(
        "select_text",
        "select the text inside an element, usually so the next thing typed replaces it",
    ),
    "dispatch_event": ActionSpec(
        "dispatch_event",
        "fire a raw DOM event. LAST RESORT — it skips the checks that make a normal click "
        "trustworthy, so it can act on something invisible or not ready. Try click, hover "
        "or press first",
        value_means='the event name, such as "click" or "change"',
    ),
    "highlight": ActionSpec(
        "highlight",
        "draw a box around an element so a watching human can see it. Changes nothing",
        recordable=False,
    ),
    "hide_highlight": ActionSpec(
        "hide_highlight",
        "remove the box drawn by highlight. Changes nothing",
        needs_target=False,
        recordable=False,
    ),
    # ---- page level: these act on the whole page, so they take no element -------
    "goto": ActionSpec(
        "goto",
        "open a web address",
        needs_target=False,
        value_means="the full url",
        verifies_with="url_contains",
    ),
    "back": ActionSpec(
        "back",
        "go back one page in history",
        needs_target=False,
        verifies_with="url_contains",
    ),
    "forward": ActionSpec(
        "forward",
        "go forward one page in history",
        needs_target=False,
        verifies_with="url_contains",
    ),
    "reload": ActionSpec(
        "reload",
        "reload the current page",
        needs_target=False,
    ),
    "scroll": ActionSpec(
        "scroll",
        "scroll the page itself, for feeds that load more as you go",
        needs_target=False,
        value_means='"down", "up", "top", "bottom", or a number of pixels',
    ),
    "evaluate": ActionSpec(
        "evaluate",
        "run your own JavaScript on the page and get the result back. THE ESCAPE HATCH — "
        "when a site does something none of the actions above covers, write the code "
        "yourself instead of giving up. With a ref it runs on that element (given as "
        "`el`); without one it runs on the page. NOT REMEMBERED: a step made of code "
        "cannot be repaired when the site changes, so use a real action for anything that "
        "belongs in the trail",
        needs_target=False,
        value_means="the JavaScript, e.g. `() => document.title` or `el => el.dataset.id`",
        recordable=False,
    ),
    "screenshot": ActionSpec(
        "screenshot",
        "save a picture of the page, or of one element. For showing a human what happened",
        needs_target=False,
        value_means="where to save it. Leave empty for an automatic name",
        recordable=False,
    ),
    "set_time": ActionSpec(
        "set_time",
        "tell the page it is a different date and time. For a dashboard whose numbers "
        "depend on today — a trail recorded in September otherwise reads the wrong month "
        "in October",
        needs_target=False,
        value_means='a date such as "2026-09-15" or "2026-09-15T10:00:00"',
        session_handled=True,
    ),
    "restart_trail": ActionSpec(
        "restart_trail",
        "forget the steps recorded so far and start the trail from here. The browser stays "
        "exactly where it is. USE THIS BEFORE SAVING if you went the wrong way, undid "
        "something, or recovered from a mistake — everything you did is being written down, "
        "and a saved mistake gets replayed forever. Explore however you like, then restart "
        "and walk the task once, cleanly",
        needs_target=False,
        recordable=False,
        session_handled=True,
    ),
    "dismiss_when_seen": ActionSpec(
        "dismiss_when_seen",
        "clear something that covers the page whenever it appears — a cookie banner, a "
        '"rate us" box, a survey. Learned once against the SITE, so it never becomes a '
        "step and never has to be handled again on any later run",
        needs_target=False,
        value_means="a CSS selector for the thing to click, such as #accept-cookies",
        recordable=False,
        session_handled=True,
    ),
    "new_tab": ActionSpec(
        "new_tab",
        "open a new empty tab and continue in it",
        needs_target=False,
        value_means="a url to open in it, or nothing for a blank tab",
        session_handled=True,
    ),
    "switch_tab": ActionSpec(
        "switch_tab",
        'continue in another tab. A site that opens a new tab — "open in new tab", most '
        "sign-in-with-Google flows — leaves the trail in the old one until you move",
        needs_target=False,
        value_means='"latest", "main", or a tab number starting at 0',
        session_handled=True,
    ),
    "wait_for": ActionSpec(
        "wait_for",
        "wait until something is actually true. THE RIGHT WAY TO WAIT — a page that loads "
        "its content late is the most common reason a run fails",
        needs_target=False,
        value_means=(
            "what to wait for, as kind:subject — "
            + ", ".join(
                f"{spec.name}:..." if spec.needs_value else spec.name
                for spec in waits.WAITS.values()
            )
        ),
    ),
    "wait": ActionSpec(
        "wait",
        "wait a fixed number of seconds. LAST RESORT — prefer wait_for. A fixed wait is "
        "either too short and flaky or too long and slow on every run forever",
        needs_target=False,
        value_means="seconds",
    ),
}


class UnknownAction(ValueError):
    """Asked for an action that does not exist."""


class ActionNeedsMore(ValueError):
    """The action was understood but something it requires was not given."""


def spec_for(action: str) -> ActionSpec:
    try:
        return ACTIONS[action]
    except KeyError:
        known = ", ".join(sorted(ACTIONS))
        raise UnknownAction(f"no action called {action!r}. Known actions: {known}") from None


def catalogue() -> str:
    """The whole action list as one block of text, for the MCP tool description.

    Generated rather than written by hand, so a new action can never be missing from the
    description an AI reads.
    """
    return "\n".join(f"  {spec.describe()}" for spec in ACTIONS.values())


# ------------------------------------------------------------------ performing


def perform(
    action: str,
    *,
    page: Page,
    target: PWLocator | None = None,
    value: str | None = None,
    second: PWLocator | None = None,
) -> Any:
    """Do one thing, and hand back whatever it answered.

    The element, when one is needed, is already resolved — this function never searches for
    it. Playwright's own actionability checks (visible, stable, enabled, able to receive
    events) run inside each call below, which is why Dejo does not reimplement waiting.
    """
    spec = spec_for(action)

    if spec.needs_target and target is None:
        raise ActionNeedsMore(f"{action} needs an element to act on")
    if spec.needs_second_target and second is None:
        raise ActionNeedsMore(f"{action} needs a second element, given as `to`")
    if spec.value_means and value is None and action not in _VALUE_OPTIONAL:
        raise ActionNeedsMore(f"{action} needs a value: {spec.value_means}")

    # Most actions answer nothing. `evaluate` and `screenshot` do, so the return travels.
    return _RUNNERS[action](page, target, value, second)


# Each runner has the same shape so the registry can call them without special cases.
# `_T` is the resolved element, absent for page-level actions.
_T = PWLocator


def _click(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    t.click()


def _double_click(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    t.dblclick()


def _hover(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    t.hover()


def _fill(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    t.fill(_lines_for(t, value or ""))


def _type(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    # One key at a time. Search and autocomplete boxes listen for keystrokes and ignore a
    # value that simply appears, which is exactly what `fill` does.
    t.press_sequentially(_lines_for(t, value or ""))


def _lines_for(t: _T, text: str) -> str:
    """`\\n` written in a step, as a real new line where the field can hold one.

    A step is one line, so a description with several lines can only be written with `\\n`,
    and it went in as a backslash and an n (launchingnext.com). A one-line box cannot hold a
    new line, and a backslash there may be meant, so it keeps what was written."""
    if NEW_LINE not in text or not t.evaluate(_HOLDS_LINES_JS):
        return text
    return text.replace(NEW_LINE, "\n")


def _clear(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    t.clear()


def _press(page: Page, t: _T | None, value: str | None, second: _T | None) -> None:
    key = value or "Enter"
    if t is not None:
        t.press(key)
        return
    # No element named: send it to whatever has focus. Closing a modal with Escape is the
    # normal case, and there is nothing sensible to point at when you do it.
    page.keyboard.press(key)


def _check(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    _tick(t, True)


def _uncheck(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    _tick(t, False)


def _set_checked(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    _tick(t, _as_bool(value))


def _tick(t: _T, wanted: bool) -> None:
    """Tick or untick, through the box's own label when that is what is on show.

    Sites style a checkbox by laying its label over the real box, or by hiding the box and
    drawing one in the label. Playwright then refuses: "<label> intercepts pointer events"
    (agenticskills.io), or it waits for the hidden box to be seen. A person clicks the label,
    and so does this. Anything else in the way is still reported as covering it."""
    if t.evaluate(_COVERED_BY_OWN_LABEL_JS):
        if t.is_checked() != wanted:
            t.evaluate(_CLICK_OWN_LABEL_JS)
        if t.is_checked() != wanted:
            raise ActionNeedsMore(
                "clicking this box's label did not change it. The page may draw its own box "
                "elsewhere: look at the page and click what shows the tick."
            )
        return
    t.set_checked(wanted)


def _select(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    # Read the options first. `select_option` waits its whole timeout for an option that is
    # not there and then raises Playwright's bare "Timeout 15000ms exceeded", which tells
    # the agent nothing about what it could have picked.
    options = t.evaluate(_SELECT_OPTIONS_JS)
    if options is None:
        _pick_from_a_combobox(t, value or "")
        return
    if not t.is_enabled():
        # Playwright waits its whole timeout for a disabled dropdown to become usable, and
        # then says only "Timeout 15000ms exceeded".
        raise ActionNeedsMore(
            "this dropdown is disabled, so nothing can be chosen in it yet. Something else on "
            "the page usually has to be done first: look at the page for what."
        )
    chosen = _select_options(value or "", options)
    # Choices.js, nice-select and many sites hide the real <select> and draw a menu of their
    # own that listens to it. Playwright waits for a hidden one to be seen, which never
    # happens (fewservers.com timed out by option and by label). Choosing in it is what the
    # site's own menu does, and it fires the same change the menu listens for.
    t.select_option(**chosen, force=not t.is_visible())


def _pick_from_a_combobox(t: _T, value: str) -> None:
    """Choose in a dropdown that is not a <select>: type into it (react-select's text box)
    or open it (a Radix or Headless UI button), then click the option with these words.

    Half the dropdowns on the modern web are built this way, and `select` used to give up on
    all of them with "click the button" (launchit.site)."""
    how = t.evaluate(_COMBOBOX_JS)
    if how is None:
        raise ActionNeedsMore(
            "this is not a dropdown Dejo can choose in: neither a <select> nor a combobox. "
            "Click it, then look at the page again and click the option you want."
        )
    t.evaluate(_NOTE_CLICKABLES_JS)
    t.click()
    if how == "typed":
        t.fill("")
        t.press_sequentially(value)
    # Found from the box itself, never by searching the page, so a box in a frame finds the
    # options in its own frame.
    found = t.evaluate_handle(_OPTION_JS, [value, OPTION_WAIT_MS]).as_element()
    if found is not None:
        found.click()
        return
    shown = t.evaluate(_OPTIONS_SHOWN_JS)
    if shown:
        raise ActionNeedsMore(_no_such_option([value], shown))
    raise ActionNeedsMore(_no_options_appeared(value, how, t.evaluate(_NEW_CLICKABLES_JS)))


def _upload(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    paths = [Path(part.strip()) for part in (value or "").split(",") if part.strip()]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ActionNeedsMore(f"no file at {', '.join(missing)}")

    # Two shapes of the same task. Plenty of sites hide the real file input and show a
    # styled button instead, so attaching to the element directly is not always possible;
    # clicking it opens the operating system's file chooser, which Playwright can catch.
    if _is_file_input(t):
        t.set_input_files(paths)
        _check_the_box_kept(t.element_handle(), paths)
        return
    try:
        with page.expect_file_chooser(timeout=CHOOSER_WAIT_MS) as caught:
            t.click()
    except PlaywrightTimeout:
        raise ActionNeedsMore(
            "clicking this opened no file chooser, so the file went nowhere. Upload onto the "
            "page's file box itself: look raw for a button named Choose File or Browse."
        ) from None
    caught.value.set_files(paths)
    _check_the_box_kept(caught.value.element, paths)


def _check_the_box_kept(box: Any, paths: list[Path]) -> None:
    """Fail unless the file box still holds the files once the page has looked at them.

    A site checks a file the moment it arrives and empties the box when it does not like
    it, saying nothing: devhunt.org's "Select an image" took the upload, reported done, and
    showed no logo. What the box accepts is the likeliest reason, so it is named."""
    kept, accepts = box.evaluate("el => [el.files ? el.files.length : 0, el.accept || '']")
    if kept >= len(paths):
        return
    takes = f" It takes only {accepts}." if accepts else ""
    raise ActionNeedsMore(
        f"the page's file box did not keep {', '.join(path.name for path in paths)}: it took "
        f"the file and then emptied itself.{takes} Send a file it accepts."
    )


def _is_file_input(target: _T) -> bool:
    if target.count() == 0:
        return False
    tag = (target.evaluate("el => el.tagName") or "").lower()
    kind = (target.get_attribute("type") or "").lower()
    return tag == "input" and kind == "file"


def _scroll_to(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    t.scroll_into_view_if_needed()


def _drag(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    assert second is not None  # guaranteed by perform()
    t.drag_to(second)


def _focus(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    t.focus()


def _blur(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    t.blur()


def _tap(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    try:
        t.tap()
    except PlaywrightError as refused:
        if "hasTouch" not in str(refused):
            raise
        raise ActionNeedsMore(
            "tap needs a touch device. Start the browser with touch=True, or use click "
            "instead — on most sites click does the same thing."
        ) from refused


def _select_text(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    t.select_text()


def _dispatch_event(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    t.dispatch_event(value or "click")


def _highlight(page: Page, t: _T, value: str | None, second: _T | None) -> None:
    t.highlight()


def _hide_highlight(page: Page, t: _T | None, value: str | None, second: _T | None) -> None:
    page.hide_highlight()


def _goto(page: Page, t: _T | None, value: str | None, second: _T | None) -> None:
    page.goto(value or "")


def _back(page: Page, t: _T | None, value: str | None, second: _T | None) -> None:
    page.go_back()


def _forward(page: Page, t: _T | None, value: str | None, second: _T | None) -> None:
    page.go_forward()


def _reload(page: Page, t: _T | None, value: str | None, second: _T | None) -> None:
    page.reload()


def _scroll(page: Page, t: _T | None, value: str | None, second: _T | None) -> None:
    size = page.viewport_size or {"width": 1280, "height": FALLBACK_VIEWPORT_HEIGHT}
    # A wheel event only moves whatever is under the pointer, and the pointer starts in the
    # top-left corner. Centring it also means the wheel lands on the main panel rather than
    # on some narrow strip at the edge of the page.
    page.mouse.move(size["width"] / 2, size["height"] / 2)
    page.mouse.wheel(0, _scroll_amount(page, value))
    _wait_for_scroll(page)


def _wait_for_scroll(page: Page) -> None:
    """Let the browser actually apply the scroll before anything reads the page.

    `mouse.wheel` returns before the scroll is committed, so reading the position straight
    afterwards gives the position from *before* the scroll. On an infinite feed that means
    scrolling and then immediately reading the same rows again, forever.

    Two animation frames is enough for the commit, and unlike waiting for the position to
    change it is still correct at the very bottom of a page, where scrolling moves nothing.
    """
    page.evaluate(_TWO_FRAMES)


def _wait(page: Page, t: _T | None, value: str | None, second: _T | None) -> None:
    page.wait_for_timeout(float(value or DEFAULT_WAIT_SECONDS) * MS_PER_SECOND)


def _wait_for(page: Page, t: _T | None, value: str | None, second: _T | None) -> None:
    waits.wait_for(value or "idle", page=page)


def _evaluate(page: Page, t: _T | None, value: str | None, second: _T | None) -> Any:
    """Run the caller's own JavaScript.

    On the element when one is given, on the page otherwise. Playwright serialises the
    result back, so anything JSON-shaped comes through.
    """
    if t is not None:
        return t.evaluate(value or "el => el")
    return page.evaluate(value or "() => null")


def _screenshot(page: Page, t: _T | None, value: str | None, second: _T | None) -> str:
    where = Path(value) if value else Path.cwd() / f"dejo-{int(time.time())}.png"
    where.parent.mkdir(parents=True, exist_ok=True)
    if t is not None:
        t.screenshot(path=where)
    else:
        page.screenshot(path=where, full_page=True)
    return str(where)


def _set_time(page: Page, t: _T | None, value: str | None, second: _T | None) -> None:
    # Unreachable: the Session handles it, because the clock belongs to the whole context.
    raise AssertionError("set_time should have been handled by the session")


def _restart_trail(page: Page, t: _T | None, value: str | None, second: _T | None) -> None:
    # Unreachable: the Session owns the trail, so it handles this before we get here.
    raise AssertionError("restart_trail should have been handled by the session")


def _dismiss_when_seen(page: Page, t: _T | None, value: str | None, second: _T | None) -> None:
    # Unreachable: the Session handles it, because it also has to reach memory.
    raise AssertionError("dismiss_when_seen should have been handled by the session")


def _new_tab(page: Page, t: _T | None, value: str | None, second: _T | None) -> None:
    # Unreachable, like _switch_tab: the Session owns the tab list.
    raise AssertionError("new_tab should have been handled by the session")


def _switch_tab(page: Page, t: _T | None, value: str | None, second: _T | None) -> None:
    # Unreachable: `Session._perform` handles every `session_handled` action before it gets
    # here. Present so the registry and the runner table stay in step.
    raise AssertionError("switch_tab should have been handled by the session")


_RUNNERS: dict[str, Any] = {
    "click": _click,
    "double_click": _double_click,
    "hover": _hover,
    "fill": _fill,
    "type": _type,
    "clear": _clear,
    "press": _press,
    "check": _check,
    "uncheck": _uncheck,
    "set_checked": _set_checked,
    "select": _select,
    "upload": _upload,
    "scroll_to": _scroll_to,
    "drag": _drag,
    "focus": _focus,
    "blur": _blur,
    "tap": _tap,
    "select_text": _select_text,
    "dispatch_event": _dispatch_event,
    "highlight": _highlight,
    "hide_highlight": _hide_highlight,
    "goto": _goto,
    "back": _back,
    "forward": _forward,
    "reload": _reload,
    "scroll": _scroll,
    "wait": _wait,
    "wait_for": _wait_for,
    "switch_tab": _switch_tab,
    "new_tab": _new_tab,
    "dismiss_when_seen": _dismiss_when_seen,
    "restart_trail": _restart_trail,
    "evaluate": _evaluate,
    "screenshot": _screenshot,
    "set_time": _set_time,
}

# These have a sensible default, so a missing value is not an error.
_VALUE_OPTIONAL = {
    "press",
    "dispatch_event",
    "scroll",
    "wait",
    "new_tab",
    "wait_for",
    "screenshot",
}


# -------------------------------------------------------------------- helpers


def _scroll_amount(page: Page, value: str | None) -> float:
    """Turn a written scroll instruction into a number of pixels."""
    height = page.viewport_size["height"] if page.viewport_size else FALLBACK_VIEWPORT_HEIGHT
    word = (value or "down").strip().lower()
    if word in {"down", ""}:
        return height * SCREENS_PER_SCROLL
    if word == "up":
        return -height * SCREENS_PER_SCROLL
    if word == "bottom":
        return height * SCREENS_TO_REACH_END
    if word == "top":
        return -height * SCREENS_TO_REACH_END
    try:
        return float(word)
    except ValueError:
        raise ActionNeedsMore(
            f'cannot scroll by {value!r} — use "down", "up", "top", "bottom" or a number'
        ) from None


def _as_bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "on", "checked"}


def _select_options(value: str, options: Sequence[Sequence[str]]) -> dict[str, Any]:
    """Turn one written value into keyword arguments for `select_option`, checked against
    the dropdown's real `(value, label)` options.

    A dropdown option can be picked by the value behind it, by the words a person actually
    sees, or by position. Sites change the hidden value far more often than the visible
    label, so `label:September` is the more durable way to record a choice. Plain text is
    the value if one matches, else the words shown: the page view prints the words, and
    `select e3 "Python"` failed on a value of `python`.

    Playwright's Python API takes these as separate keyword arguments. The list-of-dicts
    form works only in JavaScript, and here it fails without saying why.
    """
    known_values = [v for v, _ in options]
    known_labels = [label for _, label in options]
    values: list[str] = []
    labels: list[str] = []
    indexes: list[int] = []
    missing: list[str] = []

    for part in (piece.strip() for piece in value.split(",")):
        if not part:
            continue
        if part.startswith("label:"):
            wanted, found, into = part[len("label:") :], known_labels, labels
        elif part.startswith("index:"):
            position = int(part[len("index:") :])
            (indexes if 0 <= position < len(options) else missing).append(position)
            continue
        elif part.startswith("value:"):
            wanted, found, into = part[len("value:") :], known_values, values
        elif part in known_values:
            wanted, found, into = part, known_values, values
        else:
            wanted, found, into = part, known_labels, labels
        (into if wanted in found else missing).append(wanted)

    if missing:
        raise ActionNeedsMore(_no_such_option(missing, known_labels))

    chosen: dict[str, Any] = {}
    if values:
        chosen["value"] = values
    if labels:
        chosen["label"] = labels
    if indexes:
        chosen["index"] = indexes
    return chosen


def _no_such_option(missing: list[str | int], labels: list[str]) -> str:
    shown = ", ".join(f'"{label}"' for label in labels[:OPTIONS_NAMED])
    more = f" and {len(labels) - OPTIONS_NAMED} more" if len(labels) > OPTIONS_NAMED else ""
    asked = ", ".join(f'"{m}"' if isinstance(m, str) else f"index:{m}" for m in missing)
    return (
        f"this dropdown has no option {asked}. Its options are {shown}{more}. "
        "Send the step again with one of them, written as it is shown."
    )


def _no_options_appeared(value: str, how: str, appeared: list[str]) -> str:
    """Why a combobox chose nothing when it drew no options at all, and what it drew instead.

    Its empty list of options was printed as "Its options are ." (launchit.site)."""
    did = f'typed "{value}" into it' if how == "typed" else "opened it"
    if not appeared:
        return (
            f"{did}, and no options appeared, nor anything else to click. Look at the page: "
            "the box may want other words, or be filled another way."
        )
    listed = " · ".join(appeared[:OPTIONS_NAMED])
    more = f" and {len(appeared) - OPTIONS_NAMED} more" if len(appeared) > OPTIONS_NAMED else ""
    again = f'fill the box with "{value}"' if how == "typed" else "click the box"
    return (
        f"{did}, and no options appeared. What appeared instead: {listed}{more}. To choose "
        f"with those, {again}, then click the one you want."
    )


def sanity_check() -> None:
    """Every action in the registry has a runner, and every runner is in the registry.

    Called by a test. Without it, adding an action to one and not the other fails only when
    somebody happens to use it.
    """
    missing_runner = sorted(set(ACTIONS) - set(_RUNNERS))
    missing_spec = sorted(set(_RUNNERS) - set(ACTIONS))
    if missing_runner or missing_spec:
        raise AssertionError(
            f"action registry out of step — no runner for {missing_runner}, "
            f"no spec for {missing_spec}"
        )
