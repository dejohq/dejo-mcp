"""A trail learned on the English page, replayed where the site answers in another language.

`/safety/lang` serves the same basket in English or Hindi by Accept-Language, and has two
buttons: one shows the total, the other empties the basket. With DEJO_LOCALE=hi-IN a step
found by role or place still works, or Dejo stops at it and says the page is in another
language. It never clicks the wrong control because a name matched loosely.
"""

from __future__ import annotations

import pytest

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.operations import Session
from dejo.runner import Runner
from dejo.store import DejoStore

TASK = "what is the basket total"


def learn(store: DejoStore, demo_server: str, steps: str, downloads) -> None:
    """Learned in a browser that asks for English, closed before the other one opens."""
    with Browser(headless=True, downloads=downloads) as english:
        runner = Runner(Session(browser=english, store=store), task=TASK, store=store)
        outcome = runner.run(program.parse(f"go {demo_server}/safety/lang\n{steps}"))
        assert outcome.ok, outcome.text()


@pytest.mark.parametrize(
    "steps",
    [
        'click button "Show total"\nread css "#total" as total',
        'click button "Show"\nread css "#total" as total',
    ],
    ids=["whole name", "part of the name"],
)
def test_another_language_works_or_stops_and_says_so(
    store: DejoStore,
    demo_server: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    steps: str,
) -> None:
    monkeypatch.setenv("DEJO_LOCALE", "en-GB")
    learn(store, demo_server, steps, tmp_path / "english")

    monkeypatch.setenv("DEJO_LOCALE", "hi-IN")
    with Browser(headless=True, downloads=tmp_path / "hindi") as hindi:
        later = Executor(store, hindi).run(domain_of(demo_server), task=TASK)
        emptied = hindi.page.evaluate("Boolean(window.lab && window.lab.emptied)")

    assert not emptied, "it pressed the button that empties the basket"
    if later.ok:
        assert later.answers == {"total": "£31.40"}
    else:
        assert "language" in later.reason and "hi" in later.reason, later.reason
        assert later.repair is None or "language" in later.reason
