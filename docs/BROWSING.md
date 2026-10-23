# BROWSING.md — what Dejo must be able to do on a real website

Written 2026-09-01, after a test proved the browsing layer was far weaker than assumed.

**Since 0.2.0** every action and read below is a step line in one tool, `dejo_run`
(`engine/src/dejo/program.py`), and the tools named `dejo_act` and `dejo_read` are gone.
The capability list is current; the decision notes keep the tool names of their time.

## Why this document exists

Dejo was tested against a page containing a React-style dropdown, a shadow DOM, an iframe,
and a link that loaded late. Our page snapshot found **1 element**. Playwright's own
snapshot found **7**, with working handles for every one — including the button inside the
iframe.

The cause was not a missing feature. It was that the snapshot had been hand-written instead
of calling Playwright, which already does it better. The risk is that the same mistake is
sitting in the rest of the browsing layer, unseen, waiting for a real site.

So this document does not list the things we happened to think of. It lists **everything
Playwright can do**, taken from the installed library, and decides for each one whether
Dejo needs it. If something is missing from Dejo later, it should be because this document
said "no" on purpose.

## The rule that decides everything

> **A capability belongs in Dejo if it can be recorded once, replayed later with no model
> involved, and checked afterwards by a postcondition.**

Three consequences fall out of this, and they are the reason the list below is not simply
"all of Playwright":

- **No arbitrary JavaScript.** `evaluate` would let a step do anything, cannot be verified,
  and turns the trail into code we cannot reason about. It is also an escape hatch that
  would quietly become the answer to every hard problem.
- **No network manipulation.** Route interception and HAR replay change what the site *is*.
  Dejo's claim is that it repeats what a person did, on the real site.
- **No test-framework machinery.** Tracing, video, `pause`, `pick_locator` belong to a test
  runner, not to a memory.

## Where Dejo stands today

Measured 2026-09-01, before Phase 2.5 began, and updated as each step lands.

| | Playwright offers | Dejo had | Dejo has now |
|---|---|---|---|
| ways to act on an element | 21 | 4 | **21, plus 6 page-level** ✅ 2.5c |
| ways to find an element | 10 | 4 | **9, plus 2 refinements** ✅ 2.5e |
| page-level events (dialogs, popups, uploads) | yes | none | **all four, plus overlays** ✅ 2.5f |
| ways to wait for a page | 5 | 1 (fixed sleep) | **5 real waits** ✅ 2.5b |
| ways to read from a page | 18 | 1 (page text) | **12, plus 5 new postcondition kinds** ✅ 2.5d |

| frames / shadow DOM | yes | none | **both, plus div-buttons** ✅ 2.5a |

It started at roughly a quarter, and the missing parts were ordinary things: a hover menu,
a checkbox filter, a confirm dialog, a login that opens a new tab, a cookie banner.

---

# The complete inventory

Every public capability of `Locator`, `Page`, `BrowserContext`, `Keyboard`, `Mouse`,
`FrameLocator`, `Dialog`, `FileChooser` and `Download`, taken from playwright 1.62.0.

## 1. Acting on an element — `Locator` (21 methods) — ✅ ALL BUILT (2.5c, 2026-09-01)

All 21 are implemented in `src/dejo/actions.py` and each one has a test in
`tests/test_actions.py`. `test_every_action_is_exercised` fails if an action is ever added
without a test, so this table cannot drift away from the code again.

**This table originally marked the last five "no".** Rohit overruled that on 2026-09-01:
build everything, lose no edge case. The original reasoning is kept in the last column,
because two of those five turned out to earn their place and the other three did not — and
that is worth being honest about rather than quietly rewriting.

