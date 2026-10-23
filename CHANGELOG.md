# Changelog

Every release of `dejo` and `dejo-mcp`. The two are released together with the same version.

## Unreleased

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
