# Changelog

Every release of `dejo` and `dejo-mcp`. The two are released together with the same version.

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