| Playwright | Dejo verb | in? | why |
|---|---|---|---|
| `click` | `click` | **yes** | already have |
| `dblclick` | `double_click` | **yes** | grids and file lists need it |
| `hover` | `hover` | **yes** | menus that only open on hover are everywhere |
| `fill` | `fill` | **yes** | already have |
| `type` / `press_sequentially` | `type` | **yes** | search and autocomplete boxes ignore `fill`, because they listen for keystrokes |
| `clear` | `clear` | **yes** | a field must be emptied before retyping, or values concatenate |
| `press` | `press` | **yes** | already have — Enter, Escape, Tab, combinations |
| `check` | `check` | **yes** | filters and consent boxes |
| `uncheck` | `uncheck` | **yes** | as above |
| `set_checked` | `set_checked` | **yes** | kept as its own verb, not folded (Rohit, 2026-09-01). `check` means "make sure it is ticked" and is safe to repeat; `set_checked` means "make it match this value". Only the second lands on a state we know for certain, and warm replay wants certainty |
| `select_option` | `select` | **yes** | now takes value, `label:`, `index:` and multi-select. Label matters most: sites change an option's hidden value far more often than the words a person reads |
| `set_input_files` | `upload` | **yes** | attaching a receipt or a CSV is a real repeated task |
| `scroll_into_view_if_needed` | `scroll_to` | **yes** | long lists and lazy loading |
| `drag_to` / `drop` | `drag` | **yes** | rarer, but kanban boards and reordering are real |
| `focus` | `focus` | **yes** | some forms only validate on focus/blur |
| `blur` | `blur` | **yes** | as above |
| `tap` | `tap` | **yes** | *was "no — mobile touch".* Built, but needs `Browser(touch=True)`. Touch is **off by default on purpose**: some sites serve a different mobile layout the moment they detect it, which would change what every other trail sees |
| `select_text` | `select_text` | **yes** | *was "no — a step toward copying".* That reason was wrong. `select_text` then `type` is how you replace the contents of a field that fights `fill` |
| `dispatch_event` | `dispatch_event` | **yes** | *was "no — bypasses the checks".* Still true, and its description says so in capitals. But it is the escape hatch when a site's button ignores a real click, and without it such a site is simply unusable |
| `highlight` / `hide_highlight` | `highlight` / `hide_highlight` | **yes** | *was "no — debugging aid".* Built, but marked `recordable=False`: they change nothing on the page, so they are never written into a trail |

### Also built, beyond this table: 6 page-level actions

`Locator` is only half the story — a trail has to move between pages too. These take no
element, and live in the same registry so that one `dejo_run` program covers a whole flow:

| Dejo verb | why |
|---|---|
| `goto` | open an address |
| `back` / `forward` | history, for flows that branch and come back |
| `reload` | some dashboards only refresh their numbers this way |
| `scroll` | the page itself, for feeds that load more as you go |
| `wait` | a fixed pause. Kept, but its own description tells the AI to prefer `wait_for` |

### Five real bugs this step found

Worth recording, because each would have hit a real site and none was visible from reading
the code:

1. **Warm replay silently did nothing for any unknown action** — `executor._do` had no
   `else`. If the page already satisfied the postcondition, that no-op was recorded as a
   **successful replay**. A false pass is worse than a failure.
2. **Only `click` and `press` waited for the page.** A `select` that navigated was never
   waited for. Now one `Browser.settle()` runs after every action.
3. **`select_option` was being given the JavaScript argument shape.** Python takes
   `value=` / `label=` / `index=` separately, so choosing by visible label failed.
4. **`mouse.wheel` returns before the scroll is applied**, so reading the position straight
   after gives the position from *before*. On an infinite feed: scroll, read the same rows,
   forever.
5. **The wheel only moves what is under the pointer**, which starts in the corner.

## 2. Reading from a page — `Locator` (18 methods) — ✅ BUILT (2.5d, 2026-09-01)

Dejo could read page text and nothing else. That is why "check my dashboard numbers" was
impossible, and reading is also what postconditions are built from.

Now in `src/dejo/reads.py`, 12 kinds, tested in `tests/test_reads.py`. Same registry shape
as `actions.py`, and the same rule: nothing in it resolves an element.

| Playwright | Dejo | in? | why |
|---|---|---|---|
| `inner_text` / `text_content` | `read(text)` | **yes** | the number, the status, the error message |
| `input_value` | `read(value)` | **yes** | also lets us verify a `fill` actually landed |
| `is_checked` | `read(checked)` | **yes** | verifying a `check` |
| `is_visible` / `is_hidden` | `read(visible)` | **yes** | "the dialog closed" |
| `is_enabled` / `is_disabled` | `read(enabled)` | **yes** | "the submit button became clickable" |
| `is_editable` | `read(editable)` | **yes** | split out, not folded into `enabled` as this table first said. A read-only field is **enabled but not editable** — calling it enabled would send a caller into a retry loop that can never succeed |
| `get_attribute` | `read(attribute)` | **yes** | href, aria-expanded, data attributes |
| `count` | `read(count)` | **yes** | "there are 3 unpaid invoices" |
| `all_text_contents` / `all_inner_texts` | `read(all_text)` | **yes** | reading a table or a list in one go |
| `aria_snapshot` | the snapshot itself | **yes** | replaces our hand-written collector. Still to do — this is step 2.5a |
| `bounding_box` | — | **no** | pixel geometry is not something to remember |
| `screenshot` | out of band | **later** | useful for the dashboard, never part of a trail |
| `inner_html` | — | **no** | raw markup is the cost we exist to remove |
| `evaluate` / `evaluate_all` / `element_handle` | — | **no** | see the rule |

