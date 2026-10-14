# Contributing to Dejo

Thank you for helping. Dejo is a browser your AI agent remembers, and it gets better every time
someone shows it a website it gets wrong.

## The most useful thing you can send

**A site Dejo gets wrong.** Use the ["A site Dejo gets wrong"](https://github.com/dejohq/dejo-mcp/issues/new?template=2_site_gets_wrong.yml)
form. Tell us the page, what you asked for, and what happened. Real websites are where every
part of Dejo was hardened, and a page we can open beats a long description.

Please never paste a password, a session cookie or anything typed into a private form. Dejo
never stores those, and an issue should not either.

## Set up

You need Python 3.11 or newer.

```bash
git clone https://github.com/dejohq/dejo-mcp
cd dejo-mcp
python -m venv .venv

# macOS / Linux
.venv/bin/python -m pip install -e "engine[dev]" -e "mcp[dev]"
.venv/bin/python -m playwright install chromium

# Windows
.venv\Scripts\python -m pip install -e "engine[dev]" -e "mcp[dev]"
.venv\Scripts\python -m playwright install chromium
```

Opening Claude Code inside the clone needs no setup: the checked-in `.mcp.json` starts this
copy of the server.

## Run the tests

```bash
cd engine && ../.venv/bin/python -m pytest
cd ../mcp && ../.venv/bin/python -m pytest
```

The engine suite drives a real browser against a small demo site in `engine/tests/demo_site/`,
so it takes about ten minutes. While you work, run one file:

```bash
cd engine && ../.venv/bin/python -m pytest tests/test_store.py
```

Tests never touch your real memory, browser profiles or home folder. Every test gets its own
temporary folders. If you add code that reads or writes under `~/.dejo`, keep it that way.

## Lint

```bash
.venv/bin/python -m ruff check engine/src engine/tests mcp/src mcp/tests benchmarks
.venv/bin/python -m ruff format engine/src engine/tests mcp/src mcp/tests benchmarks
```

CI runs the same two commands, plus both test suites on Linux, macOS and Windows.

## How the code is laid out

```
engine/src/dejo/     the engine, published as `dejo`
  browser.py         Playwright, wrapped. Nothing else touches it directly
  operations.py      what an agent does while learning a site: act, read, save
  executor.py        replay: follow a saved route, check every step, ask for a repair
  store.py           every decision about memory
  memory.py          the SQLite database underneath; the only file that speaks SQL
  actions.py         the 35 actions, as a registry
  reads.py           the 14 kinds of read, as a registry
  cli.py             the `dejo` command
mcp/src/dejo_mcp/    the MCP server, published as `dejo-mcp`: thin tools over the engine
benchmarks/          the benchmark scripts and their raw results
docs/BROWSING.md     what Dejo can and cannot do in a browser, and why
```

## The rules the code keeps

These are what make Dejo work. A pull request that breaks one will be asked to change.

1. **Replay makes zero model calls.** Following a saved route is plain Python. Nothing on that
   path calls a model or reaches the network on its own behalf.
2. **Every step proves it landed.** A step without a check is not saved.
3. **`dejo forget` really forgets.** After it, replay has nothing to follow and says so.
   `engine/tests/test_deletion_gate.py` is the proof.
4. **Memory has one front door.** Only `store.py` uses the database, and only `memory.py`
   speaks SQL. Tests check both.
5. **Two browsing tools, not thirty-five.** `dejo_act` and `dejo_read` carry every action and
   read. Their descriptions are generated from `actions.py` and `reads.py`, so a new action
   is added to the registry, never as a new tool.
6. **Errors say what to do next.** A person, or an agent, should never have to read a stack
   trace to know how to fix a problem.
7. **The MCP server never prints to stdout.** Stdout is the MCP connection; one stray line
   breaks it. Log to stderr.

## Code style

- Type hints everywhere. Small functions with one job.
- Named constants at the top of the file, with a comment that says why that value.
- Comments explain *why*, especially the bug or the real website that made the code look the
  way it does.
- No bare `except:`. A deliberate `except Exception` needs `# noqa: BLE001` and the reason.
- A bug fix comes with a test that fails without it.

## Sending a pull request

1. Open an issue first for anything bigger than a small fix, so we can agree on the shape.
2. Keep one change per pull request.
3. Run both test suites and the lint before you push.
4. Fill in the pull request template. If an AI tool wrote part of the change, say which and
   what you checked yourself. That is welcome; we only ask that you understand every line.

By contributing, you agree that your work is released under the [MIT license](../LICENSE).

## Questions

Open an issue, or see [dejo.run](https://dejo.run). Everyone taking part follows the
[Code of Conduct](CODE_OF_CONDUCT.md).
