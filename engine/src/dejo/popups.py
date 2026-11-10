"""Clearing a pop-up nobody told Dejo about, before it breaks a step.

A trail is learned on one visit and replayed on another, and the second visit is often the
one that shows a newsletter box, a consent banner or a "rate us" card. Playwright's
`add_locator_handler` only clears what Dejo already knows about, and only when it is
visible BEFORE an action starts. Anything new covers the step's target, and the click
either waits out its whole timeout ("... intercepts pointer events") or lands on the
pop-up instead.

So when a step's target is covered, this module tries a few moves that cannot do harm, in
this order, and stops at the first that uncovers the target:

  1. a close control inside the covering element: "Close", "No thanks", "Not now", "x"...
  2. the Escape key, which closes most modal dialogs;
  3. a consent banner's own button, preferring "Reject all" or "Necessary only" to "Accept".

It never presses anything that reads like buying, paying, sending, deleting, submitting,
subscribing or signing up, and never a button that sends a form with fields in it (a
newsletter box's "Subscribe" is exactly that). When nothing safe works, the caller stops
exactly as it would have without this.

Plain Playwright and JavaScript, no memory and no model: the caller decides what to report
and what to remember. That keeps it usable on the replay path.
"""

from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Frame, Page
from playwright.sync_api import Locator as PWLocator

# Actions that press or point at their element, so a pop-up over it gets in the way. A fill
# or a read does not care what is drawn on top.
POINTER_ACTIONS = frozenset(
    {"click", "double_click", "tap", "hover", "drag", "check", "uncheck", "set_checked"}
)

# Written into a known-overlay entry for a pop-up only Escape closes. A plain entry is a
# selector to click; this one names the pop-up, and the handler presses Escape on sight.
PRESS_ESCAPE = "press Escape on "

# What Playwright says when another element would receive the click.
COVERED_TELL = "intercepts pointer events"

# How long one clearing click may take. A close button is either there and clickable at
# once, or it is not the way out; waiting the page's whole timeout would only stall.
CLEAR_CLICK_MS = 2000

# How long a pop-up gets to finish leaving after a move, before the target is looked at
# again. Most close with a fade or a slide of 150-300 ms.
LEAVE_MS = 600
LEAVE_POLL_MS = 100

# How long a pop-up that has got out of the target's way gets to finish leaving. Bootstrap
# and most libraries animate a dialog out in 150-300 ms.
GONE_MS = 1500

# How long scrolling the target into view may take before the covered check is skipped.
SCROLL_MS = 1500

# The attribute a candidate is marked with so Playwright can click exactly that element.
# Removed again as soon as the moves are done.
MARK = "data-dejo-clear"

# Words a close control says, as its whole label, in the order they are tried: an explicit
# "close" before a polite refusal, and the bare symbols last, since an "x" is the likeliest
# to mean something else. Matched exactly, after lower-casing and squeezing spaces, so
# "Close account" is never taken for "Close".
CLOSE_WORDS = (
    "close",
    "close dialog",
    "close modal",
    "close popup",
    "close pop-up",
    "close banner",
    "close this",
    "dismiss",
    "no thanks",
    "no, thanks",
    "no thank you",
    "no, thank you",
    "not now",
    "maybe later",
    "not interested",
    "skip",
    "×",
    "✕",
    "✖",
    "╳",
    "x",
)

# Consent platforms' own buttons, by the ids and attributes the platforms ship with. Reject
# first: declining is what a person who did not ask to be tracked would choose.
CONSENT_REJECT = (
    "#onetrust-reject-all-handler",
    "#CybotCookiebotDialogBodyButtonDecline",
    "#didomi-notice-disagree-button",
    "#truste-consent-required",
    "[data-testid=uc-deny-all-button]",
    ".osano-cm-denyAll",
    ".cky-btn-reject",
    ".cmplz-deny",
    "[data-tid=banner-decline]",
    ".cm-btn-decline",
    ".qc-cmp2-summary-buttons button[mode=secondary]",
)
CONSENT_ACCEPT = (
    "#onetrust-accept-btn-handler",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowallSelection",
    "#didomi-notice-agree-button",
    "#truste-consent-button",
    "[data-testid=uc-accept-all-button]",
    ".osano-cm-accept-all",
    ".cky-btn-accept",
    ".cmplz-accept",
    "[data-tid=banner-accept]",
    ".cm-btn-accept-all",
    ".qc-cmp2-summary-buttons button[mode=primary]",
)

