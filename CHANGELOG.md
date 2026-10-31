# Changelog

Every release of `dejo` and `dejo-mcp`. The two are released together with the same version.

## 0.3.0 — 2026-10-31

- **`select` on a combobox names a matching button that was already beside it.** The reply
  named only what appeared after typing, so on launchit.site `select combobox "" "JavaScript"`
  said "nor anything else to click" while `button "JavaScript +"` sat next to the box. It
  now also names the buttons and links next to the box that say the typed words.
- **A task that signs in on the way to its work does the work when already signed in.** A
  trail learned signed out signs in first. Replayed signed in, the site skipped its sign-in
  page, and the replay stopped there and said the work was done: on launchit.site "submit a
  product" stopped at "Continue with Google" on /register and submitted nothing. Now, when
  the site shows it is past its sign-in page, the replay skips the trail's sign-in steps,
  says so, and runs the rest. A trail that is only a sign-in is still "already done".
- **A new task is never given a trail that does something else.** A request was matched to a
  site's only trail when the two names shared any one word, so on launchit.site a brand-new
  "submit" task, whose name shared the product's name with the saved sign-in trail, replayed
  the sign-in and stopped on its page instead of answering "new task". Now two names that
  say they do different things (sign in, add or submit, delete or cancel, buy, send, edit,
  or only look something up) are never the same job, and the reply says which trail ran
  whenever it was found by other words and could not start.
