# CLAUDE.md — dejo-mcp

Dejo is a browser your AI agent remembers. It learns a website once, replays it with zero
model calls, and re-learns only the step that moved. This repo is the open-source product:
the engine (`engine/`, PyPI `dejo`) and the MCP server (`mcp/`, PyPI `dejo-mcp`).

## The rules that ARE the architecture

1. **Dejo is a tool, not an agent.** The user's own agent (Claude Code, Codex, Cursor) does the
   thinking. Dejo supplies the browser and the memory. No model SDK is a required dependency,
   and Dejo must run fully with no API key.
2. **Replay makes zero model calls.** Replay and its checks are plain deterministic Python.
   Nothing on the replay path may reach the network on its own behalf. A test walks the source
   to enforce it.
3. **Every memory read and write lives in `engine/src/dejo/store.py`.** No other file imports
   the memory client. A test walks the source to enforce it.
4. **Every step has a postcondition.** A step that cannot check it landed is not saved. That
   check is what separates Dejo from a cache.
5. **`forget` must always really forget.** After `dejo forget`, replay has nothing to follow and
   says so. `engine/tests/test_deletion_gate.py` is the proof; keep it green.
6. **Events out, never prints.** Library code emits typed events from `events.py`; the CLI
   renders them. The MCP server never prints to stdout, because stdout is the MCP transport.
7. **One MCP server for every agent.** Supporting another agent costs install docs, never a
   separate build.
8. **Two browsing tools, never one per action.** `dejo_act` and `dejo_read` carry every action
   and read, and their descriptions are generated from `actions.ACTIONS` and `reads.READS`.
   Tool choice is the most fragile part of an agent's day; more tool names make it worse.
9. **`mcp/` is a thin wrapper.** It imports the engine only. If a tool needs real logic, that
   logic belongs in the engine.
10. **Everything Dejo writes on a user's machine lives under `~/.dejo`**, named in
    `engine/src/dejo/home.py`. Settings are read through `home.setting()`.

## Clean code

- Python 3.11+. Type hints everywhere. `ruff check` and `ruff format --check` clean.
- Small functions, one job each. No magic numbers: named constants at the top of the file,
  with a comment saying why that value.
- No bare `except:`. A blind `except Exception` needs `# noqa: BLE001` and the reason.
- Errors a person sees say what happened and what to do next, never a stack trace.
- No dead code, no commented-out blocks, no TODO left behind.
- Comments explain WHY, especially the bug or decision that made the code look this way.

## Tests

```bash
cd engine && ../.venv/Scripts/python -m pytest      # macOS / Linux: ../.venv/bin/python
cd mcp    && ../.venv/Scripts/python -m pytest
```

Tests never touch the developer's real memory, browser profiles or home folder: every store,
server and browser in a test gets its own temporary path.

## Definition of done

Code written, ruff clean, both test suites green, README updated if behaviour changed.
