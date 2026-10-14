"""Handing the map to the host AI.

Recording what Dejo saw is only half of it. The other half is that the AI is TOLD, at the
moment it is about to explore, that Dejo has already stood on these pages — otherwise the
memory exists and nothing ever reads it.

The shape is index-then-detail, on purpose. A forty-page map cannot ride inside every
dejo_run reply, and most of it is irrelevant to any one task. So `dejo_run` returns the
table of contents and `dejo_map` opens one page.
"""

from __future__ import annotations

import asyncio

from dejo.browser import domain_of
from dejo.models import Playbook

from helpers import call, teach_the_site

# The demo site's front page is the login screen; these are on it.
ON_THE_FRONT_PAGE = {"Email", "Password", "Sign in"}


class TestTheMapIsOffered:
    def test_a_new_task_on_a_known_site_is_handed_the_pages(self, mcp_server, demo_server):
        """The whole point. A second task used to start blind on a site already walked."""
        teach_the_site(mcp_server, demo_server)

        answer = call(mcp_server, "dejo_run", site=demo_server, task="something else entirely")

        assert answer["pages_known"], "a site Dejo has walked must not come back empty"
        assert {row["path"] for row in answer["pages_known"]} >= {"/", "/invoices"}

    def test_and_told_to_start_from_them(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        answer = call(mcp_server, "dejo_run", site=demo_server, task="something else entirely")

        assert "pages_known" in answer["next"]
        assert "ALREADY" in answer["next"]

    def test_the_old_instruction_no_longer_forbids_a_genuinely_new_task(
        self, mcp_server, demo_server
    ):
        """This branch used to end "Do NOT explore — the trail is already there".

        True when one of `tasks` is what was asked for. Simply wrong when none is, which
        is exactly the case this whole feature exists for.
        """
        teach_the_site(mcp_server, demo_server)

        answer = call(mcp_server, "dejo_run", site=demo_server, task="something else entirely")

        assert answer["needs_task"] is True
        assert "If none of them is" in answer["next"]

    def test_but_it_is_withheld_when_a_saved_trail_plainly_fits(self, mcp_server, demo_server):
        """The advice that made Dejo lose its own benchmark.

        Measured on 2026-09-05: the model called dejo_run, was not given a trail by name,
        and read the page itself — because directly under a hedged retry sat a concrete
        exploration plan with real page paths. It is the longer and more actionable of the
        two, so it won. It is now withheld while a trail plausibly matches.

        "Plausibly" is doing real work here: ranking returns EVERY task, so the mere
        presence of candidates says nothing about whether any of them is the job.
        """
        teach_the_site(mcp_server, demo_server)
        mcp_server.dejo_tools.store.save_playbook(
            Playbook(domain=domain_of(demo_server), task="download last month's invoice")
        )

        answer = call(mcp_server, "dejo_run", site=demo_server, task="download the invoice")

        assert answer["needs_task"] is True
        assert "DO THIS FIRST" in answer["next"]
        assert "ALREADY" not in answer["next"], "the escape hatch must not be offered here"

    def test_a_site_nobody_walked_offers_an_empty_map_rather_than_a_lie(self, mcp_server):
        answer = call(mcp_server, "dejo_run", site="never.visited.example.com")

        assert answer["known"] is False
        assert answer["pages_known"] == []
        assert "ALREADY" not in answer["next"]


class TestOpeningOnePage:
    def test_the_index_lists_what_was_walked(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        answer = call(mcp_server, "dejo_map", site=demo_server)

        assert answer["ok"] is True
        assert {row["path"] for row in answer["pages"]} == {"/", "/invoices", "/invoices/:id"}

    def test_the_index_carries_no_controls(self, mcp_server, demo_server):
        """Index then detail: a whole map inside every reply is what this avoids."""
        teach_the_site(mcp_server, demo_server)

        answer = call(mcp_server, "dejo_map", site=demo_server)

        assert all("controls" in row for row in answer["pages"])
        assert all(isinstance(row["controls"], int) for row in answer["pages"])

    def test_one_page_gives_back_what_was_on_it(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        answer = call(mcp_server, "dejo_map", site=demo_server, path="/")

        names = {control["name"] for control in answer["controls"]}
        assert names >= ON_THE_FRONT_PAGE

    def test_an_id_in_the_path_is_generalised(self, mcp_server, demo_server):
        """The demo site's invoice is `2026-09`. Twelve months must not be twelve pages."""
        teach_the_site(mcp_server, demo_server)

        answer = call(mcp_server, "dejo_map", site=demo_server, path="/invoices/2026-09")

        assert answer["ok"] is True
        assert answer["path"] == "/invoices/:id"

    def test_a_page_never_looked_at_says_so_and_lists_the_ones_that_were(
        self, mcp_server, demo_server
    ):
        teach_the_site(mcp_server, demo_server)

        answer = call(mcp_server, "dejo_map", site=demo_server, path="/nowhere")

        assert answer["ok"] is False
        assert "/invoices" in answer["pages"]

    def test_a_site_with_no_map_says_how_to_get_one(self, mcp_server):
        answer = call(mcp_server, "dejo_map", site="never.visited.example.com")

        assert answer["ok"] is False
        assert "dejo_act" in answer["next"]


class TestItNeverClaimsToBeCurrent:
    """A map is a memory with a date on it, exactly like a locator."""

    def test_every_page_in_the_index_says_when_it_was_seen(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        rows = call(mcp_server, "dejo_map", site=demo_server)["pages"]

        assert all(row["seen"] for row in rows)

    def test_one_page_carries_its_own_date_and_says_to_check(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        answer = call(mcp_server, "dejo_map", site=demo_server, path="/")

        assert answer["last_seen"]
        # The substance, not one word: it must say the page may have moved, and name the
        # way back when it has.
        assert "last looked" in answer["next"]
        assert "dejo_read" in answer["next"]

    def test_the_description_warns_the_ai_in_its_own_words(self, mcp_server):
        described = {t.name: t.description or "" for t in asyncio.run(mcp_server.list_tools())}

        assert "NOT WHAT IS THERE NOW" in described["dejo_map"]


class TestForgettingTakesTheMap:
    def test_the_gate_holds_through_the_tools_too(self, mcp_server, demo_server):
        """Someone running this from inside their own Claude Code must see it go."""
        teach_the_site(mcp_server, demo_server)
        assert call(mcp_server, "dejo_map", site=demo_server)["ok"] is True

        call(mcp_server, "dejo_forget", site=demo_server)

        assert call(mcp_server, "dejo_map", site=demo_server)["ok"] is False
        assert call(mcp_server, "dejo_run", site=demo_server)["pages_known"] == []
