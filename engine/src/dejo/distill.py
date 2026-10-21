"""Raw trace in, playbook out.

Distilling is where an exploratory run stops being a recording and becomes something that
can check itself. Two jobs:

1. **Give every step a postcondition**, derived from what actually changed when the step
   ran. No postcondition, no step — a step that cannot prove it landed is exactly the
   stale-cache behaviour this project exists to avoid.

2. **Keep several ways to find each element**, ranked. One selector is a single point of
   failure; four independent descriptors mean the usual cosmetic redesign costs nothing.
"""

from __future__ import annotations

from .models import Locator, Playbook, Postcondition, Step, href_path
from .operations import READ_ACTION, TraceEntry


def distill(trace: list[TraceEntry], *, domain: str, task: str) -> Playbook:
    """Build a playbook from what a cold run actually did."""
    steps = [
        Step(
            index=position,
            intent=entry.intent,
            action=entry.action,
            value=entry.value,
            secret=entry.secret,
            postcondition=entry.expect or postcondition_for(entry),
            locators=locators_for(entry),
            # Where this step happened. A goto has no "before", and needs none: it names
            # its own destination.
            page=href_path(entry.url_before) if entry.url_before else "",
            answered=bool(entry.answer),
            dialog_message=(entry.dialog or {}).get("message"),
            dialog_choice=(entry.dialog or {}).get("choice"),
            risky=entry.risky,
        )
        for position, entry in enumerate(trace, start=1)
    ]
    return Playbook(domain=domain, task=task, steps=steps)


def postcondition_for(entry: TraceEntry) -> Postcondition:
    """Pick the strongest honest signal that this step landed.

    Order matters. A download is unambiguous, a URL change is nearly so, and new text on
    the page is the weakest of the three — so we only fall back to text when nothing
    better is available.
    """
    if entry.action == READ_ACTION and entry.element is not None:
        # A read changes nothing. What has to still be true is that the thing being read
        # is there at all — if it is gone, the answer would be silently wrong.
        return Postcondition("element_present", entry.element.css)

    if entry.download:
        return Postcondition("download", entry.download)

    if entry.navigated and entry.element is not None and entry.element.by_place:
        return _landed_somewhere_like(entry)

    if entry.navigated or entry.action == "goto":
        # Where we LANDED, and — for a goto — where we asked to go, which are not always
        # the same place. MDN answers /Web/API/fetch with /Web/API/Window/fetch; sites add
        # a locale, a trailing slash, a canonical host. Recording only the landing spot
        # made a trail whose own `goto` could not satisfy its own check: replay went to
        # the URL it was told to, the site redirected, and the step was called broken on a
        # page that was perfectly correct. Either one arriving is arrival.
        asked = href_path(entry.value) if entry.action == "goto" and entry.value else None
        landed = href_path(entry.url_after)
        return Postcondition("url_contains", landed, target=asked if asked != landed else None)

    if entry.action == "fill" and entry.element is not None:
        # Nothing visibly changes when you type, so assert the field is still there.
        return Postcondition("element_present", entry.element.css)

    if entry.text_gained:
        return Postcondition("text_present", entry.text_gained)

    if entry.element is not None:
        return Postcondition("element_present", entry.element.css)

    return Postcondition("url_contains", href_path(entry.url_after))


def locators_for(entry: TraceEntry) -> list[Locator]:
    """Every way we know to find this element again, most durable first.

    `goto` has no element, so it carries none — its URL is in the step itself.
    """
    if entry.element is None:
        return []
    if entry.locators is not None:
        return entry.locators
    return entry.element.locators()


def _landed_somewhere_like(entry: TraceEntry) -> Postcondition:
    """The check for a step picked by its place in a list ("open the first book").

    Which page it lands on changes with the list: that is the point of storing it by place.
    Checking for the exact page it reached while learning (`/books/0`) called a correct
    replay broken the day another book was first. What stays true is the KIND of page, so
    the check is the landing path without its last part (`/books/`), as long as that tells
    it apart from where the step started. Otherwise the step is checked by the list it
    picked from being gone, which is what leaving the list page means.
    """
    landed = href_path(entry.url_after)
    parent = landed.rstrip("/").rsplit("/", 1)[0] + "/"
    if parent != "/" and parent not in href_path(entry.url_before) + "/":
        return Postcondition("url_contains", parent)
    assert entry.element is not None and entry.element.found_by is not None
    return Postcondition("element_gone", entry.element.found_by.value)