# The same choice in words, for a banner no platform id names. Reject words first.
CONSENT_REJECT_WORDS = (
    "reject all",
    "reject",
    "decline all",
    "decline",
    "deny",
    "refuse",
    "necessary only",
    "only necessary",
    "necessary cookies only",
    "use necessary cookies only",
    "essential only",
    "only essential",
    "continue without accepting",
)
CONSENT_ACCEPT_WORDS = (
    "accept all",
    "accept all cookies",
    "allow all",
    "accept",
    "accept cookies",
    "accept and continue",
    "agree and continue",
    "consent and continue",
    "accept & continue",
    "agree",
    "i agree",
    "got it",
    "ok",
)

# A banner is only treated as a consent banner when it says one of these.
CONSENT_TELLS = ("cookie", "consent", "privacy", "tracking")

# Words that mean a press does something that cannot be taken back. Never pressed while
# clearing, whatever else the control says. Checked as whole words.
RISKY = (
    "buy",
    "purchase",
    "pay",
    "checkout",
    "order",
    "send",
    "submit",
    "post",
    "publish",
    "delete",
    "remove",
    "subscribe",
    "unsubscribe",
    "sign up",
    "signup",
    "register",
    "join",
    "upgrade",
    "trial",
    "donate",
    "confirm",
    "transfer",
)
_RISKY = re.compile(r"\b(" + "|".join(re.escape(word) for word in RISKY) + r")\b", re.IGNORECASE)

# What covers the target's middle, and the pop-up that thing belongs to. A cover that is
# part of the target, or a label of it, is not a pop-up. The pop-up is the nearest box
# around the cover that is a dialog, or fixed or sticky on the screen, and is not the site's
# own header or navigation, and does not hold the target itself. Marked for Playwright.
_COVER_JS = """
(el, [mark]) => {
  const root = el.getRootNode();
  const at = (root.elementFromPoint ? root : document);
  const box = el.getBoundingClientRect();
  if (!box.width || !box.height) return null;
  const x = box.left + box.width / 2, y = box.top + box.height / 2;
  if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return null;
  const top = at.elementFromPoint(x, y);
  if (!top) return null;
  const up = (n) => n.parentElement || (n.getRootNode() && n.getRootNode().host) || null;
  for (let n = el; n; n = up(n)) if (n === top) return null;
  for (let n = top; n; n = up(n)) if (n === el) return null;
  if (top.tagName === "LABEL" && (top.control === el || top.contains(el))) return null;
  const holds = (n) => { for (let m = el; m; m = up(m)) if (m === n) return true; return false; };
  const dialog = (n) => n.tagName === "DIALOG" || n.getAttribute("aria-modal") === "true" ||
    ["dialog", "alertdialog"].includes((n.getAttribute("role") || "").toLowerCase());
  const chrome = (n) => ["HEADER", "NAV"].includes(n.tagName) ||
    ["banner", "navigation"].includes((n.getAttribute("role") || "").toLowerCase());
  let popup = null;
  for (let n = top; n && n !== document.body && n !== document.documentElement; n = up(n)) {
    if (holds(n)) break;
    const position = getComputedStyle(n).position;
    if (dialog(n) || position === "fixed" || position === "sticky") {
      if (chrome(n)) return null;
      popup = n;
    }
  }
  if (!popup) return null;
  if (mark) popup.setAttribute(mark, "popup");
  const named = popup.getAttribute("aria-label") ||
    (popup.querySelector("h1,h2,h3,h4,[role=heading]") || {}).innerText || "";
  const words = (popup.innerText || "").replace(/\\s+/g, " ").trim();
  return { name: named.replace(/\\s+/g, " ").trim().slice(0, 60), words: words.slice(0, 400) };
}
"""

