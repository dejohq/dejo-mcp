"""Driving the MCP tools the way a host AI would."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from mcp import types

TASK = "download this month's invoice"


def result(server, tool: str, **arguments: Any) -> types.CallToolResult:
    """One tool call, through the same request path a client uses."""
    return asyncio.run(server.call_tool(tool, arguments))


def call(server, tool: str, **arguments: Any) -> str:
    """One tool call; the plain-text reply the agent reads."""
    replied = result(server, tool, **arguments)
    return "".join(block.text for block in replied.content if hasattr(block, "text"))


def ref_named(view: str, name: str) -> str:
    """The ref the view printed for an element with this exact name."""
    found = re.search(rf'((?:f\d+)?e\d+) \w+ "{re.escape(name)}"', view)
    if found is None:
        raise AssertionError(f"no element named {name!r} in the view:\n{view}")
    return found.group(1)


def teach_the_site(server, base_url: str) -> str:
    """The learning run, the way a host AI does it now: one look, then one call of steps."""
    call(server, "dejo_run", site=base_url, task=TASK, url=f"{base_url}/")
    return call(
        server,
        "dejo_run",
        site=base_url,
        task=TASK,
        steps=(
            'fill label "Email" "finance@acme.com"\n'
            'fill label "Password" "hunter2"\n'
            'click button "Sign in"\n'
            'click link "September 2026"\n'
            'click link "Download"\n'
        ),
    )
