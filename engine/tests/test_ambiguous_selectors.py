"""A selector that matches several things is a question, not an instruction.

The worst bug Dejo has had. On a table with a menu button in every row,
`button[aria-haspopup="menu"]` matched all of them; Dejo clicked the first one and
returned ok. The person who reported it spent eight calls hunting a fault in their own
application that was never there.

It is worse than an ordinary wrong answer for two reasons. It reports SUCCESS, so nothing
downstream has any reason to doubt it. And `dejo_save` then writes it into a trail, where
it is replayed for ever.

Playwright refuses the same selector for the same reason. Dejo now does too — except for
the two reads whose whole purpose is to match many.
"""

from __future__ import annotations

import pytest

from dejo.browser import Browser
from dejo.operations import ActionFailed, Session
from dejo.store import DejoStore


@pytest.fixture
def hard(browser: Browser, store: DejoStore, demo_server: str) -> Session:
    """The hard page, which has plenty of buttons — the shape that caused this."""
    session = Session(browser=browser, store=store)
    session.act("open the hard page", "goto", value=f"{demo_server}/hard")
    return session


class TestItRefusesToGuess:
    def test_acting_on_an_ambiguous_selector_is_refused(self, hard: Session) -> None:
        with pytest.raises(ActionFailed) as refused:
            hard.act("press something", "click", ref="button")

        assert "matches" in str(refused.value)

    def test_and_says_how_many_there_were(self, hard: Session) -> None:
        """A count is the one thing that turns "it did the wrong thing" into "ah, of
        course" — without it the caller has no idea the selector was the problem."""
        with pytest.raises(ActionFailed) as refused:
            hard.act("press something", "click", ref="button")

        assert "elements on this page" in str(refused.value)

    def test_and_names_the_first_few_so_the_caller_can_choose(self, hard: Session) -> None:
        with pytest.raises(ActionFailed) as refused:
            hard.act("press something", "click", ref="button")

        said = str(refused.value)
        assert "0:" in said and "1:" in said

    def test_and_says_how_to_mean_one_of_them(self, hard: Session) -> None:
        with pytest.raises(ActionFailed) as refused:
            hard.act("press something", "click", ref="button")

        said = str(refused.value)
        assert "nth=0" in said, "the shortest fix has to be the one it names first"

    def test_reading_one_thing_is_refused_the_same_way(self, hard: Session) -> None:
        """Reading the first of several silently is how a caller comes to believe the
        wrong number, which is quieter and worse than a wrong click."""
        with pytest.raises(ActionFailed):
            hard.read("text", ref="button")


class TestSayingWhichOneYouMean:
    """Refusing is only half an answer. The message has to name a way through."""

    def test_nth_makes_an_ambiguous_selector_specific(self, hard: Session) -> None:
        assert hard.read("text", ref="button >> nth=0") == "Accept all"

    def test_and_the_same_selector_can_reach_a_different_one(self, hard: Session) -> None:
        first = hard.read("text", ref="button >> nth=0")
        second = hard.read("text", ref="button >> nth=1")

        assert first != second


class TestItStillDoesTheUnambiguousThing:
    def test_a_selector_matching_exactly_one_still_works(self, hard: Session) -> None:
        assert hard.read("text", ref="#pointer-menu-button") == "Row actions"

    def test_a_selector_matching_nothing_says_so(self, hard: Session) -> None:
        with pytest.raises(ActionFailed) as refused:
            hard.read("text", ref="#there-is-no-such-thing")

        assert "nothing on this page matches" in str(refused.value)


class TestTheReadsThatAreAboutMany:
    """`count` and `all_text` exist to match several. Refusing those would be nonsense."""

    def test_count_is_allowed_to_match_many(self, hard: Session) -> None:
        assert hard.read("count", ref="button") > 1

    def test_all_text_is_allowed_to_match_many(self, hard: Session) -> None:
        assert len(hard.read("all_text", ref="button")) > 1

    def test_all_text_survives_elements_with_no_text_at_all(self, hard: Session) -> None:
        """An icon button holds an `svg` and nothing else. Playwright answers None for
        those, and calling `.strip()` on it crashed with a message about NoneType that
        told the caller nothing about their page."""
        assert hard.read("all_text", ref="#pointer-menu button, #pointer-menu svg") is not None


class TestWhenTheRefIsNotASelectorAtAll:
    def test_a_plain_name_is_told_how_to_be_said_properly(self, hard: Session) -> None:
        """Reported as a papercut: passing the visible NAME of a control failed with "not
        a selector this page understands" and no hint that a name IS sayable."""
        with pytest.raises(ActionFailed) as refused:
            hard.act("press it", "click", ref="Next: Document Submission")

        said = str(refused.value)
        assert "role=button|" in said
        assert "site map" in said


class TestControlsWithNoNameOfTheirOwn:
    """The icon buttons in an admin table's rows: view, approve, reject, suspend.

    They carry no text and no aria-label, and the map used to leave them out entirely —
    listing the sidebar and the search box and none of the things anybody wanted to click,
    on exactly the page where a map should save the most work. Reported from a real
    marketplace. Position is a weak way to name a thing, and far better than absence.
    """

    def test_an_unnamed_control_is_kept_and_numbered(self, hard: Session) -> None:
        from dejo.operations import controls_in

        controls = controls_in(hard.browser.snapshot())
        unnamed = [control for control in controls if not control.name]

        assert unnamed, "the hard page has controls with no accessible name"
        assert unnamed[0].nth == 0

    def test_and_can_be_said_back_to_dejo_as_a_ref(self, hard: Session) -> None:
        from dejo.operations import controls_in

        unnamed = [c for c in controls_in(hard.browser.snapshot()) if not c.name]

        assert unnamed[0].use.startswith("role=")
        assert ">> nth=" in unnamed[0].use

    def test_a_named_control_is_still_said_by_its_name(self, hard: Session) -> None:
        from dejo.operations import controls_in

        named = [c for c in controls_in(hard.browser.snapshot()) if c.name]

        assert named[0].use == f"role={named[0].role}|{named[0].name}"

    def test_position_resolves_to_a_real_element(self, hard: Session) -> None:
        """The whole point: what the map hands back has to be actionable."""
        assert hard.read("visible", ref="role=button >> nth=0") is True


class TestWhenNothingMatchesAtAll:
    def test_a_label_is_told_the_form_that_would_have_worked(self, hard: Session) -> None:
        """ "Export Vendors CSV" is valid CSS — three tag names in a descendant chain — so
        Playwright does not reject it, it just finds nothing. The old message stopped at
        "nothing on this page matches": true, useless, and silent about the one form that
        works. A visible label is the most natural thing to reach for."""
        with pytest.raises(ActionFailed) as refused:
            hard.act("press it", "click", ref="Export Vendors CSV")

        said = str(refused.value)
        assert "role=button|Export Vendors CSV" in said
        assert "LABEL" in said

    def test_a_real_selector_that_finds_nothing_is_not_lectured_about_labels(
        self, hard: Session
    ) -> None:
        """`#no-such-id` is plainly a selector. Suggesting it might be a label would be
        noise on top of a clear message."""
        with pytest.raises(ActionFailed) as refused:
            hard.act("press it", "click", ref="#no-such-id")

        said = str(refused.value)
        assert "LABEL" not in said
        assert "look at the page again" in said.lower()
