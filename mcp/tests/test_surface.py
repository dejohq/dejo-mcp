"""The tool surface itself: what every client reads before the first turn, and on every turn.

Measured on 20 Oct 2026: sixteen tools were 29,024 characters of definitions, and turns
decided the bill. Five tools, one of them loaded up front, is the shape that lets a learning
run take three turns. These tests pin that shape, so it cannot drift back by accident.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from dejo import actions, reads

from helpers import call, result

GOLDEN = Path(__file__).parent / "fixtures" / "tools.json"

# What Claude Code reads for an upfront tool before cutting it (code.claude.com/docs/en/mcp.md).
UPFRONT_LIMIT = 4096
# Codex reads only this much of a server's instructions.
INSTRUCTIONS_LIMIT = 512
# All five tools, as JSON. The old surface was 29,024 characters.
SURFACE_LIMIT = 4500


@pytest.fixture
def tools(mcp_server) -> list:
    return asyncio.run(mcp_server.list_tools())


def dumped(tools) -> list[dict]:
    return [tool.model_dump(by_alias=True, exclude_none=True) for tool in tools]


# ------------------------------------------------------------------- the shape


def test_the_tool_list_is_exactly_what_was_agreed(tools) -> None:
    """Byte for byte. A change here changes what every agent reads, so it must be a
    deliberate one: rewrite the golden file and read the diff."""
    assert dumped(tools) == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_only_dejo_run_loads_up_front(tools) -> None:
    upfront = [t.name for t in tools if (t.meta or {}).get("anthropic/alwaysLoad")]
    assert upfront == ["dejo_run"]


def test_dejo_run_fits_what_claude_code_reads_up_front(tools) -> None:
    run = next(t for t in tools if t.name == "dejo_run")
    assert len(run.description or "") <= UPFRONT_LIMIT


def test_the_instructions_fit_what_codex_reads(mcp_server) -> None:
    assert len(mcp_server.instructions) <= INSTRUCTIONS_LIMIT


def test_the_whole_surface_stays_small(tools) -> None:
    assert len(json.dumps(dumped(tools))) <= SURFACE_LIMIT


def test_no_tool_declares_structured_output(tools) -> None:
    """Codex sends only structured content to the model when it is set, and drops the
    text. Every reply here is text, so no tool may declare an output schema."""
    assert all(tool.outputSchema is None for tool in tools)


def test_reading_and_changing_memory_are_marked(tools) -> None:
    marked = {t.name: t.annotations for t in tools if t.annotations}
    assert marked["dejo_memory"].readOnlyHint is True
    assert marked["dejo_manage"].destructiveHint is True


def test_the_old_tools_are_gone(tools) -> None:
    names = {t.name for t in tools}
    for gone in ("dejo_act", "dejo_read", "dejo_save", "dejo_repair", "dejo_login_done"):
        assert gone not in names


# ------------------------------------------------------------------- the language


@pytest.fixture
def on_the_page(mcp_server, demo_server) -> str:
    """The demo site's sign-in page, opened as a new task."""
    return call(mcp_server, "dejo_run", site=demo_server, task="try things", url=f"{demo_server}/")


def steps(mcp_server, demo_server, lines: str) -> str:
    return call(mcp_server, "dejo_run", site=demo_server, task="try things", steps=lines)


def test_every_action_can_be_written_as_a_step() -> None:
    """The registry is the one list of what Dejo can do. An action the language cannot
    write is an action no agent can use."""
    from dejo import program

    verbs = program.verbs_help()
    spoken = set(program.ALIASES.values()) | program.DESCRIBED | program.ALONE
    for name in actions.ACTIONS:
        assert name in verbs or name in spoken, f"{name} has no verb"


def test_every_read_can_be_written_as_a_step() -> None:
    from dejo import program

    for name in reads.READS:
        program.parse(
            f"read {name}{' href' if reads.READS[name].needs_attribute else ''}"
            f"{' e1' if reads.READS[name].needs_target else ''} as x"
        )


def test_fill_click_and_read_reach_the_engine(mcp_server, demo_server, on_the_page) -> None:
    said = steps(
        mcp_server,
        demo_server,
        'fill label "Email" "finance@acme.com"\nread value label "Email" as email',
    )
    assert "email = finance@acme.com" in said


def test_wait_and_tabs_reach_the_engine(mcp_server, demo_server, on_the_page) -> None:
    said = steps(mcp_server, demo_server, "wait idle\ntab new\ntab main\nlook")
    assert not said.startswith("stopped"), said


def test_read_the_url_and_count(mcp_server, demo_server, on_the_page) -> None:
    said = steps(mcp_server, demo_server, 'read url as here\nread count css "input" as fields')
    assert f"here = {demo_server}/" in said
    assert "fields = 2" in said


def test_a_value_missing_from_a_step_says_what_is_needed(mcp_server, demo_server) -> None:
    said = result(mcp_server, "dejo_run", site=demo_server, task="x", steps='fill label "Email"')
    assert said.isError
    assert "fill needs the text to put in" in said.content[0].text


def test_a_target_that_is_not_there_says_so(mcp_server, demo_server, on_the_page) -> None:
    said = steps(mcp_server, demo_server, 'click button "Teleport"')
    assert said.startswith('stopped at line 1 of 1: click button "Teleport" -> nothing')


def test_a_password_box_never_shows_what_is_in_it(mcp_server, demo_server, on_the_page) -> None:
    """Playwright's own snapshot prints field contents in plain text, passwords included.
    Nothing that leaves this server may carry one."""
    said = steps(mcp_server, demo_server, 'fill label "Password" "hunter2"\nlook')
    assert "hunter2" not in said


def test_dejo_run_takes_a_task(tools) -> None:
    """One site, many tasks. Keying on the site alone meant github.com could hold one."""
    run = next(t for t in tools if t.name == "dejo_run")
    assert "task" in run.inputSchema["required"]


class TestABrowserSwapIsSaidOutLoud:
    """Dejo may open its profile with the other browser when the owner refuses it. The
    engine records the swap and cannot print; something has to say it, once."""

    @staticmethod
    def _swapped(mcp_server, note="Chrome would not open Dejo's browser profile"):
        tools = mcp_server.dejo_tools
        tools.worker.browser = type("FakeBrowser", (), {"profile_note": note})()
        return tools

    def test_the_note_is_handed_over(self, mcp_server) -> None:
        assert "Chrome would not open" in (self._swapped(mcp_server).take_profile_note() or "")

    def test_and_only_once(self, mcp_server) -> None:
        tools = self._swapped(mcp_server)
        tools.take_profile_note()
        assert tools.take_profile_note() is None

    def test_a_normal_open_says_nothing(self, mcp_server) -> None:
        assert self._swapped(mcp_server, note=None).take_profile_note() is None