### Also built, beyond this table: 3 page-level reads

| Dejo | why |
|---|---|
| `read(url)` | which page am I on |
| `read(title)` | the page title, a cheap way to confirm where you landed |
| `read(page_text)` | the whole page as text. A last resort, and its own description says to prefer `text` on one element |

### The 5 new postcondition kinds this unlocked

A postcondition is a read plus an expected answer, so `check_postcondition` now calls
`reads.read` instead of talking to Playwright itself. One reading path, so a check can
never disagree with the read an AI would have done by hand.

| kind | proves |
|---|---|
| `value_is` | a `fill` actually landed, instead of silently doing nothing |
| `checked_is` | a `check` actually ticked the box |
| `count_is` | "there are still 3 rows" |
| `attribute_is` | href, aria-expanded, data attributes |
| `element_gone` | the dialog closed, the spinner finished |

`Postcondition` gained an optional `target`. The older kinds keep their selector in
`value`; the new ones need `value` for the expected answer, so they put the selector in
`target`. Old playbooks already in memory still load — there is a test for exactly that.

**One bug found here:** adding `settle()` to the warm path but not the cold path meant
downloads were flushed *before* the download event arrived, so the file was never written.
The existing download test caught it. That test was itself written after an earlier miss,
where it only checked the download *event* and passed for a week while the file was being
thrown away.

## 3. Finding an element — `Locator` (finding methods) — ✅ BUILT (2.5e, 2026-09-01)

We stored four kinds of locator: role, text, css, structural(href). Now **nine kinds plus
two refinements**, so a step has nine chances to survive a redesign instead of four.

Built in `models.py` (the shape) and `browser.py` (capture and resolution), tested in
`tests/test_locators.py`.

| Playwright | in? | why |
|---|---|---|
| `get_by_role(name=)` | **have it** | the most durable thing on a page |
| `get_by_text` | **have it** | |
| `locator(css)` | **have it** | |
| `get_by_label` | **add** | the right way to find a form field; survives redesigns better than css |
| `get_by_placeholder` | **add** | ditto |
| `get_by_test_id` | **added, but not via `get_by_test_id`** | that method reads one globally configured attribute name, and real sites use `data-testid`, `data-test-id`, `data-test`, `data-qa` and `data-cy`. Dejo stores the attribute *name* with the value and matches on it directly, so it works on all five with no global setting. Still ranked first: a test id is written for machines and almost never touched |
| `get_by_title` / `get_by_alt_text` | **add** | cheap, and images/icons often have nothing else |
| `filter(has_text=)`, `nth`, `first`, `last` | **added, but not as kinds** | these are *refinements*, not ways of searching: "the third row" and "the row containing September" narrow any locator. So they are two optional fields on `Locator` — `nth` and `has_text` — that compose with all nine kinds, rather than two more kinds that would each only work one way. `first` is `nth=0`, `last` is `nth=-1` |
| `and_` / `or_` | **no** | combining predicates is more expressive than a stored trail needs |
| `frame_locator` / `content_frame` | **handled** | Playwright's ai-mode refs already reach inside frames (proven: `ref=f1e2`). Comes with 2.5a |

### The ranking, and why it is in this order

Order only decides what gets tried on the *first* replay — after that, measured confidence
reorders them. But the first replay is the one where a site has already changed.

`test_id` → `structural(href)` → `label` → `role` → `placeholder` → `alt` → `title` →
`text` → `css`

A test id is written for machines. A link target usually outlives its label. A label
usually outlives a CSS id, which is the first thing a rewrite throws away.

### Two bugs found here, both by the same test

`test_every_locator_a_real_element_offers_actually_resolves` walks every locator an element
offers and demands it find *that element*. A locator that is stored but never resolves is
worse than none — it costs a failed attempt on every single replay.

