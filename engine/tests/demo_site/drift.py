"""The drift lab: pages that are different on the next visit, the way real sites are.

A trail is learned on one visit and replayed on another, and real sites rarely show the same
thing twice: a newsletter box appears on the second visit, a consent banner comes and goes,
a toast is there one time and not the next. Each page here counts its visits in a cookie, so
learning is visit one and every replay is a later visit, with no flag to set by hand. A test
that wants a particular visit starts a fresh browser, or clears the cookie.

    /drift/newsletter  a newsletter box over the page on every visit after the first
    /drift/escape      a "rate us" box with nothing to click, closed only by Escape
    /drift/consent     a consent banner dimming the page on every visit after the first;
                       ?kind=words gives one that no consent platform's id names
    /drift/locked      a box whose only button subscribes: nothing safe clears it
    /drift/dialogs     two dialogs alike but for their titles, one left open over the other's
                       button
    /drift/toast       a toast on show, then not there, then already faded out by itself;
                       ?kind=fade fades when closed, ?kind=say says "Dismissed" first
    /drift/button      a button whose words and class change after the first visit
    /drift/list        a shop list in a different order on every visit after the first
    /drift/late        a button drawn from data that arrives late after the first visit
    /drift/session     answers 401 once the session has run out (cookie lab-session=gone)
    /drift/workspace   sends the visitor to Google's account chooser once it has run out
    /drift/start       shows an identifier-first sign-in form once it has run out
    /drift/account/... two accounts, finance@acme.com and riya@acme.com, signed in by
                       whose password is typed, each shown in the header when signed in

What the page did is written where a test can read it: `#log`, and `window.lab`.
"""

from __future__ import annotations

import asyncio
import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

router = APIRouter(prefix="/drift")

# Long enough to outlive any test, short enough that nothing lingers in a real browser.
VISIT_COOKIE_S = 3600

STYLE = """
  body { font: 15px/1.5 system-ui, sans-serif; margin: 0; padding: 40px; }
  .cover { position: fixed; inset: 0; background: rgba(0, 0, 0, .45); display: flex;
           align-items: center; justify-content: center; z-index: 10 }
  .cover[hidden] { display: none }
  .box { background: #fff; padding: 24px; border-radius: 10px; width: 320px }
  .bar { position: fixed; left: 0; right: 0; bottom: 0; background: #222; color: #fff;
         padding: 16px; z-index: 11 }
"""


# A visit count is a small number; anything else a cookie says is read as a first visit.
MAX_VISITS = 1000


def _visits(request: Request, name: str) -> int:
    """How many times this browser has been to this page before."""
    try:
        seen = int(request.cookies.get(f"lab-{name}", "0"))
    except ValueError:
        return 0
    return seen if 0 <= seen <= MAX_VISITS else 0


def _page(request: Request, name: str, title: str, body: str) -> HTMLResponse:
    """One lab page, with its visit counted for next time."""
    response = HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{title} · Drift lab</title><style>{STYLE}</style></head>
