"""The hard page: every awkward thing a real website does, on one URL.

Kept forever, and deliberately nastier than anything the demo site does. The demo site has
clean HTML, stable ids, no JavaScript rendering and no cookie banner — it proves the memory
loop works, and proves nothing at all about a real site.

Everything here was chosen because it has broken a recorded flow in the wild:

1. a `div` acting as a dropdown, with no `<select>` anywhere
2. a button inside a shadow DOM
3. a button inside an iframe
4. content that only appears after the data arrives
5. a cookie banner that covers the page at a moment nobody chose
6. a `confirm()` that stops the browser dead until it is answered
7. a link that opens a new tab
8. a file input hidden behind a styled button
9. a list that only grows as you scroll
10. a menu that opens on `pointerdown` and ignores `click` — how Radix, and therefore
    shadcn/ui, builds every dropdown menu. A synthetic click does nothing to it
11. a link that calls `preventDefault` and navigates with `pushState` instead — every
    React Router `<Link>` in every admin sidebar. The URL changes AFTER the handler
    returns, so anything reading it too early sees no navigation at all
12. a table row of icon-only buttons with no text and no aria-label — view, approve,
    reject. The controls that matter most on an admin screen, and the ones a map built
    out of names cannot hold at all

Reachable at `/hard` on the demo site, so it is also a real URL to show on camera.
"""

from __future__ import annotations

from fastapi.responses import HTMLResponse

# How long the late content takes to arrive. Long enough that a snapshot taken immediately
# misses it, short enough that tests stay quick.
LATE_MS = 400