# Every control inside the pop-up whose whole label is one of `words`, in the order the
# words are given, marked for Playwright, each with a selector that finds it again on a
# later visit (or "" when nothing durable names it). Controls that send a form with fields
# in it are left out: that is how a newsletter box takes an address.
_CANDIDATES_JS = """
(popup, [words, mark, risky]) => {
  const risk = new RegExp(risky, "i");
  const squeeze = (s) => (s || "").replace(/\\s+/g, " ").trim().toLowerCase();
  const said = (n) => (n.getAttribute("aria-label") || n.getAttribute("title") ||
    n.innerText || n.value || "").replace(/\\s+/g, " ").trim();
  const labelOf = (n) => squeeze(said(n));
  const shown = (n) => {
    const b = n.getBoundingClientRect(), s = getComputedStyle(n);
    return b.width > 0 && b.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };
  const sendsFields = (n) => {
    const form = n.form || n.closest("form");
    if (!form) return false;
    const type = (n.getAttribute("type") || "").toLowerCase();
    const submits = (n.tagName === "BUTTON" && (type === "" || type === "submit")) ||
      (n.tagName === "INPUT" && (type === "submit" || type === "image"));
    return submits && !!form.querySelector(
      "input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea");
  };
  const css = (s) => CSS.escape(s);
  const stable = (s) => s && !/[0-9]{3,}/.test(s);
  // Only what names THIS pop-up. "Any dialog's Close button" would also close a dialog the
  // trail opens on purpose (demoqa.com: the large modal, closed as soon as it opened).
  const popupPath = () => {
    if (stable(popup.id)) return "#" + css(popup.id);
    for (const name of ["aria-label", "aria-labelledby"]) {
      const said = popup.getAttribute(name);
      if (said) return "[" + name + "=" + JSON.stringify(said) + "]";
    }
    return "";
  };
  const pathOf = (n) => {
    const base = popupPath();
    if (stable(n.id)) return base ? base + " #" + css(n.id) : "#" + css(n.id);
    if (!base) return "";
    const aria = n.getAttribute("aria-label");
    if (aria) return base + " [aria-label=" + JSON.stringify(aria) + "]";
    return base + " " + n.tagName.toLowerCase() + ":text-is(" + JSON.stringify(
      (n.innerText || "").trim()) + ")";
  };
  const pool = [...popup.querySelectorAll(
    "button, a, [role=button], input[type=button], input[type=submit], [aria-label], " +
    "[onclick], span, div, p")];
  const found = [];
  const before = document.querySelectorAll("[" + mark + "^=c]").length;
  for (const word of words) {
    for (const n of pool) {
      if (n.hasAttribute(mark) || !shown(n)) continue;
      const label = labelOf(n);
      if (label !== word || risk.test(label) || sendsFields(n)) continue;
      const index = "c" + (before + found.length);
      n.setAttribute(mark, index);
      found.push({ index, label: said(n), path: pathOf(n) });
    }
  }
  return found;
}
"""

# Marks every banner on show that is fixed on the screen or a dialog and talks about cookies
# or consent, outermost only, and says how many it marked.
_CONSENT_BANNERS_JS = """
([mark, tells]) => {
  const marked = [];
  for (const n of document.querySelectorAll("body *")) {
    const s = getComputedStyle(n);
    const pinned = s.position === "fixed" || s.position === "sticky" ||
      ["dialog", "alertdialog"].includes(n.getAttribute("role") || "") || n.tagName === "DIALOG";
    if (!pinned || s.display === "none" || s.visibility === "hidden") continue;
    if (marked.some((m) => m.contains(n))) continue;
    const words = (n.innerText || "").toLowerCase();
    if (!tells.some((t) => words.includes(t))) continue;
    n.setAttribute(mark, "banner-" + marked.length);
    marked.push(n);
  }
  return marked.length;
}
"""

# Takes every mark this module left on the page back off.
_UNMARK_JS = """
(mark) => {
  for (const n of document.querySelectorAll("[" + mark + "]")) n.removeAttribute(mark);
}
"""