<body><script>window.lab = {{}};</script>{body}<p id="log"></p></body></html>"""
    )
    response.set_cookie(
        f"lab-{name}", str(_visits(request, name) + 1), max_age=VISIT_COOKIE_S, path="/"
    )
    return response


_PRICE = """<h1>Plans</h1>
<button type="button" onclick="price.textContent = '£12 a month'">Show the price</button>
<p id="price"></p>"""


@router.get("/newsletter", response_class=HTMLResponse)
def newsletter(request: Request) -> HTMLResponse:
    """A newsletter box that covers the page on every visit after the first. Its own
    "Subscribe" sends the form; "No thanks" only closes it."""
    box = (
        """<div class="cover" role="dialog" aria-modal="true" aria-label="Join our newsletter">
             <div class="box"><h2>Join our newsletter</h2>
               <form onsubmit="event.preventDefault(); window.lab.subscribed = true;
                               log.textContent = 'subscribed'">
                 <input type="email" placeholder="you@example.com">
                 <button>Subscribe</button>
               </form>
               <button type="button" onclick="this.closest('.cover').remove()">No thanks</button>
             </div></div>"""
        if _visits(request, "newsletter")
        else ""
    )
    return _page(request, "newsletter", "Plans", _PRICE + box)


@router.get("/escape", response_class=HTMLResponse)
def escape(request: Request) -> HTMLResponse:
    """A "rate us" box on every visit after the first, with stars to press and nothing that
    closes it but the Escape key."""
    box = (
        """<div class="cover" id="rate-us">
             <div class="box"><h2>Enjoying Plans?</h2>
               <span onclick="window.lab.rated = true">★★★★★</span></div></div>
           <script>
             addEventListener("keydown", (e) => {
               if (e.key === "Escape") document.getElementById("rate-us")?.remove();
             });
           </script>"""
        if _visits(request, "escape")
        else ""
    )
    return _page(request, "escape", "Plans", _PRICE + box)


@router.get("/consent", response_class=HTMLResponse)
def consent(request: Request, kind: str = "platform") -> HTMLResponse:
    """A consent banner on every visit after the first, dimming the page with one element
    and asking in another, as consent platforms do. Each answer is written to `#log`."""
    answer = "window.lab.consent = '{0}'; log.textContent = '{0}'; banner.remove()"
    if kind == "words":
        ids = ("", "")
    else:
        ids = (' id="onetrust-accept-btn-handler"', ' id="onetrust-reject-all-handler"')
    banner = (
        f"""<div id="banner">
             <div class="cover"></div>
             <div class="bar">We use cookies to improve your visit.
               <button type="button"{ids[0]} onclick="{answer.format("accepted")}">
                 Accept all</button>
               <button type="button"{ids[1]} onclick="{answer.format("rejected")}">
                 Reject all</button></div></div>"""
        if _visits(request, f"consent-{kind}")
        else ""
    )
    return _page(request, f"consent-{kind}", "Plans", _PRICE + banner)


@router.get("/locked", response_class=HTMLResponse)
def locked(request: Request) -> HTMLResponse:
    """A box on every visit after the first whose only way out is to subscribe. Nothing
    safe clears it, so a replay has to stop where it always would have."""
    box = (
        """<div class="cover" role="dialog" aria-modal="true" aria-label="Members only">
             <div class="box"><h2>Members only</h2>
               <form onsubmit="event.preventDefault(); window.lab.subscribed = true">
                 <input type="email" placeholder="you@example.com">
                 <button>Subscribe</button>
               </form></div></div>"""
        if _visits(request, "locked")
        else ""
    )
    return _page(request, "locked", "Plans", _PRICE + box)


# How long the "say" toast shows "Dismissed" before it goes, in milliseconds.
DISMISSED_FOR_MS = 400

# How each kind of toast leaves when its close is pressed.
_LEAVES = {
    "plain": "toast.remove()",
    "fade": "toast.style.opacity = 0",
    "say": f"toast.firstChild.textContent = 'Dismissed '; setTimeout(() => toast.remove(), "
    f"{DISMISSED_FOR_MS})",
}


@router.get("/toast", response_class=HTMLResponse)
def toast(request: Request, kind: str = "plain") -> HTMLResponse:
    """A "Saved" toast, pinned to a corner away from the page's button, in a three-visit
    cycle: on show, then not there at all, then there but already faded out by itself.
    `kind` says how it leaves when closed: removed at once, faded out and left in the page,
    or first saying "Dismissed" and removed a moment later."""
    visit = _visits(request, f"toast-{kind}") % 3
    style = "opacity: 0" if visit == 2 else "opacity: 1"
    shown = (
        f"""<div id="toast" role="status" style="position: fixed; top: 12px; right: 12px;
                  transition: opacity .2s; {style}">Saved
             <button type="button" aria-label="Close" onclick="{_LEAVES.get(kind, "")}">×</button>
           </div>"""
        if visit != 1
        else ""
    )
    return _page(request, f"toast-{kind}", "Plans", _PRICE + shown)


# The lab's two accounts: who owns which password, and the name on their account button.
# The site signs in whoever owns the password typed, as many real sites with one shared
# sign-in page for several accounts effectively do.
ACCOUNTS = {
    "hunter2": ("finance@acme.com", "Finance Team"),
    "riya-pass": ("riya@acme.com", "Riya Sharma"),
}
ACCOUNT_COOKIE = "lab-account"


@router.get("/account/sign-in", response_class=HTMLResponse)
def account_sign_in(request: Request) -> HTMLResponse:
    """Signs in whoever owns the password typed, then goes to the account's invoices."""
    owners = {password: email for password, (email, _name) in ACCOUNTS.items()}
    return _page(
        request,
        "account-sign-in",
        "Sign in",
        f"""<h1>Sign in</h1>
           <label>Email <input type="email" id="email"></label>
           <label>Password <input type="password" id="password"></label>
           <button type="button" onclick="
             const who = {owners!r}[password.value];
             if (!who) {{ log.textContent = 'wrong password'; return; }}
             document.cookie = '{ACCOUNT_COOKIE}=' + who + '; path=/';
             location.href = '/drift/account/home';">Sign in</button>""",
    )