1. **A form field was given a `text` locator.** A field takes its accessible name from the
   `<label>` beside it, so searching the page for that text finds **the label, not the
   field** — and filling a label does nothing. Text locators are now only offered for
   elements that contain their own words.
2. **`alt` could resolve but was never captured.** The collector never looked at `<img>` at
   all, so the kind existed and no real page ever produced one. Images with non-empty alt
   are now collected — an icon button is often an image with nothing else on it. Empty alt
   means decorative, and a decorative image is not worth remembering.

**Six more locator kinds means a broken step has six chances to survive instead of four.**
This is the cheapest reliability we can buy.

## 4. The page — `Page` (118 methods)

### Navigation
| Playwright | Dejo | in? |
|---|---|---|
| `goto` | `goto` | **yes**, have it |
| `go_back` | `back` | **yes** — many flows depend on it |
| `go_forward` | `forward` | **built anyway** | this table said no. It came free with `back` and costs one line, so it is in and tested. Say the word and it goes |
| `reload` | `reload` | **yes** — the standard fix for a stuck dashboard |
| `url`, `title`, `content` | internal | **yes** |
| `set_content` | — | **no** — that is fabricating a page |

### Waiting — the thing modern sites need most — ✅ BUILT (2.5b, 2026-09-01)

In `src/dejo/waits.py`, reached through the `wait_for` action as `kind:subject`.
| Playwright | Dejo | in? | why |
|---|---|---|---|
| `wait_for_load_state("networkidle")` | `wait_for(idle)` | **yes** | a React dashboard is blank until its data arrives. Without this, `look()` sees an empty page — the single most likely cause of failure on PostHog |
| `wait_for_url` | `wait_for(url)` | **yes** | SPA routing changes the URL without a page load |
| `wait_for_selector` | `wait_for(element)` | **yes** | wait for the thing, not for a guessed number of seconds |
| `locator.wait_for(state=visible)` | used internally | **yes** | **we currently wait for `attached`, which is wrong** — it can act on an element that is still animating in |
| `wait_for_timeout` | `wait(seconds)` | **keep, discourage** | a fixed sleep is a last resort; the description should say so |
| `wait_for_function` | — | **no** | arbitrary JavaScript |

### Events that hang a run if ignored — ✅ BUILT (2.5f, 2026-09-01)
These are not element actions. If they are not handled, the browser simply stops.

| Playwright | Dejo | in? | why |
|---|---|---|---|
| `on("dialog")` | auto-handle + `dialog` verb | **yes** | an unhandled `confirm()` blocks everything after it. Playwright dismisses by default, which silently cancels deletes and saves — we must decide per step and record the choice |
| `expect_popup` / `on("popup")` | `popup` handling | **yes** | "open in new tab", and most OAuth flows |
| `expect_file_chooser` | part of `upload` | **yes** | some sites open a chooser rather than exposing a file input |
| `expect_download` | have it | **yes** | already working |
| `expect_navigation` | internal | **yes** | |
| **`add_locator_handler`** | `dismiss_when_seen` | **yes — high value** | Playwright's own answer to overlays that appear at unpredictable times: cookie banners, "rate us", survey pop-ups. Register once and Playwright clears it automatically whenever it blocks an action. This is exactly the thing that breaks recorded flows on real sites, and it is already built |
| `expect_console_message`, `page_errors` | diagnostics only | **later** | useful for explaining a failure, not for replay |
| `expect_request` / `expect_response` | — | **no** | this is a test framework's job |

### Input devices
| Playwright | Dejo | in? | why |
|---|---|---|---|
| `keyboard.press` | via `press` | **yes** | including combinations like `Control+A` |
| `keyboard.insert_text` | via `type` | **yes** | |
| `mouse.wheel` | `scroll(amount)` | **yes** | infinite-scroll lists that ignore `scroll_into_view` |
| `mouse.move/down/up` | — | **no** | raw coordinates are the least durable thing possible |
| `touchscreen` | `tap` | **built** | via `Browser(touch=True)`, which is off by default: some sites serve a different mobile layout the moment they detect touch, and that would change what every other trail sees |

### Frames
| Playwright | Dejo | in? |
|---|---|---|
| `frames`, `frame_locator`, `main_frame` | handled by ai-mode refs | **yes** |

