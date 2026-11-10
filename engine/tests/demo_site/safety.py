"""The memory safety lab: pages where replaying a remembered task could quietly do the WRONG
task, for the wrong person, or with old values, while every step's own check passes.

    /safety/shop/...     a shop with a customer and a vendor, each signed in by a cookie and
                         shown in the header; "my orders" is a different page for each
    /safety/months       invoice links for this month and the two before it, drawn from the
                         browser's own clock, so a test can move the date with `set_time`
    /safety/flights      a flight search: from, to and a date, and a results page that says
                         back what was searched
    /safety/ab           version A on odd visits and version B on even ones: the same control
                         with other words and in another place, as an A/B test shows it
    /safety/lang         the same basket in English or in Hindi, by Accept-Language
    /safety/prices       a price list whose rows have no links and come back in another order
                         on every visit after the first

Like the drift lab, each page counts its visits in a cookie, and what the page did is
written to `#log` and `window.lab`.
"""

from __future__ import annotations

import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .drift import ITEMS, STYLE, _page, _visits

router = APIRouter(prefix="/safety")

# The shop's two accounts: email, the name on the account button, and where "my orders"
# lives for them. A customer's orders are what they bought; a vendor's are what they sold.
SHOP_COOKIE = "lab-shop"
CUSTOMER = "asha@shop.test"
VENDOR = "sales@potters.test"
SHOP_ACCOUNTS = {
    CUSTOMER: ("Asha Rao", "My orders", "/safety/shop/orders"),
    VENDOR: ("Potters Ltd", "Orders to ship", "/safety/shop/sales"),
}
CUSTOMER_ORDERS = "2 orders on the way"
VENDOR_ORDERS = "7 orders to ship"


def _shop_page(request: Request, name: str, body: str) -> HTMLResponse:
    """A shop page with the signed-in account in its header, or a sign-in link."""
    sent = request.cookies.get(SHOP_COOKIE, "")
    if sent not in SHOP_ACCOUNTS:
        return _page(request, name, "Shop", '<h1>Shop</h1><a href="/safety/shop/home">Sign in</a>')
    shown, link, where = SHOP_ACCOUNTS[sent]
    header = f"""<header>
          <span class="who">{html.escape(sent)}</span>
          <button type="button" aria-haspopup="menu" aria-label="Account menu"
                  onclick="menu.hidden = !menu.hidden">{html.escape(shown)}</button>
          <div id="menu" role="menu" hidden><a href="/safety/shop/home">Sign out</a></div>
        </header>
        <nav><a href="{where}">{link}</a></nav>"""
    return _page(request, name, "Shop", header + body)


@router.get("/shop/home", response_class=HTMLResponse)
def shop_home(request: Request) -> HTMLResponse:
    return _shop_page(request, "shop-home", "<h1>Welcome back</h1>")


@router.get("/shop/orders", response_class=HTMLResponse)
def shop_orders(request: Request) -> HTMLResponse:
    """What the customer bought."""
    return _shop_page(
        request, "shop-orders", f'<h1>Your orders</h1><p id="orders">{CUSTOMER_ORDERS}</p>'
    )


@router.get("/shop/sales", response_class=HTMLResponse)
def shop_sales(request: Request) -> HTMLResponse:
    """What the vendor has to send."""
    return _shop_page(
        request, "shop-sales", f'<h1>Orders to ship</h1><p id="orders">{VENDOR_ORDERS}</p>'
    )


# How many months of invoices the months page lists, newest first.
MONTHS_SHOWN = 3


@router.get("/months", response_class=HTMLResponse)
def months(request: Request) -> HTMLResponse:
    """Invoice links for this month and the ones before it, by the browser's own clock."""
    return _page(
        request,
        "months",
        "Invoices",
        f"""<h1>Invoices</h1><ul id="months"></ul>
           <script>
             const now = new Date();
             for (let back = 0; back < {MONTHS_SHOWN}; back++) {{
               const when = new Date(now.getFullYear(), now.getMonth() - back, 1);
               const name = when.toLocaleString("en-GB", {{ month: "long", year: "numeric" }});
               const id = when.getFullYear() + "-" + String(when.getMonth() + 1).padStart(2, "0");
               const row = document.createElement("li");
               row.innerHTML = '<a href="/safety/months/' + id + '">' + name + '</a>';
               document.getElementById("months").append(row);
             }}
           </script>""",
    )


