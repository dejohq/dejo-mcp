"""A tiny billing portal, so Dejo has a site it is allowed to break.

Four pages, the shape of the boring work Dejo is for:

    /  (login)  ->  /invoices  ->  /invoices/{id}  ->  download

Three variants, because "the site changed" is not one event, it is two:

  a  the original site.
  b  a REAL break. The download control is renamed, re-id'd, moved, AND its link target
     changes. Every locator we hold misses, so the step genuinely fails and has to be
     handed back for repair. This is the variant the repair demo uses.
  c  a COSMETIC redesign. Renamed, re-id'd and moved exactly like B, but the link target
     is untouched. The css and text locators miss while the href locator still lands, so
     the step survives with no repair and no model call at all.

C exists to prove the point of storing several ranked locators instead of recording one
selector: most redesigns should cost nothing, and only a real break should reach your AI.
Exactly one step is affected in both, so a repair stays surgical instead of turning the
whole playbook stale.

Run it:

    python engine/tests/demo_site/app.py            # port 8787
    python engine/tests/demo_site/app.py --port 9000

Then open http://127.0.0.1:8787  and  http://127.0.0.1:8787/?variant=b
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import sys
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .hard import hard_page

app = FastAPI(title="Acme Billing (Dejo demo site)", docs_url=None, redoc_url=None)

# How long /contact/send takes to answer: well past the moment a click returns.
CONTACT_REPLY_S = 1.5
# How long a single-page app's data takes, after its address has already changed.
SPA_DATA_S = 0.8

INVOICES = [
    {"id": "2026-09", "month": "September 2026", "amount": "48,200", "state": "due"},
    {"id": "2026-08", "month": "August 2026", "amount": "46,900", "state": "paid"},
    {"id": "2026-07", "month": "July 2026", "amount": "51,400", "state": "paid"},
]

STYLE = """
  * { box-sizing: border-box }
  body { font: 15px/1.5 system-ui, sans-serif; color: #0a0b0c; background: #fafafa;
         margin: 0; padding: 48px 24px; }
  main { max-width: 720px; margin: 0 auto; background: #fff; border: 1px solid #e5e5e5;
         border-radius: 14px; padding: 32px; }
  h1 { font-size: 22px; margin: 0 0 4px }
  p.sub { color: #737373; margin: 0 0 28px }
  nav { display: flex; gap: 18px; margin-bottom: 28px; padding-bottom: 16px;
        border-bottom: 1px solid #eee }
  nav a { color: #737373; text-decoration: none }
  nav a.active { color: #0a0b0c; font-weight: 600 }
  ul.rows { list-style: none; padding: 0; margin: 0 }
  li.row { display: flex; align-items: center; justify-content: space-between;
           padding: 14px 0; border-bottom: 1px solid #f0f0f0 }
  .amount { color: #737373; font-variant-numeric: tabular-nums }
  .tag { font-size: 12px; padding: 3px 9px; border-radius: 999px; background: #f0f0f0;
         color: #737373 }
  .tag.due { background: #f6ece2; color: #a46a3c }
  label { display: block; margin: 14px 0 6px; color: #737373; font-size: 13px }
  input { width: 100%; padding: 10px 12px; border: 1px solid #ddd; border-radius: 8px;
          font-size: 15px }
  button, .btn { display: inline-block; margin-top: 20px; padding: 10px 18px;
                 border: 0; border-radius: 8px; background: #0a0b0c; color: #fff;
                 font-size: 14px; cursor: pointer; text-decoration: none }
  .toolbar { display: flex; margin-top: 28px }
  .toolbar.right { justify-content: flex-end }
  .ok { margin-top: 20px; padding: 12px 14px; border-radius: 8px; background: #eef6f1;
        color: #2e7d55 }
"""


VARIANTS = ("a", "b", "c")


def variant_of(request: Request, variant: str | None) -> str:
    """Variant sticks across links so a whole run stays in one version of the site."""
    if variant in VARIANTS:
        return variant
    fallback = request.query_params.get("variant", "a")
    return fallback if fallback in VARIANTS else "a"


def link(path: str, variant: str) -> str:
    return f"{path}?variant={variant}" if variant != "a" else path


def page(title: str, body: str, *, variant: str, nav: bool = True) -> HTMLResponse:
    # Variant B renames the section in the nav as well, so a text locator on the nav
    # has to cope too. The href does not change.
    invoices_label = "Invoices" if variant == "a" else "Billing"
    # Payments and Settings used to be decoration — both pointed back at /invoices. They
    # are real pages now, because a site with one destination cannot show what the map is
    # for. A second task on a DIFFERENT page of a site already walked is the whole point,
    # and it needs a second page to be walked to.
    nav_html = (
        f"""<nav>
              <a href="{link("/invoices", variant)}" class="active">{invoices_label}</a>
              <a href="{link("/payments", variant)}">Payments</a>
              <a href="{link("/settings", variant)}">Settings</a>
            </nav>"""
        if nav
        else ""
    )
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{title} · Acme Billing</title><style>{STYLE}</style></head>
<body><main>{nav_html}{body}</main></body></html>"""
    )


@app.get("/admin")
def admin(request: Request, variant: str | None = Query(None)) -> RedirectResponse:
    """A page that bounces you somewhere else, the way a sign-in page does once you are
    already signed in.

    Every real app does this, and it is what made Dejo offer to "repair" a healthy trail:
    the trail opens the sign-in page, the site sends it to the dashboard instead, and the
    step that wanted an email field finds a page that has none.
    """
    return RedirectResponse(link("/invoices", variant_of(request, variant)), status_code=303)


@app.get("/payments", response_class=HTMLResponse)
def payments(request: Request, variant: str | None = Query(None)) -> HTMLResponse:
    """A second destination, reachable from the nav on every signed-in page."""
    v = variant_of(request, variant)
    return page(
        "Payments",
        """<h1>Payments</h1>
           <p class="sub">How this account pays</p>
           <ul class="rows">
             <li class="row"><span>Card on file</span>
                 <span class="amount" id="card">Visa ending 4242</span></li>
             <li class="row"><span>Next charge</span>
                 <span class="amount" id="next-charge">&#8377; 18,400</span></li>
             <li class="row"><span>Billing cycle</span>
                 <span class="amount" id="cycle">Monthly</span></li>
           </ul>
           <div class="toolbar"><a class="btn" id="change-card" href="#">Change card</a></div>""",
        variant=v,
    )


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request, variant: str | None = Query(None)) -> HTMLResponse:
    """A third destination. Nothing clever — it exists so the site has a shape."""
    v = variant_of(request, variant)
    return page(
        "Settings",
        """<h1>Settings</h1>
           <p class="sub">Who hears about invoices</p>
           <form>
             <label for="billing-email">Billing email</label>
             <input id="billing-email" name="billing-email" value="finance@acme.com">
             <button type="submit">Save changes</button>
           </form>""",
        variant=v,
    )


@app.get("/preferences", response_class=HTMLResponse)
def preferences(request: Request) -> HTMLResponse:
    """A native `<select>` whose values are not its words, as on most real forms: picking
    "September" means choosing the value `sep`."""
    return page(
        "Preferences",
        """<h1>Preferences</h1>
           <label for="month">Statement month</label>
           <select id="month" onchange="shown.textContent = this.selectedOptions[0].label">
             <option value="">Choose one</option>
             <option value="jan">January</option>
             <option value="sep">September</option>
           </select>
           <p>Statements for <span id="shown">no month</span></p>""",
        variant=variant_of(request, None),
    )


@app.get("/contact", response_class=HTMLResponse)
def contact(request: Request) -> HTMLResponse:
    """A form sent with fetch, the way most launch sites do it: the fields lock, the button
    says "Sending...", and only after the server answers does the page say it worked."""
    return page(
        "Contact",
        """<h1>Contact</h1>
           <form id="contact">
             <label for="note">Note</label> <input id="note" name="note">
             <button type="submit">Send note</button>
           </form>
           <p id="result"></p>
           <script>
             contact.onsubmit = async (event) => {
               event.preventDefault();
               note.disabled = true;
               contact.querySelector("button").textContent = "Sending...";
               await fetch("/contact/send", {method: "POST"});
               contact.remove();
               result.textContent = "Note sent. Thank you!";
             };
           </script>""",
        variant=variant_of(request, None),
    )


@app.post("/contact/send")
async def contact_send() -> Response:
    """Slow on purpose: long enough that a reply written at once sees the half-sent form."""
    await asyncio.sleep(CONTACT_REPLY_S)
    return Response(status_code=204)


@app.get("/news", response_class=HTMLResponse)
def news(request: Request) -> HTMLResponse:
    """A cookie banner shown until it is accepted once, as on most real sites: the click that
    clears it is needed on the first visit and finds nothing on every visit after."""
    banner = (
        ""
        if request.cookies.get("cookies") == "ok"
        else """<div id="consent"><p>We use cookies.</p>
             <button onclick="document.cookie = 'cookies=ok; path=/'; consent.remove()">
               Accept cookies</button></div>"""
    )
    return page(
        "News",
        f'{banner}<h1>News</h1><p id="headline">Rates hold for September</p>',
        variant=variant_of(request, None),
    )


@app.get("/launch", response_class=HTMLResponse)
def launch(request: Request) -> HTMLResponse:
    """A launch site's submit page, with the controls whose words sound risky and are not
    (a footer link to /submit, a "Publish" tab, a tag chip's "Remove") beside ones that are
    (a link that deletes, a button that sends, a row's "Remove")."""
    return page(
        "Launch",
        """<h1>Launch</h1>
           <div role="tablist">
             <button role="tab" aria-selected="true" onclick="panel.textContent='Draft view'">
               Draft</button>
             <button role="tab" aria-selected="false"
                     onclick="panel.textContent='Publish view'">Publish</button>
           </div>
           <p id="panel">Draft view</p>
           <form id="details">
             <label for="tags">Tags</label> <input id="tags">
             <span class="chip" id="chip-js">javascript
               <button type="button" aria-label="Remove javascript"
                       onclick="this.parentElement.remove()">×</button></span>
           </form>
           <button type="button" onclick="panel.textContent='Sent'">Send</button>
           <table><tr><td>Old launch</td>
             <td><button type="button" onclick="this.closest('tr').remove()">Remove</button></td>
           </tr></table>
           <a href="/launch" data-method="delete">Delete launch</a>
           <footer><a href="/submit">Submit</a></footer>""",
        variant=variant_of(request, None),
    )


@app.get("/submit", response_class=HTMLResponse)
def submit_info(request: Request) -> HTMLResponse:
    """Where a footer "Submit" link goes: a page about submitting, which sends nothing."""
    return page(
        "Submit a site",
        "<h1>Submit a site</h1>",
        variant=variant_of(request, None),
    )


@app.get("/directory", response_class=HTMLResponse)
def directory(request: Request) -> HTMLResponse:
    """A dropdown made pretty the way Choices.js and nice-select do it: the real `<select>` is
    hidden and a menu of the site's own shows the choice, by listening to its changes."""
    return page(
        "List a tool",
        """<h1>List a tool</h1>
           <label for="category">Category</label>
           <select id="category" hidden
                   onchange="picked.textContent = this.selectedOptions[0].label">
             <option value="">Choose a category</option>
             <option value="dev">Developer tools</option>
             <option value="ai">AI agents</option>
           </select>
           <div class="menu">Category: <span id="picked">none</span></div>
           <label for="tool">Tool name</label> <input id="tool">
           <label for="about">About it</label> <textarea id="about"></textarea>
           <select id="region" disabled><option>Europe</option><option>Asia</option></select>""",
        variant=variant_of(request, None),
    )


@app.get("/clients", response_class=HTMLResponse)
def clients(request: Request) -> HTMLResponse:
    """Styled checkboxes, the two ways sites draw them: the real box under its own label
    (agenticskills.io), and the real box hidden with only its label on show."""
    return page(
        "Clients",
        """<h1>Which clients does it support?</h1>
           <style>
             .pick { position: relative; width: 160px; height: 24px; margin: 6px 0 }
             .pick input { position: absolute; left: 2px; top: 4px; margin: 0 }
             .pick label { position: absolute; inset: 0; z-index: 1; margin: 0;
                           padding-left: 24px; color: #0a0b0c }
           </style>
           <form id="clients">
             <div class="pick"><input type="checkbox" id="claude" name="claude">
               <label for="claude">Claude Code</label></div>
             <div class="pick"><input type="checkbox" id="cursor" name="cursor" hidden>
               <label for="cursor">Cursor</label></div>
           </form>
           <p>Chosen: <span id="chosen">none</span></p>
           <script>
             clients.addEventListener("change", () => {
               const on = [...clients.querySelectorAll("input:checked")].map(i => i.name);
               chosen.textContent = on.join(", ") || "none";
             });
           </script>""",
        variant=variant_of(request, None),
    )


@app.get("/listing", response_class=HTMLResponse)
def listing(request: Request) -> HTMLResponse:
    """A listing form that says it worked only in a toast that is gone a moment later, then
    empties itself, the way mcpserverhub.net does: once the page is still, nothing on it
    says the form was sent. Its second button sends to an address that fails."""
    return page(
        "List your server",
        """<h1>List your server</h1>
           <form id="listing">
             <label for="server">Server</label> <input id="server" name="server" required>
             <button type="submit">List it</button>
             <button type="button" id="broken">Send for review</button>
           </form>
           <div id="toasts"></div>
           <script>
             listing.onsubmit = async (event) => {
               event.preventDefault();
               const button = listing.querySelector("button");
               button.textContent = "Loading...";
               await fetch("/contact/send", {method: "POST"});
               button.textContent = "List it";
               listing.reset();
               const toast = document.createElement("div");
               toast.setAttribute("role", "status");
               toast.textContent = "Thanks! Your server is in the queue.";
               toasts.append(toast);
               setTimeout(() => toast.remove(), 300);
             };
             broken.onclick = () => fetch("/listing/review", {method: "POST"});
           </script>""",
        variant=variant_of(request, None),
    )


@app.post("/listing/review")
def listing_review() -> Response:
    """Fails the way a broken backend does, with nothing on the page to say so."""
    return Response("upstream down", status_code=502)


@app.get("/categories", response_class=HTMLResponse)
def categories(request: Request) -> HTMLResponse:
    """A type-ahead list that says "Loading..." before its choices arrive (saashub.com)."""
    return page(
        "Categories",
        """<h1>Pick categories</h1>
           <ul id="choices"><li>Loading...</li></ul>
           <script>
             setTimeout(() => {
               choices.innerHTML = '<li class="choice">Developer tools</li>'
                 + '<li class="choice">AI agents</li>';
             }, 1200);
           </script>""",
        variant=variant_of(request, None),
    )


@app.get("/publish.md")
def publish_guide() -> Response:
    """A long markdown file served as plain text, the way market.lobehub.com serves its
    guide for agents: the whole page is one element, far past what one read may hand back."""
    filler = "\n\n".join(
        f"## Note {n}\n\nThis part says nothing about money or manifests. " * 3
        for n in range(1, 40)
    )
    body = (
        "# Publish your MCP server\n\nSend this guide to your agent.\n\n"
        "## Requirements\n\nYou need a manifest.\nIt must be valid JSON.\n\n"
        f"{filler}\n\n"
        "## Pricing\n\nPublishing is free for open source servers.\n\n"
        "## Contact\n\nWrite to the team.\n"
    )
    return Response(body, media_type="text/plain")


@app.get("/spa", response_class=HTMLResponse)
@app.get("/spa/listing", response_class=HTMLResponse)
def spa(request: Request) -> HTMLResponse:
    """A single-page app, the way lobehub.com draws a listing: the link changes the address
    at once, and the listing is drawn only once its data has come back."""
    return page(
        "Servers",
        """<h1 id="title">Servers</h1>
           <a id="item" href="/spa/listing">Dejo server</a>
           <section id="detail"></section>
           <footer>About · Terms</footer>
           <script>
             item.onclick = async (event) => {
               event.preventDefault();
               history.pushState({}, "", "/spa/listing");
               title.textContent = "";
               const listing = await (await fetch("/spa/data")).json();
               title.textContent = listing.name;
               detail.textContent = listing.about;
             };
           </script>""",
        variant=variant_of(request, None),
    )


@app.get("/spa/data")
async def spa_data() -> dict[str, str]:
    """Slow on purpose, as an API behind a listing is."""
    await asyncio.sleep(SPA_DATA_S)
    return {"name": "Dejo", "about": "A browser your agent remembers."}


@app.get("/sign-up", response_class=HTMLResponse)
def sign_up(request: Request) -> HTMLResponse:
    """Sign-in buttons that are only a logo, the way devhunt.org draws them: no words, no
    label, nothing a screen reader could say."""
    github = '<svg class="lucide lucide-github" viewBox="0 0 24 24"><path d="M9 19"/></svg>'
    google = (
        '<svg viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9"/>'
        '<path fill="#4285F4" d="M46 24"/><path fill="#FBBC05" d="M10 28"/></svg>'
    )
    blank = '<svg viewBox="0 0 24 24"><path d="M1 1"/></svg>'
    return page(
        "Sign up",
        f"""<h1>Sign up</h1>
            <button type="button" onclick="said.textContent='GitHub'">{github}</button>
            <button type="button" onclick="said.textContent='Google'">{google}</button>
            <button type="button">{blank}</button>
            <p id="said">nobody</p>""",
        variant=variant_of(request, None),
    )


@app.get("/logo", response_class=HTMLResponse)
def logo(request: Request) -> HTMLResponse:
    """A logo picker the way devhunt.org has one: a "Select an image" button opens a hidden
    file box that takes PNG only, and empties itself when given anything else."""
    return page(
        "Logo",
        """<h1>Logo</h1>
           <input type="file" id="logo-file" accept="image/png" hidden>
           <button type="button" onclick="document.getElementById('logo-file').click()">
             Select an image</button>
           <p id="chosen">no logo</p>
           <label>Banner <input type="file" id="banner"></label>
           <script>
             const box = document.getElementById("logo-file");
             box.onchange = () => {
               const file = box.files[0];
               if (file && file.type !== "image/png") { box.value = ""; return; }
               chosen.textContent = file ? file.name : "no logo";
             };
           </script>""",
        variant=variant_of(request, None),
    )


@app.get("/continue", response_class=HTMLResponse)
def continue_with(request: Request) -> HTMLResponse:
    """A "Continue with Google" button that opens the sign-in in a new tab, the way
    fazier.com does, and leaves this page exactly as it was."""
    return page(
        "Join",
        """<h1>Join</h1>
           <button type="button" onclick="window.open('/books', '_blank')">
             Continue with Google</button>""",
        variant=variant_of(request, None),
    )


@app.get("/hard", response_class=HTMLResponse)
def hard() -> HTMLResponse:
    """Every awkward thing a real website does, on one URL. See `hard.py`."""
    return hard_page()


@app.get("/checkout", response_class=HTMLResponse)
def checkout(request: Request, variant: str | None = Query(None)) -> HTMLResponse:
    """A payment widget inside an iframe, the way hosted card forms arrive on real sites.

    It exists for one bug. After the browser has navigated even once, Playwright numbers the
    main page's refs as well as the frame's, and Dejo used to read that number as "which
    frame". The button in here then lost its frame, and a trail that pressed it could never
    find it again."""
    widget = (
        "<button onclick=&quot;parent.document.getElementById('status').textContent='Paid'"
        "&quot;>Pay now</button>"
    )
    return page(
        "Checkout",
        f"""<h1>Checkout</h1>
            <p id="status">Not paid</p>
            <iframe id="card" title="Card payment" srcdoc="{widget}"></iframe>""",
        variant=variant_of(request, variant),
    )


# Orders placed through /shop, so a test can count how many times "Pay" really ran. A
# risky step must happen exactly once, and the only honest proof is the shop's own count.
ORDERS = {"placed": 0}

BOOKS = ["It's Only the Himalayas", "Full Moon over Noah's Ark", "See America", "Vagabonding"]


@app.get("/shop", response_class=HTMLResponse)
def shop(request: Request, variant: str | None = Query(None)) -> HTMLResponse:
    """A form that POSTs an order, next to a search form that only GETs.

    The search button says "Submit" on purpose: a plain search must never be treated as a
    risky step, while "Pay now" always is."""
    v = variant_of(request, variant)
    return page(
        "Shop",
        f"""<h1>Shop</h1>
            <p class="sub">Orders placed: <span id="orders">{ORDERS["placed"]}</span></p>
            <form method="get" action="/shop/search"><label for="q">Search</label>
              <input id="q" name="q"><button type="submit">Submit</button></form>
            <form method="post" action="{link("/shop/pay", v)}"><button type="submit">Pay now</button></form>""",
        variant=v,
    )


@app.get("/shop/search", response_class=HTMLResponse)
def shop_search(request: Request, q: str = "", variant: str | None = Query(None)) -> HTMLResponse:
    return page(
        "Search", f"<h1>Results for {q or 'nothing'}</h1>", variant=variant_of(request, variant)
    )


@app.post("/shop/pay", response_class=HTMLResponse)
def shop_pay(request: Request, variant: str | None = Query(None)) -> HTMLResponse:
    # Variant b renames the receipt, so a trail that pays and then reads it breaks AFTER
    # the payment: the fix must not pay a second time.
    ORDERS["placed"] += 1
    v = variant_of(request, variant)
    receipt = "receipt" if v == "a" else "order-receipt"
    return page(
        "Paid",
        f'<h1>Paid</h1><p class="ok" id="{receipt}">Order {ORDERS["placed"]} placed</p>',
        variant=v,
    )


@app.get("/books", response_class=HTMLResponse)
def books(request: Request, order: str = "a", variant: str | None = Query(None)) -> HTMLResponse:
    """A list whose order changes: `?order=b` reverses it. "Open the first book" learned on
    one order has to open whatever is first on the other, not the book it opened before."""
    listed = BOOKS if order == "a" else list(reversed(BOOKS))
    rows = "".join(
        f'<li class="row"><article class="book"><h3><a href="/books/{index}">{title}</a></h3>'
        f'<p class="price">£{40 + index}.00</p></article></li>'
        for index, title in ((BOOKS.index(title), title) for title in listed)
    )
    return page(
        "Books",
        f'<h1>Books</h1><ul class="rows">{rows}</ul>',
        variant=variant_of(request, variant),
    )


@app.get("/books/{index}", response_class=HTMLResponse)
def book(request: Request, index: int, variant: str | None = Query(None)) -> HTMLResponse:
    return page(
        BOOKS[index],
        f'<h1 id="title">{BOOKS[index]}</h1><p class="price" id="price">£{40 + index}.00</p>',
        variant=variant_of(request, variant),
    )


@app.get("/tickets", response_class=HTMLResponse)
def tickets(request: Request, open_count: int = Query(3, alias="open")) -> HTMLResponse:
    """GitHub's issue list in miniature: the count lives in a link NAMED by the count, under
    an id React made up for this page load. A read learned at one count has to answer at
    another, which it cannot do if it was stored by the name "Open (3)" or by that id."""
    return page(
        "Tickets",
        f"""<h1>Tickets</h1>
            <div id="_r_2o_-list-view-metadata"><ul>
              <li><a href="/tickets?state=open">Open ({open_count})</a></li>
              <li><a href="/tickets?state=closed">Closed (40)</a></li>
            </ul></div>""",
        variant=variant_of(request, None),
    )


@app.get("/challenge", response_class=HTMLResponse)
def challenge() -> HTMLResponse:
    """What Cloudflare shows a browser it does not trust yet, with no widget a page can see:
    only its title and its heading say what it is (three real sites, 22 Oct 2026)."""
    return HTMLResponse(
        "<html><head><title>Just a moment...</title></head><body>"
        "<h1>example.org</h1><h2>Performing security verification</h2>"
        "<p>This website uses a security service to protect against malicious bots.</p>"
        "</body></html>"
    )


@app.get("/refused", response_class=HTMLResponse)
def refused() -> HTMLResponse:
    """A site that turns automated browsers away with a plain 403."""
    return HTMLResponse("<h1>403 Forbidden</h1>", status_code=403)


CATALOG = {1: "Degrees", 2: "Courses", 3: "Policies"}


@app.get("/catalog", response_class=HTMLResponse)
def catalog(nav: int = 0) -> HTMLResponse:
    """Every page at one address, told apart only by its query, the way catalog.ccv.edu
    serves all of its pages as `/content.php?navoid=N`. Every menu link has the same path, so
    a step stored by that path clicks whichever link comes first."""
    links = "".join(
        f'<li><a href="/catalog?nav={n}">{name}</a></li>' for n, name in CATALOG.items()
    )
    title = CATALOG.get(nav, "Catalog")
    return page(
        title,
        f'<ul class="menu">{links}</ul><h1 id="heading">{title}</h1>',
        variant="a",
    )


@app.get("/", response_class=HTMLResponse)
def login_page(request: Request, variant: str | None = Query(None)) -> HTMLResponse:
    v = variant_of(request, variant)
    return page(
        "Sign in",
        f"""
        <h1>Sign in</h1>
        <p class="sub">Acme Billing</p>
        <form method="post" action="{link("/login", v)}">
          <label for="email">Email</label>
          <input id="email" name="email" type="email" value="finance@acme.com" required>
          <label for="password">Password</label>
          <input id="password" name="password" type="password" value="hunter2" required>
          <button type="submit">Sign in</button>
        </form>
        """,
        variant=v,
        nav=False,
    )


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    variant: str | None = Query(None),
) -> RedirectResponse:
    """Any credentials work. This is a demo site, not a security exercise."""
    del email, password
    return RedirectResponse(link("/invoices", variant_of(request, variant)), status_code=303)


@app.get("/invoices", response_class=HTMLResponse)
def invoice_list(request: Request, variant: str | None = Query(None)) -> HTMLResponse:
    v = variant_of(request, variant)
    rows = "".join(
        f"""<li class="row">
              <a href="{link("/invoices/" + inv["id"], v)}">{inv["month"]}</a>
              <span>
                <span class="amount">&#8377; {inv["amount"]}</span>
                <span class="tag {inv["state"]}">{inv["state"]}</span>
              </span>
            </li>"""
        for inv in INVOICES
    )
    return page(
        "Invoices",
        f"""<h1>{"Invoices" if v == "a" else "Billing"}</h1>
            <p class="sub">Three most recent statements</p>
            <ul class="rows">{rows}</ul>""",
        variant=v,
    )


@app.get("/invoices/{invoice_id}", response_class=HTMLResponse)
def invoice_detail(
    request: Request, invoice_id: str, variant: str | None = Query(None)
) -> HTMLResponse:
    v = variant_of(request, variant)
    invoice = next((i for i in INVOICES if i["id"] == invoice_id), None)
    if invoice is None:
        return page("Not found", "<h1>No such invoice</h1>", variant=v)

    # THE ONE THING THAT MOVES.
    #   a  id="download-btn"  "Download"  left   href .../file
    #   b  id="get-pdf"       "Get PDF"   right  href .../download   <- every locator misses
    #   c  id="get-pdf"       "Get PDF"   right  href .../file       <- href still lands
    if v == "a":
        href = link(f"/invoices/{invoice_id}/file", v)
        action = f"""<div class="toolbar">
                       <a class="btn" id="download-btn" href="{href}">Download</a>
                     </div>"""
    else:
        path = "download" if v == "b" else "file"
        href = link(f"/invoices/{invoice_id}/{path}", v)
        action = f"""<div class="toolbar right">
                       <a class="btn" id="get-pdf" href="{href}">Get PDF</a>
                     </div>"""

    return page(
        invoice["month"],
        f"""<h1>{invoice["month"]}</h1>
            <p class="sub">Invoice {invoice["id"]} &middot; &#8377; {invoice["amount"]}</p>
            {action}""",
        variant=v,
    )


@app.get("/invoices/{invoice_id}/download")
@app.get("/invoices/{invoice_id}/file")
def invoice_file(invoice_id: str) -> Response:
    """A real download, so a 'download happened' postcondition has something to check."""
    body = f"ACME BILLING\nInvoice {invoice_id}\nThis is a demo file.\n".encode()
    return Response(
        content=body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="acme-{invoice_id}.pdf"'},
    )


def _how_to_stop(port: int) -> list[str]:
    """How to free a busy port, in the shell the reader is actually using.

    This used to print `netstat` and `taskkill` on every platform, which is simply wrong
    advice for two thirds of the people who might read it.
    """
    if sys.platform == "win32":
        return [
            f"  to stop it   netstat -ano | findstr :{port}",
            "               taskkill /PID <pid> /F",
        ]
    return [f"  to stop it   lsof -ti:{port} | xargs kill"]


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex((host, port)) != 0


def main() -> int:
    """Run the demo site, and say something useful if the port is already taken."""
    import uvicorn

    parser = argparse.ArgumentParser(description="Acme Billing — Dejo's practice site")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    if not _port_is_free(args.host, args.port):
        script = Path(__file__).name
        print(
            "\n".join(
                [
                    f"Port {args.port} is already in use.",
                    "Most likely this demo site is already running somewhere.",
                    "",
                    f"  open it      http://{args.host}:{args.port}/",
                    f"  or use       python {script} --port {args.port + 1}",
                    *_how_to_stop(args.port),
                ]
            ),
            file=sys.stderr,
        )
        return 1

    base = f"http://{args.host}:{args.port}"
    print("Acme Billing demo site")
    print(f"  variant A  {base}/            original")
    print(f"  variant B  {base}/?variant=b  real break, needs repair")
    print(f"  variant C  {base}/?variant=c  cosmetic only, survives")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
