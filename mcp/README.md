# Dejo MCP

**A browser your AI agent remembers.**

Dejo gives Claude Code, Codex, Cursor or any MCP client a browser with a memory. Your agent
walks a site once and Dejo writes down the route. Every run after that is one tool call, no
page reading, and zero model calls. When the site changes, Dejo hands back only the step that
moved.

```bash
pip install dejo-mcp
playwright install chromium        # the browser, a separate download

claude mcp add --scope user dejo -- dejo-mcp    # Claude Code, every project
```

Codex: add `[mcp_servers.dejo]` with `command = "dejo-mcp"` to `~/.codex/config.toml`.
Cursor: add `"dejo": { "command": "dejo-mcp" }` under `mcpServers` in `~/.cursor/mcp.json`.

Then ask in your own words: *"go to github.com/microsoft/playwright and tell me how many open
issues it has."* The first time it explores. After that it is one call.

No API key and no account. Your agent does the thinking; Dejo supplies the browser and the
memory, on your machine.

<!-- mcp-name: io.github.dejohq/dejo-mcp -->

Documentation: **https://github.com/dejohq/dejo-mcp** · Website: **https://dejo.run** · MIT licensed.