Proven: a button inside an iframe was returned as `ref=f1e2` and was clickable with no
frame-specific code. Durable locators inside frames still need thought — see Open questions.

### Emulation, storage, network, scripts, diagnostics
| Playwright | in? | why |
|---|---|---|
| `set_viewport_size` | **yes** | a narrow window shows a hamburger menu instead of a nav bar, so a trail recorded at one size can break at another. Fix the size |
| `local_storage` / `session_storage` | **no** | the browser profile already carries these |
| `emulate_media`, `clock` | **no** for now | `clock` is worth remembering for date-dependent dashboards. Noted, not built |
| `screencast`, `video`, `pdf` | **no** | not part of a trail |
| `route`, `route_from_har`, `unroute` | **no** | changes what the site is |
| `add_init_script`, `add_script_tag`, `expose_function` | **no** | injecting code into someone's site |
| `pause`, `pick_locator` | **no** | interactive debugging |
| `screenshot` | **later** | for the dashboard and for explaining a repair, never a step |

## 5. The context — `BrowserContext` (40 methods) — ✅ BUILT (2026-09-01)

Tested in `tests/test_context.py`. Most of this class is deliberately absent: cookies
and storage are already handled by keeping a whole browser profile, which is stronger
than replaying a saved blob.

| Playwright | in? | why |
|---|---|---|
| `storage_state` / `set_storage_state` | **already solved** | we keep a whole browser profile, which is stronger |
| `cookies` / `add_cookies` / `clear_cookies` | **no** | the profile handles it |
| `grant_permissions` | **built** | nothing is granted unless a caller asks. A site that wants notifications puts a prompt over the page, and a prompt blocks everything behind it. Denying is silent, and silence is what an unattended agent needs |
| `set_geolocation` | **built** | `Browser(geolocation=(lat, lon))`. Passing one grants the geolocation permission automatically — granting it *without* a position makes a site wait forever for a fix that never arrives, so the two always travel together. Note: Chrome only hands out a position on a secure origin |
| `set_offline` | **no** | |
| `new_page` / `pages` / `expect_page` | **built** | `new_tab` opens one we asked for, `switch_tab` moves between them, and a tab the *site* opens is noticed but never switched to. Every tab gets the same dialog and download listeners, attached once each |
| `set_default_timeout` | **built** | `Browser(timeout_ms=...)` and `set_timeout()`, applied to the context so every call inherits it. Default 15s rather than Playwright's 30s, so a broken site surfaces sooner |
| `tracing` | **no** | test framework |
| `route*`, `service_workers`, `new_cdp_session` | **no** | |

## 6. Dialog, FileChooser, Download

| Object | Dejo |
|---|---|
| `Dialog.accept / dismiss / message` | recorded as a step: which choice was made, and what the message said |
| `FileChooser.set_files` | folded into `upload` |
| `Download.save_as / suggested_filename` | **already working** |

---

# What Dejo ended up with

Counted from the code on 2026-09-01, not from the plan above — the plan was written before
any of it existed and undercounted.

**Actions (31)**, all as step lines in `dejo_run`:

- *element* — click, double_click, hover, tap, fill, type, clear, press, select_text,
  check, uncheck, set_checked, select, upload, scroll_to, drag, focus, blur,
  dispatch_event, highlight, hide_highlight
- *page* — goto, back, forward, reload, scroll, wait, wait_for, new_tab, switch_tab,
  dismiss_when_seen

**Reads (12 kinds)**, all as `read` steps in `dejo_run` — text, all_text, value, checked,
visible, enabled, editable, attribute, count, url, title, page_text. The page itself, one
line per control, comes back from every call that stops or ends with `look`.

**Waits (5)** — element, gone, text, url, idle. None of them is a sleep.

**Locator kinds (9, from 4)** — test_id, structural(href), label, role, placeholder, alt,
title, text, css. Plus two refinements that compose with all nine: `nth` and `has_text`.
Plus `frame`, so a locator inside an iframe can be resolved again.

**Postcondition kinds (10, from 5)** — url_contains, text_present, text_gone,
element_present, element_gone, download, value_is, checked_is, count_is, attribute_is

**Page events (4)** — dialogs, popups and new tabs, file chooser, overlays.

Every one of these is a thin pass-through to Playwright. The cost is breadth, not depth.

## The escape hatch (decided 2026-09-02)

