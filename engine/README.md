# Dejo

**A browser your AI agent remembers.** This is the engine.

Your agent walks a website once: signing in, clicking, reading. Dejo writes down the route.
Every run after that follows the route instead: one call, no page reading, zero model calls.
When the site changes, Dejo repairs the one step that moved and keeps the rest.

```bash
pip install dejo
playwright install chromium        # the browser, a separate download

dejo run "count open issues" --site github.com
dejo show github.com               # the route, step by step
dejo forget --site github.com      # make it forget
```

Most people want Dejo wired into their agent instead. That is
[`dejo-mcp`](https://pypi.org/project/dejo-mcp/): Dejo as MCP tools for Claude Code, Codex,
Cursor and any MCP client.

No API key and no account. Dejo never calls a model, and the memory is a local file.

Documentation: **https://github.com/dejohq/dejo-mcp** · Website: **https://dejo.run** · MIT licensed.
