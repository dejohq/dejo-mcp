"""The reliability benchmark's rules, checked without a browser or a network.

The lint job runs `pytest benchmarks` with nothing but pytest installed, so everything here
except the one parse check works without Dejo itself.
"""

from __future__ import annotations

import re

import pytest
import reliability
from real_tasks import REAL
from reliability import (
    ANSWER_CHANGED,
    BLOCKED,
    NOT_FOUND,
    NOT_READY,
    OTHER,
    WRONG_ELEMENT,
    Result,
    answer_matches,
    cause_of,
    cause_of_wrong_answer,
    summary,
)
from reliability_tasks import TASKS

# Verbs that change something on a site. The benchmark only reads, searches and clicks
# links, tabs and filters, so none of these may appear, and neither may a line marked `!`.
CHANGING_VERBS = ("upload", "drag", "dispatch_event", "js", "evaluate", "set_time")
WORDS_THAT_SEND = re.compile(r"\b(sign in|log ?in|register|subscribe|add to cart|buy|vote)\b", re.I)


def test_there_are_fifty_tasks_and_then_the_parity_tasks_with_unique_ids() -> None:
    """R01-R50 are the score compared week on week; R51 on are what other tools can do."""
    ids = [task.id for task in TASKS]
    assert len(ids) == len(set(ids)) == 61
    assert ids == sorted(ids)


def test_the_first_twenty_five_are_the_real_tasks_with_their_checked_answers() -> None:
    for task, (_, _, _, _, answers) in zip(TASKS[:25], REAL, strict=True):
        assert set(answers) & set(task.answers), task.id


def test_every_task_starts_somewhere_and_ends_in_a_named_read() -> None:
    for task in TASKS:
        lines = task.steps.strip().splitlines()
        assert lines[0].startswith("go https://") or lines[0].startswith("go http://"), task.id
        assert re.match(r"^read .* as answer$", lines[-1]), task.id
        assert task.answers, task.id


def test_no_task_sends_buys_posts_or_signs_in() -> None:
    for task in TASKS:
        for line in task.steps.splitlines():
            verb = line.split(" ", 1)[0]
            assert not verb.endswith("!"), f"{task.id}: {line}"
            assert verb not in CHANGING_VERBS, f"{task.id}: {line}"
            if verb in ("click", "press"):
                assert not WORDS_THAT_SEND.search(line), f"{task.id}: {line}"


def test_every_program_is_one_dejo_accepts() -> None:
    program = pytest.importorskip("dejo.program")
    for task in TASKS:
        program.parse(task.steps)


@pytest.mark.parametrize(
    ("said", "accepted", "matches"),
    [
        ("BCP 246: Operational Recommendations", ("BCP 246",), True),
        ("Package: moon-buggy (1:1.0.51-13)", ("1:1.0.51-13",), True),
        ("1880–1890", ("1880-1890",), True),
        ("MARILYN MONROE", ("Marilyn Monroe",), True),
        ("Dominic Orchard", ("Alberto Perez",), False),
        ("", ("x",), False),
        ("12/15/2026", (r"re:^\d\d/15/\d{4}$",), True),
        ("12/16/2026", (r"re:^\d\d/15/\d{4}$",), False),
    ],
)
def test_answers_are_compared_without_case_dashes_or_spacing(
    said: str, accepted: tuple[str, ...], matches: bool
) -> None:
    assert answer_matches(said, accepted) is matches


@pytest.mark.parametrize(
    ("reason", "page_top", "cause"),
    [
        ('nothing on this page is link "Travel"', "", NOT_FOUND),
        ('waited 15 s for link "Belt Sander" and it never appeared', "", NOT_FOUND),
        ('3 matches for link "Next": #1 ...', "", WRONG_ELEMENT),
        ("Locator.click: Timeout 15000ms exceeded.", "", NOT_READY),
        ("the site showed a human check instead of the page", "", BLOCKED),
        ("Page.goto: net::ERR_CERT_INVALID at https://x/", "", BLOCKED),
        ('nothing on this page is link "Realmah"', "\n504 Gateway Time-out", BLOCKED),
        ("the page answered HTTP 404 instead of the page", "", ANSWER_CHANGED),
        ("the read found nothing there", "", OTHER),
    ],
)
def test_a_stopped_step_gets_a_cause_from_its_reason(
    reason: str, page_top: str, cause: str
) -> None:
    assert cause_of(reason, page_top) == cause


def test_a_long_page_that_mentions_403_further_down_is_not_a_block() -> None:
    page = "RFC 9110\n" + "x" * reliability.PAGE_TOP_CHARS + " 403 Forbidden"
    assert cause_of('nothing on this page is heading "418"', page[:300]) == NOT_FOUND


def test_a_wrong_answer_is_the_wrong_element_while_the_page_still_shows_the_right_one() -> None:
    assert cause_of_wrong_answer("Author Alberto Perez", ("Alberto Perez",)) == WRONG_ELEMENT
    assert cause_of_wrong_answer("Author Dominic Orchard", ("Alberto Perez",)) == ANSWER_CHANGED


def test_the_summary_counts_passes_and_failures_by_cause() -> None:
    def result(passed: bool, cause: str = "", engine: str = "dejo") -> Result:
        return Result("R01", "x", "y", engine, passed, 1.0, cause=cause)

    results = [
        result(True),
        result(False, NOT_FOUND),
        result(False, NOT_FOUND),
        result(False, BLOCKED),
        result(True, engine="playwright"),
    ]
    assert summary(results, "dejo") == {
        "passed": 1,
        "total": 4,
        "failures_by_cause": {NOT_FOUND: 2, BLOCKED: 1},
    }
