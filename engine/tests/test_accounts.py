"""Which account is signed in: noted while learning, checked before a replay acts.

The lab site in `demo_site/drift.py` has two accounts, finance@acme.com and riya@acme.com,
and signs in whoever owns the password typed. Each shows itself in the header. A trail
learned as one and replayed signed in as the other must stop before it does anything, and
say who was expected and who is signed in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.demo_site.drift import ACCOUNT_COOKIE

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor, NoTrailError
from dejo.operations import Session
from dejo.runner import Runner
from dejo.secrets import env_var_name
from dejo.store import DejoStore

TASK = "what is due"
FINANCE = "finance@acme.com"
RIYA = "riya@acme.com"


def runner_for(browser: Browser, store: DejoStore) -> Runner:
    return Runner(Session(browser=browser, store=store), task=TASK, store=store)


def sign_in_as(browser: Browser, demo_server: str, email: str) -> None:
    """Be signed in as `email`, as a browser profile that signed in earlier would be."""
    browser._context.add_cookies([{"name": ACCOUNT_COOKIE, "value": email, "url": demo_server}])


def learn_signed_in(browser: Browser, store: DejoStore, demo_server: str, extra: str = ""):
    outcome = runner_for(browser, store).run(
        program.parse(f'go {demo_server}/drift/account/home\n{extra}read css "#due" as due')
    )
    assert outcome.ok, outcome.text()
    return outcome


def replay(browser: Browser, store: DejoStore, demo_server: str, **how):
    return Executor(store, browser).run(domain_of(demo_server), task=TASK, **how)


def test_the_account_shown_while_learning_is_kept_with_the_trail(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    sign_in_as(browser, demo_server, FINANCE)
    learn_signed_in(browser, store, demo_server)

    trail = store.load_playbook(domain_of(demo_server), TASK)
    assert trail is not None and trail.signed_in_as == FINANCE
    assert "signed_in_as" not in trail.for_sharing(None).to_dict(), "a shared trail names a person"

    same = replay(browser, store, demo_server)
    assert same.ok, same.reason
    assert same.answers == {"due": "48,200 due"}


def test_a_replay_signed_in_as_someone_else_stops_before_it_acts(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    sign_in_as(browser, demo_server, FINANCE)
    learn_signed_in(browser, store, demo_server)
    sign_in_as(browser, demo_server, RIYA)
    browser.goto("about:blank")

    other = replay(browser, store, demo_server)

    assert not other.ok
    assert other.wrong_account == (FINANCE, RIYA)
    assert other.metrics.steps_replayed == 1, "only the page was opened"
    assert other.answers == {}
    assert f"signed in as {RIYA!r}" in other.reason and f"learned as {FINANCE!r}" in other.reason
    assert other.repair is None, "the trail is fine; nothing to repair"


def test_a_tab_already_on_the_site_as_someone_else_stops_before_step_one(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    sign_in_as(browser, demo_server, FINANCE)
    learn_signed_in(browser, store, demo_server)
    sign_in_as(browser, demo_server, RIYA)
    browser.goto(f"{demo_server}/drift/account/home")

    other = replay(browser, store, demo_server)

    assert other.wrong_account == (FINANCE, RIYA)
    assert other.metrics.steps_replayed == 0
    assert "Stopped before step 1" in other.reason


def test_a_sign_in_step_that_signs_in_someone_else_stops_right_after_it(
    browser: Browser, store: DejoStore, demo_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This machine holds Riya's password for the site, so the trail's own sign-in signs
    in the wrong person."""
    outcome = runner_for(browser, store).run(
        program.parse(
            f"go {demo_server}/drift/account/sign-in\n"
            f'fill label "Email" "{FINANCE}"\n'
            'fill label "Password" "hunter2"\n'
            'click button "Sign in"\n'
            'read css "#due" as due'
        )
    )
    assert outcome.ok, outcome.text()
    assert outcome.saved is not None and outcome.saved.signed_in_as == FINANCE

    browser._context.clear_cookies()
    monkeypatch.setenv(env_var_name(domain_of(demo_server), "password"), "riya-pass")
    other = replay(browser, store, demo_server)

    assert other.wrong_account == (FINANCE, RIYA)
    assert "Stopped before step 5" in other.reason
    assert other.answers == {}


