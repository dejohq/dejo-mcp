"""The handoff from a terminal, with no MCP client anywhere.

Anyone should be able to see two agents share a trail without installing anything or
trusting a screen recording. These are the commands that make that possible.
"""

from __future__ import annotations

import shlex

import pytest

from dejo.cli import build_parser, main
from dejo.models import Locator, Playbook, Postcondition, Step
from dejo.store import DejoStore

SITE = "acme.com"
TASK = "read the invoice total"


def a_trail() -> Playbook:
    return Playbook(
        domain=SITE,
        task=TASK,
        runs=3,
        steps=[
            Step(
                index=1,
                intent="open the portal",
                action="goto",
                value=f"https://{SITE}/",
                postcondition=Postcondition("url_contains", "/"),
            ),
            Step(
                index=2,
                intent="type the account email",
                action="fill",
                value="alice@acme.com",
                postcondition=Postcondition("element_present", "#email"),
                locators=[Locator("css", "#email", hits=5)],
            ),
        ],
    )


@pytest.fixture
def db(tmp_path) -> str:
    return str(tmp_path / "memory.db")


@pytest.fixture
def alice(db) -> DejoStore:
    store = DejoStore(db_path=db, agent="alice")
    store.save_playbook(a_trail())
    return store


def run(db: str, *argv: str) -> int:
    return main(["--db", db, *argv])


class TestTheAgentFlag:
    def test_an_agent_sees_only_its_own_trails(self, alice, db, capsys):
        run(db, "--agent", "bob", "sites")

        assert "remembers nothing yet" in capsys.readouterr().out

    def test_the_acting_agent_is_announced(self, alice, db, capsys):
        """An exported DEJO_AGENT nobody remembers setting looks exactly like data loss."""
        run(db, "--agent", "bob", "sites")

        assert "as agent bob" in capsys.readouterr().out

    def test_no_agent_means_the_memory_that_was_already_there(self, db, capsys):
        DejoStore(db_path=db).save_playbook(a_trail())

        run(db, "sites")
        out = capsys.readouterr().out

        assert SITE in out
        assert "as agent" not in out


class TestSharingFromATerminal:
    def test_sharing_says_what_became_public(self, alice, db, capsys):
        run(db, "--agent", "alice", "share", SITE)

        assert "shared" in capsys.readouterr().out

    def test_sharing_says_what_stayed_behind(self, alice, db, capsys):
        """The email typed into the login form is the thing most worth being told about."""
        run(db, "--agent", "alice", "share", SITE)
        out = capsys.readouterr().out

        assert "did NOT leave your machine" in out
        assert "type the account email" in out
        assert "alice@acme.com" not in out

    def test_sharing_a_site_this_agent_never_walked_fails_clearly(self, db, capsys):
        assert run(db, "--agent", "bob", "share", "nowhere.com") == 2
        assert "no trail here to share" in capsys.readouterr().out


class TestBorrowingFromATerminal:
    def test_the_commons_lists_what_others_left(self, alice, db, capsys):
        run(db, "--agent", "alice", "share", SITE)
        capsys.readouterr()

        run(db, "--agent", "bob", "commons")
        out = capsys.readouterr().out

        assert SITE in out
        assert "left by alice" in out

    def test_an_empty_commons_says_so(self, db, capsys):
        run(db, "--agent", "bob", "commons")

        assert "nothing has been shared yet" in capsys.readouterr().out

    def test_borrowing_writes_the_trail_into_this_agents_memory(self, alice, db, capsys):
        run(db, "--agent", "alice", "share", SITE)
        capsys.readouterr()

        assert run(db, "--agent", "bob", "borrow", SITE) == 0
        assert DejoStore(db_path=db, agent="bob").load_playbook(SITE, TASK) is not None

    def test_borrowing_prints_the_exact_command_to_run_next(self, alice, db, capsys):
        """A paraphrased task may not match, so the wording is handed over verbatim."""
        run(db, "--agent", "alice", "share", SITE)
        capsys.readouterr()

        run(db, "--agent", "bob", "borrow", SITE)
        out = capsys.readouterr().out

        printed = f'dejo run "{TASK}" --site {SITE}'
        assert printed in out
        # It once printed `--task`, which `run` does not have, so the hint itself failed.
        args = build_parser().parse_args(shlex.split(printed)[1:])
        assert (args.task, args.site) == (TASK, SITE)

    def test_borrowing_says_what_it_will_ask_for(self, alice, db, capsys):
        run(db, "--agent", "alice", "share", SITE)
        capsys.readouterr()

        run(db, "--agent", "bob", "borrow", SITE)

        assert "it will ask you for: email" in capsys.readouterr().out

    def test_borrowing_nothing_fails_clearly(self, db, capsys):
        assert run(db, "--agent", "bob", "borrow", "nowhere.com") == 2
        assert "nobody has shared" in capsys.readouterr().out

    def test_borrowing_over_a_repaired_trail_needs_saying_so(self, alice, db, capsys):
        run(db, "--agent", "alice", "share", SITE)
        mine = a_trail()
        mine.repairs = 1
        DejoStore(db_path=db, agent="bob").save_playbook(mine)
        capsys.readouterr()

        assert run(db, "--agent", "bob", "borrow", SITE) == 2
        assert "--force" in capsys.readouterr().out

        assert run(db, "--agent", "bob", "borrow", SITE, "--force") == 0