@router.get("/account/home", response_class=HTMLResponse)
def account_home(request: Request, quiet: int = 0) -> HTMLResponse:
    """The signed-in account's invoices, with the account shown in the header: its email
    address, and its name on the account button, whose menu holds "Sign out". `quiet=1`
    draws the page with no header at all, as a print view or an embedded page does."""
    # Only the lab's own accounts: any other cookie value is no one, so nothing a visitor
    # sends is written into the page.
    known = {mail: name for mail, name in ACCOUNTS.values()}
    sent = request.cookies.get(ACCOUNT_COOKIE, "")
    email = html.escape(sent) if sent in known else ""
    name = html.escape(known.get(sent, ""))
    header = (
        f"""<header>
              <span class="who">{email}</span>
              <button type="button" aria-haspopup="menu" aria-label="Account menu"
                      onclick="menu.hidden = !menu.hidden">{name}</button>
              <div id="menu" role="menu" hidden><a href="/drift/account/sign-in">Sign out</a></div>
            </header>"""
        if email and not quiet
        else ""
    )
    body = (
        '<h1>Invoices</h1><p id="due">48,200 due</p>'
        if email
        else '<h1>Invoices</h1><a href="/drift/account/sign-in">Sign in</a>'
    )
    return _page(request, "account-home", "Invoices", header + body)


# Set by a test to end the lab's session: every page below then asks for a sign-in again,
# each in a different way, none of them with a password box or a sign-in word in its path.
SESSION_COOKIE = "lab-session"
SESSION_GONE = "gone"

# Where /drift/workspace sends a visitor whose session ran out. Google's account chooser
# has no password box and no "login" in its path. Tests answer it themselves, offline.
ACCOUNT_CHOOSER = "https://accounts.google.com/AccountChooser?service=lab"

_DUE = '<h1>Invoices</h1><p id="due">48,200 due</p>'


def _session_gone(request: Request) -> bool:
    return request.cookies.get(SESSION_COOKIE) == SESSION_GONE


@router.get("/session", response_class=HTMLResponse)
def session(request: Request) -> HTMLResponse:
    """Answers 401, with a page that only says so, once the session has run out."""
    if _session_gone(request):
        response = _page(request, "session", "Expired", "<p>Your session has expired.</p>")
        response.status_code = 401
        return response
    return _page(request, "session", "Invoices", _DUE)


@router.get("/workspace", response_class=HTMLResponse, response_model=None)
def workspace(request: Request) -> Response:
    """Sends the visitor to Google's account chooser once the session has run out."""
    if _session_gone(request):
        return RedirectResponse(ACCOUNT_CHOOSER, status_code=302)
    return _page(request, "workspace", "Invoices", _DUE)


@router.get("/start", response_class=HTMLResponse)
def start(request: Request, form: str = "named") -> HTMLResponse:
    """Shows an identifier-first sign-in at its own address once the session has run out:
    an email field and a button, the password asked for on the next page. `form=named` names
    the form "Sign in to Acme"; `form=plain` leaves it unnamed, with a "Log in" button."""
    if not _session_gone(request):
        return _page(request, "start", "Invoices", _DUE)
    named = ' aria-label="Sign in to Acme"' if form == "named" else ""
    button = "Next" if form == "named" else "Log in"
    return _page(
        request,
        "start",
        "Acme",
        f"""<form{named} onsubmit="event.preventDefault()">
              <label>Email <input type="email" name="email"></label>
              <button>{button}</button></form>""",
    )


