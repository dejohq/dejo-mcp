"""The tool surface itself.

Exploring used to be four tools — open, look, act, save. It is now two verbs, `dejo_act`
and `dejo_read`, plus `dejo_save` at the end. Tool choice is the most fragile part of
this whole system: on the first live test a host AI ignored Dejo completely and reached
for `curl`. Thirty-one separate action tools would have made that worse, not better.

So the descriptions are generated from the registries rather than written beside them. A
hand-kept list drifts the first time an action is added, and an action a host AI cannot see
may as well not exist.
"""

from __future__ import annotations

import asyncio

import pytest
from dejo import actions, reads

from helpers import call, ref_named

EXPLORING_TOOLS = {"dejo_act", "dejo_read", "dejo_save"}


@pytest.fixture
def described(mcp_server) -> dict[str, str]:
    return {t.name: t.description or "" for t in asyncio.run(mcp_server.list_tools())}


@pytest.fixture
def on_the_page(mcp_server, demo_server):
    """The demo site's front page, open and looked at."""
    call(
        mcp_server,
        "dejo_act",
        intent="open the billing portal",
        action="goto",
        value=f"{demo_server}/",
    )
    return call(mcp_server, "dejo_read", kind="page")


# ----------------------------------------------------------- one tool each


def test_the_old_tools_are_gone(described: dict[str, str]) -> None:
    assert "dejo_open" not in described
    assert "dejo_look" not in described


def test_exploring_is_two_verbs_plus_save(described: dict[str, str]) -> None:
    assert set(described) >= EXPLORING_TOOLS


def test_every_action_is_named_in_one_description(described: dict[str, str]) -> None:
    """The whole list has to be reachable from the one tool that performs it. Generated
    from the registry, so adding an action can never leave it undiscoverable."""
    for name in actions.ACTIONS:
        assert name in described["dejo_act"], f"{name} is not in the tool description"


def test_every_read_is_named_in_one_description(described: dict[str, str]) -> None:
    for name in reads.READS:
        assert name in described["dejo_read"], f"{name} is not in the tool description"
    assert "page" in described["dejo_read"]


def test_the_act_description_still_rules_out_curl(described: dict[str, str]) -> None:
    """The real failure seen in testing. A description that only ranks Dejo's own tools
    against each other loses to the shell, because the shell is always right there."""
    text = described["dejo_act"]
    for rival in ("curl", "wget", "fetch"):
        assert rival in text


def test_the_act_description_still_ranks_dejo_run_first(described: dict[str, str]) -> None:
    """Exploring a site whose task is already known throws away the entire point."""
    assert "dejo_run FIRST" in described["dejo_act"]
    assert "not known" in described["dejo_act"]


# ------------------------------------------------------------- acting


def test_goto_is_an_action_now(mcp_server, demo_server) -> None:
    result = call(
        mcp_server,
        "dejo_act",
        intent="open the billing portal",
        action="goto",
        value=f"{demo_server}/",
    )
    assert result["ok"]


def test_fill_and_click(mcp_server, on_the_page) -> None:
    filled = call(
        mcp_server,
        "dejo_act",
        intent="type the account email",
        action="fill",
        ref=ref_named(on_the_page, "Email"),
        value="finance@acme.com",
    )
    assert filled["ok"]


def test_an_action_that_does_not_exist_says_what_does(mcp_server, on_the_page) -> None:
    result = call(mcp_server, "dejo_act", intent="teleport", action="teleport")
    assert not result["ok"]
    assert "click" in result["error"]


def test_an_action_missing_its_value_says_what_is_needed(mcp_server, on_the_page) -> None:
    result = call(
        mcp_server,
        "dejo_act",
        intent="type the email",
        action="fill",
        ref=ref_named(on_the_page, "Email"),
    )
    assert not result["ok"]
    assert "value" in result["error"]


def test_wait_for_reaches_the_engine(mcp_server, on_the_page) -> None:
    result = call(mcp_server, "dejo_act", intent="let it settle", action="wait_for", value="idle")
    assert result["ok"]


def test_new_tab_and_switch_tab_reach_the_engine(mcp_server, on_the_page) -> None:
    assert call(mcp_server, "dejo_act", intent="open a tab", action="new_tab")["ok"]
    assert call(
        mcp_server,
        "dejo_act",
        intent="go back to the first tab",
        action="switch_tab",
        value="main",
    )["ok"]


# ------------------------------------------------------------- reading


def test_read_page_lists_the_controls(on_the_page) -> None:
    assert on_the_page["ok"]
    assert on_the_page["kind"] == "page"
    assert any(element["name"] == "Email" for element in on_the_page["elements"])


def test_read_page_is_the_default_kind(mcp_server, demo_server) -> None:
    """The first thing anyone wants is "what is on this page", so it costs no argument."""
    call(
        mcp_server,
        "dejo_act",
        intent="open the billing portal",
        action="goto",
        value=f"{demo_server}/",
    )
    assert call(mcp_server, "dejo_read")["kind"] == "page"


