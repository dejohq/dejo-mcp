<p align="center">
  <a href="https://dejo.run">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset=".github/assets/dejo-mark-white.svg">
      <img alt="Dejo" src=".github/assets/dejo-mark-black.svg" width="76">
    </picture>
  </a>
</p>

<h1 align="center">Dejo</h1>

<p align="center">
  <strong>A browser your AI agent remembers.</strong><br>
  It learns a website once. Every run after that is one tool call, with zero model calls.
</p>

<p align="center">
  <a href="https://pypi.org/project/dejo-mcp/"><img alt="PyPI" src="https://img.shields.io/pypi/v/dejo-mcp?label=pypi&color=0b0d10"></a>
  <a href="https://pypi.org/project/dejo-mcp/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/dejo-mcp?color=0b0d10"></a>
  <a href="https://github.com/dejohq/dejo-mcp/actions/workflows/test.yml"><img alt="Tests" src="https://github.com/dejohq/dejo-mcp/actions/workflows/test.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-0b0d10"></a>
</p>

<p align="center">
  <a href="https://dejo.run">Website</a> ·
  <a href="#install">Install</a> ·
  <a href="#benchmark">Benchmark</a> ·
  <a href="#tools">Tools</a> ·
  <a href="docs/BROWSING.md">What it can do</a> ·
  <a href=".github/CONTRIBUTING.md">Contributing</a>
</p>

Your AI can use websites. But it forgets how, every single time. Dejo makes it remember.

Dejo gives Claude Code, Codex, Cursor or any MCP client a browser with a memory. Your agent
walks a website once: signing in, clicking, reading. Dejo writes down the route. Every run
after that follows the route instead: **one tool call, no page reading, zero model calls.**
When the site changes, Dejo repairs the one step that moved and keeps the rest.

## Install

Python 3.11 or newer.

```bash
pip install dejo-mcp
playwright install chromium      # the browser, a separate download of about 150 MB
```

Then connect it to your agent:

| agent | where | what |
|---|---|---|
| Claude Code | your terminal | `claude mcp add --scope user dejo -- dejo-mcp` |
| Codex | `~/.codex/config.toml` | `[mcp_servers.dejo]`<br>`command = "dejo-mcp"` |
| Cursor | `~/.cursor/mcp.json` | `{ "mcpServers": { "dejo": { "command": "dejo-mcp" } } }` |
| anything else | as a stdio server | `dejo-mcp` |

Dejo is one stdio server with no arguments, so any agent that can run an MCP server can use it.

**No API key, no account.** Dejo never calls a model. Your agent does the thinking, and the
memory is a local file on your machine.

Check the install at any time. It names anything missing and the command that fixes it:

```bash
dejo doctor
```

## Quick start

Ask your agent for something on a website, in your own words:

> Go to github.com/microsoft/playwright and tell me how many open issues it has.

The first time, your agent learns it: Dejo opens the page and shows it, one line per control,
and your agent sends the steps back in one call (`click link "Issues"`, then `read ... as open
issues`). The read is what Dejo saves. Ask again tomorrow, in a brand-new chat, and it is one
call:

```
done: "count open issues" on github.com (profile default), 2 steps replayed in 1391 ms, no page reading.
open issues = 117
next: report the answer exactly as read and stop. Every step was checked as it ran.
```

Prefer a terminal? Everything works without an MCP client:

```bash
dejo sites                                            # what it remembers
dejo run "count open issues" --site github.com        # replay, no model involved
dejo run "count open issues" --site github.com --json # one JSON line, for cron and scripts
dejo show github.com                                  # the route, step by step
dejo forget --site github.com                         # make it forget
```

## How it works

| | what happens | cost |
|---|---|---|
| **First run** | Your agent drives the browser through Dejo. Dejo watches, and turns what happened into a route. | many calls |
| **Every run after** | Dejo replays the route itself and checks that each step landed. | **one call, zero model calls** |
| **The site changed** | Dejo stops at the one broken step and shows the page there. Your agent sends one line for that step; Dejo saves it, keeps the old ways as backups, and replays the rest in the same call. | one extra call, once |

### What a route is

Not a recording, and not notes. Each step keeps:

- **what it was for**, in plain words: `"open this month's invoice"`
- **up to nine ways to find the control**: test id, link target, label, role, placeholder,
  alt text, title, visible text, CSS. Ranked by which have actually worked.
- **a check that proves it landed**: the address changed, the file downloaded, the field holds
  what was typed, the row count is what it should be.

The checks are the difference between this and a macro recorder. A recorder clicks and hopes.
Dejo notices when a click did nothing, and says the site changed.

The nine locators are why most redesigns cost nothing: lose the CSS id, keep the label, and the
step still lands. If more than half the steps break, the site was rebuilt rather than adjusted.
Dejo throws the route away but keeps what it knows about the site (needs a login, sends a code
to your phone), so relearning is cheaper than the first visit.

