"""Every `dejo` command a README shows must be one the CLI accepts.

The READMEs once told people to run `dejo run --site github.com --task "..."`, but `run` takes
the task as a plain argument and has no `--task`, so the first command a reader copied failed.
This parses every `dejo ...` line in the READMEs' code blocks, exactly as written.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from dejo.cli import build_parser

REPO = Path(__file__).resolve().parents[2]
READMES = [REPO / "README.md", REPO / "engine" / "README.md", REPO / "mcp" / "README.md"]
FENCE = "```"


def readme_commands() -> list[tuple[str, str]]:
    found = []
    for readme in READMES:
        in_code = False
        for line in readme.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith(FENCE):
                in_code = not in_code
                continue
            command = line.split(" #", 1)[0].strip()
            if in_code and command.startswith("dejo "):
                found.append((readme.relative_to(REPO).as_posix(), command))
    return found


def test_the_readmes_show_dejo_commands() -> None:
    # guards the test below from passing because it found nothing to check
    assert len(readme_commands()) >= 5


@pytest.mark.parametrize(("readme", "command"), readme_commands())
def test_readme_command_is_accepted(readme: str, command: str) -> None:
    try:
        build_parser().parse_args(shlex.split(command)[1:])
    except SystemExit:
        pytest.fail(f"{readme} shows a command the CLI rejects: {command}")
