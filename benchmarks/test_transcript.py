"""The turn-by-turn reader must reproduce a run that was already measured.

The fixture is the real 20 Oct Dejo learning run on github.com/microsoft/playwright, taken
from its Claude Code session file with local paths left out and one signed-in username
replaced by a placeholder of the same length. `benchmark_agents.py` recorded that run as
267,454 tokens.
"""

from __future__ import annotations

import json
from pathlib import Path

from transcript import parse

FIXTURE = Path(__file__).parent / "fixtures" / "learning-github-2026-10-20.jsonl"
MEASURED_TOKENS = 267_454
MEASURED_TURNS = 8


def _fixture() -> list[str]:
    return FIXTURE.read_text(encoding="utf-8").splitlines()


def test_the_measured_run_is_reproduced() -> None:
    run = parse(_fixture())
    assert len(run.turns) == MEASURED_TURNS
    assert run.tokens == MEASURED_TOKENS


def test_every_tool_call_is_found_in_order() -> None:
    run = parse(_fixture())
    assert run.called("mcp__dejo__") == [
        "ToolSearch",
        "dejo_run",
        "ToolSearch",
        "dejo_act",
        "dejo_read",
        "dejo_read",
        "dejo_save",
    ]


def test_the_page_read_is_the_big_result() -> None:
    """The one page read was 6,007 characters; every other result was under 600."""
    run = parse(_fixture())
    sizes = {call.result_chars for call in run.calls if call.name == "mcp__dejo__dejo_read"}
    assert 6007 in sizes
    assert max(c.result_chars for c in run.calls if c.name != "mcp__dejo__dejo_read") < 600


def test_a_repeated_message_is_one_turn_and_the_result_event_is_read() -> None:
    """The live stream prints one line per content block, all with the same message id."""
    usage = {"input_tokens": 5, "cache_read_input_tokens": 100, "output_tokens": 7}
    lines = [
        "not json, a log line",
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "m1",
                    "usage": usage,
                    "content": [{"type": "text", "text": "looking"}],
                },
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "m1",
                    "usage": usage,
                    "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}],
                },
            }
        ),
        json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t1",
                            "content": [{"type": "text", "text": "abc"}],
                        }
                    ]
                },
            }
        ),
        json.dumps(
            {
                "type": "result",
                "result": "42",
                "is_error": False,
                "total_cost_usd": 0.01,
                "usage": usage,
            }
        ),
    ]
    run = parse(lines)
    assert len(run.turns) == 1
    assert run.tokens == 112
    assert run.reported_tokens == 112
    assert run.answer == "42"
    assert run.calls[0].result_chars == 3
