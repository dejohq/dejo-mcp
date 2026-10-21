"""More than one signed-in identity at a time.

A suite testing a marketplace with a customer, a vendor and an admin used to sign out and
back in between roles: slow, and it made the ORDER of the work matter. A profile is a whole
browser (its own cookies, session and process), so Dejo keeps them side by side and
switching between them is free.

Trails and the map are shared by every profile: the site is one site however many logins
reach it.
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


def open_page(server, demo_server: str, profile: str, path: str) -> str:
    """Open a page as one profile, as a new task of that profile's own."""
    return call(
        server,
        "dejo_run",
        site=demo_server,
        task=f"open {path} as {profile}",
        url=f"{demo_server}{path}",
        profile=profile,
    )


class TestNamingProfiles:
    def test_it_starts_on_the_default_one(self, server):
        assert call(server, "dejo_profile").startswith(f"profiles: {DEFAULT_PROFILE_NAME} (in use)")

    def test_a_new_name_is_made_on_the_spot(self, server):
        said = call(server, "dejo_profile", name="vendor")
        assert said.startswith(f"now working as vendor (was {DEFAULT_PROFILE_NAME})")

    def test_the_default_keeps_the_folder_it_always_had(self, server, tmp_path):
        tools = server.dejo_tools
        assert tools.path_for(DEFAULT_PROFILE_NAME) == str(tmp_path / "default-profile")

    def test_every_other_profile_gets_its_own_folder(self, server, tmp_path):
        tools = server.dejo_tools
        vendor, admin = tools.path_for("vendor"), tools.path_for("admin")
        assert vendor != admin
        assert str(tmp_path / "profiles") in vendor

    def test_a_name_with_spaces_still_makes_one_folder(self, server):
        assert server.dejo_tools.path_for("Vendor A").endswith("vendor-a")

    def test_listing_says_which_one_is_in_use(self, server):
        call(server, "dejo_profile", name="admin")
        assert "admin (in use)" in call(server, "dejo_profile")

    def test_dejo_run_can_switch_profile_for_itself(self, server, demo_server):
        """A multi-role job needs no extra tool load: dejo_run takes the profile."""
        said = open_page(server, demo_server, "admin", "/")
        assert "(profile admin)" in said
        assert server.dejo_tools.active == "admin"


class TestSideBySide:
    def test_two_profiles_are_two_browsers_at_the_same_time(self, server, demo_server):
        open_page(server, demo_server, "vendor", "/")
        open_page(server, demo_server, "customer", "/invoices")

        tools = server.dejo_tools
        assert tools._workers["vendor"].running
        assert tools._workers["customer"].running

    def test_each_keeps_its_own_page(self, server, demo_server):
        open_page(server, demo_server, "vendor", "/")
        open_page(server, demo_server, "customer", "/settings")

        call(server, "dejo_profile", name="vendor")
        where = call(
            server, "dejo_run", site=demo_server, task="open / as vendor", steps="read url as here"
        )

        assert "here = " in where and not where.split("here = ")[1].startswith(
            f"{demo_server}/settings"
        ), "it landed on the other profile's page"

    def test_each_learns_its_own_steps(self, server, demo_server):
        open_page(server, demo_server, "vendor", "/")
        open_page(server, demo_server, "customer", "/")

        runs = server.dejo_tools._runners
        vendor = next(r for (who, _, _), r in runs.items() if who == "vendor")
        customer = next(r for (who, _, _), r in runs.items() if who == "customer")
        assert vendor.session is not customer.session

    def test_what_one_profile_saw_the_next_one_knows(self, server, demo_server):
        open_page(server, demo_server, "vendor", "/")

        call(server, "dejo_profile", name="customer")
        assert "pages seen:" in call(server, "dejo_memory", what="map", site=demo_server)


class TestRememberingWhoIsInUse:
    """An MCP server restarts whenever its client does. The active profile used to reset to
    `default` there, silently, and the next failure looked like a broken trail."""

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
            assert "admin (in use)" in call(second, "dejo_profile")
        finally:
            second.dejo_tools.close()

    def test_a_machine_where_nobody_ever_switched_is_still_the_default(self, server):
        assert f"{DEFAULT_PROFILE_NAME} (in use)" in call(server, "dejo_profile")

    def test_the_note_of_who_is_in_use_is_not_itself_a_profile(self, server):
        call(server, "dejo_profile", name="admin")
        assert ".active" not in call(server, "dejo_profile")


class TestPasswordsFollowTheProfile:
    def test_a_password_lookup_names_the_profile_even_when_it_is_the_default(self, server):
        assert server.dejo_tools.secrets_profile == DEFAULT_PROFILE_NAME

    def test_and_the_one_that_was_switched_to(self, server):
        call(server, "dejo_profile", name="vendor")
        assert server.dejo_tools.secrets_profile == "vendor"

    def test_a_new_task_says_who_it_ran_as(self, server, demo_server):
        said = call(server, "dejo_run", site=demo_server, task="look", url=f"{demo_server}/")
        assert f"(profile {DEFAULT_PROFILE_NAME})" in said
