"""The four core promises, end to end, against a real browser and a real site.

  1  a cold run completes the task and leaves a playbook in memory
  2  a warm run replays it with zero model calls and far fewer tool calls
  3  a cosmetic redesign is survived with no repair at all
  4  a real break stops on ONE step, is repaired, and the next run is clean again

The deletion gate is its own file, because it is the one to run first.
"""

from __future__ import annotations

import pytest
from tests.conftest import TASK, cold_run

from dejo.browser import Browser, domain_of
from dejo.events import Emitter
from dejo.executor import Executor
from dejo.models import Locator
from dejo.operations import Session
from dejo.store import DejoStore


@pytest.fixture
def learned(browser: Browser, store: DejoStore, demo_server: str):
    """A site Dejo has walked once. This is the starting point for every warm test."""
    session = Session(browser, store)
    cold_run(session, demo_server)
    playbook = session.save(TASK, domain=domain_of(demo_server))
    return playbook, session


class TestColdRun:
    """Finish line 1: the task completes and a playbook appears in memory."""

    def test_the_task_actually_completes(self, learned):
        """A file on disk, not just a download event.

        The first version of this test only checked that Playwright fired a download
        event. It passed for a week while the file was being thrown away when the browser
        context closed, which a real Claude Code session caught immediately. A download
        task is done when there is a file you can open.
        """
        from pathlib import Path

        _, session = learned
        last = session.trace[-1]

        assert last.download is not None, "the invoice should have downloaded"
        saved = session.browser.last_download_path
        assert saved is not None, "the download was never written anywhere"
        assert Path(saved).is_file(), f"no file at {saved}"
        assert Path(saved).stat().st_size > 0, "the saved file is empty"

    def test_a_playbook_lands_in_memory(self, learned, store: DejoStore, demo_server: str):
        playbook, _ = learned

        stored = store.load_playbook(domain_of(demo_server))
        assert stored is not None
        assert stored.task == TASK
        assert len(stored.steps) == len(playbook.steps) == 6

    def test_every_step_has_a_postcondition(self, learned):
        playbook, _ = learned

        for step in playbook.steps:
            assert step.postcondition.kind, f"step {step.index} cannot verify itself"

    def test_each_clickable_step_keeps_several_ways_to_be_found(self, learned):
        playbook, _ = learned

        clicks = [step for step in playbook.steps if step.action == "click"]
        assert clicks, "the trail should contain clicks"
        for step in clicks:
            kinds = {locator.kind for locator in step.locators}
            assert len(kinds) >= 2, f"step {step.index} only knows {kinds}"

    def test_a_way_that_also_finds_something_else_is_not_kept(self, learned):
        """The sign-in page has an `<h1>Sign in</h1>` above the button of the same name, so
        `text "Sign in"` finds two elements and a replay could press the heading."""
        playbook, _ = learned

        sign_in = next(step for step in playbook.steps if step.intent == "sign in")
        assert ("text", "Sign in") not in {(loc.kind, loc.value) for loc in sign_in.locators}

    def test_the_cold_run_was_expensive(self, learned):
        """The thing we are removing. Nine calls to do it the first time."""
        _, session = learned

        assert session.tool_calls >= 8


class TestDownloadsAreRealEachTime:
    """A replay must download the file again, not coast on an earlier one.

    Found by a test that only failed when the whole suite ran: the executor never cleared
    the last download, so a "did it download?" check could be satisfied by a file fetched
    minutes earlier in the same browser. The step reported success having downloaded
    nothing, and `saved_files` came back empty.
    """

    def test_each_replay_writes_the_file_again(
        self, learned, store: DejoStore, browser: Browser, demo_server: str
    ):
        from pathlib import Path

        domain = domain_of(demo_server)
        first = Executor(store, browser).run(domain, start_url=f"{demo_server}/")
        assert first.saved_files, "the first replay should save a file"

        second = Executor(store, browser).run(domain, start_url=f"{demo_server}/")

        assert second.saved_files, "the second replay must not coast on the first download"
        assert Path(second.saved_files[0]).is_file()

    def test_a_run_starts_with_no_download_remembered(
        self, learned, store: DejoStore, browser: Browser, demo_server: str
    ):
        Executor(store, browser).run(domain_of(demo_server), start_url=f"{demo_server}/")
        assert browser.last_download is not None

        # A run against a page with no download must not still report the old one.
        browser.goto(f"{demo_server}/invoices")
        assert browser.last_download is not None, "still set until the next run clears it"

        Executor(store, browser).run(domain_of(demo_server), start_url=f"{demo_server}/")
        assert len(browser.saved_files) == 1, "saved_files is per run, not cumulative"


