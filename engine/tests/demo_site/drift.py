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

What the page did is written where a test can read it: `#log`, and `window.lab`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/drift")

# Long enough to outlive any test, short enough that nothing lingers in a real browser.
VISIT_COOKIE_S = 3600

STYLE = """
  body { font: 15px/1.5 system-ui, sans-serif; margin: 0; padding: 40px; }
  .cover { position: fixed; inset: 0; background: rgba(0, 0, 0, .45); display: flex;
           align-items: center; justify-content: center; z-index: 10 }
  .box { background: #fff; padding: 24px; border-radius: 10px; width: 320px }
  .bar { position: fixed; left: 0; right: 0; bottom: 0; background: #222; color: #fff;
         padding: 16px; z-index: 11 }
"""


def _visits(request: Request, name: str) -> int:
    """How many times this browser has been to this page before."""
    try:
        return int(request.cookies.get(f"lab-{name}", "0"))
    except ValueError:
        return 0


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
