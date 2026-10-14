"""Entry point: `dejo-mcp` console script and `python -m dejo_mcp`."""

import sys

from dejo.home import OldHomeNotMoved, adopt_old_home
from dejo.store import OldMemoryUnreadable, adopt_old_memory

from .server import log, run_stdio


def main() -> None:
    try:
        if adopt_old_home():
            log("moved your old ~/.cairn folder to ~/.dejo, so every sign-in is kept")
    except OldHomeNotMoved as stuck:
        # stderr only: stdout is the MCP transport, and one stray line there breaks it.
        sys.exit(str(stuck))
    try:
        if adopt_old_memory():
            log("brought your memory across from Sibyl, so every learned site is kept")
    except OldMemoryUnreadable as unreadable:
        log(str(unreadable))
    run_stdio()


if __name__ == "__main__":
    main()
