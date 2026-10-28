"""The worker keeps its browser answered between jobs, not only while one runs."""

from __future__ import annotations

import time

from dejo.browser import SESSION_COOKIE_EVERY_S
from dejo.worker import BrowserWorker

# Raises an alert while no job is running, and notes how long the page was frozen by it.
ALERT_WHILE_IDLE = """
<!doctype html>
<title>idle</title>
<script>
  setTimeout(() => {
    const start = Date.now();
    alert('while nobody is asking');
    window.frozenMs = Date.now() - start;
  }, 200);
</script>
"""

# Long enough that a worker which only answers when a job arrives shows the whole wait.
IDLE_S = 2
# Far under IDLE_S: the alert was answered while the worker had nothing to do.
ANSWERED_WITHIN_MS = 1000


def test_a_page_is_answered_while_no_job_is_running():
    """A blocked worker left the page frozen until the next call: a sign-in window behind a
    Cloudflare check spun forever that way."""
    worker = BrowserWorker()
    try:
        worker.submit(lambda browser: browser.page.set_content(ALERT_WHILE_IDLE))
        time.sleep(IDLE_S)
        frozen = worker.submit(lambda browser: browser.page.evaluate("window.frozenMs"))
    finally:
        worker.stop()
    assert frozen is not None and frozen < ANSWERED_WITHIN_MS, frozen


SET_SESSION_COOKIE = "document.cookie = 'signed_in=yes; path=/'"
# Longer than SESSION_COOKIE_EVERY_S, so the waiting browser has had its turn.
WAIT_FOR_KEEP_S = SESSION_COOKIE_EVERY_S + 2


def _cookie_after_reopen(profile: str, url: str) -> str:
    again = BrowserWorker(profile=profile)
    try:
        again.submit(lambda browser: browser.goto(url))
        return again.submit(lambda browser: browser.page.evaluate("document.cookie"))
    finally:
        again.stop()


def test_a_session_cookie_outlives_closing_the_profile(demo_server, tmp_path):
    """Chrome drops a cookie with no expiry on close: saashub.com was signed out again the
    run after `dejo_login`."""
    profile = str(tmp_path / "profile")
    worker = BrowserWorker(profile=profile)
    worker.submit(lambda browser: browser.goto(demo_server))
    worker.submit(lambda browser: browser.page.evaluate(SET_SESSION_COOKIE))
    worker.stop()

    assert "signed_in=yes" in _cookie_after_reopen(profile, demo_server)


def test_a_session_cookie_outlives_the_person_closing_the_window(demo_server, tmp_path):
    """No clean close to keep it at: the waiting browser must already have kept it."""
    profile = str(tmp_path / "profile")
    worker = BrowserWorker(profile=profile)
    worker.submit(lambda browser: browser.goto(demo_server))
    worker.submit(lambda browser: browser.page.evaluate(SET_SESSION_COOKIE))
    time.sleep(WAIT_FOR_KEEP_S)
    # What shutting the window does: the browser is gone before Dejo is told anything.
    worker.submit(lambda browser: browser._context.close())
    worker.stop()

    assert "signed_in=yes" in _cookie_after_reopen(profile, demo_server)
