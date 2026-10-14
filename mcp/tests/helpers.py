"""Driving the MCP tools the way a host AI would."""

from __future__ import annotations

import asyncio
import json
from typing import Any


def call(server, tool: str, **arguments: Any) -> dict[str, Any]:
    """Invoke one MCP tool and return its structured result.

    This is exactly what a host AI does, minus the transport.
    """
    result = asyncio.run(server.call_tool(tool, arguments))

    if isinstance(result, dict):
        return result

    # FastMCP hands back (content_blocks, structured_result). Prefer the structured half,
    # which is exactly what a host AI receives as the tool's output.
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return result[1]

    for block in result:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError(f"{tool} returned nothing usable: {result!r}")


def ref_named(page: dict[str, Any], name: str) -> str:
    for element in page["elements"]:
        if element["name"] == name:
            return element["ref"]
    seen = [e["name"] for e in page["elements"]]
    raise AssertionError(f"no control named {name!r}. saw: {seen}")


def teach_the_site(server, base_url: str) -> dict[str, Any]:
    """The cold path, driven through MCP tools exactly as a host AI would drive it."""
    call(server, "dejo_act", intent="open the billing portal", action="goto", value=f"{base_url}/")

    page = call(server, "dejo_read", kind="page")
    call(
        server,
        "dejo_act",
        intent="type the account email",
        action="fill",
        ref=ref_named(page, "Email"),
        value="finance@acme.com",
    )
    call(
        server,
        "dejo_act",
        intent="type the password",
        action="fill",
        ref=ref_named(page, "Password"),
        value="hunter2",
    )
    call(server, "dejo_act", intent="sign in", action="click", ref=ref_named(page, "Sign in"))

    page = call(server, "dejo_read", kind="page")
    call(
        server,
        "dejo_act",
        intent="open this month's invoice",
        action="click",
        ref=ref_named(page, "September 2026"),
    )

    page = call(server, "dejo_read", kind="page")
    call(
        server,
        "dejo_act",
        intent="download the PDF",
        action="click",
        ref=ref_named(page, "Download"),
    )

    return call(server, "dejo_save", task="download this month's invoice")