# Month names for the invoice page, so it says the month the way the list did.
_MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


@router.get("/months/{month_id}", response_class=HTMLResponse)
def month(request: Request, month_id: str) -> HTMLResponse:
    """One month's invoice. The amount differs by month, so a wrong month is a wrong answer."""
    year, _, number = month_id.partition("-")
    if not (year.isdigit() and number.isdigit() and 1 <= int(number) <= len(_MONTH_NAMES)):
        return _page(request, "month", "Invoice", "<h1>No such invoice</h1>")
    named = f"{_MONTH_NAMES[int(number) - 1]} {int(year)}"
    amount = f"£{40 + int(number)}.00"
    return _page(
        request,
        "month",
        "Invoice",
        f'<h1 id="month">Invoice for {named}</h1><p id="amount">{amount}</p>',
    )


@router.get("/flights", response_class=HTMLResponse)
def flights(request: Request) -> HTMLResponse:
    """A flight search: from, to and a date."""
    return _page(
        request,
        "flights",
        "Flights",
        """<h1>Find a flight</h1>
           <form action="/safety/flights/results">
             <label>From <input name="from"></label>
             <label>To <input name="to"></label>
             <label>Date <input name="on"></label>
             <button>Search</button>
           </form>""",
    )


@router.get("/flights/results", response_class=HTMLResponse)
def flight_results(request: Request) -> HTMLResponse:
    """Says back what was searched, so a replay with old values shows them."""
    asked = request.query_params
    said = " ".join(
        html.escape(part)
        for part in (asked.get("from", ""), "to", asked.get("to", ""), "on", asked.get("on", ""))
    )
    return _page(
        request,
        "flight-results",
        "Flights",
        f'<h1>Flights</h1><p id="result">{said}: 3 flights</p>',
    )


@router.get("/ab", response_class=HTMLResponse)
def ab(request: Request) -> HTMLResponse:
    """Version A on the first visit and every other one after it, version B between: the
    same control, with other words, another class and in another place."""
    show = "total.textContent = '£31.40'"
    version_b = _visits(request, "ab") % 2 == 1
    if version_b:
        body = f"""<h1>Basket</h1><p id="total"></p>
           <aside class="promo"><p>New look!</p>
             <button type="button" class="cta-b" onclick="{show}">See the total</button></aside>"""
    else:
        body = f"""<h1>Basket</h1>
           <div class="bar"><button type="button" class="cta-a" onclick="{show}">Show total</button></div>
           <p id="total"></p>"""
    return _page(request, "ab", "Basket", body)


# The basket's words in each language it speaks: the safe button, then the one that empties.
_BASKET_WORDS = {
    "en": ("Basket", "Show total", "Empty basket"),
    "hi": ("टोकरी", "कुल दिखाएँ", "टोकरी खाली करें"),
}


@router.get("/lang", response_class=HTMLResponse)
def lang(request: Request) -> HTMLResponse:
    """The same basket in English or Hindi, chosen by the browser's Accept-Language."""
    wanted = request.headers.get("accept-language", "en").lower()
    language = "hi" if wanted.startswith("hi") else "en"
    title, show, empty = _BASKET_WORDS[language]
    response = HTMLResponse(
        f"""<!doctype html><html lang="{language}"><head><meta charset="utf-8">
<title>{title} · Safety lab</title><style>{STYLE}</style></head>
<body><script>window.lab = {{}};</script><h1>{title}</h1>
<button type="button" onclick="total.textContent = '£31.40'">{show}</button>
<button type="button" onclick="window.lab.emptied = true; log.textContent = 'emptied';
        total.textContent = '£0.00'">{empty}</button>
<p id="total"></p><p id="log"></p></body></html>"""
    )
    return response


@router.get("/prices", response_class=HTMLResponse)
def prices(request: Request) -> HTMLResponse:
    """The shop's prices as plain rows, no links, in another order after the first visit."""
    shown = ITEMS if not _visits(request, "prices") else list(reversed(ITEMS))
    rows = "".join(
        f'<li class="row"><span class="name">{name}</span> <span class="price">{price}</span></li>'
        for name, _, price in shown
    )
    return _page(request, "prices", "Prices", f'<h1>Prices</h1><ul class="rows">{rows}</ul>')
