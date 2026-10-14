"""The core promises, driven through the MCP tools themselves.

A host AI only ever sees tool names, descriptions and results. So these tests call the
tools the same way Claude Code would, and check the thing that actually decides whether
this works in practice: does each result tell the AI what to do next?
"""

from __future__ import annotations

from dejo.browser import domain_of

from helpers import call, ref_named, teach_the_site


class TestAnUnknownSite:
    """What a host AI meets first, and how it is told what to do about it."""

    def test_dejo_run_says_it_does_not_know_the_site(self, mcp_server, demo_server):
        result = call(mcp_server, "dejo_run", site=demo_server)

        assert result["ok"] is False
        assert result["known"] is False

    def test_and_tells_the_ai_exactly_how_to_fix_that(self, mcp_server, demo_server):
        result = call(mcp_server, "dejo_run", site=demo_server)

        nudge = result["next"]
        assert "dejo_act" in nudge
        assert "dejo_save" in nudge

    def test_sites_starts_empty(self, mcp_server):
        assert call(mcp_server, "dejo_sites")["count"] == 0


class TestLearningThroughTheTools:
    """Finish line part 1: the AI explores through Dejo and the site gets learned."""

    def test_the_site_is_learned_and_reported_back(self, mcp_server, demo_server):
        saved = teach_the_site(mcp_server, demo_server)

        assert saved["ok"] is True
        assert saved["steps"] == 6
        assert "one dejo_run call" in saved["message"]

    def test_look_returns_controls_not_a_page_dump(self, mcp_server, demo_server):
        call(
            mcp_server,
            "dejo_act",
            intent="open the billing portal",
            action="goto",
            value=f"{demo_server}/",
        )

        page = call(mcp_server, "dejo_read", kind="page")

        assert page["ok"] is True
        assert {"Email", "Password", "Sign in"} <= {e["name"] for e in page["elements"]}
        assert len(str(page)) < 2000, "a look() must stay cheap to read"

    def test_the_site_now_shows_up_in_sites(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        listed = call(mcp_server, "dejo_sites")
        assert listed["count"] == 1
        assert listed["sites"][0]["steps"] == 6

    def test_show_explains_the_trail_in_plain_words(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        shown = call(mcp_server, "dejo_show", site=demo_server)

        intents = [step["intent"] for step in shown["playbook"]["steps"]]
        assert "sign in" in intents
        assert "download the PDF" in intents


class TestTheWarmCall:
    """Finish line part 2: one call, no thinking, no model."""

    def test_one_call_does_the_whole_task(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        result = call(mcp_server, "dejo_run", site=demo_server, url=f"{demo_server}/")

        assert result["ok"] is True
        assert result["steps_replayed"] == 6
        assert result["model_calls"] == 0
        assert result["pages_read"] == 0

    def test_it_reports_where_the_file_was_saved(self, mcp_server, demo_server):
        """The AI has to be able to tell the user where the invoice actually is."""
        from pathlib import Path

        teach_the_site(mcp_server, demo_server)

        result = call(mcp_server, "dejo_run", site=demo_server, url=f"{demo_server}/")

        assert result["saved_files"], "a download task must report a path"
        assert Path(result["saved_files"][0]).is_file()

    def test_it_works_from_a_second_server_on_the_same_memory(
        self, mcp_server, demo_server, tmp_path
    ):
        """The fresh-session beat: a brand new server process reads the same trail.

        This is the closest a test can get to "quit Claude Code and open it again".
        """
        from dejo_mcp.server import build_server

        teach_the_site(mcp_server, demo_server)
        db = mcp_server.dejo_tools.store  # same database, brand new server object
        del db

        # profile="" like every other test. Without it this reached into the real
        # signed-in profile, which only worked while a silent fallback let a second
        # process share one Chrome profile — and that fallback was signing users out.
        second = build_server(
            db_path=str(tmp_path / "memory.db"),
            headless=True,
            downloads=str(tmp_path / "downloads"),
            profile="",
            profiles_dir=str(tmp_path / "profiles"),
        )
        try:
            result = call(second, "dejo_run", site=demo_server, url=f"{demo_server}/")
        finally:
            second.dejo_tools.close()

        assert result["ok"] is True
        assert result["steps_replayed"] == 6


class TestTheSiteChanging:
    """Finish line part 3: one step breaks, the AI fixes only that step."""

    def test_a_cosmetic_redesign_is_survived_silently(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        result = call(mcp_server, "dejo_run", site=demo_server, url=f"{demo_server}/?variant=c")

        assert result["ok"] is True, "no repair should be needed for a cosmetic change"
        assert result["model_calls"] == 0

    def test_a_real_break_hands_back_one_step(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        result = call(mcp_server, "dejo_run", site=demo_server, url=f"{demo_server}/?variant=b")

        assert result["needs_repair"] is True
        assert result["steps_replayed"] == 5, "the five working steps still ran"
        assert result["repair"]["intent"] == "download the PDF"
        assert "one step broke" in result["next"] or "one step" in result["next"]

    def test_the_repair_result_tells_the_ai_what_to_do(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        result = call(mcp_server, "dejo_run", site=demo_server, url=f"{demo_server}/?variant=b")

        assert "dejo_repair" in result["next"]
        assert any(c["name"] == "Get PDF" for c in result["repair"]["candidates"])

    def test_the_ai_repairs_it_and_the_next_run_is_clean(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        broken = call(mcp_server, "dejo_run", site=demo_server, url=f"{demo_server}/?variant=b")

        # This is the host AI's whole contribution: pick the right control.
        chosen = next(c for c in broken["repair"]["candidates"] if c["name"] == "Get PDF")
        fixed = call(
            mcp_server,
            "dejo_repair",
            site=demo_server,
            step_index=broken["repair"]["step_index"],
            css=chosen["css"],
        )
        assert fixed["ok"] is True

        again = call(mcp_server, "dejo_run", site=demo_server, url=f"{demo_server}/?variant=b")
        assert again["ok"] is True
        assert again["steps_replayed"] == 6
        assert again["model_calls"] == 0


class TestTheGateThroughMCP:
    """Finish line part 4: forget from inside any MCP client, and the fast path is gone."""

    def test_forget_then_run_reports_it_knows_nothing(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        assert call(mcp_server, "dejo_run", site=demo_server, url=f"{demo_server}/")["ok"]

        forgotten = call(mcp_server, "dejo_forget", site=demo_server)
        assert forgotten["ok"] is True

        after = call(mcp_server, "dejo_run", site=demo_server, url=f"{demo_server}/")
        assert after["known"] is False
        assert call(mcp_server, "dejo_sites")["count"] == 0

    def test_forgetting_an_unknown_site_is_honest_about_it(self, mcp_server):
        result = call(mcp_server, "dejo_forget", site="never-visited.example.com")

        assert result["ok"] is False
        assert "nothing was remembered" in result["message"]


class TestSiteFacts:
    """Facts that outlive a redesign, written by the AI and handed back when it matters."""

    def test_a_fact_is_saved_and_read_back(self, mcp_server, demo_server):
        saved = call(
            mcp_server,
            "dejo_note",
            site=demo_server,
            fact="locks you out after five wrong passwords",
        )

        assert saved["ok"] is True
        assert "locks you out after five wrong passwords" in saved["known_facts"]

    def test_facts_add_up_across_calls(self, mcp_server, demo_server):
        call(mcp_server, "dejo_note", site=demo_server, fact="the export takes two minutes")
        second = call(
            mcp_server,
            "dejo_note",
            site=demo_server,
            needs_2fa=True,
            account="finance@acme.com",
        )

        assert len(second["known_facts"]) >= 3, "nothing may overwrite what came before"

    def test_calling_it_with_nothing_says_so(self, mcp_server, demo_server):
        result = call(mcp_server, "dejo_note", site=demo_server)

        assert result["ok"] is False
        assert "at least one of" in result["error"]

    def test_facts_come_back_when_the_site_is_unknown(self, mcp_server, demo_server):
        """The point of writing them: the next AI to explore this site starts informed."""
        call(mcp_server, "dejo_note", site=demo_server, needs_login=True)

        result = call(mcp_server, "dejo_run", site=demo_server)

        assert result["known"] is False
        assert any("login" in fact for fact in result["site_facts"])
        assert "site_facts" in result["next"]

    def test_an_unknown_site_with_no_facts_is_told_to_write_some(self, mcp_server, demo_server):
        result = call(mcp_server, "dejo_run", site=demo_server)

        assert result["site_facts"] == []
        assert "dejo_note" in result["next"]

    def test_show_includes_the_facts(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        call(mcp_server, "dejo_note", site=demo_server, fact="invoices appear after the 3rd")

        shown = call(mcp_server, "dejo_show", site=demo_server)

        assert "invoices appear after the 3rd" in shown["site_facts"]

    def test_forgetting_a_site_takes_the_facts_with_it(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        call(mcp_server, "dejo_note", site=demo_server, needs_login=True)

        call(mcp_server, "dejo_forget", site=demo_server)

        assert call(mcp_server, "dejo_run", site=demo_server)["site_facts"] == []


class TestSigningIn:
    """Some logins cannot be automated and should not be — Google, SSO, one-time codes.

    The answer is not to get cleverer at typing passwords. It is to open a real window,
    let the person sign in themselves, and keep the session afterwards.
    """

    def test_login_done_without_login_first_says_so(self, mcp_server, demo_server):
        result = call(mcp_server, "dejo_login_done", site=demo_server)

        assert result["ok"] is False
        assert "call dejo_login first" in result["error"]

    def test_dejo_login_tells_the_ai_to_hand_over_to_the_user(self, mcp_server):
        import asyncio

        tools = {t.name: t.description or "" for t in asyncio.run(mcp_server.list_tools())}
        login = tools["dejo_login"]

        assert "USER" in login, "it must be clear the person signs in, not the AI"
        assert "Google" in login
        assert "never guess a password" in login

    def test_login_done_makes_clear_nothing_secret_was_kept(self, mcp_server):
        import asyncio

        tools = {t.name: t.description or "" for t in asyncio.run(mcp_server.list_tools())}

        assert "no password, no code" in tools["dejo_login_done"]

    def test_the_instructions_forbid_automating_an_sso_button(self, mcp_server):
        instructions = mcp_server.instructions or ""

        assert "never guess" in instructions
        assert "dejo_login" in instructions
        assert "only ever have to do that once per site" in instructions


class TestToolDescriptions:
    """The descriptions ARE the product here — they are all the host AI gets to choose from.

    A host AI that reaches for dejo_act first would explore a site it already knows,
    which would quietly destroy the entire value of the project. So the wording that
    prevents that is pinned by tests.
    """

    def test_dejo_run_is_named_first_in_the_server_instructions(self, mcp_server):
        instructions = mcp_server.instructions or ""

        assert "dejo_run FIRST" in instructions
        assert instructions.index("dejo_run") < instructions.index("dejo_act")

    def test_the_instructions_rule_out_curl_and_friends(self, mcp_server):
        """The real failure seen in testing: a host AI reached for curl and ignored Dejo.

        A description that only ranks Dejo's own tools against each other loses to the
        shell, because the shell is always right there. So the competition has to be named.
        """
        instructions = (mcp_server.instructions or "").lower()

        for shortcut in ("curl", "wget", "fetch", "shell command"):
            assert shortcut in instructions, f"{shortcut} is not ruled out"

    def test_dejo_run_claims_every_website_task_unconditionally(self, mcp_server):
        """It must not read as conditional.

        The first wording said "a website that Dejo already knows". A host AI scanning
        the tool list cannot evaluate that condition, so it skipped the tool and used curl
        instead. The trigger has to be something the AI can match on sight.
        """
        import asyncio

        tools = {t.name: t.description or "" for t in asyncio.run(mcp_server.list_tools())}
        summary = tools["dejo_run"]

        opener = summary.splitlines()[0]

        assert "ANY WEBSITE TASK" in summary
        assert "already knows" not in opener, "the opening line must not be a condition"
        assert "curl" in summary, "the shell shortcut has to be named to be ruled out"

    def test_the_cold_tools_say_they_are_only_for_unknown_sites(self, mcp_server):
        import asyncio

        tools = {t.name: t.description or "" for t in asyncio.run(mcp_server.list_tools())}

        assert "not known" in tools["dejo_act"]
        assert "dejo_run FIRST" in tools["dejo_act"]
        assert "never needs exploring again" in tools["dejo_save"]

    def test_dejo_note_says_when_to_call_it(self, mcp_server):
        import asyncio

        tools = {t.name: t.description or "" for t in asyncio.run(mcp_server.list_tools())}
        note = tools["dejo_note"]

        assert "not a step" in note, "it must be clear this is for facts, not actions"
        assert "ADDS" in note, "the AI has to know it can call this many times"

    def test_every_tool_has_a_description(self, mcp_server):
        import asyncio

        for tool in asyncio.run(mcp_server.list_tools()):
            assert tool.description, f"{tool.name} has no description — the AI is blind to it"


class TestErrorsAreReadable:
    def test_a_bad_action_returns_a_message_not_a_stack_trace(self, mcp_server, demo_server):
        call(
            mcp_server,
            "dejo_act",
            intent="open the billing portal",
            action="goto",
            value=f"{demo_server}/",
        )

        result = call(mcp_server, "dejo_act", intent="do something odd", action="jump")

        assert result["ok"] is False
        assert "Traceback" not in result["error"]

    def test_saving_nothing_explains_itself(self, mcp_server):
        result = call(mcp_server, "dejo_save", task="nothing happened")

        assert result["ok"] is False
        assert "trace is empty" in result["error"]


class TestDomainKeying:
    def test_a_full_url_and_a_bare_domain_mean_the_same_site(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        by_url = call(mcp_server, "dejo_show", site=demo_server)
        by_domain = call(mcp_server, "dejo_show", site=domain_of(demo_server))

        assert by_url["site"] == by_domain["site"]


class TestATrailThatAnswersNothing:
    """Saying nothing here costs the caller full price on every future run.

    Measured 2026-09-05 on pypi.org: the model answered from dejo_read(kind="page") — the
    control list — so the saved trail had no read in it. Ten runs, ten page readings, and
    every reply said "ok".
    """

    def test_the_reply_says_so_plainly(self, mcp_server, demo_server):
        call(mcp_server, "dejo_act", intent="open it", action="goto", value=f"{demo_server}/")
        call(mcp_server, "dejo_read", kind="page")

        saved = call(mcp_server, "dejo_save", task="just look at the page")

        assert saved["ok"] is True
        assert "answers NOTHING" in saved["warning"]
        assert "dejo_read(kind='text'" in saved["warning"]

    def test_and_a_trail_that_does_answer_is_not_nagged(self, mcp_server, demo_server):
        call(mcp_server, "dejo_act", intent="open it", action="goto", value=f"{demo_server}/")
        page = call(mcp_server, "dejo_read", kind="page")
        call(
            mcp_server,
            "dejo_read",
            kind="text",
            ref=ref_named(page, "Sign in"),
            remember=True,
            intent="the button text",
        )

        saved = call(mcp_server, "dejo_save", task="read the button")

        assert "warning" not in saved
        assert "note" not in saved

    def test_and_replaying_it_does_not_look_like_a_finished_answer(self, mcp_server, demo_server):
        """The reply that cost pypi.org ten page readings in ten runs.

        `ok: True` with an empty `answers` reads as "done" to a caller, so it went and read
        the page itself — and did so again on every later run, because nothing in the reply
        ever said why it was empty or how to fix it.
        """
        call(mcp_server, "dejo_act", intent="open it", action="goto", value=f"{demo_server}/")
        call(mcp_server, "dejo_read", kind="page")
        call(mcp_server, "dejo_save", task="just look at the page")

        again = call(mcp_server, "dejo_run", site=demo_server, task="just look at the page")

        assert again["ok"] is True
        assert again["answers"] == {}
        assert "reads no value" in again["next"]
        assert "dejo_save again" in again["next"]

    def test_but_a_trail_that_answers_is_told_to_stop(self, mcp_server, demo_server):
        """The opposite mistake would be worse: telling a caller with the answer in hand to
        go and read the page."""
        call(mcp_server, "dejo_act", intent="open it", action="goto", value=f"{demo_server}/")
        page = call(mcp_server, "dejo_read", kind="page")
        call(
            mcp_server,
            "dejo_read",
            kind="text",
            ref=ref_named(page, "Sign in"),
            remember=True,
            intent="the button text",
        )
        call(mcp_server, "dejo_save", task="read the button")

        done = call(mcp_server, "dejo_run", site=demo_server, task="read the button")

        assert done["answers"]
        assert "report it and stop" in done["next"]
        assert "reads no value" not in done["next"]

    def test_but_the_caller_can_hand_over_the_answer_it_already_has(self, mcp_server, demo_server):
        """The fix for the case no wording closed: the read was refused for ambiguity, the
        caller read the value out of the refusal, and the trail would have saved empty."""
        call(
            mcp_server,
            "dejo_act",
            intent="open payments",
            action="goto",
            value=f"{demo_server}/payments",
        )

        saved = call(mcp_server, "dejo_save", task="what is the next charge", answer="₹ 18,400")

        assert "warning" not in saved
        assert "stored where it lives" in saved["note"]

        again = call(mcp_server, "dejo_run", site=demo_server, task="what is the next charge")
        assert again["answers"] == {"what is the next charge": "₹ 18,400"}

    def test_and_a_value_that_is_not_on_the_page_is_refused_out_loud(self, mcp_server, demo_server):
        call(
            mcp_server,
            "dejo_act",
            intent="open payments",
            action="goto",
            value=f"{demo_server}/payments",
        )

        saved = call(mcp_server, "dejo_save", task="what is the next charge", answer="£999.99")

        assert "matches no element" in saved["warning"]
