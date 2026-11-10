"""Telling "you were signed out" from "the site changed", in the ways sites sign you out.

A page with a password box, or an address with "login" in it, was all Dejo knew. These lab
pages ask for a sign-in without either: a 401 with a page that only says so, Google's account
chooser, and an identifier-first form that asks for the email now and the password on the
next page. Each must come back as `needs_login`, so the agent asks the person to sign in
rather than repairing a step that is not broken. It is still only asked after a step failed.
"""

from __future__ import annotations

import pytest
from tests.demo_site.drift import SESSION_COOKIE, SESSION_GONE

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.operations import Session
from dejo.runner import Runner
from dejo.store import DejoStore

TASK = "what is due"

_CHOOSER = """<!doctype html><title>Choose an account</title>
<h1>Choose an account</h1><p>to continue to Lab</p>
<ul><li><a href="#">Use another account</a></li></ul>"""


def learn(browser: Browser, store: DejoStore, url: str, read: str = 'css "#due"') -> None:
    runner = Runner(Session(browser=browser, store=store), task=TASK, store=store)
    outcome = runner.run(program.parse(f"go {url}\nread {read} as due"))
    assert outcome.ok, outcome.text()


def end_the_session(browser: Browser, demo_server: str) -> None:
    browser._context.add_cookies(
        [{"name": SESSION_COOKIE, "value": SESSION_GONE, "url": demo_server}]
    )
    browser._context.route(
        "https://accounts.google.com/**",
        lambda route: route.fulfill(status=200, content_type="text/html", body=_CHOOSER),
    )


@pytest.mark.parametrize(
    "path",
    ["/drift/session", "/drift/workspace", "/drift/start?form=named", "/drift/start?form=plain"],
)
def test_a_session_that_ran_out_is_a_sign_in_not_a_broken_step(
    browser: Browser, store: DejoStore, demo_server: str, path: str
) -> None:
    learn(browser, store, f"{demo_server}{path}")
    end_the_session(browser, demo_server)

    result = Executor(store, browser).run(domain_of(demo_server), task=TASK)

    assert not result.ok
    assert result.needs_login, result.reason
    assert result.repair is None and result.page_error is None


def test_a_trail_that_starts_at_a_sign_in_page_on_purpose_still_replays(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    learn(browser, store, f"{demo_server}/drift/account/sign-in", read='css "h1"')

    result = Executor(store, browser).run(domain_of(demo_server), task=TASK)

    assert result.ok, result.reason
    assert result.answers == {"due": "Sign in"}
