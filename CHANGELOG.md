# Changelog

Every release of `dejo` and `dejo-mcp`. The two are released together with the same version.

## Unreleased

- **`dejo run` prints the answer.** A run read the value it was saved for (the open issue
  count, the invoice total) and never showed it, so a terminal run ended with no result.
- **`dejo run --json`** prints one line of JSON (outcome, answers, saved files, time) for cron
  jobs and scripts. Exit codes: 0 done, 1 failed or needs a repair, 2 no trail or the site was
  rebuilt, 3 needs a sign-in, 4 blocked by a captcha, 5 not on the trail's starting page.
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
