#!/usr/bin/env python3
"""Start Dejo's MCP server using this repo's virtualenv, on any operating system.

`.mcp.json` is read by Claude Code the moment somebody opens this repo, before anyone has
activated anything. It used to name `.venv/Scripts/dejo-mcp.exe` directly, which is a
Windows path — so anyone on a Mac or Linux got a broken server before reading a word of
the README. JSON cannot choose a path based on the operating system; this file can.

If your system has no plain `python` on PATH (some macOS setups only have `python3`), skip
this and wire the server up explicitly instead — the README's Install section shows the
command for both layouts.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Windows puts the interpreter in Scripts\, everything else in bin/.
CANDIDATES = (
    HERE / ".venv" / "Scripts" / "python.exe",
    HERE / ".venv" / "bin" / "python",
)


def main() -> int:
    for interpreter in CANDIDATES:
        if interpreter.is_file():
            # A child process that inherits this one's stdin, stdout and stderr, rather
            # than `os.execv`. Windows has no real exec: Python emulates it by starting a
            # NEW process and killing this one, so the process id changes underneath the
            # caller. Claude Code holds the pipes and waits on the process it started, sees
            # that process exit, and times out after 30 seconds — which is exactly what it
            # did. Waiting on a child keeps one stable process id and passes the transport
            # straight through.
            return subprocess.call([str(interpreter), "-m", "dejo_mcp"])

    looked = "\n  ".join(str(path) for path in CANDIDATES)
    sys.exit(
        "Dejo could not find this repository's virtualenv. Looked for:\n  "
        f"{looked}\n\nFollow the Install section of the README first — it creates .venv "
        "and installs Dejo into it."
    )


if __name__ == "__main__":
    raise SystemExit(main())