- **`select` on a combobox that draws no options says what it drew instead.** A box whose
  suggestions are plain buttons (launchit.site's "Built with" shows `JavaScript +`) got
  "Its options are ." with nothing after it. The reply now says it typed the words and no
  options appeared, and names the buttons and links that did appear, so the agent can fill
  the box and click one.
- **The first look at a client-side app shows the page it draws.** A `go` returned as soon as
  the page's HTML had arrived, before the app's own code had loaded and drawn anything, so
  launchit.site/submit showed only its header and footer and tinylaunch.com/dashboard a
  signed-out shell. A `go` now waits, like a click that changes the address, until the
  page's scripts and requests have finished and nothing has been redrawn for half a second.
- **A task's steps never run on another site's page.** Every task in a profile shares one
  tab, so steps sent for one site could run on a page a task for another site had left open
  (a `js` line for agenticskills.io ran on saashub.com, and nothing said so). Dejo now goes
  back to where the task left the tab first and says so in the reply; steps that name refs
  from the old view do not run, and the task's page is shown again for fresh ones.
- **A sent form is shown after the site answers.** A `click!` on a submit that sends in the
  background returned while the form was still sending (fields disabled, no result yet). A
  sent step now waits until the page is still, and keeps any toast or status line that
  appeared on the way, so the reply shows what the site said.
- **Every sent step says whether the page answered:** its message, the requests that failed
  (4xx/5xx), or that nothing appeared.
- **A form the browser holds back is named.** When a submit is stopped by the browser's own
  checks ("Please fill out this field"), the reply stops and names the fields instead of
  looking like it worked.
- **Plain words are not risky on things that cannot send.** A link only opens a page, a tab or
  an option only switches what is shown, and removing a chip from an unsent form deletes
  nothing, so none of them needs a `!` any more. A link sent as a POST or DELETE still does.
- **Filled fields read as filled.** A box with a placeholder kept its value on a line of its
  own and showed no `[filled]`. `read` on a field now gives what it holds: a box's value or a
  dropdown's chosen option (never a password).
- **More dropdowns and check boxes work.** `select` chooses in a dropdown the site hides behind
  its own menu, and in a combobox that is not a `<select>` (it types, then clicks the option);
  it says so when a dropdown is disabled. `check` ticks a styled box through its own label
  when the label covers the real one.
- **Any ref the page has can be used**, including folded rows, lines past the view's budget,
  refs from a full view after a partial `look`, and refs spelt as `look raw` prints them.
- **`\n` in a fill is a new line in a text area** (kept as written in a one-line box).
- **`wait` waits** for its target to appear instead of failing because it is not there yet.
- **One long text can be read by its parts:** `read passage "words" eN as name` gives the section or paragraph that
  says some words, and `look <words>` shows where they are.
- **Pages are shown drawn.** After any step that moves to another address, Dejo waits until a
  single-page app is still.
- **Sites get the machine's language and region,** not the browser's en-US. `DEJO_LOCALE`
  chooses another.
- **Nameless buttons and links are described:** the words they show, what their icon says, or
  that they have no name. Such a button is saved by the words beside it, and every saved step
  says truly how it is found.
- **Uploads are checked:** the file must reach the page's file box, or the reply says why not.
- **A tab a step opened is named** in the reply, with how to work in it.
- **The view is clearer:** a disabled control with no ref stays in it, marked disabled; an open
  modal dialog comes first; a block repeated word for word prints once with a count; a card
  that is one nameless link is kept; `look raw from` stops at the end of its section; every
  `look` in one call is shown, in order.
- **One-time sign-in codes and magic-link tokens are hidden** in the view and in `look raw`; a
  `read` of the element still gives them.
- **Fewer false alarms.** reCAPTCHA's invisible badge is not a human check; Reddit's "Prove your
  humanity" page is. A site that is down is never blamed on the profile, and nobody is told to
  delete a profile for it.
- **Slow pages and redirects are handled in words.** A heavy page that takes too long to
  describe is looked at again, and a `go` cut off by the page's own redirect is retried,
  instead of showing Playwright's raw error.
- **Replays are safer.** A cookie-banner click is skipped when the banner is not shown. A trail
  that needed a `js` change is not saved, with the reason. The page's own title comes back
  after a `js` line writes to it. Every replay reply says how to replace a trail that gives
  the wrong answer.
- **A profile another Dejo session holds is refused, naming that session,** instead of falling
  back to another browser.
- **The MCP server reports Dejo's own version**, not the MCP library's.
- **A sign-in window behind a Cloudflare check no longer spins forever.** Between calls,
  Dejo's browser thread waited on its job queue and made no Playwright calls, and Playwright
  only handles the browser while a call runs. A page left alone that way stalled:
  `dejo_login` on saashub.com sat on "Just a moment..." for good, and an `alert()` stayed open
  until the next call. The worker now keeps the browser answered while it waits
  (`engine/tests/test_worker.py`).
- **A sign-in kept in a session cookie now survives Dejo's browser closing.** Chrome drops a
  cookie with no expiry when the browser closes, and Dejo's closes after every sign-in window
  and server restart, so on sites like saashub.com `dejo_login` worked and the next run was
  signed out. Session cookies in a profile are now given a 30-day expiry inside the browser,
  at close and every few seconds while it waits (for a person who shuts the window
  themselves). They stay in Chrome's own encrypted cookie store; nothing is written anywhere
  else.
- **A plain dropdown shows its choices.** The options of a native `<select>` have no ref in
  Playwright's snapshot, so the page view left them all out and an agent could not see what
  to pick. Its line now lists them and the one chosen:
  `e3 combobox "Category" [chosen "Productivity"]: options Choose one · Development · …`,
  cut with "+N more" on long lists, and every option counts when the view ranks lines by
  the task.
- **`select` with an option that is not there stops at once and names the real ones.** It
  waited Playwright's full 15 seconds and then returned the bare "Locator.select_option:
  Timeout 15000ms exceeded". Plain words now also match what the option shows, not only the
  value behind it, so `select e3 "September"` picks the option whose value is `sep`.
- **What a `js` line returns is in the reply** (`js returned: ["January", "September"]`,
  as JSON, capped at 2,000 characters). It was thrown away, so agents wrote it into the page
  title just to see it.

## 0.2.1 — 2026-10-23

- **Dejo no longer tells websites it is a hidden browser.** With a browser profile, which is
  every MCP session, Dejo's headless Chrome introduced itself as `HeadlessChrome`, and
  Cloudflare checks and plain 403 walls turned it away on sight. The honest user agent (the
  real Chrome version, without that one word) was only used when no profile was open. On the
  six real-site benchmark tasks that had been blocked for every headless tool, Dejo now opened
  all six sites and answered five of them right
  (`benchmarks/benchmark-real-2026-10-23-agent.json`).

## 0.2.0 — 2026-10-23

**Learning a website now costs fewer tokens, on average, than using a browser tool with no
memory at all.**
On 19 tasks across 12 lesser-known real websites (Claude Sonnet 5, medium), Dejo got 19 of 19
right; the first run averaged 251k tokens against Playwright MCP's 409k (17 of 19 right) and
Playwright CLI's 559k (18 of 19), and 17 of 19 repeats were a single tool call at about 81k
tokens. Tasks and raw results are in `benchmarks/` (`real_tasks.py`,
`benchmark-real-2026-10-2*.json`).

### Breaking: five tools instead of sixteen

Every tool name is read on every turn, and choosing between sixteen was where agents went
wrong. The old names are gone:

| 0.1.x | 0.2.0 |
|---|---|
| `dejo_run`, `dejo_act`, `dejo_read`, `dejo_save`, `dejo_repair` | `dejo_run` (steps, one per line) |
| `dejo_login`, `dejo_login_done` | `dejo_login` (then `done=true`) |
| `dejo_profile` | `dejo_profile` |
| `dejo_sites`, `dejo_show`, `dejo_map`, `dejo_commons` | `dejo_memory` (`what=sites/show/map/commons`) |
| `dejo_forget`, `dejo_note`, `dejo_share`, `dejo_borrow` | `dejo_manage` (`do=forget/note/share/borrow`) |

Replies are plain text, not JSON: the whole tool list is about 3,900 characters (was 29,000).
`dejo_run` is marked to load up front in Claude Code. The CLI (`dejo run`, `dejo sites`,
`dejo show`, `dejo forget`, `dejo map`, `dejo login`) is unchanged, and memory from 0.1.x is
kept.

### Added

- **Steps.** Your agent sends many steps in one call (`click link "Issues"`, `read css ".count"
  as open`). They run in order; Dejo stops at the first that fails, keeps the ones that passed,
  and shows the page there, so the next call sends only the rest. A step that reads the answer
  saves the task by itself; `done=true` saves one that reads nothing.
- **A new page view.** One line per control, each with a ref, the words of the task first, long
  pages folded and paged. `look` shows it on purpose, also in the middle of steps.
- **Picks by place.** `click css "article h3 a" first` stores "the first one", so a list in a
  new order still opens its first item.
- **Repair in place.** When a replay breaks at one step, one line fixes it. The new way goes
  first, the old ways that worked stay as backups, and the rest of the task replays in the same
  call.
- **Risky steps.** A step that buys, pays, sends, deletes or submits must be marked with `!`;
  unmarked, it is not done, and a marked one never runs twice on its own.
- After saving, Dejo says what every replay will answer, and a read sent again with the same
  name replaces the old one.

### Fixed (found on real websites)

- Address checks keep the part after `?` that changed (page 5, a price filter, sites that serve
  every page as `/content.php?navoid=N`), and a stored way of finding an element must match only
  that element. Before, a replay could click the wrong link and call it right.
- A url given on replay that is only the trail's own start with parts left out no longer
  replaces the start (it sent "page 5" back to page 1).
- A Cloudflare "Performing security verification" page is recognised: Dejo stops at once and
  keeps nothing done on it. A 403 or 429 says the site refused this browser, a 401 asks for a
  sign-in.
- Learning's `go` records the page's HTTP status, so an error page is no longer learned on.
- A slow first page that did arrive counts as arrived, and a saved task always starts with a
  `go`.
- A bare `press Enter` replays, and Dejo waits for the page it submits to.
- A read of the whole page is refused; a field typed into again drops the first try.
- A locator that worked once is kept as a backup after one miss (it used to be dropped).

## 0.1.2 — 2026-10-18

- **A run that ends with a click waits for the address to stop moving.** An app that redirects
  on a timer after sign-in (pushState a beat later) sends no request, so "the network is quiet"
  was already true and the run could return on the sign-in page. Found on macOS CI.
- **A sign-in page is no longer read as the answer.** Replaying a Google Doc while signed out,
  Google sent the document to its sign-in page with the document's address in the query string.
  The address check matched that, walking back joined the document's path onto
  accounts.google.com (a 404 page), and the run reported `ok` with the 404 text as the answer.
  Address checks now ignore the query string unless the saved address has one, walking back
  stays on the route's own site, and the run reports `needs_login`.
- **An error page stops the run.** When a site answers a step's address with HTTP 400 or above,
  the run stops with the new outcome `page_error` (`dejo run` exit code 6) instead of reading
  the error page. Nothing is marked broken and no repair is offered. A 401/403 that shows a
  sign-in page is reported as `needs_login`.
- **A site's only route is not run for a different job.** "read the keywords tab of the Sheet"
  ran the one route saved on docs.google.com, "read the full text of a Google Doc", because
  both start with "read". Sharing only an action word (read, open, check, download...) no
  longer counts as the same task; a swapped subject ("message riya" for "message ankush")
  still does.
- **`dejo run` prints the answer.** A run read the value it was saved for (the open issue
  count, the invoice total) and never showed it, so a terminal run ended with no result.
- **`dejo run --json`** prints one line of JSON (outcome, answers, saved files, time) for cron
  jobs and scripts. Exit codes: 0 done, 1 failed or needs a repair, 2 no trail or the site was
  rebuilt, 3 needs a sign-in, 4 blocked by a captcha, 5 not on the trail's starting page, 6 the
  page answered with an HTTP error.
- **The README's `dejo run` example works.** It showed `--task`, which `run` does not have, so
  the first command a reader copied failed. `run` takes the task as plain words:
  `dejo run "count open issues" --site github.com`. `dejo borrow` suggested the same broken
  form and now prints the working one. A test checks every `dejo` command in the READMEs.
- `dejo --help` names the real default memory file, `~/.dejo/memory.db`.
- The README no longer says every tool answered "correctly" 30 times out of 30. The benchmark
  checks that an answer came back, not that it was right, so it now says every tool answered.
- **The Claude Code setup line adds Dejo for every project.** `claude mcp add` alone adds a server
  to the current folder only, so Dejo vanished when Claude Code opened anywhere else. The READMEs now
  say `claude mcp add --scope user dejo -- dejo-mcp`.

## 0.1.1 — 2026-10-15

- **Moving from Cairn is instant.** An old `~/.cairn` folder is now moved to `~/.dejo` instead of
  copied. A real folder held 1.5 GB of signed-in browser profiles, and copying it took longer
  than an MCP client waits for a server to start, so the first start looked like a failure.
- Listed in the official MCP Registry as `io.github.dejohq/dejo-mcp`.
- The test suite can no longer touch the real `~/.dejo` or `~/.cairn` on a developer's machine.

## 0.1.0 — 2026-10-15

The first release under the name Dejo. Formerly Cairn (`cairn-browser`, `cairn-browser-mcp`).

- **Dejo's own memory.** One SQLite file, `~/.dejo/memory.db`, with no size limit and no
  account. An existing Sibyl memory is brought across on first start. Sibyl stays available
  as an optional backend (`pip install "dejo[sibyl]"`, `DEJO_MEMORY=sibyl`).
- **Signing in is checked.** `dejo_login_done` and `dejo login` look at the window before
  saying you are signed in, and never record a sign-in that did not happen.
- **A stuck browser profile is named.** When a page times out in a saved profile and loads in
  a fresh browser, Dejo says the profile is stuck, instead of blaming the website.
- **Waiting for an iframe waits for its content.** `wait_for element:` on a frame waits for
  something inside it, and the new `in_frame:<frame>|<inside>` waits for one thing in a frame.
- **A step whose proof arrives late is not called broken.** A step that acted gets up to 3
  seconds for its check to come true.
- Everything moved to the new name: the `dejo` command, `dejo_*` tools, `DEJO_*` settings
  (old `CAIRN_*` ones still work) and `~/.dejo`.
- The paid "sell a trail" market (x402 on Base) from the hackathon version was removed.
