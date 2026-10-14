"""Tests for the shapes Dejo remembers.

These are pure — no browser, no memory, no network. They pin down the two rules that make
replay behave sensibly: how a locator earns trust, and when a trail is past saving.
"""

from __future__ import annotations

import pytest

from dejo.models import Locator, Playbook, Postcondition, RunMetrics, SiteKnowledge, Step


def step_with(*locators: Locator) -> Step:
    return Step(
        index=1,
        intent="download the PDF",
        action="click",
        postcondition=Postcondition("download", "invoice.pdf"),
        locators=list(locators),
    )


class TestLocatorConfidence:
    def test_an_unproven_locator_starts_neutral(self):
        """Not 1.0. A fresh guess must never outrank something with a track record."""
        assert Locator("css", "#new").confidence == 0.5

    def test_a_perfect_record_is_full_confidence(self):
        assert Locator("css", "#solid", hits=10).confidence == 1.0

    def test_a_miss_costs_more_than_a_hit_earns(self):
        """One failure should outweigh one success — being wrong is expensive."""
        even = Locator("css", "#flaky", hits=1, misses=1)

        assert even.confidence < 0.5

    def test_confidence_never_goes_negative(self):
        assert Locator("css", "#dead", hits=0, misses=9).confidence == 0.0

    def test_recording_a_hit_stamps_the_time(self):
        locator = Locator("role", "link|Download")

        locator.record_hit()

        assert locator.hits == 1
        assert locator.last_ok is not None


class TestStepRanking:
    def test_the_best_locator_comes_first(self):
        weak = Locator("css", "#maybe", hits=1, misses=4)
        strong = Locator("structural", "href=/file", hits=8)
        step = step_with(weak, strong)

        assert step.ranked_locators()[0] is strong

    def test_step_health_is_its_best_locator(self):
        """One working route is enough. A step is not the average of its options."""
        step = step_with(
            Locator("css", "#dead", misses=5), Locator("structural", "href=/f", hits=5)
        )

        assert step.health == 1.0

    def test_a_step_with_no_locators_is_neutral_not_broken(self):
        """This test used to assert 0.0, and 0.0 was the bug.

        A `goto` carries its destination in the step rather than in a locator, so it has
        none — and scoring that zero meant every trail containing one was permanently
        part-broken, and one step closer to being retired for staleness. Seen live: a
        brand new working GitHub trail reported health 0.25.
        """
        assert step_with().health == 0.5

    def test_a_step_with_no_locators_earns_a_record_of_its_own(self):
        step = step_with()
        step.record_hit()
        assert step.health == 1.0

        for _ in range(3):
            step.record_miss()
        assert step.health == 0.0


class TestPlaybookStaleness:
    def test_a_healthy_playbook_is_not_stale(self):
        playbook = Playbook(
            domain="example.com",
            task="t",
            steps=[step_with(Locator("css", "#ok", hits=5)) for _ in range(4)],
        )

        assert playbook.is_stale is False

    def test_a_mostly_broken_playbook_is_stale(self):
        """Past half broken it is not drift any more, the site was rebuilt."""
        broken = [step_with(Locator("css", "#gone", misses=5)) for _ in range(3)]
        working = [step_with(Locator("css", "#ok", hits=5))]

        assert Playbook(domain="e.com", task="t", steps=broken + working).is_stale is True

    def test_an_empty_playbook_is_stale(self):
        assert Playbook(domain="e.com", task="t").is_stale is True

    def test_touching_bumps_the_version(self):
        playbook = Playbook(domain="e.com", task="t")
        before = playbook.version

        playbook.touch()

        assert playbook.version == before + 1


class TestSerialisation:
    """These bodies are written to memory as JSON, so the shape has to survive a trip."""

    @pytest.mark.parametrize(
        "original",
        [
            Locator("role", "link|Download", hits=3, misses=1),
            Postcondition("url_contains", "/invoices"),
            RunMetrics(domain="e.com", task="t", mode="warm", steps_replayed=6),
            SiteKnowledge(domain="e.com", needs_2fa=True, notes=["slow"]),
        ],
    )
    def test_round_trips_through_a_dict(self, original):
        restored = type(original).from_dict(original.to_dict())

        assert restored == original

    def test_a_whole_playbook_round_trips(self):
        original = Playbook(
            domain="e.com",
            task="download the invoice",
            steps=[step_with(Locator("structural", "href=/file", hits=2))],
        )

        restored = Playbook.from_dict(original.to_dict())

        assert restored.domain == original.domain
        assert restored.steps[0].intent == original.steps[0].intent
        assert restored.steps[0].locators[0].hits == 2

    def test_health_is_stored_for_readers_but_recomputed_on_load(self):
        """`health` is derived. It is written so a human reading the JSON can see it,
        but it is never trusted on the way back in."""
        playbook = Playbook(
            domain="e.com", task="t", steps=[step_with(Locator("css", "#x", hits=4))]
        )
        body = playbook.to_dict()
        body["steps"][0]["health"] = 0.01

        assert Playbook.from_dict(body).steps[0].health == 1.0
