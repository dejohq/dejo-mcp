"""Entry point: `dejo-mcp` console script and `python -m dejo_mcp`."""

import sys

from dejo.home import OldHomeNotCopied, adopt_old_home

from .server import log, run_stdio


def main() -> None:
    try:
        if adopt_old_home():
            log("copied your old ~/.cairn folder to ~/.dejo, so every sign-in is kept")
    except OldHomeNotCopied as stuck:
        # stderr only: stdout is the MCP transport, and one stray line there breaks it.
        sys.exit(str(stuck))
    run_stdio()


if __name__ == "__main__":
    main()
