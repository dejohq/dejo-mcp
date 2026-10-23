"""Read one Claude Code session, turn by turn, from its own event stream.

`benchmark_agents.py` reports a session as one total. That total hid where a learning run's
tokens went: on 20 Oct a Dejo learning run on GitHub took 267k tokens, and only splitting it
by turn showed why. Every turn re-reads the whole context (about 28k tokens before any tool
says a word), so eight turns cost far more than one big page read. This module keeps that
split, so every learning run reports its turns, not just its total.

It reads both shapes Claude Code writes, because they carry the same events:
`claude -p --output-format stream-json --verbose` on stdout, and the session `.jsonl` files
under `~/.claude/projects`. The fixture in `fixtures/` is one of the latter.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

# The usage fields one turn is billed on. A cached token is still a token the model reads,
# so the cache columns count, exactly as `Run.tokens` counts them in benchmark_agents.py.
CONTEXT_FIELDS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
OUTPUT_FIELD = "output_tokens"


@dataclass
class Turn:
    """One model response. The stream repeats a message once per content block, so a turn
    is keyed by the message id, not by the line."""

    message_id: str
    context: int
    output: int

    @property
    def tokens(self) -> int:
        return self.context + self.output


@dataclass
class ToolCall:
    """One tool the model called, and how much text each side of it carried."""

    tool_use_id: str
    name: str
    input_chars: int
    result_chars: int = 0
    is_error: bool = False


@dataclass
class Transcript:
    turns: list[Turn] = field(default_factory=list)
    calls: list[ToolCall] = field(default_factory=list)
    answer: str = ""
    is_error: bool = False
    reported_tokens: int | None = None
    """The total from the stream's closing `result` event, when there is one. It is kept
    beside the per-turn sum so a run where the two disagree is visible, not averaged away."""
    cost_usd: float = 0.0

    @property
    def tokens(self) -> int:
        """The session's total. The closing `result` event is the authority when there is
        one: in the live stream a message's output count is lower than its final count (698
        tokens short over a 9-turn pilot on 20 Oct), while the session file and the result
        event agree to the token. Without a result event, the per-turn sum is exact."""
        if self.reported_tokens is not None:
            return self.reported_tokens
        return sum(turn.tokens for turn in self.turns)

    def called(self, prefix: str = "") -> list[str]:
        """Tool names in order, with an MCP prefix such as `mcp__dejo__` taken off."""
        return [call.name.removeprefix(prefix) for call in self.calls]


def _text_of(content: Any) -> str:
    """A tool result is either a string or a list of blocks; only text reaches the model as
    text. A ToolSearch result is a list of tool references with no text at all."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _usage_total(usage: dict[str, Any]) -> int:
    return sum(int(usage.get(name) or 0) for name in (*CONTEXT_FIELDS, OUTPUT_FIELD))


def parse(lines: Iterable[str]) -> Transcript:
    """Build a transcript from raw event lines. Lines that are not JSON events are skipped:
    `--verbose` mixes in plain log lines."""
    found = Transcript()
    turns: dict[str, Turn] = {}
    calls: dict[str, ToolCall] = {}

    for raw in lines:
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        message = event.get("message") or {}

        if kind == "assistant":
            usage = message.get("usage") or {}
            turn_id = str(message.get("id", len(turns)))
            # Later lines of the same message carry the same or a more complete usage, so
            # the last one seen wins.
            turns[turn_id] = Turn(
                message_id=turn_id,
                context=sum(int(usage.get(name) or 0) for name in CONTEXT_FIELDS),
                output=int(usage.get(OUTPUT_FIELD) or 0),
            )
            for block in message.get("content") or []:
                if block.get("type") == "tool_use" and block["id"] not in calls:
                    calls[block["id"]] = ToolCall(
                        tool_use_id=block["id"],
                        name=str(block.get("name", "?")),
                        input_chars=len(json.dumps(block.get("input") or {})),
                    )

        elif kind == "user" and isinstance(message.get("content"), list):
            for block in message["content"]:
                if block.get("type") != "tool_result":
                    continue
                call = calls.get(block.get("tool_use_id", ""))
                if call is not None:
                    call.result_chars = len(_text_of(block.get("content")))
                    call.is_error = bool(block.get("is_error"))

        elif kind == "result":
            found.answer = str(event.get("result") or "")
            found.is_error = bool(event.get("is_error"))
            found.cost_usd = float(event.get("total_cost_usd") or 0.0)
            if event.get("usage"):
                found.reported_tokens = _usage_total(event["usage"])

    found.turns = list(turns.values())
    found.calls = list(calls.values())
    return found