class TestWarmRun:
    """Finish line 2: replay, deterministically, with no model involved."""

    def test_replays_the_whole_trail(
        self, learned, store: DejoStore, browser: Browser, demo_server: str
    ):
        result = Executor(store, browser).run(domain_of(demo_server), start_url=f"{demo_server}/")

        assert result.ok is True
        assert result.metrics.steps_replayed == 6

    def test_uses_no_model_and_one_tool_call(self, learned, store, browser, demo_server):
        result = Executor(store, browser).run(domain_of(demo_server), start_url=f"{demo_server}/")

        assert result.metrics.model_calls == 0
        assert result.metrics.tool_calls == 1, "the caller makes one call, not nine"

    def test_the_run_is_journalled(self, learned, store: DejoStore, browser, demo_server):
        Executor(store, browser).run(domain_of(demo_server), start_url=f"{demo_server}/")

        kinds = [entry.get("extra", {}).get("kind") for entry in store.read_journal(limit=20)]
        assert "run" in kinds

    def test_memory_is_read_before_anything_else_happens(
        self, learned, store, browser, demo_server
    ):
        """If this read stops happening, the warm path is not using memory at all."""
        emitter = Emitter()
        Executor(store, browser, emitter=emitter).run(
            domain_of(demo_server), start_url=f"{demo_server}/"
        )

        reads = emitter.of_kind("memory_read")
        assert reads and reads[0].to_dict()["found"] is True

    def test_walking_the_trail_makes_it_more_confident(
        self, learned, store: DejoStore, browser, demo_server
    ):
        domain = domain_of(demo_server)
        before = store.load_playbook(domain).steps[-1].health

        Executor(store, browser).run(domain, start_url=f"{demo_server}/")

        after = store.load_playbook(domain).steps[-1].health
        assert after >= before
        assert store.load_playbook(domain).runs == 1


class TestCosmeticRedesign:
    """Finish line 3a: the site changed, and it cost nothing.

    Variant C renames the control, changes its id and moves it. Only the link target is
    untouched. Because a step keeps several ranked locators, one of them still lands.
    """

    def test_survives_with_no_repair(self, learned, store, browser, demo_server):
        result = Executor(store, browser).run(
            domain_of(demo_server), start_url=f"{demo_server}/?variant=c"
        )

        assert result.ok is True, "a cosmetic redesign should not need a model"
        assert result.needs_repair is False
        assert result.metrics.model_calls == 0

    def test_the_redesign_costs_literally_nothing(self, learned, store, browser, demo_server):
        """Not one wasted attempt, because the durable locator is tried first.

        The CSS id did go stale in variant C. Dejo never finds that out, and should not:
        probing locators it does not need would spend time to learn something it has no
        use for. A dead locator only gets discovered when the ones ahead of it fail too.
        """
        emitter = Emitter()
        Executor(store, browser, emitter=emitter).run(
            domain_of(demo_server), start_url=f"{demo_server}/?variant=c"
        )

        assert emitter.of_kind("drift_detected") == []
        assert emitter.of_kind("repair_needed") == []

    def test_it_won_on_the_link_target_not_the_css(self, learned, store, browser, demo_server):
        """The specific reason it survived, pinned down."""
        emitter = Emitter()
        Executor(store, browser, emitter=emitter).run(
            domain_of(demo_server), start_url=f"{demo_server}/?variant=c"
        )

        download_step = emitter.of_kind("step_passed")[-1].to_dict()
        assert download_step["matched_by"].startswith("structural:href=")


