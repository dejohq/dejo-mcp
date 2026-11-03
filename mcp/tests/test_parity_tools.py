"""What the MCP server adds for the parity steps: things a plain text reply cannot carry."""

from __future__ import annotations

import base64

from helpers import result

PNG = b"\x89PNG"


def test_look_image_sends_a_picture_of_the_screen(mcp_server, demo_server) -> None:
    """A chart or a map has nothing inside it to name. The agent sees it as a picture, and
    clicks a spot it can see with `mouse click X Y`."""
    replied = result(
        mcp_server,
        "dejo_run",
        site=demo_server,
        task="see the chart",
        url=f"{demo_server}/parity",
        steps="look image",
    )
    kinds = [block.type for block in replied.content]
    assert kinds == ["text", "image"]
    assert "mouse click X Y" in replied.content[0].text
    picture = replied.content[1]
    assert picture.mimeType == "image/png"
    assert base64.b64decode(picture.data).startswith(PNG)