def test_read_a_value_off_one_element(mcp_server, on_the_page) -> None:
    email = ref_named(on_the_page, "Email")
    call(
        mcp_server,
        "dejo_act",
        intent="type the account email",
        action="fill",
        ref=email,
        value="finance@acme.com",
    )
    result = call(mcp_server, "dejo_read", kind="value", ref=email)
    assert result["ok"]
    assert result["value"] == "finance@acme.com"


def test_read_the_url(mcp_server, on_the_page, demo_server) -> None:
    result = call(mcp_server, "dejo_read", kind="url")
    assert result["ok"]
    assert demo_server in result["value"]


def test_read_counts_things(mcp_server, on_the_page) -> None:
    result = call(mcp_server, "dejo_read", kind="count", ref=ref_named(on_the_page, "Email"))
    assert result["ok"]
    assert result["value"] == 1


def test_a_read_that_does_not_exist_says_what_does(mcp_server, on_the_page) -> None:
    result = call(mcp_server, "dejo_read", kind="vibes")
    assert not result["ok"]
    assert "text" in result["error"]


def test_a_read_missing_its_element_says_so(mcp_server, on_the_page) -> None:
    result = call(mcp_server, "dejo_read", kind="text")
    assert not result["ok"]
    assert "ref" in result["error"].lower()


def test_reading_never_reports_what_is_in_a_password_box(mcp_server, on_the_page) -> None:
    """Playwright's own snapshot prints field contents in plain text, passwords included.
    Nothing that leaves this server may carry one."""
    call(
        mcp_server,
        "dejo_act",
        intent="type the password",
        action="fill",
        ref=ref_named(on_the_page, "Password"),
        value="hunter2",
    )
    page = call(mcp_server, "dejo_read", kind="page")
    assert "hunter2" not in str(page)


# ------------------------------------------ what the GitHub test found (P0)


def test_a_remembered_read_comes_back_from_a_warm_run(mcp_server, on_the_page, demo_server) -> None:
    """The bug GitHub exposed: a saved trail walked to a page and then stopped, so the
    answer had to be worked out again on every single run."""
    call(
        mcp_server,
        "dejo_read",
        kind="text",
        ref=ref_named(on_the_page, "Sign in"),
        remember=True,
        intent="read the sign in button",
    )
    call(mcp_server, "dejo_save", task="read the sign in button")

    result = call(mcp_server, "dejo_run", site=demo_server, task="read the sign in button")
    assert result["answers"]["read the sign in button"] == "Sign in"


def test_an_ordinary_read_is_not_remembered(mcp_server, on_the_page) -> None:
    result = call(mcp_server, "dejo_read", kind="text", ref=ref_named(on_the_page, "Sign in"))
    assert result["remembered"] is False


def test_the_read_description_says_to_remember_the_answer(described) -> None:
    """A host AI that does not know this saves trails that cannot answer anything."""
    assert "REMEMBER THE READ THAT IS THE ANSWER" in described["dejo_read"]


def test_dejo_run_takes_a_task(described) -> None:
    """One site, many tasks. Keying on the site alone meant github.com could hold one."""
    assert "task" in described["dejo_run"]


def test_remembering_the_whole_page_says_what_that_costs(mcp_server, on_the_page) -> None:
    """Seen on PostHog: the tiles had no ref, so the AI remembered a whole-page read and
    the trail's answer became five thousand characters with the number buried inside."""
    result = call(mcp_server, "dejo_read", kind="page_text", remember=True, intent="the number")
    assert "warning" in result
    assert "CSS selector" in result["warning"]


def test_an_ordinary_whole_page_read_is_not_warned_about(mcp_server, on_the_page) -> None:
    """Looking around is fine. It is only remembering it that makes a poor trail."""
    assert "warning" not in call(mcp_server, "dejo_read", kind="page_text")


def test_the_kinds_list_steers_away_from_the_whole_page(described) -> None:
    """The AI reads the kinds list when it chooses, not the argument notes underneath."""
    text = described["dejo_read"]
    assert "ALMOST NEVER THE RIGHT ANSWER" in text
    assert "THE ONE YOU USUALLY WANT" in text


class TestABrowserSwapIsSaidOutLoud:
    """Dejo may open its profile with the other browser when the owner refuses it.

    That is the difference between a working browser and a dead one, but it can cost a
    sign-in. The engine records the swap and cannot print; something has to say it.
    """

    @staticmethod
    def _swapped(mcp_server, note="Chrome would not open Dejo's browser profile"):
        tools = mcp_server.dejo_tools
        tools.worker.browser = type("FakeBrowser", (), {"profile_note": note})()
        return tools

    def test_the_note_is_handed_over(self, mcp_server) -> None:
        tools = self._swapped(mcp_server)

        assert "Chrome would not open" in (tools.take_profile_note() or "")

    def test_and_only_once(self, mcp_server) -> None:
        """Telling somebody is useful. Repeating it on every call is noise."""
        tools = self._swapped(mcp_server)
        tools.take_profile_note()

        assert tools.take_profile_note() is None

    def test_a_normal_open_says_nothing(self, mcp_server) -> None:
        tools = self._swapped(mcp_server, note=None)

        assert tools.take_profile_note() is None
