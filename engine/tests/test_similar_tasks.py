"""Two tasks whose names differ in what they DO are two jobs, never one.

Saved: "download invoice" and "delete invoice". Asked: "download my invoice". Matching by the
words the names share would run the delete. The verb is the job: download and delete, open
and close, add and remove, cancel and track, approve and reject are opposite or different
deeds, however many other words they share.

A trail that does something risky (a `click!`: pay, send, delete) is never picked by a loose
match either. Only the task it was saved as, or that task in other common words, runs it.
"""

from __future__ import annotations

import pytest

from dejo.models import Locator, Playbook, Postcondition, Step
from dejo.store import DejoStore, best_match, shares_meaning

SITE = "shop.example"

# Pairs of tasks that share every word but the deed.
OPPOSITES = [
    ("download my invoice", "delete invoice"),
    ("open the support ticket", "close the support ticket"),
    ("add a team member", "remove a team member"),
    ("track my order", "cancel my order"),
    ("approve the expense report", "reject the expense report"),
    ("archive the project", "restore the project"),
    ("enable two factor sign in", "disable two factor sign in"),
    ("lock the account", "unlock the account"),
]


def trail(task: str, *, risky: bool = False) -> Playbook:
    """A two-step trail: open the page, press the task's button."""
    deed = task.split()[0]
    return Playbook(
        domain=SITE,
        task=task,
        steps=[
            Step(
                index=1,
                intent="open the page",
                action="goto",
                value=f"https://{SITE}/things",
                postcondition=Postcondition("url_contains", "/things"),
            ),
            Step(
                index=2,
                intent=f"press {deed}",
                action="click",
                locators=[Locator("role", f"button|{deed.title()}")],
                postcondition=Postcondition("text_present", "done"),
                risky=risky,
            ),
        ],
    )


@pytest.mark.parametrize(("asked", "saved"), OPPOSITES + [(b, a) for a, b in OPPOSITES])
def test_a_different_deed_never_shares_meaning(asked: str, saved: str) -> None:
    assert not shares_meaning(asked, saved, SITE)


@pytest.mark.parametrize(("asked", "saved"), OPPOSITES + [(b, a) for a, b in OPPOSITES])
def test_a_different_deed_is_never_the_best_match(asked: str, saved: str) -> None:
    assert best_match(asked, [saved, "count the visitors"], domain=SITE) is None


@pytest.mark.parametrize(("asked", "saved"), OPPOSITES + [(b, a) for a, b in OPPOSITES])
def test_the_only_trail_is_not_run_for_the_opposite_deed(tmp_path, asked: str, saved: str) -> None:
    store = DejoStore(db_path=str(tmp_path / "memory.db"))
    store.save_playbook(trail(saved, risky=True))
    assert store.load_playbook(SITE, asked) is None


def test_download_finds_download_and_never_delete(tmp_path) -> None:
    store = DejoStore(db_path=str(tmp_path / "memory.db"))
    store.save_playbook(trail("download invoice"))
    store.save_playbook(trail("delete invoice", risky=True))

    found = store.load_playbook(SITE, "download my invoice")

    assert found is not None and found.task == "download invoice"


class TestARiskyTrailNeedsTheSameTask:
    """A loose match is fine for reading something, and never for pressing pay or delete."""

    @pytest.mark.parametrize(
        "asked",
        [
            "delete the invoice",
            "delete the draft invoice from march",
            "delete every draft",
        ],
    )
    def test_a_loose_match_does_not_pick_a_risky_trail(self, tmp_path, asked: str) -> None:
        store = DejoStore(db_path=str(tmp_path / "memory.db"))
        store.save_playbook(trail("delete the draft invoice", risky=True))
        assert store.load_playbook(SITE, asked) is None

    @pytest.mark.parametrize(
        "asked",
        ["delete the draft invoice", "Delete the draft invoice.", "delete my draft invoice"],
    )
    def test_the_same_task_still_runs_it(self, tmp_path, asked: str) -> None:
        store = DejoStore(db_path=str(tmp_path / "memory.db"))
        store.save_playbook(trail("delete the draft invoice", risky=True))
        found = store.load_playbook(SITE, asked)
        assert found is not None and found.task == "delete the draft invoice"

    def test_a_loose_match_still_finds_a_trail_that_only_reads(self, tmp_path) -> None:
        store = DejoStore(db_path=str(tmp_path / "memory.db"))
        store.save_playbook(trail("count open issues"))
        assert store.load_playbook(SITE, "how many open issues are there") is not None
