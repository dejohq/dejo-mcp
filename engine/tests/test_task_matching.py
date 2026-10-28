"""A site's only trail must not answer a request that merely starts with the same verb.

Found in real use: docs.google.com held one trail, "read the full text of a Google Doc".
Asked to "read the keywords tab of the Sheet", Dejo replayed it, because both share the
word "read", and the run reported the wrong document's text as the answer.
"""

from __future__ import annotations

import pytest

from dejo.models import Playbook, Postcondition, Step
from dejo.store import DejoStore, best_match, shares_meaning, swapped_subject

DOCS = "docs.google.com"


class TestSharedMeaning:
    def test_sharing_only_an_action_word_is_not_the_same_job(self) -> None:
        asked = "read the keywords tab of the Sheet"
        saved = "read the full text of a Google Doc"
        assert not shares_meaning(asked, saved, DOCS)

    @pytest.mark.parametrize(
        ("asked", "saved"),
        [
            ("open the billing page", "open the team settings"),
            ("download the report", "download the invoice for march and april"),
            ("check my inbox and the spam folder", "check the server status page"),
        ],
    )
    def test_other_verb_only_overlaps_are_refused(self, asked: str, saved: str) -> None:
        assert not shares_meaning(asked, saved)

    def test_sharing_what_the_job_is_about_still_matches(self) -> None:
        assert shares_meaning("how many open issues does it have", "count open issues")

    def test_a_swapped_subject_still_matches(self) -> None:
        """The same route aimed at someone else is handled downstream as a swap."""
        assert shares_meaning("message riya", "message ankush")
        assert shares_meaning("read inbox", "read invoices")

    def test_nothing_in_common_is_still_refused(self) -> None:
        assert not shares_meaning("cancel my subscription", "count open issues")


def test_the_only_trail_is_not_replayed_for_a_different_job(tmp_path) -> None:
    store = DejoStore(db_path=str(tmp_path / "memory.db"))
    store.save_playbook(
        Playbook(
            domain=DOCS,
            task="read the full text of a Google Doc",
            steps=[
                Step(
                    index=1,
                    intent="open the document",
                    action="goto",
                    value=f"https://{DOCS}/document/d/abc",
                    postcondition=Postcondition("url_contains", "/document/"),
                )
            ],
        )
    )
    assert store.load_playbook(DOCS, "read the keywords tab of the Sheet") is None
    assert store.load_playbook(DOCS, "read the full text of the Google Doc") is not None
    assert store.load_playbook(DOCS) is not None


class TestWhatTheTaskDoes:
    """28 Oct, launchit.site: a brand-new task to submit a product replayed the site's only
    trail, a sign-in, because the two names shared the product's name. A task that does
    something else is another job, whatever words it shares."""

    @pytest.mark.parametrize(
        ("asked", "saved"),
        [
            ("submit Dejo to launchit", "sign in to launchit for Dejo"),
            ("submit Dejo to launchit", "log in to launchit with Google to list Dejo"),
            ("download the invoice", "delete the invoice"),
            ("what is the invoice total", "delete the invoice"),
            ("cancel the order for Dejo", "buy Dejo"),
        ],
    )
    def test_a_different_deed_is_a_different_job(self, asked: str, saved: str) -> None:
        assert not shares_meaning(asked, saved, "launchit.site")
        assert best_match(asked, [saved, "count the visitors"], domain="launchit.site") is None

    @pytest.mark.parametrize(
        ("asked", "saved"),
        [
            ("sign in and download this month's invoice", "download this month's invoice"),
            ("open the settings and delete my account", "delete my account"),
            ("how do I cancel my subscription", "cancel my subscription"),
            ("submit Dejo to launchit", "publish Dejo on launchit"),
        ],
    )
    def test_the_same_deed_in_other_words_still_matches(self, asked: str, saved: str) -> None:
        assert shares_meaning(asked, saved, "launchit.site")

    def test_a_deed_is_never_taken_for_a_new_subject(self) -> None:
        """ "delete riya" against "remove riya" is a rewording, not riya swapped for
        someone: swapping "remove" into the trail's steps would aim them at nothing."""
        assert swapped_subject("delete riya", "remove riya") is None


def test_a_new_task_is_not_given_the_only_trail_when_it_does_another_thing(tmp_path) -> None:
    store = DejoStore(db_path=str(tmp_path / "memory.db"))
    store.save_playbook(
        Playbook(
            domain="launchit.site",
            task="sign in to launchit for Dejo",
            steps=[
                Step(
                    index=1,
                    intent="open the sign-in page",
                    action="goto",
                    value="https://launchit.site/register",
                    postcondition=Postcondition("url_contains", "/register"),
                )
            ],
        )
    )
    assert store.load_playbook("launchit.site", "submit Dejo to launchit") is None
    assert store.load_playbook("launchit.site", "log in to launchit for Dejo") is not None