### The map

A route is one path through a site. Dejo also keeps a **map**: every page it has looked at,
and the controls that were on it. It costs nothing to keep, because the page had already been
read.

```bash
dejo map github.com                    # every page it has seen
dejo map github.com --path /issues     # the controls that were on one of them
```

Ask for something new on a site Dejo has walked, and your agent is handed the pages it already
knows before it starts hunting. Each control comes back as a step target such as
`button "Sign in"`, which works in a step without looking at the page first. A page Dejo has
already walked costs no reading at all. This matters most where one site carries many tasks: an end-to-end test
suite, an admin console, a portal you work in every day.

The map says when each page was seen. It is what was there last time, not a promise about now.

Measured on the demo site in this repo (`python benchmarks/benchmark.py`):

```
                time  tool calls  page reads  model calls
Monday          1.4s           9           3            0   learning the site
Tuesday         1.7s           1           0            0   from memory
Wednesday       1.9s           1           0            0   from memory
Thursday       12.6s           3           0            0   the site changed, one step repaired
Friday          1.9s           1           0            0   from memory
```

The time is mostly Dejo waiting for the site to finish after the last click (this task ends in
a download). A task that ends by reading its answer does not pay that wait.

## Benchmark

**19 tasks on 12 lesser-known websites**, the kind a model cannot answer from memory: a
college course catalog, the Debian package directory, the RFC Editor, a museum's collection,
a Dart package registry, a small shop. Every right answer was written down before any tool
ran. Claude Sonnet 5 (medium), one fresh session per run, `@playwright/mcp@0.0.80`.

| | right answers | avg tokens | avg tool calls | avg cost | avg time |
|---|---|---|---|---|---|
| **Dejo, first run** (learns the task) | **19/19** | **251k** | **4.7** | **$0.17** | **31 s** |
| **Dejo, every run after** | **19/19** | **89k** | **1.2** | **$0.02** | **16 s** |
| Playwright MCP, every run | 17/19 | 409k | 6.5 | $0.23 | 40 s |
| Playwright CLI, every run | 18/19 | 559k | 8.4 | $0.28 | 38 s |

- **First run:** 38% fewer tokens than Playwright MCP, 55% fewer than Playwright CLI.
- **Every run after:** 78% fewer tokens than Playwright MCP, and 17 of 19 repeats were a
  single tool call. The same task run 10 times costs 74% fewer tokens.

Three things the table should also tell you, because they are true:

- **On a typical task the first run costs about the same as Playwright MCP** (median 216k vs
  257k). The first-run savings come from the hard sites: 324k against 1.36M on the college
  catalog, 398k against 983k on the museum's filters.
- **6 more tasks were on sites that block automated browsers** (Cloudflare checks, plain 403s).
  Dejo and Playwright MCP were stopped on all six; Playwright CLI got through two of them at
  1.2M and 1.7M tokens. They are in the results file, not in the table.
- **Dejo's numbers are from the release code**, after fixing what this benchmark found; the
  Playwright rows are from the same tasks and model, one day earlier.

Tasks: [`benchmarks/real_tasks.py`](benchmarks/real_tasks.py). Results:
`benchmarks/benchmark-real-2026-10-21.json` (all three tools), `-10-23.json` and
`-10-23-fixes.json` (Dejo after the fixes). Run it yourself:
`python benchmarks/benchmark_learning.py --bench real --tools dejo,playwright --runs 1`.

### Earlier: the same job ten times (Dejo 0.1.2)

The same job, done **10 times**, each time in a brand-new chat. Three multi-step tasks on
well-known sites, three MCP browser tools, **90 fresh Claude sessions** (Sonnet 5, medium):
`@playwright/mcp@0.0.80`, `chrome-devtools-mcp@1.8.0`.

| the task, done 10 times | **Dejo** | Playwright MCP | Chrome DevTools MCP |
|---|---|---|---|
| open a GitHub repo → Issues → count them | **28 calls · 1.4M tokens** | 83 · 3.4M | 33 · 1.7M |
| open an author's page → read their birth date | **27 calls · 1.3M tokens** | 60 · 2.6M | 60 · 2.6M |
| open a category → open a book → read the price | **41 calls · 1.9M tokens** | 56 · 2.8M | 56 · 2.8M |
| **all three** | **96 calls · 4.6M tokens** | 199 · 8.7M | 149 · 7.1M |

**52% fewer tool calls and 47% fewer tokens than Playwright MCP.** Against Chrome DevTools
MCP: 36% fewer calls, 35% fewer tokens. Every tool answered in all 30 of its sessions.

The GitHub task, run by run:

```
run              1   2   3   4   5   6   7   8   9  10
Dejo            10   2   2   2   2   2   2   2   2   2
Playwright MCP   8   8  18   7   9   9   7   6   5   6
```

