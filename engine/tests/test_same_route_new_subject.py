"""Same route, different subject.

"message ankush" today and "message riya" tomorrow is ONE route with one thing swapped.
Storing a separate trail per person is not memory, it is a filing cabinet, and it means the
second person costs full price forever.

Before this, the matcher scored those two as nearly identical — every word matches but one —
and replayed the stored trail unchanged. Asking for pannly's search clicks returned
vouchley's number. Asking to message riya would have messaged ankush.

The promise this file pins down: **Dejo will aim a route at a new subject, but it will not
act until it can see that subject on the thing it is about to act on.**
"""

from __future__ import annotations

import pytest

from dejo.browser import Browser
from dejo.executor import Executor, with_subject
from dejo.models import Locator, Playbook, Postcondition, Step
from dejo.store import DejoStore, swapped_subject

SITE = "acme.example"


class TestSpottingTheSwap:
    def test_one_word_changed_is_the_same_job_aimed_elsewhere(self) -> None:
        assert swapped_subject("message riya", "message ankush") == ("ankush", "riya")

    def test_it_works_on_the_case_that_started_this(self) -> None:
        got = swapped_subject(
            "read total web search clicks for pannly",
            "read total web search clicks for vouchley",
            "search.google.com",
        )
        assert got == ("vouchley", "pannly")

    def test_two_things_changed_is_a_different_request(self) -> None:
        """One swap is aim. Two is a different question wearing the same shape."""
        assert swapped_subject("email riya tomorrow", "message ankush") is None

    def test_a_pure_rephrasing_is_not_a_swap_of_subject(self) -> None:
        assert swapped_subject("count open issues", "count open issues") is None

    def test_nothing_in_common_is_not_a_swap(self) -> None:
        assert swapped_subject("cancel subscription", "count issues") is None


def a_trail(*, subject: str) -> Playbook:
    """Open a page about someone, find their row, act on it."""
    return Playbook(
        domain=SITE,
        task=f"message {subject}",
        steps=[
            Step(
                index=1,
                intent="open the inbox",
                action="goto",
                value=f"/inbox?to={subject}",
                postcondition=Postcondition("url_contains", "/inbox"),
            ),
            Step(
                index=2,
                intent="open the conversation",
                action="click",
                postcondition=Postcondition("element_present", "#thread"),
                locators=[Locator("text", subject)],
            ),
        ],
    )


class TestAimingTheTrail:
    def test_the_subject_is_replaced_everywhere_it_is_written_down(self) -> None:
        aimed, touched = with_subject(a_trail(subject="ankush"), "ankush", "riya")

        assert aimed.steps[0].value == "/inbox?to=riya"
        assert aimed.steps[1].locators[0].value == "riya"
        assert touched == {1: {"value"}, 2: {"locator"}}

    def test_the_trail_in_memory_is_never_touched(self) -> None:
        """The route belongs to the trail. The subject belongs to this one caller."""
        original = a_trail(subject="ankush")

        with_subject(original, "ankush", "riya")

        assert original.steps[0].value == "/inbox?to=ankush"
        assert original.steps[1].locators[0].value == "ankush"

    def test_a_subject_written_nowhere_is_not_a_swap_at_all(self) -> None:
        """ "tell" against "read" also differs by one word, but `read` is not written into
        any step — so it is a rephrasing, and the ordinary matcher should handle it."""
        assert with_subject(a_trail(subject="ankush"), "read", "tell") is None

    def test_it_matches_whole_words_only(self) -> None:
        """Otherwise "ana" quietly rewrites "anastasia"."""
        trail = a_trail(subject="anastasia")

        assert with_subject(trail, "ana", "riya") is None

    def test_but_still_finds_the_subject_inside_an_address(self) -> None:
        """A dot or a slash is a boundary, and a URL is where the subject usually hides."""
        trail = a_trail(subject="ankush")
        trail.steps[0].value = "https://ankush.example.com/inbox"

        aimed, _ = with_subject(trail, "ankush", "riya")

        assert aimed.steps[0].value == "https://riya.example.com/inbox"

    def test_a_percent_escape_is_a_boundary_too(self) -> None:
        """Found on a real trail. Search Console stores the property percent-encoded, so
        the character before the subject is the `F` of `%2F` — a plain word check reads that
        as part of a longer word and the subject goes unseen, inside an encoded URL, which
        is exactly where a subject usually lives."""
        trail = a_trail(subject="ankush")
        trail.steps[0].value = "https://x.example/inbox?to=https%3A%2F%2Fankush.example.com%2F"

        aimed, touched = with_subject(trail, "ankush", "riya")

        assert (
            aimed.steps[0].value == "https://x.example/inbox?to=https%3A%2F%2Friya.example.com%2F"
        )
        assert 1 in touched

    def test_the_check_is_re_aimed_too_so_it_verifies_the_new_subject(self) -> None:
        """This is where the safety comes from. The step's own check was recorded against
        the old subject, so swapping it makes that check confirm the new one landed."""
        trail = a_trail(subject="ankush")
        trail.steps[1].postcondition = Postcondition("text_present", "ankush")

        aimed, touched = with_subject(trail, "ankush", "riya")

        assert aimed.steps[1].postcondition.value == "riya"
        assert "check" in touched[2]


