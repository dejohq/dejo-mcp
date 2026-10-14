"""`dejo show` on a site that remembers more than one thing.

This is the command a person reaches for to see what memory actually holds, and it used to
answer "nothing remembered for marketplace.example" about a site holding three trails.
`load_playbook` has no branch for "several trails, no task named", so it fell through every
case and returned None — and the one command whose whole job is to show you memory told you
memory was empty.
"""

from __future__ import annotations

import pytest

from dejo.cli import main
from dejo.models import Locator, Playbook, Postcondition, Step
from dejo.store import DejoStore

SITE = "marketplace.example"


def a_trail(task: str) -> Playbook:
    return Playbook(
        domain=SITE,
        task=task,
        runs=2,
        steps=[
            Step(
                index=1,
                intent="open the sign-in page",
                action="goto",
                value=f"https://{SITE}/admin/sign-in",
                postcondition=Postcondition("url_contains", "/admin/sign-in"),
            ),
            Step(
                index=2,
                intent="type the admin email",
                action="fill",
                value="admin@marketplace.example",
                postcondition=Postcondition("element_present", "#email"),
                locators=[Locator("css", "#email", hits=4)],
            ),
        ],
    )


@pytest.fixture
def db(tmp_path) -> str:
    return str(tmp_path / "memory.db")


def run(db: str, *argv: str) -> int:
    return main(["--db", db, *argv])


class TestASiteWithSeveralTrails:
    @pytest.fixture(autouse=True)
    def three_trails(self, db):
        store = DejoStore(db_path=db)
        for task in ("sign in as admin", "register a new vendor", "submit a quote"):
            store.save_playbook(a_trail(task))

    def test_it_lists_them_instead_of_claiming_the_site_is_unknown(self, db, capsys):
        code = run(db, "show", SITE)
        out = capsys.readouterr().out

        assert code == 0
        assert "nothing remembered" not in out
        assert "sign in as admin" in out
        assert "register a new vendor" in out
        assert "submit a quote" in out

    def test_and_shows_how_to_ask_for_one(self, db, capsys):
        """A list with no way to act on it just moves the dead end one step along."""
        run(db, "show", SITE)

        assert "--task" in capsys.readouterr().out

    def test_naming_one_prints_its_steps(self, db, capsys):
        code = run(db, "show", SITE, "--task", "sign in as admin")
        out = capsys.readouterr().out

        assert code == 0
        assert "open the sign-in page" in out
        assert "type the admin email" in out


class TestASiteWithOneTrail:
    def test_it_still_prints_the_steps_with_no_task_named(self, db, capsys):
        """The single-trail case has to keep working exactly as it did."""
        DejoStore(db_path=db).save_playbook(a_trail("sign in as admin"))

        code = run(db, "show", SITE)
        out = capsys.readouterr().out

        assert code == 0
        assert "open the sign-in page" in out


class TestASiteWithNothing:
    def test_it_says_so(self, db, capsys):
        code = run(db, "show", "never-seen.example")

        assert code == 2
        assert "nothing remembered" in capsys.readouterr().out