Rohit asked for all 177 Playwright methods as named actions: *"in the real world we cannot
guess that ohh this is not useful, maybe this is useful we dont know just yet, because the
web is changing."*

He is right about the risk, and he had already been proved right twice — I marked
`select_text` and `dispatch_event` as "nobody needs these" and both turned out to matter.

But the framing needed one correction. **Dejo already HAS all of Playwright.** It is an
installed dependency and all 177 methods are callable right now. This registry does not
decide what Dejo *can* do; it decides what gets written into a trail. Those have different
costs — more power while exploring is nearly free, while more names in a trail measurably
hurts tool choice, and a host AI has already ignored Dejo once and reached for `curl`.

So instead of 94 named actions, **one `evaluate`**:

- runs any JavaScript, on the page or on one element
- covers everything nobody thought of, without anyone having to predict it
- **is never written into a trail**, because a step made of code cannot be repaired.
  Repair works by finding an element again; a blob of JavaScript has no element, so it
  could only ever break.

Plus the three things a hatch genuinely does not cover:

| built | why a hatch does not cover it |
|---|---|
| `read(console_errors)` / `read(failed_requests)` | you cannot ask the page why it failed — the failure already happened. These are collected as they occur |
| `set_time` | a trail recorded in September reads the wrong month in October, and nothing about that looks like a broken step |
| `screenshot` | for showing a human what happened. Never a step |

**My old reason for excluding `evaluate` was weak** and is worth correcting: I said it was
about protecting the user from arbitrary code. It was not — the host AI already has shell
access and could write its own Playwright script. The real reason is repairability, and
that is solved by never recording it.

## Full parity — deferred, NOT dropped

Rohit's call, 2026-09-02: *"we are not discarding things, we are just shifting them to the
end, so if we have time we will do it."*

Everything in the table below stays on the list. `evaluate` means none of it blocks a real
site in the meantime — the AI can already do all of it, just without a name. When a real
website shows us one of these earns a name, we promote it and it becomes recordable.

That order is better than guessing now: a capability promoted because a real site needed it
arrives with a real test.

## What is deliberately still out

Nothing on this list is missing by accident, and none of it is needed to use a website:

| left out | why |
|---|---|
| `evaluate`, `evaluate_all`, `element_handle` | running arbitrary JavaScript. It cannot be verified afterwards, and it is the escape hatch that would let a trail do anything at all |
| `inner_html` | raw markup is the cost Dejo exists to remove |
| `route`, `route_from_har`, `unroute` | intercepting network traffic changes what the site *is*. A trail recorded against a faked response is a trail against a site that does not exist |
| `add_init_script`, `add_script_tag`, `expose_function` | injecting code into somebody else's site |
| `tracing`, `video`, `screencast`, `pdf` | test-framework and recording features, not part of a trail |
| `bounding_box`, `mouse.move/down/up` | raw pixel coordinates are the least durable thing on a page |
| `and_` / `or_` | combining predicates is more expressive than a stored trail needs |
| `set_content` | fabricating a page rather than visiting one |
| cookies, `storage_state`, local/session storage | the browser profile already carries all of it, and carries it better |
| `pause`, `pick_locator` | interactive debugging, with nobody sitting there |
| `expect_request` / `expect_response` | a test framework's job |
| `set_offline` | no use in a recorded trail |

**All three are now built (2026-09-02).** What is left is the table above, deferred to Phase 7:

1. ✅ **`screenshot`** — built, never a step.
2. ✅ **`console_message` / `page_error`** — built as `read(console_errors)` and
   `read(failed_requests)`.
3. ✅ **`clock`** — built as `set_time`.

---

# Changes to what already exists

1. **Delete `_COLLECT_JS`.** Replace with `page.locator("body").aria_snapshot(mode="ai")`,
   which returns roles, names, urls and refs, pierces shadow DOM and reaches into iframes.
   About 60 lines of my JavaScript deleted.
2. **Act through `aria-ref=` while exploring.** Verified working, including in frames.
3. **Stored locators stay durable.** Refs are only valid inside one snapshot, so they can
   never be written to memory. The trail keeps role/text/css/href plus the six new kinds.
   **This is why this is a contained change: the memory format, the repair logic and the
   deletion gate are untouched.**
4. **Wait for `visible`, not `attached`**, so animations settle before clicking.
5. **Register `add_locator_handler` for cookie banners** as part of site knowledge, so an
   overlay learned once is dismissed forever after.