class TestItWillNotActOnTheWrongOne:
    """The promise, against a real browser.

    The demo site's /settings has a billing email on it and nothing called "riya". A trail
    aimed at riya must stop there rather than act on whatever it did find.
    """

    def a_reading_trail(self, subject: str) -> Playbook:
        return Playbook(
            domain=SITE,
            task=f"read the {subject} address",
            steps=[
                Step(
                    index=1,
                    intent="open settings",
                    action="goto",
                    value="/settings",
                    postcondition=Postcondition("url_contains", "/settings"),
                ),
                Step(
                    index=2,
                    intent="read the address",
                    action="read",
                    value="text",
                    postcondition=Postcondition("element_present", "#billing-email"),
                    locators=[Locator("css", f"#{subject}-email")],
                ),
            ],
        )

    def test_it_stops_instead_of_acting_on_something_else(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        store.save_playbook(self.a_reading_trail("billing"))

        result = Executor(store, browser).run(
            SITE, task="read the shipping address", start_url=f"{demo_server}/settings"
        )

        assert result.ok is False
        assert result.aimed_at == ("billing", "shipping")

    def test_no_repair_is_ever_offered_for_an_aimed_run(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        """The trail is not broken. It was pointed somewhere its subject does not live, and
        binding this step to whatever happens to be on the page would wreck a working
        route — the same damage the wrong-page case exists to prevent."""
        store.save_playbook(self.a_reading_trail("billing"))

        result = Executor(store, browser).run(
            SITE, task="read the shipping address", start_url=f"{demo_server}/settings"
        )

        assert result.needs_repair is False
        assert result.repair is None
        assert "do NOT repair" in result.reason

    def test_the_swap_is_always_reported(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        """The caller asked about one thing and Dejo worked out the route for another. It
        has to be able to see that happened rather than be told the answer."""
        store.save_playbook(self.a_reading_trail("billing"))

        result = Executor(store, browser).run(
            SITE, task="read the shipping address", start_url=f"{demo_server}/settings"
        )

        assert result.aimed_at is not None


class TestAnAimedRunNeverWritesTheTrailBack:
    def test_the_stored_trail_keeps_its_own_subject(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        """Saving would overwrite the trail that belongs to billing with shipping's
        addresses, and fold a run it was never asked to do into its health."""
        store.save_playbook(TestItWillNotActOnTheWrongOne().a_reading_trail("billing"))
        before = store.load_playbook(SITE).steps[1].locators[0].value

        Executor(store, browser).run(
            SITE, task="read the shipping address", start_url=f"{demo_server}/settings"
        )

        assert store.load_playbook(SITE).steps[1].locators[0].value == before == "#billing-email"

    def test_and_its_run_count_is_not_moved_by_someone_else_s_question(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        store.save_playbook(TestItWillNotActOnTheWrongOne().a_reading_trail("billing"))
        before = store.load_playbook(SITE).runs

        Executor(store, browser).run(
            SITE, task="read the shipping address", start_url=f"{demo_server}/settings"
        )

        assert store.load_playbook(SITE).runs == before


class TestOrdinaryReplayIsUntouched:
    def test_asking_for_what_the_trail_is_named_still_just_runs(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        store.save_playbook(TestItWillNotActOnTheWrongOne().a_reading_trail("billing"))

        result = Executor(store, browser).run(
            SITE, task="read the billing address", start_url=f"{demo_server}/settings"
        )

        assert result.ok is True
        assert result.aimed_at is None

    def test_and_that_run_is_still_written_back(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        store.save_playbook(TestItWillNotActOnTheWrongOne().a_reading_trail("billing"))
        before = store.load_playbook(SITE).runs

        Executor(store, browser).run(
            SITE, task="read the billing address", start_url=f"{demo_server}/settings"
        )

        assert store.load_playbook(SITE).runs == before + 1


class TestItDoesNotDisturbTheMatchingThatAlreadyWorked:
    """Two gates, and the second one is what protects the rephrasings.

    `swapped_subject` only asks "did exactly one word change?", which is true of a
    rephrasing too — "tell" for "read". What stops it becoming a swap is `with_subject`
    finding that word written nowhere in the trail. Both gates matter; neither alone is
    enough.
    """

    @pytest.mark.parametrize(
        ("asked", "trail"),
        [
            ("how many open issues does playwright have", "count open issues on playwright"),
            ("tell me the first quote", "read the first quote"),
        ],
    )
    def test_a_rephrasing_never_reaches_the_second_gate(self, asked: str, trail: str) -> None:
        """Every one of these was measured and fixed before. None may reopen."""
        swap = swapped_subject(asked, trail)
        if swap is None:
            return
        assert with_subject(a_trail(subject="ankush"), *swap) is None

    def test_a_real_swap_passes_both(self) -> None:
        swap = swapped_subject("message riya", "message ankush")

        assert swap == ("ankush", "riya")
        assert with_subject(a_trail(subject="ankush"), *swap) is not None