Dejo pays once to learn the route, then costs two calls however many steps that route has.

Two things this table should also tell you, because they are true:

- **Dejo costs the most on run 1.** It does the job *and* learns the site. That is the trade.
- **On a single page with a one-line answer, Dejo is not cheaper.** Opening one page and reading
  one line costs every tool two or three calls, and there is nothing left for memory to save.

Run it yourself: `python benchmarks/benchmark_agents.py --journeys --runs 10`. These results
were recorded while Dejo was still called Cairn, so the files say `cairn` where they mean Dejo.

## Signing in

You sign in to a site once, by hand, in a real window:

```bash
dejo login --site posthog.com
```

Sign in however the site asks: a password, Google, a code on your phone. Dejo never types a
password for you and never automates an SSO button. When you say you are done, Dejo checks the
window first: if it still shows a sign-in page, it says so rather than pretending. The session
is kept, so you stay signed in.

**Passwords never go into memory.** A step that needs one records only *that* a password goes
there. The value is read at run time from an environment variable
(`DEJO_SECRET_BILLING_ACME_COM_PASSWORD`) or from `~/.dejo/secrets.json`:

```json
{ "billing.acme.com": { "password": "..." } }
```

### More than one identity at once

A profile is a whole signed-in browser: its own cookies, its own session. Keep as many as you
need, side by side:

```bash
dejo --profile vendor login --site shop.example.com
dejo --profile admin  login --site shop.example.com
```

From your agent, `dejo_profile` with `name="vendor"` switches, and without a name lists them. A suite
covering three roles never has to sign out and back in, so the order of the tests stops
mattering.

## Sharing a route

Memory is per agent. Agents on one machine can hand routes to each other:

```bash
dejo --agent alice share github.com     # alice already knows the site
dejo --agent bob borrow github.com      # bob has never opened it
dejo --agent bob run "count open issues" --site github.com   # one call
```

**What travels:** the steps, the ranked locators, the checks, the notes about the site, and the
map. **What never travels:** anything typed into a field, and which account was used. A shared
sign-in step asks the borrower for their own credentials.

When a borrower repairs a broken step, the fix can be contributed back to the original.

## Forgetting

```bash
dejo forget --site github.com
```

Dejo now has nothing to follow for that site, its map included. The next run says the memory is
gone. It does not quietly fall back to exploring. Forgetting also withdraws anything you shared
for that site, and Dejo will not quietly hand you somebody else's route for it afterwards: you
have to borrow it on purpose.

## Where your data lives

All on your machine.

| what | where |
|---|---|
| routes, site facts, maps, history | `~/.dejo/memory.db`, one SQLite file. Every decision about what is remembered is in [`engine/src/dejo/store.py`](engine/src/dejo/store.py) |
| signed-in browser profiles | `~/.dejo/browser-profile`, `~/.dejo/profiles/` |
| downloads | `~/.dejo/downloads` |
| passwords, if you choose to keep them in a file | `~/.dejo/secrets.json` |

Being signed in is not the same as remembering. Forget a site and Dejo is still signed in, and
has no idea what to click.