---

# Open questions — decide before building

1. **Durable locators inside iframes - DECIDED 2026-10-20.** A stored locator names its
   iframe by a CSS selector (`Locator.frame`). Which iframe an element is in comes from
   NESTING in the snapshot, never from Playwright's `f<N>` number: after any navigation
   Playwright prefixes the main page's refs too, and reading that number as "which frame"
   saved iframe steps with no frame, so they never replayed
   (`engine/tests/test_frame_after_navigation.py`). Callers see Dejo's own refs, `e16` on the
   main page and `f1e3` in the first iframe, the same on every visit.
2. **Dialogs during replay - DECIDED 2026-09-01.** A step records the choice **and** the
   message. On replay, if the message has changed, stop and hand it back rather than
   accepting. A trail that recorded "click OK" must never blindly accept a box that now says
   "delete 400 rows?". Note that Playwright's default is to *dismiss* every dialog, which
   would silently cancel a save - so doing nothing is not neutral either.
3. **Popups.** When a click opens a new tab, does the trail continue in the new tab or the
   old one? Must be recorded explicitly, not guessed.
4. **`type` versus `fill`.** Dejo should probably choose automatically — try `fill`, and if
   the value does not stick, fall back to real keystrokes. That is a postcondition doing
   useful work rather than a flag the AI has to reason about.
5. **How many verbs before an AI gets confused? - DECIDED 2026-09-01.** **One `dejo_act`
   tool with an `action` argument.** Never sixteen tools. Tool choice is the most fragile
   part of the whole system - a host AI ignored Dejo entirely and reached for `curl` on the
   first live test. Sixteen more names to choose between makes that worse. The action list
   lives in one description where it can be read at a glance. *(Taken further in 0.2.0:
   one `dejo_run` tool, every action a step line, five tools in all.)*

---

# Prior work to declare

- **Playwright** (Apache-2.0) — Dejo calls it; nothing is copied. The mistake being
  corrected here was writing our own version of something it already provided.
- **`@playwright/mcp`** — their tool design is the reference for which verbs an AI actually
  needs and how to describe them. Design influence, no code. Must go in the README's Prior
  Work section.

---

# Cost and the decision

Roughly **1½ to 2 days** with tests, done properly.

Phases 0–2 are complete and the deadline is Sep 10, so this fits — but it means dropping
the backend and the dashboard. `MASTER-PLAN.md` already lists those as the first two things
to cut, and says never to cut the memory showcase.

I argued for cutting this to half a day and spending the rest on the memory story, since
"coordination and dynamic-storage patterns top the band" is where the 40% is won.

**Rohit's call, 2026-09-01: build all of it, cut nothing.** He does this kind of work
himself, so the browsing layer is not a demo prop - it is the reason the tool exists. Nine
days is enough for both, and the coordination half is now Phase 5a, which needs no
blockchain and is not blocked.

Scheduled as **Phase 2.5, Sep 2-3**. `MASTER-PLAN.md` carries the day-by-day schedule.

## Progress

- **Section 5, the context: DONE 2026-09-01.** Permissions denied by default,
  geolocation, `new_tab`, one timeout. 16 tests.
- **2.5b — waiting: DONE 2026-09-01.** Five real waits (element, gone, text, url,
  idle) and the `attached` → `visible` fix. The viewport was fixed back in 2.5c.
- **2.5f — page events: DONE 2026-09-01.** Dialogs, tabs, overlays, file choosers. 34 tests.
- **2.5h — the hard page: DONE 2026-09-01.** Nine obstacles on one URL at
  `/hard`, and a test that walks all nine in one journey. 19 tests.
- **2.5g — the MCP surface: DONE 2026-09-01.** `dejo_open` and `dejo_look` are gone.
  One `dejo_act` and one `dejo_read`, both described from the registries. 20 tests.
- **2.5a — the snapshot: DONE 2026-09-01.** On Playwright's own engine. The
  hand-written collector is deleted. 36 tests.
- **2.5e — finding: DONE 2026-09-01.** Nine locator kinds plus `nth` and
  `has_text` refinements. 34 tests.
- **2.5d — reading: DONE 2026-09-01.** 12 read kinds and 5 new postcondition kinds,
  built on one shared reading path. 40 tests.
- **2.5c — the action set: DONE 2026-09-01.** All 21 `Locator` actions plus 6 page-level
  ones, in one registry, wired into both the cold and the warm path. 46 tests. Five real
  bugs found on the way, listed in section 1.