@router.get("/button", response_class=HTMLResponse)
def button(request: Request, keep: str = "id") -> HTMLResponse:
    """A button whose words and class change after the first visit, while it stays a button.
    `keep=id` keeps its id, as most redesigns do; `keep=role` keeps nothing but its role
    and its place on the page."""
    later = _visits(request, f"button-{keep}") > 0
    words, look = ("Reveal total", "btn-green") if later else ("Show total", "btn-blue")
    named = ' id="total-button"' if keep == "id" else ""
    return _page(
        request,
        f"button-{keep}",
        "Basket",
        f"""<h1>Basket</h1>
           <button type="button"{named} class="{look}"
                   onclick="total.textContent = '£31.40'">{words}</button>
           <p id="total"></p>""",
    )


# The list's items, as (name, address part, price). Shown in this order on the first visit
# and reversed on every visit after it.
ITEMS = [("Teapot", "teapot", "£18.50"), ("Kettle", "kettle", "£24.00"), ("Mug", "mug", "£6.00")]


@router.get("/list", response_class=HTMLResponse)
def item_list(request: Request) -> HTMLResponse:
    """A shop list that comes back in a different order on every visit after the first."""
    shown = ITEMS if not _visits(request, "list") else list(reversed(ITEMS))
    rows = "".join(
        f'<li class="item"><a href="/drift/item/{slug}">{name}</a></li>' for name, slug, _ in shown
    )
    return _page(request, "list", "Shop", f'<h1>Shop</h1><ul class="items">{rows}</ul>')


@router.get("/item/{slug}", response_class=HTMLResponse)
def item(request: Request, slug: str) -> HTMLResponse:
    name, price = next(((n, p) for n, s, p in ITEMS if s == slug), ("Gone", ""))
    return _page(request, f"item-{slug}", name, f'<h1>{name}</h1><p id="price">{price}</p>')


# How long the late page's data takes on every visit after the first, in seconds. Longer
# than replay's first look for an element, so only waiting for the page to finish can see it.
LATE_S = 3.0


@router.get("/late", response_class=HTMLResponse)
def late(request: Request) -> HTMLResponse:
    """A "Continue" button drawn from data the page fetches: at once on the first visit, and
    only after a slow answer on every visit after it."""
    slow = 1 if _visits(request, "late") else 0
    return _page(
        request,
        "late",
        "Checkout",
        f"""<h1>Checkout</h1><div id="slot"></div><p id="total"></p>
           <script>
             fetch("/drift/late/data?slow={slow}").then((r) => r.json()).then((data) => {{
               slot.innerHTML = '<button type="button">Continue</button>';
               slot.firstChild.onclick = () => total.textContent = data.total;
             }});
           </script>""",
    )


@router.get("/late/data")
async def late_data(slow: int = 0) -> dict[str, str]:
    if slow:
        await asyncio.sleep(LATE_S)
    return {"total": "£42.00"}


# No id on the dialog, as on demoqa.com: only its title tells the two apart.
_DIALOG = """<div class="cover" role="dialog" aria-modal="true" aria-labelledby="{key}-title"
     hidden><div class="box"><h2 id="{key}-title">{title}</h2>
  <button type="button" aria-label="Close"
          onclick="this.closest('[role=dialog]').hidden = true">×</button>
</div></div>"""
_OPEN = "document.querySelector('[aria-labelledby={key}-title]').hidden = false"


@router.get("/dialogs", response_class=HTMLResponse)
def dialogs(request: Request) -> HTMLResponse:
    """Two dialogs alike in every way but their titles, each with its own "Close": the small
    one is left open over the button that opens the large one."""
    small, large = _OPEN.format(key="small"), _OPEN.format(key="large")
    return _page(
        request,
        "dialogs",
        "Dialogs",
        f"""<h1>Dialogs</h1>
           <button type="button" onclick="{small}">Open small</button>
           <button type="button" onclick="{large}">Open large</button>"""
        + _DIALOG.format(key="small", title="Small dialog")
        + _DIALOG.format(key="large", title="Large dialog"),
    )
