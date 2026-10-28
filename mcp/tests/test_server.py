"""The core promises, driven through the MCP tools themselves.

A host AI only ever sees tool names, descriptions and replies. So these tests call the tools
the way Claude Code would, and check what decides whether this works in practice: does each
reply tell the AI what to do next, in as few turns as possible?
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from dejo.browser import domain_of

from helpers import TASK, call, ref_named, result, teach_the_site


def descriptions(server) -> dict[str, str]:
    return {t.name: t.description or "" for t in asyncio.run(server.list_tools())}


class TestAnUnknownSite:
    """What a host AI meets first. The "not known" reply and the first look are one turn."""

    def test_a_new_task_opens_the_page_and_shows_it(self, mcp_server, demo_server):
        first = call(mcp_server, "dejo_run", site=demo_server, task=TASK, url=f"{demo_server}/")

        assert first.startswith(f'new task "{TASK}"')
        assert 'e10 button "Sign in"' in first or 'button "Sign in"' in first
        assert "send steps" in first

    def test_the_first_look_waits_for_a_client_side_app_to_draw(self, mcp_server, demo_server):
        """tinylaunch.com: the first look showed a signed-out shell; the next one, the page."""
        said = call(
            mcp_server, "dejo_run", site=demo_server, task="t", url=f"{demo_server}/app/dashboard"
        )
        assert "Dejo · Waiting for approval" in said, said

    def test_the_first_look_stays_cheap_to_read(self, mcp_server, demo_server):
        first = call(mcp_server, "dejo_run", site=demo_server, task=TASK, url=f"{demo_server}/")
        assert len(first) < 2000, "a first look must stay cheap to read"

    def test_sites_starts_empty(self, mcp_server):
        assert "no trails yet" in call(mcp_server, "dejo_memory", what="sites")


class TestLearningThroughTheTools:
    def test_the_site_is_learned_in_one_call_of_steps(self, mcp_server, demo_server):
        saved = teach_the_site(mcp_server, demo_server)

        assert saved.startswith(f'saved "{TASK}"')
        assert "6 steps" in saved
        assert "one dejo_run call" in saved

    def test_the_site_now_shows_up_in_sites(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        assert "6 steps" in call(mcp_server, "dejo_memory", what="sites")

    def test_show_explains_the_trail_in_plain_words(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        shown = call(mcp_server, "dejo_memory", what="show", site=demo_server)

        assert 'click button "Sign in"' in shown
        assert 'click link "Download"' in shown

    def test_a_typed_password_never_reaches_memory(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        shown = call(mcp_server, "dejo_memory", what="show", site=demo_server)
        assert "hunter2" not in shown


class TestTheWarmCall:
    """One call, no thinking, no model."""

    def test_one_call_does_the_whole_task(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        done = call(mcp_server, "dejo_run", site=demo_server, task=TASK, url=f"{demo_server}/")

        assert done.startswith(f'done: "{TASK}"')
        assert "6 steps replayed" in done
        assert "no page reading" in done

    def test_it_reports_where_the_file_was_saved(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        done = call(mcp_server, "dejo_run", site=demo_server, task=TASK, url=f"{demo_server}/")

        saved = next(line for line in done.splitlines() if line.startswith("saved file: "))
        assert Path(saved.removeprefix("saved file: ")).is_file()

    def test_it_works_from_a_second_server_on_the_same_memory(
        self, mcp_server, demo_server, tmp_path
    ):
        """The closest a test gets to "quit Claude Code and open it again"."""
        from dejo_mcp.server import build_server

        teach_the_site(mcp_server, demo_server)
        second = build_server(
            db_path=str(tmp_path / "memory.db"),
            headless=True,
            downloads=str(tmp_path / "downloads"),
            profile="",
            profiles_dir=str(tmp_path / "profiles"),
        )
        try:
            done = call(second, "dejo_run", site=demo_server, task=TASK, url=f"{demo_server}/")
        finally:
            second.dejo_tools.close()

        assert "6 steps replayed" in done


class TestTheSiteChanging:
    """One step breaks; the AI fixes only that step, in one call."""

    def test_a_cosmetic_redesign_is_survived_silently(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        done = call(
            mcp_server, "dejo_run", site=demo_server, task=TASK, url=f"{demo_server}/?variant=c"
        )

        assert done.startswith("done:"), "no repair should be needed for a cosmetic change"

    def test_a_real_break_hands_back_one_step_and_the_page(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        broke = call(
            mcp_server, "dejo_run", site=demo_server, task=TASK, url=f"{demo_server}/?variant=b"
        )

        assert broke.startswith('broke at step 6 of 6: click link "Download"')
        assert "steps 1-5 passed and are kept" in broke
        assert 'link "Get PDF"' in broke, "the page where it broke must be shown"

    def test_the_ai_fixes_it_in_one_call_and_the_next_run_is_clean(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        call(mcp_server, "dejo_run", site=demo_server, task=TASK, url=f"{demo_server}/?variant=b")

        fixed = call(
            mcp_server, "dejo_run", site=demo_server, task=TASK, steps='click link "Get PDF"'
        )
        assert fixed.startswith("repaired step 6 of 6"), fixed

        again = call(
            mcp_server, "dejo_run", site=demo_server, task=TASK, url=f"{demo_server}/?variant=b"
        )
        assert "6 steps replayed" in again

    def test_a_fix_in_the_middle_runs_the_rest_in_the_same_call(self, mcp_server, demo_server):
        """Before, a fix replaced every step from the broken one on, or cost a second replay
        call. One line now repairs the step and Dejo walks the rest itself."""
        task = "download the invoice and say its month"
        call(
            mcp_server,
            "dejo_run",
            site=demo_server,
            task=task,
            url=f"{demo_server}/",
            steps='fill label "Email" "finance@acme.com"\nfill label "Password" "hunter2"\n'
            'click button "Sign in"\nclick link "September 2026"\nclick link "Download"\n'
            'read css "h1" as month',
        )
        call(mcp_server, "dejo_run", site=demo_server, task=task)

        broke = call(
            mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/?variant=b"
        )
        assert broke.startswith("broke at step 6 of 7"), broke
        assert "runs steps 7-7 itself" in broke

        fixed = call(
            mcp_server, "dejo_run", site=demo_server, task=task, steps='click link "Get PDF"'
        )
        assert fixed.startswith("repaired step 6 of 7"), fixed
        assert "done: steps 7-7 replayed" in fixed
        assert "month = September 2026" in fixed


class TestTheGateThroughMCP:
    """Forget from inside any MCP client, and the fast path is gone."""

    def test_forget_then_run_starts_from_zero(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        assert call(mcp_server, "dejo_run", site=demo_server, task=TASK).startswith("done:")

        forgotten = call(mcp_server, "dejo_manage", do="forget", site=demo_server)
        assert forgotten.startswith("forgot ")

        after = call(mcp_server, "dejo_run", site=demo_server, task=TASK, url=f"{demo_server}/")
        assert after.startswith("new task")
        assert "no trails yet" in call(mcp_server, "dejo_memory", what="sites")

    def test_forgetting_an_unknown_site_is_honest_about_it(self, mcp_server):
        said = call(mcp_server, "dejo_manage", do="forget", site="never-visited.example.com")
        assert "nothing was remembered" in said

    def test_forgetting_one_task_keeps_the_rest(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        said = call(mcp_server, "dejo_manage", do="forget", site=demo_server, task=TASK)
        assert said.startswith(f'forgot "{TASK}"')


class TestSiteFacts:
    """Facts that outlive a redesign, written by the AI and handed back when it matters."""

    def test_a_fact_is_saved_and_read_back(self, mcp_server, demo_server):
        saved = call(
            mcp_server,
            "dejo_manage",
            do="note",
            site=demo_server,
            text="locks you out after five wrong passwords",
        )
        assert "locks you out after five wrong passwords" in saved

    def test_facts_add_up_across_calls(self, mcp_server, demo_server):
        call(
            mcp_server, "dejo_manage", do="note", site=demo_server, text="export takes two minutes"
        )
        second = call(mcp_server, "dejo_manage", do="note", site=demo_server, text="use finance")
        assert "export takes two minutes" in second and "use finance" in second

    def test_a_note_with_no_text_says_so(self, mcp_server, demo_server):
        said = result(mcp_server, "dejo_manage", do="note", site=demo_server)
        assert said.isError
        assert "needs text" in said.content[0].text

    def test_facts_come_back_on_a_new_task(self, mcp_server, demo_server):
        """The point of writing them: the next AI to learn this site starts informed."""
        call(mcp_server, "dejo_manage", do="note", site=demo_server, text="needs the VPN")
        first = call(mcp_server, "dejo_run", site=demo_server, task=TASK, url=f"{demo_server}/")
        assert "site facts: " in first and "needs the VPN" in first

    def test_show_includes_the_facts(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        call(mcp_server, "dejo_manage", do="note", site=demo_server, text="invoices after the 3rd")
        assert "invoices after the 3rd" in call(
            mcp_server, "dejo_memory", what="show", site=demo_server
        )

    def test_forgetting_a_site_takes_the_facts_with_it(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)
        call(mcp_server, "dejo_manage", do="note", site=demo_server, text="needs the VPN")
        call(mcp_server, "dejo_manage", do="forget", site=demo_server)

        first = call(mcp_server, "dejo_run", site=demo_server, task=TASK, url=f"{demo_server}/")
        assert "needs the VPN" not in first


class TestSigningIn:
    """Some logins cannot be automated and should not be: Google, SSO, one-time codes."""

    def test_done_without_a_window_first_says_so(self, mcp_server, demo_server):
        said = result(mcp_server, "dejo_login", site=demo_server, done=True)
        assert said.isError
        assert "call dejo_login first" in said.content[0].text

    def test_the_login_tool_hands_over_to_the_user(self, mcp_server):
        login = descriptions(mcp_server)["dejo_login"]

        assert "USER" in login, "it must be clear the person signs in, not the AI"
        assert "Google" in login
        assert "never type a password you were not given" in login


class TestToolDescriptions:
    """The descriptions ARE the product: they are all the host AI gets to choose from."""

    def test_five_tools_in_a_fixed_order(self, mcp_server):
        assert list(descriptions(mcp_server)) == [
            "dejo_run",
            "dejo_login",
            "dejo_profile",
            "dejo_memory",
            "dejo_manage",
        ]

    def test_the_instructions_name_dejo_run_and_rule_out_the_shortcuts(self, mcp_server):
        """Seen in testing: a host AI reached for curl and ignored Dejo. The competition has
        to be named to be ruled out."""
        instructions = mcp_server.instructions
        assert "dejo_run for ANY website task" in instructions
        for shortcut in ("curl", "fetch", "WebFetch"):
            assert shortcut in instructions

    def test_dejo_run_claims_every_website_task_unconditionally(self, mcp_server):
        """The first wording said "a website that Dejo already knows". A host AI cannot
        evaluate that while scanning a tool list, so it used curl instead."""
        opener = descriptions(mcp_server)["dejo_run"].splitlines()[0]
        assert opener.startswith("Use for ANY website task")
        assert "already knows" not in opener

    def test_every_tool_has_a_description(self, mcp_server):
        for name, text in descriptions(mcp_server).items():
            assert text, f"{name} has no description: the AI is blind to it"


class TestErrorsAreReadable:
    def test_a_bad_step_is_refused_before_anything_runs(self, mcp_server, demo_server):
        said = result(mcp_server, "dejo_run", site=demo_server, task="x", steps="jump e4")

        assert said.isError
        text = said.content[0].text
        assert text.startswith("nothing ran: line 1: no verb 'jump'")
        assert "Traceback" not in text

    def test_a_missing_task_is_refused_by_the_schema(self, mcp_server, demo_server):
        said = result(mcp_server, "dejo_run", site=demo_server)
        assert said.isError
        assert "'task' is a required property" in said.content[0].text


class TestDomainKeying:
    def test_a_full_url_and_a_bare_domain_mean_the_same_site(self, mcp_server, demo_server):
        teach_the_site(mcp_server, demo_server)

        by_url = call(mcp_server, "dejo_memory", what="show", site=demo_server)
        by_domain = call(mcp_server, "dejo_memory", what="show", site=domain_of(demo_server))

        assert by_url == by_domain


class TestATrailThatAnswersNothing:
    """Saying nothing here costs the caller full price on every future run.

    Measured 2026-09-05 on pypi.org: a trail saved with no read in it; ten runs, ten page
    readings, and every reply said "ok"."""

    def test_steps_with_no_read_are_not_saved_and_say_why(self, mcp_server, demo_server):
        task = "look at the sign in page"
        call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/")

        said = call(mcp_server, "dejo_run", site=demo_server, task=task, steps="look")

        assert not said.startswith("saved")

    def test_a_task_that_reads_nothing_can_be_saved_on_purpose(self, mcp_server, demo_server):
        task = "open the sign in page"
        call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/")

        saved = call(mcp_server, "dejo_run", site=demo_server, task=task, done=True)
        assert saved.startswith(f'saved "{task}"')

        again = call(mcp_server, "dejo_run", site=demo_server, task=task)
        assert "the trail reads no value" in again
        assert "It is added to this trail" in again

    def test_a_trail_that_answers_is_told_to_stop(self, mcp_server, demo_server):
        task = "read the next charge"
        call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/payments")
        saved = call(
            mcp_server,
            "dejo_run",
            site=demo_server,
            task=task,
            steps='read css "#next-charge" as charge',
        )
        assert "charge = ₹ 18,400" in saved

        done = call(mcp_server, "dejo_run", site=demo_server, task=task)
        assert "charge = ₹ 18,400" in done
        assert "report the answer exactly as read and stop" in done
        assert "reads no value" not in done

    def test_a_read_added_after_a_replay_extends_the_trail(self, mcp_server, demo_server):
        """A replayed trail with no read, plus one read line, must keep every old step."""
        task = "open the payments page"
        call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/payments")
        call(mcp_server, "dejo_run", site=demo_server, task=task, done=True)
        call(mcp_server, "dejo_run", site=demo_server, task=task)

        extended = call(
            mcp_server, "dejo_run", site=demo_server, task=task, steps='read css "#cycle" as cycle'
        )

        assert extended.startswith(f'saved "{task}"') and "2 steps" in extended


def test_steps_sent_with_a_url_on_the_first_call_start_there(mcp_server, demo_server):
    """Seen in the 21 Oct benchmark: url and steps in one call, and the url was ignored."""
    said = call(
        mcp_server,
        "dejo_run",
        site=demo_server,
        task="read the next charge",
        url=f"{demo_server}/payments",
        steps='read css "#next-charge" as charge',
    )
    assert "charge = ₹ 18,400" in said


def test_a_url_the_trail_cannot_start_from_falls_back_to_its_own_start(mcp_server, demo_server):
    """Seen 21 Oct: a trail that starts on the Issues page was replayed with the repo's front
    page as url, so it stopped, and the agent read a different count off the front page."""
    task = "read the next charge"
    call(
        mcp_server,
        "dejo_run",
        site=demo_server,
        task=task,
        url=f"{demo_server}/payments",
        steps='read css "#next-charge" as charge',
    )

    done = call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/")

    assert done.startswith(f'done: "{task}"'), done
    assert "charge = ₹ 18,400" in done


def test_an_option_picked_by_its_words_is_learned_and_replayed(mcp_server, demo_server):
    """The view prints a dropdown's words, so that is what an agent sends; the value behind
    "September" is `sep`. A wrong option is refused at once with the real ones named."""
    task = "show the September statements"
    url = f"{demo_server}/preferences"
    wrong = call(
        mcp_server,
        "dejo_run",
        site=demo_server,
        task=task,
        url=url,
        steps='select label "Statement month" "Octember"',
    )
    assert '"January", "September"' in wrong and "Timeout" not in wrong

    learned = call(
        mcp_server,
        "dejo_run",
        site=demo_server,
        task=task,
        url=url,
        steps='select label "Statement month" "September"\nread css "#shown" as month',
    )
    assert learned.startswith(f'saved "{task}"') and "month = September" in learned

    replayed = call(mcp_server, "dejo_run", site=demo_server, task=task)
    assert "month = September" in replayed, replayed


def test_what_a_js_line_returns_is_in_the_reply(mcp_server, demo_server):
    """Agents wrote the result into document.title to see it at all (23 Oct)."""
    task = "count the statement months"
    call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/preferences")
    said = call(
        mcp_server,
        "dejo_run",
        site=demo_server,
        task=task,
        steps='js "() => [...document.querySelectorAll(`option`)].map(o => o.label)"',
    )
    assert 'js returned: ["Choose one", "January", "September"]' in said


def test_a_sent_form_is_shown_after_the_site_answers(mcp_server, demo_server):
    """23 Oct: the reply came while the form still said "Sending...", and only the next call
    showed it had worked."""
    task = "send a note"
    call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/contact")
    said = call(
        mcp_server,
        "dejo_run",
        site=demo_server,
        task=task,
        steps='fill label "Note" "hello"\nclick! button "Send note"',
    )
    assert "Note sent. Thank you!" in said, said
    assert "Sending..." not in said


def test_a_cookie_banner_not_shown_again_does_not_break_the_replay(mcp_server, demo_server):
    """Bench T07: the banner was accepted while learning, so the very next replay broke at
    the click that cleared it."""
    task = "read the headline"
    call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/news")
    call(
        mcp_server,
        "dejo_run",
        site=demo_server,
        task=task,
        steps='click button "Accept cookies"\nread css "#headline" as headline',
    )

    said = call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/news")

    assert said.startswith('done: "read the headline"'), said
    assert "headline = Rates hold for September" in said
    assert 'skipped step 2 (click button "Accept cookies")' in said


def test_a_wrong_answer_says_how_to_replace_the_trail(mcp_server, demo_server):
    """Bench T12: the saved read answered the wrong thing, and the agent re-asked 28 times in
    other words, each time getting the same trail back."""
    task = "the next charge"
    call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/payments")
    call(mcp_server, "dejo_run", site=demo_server, task=task, steps='read css "#card" as charge')
    asked = "how much is the next charge"

    replayed = call(mcp_server, "dejo_run", site=demo_server, task=asked)
    assert "charge = Visa ending 4242" in replayed
    assert "first line is restart" in replayed

    call(
        mcp_server,
        "dejo_run",
        site=demo_server,
        task=asked,
        steps='restart\nread css "#next-charge" as charge',
    )
    again = call(mcp_server, "dejo_run", site=demo_server, task=task)
    assert "charge = ₹ 18,400" in again, again


def test_a_toast_shown_after_a_sent_form_is_in_the_reply(mcp_server, demo_server):
    """mcpserverhub.net: the button went "Loading...", the form emptied itself, and the toast
    that said it worked was gone before the reply was written."""
    task = "list my server"
    call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/listing")
    said = call(
        mcp_server,
        "dejo_run",
        site=demo_server,
        task=task,
        steps='fill label "Server" "dejo"\nclick! button "List it"',
    )
    assert 'the page said: "Thanks! Your server is in the queue."' in said, said


def test_a_sent_step_whose_request_failed_says_so(mcp_server, demo_server):
    """mcpserver.dev: after `click! Submit` the dialog stayed open, with no message and no
    toast, and nothing in the reply said whether it had worked."""
    task = "send for review"
    call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/listing")
    said = call(
        mcp_server,
        "dejo_run",
        site=demo_server,
        task=task,
        steps='click! button "Send for review"',
    )
    assert "no message appeared" in said, said
    assert f"requests that failed: 502 POST {demo_server}/listing/review" in said


def test_a_form_the_browser_held_back_says_which_fields(mcp_server, demo_server):
    """A submit that the browser stopped with "Please fill out this field" looked like
    success: the bubble is not on the page, and nothing else changed."""
    task = "list my server"
    call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/listing")
    held = call(
        mcp_server, "dejo_run", site=demo_server, task=task, steps='click! button "List it"'
    )
    assert "the browser did not send the form" in held, held
    assert "Server: Please fill out this field." in held

    sent = call(
        mcp_server,
        "dejo_run",
        site=demo_server,
        task=task,
        steps='fill label "Server" "dejo"\nclick! button "List it"',
    )
    assert "Thanks! Your server is in the queue." in sent, "a held-back press is not one that ran"


def test_a_tab_a_click_opened_is_named_in_the_reply(mcp_server, demo_server):
    """fazier.com: "Continue with Google" opened a new tab, and the reply showed the old page
    as if nothing had happened."""
    task = "join"
    call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/continue")
    said = call(
        mcp_server,
        "dejo_run",
        site=demo_server,
        task=task,
        steps='click button "Continue with Google"',
    )
    host = demo_server.split("://")[1]
    assert f"line 1 opened a new tab: {host}/books (Books · Acme Billing)" in said, said
    assert "tab latest" in said


def test_a_task_goes_back_to_its_own_page_when_another_site_holds_the_tab(mcp_server, demo_server):
    """28 Oct: one tab per profile. A step for one site's task ran its js on another site's
    page, left open by a task for that site, and the reply did not say so."""
    other = demo_server.replace("127.0.0.1", "localhost")
    task = "read the next charge"
    call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/payments")
    call(mcp_server, "dejo_run", site=other, task="read the first book", url=f"{other}/books")

    said = call(mcp_server, "dejo_run", site=demo_server, task=task, steps='js "location.href"')

    assert f'js returned: "{demo_server}/payments"' in said, said
    assert f"the tab showed {other.split('://')[1]}/books" in said, said


def test_refs_from_before_another_site_used_the_tab_are_not_run(mcp_server, demo_server):
    """The refs an agent sends came from its own last view. Once another site's task used the
    tab they point at nothing, so nothing runs and the task's page is shown again."""
    other = demo_server.replace("127.0.0.1", "localhost")
    task = "read the next charge"
    first = call(mcp_server, "dejo_run", site=demo_server, task=task, url=f"{demo_server}/payments")
    change = ref_named(first, "Change card")
    call(mcp_server, "dejo_run", site=other, task="read the first book", url=f"{other}/books")

    said = call(mcp_server, "dejo_run", site=demo_server, task=task, steps=f"click {change}")

    assert said.startswith("stopped at line 1 of 1"), said
    assert f"the tab showed {other.split('://')[1]}/books" in said, said
    assert ref_named(said, "Change card"), "the task's own page is shown again"