@dataclass(frozen=True)
class Cleared:
    """What was cleared and how, for the reply, and what to remember for next time."""

    what: str
    """In words, as `"Join our newsletter" closed by its "No thanks" button`."""
    remember: str | None = None
    """An entry for the site's known overlays, so a later run clears it up front. None
    when nothing names the pop-up durably enough to find it again."""
    done: bool = True
    """False when a pop-up covers the target and no safe move cleared it. The caller then
    stops as it would have anyway, and does not try again for the same step."""


def covered_error(failed: BaseException) -> bool:
    """Did Playwright give up because something else would receive the press?"""
    return COVERED_TELL in str(failed)


def clear_the_way(page: Page, target: PWLocator) -> Cleared | None:
    """Uncover `target` with the first safe move that works. None when no pop-up covers it;
    `done=False` when one does and nothing safe uncovered it."""
    try:
        cover = _cover(target)
        if cover is None:
            return None
        popup = page.locator(f"[{MARK}=popup]").first
        return (
            _close_inside(page, target, popup, cover)
            or _inside_frames(page, target, popup, cover)
            or _escape(page, target, popup, cover)
            or _consent(page, target, popup, cover)
            or Cleared(f"{_named(cover)} covers it, and nothing safe cleared it", done=False)
        )
    finally:
        with suppress(PlaywrightError):
            page.evaluate(_UNMARK_JS, MARK)


def _cover(target: PWLocator) -> dict[str, str] | None:
    """The pop-up over the target's middle, as its name and its words, or None."""
    with suppress(PlaywrightError):
        target.scroll_into_view_if_needed(timeout=SCROLL_MS)
    try:
        return target.evaluate(_COVER_JS, [MARK])
    except PlaywrightError:
        # The target went away or the page is navigating: nothing to clear here.
        return None


def _named(cover: dict[str, str]) -> str:
    return f'"{cover["name"]}"' if cover.get("name") else "a pop-up"


def _close_inside(
    page: Page, target: PWLocator, popup: PWLocator, cover: dict[str, str]
) -> Cleared | None:
    for candidate in _candidates(popup, list(CLOSE_WORDS)):
        durable = _durable(page, candidate)
        if _press(page, candidate, target):
            return Cleared(f'{_named(cover)} closed by its "{candidate["label"]}" control', durable)
    return None


def _inside_frames(
    page: Page, target: PWLocator, popup: PWLocator, cover: dict[str, str]
) -> Cleared | None:
    """The same safe moves inside a frame the pop-up holds (or is).

    Consent platforms such as Sourcepoint ask inside their own iframe, so every button is
    in the frame and none is in the page (theguardian.com and spiegel.de, 10 Nov): a search
    of the page alone found nothing and the step stopped. A close word first, then the
    consent words, reject before accept; the risky-word rule is the same. What is pressed in
    a frame is not remembered: a page selector cannot name it, so it is cleared again each
    run, the same way."""
    try:
        handles = popup.locator("iframe").element_handles()
        if popup.evaluate("(n) => n.tagName") == "IFRAME":
            handles.insert(0, popup.element_handle())
    except PlaywrightError:
        return None
    words = [*CLOSE_WORDS, *CONSENT_REJECT_WORDS, *CONSENT_ACCEPT_WORDS]
    for handle in handles:
        try:
            frame = handle.content_frame()
        except PlaywrightError:
            continue
        if frame is None:
            continue
        try:
            for candidate in _candidates(frame.locator("body"), words):
                if _press(frame, candidate, target):
                    return Cleared(f'{_named(cover)} answered with "{candidate["label"]}"')
        finally:
            with suppress(PlaywrightError):
                frame.evaluate(_UNMARK_JS, MARK)
    return None


def _escape(
    page: Page, target: PWLocator, popup: PWLocator, cover: dict[str, str]
) -> Cleared | None:
    path = _popup_path(page, popup)
    with suppress(PlaywrightError):
        page.keyboard.press("Escape")
    if not _left(page, target):
        return None
    remember = PRESS_ESCAPE + path if path else None
    return Cleared(f"{_named(cover)} closed with the Escape key", remember)


