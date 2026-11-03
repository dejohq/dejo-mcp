"""The parity page: one URL holding what other browser tools can do and Dejo has to match.

Each part is something a person really meets: a confirm box, a prompt, a chart drawn on a
canvas that only answers to a click at a position, a list that scrolls inside its own box,
a request the page makes after a click, a link that opens a new tab, a table, a list of
cards to read many fields from. One page keeps the tests short, and the page is a real URL
to try by hand at `/parity`.

`#log` always says what the last thing done was, so a test reads one element to know.
"""

from __future__ import annotations

import json

# The JSON the page fetches when "Load data" is clicked. Read back by tests of request
# waits and response reads, so it is fixed here rather than written twice.
DATA = {"city": "Pune", "temperature": 31}

# What "Load slowly" waits before answering, in seconds: long enough that a step after the
# click finds the answer not there yet, short enough to keep the tests quick.
SLOW_SECONDS = 1.5

PRODUCTS = [("Kettle", "24.00", "/parity/kettle"), ("Teapot", "18.50", "/parity/teapot")]

_CARDS = "".join(
    f'<article class="card"><h3><a href="{link}">{name}</a></h3>'
    f'<p class="price">£{price}</p></article>'
    for name, price, link in PRODUCTS
)

PARITY_PAGE = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Parity lab</title>
<style>
  body {{ font: 14px sans-serif; margin: 0; padding: 16px; }}
  .zone {{ border: 1px solid #999; padding: 12px; min-height: 32px; margin: 4px 0; }}
  #scroller {{ height: 100px; width: 300px; overflow: auto; border: 1px solid #999; }}
  #scroller .inside {{ height: 1200px; width: 900px; }}
</style>
</head>
<body>
<h1>Parity lab</h1>
<p id="log">nothing yet</p>

<div id="drag" draggable="true">drag me</div>
<div id="zone" class="zone">drop here</div>

<a id="away" href="/books" target="_blank">Open the books in a new tab</a>

<button onclick="log(confirm('Reset the draft?') ? 'reset' : 'kept')">Reset draft</button>
<button onclick="log('name: ' + prompt('What is your name?', 'nobody'))">Ask my name</button>
<button onclick="alert('Saved!'); log('alerted')">Save</button>

<button onclick="loadData('/parity/data')">Load data</button>
<button onclick="loadData('/parity/slow-data')">Load slowly</button>
<button onclick="fetch('/parity/missing').then(() => log('asked for nothing'))">Ask for nothing</button>
<button onclick="console.log('hello from the page'); log('talked')">Talk</button>

<canvas id="chart" width="300" height="150" style="border:1px solid #999"></canvas>

<div id="scroller"><div class="inside">a long list inside its own box</div></div>
<p id="scrolled">0,0</p>

<input id="keys" aria-label="Keys">
<p id="gaps">no keys</p>
<div id="menu-zone" class="zone">right click here</div>
<button id="shifty" onclick="log(event.shiftKey ? 'shift clicked' : 'plain click')">Shift me</button>

<button onclick="showSettings()">Show settings</button>
<dl>
  <dt>size</dt><dd id="size"></dd>
  <dt>zone</dt><dd id="tz"></dd>
  <dt>language</dt><dd id="lang"></dd>
  <dt>online</dt><dd id="online"></dd>
  <dt>scheme</dt><dd id="scheme"></dd>
  <dt>mobile</dt><dd id="mobile"></dd>
  <dt>where</dt><dd id="where"></dd>
  <dt>notifications</dt><dd id="notify"></dd>
</dl>

<table id="prices">
  <thead><tr><th>Item</th><th>Price</th></tr></thead>
  <tbody><tr><td>Tea</td><td>£2.00</td></tr><tr><td>Cake</td><td>£3.50</td></tr></tbody>
</table>

<section id="cards">{_CARDS}</section>

<script>
  function log(message) {{ document.getElementById('log').textContent = message; }}

  const zone = document.getElementById('zone');
  zone.addEventListener('dragover', e => e.preventDefault());
  zone.addEventListener('drop', e => {{ e.preventDefault(); log('dropped'); }});

  function loadData(where) {{
    fetch(where).then(r => r.json()).then(d => log('weather: ' + d.city + ' ' + d.temperature));
  }}

  // A chart with no structure: only the place clicked says what was hit.
  const chart = document.getElementById('chart');
  const pen = chart.getContext('2d');
  pen.fillStyle = '#c33';
  pen.fillRect(50, 30, 100, 60);
  chart.addEventListener('click', e => {{
    const box = chart.getBoundingClientRect();
    const x = e.clientX - box.left, y = e.clientY - box.top;
    log(x >= 50 && x <= 150 && y >= 30 && y <= 90 ? 'hit the box' : 'missed the box');
  }});

  const scroller = document.getElementById('scroller');
  scroller.addEventListener('scroll', () => {{
    document.getElementById('scrolled').textContent = scroller.scrollLeft + ',' + scroller.scrollTop;
  }});

  // The gap between keys, so typing speed can be checked from the page.
  let last = 0, smallest = Infinity;
  document.getElementById('keys').addEventListener('keydown', e => {{
    const now = performance.now();
    if (last) smallest = Math.min(smallest, now - last);
    last = now;
    const held = (e.ctrlKey ? 'Control+' : '') + (e.shiftKey ? 'Shift+' : '') + (e.altKey ? 'Alt+' : '');
    log('key ' + held + e.key);
    document.getElementById('gaps').textContent = isFinite(smallest) ? 'smallest gap ' + Math.round(smallest) : 'one key';
  }});
  document.getElementById('menu-zone').addEventListener('contextmenu', e => {{
    e.preventDefault(); log('right clicked');
  }});

  function showSettings() {{
    document.getElementById('size').textContent = innerWidth + 'x' + innerHeight;
    document.getElementById('tz').textContent = Intl.DateTimeFormat().resolvedOptions().timeZone;
    document.getElementById('lang').textContent = navigator.language;
    document.getElementById('online').textContent = navigator.onLine ? 'online' : 'offline';
    document.getElementById('scheme').textContent = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    document.getElementById('notify').textContent = Notification.permission;
    document.getElementById('mobile').textContent = /Mobile/.test(navigator.userAgent) ? 'mobile' : 'desktop';
    navigator.geolocation.getCurrentPosition(
      p => {{ document.getElementById('where').textContent = p.coords.latitude + ',' + p.coords.longitude; }},
      () => {{ document.getElementById('where').textContent = 'unknown'; }});
    log('settings shown');
  }}

  // A worker, as a page that crunches numbers in the background starts one.
  new Worker(URL.createObjectURL(new Blob(['onmessage = () => {{}}'], {{type: 'text/javascript'}})));

  document.cookie = 'flavour=ginger; path=/';
  localStorage.setItem('theme', 'green');
</script>
</body>
</html>
"""


def parity_page() -> str:
    return PARITY_PAGE


def data_json() -> str:
    return json.dumps(DATA)
