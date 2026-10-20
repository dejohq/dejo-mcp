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
import socket
import sys
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .hard import hard_page

app = FastAPI(title="Acme Billing (Dejo demo site)", docs_url=None, redoc_url=None)

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