The memory needs no account and has no size limit. History, the one part that grows with every
run, keeps the newest 10,000 events per agent. If you would rather keep your memory in
[Sibyl Memory](https://pypi.org/project/sibyl-memory-client/), install `pip install "dejo[sibyl]"`
and set `DEJO_MEMORY=sibyl`.

## Tools

Five MCP tools. One of them, `dejo_run`, does all of the browsing, because every tool name is
read on every turn and tool choice is the most fragile part of an agent's day.

| tool | what it does |
|---|---|
| `dejo_run` | Every website task. A known task replays in one call. A new one shows the page; your agent sends the steps, one per line, in the next call, and the task is saved when a step reads the answer. |
| `dejo_login` | Opens a real window so the user signs in, then `done=true` when they have. |
| `dejo_profile` | Switch signed-in identity (customer, vendor, admin), or list them. |
| `dejo_memory` | What Dejo remembers: `sites`, one task step by step (`show`), the site `map`, and tasks other agents shared (`commons`). |
| `dejo_manage` | Change it: `forget` a site or task, `note` a fact, `share` a task, `borrow` one. |

Steps are plain lines, run in order. Dejo stops at the first one that fails and shows the page
there, so the next call only sends the rest:

```
go https://billing.acme.com/invoices
click link "September 2026"
fill label "Search" "acme"
read css ".total" as total
```

Targets are a ref from the page (`e12`), or `role "name"` (`link "Travel"`), `text "..."`,
`label "..."`, `css "..."`. Add `first`, `last` or `nth 3` to mean a place in a list rather
than one item. A step that buys, pays, sends, deletes or submits is marked with `!`
(`click! button "Pay"`); unmarked, Dejo will not do it, and marked, it never runs twice on its
own.

It handles what breaks recorded flows: shadow DOM, iframes, `div`s pretending to be buttons,
content that loads late, cookie banners, confirm dialogs, new tabs, and file pickers with no
visible input. A `js` step runs your own JavaScript when a site does something nobody
anticipated, and is deliberately never saved into a route, because a step made of code cannot
be repaired. The full capability list, with the reason for each choice, is in
[`docs/BROWSING.md`](docs/BROWSING.md).

## When something goes wrong

Start with `dejo doctor`. It checks the browser, the profile, the memory and the downloads
folder, and prints the exact fix for anything missing.

**"Dejo has no browser to drive yet."** `pip install` brings the code, not a browser. Run
`playwright install chromium`.

**"Dejo cannot open a window here: this machine has no screen."** Signing in needs a real
window, so `dejo login` cannot work over plain SSH or in a container. Sign in on a computer with
a desktop and copy `~/.dejo/browser-profile` across, or forward a display with `ssh -X`.
Normal runs are headless and unaffected.

**"Dejo could not open its browser profile."** Another Dejo run or sign-in window still has
it open, or the profile is in a state no browser accepts. Close any other run first. If that
was not it, deleting `~/.dejo/browser-profile` fixes it, at the cost of signing you out.
To run two agents at once, give each its own profile: `DEJO_PROFILE=~/.dejo/profile-b dejo-mcp`.

**"Nothing loads in Dejo's browser profile."** A page timed out, Dejo tried the same address
in a fresh browser, and it loaded there. The site is fine; that profile is stuck. Switch to a
new profile (`dejo --profile <name>`, or `dejo_profile` from your agent) and sign in there, or
close every Dejo window and delete the profile folder the message names.

**A captcha.** Dejo stops and says so. It does not mark the route broken and does not try to
solve it. Clear it yourself once, and run again.

## Coming from Cairn

Dejo was called **Cairn** until October 2026. On first start, Dejo moves an old `~/.cairn`
folder to `~/.dejo`, so every sign-in is kept, and copies the old memory across from Sibyl
Memory into `~/.dejo/memory.db`, so every learned site is kept. The Sibyl file itself is left
as it was. The old `CAIRN_*` environment variables still work, and the old
`cairn-browser-mcp` package installs Dejo.

## Development

```bash
git clone https://github.com/dejohq/dejo-mcp
cd dejo-mcp
python -m venv .venv
.venv/bin/python -m pip install -e "engine[dev]" -e "mcp[dev]"   # Windows: .venv\Scripts\python
.venv/bin/python -m playwright install chromium

cd engine && ../.venv/bin/python -m pytest
cd ../mcp && ../.venv/bin/python -m pytest
```

```
engine/      the engine (PyPI: dejo): browser, memory, replay, repair, sharing, the dejo command
mcp/         the MCP server (PyPI: dejo-mcp): five tools over the engine
benchmarks/  the benchmark scripts and their raw results
docs/        design notes
```

Opening Claude Code inside the clone needs no setup: the checked-in `.mcp.json` offers the
server straight away.

## FAQ

**Is Dejo a cache?** No. A cache replays and hopes. Every step Dejo saves carries a check that
proves it landed, so Dejo can tell a changed site from a working one and fix only the step that
moved.

**Does it call an AI model?** No. Replay is plain code with zero model calls, and there is no
API key to set. The agent you already use does the thinking, on the first run and when a step
needs fixing.

**Is it cheaper on every task?** No. The first run costs the most, because Dejo does the job and
learns the route. On a single page with a one-line answer there is nothing to remember. It pays
off on tasks with steps that you run again.

**Does it store my passwords?** No. You sign in yourself, in a real window. A step that needs a
password records only that a password goes there.

**Which agents does it work with?** Any agent that can run an MCP server: Claude Code, Codex,
Cursor, and others.

## Contributing

Bug reports, sites Dejo gets wrong, and pull requests are all welcome. Start with
[CONTRIBUTING.md](.github/CONTRIBUTING.md). Found a security problem? Please report it
privately, as [SECURITY.md](.github/SECURITY.md) explains, not in a public issue. Everyone
taking part follows the [Code of Conduct](.github/CODE_OF_CONDUCT.md).

## Prior work

- **[pig-dot-dev/muscle-mem](https://github.com/pig-dot-dev/muscle-mem)**, "a cache for AI
  agents to learn and replay complex behaviors". The closest existing idea. Dejo is not a cache:
  every step carries a check, so it can tell a changed site from a working one, repair the single
  step that moved, and hand a working route to another agent.
- **[@playwright/mcp](https://github.com/microsoft/playwright-mcp)**, whose accessibility-tree
  snapshot approach Dejo's page reading is built on.

## License

MIT. See [LICENSE](LICENSE).
