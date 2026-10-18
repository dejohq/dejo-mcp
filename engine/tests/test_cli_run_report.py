"""What `dejo run` tells a person, and what it tells a script.

A run used to read the answer ("how many open issues") and never print it, so a terminal run
ended with nothing to show for itself. And a scheduled run had no way to hand its result to
whatever started it. These tests pin both: the answer is printed, and `--json` is one line a
script can parse, with an exit code that never drifts from the outcome.
"""

from __future__ import annotations

import json

import pytest

from dejo.cli import EXIT_CODES, build_parser, outcome_of, run_report
from dejo.executor import RepairRequest, ReplayResult
from dejo.models import RunMetrics

SITE = "github.com"


def a_result(**kwargs) -> ReplayResult:
    metrics = RunMetrics(domain=SITE, task="count open issues", mode="warm", duration_ms=1530)
    return ReplayResult(metrics=metrics, **kwargs)


class TestTheOutcome:
    def test_a_finished_run_is_done(self) -> None:
        assert outcome_of(a_result(ok=True)) == "done"

    def test_a_run_that_stopped_for_nothing_in_particular_failed(self) -> None:
        assert outcome_of(a_result(ok=False)) == "failed"

    @pytest.mark.parametrize(
        ("flag", "outcome"),
        [
            ("already_done", "already_done"),
            ("wrong_place", "wrong_place"),
            ("blocked", "blocked"),
            ("needs_login", "needs_login"),
            ("stale", "stale"),
        ],
    )
    def test_each_kind_of_stop_is_named(self, flag: str, outcome: str) -> None:
        assert outcome_of(a_result(ok=False, **{flag: True})) == outcome

    def test_a_broken_step_with_a_repair_request_needs_repair(self) -> None:
        repair = RepairRequest(
            domain=SITE, step_index=2, intent="read the count", action="read", tried=[]
        )
        assert outcome_of(a_result(ok=False, repair=repair)) == "needs_repair"

    def test_every_outcome_has_an_exit_code(self) -> None:
        outcomes = {"done", "failed", "already_done", "wrong_place", "blocked"}
        outcomes |= {"needs_login", "stale", "needs_repair", "no_trail"}
        assert outcomes == set(EXIT_CODES)

    def test_only_success_exits_zero(self) -> None:
        assert {name for name, code in EXIT_CODES.items() if code == 0} == {"done", "already_done"}


class TestTheJsonLine:
    def test_it_carries_the_answer_and_survives_a_round_trip(self) -> None:
        line = json.dumps(run_report(SITE, a_result(ok=True, answers={"open issues": "155"})))
        back = json.loads(line)
        assert back["outcome"] == "done"
        assert back["ok"] is True
        assert back["answers"] == {"open issues": "155"}
        assert back["site"] == SITE
        assert back["task"] == "count open issues"
        assert back["model_calls"] == 0

    def test_a_stop_says_why(self) -> None:
        report = run_report(
            SITE, a_result(ok=False, needs_login=True, reason="the session ran out")
        )
        assert report["ok"] is False
        assert report["outcome"] == "needs_login"
        assert report["reason"] == "the session ran out"


def test_run_takes_json() -> None:
    args = build_parser().parse_args(["run", "count open issues", "--site", SITE, "--json"])
    assert args.json is True


def test_the_answer_is_printed(monkeypatch, capsys) -> None:
    """The human report ends with the answer, not just "done in 1530ms"."""
    import dejo.cli as cli

    class NoBrowser:
        def __init__(self, **_kwargs) -> None: ...
        def start(self) -> None: ...
        def stop(self) -> None: ...

    class Replays:
        def __init__(self, *_args, **_kwargs) -> None: ...
        def run(self, *_args, **_kwargs) -> ReplayResult:
            return a_result(ok=True, answers={"the open issue count": "155"})

    monkeypatch.setattr(cli, "Browser", NoBrowser)
    monkeypatch.setattr(cli, "Executor", Replays)
    args = build_parser().parse_args(["run", "count open issues", "--site", SITE])
    assert cli.cmd_run(args) == 0
    assert "the open issue count:  155" in capsys.readouterr().out
