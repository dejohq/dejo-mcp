"""More than one signed-in identity at a time.

Dejo used to keep a single browser profile. A suite testing a marketplace with a customer,
a vendor and an admin therefore had to sign out and back in between roles — slow, and worse,
it made the ORDER of the tests matter: anything that forgot to sign out broke whatever ran
next.

A profile is a whole browser: its own cookies, its own session, its own process. Dejo keeps
them side by side now, so all three stay signed in and switching between them is free.

Memory is deliberately NOT split by profile. The site is one site however many logins reach
it, which is the same reason the map is one merged map per site.
"""

from __future__ import annotations

import pytest
from dejo.browser import DEFAULT_PROFILE_NAME

from dejo_mcp.server import build_server
from helpers import call


@pytest.fixture
def server(tmp_path):
    """A server whose profiles live under the test's own folder, never the real one."""
    built = build_server(
        db_path=str(tmp_path / "memory.db"),
        headless=True,
        downloads=str(tmp_path / "downloads"),
        profile=str(tmp_path / "default-profile"),
        profiles_dir=str(tmp_path / "profiles"),
    )
    yield built
    built.dejo_tools.close()


class TestNamingProfiles:
    def test_it_starts_on_the_default_one(self, server):
        answer = call(server, "dejo_profile")

        assert answer["active"] == DEFAULT_PROFILE_NAME

    def test_a_new_name_is_made_on_the_spot(self, server):
        answer = call(server, "dejo_profile", name="vendor")

        assert answer["active"] == "vendor"
        assert answer["was"] == DEFAULT_PROFILE_NAME

    def test_the_default_keeps_the_folder_it_always_had(self, server, tmp_path):
        """Naming profiles must not quietly move somebody's sign-ins somewhere new."""
        tools = server.dejo_tools

        assert tools.path_for(DEFAULT_PROFILE_NAME) == str(tmp_path / "default-profile")

    def test_every_other_profile_gets_its_own_folder(self, server, tmp_path):
        tools = server.dejo_tools

        vendor = tools.path_for("vendor")
        admin = tools.path_for("admin")

        assert vendor != admin
        assert str(tmp_path / "profiles") in vendor

    def test_a_name_with_spaces_still_makes_one_folder(self, server):
        tools = server.dejo_tools

        assert tools.path_for("Vendor A").endswith("vendor-a")

    def test_listing_says_which_one_is_in_use(self, server):
        call(server, "dejo_profile", name="admin")

        listed = call(server, "dejo_profile")["profiles"]

        assert [row["name"] for row in listed if row["active"]] == ["admin"]


class TestTheyAreReallySeparateBrowsers:
    def test_two_profiles_are_two_browsers_at_the_same_time(self, server, demo_server):
        """The claim, tested rather than asserted: both open, neither closing the other."""
        tools = server.dejo_tools

        call(server, "dejo_profile", name="vendor")
        call(server, "dejo_act", intent="open", action="goto", value=f"{demo_server}/")
        call(server, "dejo_profile", name="customer")
        call(server, "dejo_act", intent="open", action="goto", value=f"{demo_server}/invoices")

        assert tools._workers["vendor"].running
        assert tools._workers["customer"].running

    def test_each_keeps_its_own_page(self, server, demo_server):
        """Switching back must land where that profile left off, not where the other is."""
        call(server, "dejo_profile", name="vendor")
        call(server, "dejo_act", intent="open", action="goto", value=f"{demo_server}/")
        call(server, "dejo_profile", name="customer")
        call(server, "dejo_act", intent="open", action="goto", value=f"{demo_server}/settings")

        call(server, "dejo_profile", name="vendor")
        where = call(server, "dejo_read", kind="url")["value"]

        assert not where.endswith("/settings"), "it landed on the other profile's page"

    def test_each_has_its_own_trace(self, server, demo_server):
        """A trace belongs to the browser that made it. Sharing one would mix an admin's
        steps into a customer's trail."""
        tools = server.dejo_tools
        call(server, "dejo_profile", name="vendor")
        call(server, "dejo_act", intent="open", action="goto", value=f"{demo_server}/")
        call(server, "dejo_read", kind="page")

        call(server, "dejo_profile", name="customer")

        assert tools._sessions["vendor"] is not tools._sessions.get("customer")


class TestMemoryIsNotSplit:
    def test_what_one_profile_learned_the_next_one_knows(self, server, demo_server):
        """One site is one site, however many logins reach it."""
        call(server, "dejo_profile", name="vendor")
        call(server, "dejo_act", intent="open", action="goto", value=f"{demo_server}/")
        call(server, "dejo_read", kind="page")

        call(server, "dejo_profile", name="customer")
        mapped = call(server, "dejo_map", site=demo_server)

        assert mapped["ok"] is True
        assert any(row["path"] == "/" for row in mapped["pages"])


class TestRememberingWhoIsInUse:
    """An MCP server restarts whenever its client does.

    The active profile used to reset to `default` there, silently. An agent that had been
    an admin for an hour came back signed in to nothing, and the next failure looked like
    a broken trail or a missing password instead of the identity change it was.
    """

    def test_a_restart_comes_back_as_the_same_profile(self, tmp_path):
        first = build_server(
            db_path=str(tmp_path / "memory.db"),
            headless=True,
            profile=str(tmp_path / "default-profile"),
            profiles_dir=str(tmp_path / "profiles"),
        )
        call(first, "dejo_profile", name="admin")
        first.dejo_tools.close()

        second = build_server(
            db_path=str(tmp_path / "memory.db"),
            headless=True,
            profile=str(tmp_path / "default-profile"),
            profiles_dir=str(tmp_path / "profiles"),
        )
        try:
            assert call(second, "dejo_profile")["active"] == "admin"
        finally:
            second.dejo_tools.close()

    def test_a_machine_where_nobody_ever_switched_is_still_the_default(self, server):
        assert call(server, "dejo_profile")["active"] == DEFAULT_PROFILE_NAME

    def test_the_note_of_who_is_in_use_is_not_itself_a_profile(self, server):
        call(server, "dejo_profile", name="admin")

        listed = call(server, "dejo_profile")["profiles"]

        assert all(not row["name"].startswith(".") for row in listed)


class TestEveryAnswerSaysWhichIdentity:
    """Naming it is what makes a remembered profile safe rather than surprising."""

    def test_a_password_lookup_names_the_profile_even_when_it_is_the_default(self, server):
        assert server.dejo_tools.secrets_profile == DEFAULT_PROFILE_NAME

    def test_and_the_one_that_was_switched_to(self, server):
        call(server, "dejo_profile", name="vendor")

        assert server.dejo_tools.secrets_profile == "vendor"

    def test_a_run_on_an_unknown_site_still_says_who_it_ran_as(self, server, demo_server):
        answer = call(server, "dejo_run", site=demo_server)

        assert answer["profile"] == DEFAULT_PROFILE_NAME