def test_a_page_that_names_nobody_is_no_reason_to_stop(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    sign_in_as(browser, demo_server, FINANCE)
    learn_signed_in(browser, store, demo_server)

    quiet = replay(
        browser, store, demo_server, start_url=f"{demo_server}/drift/account/home?quiet=1"
    )

    assert quiet.ok, quiet.reason
    assert quiet.wrong_account is None


def test_a_site_that_never_shows_an_account_keeps_no_marker(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    outcome = runner_for(browser, store).run(
        program.parse(f'go {demo_server}/news\nread css "#headline" as headline')
    )
    assert outcome.ok and outcome.saved is not None, outcome.text()
    assert outcome.saved.signed_in_as is None


def test_an_agent_can_name_the_account_by_hand(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    sign_in_as(browser, demo_server, FINANCE)
    learn_signed_in(browser, store, demo_server, extra='expect signed in as "Finance Team"\n')
    trail = store.load_playbook(domain_of(demo_server), TASK)
    assert trail is not None and trail.signed_in_as == "Finance Team"

    sign_in_as(browser, demo_server, RIYA)
    other = replay(browser, store, demo_server)

    assert other.wrong_account == ("Finance Team", RIYA)


def test_naming_an_account_the_page_does_not_show_stops_the_line(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    sign_in_as(browser, demo_server, RIYA)
    outcome = runner_for(browser, store).run(
        program.parse(
            f'go {demo_server}/drift/account/home\nexpect signed in as "Finance Team"\n'
            'read css "#due" as due'
        )
    )

    assert not outcome.ok
    assert outcome.stopped_at is not None and outcome.stopped_at.line == 2
    assert f"it shows {RIYA!r} as signed in" in outcome.reason


def test_forgetting_the_site_forgets_who_was_signed_in(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    sign_in_as(browser, demo_server, FINANCE)
    learn_signed_in(browser, store, demo_server)

    store.forget_site(domain_of(demo_server))

    with pytest.raises(NoTrailError):
        replay(browser, store, demo_server)
    sign_in_as(browser, demo_server, RIYA)
    learn_signed_in(browser, store, demo_server)
    again = store.load_playbook(domain_of(demo_server), TASK)
    assert again is not None and again.signed_in_as == RIYA, "the old account came back"


def test_the_account_is_checked_in_a_browser_dejo_did_not_start(
    running_chrome: str,
    store: DejoStore,
    demo_server: str,
    tmp_path: Path,
) -> None:
    """DEJO_CDP_URL: a browser someone else started, with its own sign-ins."""
    with Browser(cdp_url=running_chrome, downloads=tmp_path / "downloads") as theirs:
        sign_in_as(theirs, demo_server, FINANCE)
        learn_signed_in(theirs, store, demo_server)
        sign_in_as(theirs, demo_server, RIYA)
        other = replay(theirs, store, demo_server)
        assert other.wrong_account == (FINANCE, RIYA)


def test_a_link_that_only_mentions_account_is_not_who_is_signed_in(browser: Browser) -> None:
    """Google's "Choose an account" page, 10 Nov: a "Help" link labelled "Google Account
    Help" was kept as the signed-in account, so every later replay would compare against
    "Help". A sign-in page names nobody yet."""
    from dejo import identity

    browser.page.set_content(
        '<h1>Choose an account</h1><a href="/help" aria-label="Google Account Help">Help</a>'
        '<a href="/add">Use another account</a><a href="/privacy">Privacy</a>'
    )
    assert identity.marker_on(browser.page) is None


def test_an_account_menu_button_names_the_account(browser: Browser) -> None:
    from dejo import identity

    browser.page.set_content(
        '<header><a href="/help" aria-label="Google Account Help">Help</a>'
        '<a role="button" aria-haspopup="true" '
        'aria-label="Google Account: Rohit Kashyap (rohit@example.com)">R</a></header>'
    )
    assert identity.marker_on(browser.page) == "rohit@example.com"