class TestRealBreak:
    """Finish line 3b: one step breaks, one step is repaired, the rest is untouched."""

    def test_stops_on_the_one_broken_step(self, learned, store, browser, demo_server):
        result = Executor(store, browser).run(
            domain_of(demo_server), start_url=f"{demo_server}/?variant=b"
        )

        assert result.ok is False
        assert result.needs_repair is True
        assert result.repair is not None
        assert result.repair.step_index == 6, "only the download step should break"
        assert result.metrics.steps_replayed == 5, "the first five steps still worked"

    def test_the_repair_request_is_small_and_useful(self, learned, store, browser, demo_server):
        result = Executor(store, browser).run(
            domain_of(demo_server), start_url=f"{demo_server}/?variant=b"
        )

        request = result.repair
        assert request.intent == "download the PDF", "it says what the step was FOR"
        assert request.tried, "it says what was already tried"
        assert any(c["name"] == "Get PDF" for c in request.candidates), (
            "and it offers the controls actually on the page now"
        )

    def test_a_repair_is_saved_and_the_next_run_is_clean(
        self, learned, store: DejoStore, browser, demo_server
    ):
        domain = domain_of(demo_server)
        executor = Executor(store, browser)
        broken = executor.run(domain, start_url=f"{demo_server}/?variant=b")
        assert broken.needs_repair

        # This is the host AI's part: it looked at the page and picked the new control.
        fixed = next(c for c in broken.repair.candidates if c["name"] == "Get PDF")
        executor.apply_repair(domain, broken.repair.step_index, Locator("css", fixed["css"]))

        again = Executor(store, browser).run(domain, start_url=f"{demo_server}/?variant=b")

        assert again.ok is True, "after one repair the trail should run clean"
        assert again.metrics.model_calls == 0
        assert again.metrics.steps_replayed == 6

    def test_the_run_reports_how_often_this_trail_has_been_repaired(
        self, learned, store: DejoStore, browser, demo_server
    ):
        """This number used to be structurally impossible and printed anyway.

        The old field was `steps_repaired` on the run, which nothing ever incremented,
        because a run cannot repair anything — it stops at the broken step and the fix
        arrives as a separate call. So the CLI printed "0 repaired" after every single run,
        including runs of a trail that had been repaired. It now reports the trail's real
        repair history, and this test is what stops it going quiet again.
        """
        domain = domain_of(demo_server)
        executor = Executor(store, browser)

        clean = executor.run(domain, start_url=f"{demo_server}/")
        assert clean.metrics.trail_repairs == 0, "nothing has been repaired yet"

        broken = executor.run(domain, start_url=f"{demo_server}/?variant=b")
        fixed = next(c for c in broken.repair.candidates if c["name"] == "Get PDF")
        executor.apply_repair(domain, broken.repair.step_index, Locator("css", fixed["css"]))

        after = Executor(store, browser).run(domain, start_url=f"{demo_server}/?variant=b")

        assert after.ok is True
        assert after.metrics.trail_repairs == 1, "the repair that just happened must show up"

    def test_and_the_event_carries_it_too(self, learned, store: DejoStore, browser, demo_server):
        """The CLI renders the event, not the metrics, so the event is what must be right."""
        domain = domain_of(demo_server)
        executor = Executor(store, browser)
        broken = executor.run(domain, start_url=f"{demo_server}/?variant=b")
        fixed = next(c for c in broken.repair.candidates if c["name"] == "Get PDF")
        executor.apply_repair(domain, broken.repair.step_index, Locator("css", fixed["css"]))

        emitter = Emitter()
        Executor(store, browser, emitter=emitter).run(domain, start_url=f"{demo_server}/?variant=b")

        finished = emitter.of_kind("run_finished")[0].to_dict()
        assert finished["trail_repairs"] == 1

    def test_the_repair_is_journalled(self, learned, store: DejoStore, browser, demo_server):
        domain = domain_of(demo_server)
        executor = Executor(store, browser)
        broken = executor.run(domain, start_url=f"{demo_server}/?variant=b")
        fixed = next(c for c in broken.repair.candidates if c["name"] == "Get PDF")

        executor.apply_repair(domain, broken.repair.step_index, Locator("css", fixed["css"]))

        kinds = [entry.get("extra", {}).get("kind") for entry in store.read_journal(limit=20)]
        assert "repair" in kinds

    def test_only_the_broken_step_was_touched(
        self, learned, store: DejoStore, browser, demo_server
    ):
        domain = domain_of(demo_server)
        executor = Executor(store, browser)
        broken = executor.run(domain, start_url=f"{demo_server}/?variant=b")
        fixed = next(c for c in broken.repair.candidates if c["name"] == "Get PDF")

        executor.apply_repair(domain, broken.repair.step_index, Locator("css", fixed["css"]))

        playbook = store.load_playbook(domain)
        repaired = [step.index for step in playbook.steps if step.repairs > 0]
        assert repaired == [6], "a repair must stay surgical"
