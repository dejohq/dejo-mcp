"""A site's only trail must not answer a request that merely starts with the same verb.

Found in real use: docs.google.com held one trail, "read the full text of a Google Doc".
Asked to "read the keywords tab of the Sheet", Dejo replayed it, because both share the
word "read", and the run reported the wrong document's text as the answer.
"""

from __future__ import annotations

import pytest

from dejo.models import Playbook, Postcondition, Step
from dejo.store import DejoStore, shares_meaning

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