**Phase 2.5 is complete.** All eight steps done, 385 tests passing.

### The finish line, checked honestly

1. **Hard page, every control found and actionable** — ✅ nine obstacles, all exercised.
2. **Every action and read records, replays and verifies** — ✅ for recording and
   verifying; every one of the 31 actions and 12 reads has a test, with a guard test that
   fails if one is added without. **Partly honest:** warm replay runs through the same
   registry and is proven end to end on the demo site, but not every individual action has
   been replayed warm. Nothing suggests a gap; it is simply not claimed.
3. **One `dejo_act` with an `action` argument** — ✅. "Three vague prompts route to the
   right action" is **not** tested: it needs a model, and this project has no API key by
   design. What is tested instead is that every action name appears in the one description,
   generated from the registry so it cannot drift.
4. **Dialog recorded with its message, replay stops if it changed** — ✅.
5. **Cookie banner learned once, dismissed on every later run** — ✅, after two bugs were
   found while checking this exact claim.

### 2.5a: what the snapshot change actually bought

Measured on one page holding a shadow DOM, an iframe, a `div` acting as a button and a
late-loading link. The old hand-written collector found **1** element. Playwright's
`aria_snapshot(mode="ai")` finds **8**, and every one is clickable.

The `[cursor=pointer]` flag is the quiet win. A `div` with a click handler has no
interactive role at all — it is the shape most component libraries produce, and the old
collector was blind to every one. A pointer cursor is the site itself saying "this is
clickable".

**Frames are now named in the locator.** This was the open question left in section 3. A
ref reaches into a frame on its own, but a *stored* locator cannot: `page.locator` does not
look inside iframes, so a selector recorded in one would find nothing on the next run.
`Locator.frame` carries the iframe's own selector, and resolution goes through
`page.frame_locator(...)`. There is a test that strips the frame off a working locator and
proves it then finds nothing.

**Descriptors are read on demand.** The snapshot gives role, name and a ref cheaply. The
durable descriptors cost a round trip each, so they are read only for elements actually
acted on — and for repair candidates, where whoever fixes the step has to write down
something more lasting than a ref.

### A security problem this uncovered

**Playwright's AI snapshot prints the contents of every field in plain text, passwords
included:** `textbox "Password" [ref=e3]: hunter2`. Reading a page would have carried the
password out of the browser.

Dejo keeps the *fact* that a field is filled and throws the contents away — one rule for
every field, so there is no exception to remember. A caller that genuinely needs the text
asks with `read(value)`, which is a deliberate act rather than a side effect of looking.
`describe` reads real values later, in the page, where it can see `type=password` and
redact it.

Telling the two cases apart matters: with a quoted name the trailing text is the field's
*contents*, without one it is the element's *name* — which is the only thing a
`div role="combobox"` has. Both are tested.

### What 2.5b and 2.5f actually changed

**The `attached` bug was real.** `resolve` waited for `attached`, which is true the moment
an element exists in the page — including while it is still sliding into place and cannot
receive a click. It now waits for `visible`, which also waits for it to stop moving. Any
site with an animation could have been clicked mid-flight.

**Dialogs are answered, never ignored.** An unanswered `confirm()` blocks every later step:
the browser simply stops. Dejo accepts by default and records both the wording and the
choice. Playwright's own default is to *dismiss*, which silently cancels a save — the run
looks like it worked while nothing happened. On replay, a step that answered "Save
changes?" **stops** if the box now reads "Delete 400 rows?".

**A new tab is noticed but never switched to.** Which tab a trail continues in is recorded,
not guessed.

**`upload` covers both shapes.** Plenty of sites hide the real file input behind a styled
button, so attaching to the element is impossible; clicking it opens the chooser, which
Playwright can catch. One verb, both cases.

**Overlays are site knowledge, not steps.** A cookie banner appears whenever the site feels
like it, not at a fixed point in a flow — so pinning it to a step records an accident.
`dismiss_when_seen` registers it against the site, and `SiteKnowledge.overlays` remembers
it. This is the classic killer of recorded flows, and Playwright had the answer built in.

**One bug found:** attaching the download listener twice queued the same file twice, and
saving an already-saved download fails — so the file silently never reached disk. Found by
the download test that already existed for exactly this class of failure.