HARD_PAGE = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Everything that breaks a recorded flow</title>
<style>
  body {{ font: 15px system-ui, sans-serif; margin: 0; padding: 24px; max-width: 760px; }}
  h2 {{ font-size: 15px; margin: 28px 0 8px; }}
  .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 14px; }}
  #log {{ font-family: ui-monospace, monospace; background: #f5f5f5; padding: 8px 12px;
          border-radius: 6px; }}

  /* A dropdown built out of divs. No <select> anywhere on this page. */
  .menu {{ position: relative; display: inline-block; }}
  .menu-list {{ display: none; position: absolute; z-index: 5; background: #fff;
                border: 1px solid #ccc; border-radius: 6px; min-width: 180px; }}
  .menu.open .menu-list {{ display: block; }}
  .menu-item {{ padding: 8px 12px; cursor: pointer; }}
  .menu-item:hover {{ background: #eee; }}
  .menu-button {{ cursor: pointer; padding: 8px 12px; border: 1px solid #ccc;
                  border-radius: 6px; display: inline-block; }}

  /* The cookie banner covers the page, exactly like the real ones. */
  #cookies {{ position: fixed; inset: 0; background: rgba(0,0,0,.65); z-index: 99;
              display: flex; align-items: center; justify-content: center; }}
  #cookies .card {{ background: #fff; max-width: 380px; }}

  #feed li {{ padding: 6px 0; border-bottom: 1px solid #eee; }}
  #upload-input {{ display: none; }}
</style>
</head>
<body>

<h1>Everything that breaks a recorded flow</h1>
<p id="log">nothing yet</p>

<!-- 5. A cookie banner, over everything, before anything else can be clicked. -->
<div id="cookies">
  <div class="card">
    <p>We use cookies.</p>
    <button id="accept-cookies">Accept all</button>
  </div>
</div>

<!-- 1. A dropdown made of divs. -->
<h2>1. Dropdown that is not a select</h2>
<div class="menu" id="month-menu">
  <div class="menu-button" role="button" tabindex="0" id="month-button">Choose a month</div>
  <div class="menu-list">
    <div class="menu-item" role="option" data-month="aug">August 2026</div>
    <div class="menu-item" role="option" data-month="sep">September 2026</div>
    <div class="menu-item" role="option" data-month="oct">October 2026</div>
  </div>
</div>

<!-- 2. Shadow DOM. -->
<h2>2. Inside a shadow DOM</h2>
<div id="shadow-host"></div>

<!-- 3. An iframe. -->
<h2>3. Inside an iframe</h2>
<iframe id="widget" title="widget" width="320" height="70" srcdoc='
  <button id="frame-button"
          onclick="document.body.dataset.clicked=&apos;yes&apos;">Button in a frame</button>
'></iframe>

<!-- 4. Late content. -->
<h2>4. Arrives after the data does</h2>
<div id="slow">Loading…</div>

<!-- 6. A confirm box. -->
<h2>6. A confirm box that blocks everything</h2>
<button id="delete">Delete the report</button>

<!-- 7. A new tab. -->
<h2>7. Opens a new tab</h2>
<a id="new-tab" href="/hard?tab=2" target="_blank">Open the statement in a new tab</a>

<!-- 8. A hidden file input behind a styled button. -->
<h2>8. Upload with no visible file input</h2>
<input type="file" id="upload-input">
<button id="upload-button">Attach a receipt</button>

<!-- 10. A Radix-style menu: opens on pointerdown, not on click. -->
<h2>10. Menu that only answers pointerdown</h2>
<button id="pointer-menu-button" aria-haspopup="menu" aria-expanded="false">Row actions</button>
<div id="pointer-menu" hidden>
  <button role="menuitem" id="pointer-menu-edit">Edit row</button>
  <button role="menuitem" id="pointer-menu-delete">Delete row</button>
</div>

<!-- 11. A React Router style link: a real anchor that never actually follows itself. -->
<h2>11. Link that navigates by pushState</h2>
<a href="/hard/orders" id="spa-link">Orders</a>
<button id="spa-submit">Sign in</button>
<p id="spa-where">nowhere yet</p>

<!-- 12. Icon-only buttons: no text, no aria-label, nothing to be called by. -->
<h2>12. Row actions with no accessible name</h2>
<table id="rows"><tbody><tr>
  <td>Vendor A</td>
  <td>
    <button class="icon"><svg width="12" height="12"><circle cx="6" cy="6" r="5"/></svg></button>
    <button class="icon"><svg width="12" height="12"><rect width="10" height="10"/></svg></button>
  </td>
</tr></tbody></table>

<!-- 9. Infinite scroll. -->
<h2>9. Loads more only when you scroll</h2>
<ul id="feed"></ul>
<div id="sentinel" style="height: 40px"></div>

<script>
  const log = (message) => {{ document.getElementById('log').textContent = message; }};

  // 10. Radix's DropdownMenuTrigger opens on pointerdown. A `click` listener is
  // deliberately NOT registered, so anything that dispatches a synthetic click without
  // real pointer events leaves this menu shut — which is exactly the failure reported
  // against a shadcn/ui table in the wild.
  // 11. What every React Router <Link> does: swallow the anchor's own behaviour and
  // change the URL itself. The pushState happens after the handler returns, so a caller
  // that reads location too eagerly concludes nothing moved.
  document.getElementById('spa-link').addEventListener('click', (event) => {{
    event.preventDefault();
    setTimeout(() => {{
      history.pushState({{}}, '', '/hard/orders');
      document.getElementById('spa-where').textContent = 'orders';
      log('navigated by pushState');
    }}, 30);
  }});

  // The same thing a sign-in submit does: no href to hint at it, and the app redirects
  // a beat after the click. Nothing about the button says navigation is coming, which is
  // why a run that returns the moment its last step passes looks like it failed.
  document.getElementById('spa-submit').addEventListener('click', () => {{
    setTimeout(() => {{
      history.pushState({{}}, '', '/hard/dashboard');
      document.getElementById('spa-where').textContent = 'dashboard';
      log('signed in');
    }}, 120);
  }});

  const pointerTrigger = document.getElementById('pointer-menu-button');
  pointerTrigger.addEventListener('pointerdown', () => {{
    document.getElementById('pointer-menu').hidden = false;
    pointerTrigger.setAttribute('aria-expanded', 'true');
    log('pointer menu opened');
  }});

  // 5. The banner clears itself once accepted.
  document.getElementById('accept-cookies').addEventListener('click', () => {{
    document.getElementById('cookies').remove();
    log('cookies accepted');
  }});

  // 1. The div dropdown opens on click and reports what was picked.
  const menu = document.getElementById('month-menu');
  document.getElementById('month-button').addEventListener('click', () => {{
    menu.classList.toggle('open');
  }});
  menu.querySelectorAll('.menu-item').forEach((item) => {{
    item.addEventListener('click', () => {{
      document.getElementById('month-button').textContent = item.textContent;
      menu.classList.remove('open');
      log('picked ' + item.dataset.month);
    }});
  }});

  // 2. A real closed-off shadow root.
  document.getElementById('shadow-host')
    .attachShadow({{ mode: 'open' }})
    .innerHTML = '<button id="shadow-button">Button in a shadow root</button>';
  document.getElementById('shadow-host').shadowRoot
    .getElementById('shadow-button')
    .addEventListener('click', () => log('shadow button clicked'));

  // 4. Content that is simply not there yet.
  setTimeout(() => {{
    document.getElementById('slow').innerHTML =
      '<p id="total">1,240.00</p><button id="continue">Continue</button>';
    document.getElementById('continue')
      .addEventListener('click', () => log('continued'));
  }}, {LATE_MS});

  // 6. The browser stops here until somebody answers.
  document.getElementById('delete').addEventListener('click', () => {{
    log(confirm('Delete the report?') ? 'report deleted' : 'kept the report');
  }});

  // 8. The real input is hidden; the button stands in for it.
  const fileInput = document.getElementById('upload-input');
  document.getElementById('upload-button')
    .addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', (event) => {{
    log('attached ' + event.target.files[0].name);
  }});

  // 9. Ten rows at a time, only once the bottom comes into view.
  let rows = 0;
  const feed = document.getElementById('feed');
  const addRows = () => {{
    for (let i = 0; i < 10; i++) {{
      rows += 1;
      const row = document.createElement('li');
      row.className = 'row';
      row.textContent = 'Transaction ' + rows;
      feed.appendChild(row);
    }}
  }};
  addRows();
  new IntersectionObserver((entries) => {{
    if (entries[0].isIntersecting && rows < 40) addRows();
  }}).observe(document.getElementById('sentinel'));
</script>
</body>
</html>
"""


def hard_page() -> HTMLResponse:
    """The page itself. Mounted at `/hard` by the demo site."""
    return HTMLResponse(HARD_PAGE)
