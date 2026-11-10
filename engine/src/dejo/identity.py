"""Which account is signed in, read off the page the way a person would.

A trail learned as finance@acme.com and replayed in a browser signed in as someone else does
the right steps for the wrong person: it downloads their invoice, or posts as them. The
session is the browser's, not the trail's, so nothing in the steps can tell.

So while learning, Dejo notes what the page itself says about who is signed in: an email
address in the site's header or account menu, the name on the account button, or "Signed in
as ...". Only what a person can see on the screen (or what the account button says to a
screen reader) is kept, never a cookie, a token or a password. Before a replay, and after
any sign-in step, Dejo looks for that same marker. If the page names someone else, the run
stops before doing anything, and says who was expected and who is signed in. If the page
names nobody, Dejo says nothing: plenty of sites never show who you are.

Plain Playwright and JavaScript, no memory and no model, so it is safe on the replay path.
"""

from __future__ import annotations

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

# The longest marker kept. A name or an email address fits; anything longer is a sentence
# that happened to sit in the account menu, not a name.
MARKER_CHARS = 80

# How long one look at the page may take. It is a few DOM reads, so a page that does not
# answer in this time is navigating, and has no marker to give yet.
LOOK_MS = 3000

# Reads who is signed in, or null. Evidence first: a sign-out control (often in a closed
# menu, so it need not be visible), "signed in as" on show, or an account button on show.
# Without evidence nothing is read, so a contact address on a signed-out page is never taken
# for an account. Then, in order: "signed in as NAME"; an email address on an account button's
# label; an email address on show in the header, navigation or an account menu; the words on
# an account button that are not just "Account" or "Profile".
_MARKER_JS = """
(limit) => {
  const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}/;
  const SIGNED_IN = /\\b(?:signed|logged) in as\\s*:?\\s*(.+)/i;
  const ACCOUNT = /account|profile|avatar|user menu|signed in|logged in|your menu|my menu/i;
  const GENERIC = new RegExp("^(account|my account|your account|profile|your profile|menu|" +
    "user|me|avatar|settings|open user menu|user menu|account menu|open account menu)$", "i");
  const shown = (n) => {
    const b = n.getBoundingClientRect(), s = getComputedStyle(n);
    return b.width > 0 && b.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };
  const squeeze = (s) => (s || "").replace(/\\s+/g, " ").trim();
  const labelOf = (n) => squeeze(n.getAttribute("aria-label") || n.getAttribute("alt") ||
    n.getAttribute("title") || "");
  const controls = [...document.querySelectorAll(
    "a, button, [role=button], [role=menuitem], input[type=submit], img, [aria-haspopup]")];
  const SIGN_OUT = /^(sign|log)\\s?-?\\s?out\\b|^logout$|^signout$/i;
  const signsOut = controls.some((n) =>
    SIGN_OUT.test(squeeze(n.innerText || n.value || labelOf(n))));
  // A real account control opens a menu, is an avatar, or carries an email in its label. A
  // plain link that only mentions "account" is not one: on Google's "Choose an account"
  // page (10 Nov) a "Help" link labelled "Google Account Help" was kept as the account.
  const accountButtons = controls.filter((n) => shown(n) && ACCOUNT.test(labelOf(n)) &&
    (n.hasAttribute("aria-haspopup") || n.hasAttribute("aria-expanded") ||
     n.tagName === "IMG" || /avatar/i.test(labelOf(n)) || EMAIL.test(labelOf(n))));
  const body = document.body ? document.body.innerText : "";
  const said = body.split("\\n").map(squeeze).find((line) => SIGNED_IN.test(line));
  if (!signsOut && !said && !accountButtons.length) return null;
  const fit = (s) => {
    s = squeeze(s).replace(/[.,;]+$/, "");
    return s && s.length <= limit ? s : null;
  };
  if (said) {
    const name = fit(said.match(SIGNED_IN)[1]);
    if (name) return name;
  }
  for (const n of accountButtons) {
    const found = labelOf(n).match(EMAIL);
    if (found) return found[0];
  }
  const places = document.querySelectorAll(
    "header, nav, [role=banner], [role=navigation], [role=menu], [aria-label*=account i]");
  for (const place of places) {
    if (!shown(place)) continue;
    const found = (place.innerText || "").match(EMAIL);
    if (found) return found[0];
  }
  for (const n of accountButtons) {
    const words = fit(n.innerText);
    if (words && !GENERIC.test(words)) return words;
    const label = labelOf(n);
    const named = fit(label.includes(":") ? label.split(":").slice(1).join(":") : "");
    if (named && !GENERIC.test(named)) return named;
  }
  return null;
}
"""

# Does the page say this marker anywhere a person or a screen reader would meet it?
_SHOWS_JS = """
(marker) => {
  const wanted = marker.toLowerCase();
  if ((document.body ? document.body.innerText : "").toLowerCase().includes(wanted)) return true;
  for (const n of document.querySelectorAll("[aria-label], [alt], [title]")) {
    const said = (n.getAttribute("aria-label") || n.getAttribute("alt") ||
      n.getAttribute("title") || "").toLowerCase();
    if (said.includes(wanted)) return true;
  }
  return false;
}
"""


def marker_on(page: Page) -> str | None:
    """Who the page says is signed in, or None when it does not say."""
    try:
        found = page.evaluate(_MARKER_JS, MARKER_CHARS)
    except PlaywrightError:
        # A page being replaced has nothing to say yet.
        return None
    return found or None


def shows(page: Page, marker: str) -> bool:
    """Does the page show this marker?"""
    try:
        return bool(page.evaluate(_SHOWS_JS, marker))
    except PlaywrightError:
        return False


def someone_else(page: Page, expected: str) -> str | None:
    """The account the page names instead of `expected`, or None.

    None both when the page shows `expected` and when it names nobody: only a page that
    clearly names a different account is a reason to stop."""
    if shows(page, expected):
        return None
    current = marker_on(page)
    if current is None or current.casefold() == expected.casefold():
        return None
    return current
