"""The item a task read has moved, and another item now sits where it was.

`/safety/prices` lists prices as plain rows, with no link to find a row by, and comes back
in another order after the first visit. A read of "the teapot's price" must still read the
teapot's price, or stop. A read that was by place ("the first price") says it is by place
when what sits there now is not what sat there when it was learned. No replay may hand back
a value from a different element than the task meant without saying so.
"""

from __future__ import annotations

import re

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor
from dejo.operations import Session
from dejo.runner import Runner
from dejo.store import DejoStore

TEAPOT = "£18.50"


def learn_by_ref(browser: Browser, store: DejoStore, demo_server: str, task: str) -> None:
    """Look at the page and read the teapot's price by its ref, as an agent does."""
    runner = Runner(Session(browser=browser, store=store), task=task, store=store)
    looked = runner.run(program.parse(f"go {demo_server}/safety/prices\nlook"))
    assert looked.ok and looked.view is not None, looked.text()
    ref = re.search(r"((?:f\d+)?e\d+): Teapot", looked.view.text)
    assert ref is not None, looked.view.text
    read = runner.run(program.parse(f"read {ref.group(1)} as price"), done=True)
    assert read.ok and TEAPOT in read.answers["price"], read.text()


def test_a_read_learned_on_one_row_never_reads_another_in_silence(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    task = "what does the teapot cost"
    learn_by_ref(browser, store, demo_server, task)

    later = Executor(store, browser).run(domain_of(demo_server), task=task)

    if later.ok:
        said = " ".join(later.decisions)
        assert TEAPOT in later.answers["price"] or "by place" in said, (
            later.answers,
            later.decisions,
        )
    else:
        assert later.answers == {}


def test_a_read_by_place_says_it_is_by_place_when_the_row_changed(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    task = "what is the first price"
    runner = Runner(Session(browser=browser, store=store), task=task, store=store)
    learned = runner.run(
        program.parse(f'go {demo_server}/safety/prices\nread css ".price" first as price'),
        done=True,
    )
    assert learned.ok and learned.answers == {"price": TEAPOT}, learned.text()

    later = Executor(store, browser).run(domain_of(demo_server), task=task)

    assert later.ok, later.reason
    assert later.answers == {"price": "£6.00"}, "the first row is the mug now"
    assert any("by place" in line for line in later.decisions), later.decisions


def test_an_item_that_is_gone_is_not_replaced_by_the_one_in_its_place(
    browser: Browser, store: DejoStore, demo_server: str
) -> None:
    """The teapot sold out. The way of finding its link by place finds the kettle's."""
    task = "what does the teapot cost"
    runner = Runner(Session(browser=browser, store=store), task=task, store=store)
    learned = runner.run(
        program.parse(
            f'go {demo_server}/safety/stock\nclick link "Teapot"\nread css "#price" as price'
        )
    )
    assert learned.ok, learned.text()

    later = Executor(store, browser).run(domain_of(demo_server), task=task)

    assert not later.ok, later.answers
    assert later.answers == {}
