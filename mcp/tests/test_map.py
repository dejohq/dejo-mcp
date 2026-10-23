"""The map: what Dejo saw on a site, offered when it saves work.

Recording what Dejo saw is only half of it. The other half is that the agent can use it: the
controls on a page Dejo has stood on work as step targets without looking at the page again.
The shape is index-then-detail, because a forty-page map cannot ride inside every reply.
"""

from __future__ import annotations

from dejo.browser import domain_of
from dejo.models import Playbook

from helpers import TASK, call, teach_the_site

# The demo site's front page is the sign-in screen; these are on it.
ON_THE_FRONT_PAGE = ('textbox "Email"', 'textbox "Password"', 'button "Sign in"')


def mapped(mcp_server, demo_server, path: str | None = None) -> str:
    options = {"path": path} if path else {}
    return call(mcp_server, "dejo_memory", what="map", site=demo_server, **options)


class TestANewTaskOnAKnownSite:
    def test_it_is_told_which_tasks_dejo_already_knows(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        first = call(
            mcp_server,
            "dejo_run",
            site=demo_server,
            task="something else entirely",
            url=f"{demo_server}/",
        )

        assert first.startswith('new task "something else entirely"')
        assert f'other tasks Dejo knows here: "{TASK}"' in first

    def test_a_close_wording_runs_the_saved_trail_instead(self, mcp_server, demo_server):
        """Nobody words a request the same way twice. A close wording must replay, not
        learn the site again."""
        teach_the_site(mcp_server, demo_server)

        done = call(
            mcp_server, "dejo_run", site=demo_server, task="download the invoice for this month"
        )

        assert done.startswith(f'done: "{TASK}"'), done
        assert "the same job" in done

    def test_two_close_trails_are_both_offered(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        mcp_server.dejo_tools.store.save_playbook(
            Playbook(domain=domain_of(demo_server), task="download last month's invoice")
        )

        first = call(mcp_server, "dejo_run", site=demo_server, task="download the invoice")

        assert "other tasks Dejo knows here" in first
        assert "download last month's invoice" in first and TASK in first

    def test_a_site_nobody_walked_lists_no_tasks(self, mcp_server, demo_server):
        first = call(mcp_server, "dejo_run", site=demo_server, task=TASK, url=f"{demo_server}/")
        assert "other tasks" not in first


class TestTheMap:
    def test_the_index_lists_what_was_walked(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        index = mapped(mcp_server, demo_server)

        for path in ("/ ·", "/invoices ·", "/invoices/:id ·"):
            assert path in index

    def test_one_page_gives_back_what_was_on_it_as_step_targets(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        page = mapped(mcp_server, demo_server, "/")

        for target in ON_THE_FRONT_PAGE:
            assert target in page
        assert "work as step targets" in page

    def test_an_id_in_the_path_is_generalised(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        assert mapped(mcp_server, demo_server, "/invoices/2026-09").startswith("/invoices/:id ")

    def test_every_page_says_when_it_was_seen(self, mcp_server, demo_server):
        """This is what Dejo saw LAST time, not what is there now."""
        teach_the_site(mcp_server, demo_server)
        assert ", seen 20" in mapped(mcp_server, demo_server, "/")

    def test_a_page_never_looked_at_says_so(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        assert "has not looked at /nowhere" in mapped(mcp_server, demo_server, "/nowhere")

    def test_a_site_with_no_map_says_so(self, mcp_server):
        assert "has not looked at any page" in call(
            mcp_server, "dejo_memory", what="map", site="never.visited.example.com"
        )

    def test_a_map_target_works_in_steps_without_looking(self, mcp_server, demo_server):
        """The saving: a control from the map is pressed with no look at the page first."""
        teach_the_site(mcp_server, demo_server)
        task = "sign in from the map"
        call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/")

        said = call(
            mcp_server,
            "dejo_run",
            site=demo_server,
            task=task,
            steps='click button "Sign in"\nread url as here',
        )

        assert "here = " in said and "/invoices" in said


def test_the_gate_holds_through_the_tools_too(mcp_server, demo_server):
    teach_the_site(mcp_server, demo_server)
    assert "/invoices" in mapped(mcp_server, demo_server)

    call(mcp_server, "dejo_manage", do="forget", site=demo_server)

    assert "has not looked at any page" in mapped(mcp_server, demo_server)