def _consent(
    page: Page, target: PWLocator, popup: PWLocator, cover: dict[str, str]
) -> Cleared | None:
    """A consent platform's own button anywhere on the page, then the same choice in words
    inside the pop-up, or inside any banner on the page that talks about cookies: a
    platform often dims the page with one element and asks in another."""
    for selector in (*CONSENT_REJECT, *CONSENT_ACCEPT):
        button = page.locator(selector).first
        try:
            if not button.is_visible():
                continue
            label = (button.inner_text(timeout=CLEAR_CLICK_MS) or selector).strip()
        except PlaywrightError:
            continue
        if _RISKY.search(label):
            continue
        with suppress(PlaywrightError):
            button.click(timeout=CLEAR_CLICK_MS)
            if _left(page, target):
                return Cleared(f'a consent banner answered with "{label}"', selector)
    words = [*CONSENT_REJECT_WORDS, *CONSENT_ACCEPT_WORDS]
    asks = any(tell in cover.get("words", "").lower() for tell in CONSENT_TELLS)
    scopes = [popup] if asks else []
    try:
        banners = page.evaluate(_CONSENT_BANNERS_JS, [MARK, list(CONSENT_TELLS)])
    except PlaywrightError:
        banners = 0
    scopes += [page.locator(f'[{MARK}="banner-{n}"]').first for n in range(banners)]
    for scope in scopes:
        for candidate in _candidates(scope, words):
            durable = _durable(page, candidate)
            if _press(page, candidate, target):
                return Cleared(f'a consent banner answered with "{candidate["label"]}"', durable)
    return None


def _candidates(popup: PWLocator, words: list[str]) -> list[dict[str, str]]:
    try:
        return popup.evaluate(_CANDIDATES_JS, [words, MARK, _RISKY.pattern])
    except PlaywrightError:
        return []


def _press(where: Page | Frame, candidate: dict[str, str], target: PWLocator) -> bool:
    """Press one marked candidate, in the page or the frame it was marked in, and say
    whether the target is uncovered now."""
    try:
        where.locator(f'[{MARK}="{candidate["index"]}"]').first.click(timeout=CLEAR_CLICK_MS)
    except PlaywrightError:
        return False
    page = where if isinstance(where, Page) else where.page
    return _left(page, target)


def _left(page: Page, target: PWLocator) -> bool:
    """Has the pop-up got out of the target's way, allowing for it fading out?

    Uncovered is not enough on its own: a dialog that is fading out often lets the pointer
    through already, and a press that lands while it is still leaving can be swallowed by
    the page (demoqa.com's modals ignored it). So once the target is uncovered, the pop-up
    gets a moment more to be gone for good."""
    waited = 0
    while waited <= LEAVE_MS:
        try:
            if target.evaluate(_COVER_JS, [None]) is None:
                _finish_leaving(page)
                return True
        except PlaywrightError:
            return False
        with suppress(PlaywrightError):
            page.wait_for_timeout(LEAVE_POLL_MS)
        waited += LEAVE_POLL_MS
    return False


def _finish_leaving(page: Page) -> None:
    """Wait, up to GONE_MS, for the marked pop-up to be off the page or out of sight."""
    popup = page.locator(f"[{MARK}=popup]")
    with suppress(PlaywrightError):
        popup.first.wait_for(state="hidden", timeout=GONE_MS)
    # Some dialogs fade the last of the way after they are hidden from the pointer.
    with suppress(PlaywrightError):
        page.wait_for_timeout(LEAVE_POLL_MS)


def _durable(page: Page, candidate: dict[str, str]) -> str | None:
    """The candidate's selector, when it finds exactly this one thing. Asked before the
    press: a selector that matches several would click whichever comes first next time."""
    path = candidate.get("path") or ""
    if not path:
        return None
    try:
        return path if page.locator(path).count() == 1 else None
    except PlaywrightError:
        return None


def _popup_path(page: Page, popup: PWLocator) -> str:
    """A selector for the pop-up itself, read while it is still marked and on the page."""
    try:
        path = popup.evaluate(
            """(n) => n.id && !/[0-9]{3,}/.test(n.id) ? "#" + CSS.escape(n.id)
                 : n.getAttribute("aria-label")
                   ? "[aria-label=" + JSON.stringify(n.getAttribute("aria-label")) + "]" : "" """
        )
        return path if path and page.locator(path).count() == 1 else ""
    except PlaywrightError:
        return ""
