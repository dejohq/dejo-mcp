"""The shapes Dejo remembers.

Everything here is a plain dataclass with an explicit `to_dict` / `from_dict`, because
these objects are written into Sibyl Memory as JSON bodies. Keeping the serialisation
explicit means the stored shape is a deliberate decision, not a side effect of whatever
library we happen to use.

Nothing in this module talks to memory. That is `store.py`, and only `store.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

LocatorKind = Literal[
    "test_id",
    "structural",
    "label",
    "role",
    "placeholder",
    "alt",
    "title",
    "text",
    "css",
]

# Actions that put text into a field. What was typed is the caller's own business, so it
# never travels to another agent.
_TYPED_INTO_A_FIELD = frozenset({"fill", "type"})

# Below this many steps, the broken-share is meaningless and a trail is never retired
# for being stale. It is repaired instead, which is recoverable.
MIN_STEPS_TO_JUDGE_STALE = 3

# How much a single confirmed hit or miss moves a locator's health.
_HIT_WEIGHT = 1.0
_MISS_WEIGHT = 2.0  # a miss is worse news than a hit is good news

# --- the map -------------------------------------------------------------------------
#
# A map grows every time Dejo looks at a page, so it is the one shape here that could
# grow without end. That matters more than it looks: Sibyl's free tier caps the whole
# DATABASE at 5 MB, its search index roughly doubles every body, and the resulting error
# is database-wide. An unbounded map would not just spoil itself — it would stop trails,
# site knowledge and the commons from being written at all, mid-run. These two numbers
# are the guard, and a test holds them.
#
# Forty pages and fifty controls each measures at ~230 KB of JSON, and Sibyl's search
# index roughly doubles that. Sixty pages was the first guess; it made one site cost
# nearly half a megabyte, which is a lot to spend on one site inside a 5 MB database.
# Ids collapse to `:id`, so forty DISTINCT pages is a large application, not a small one.
MAX_PAGES_PER_SITE = 40
# Raised from 30 after the first real site. GitHub's repository page offers well over
# sixty controls, and keeping thirty meant keeping the global header and almost nothing
# belonging to the page itself — a map made of chrome. Document order is still what
# survives, because a site's own navigation comes first on nearly every page.
MAX_CONTROLS_PER_PAGE = 50

# Long enough for a person to recognise the page, short enough that sixty of them cost
# nothing. Element names are already cut to 80 by the snapshot, so this matches.
MAX_TITLE = 80

# Path segments that are an identity rather than a place. Without these the map fills up
# with /requests/1, /requests/2, /requests/3 and learns nothing from any of them.
# Anything that is only digits and separators: 1234, 2026-09, 2024-01-15, 12_34. Real
# sites key on dates and periods as often as on numbers, and `/invoices/2026-09` is one
# page visited twelve times a year, not twelve pages. A segment with a letter in it is
# left alone, so `v2` and `requests` survive.
_ALL_DIGITS = re.compile(r"^(?=.*\d)[\d\-_.]+$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_LONG_HEX = re.compile(r"^[0-9a-f]{16,}$", re.I)  # Mongo-style ids and hashes
_ID_MARKER = ":id"

# A path segment that names a sign-in or sign-up page: the word alone, or followed by what
# is not a letter (/login.php, /oauth2, /sign_in-oidc), so /authors is never one.
_SIGN_IN_SEGMENT = re.compile(
    r"^(log[-_]?in|log[-_]?on|sign[-_]?in|sign[-_]?on|sign[-_]?up|register|auth|authn"
    r"|authorize|authenticate|sso|oauth|openid)(?![a-z])",
    re.I,
)


def _field_name(intent: str) -> str:
    """A name for the value a borrowed step will need, taken from what the step is for.

    "type the account email" becomes "email". It only has to be recognisable to a person
    setting an environment variable, so the last meaningful word is enough.
    """
    words = [
        word
        for word in "".join(
            character if character.isalnum() else " " for character in intent.lower()
        ).split()
        if word not in {"the", "a", "an", "in", "into", "my", "your", "type", "fill"}
    ]
    return words[-1] if words else "value"


def href_path(href: str) -> str:
    """The stable part of a link target: no query string, no fragment.

    Real sites hang session ids and tracking parameters off their links, and the demo site
    carries `?variant=`. Pinning a locator to the full href would make it miss for reasons
    that have nothing to do with the site changing. Same reasoning as postconditions
    matching on path rather than whole URL.
    """
    parsed = urlparse(href)
    return parsed.path or href


def link_target(href: str) -> str:
    """Where a link points, in the form the page itself wrote it.

    Query strings and fragments still go — those carry session ids and tracking, and the
    demo site hangs `?variant=` off every link. The HOST stays, which `href_path` throws
    away, and that difference is a real bug this fixed: GitHub writes its own nav links
    absolutely, so a locator built from the stripped path — `[href="/pricing"]` — could
    never match `href="https://github.com/pricing"` and silently missed every time.

    It matters twice over for the map: without the host, a link to another site is
    recorded as though it were a page of this one.
    """
    parsed = urlparse(href)
    if parsed.scheme or parsed.netloc:
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return parsed.path or href


def page_path(url: str) -> str:
    """The identity of a page, as a place rather than one visit to it.

    `/requests/1234/edit?tab=notes` is the same PAGE as `/requests/5678/edit`. Keeping them
    apart would fill the map with a hundred copies of one screen and teach it nothing, so a
    segment that is plainly an identity — digits, a uuid, a long hash, an email address —
    becomes `:id`.

    The email rule earns its place twice: it stops `/users/someone@example.com/settings`
    multiplying, and it keeps a person's address out of a map that can now be shared.
    """
    path = urlparse(url).path or "/"
    segments = [_generalise(segment) for segment in path.split("/")]
    joined = "/".join(segments)
    return joined if joined.startswith("/") else f"/{joined}"


def signs_in_at(address: str) -> bool:
    """Is this the address of a page a person signs in or signs up on?

    Read from whole path segments, so /authors and /registry are not sign-ins and
    /Login.aspx, /oauth2 and Google's /v3/signin/identifier are. A sign-up page counts:
    launchit.site's "Continue with Google" is on /register (28 Oct).
    """
    return any(_SIGN_IN_SEGMENT.match(segment) for segment in urlparse(address).path.split("/"))


def _generalise(segment: str) -> str:
    """One path segment: itself, or `:id` if it names a particular thing."""
    if not segment:
        return segment
    if "@" in segment:
        return _ID_MARKER
    if _ALL_DIGITS.match(segment) or _UUID.match(segment) or _LONG_HEX.match(segment):
        return _ID_MARKER
    return segment


def _confidence(hits: int, misses: int) -> float:
    """0.0 to 1.0, from a track record. Nothing unproven is ever trusted or condemned.

    Shared by locators and by steps that have none, so the two cannot drift apart.
    """
    attempts = hits + misses
    if attempts == 0:
        return 0.5
    score = (hits * _HIT_WEIGHT) - (misses * _MISS_WEIGHT)
    return max(0.0, min(1.0, score / (attempts * _HIT_WEIGHT)))


def utc_now() -> str:
    """One timestamp format everywhere: ISO 8601, UTC, seconds precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass
class Locator:
    """One way to find an element on the page.

    A step keeps several of these, ranked. Replay tries them in order, so when a site
    changes its CSS but keeps its accessible name, the role locator still lands and the
    step survives without any repair at all.
    """

    kind: LocatorKind
    value: str
    # Refinements. These are not kinds of their own because they compose with every kind:
    # "the third row" and "the row containing September" are narrowings of any locator, not
    # separate ways of searching.
    nth: int | None = None
    """Which match to take when several look alike. 0 is the first, -1 the last."""
    has_text: str | None = None
    """Narrow to the match containing this text — how you find one row in a list."""
    frame: str | None = None
    """CSS selector for the iframe this element lives in, if it is inside one.

    Without it the locator is unresolvable: `page.locator` does not look inside iframes, so
    a selector recorded in one would simply find nothing on the next run."""
    hits: int = 0
    misses: int = 0
    last_ok: str | None = None

    @property
    def confidence(self) -> float:
        """0.0 to 1.0. Unproven locators start neutral rather than perfect."""
        return _confidence(self.hits, self.misses)

    def record_hit(self) -> None:
        self.hits += 1
        self.last_ok = utc_now()

    def record_miss(self) -> None:
        self.misses += 1

    @property
    def is_dead(self) -> bool:
        """Has failed and has nothing to show for it, so it is not worth keeping.

        A locator that once worked survives a single miss, so a one-off failure never kills
        a proven route: it stays behind a repair as a backup, for a site that moves back.
        One whose misses outnumber its hits is just weight in the trail. This used to be
        "confidence is zero", and a miss weighs twice a hit, so a locator with one or two
        hits died on its first miss and every repair threw away the route that had worked.
        """
        return self.misses > self.hits

    def describe(self) -> str:
        """How this locator reads in a repair request or an export."""
        written = f"{self.kind}={self.value}"
        if self.frame:
            written = f"in frame {self.frame} {written}"
        if self.has_text:
            written += f" containing {self.has_text!r}"
        if self.nth is not None:
            written += f" [{self.nth}]"
        return written

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value,
            **({"nth": self.nth} if self.nth is not None else {}),
            **({"has_text": self.has_text} if self.has_text else {}),
            **({"frame": self.frame} if self.frame else {}),
            "hits": self.hits,
            "misses": self.misses,
            "last_ok": self.last_ok,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Locator:
        return cls(
            kind=raw["kind"],
            value=raw["value"],
            nth=raw.get("nth"),
            has_text=raw.get("has_text"),
            frame=raw.get("frame"),
            hits=raw.get("hits", 0),
            misses=raw.get("misses", 0),
            last_ok=raw.get("last_ok"),
        )


@dataclass
class Postcondition:
    """What must be true after a step, for the step to count as landed.

    This is the line between Dejo and a macro recorder. A recorder clicks and hopes.
    Dejo checks that the page actually moved, which is how it knows a site changed
    instead of silently doing nothing.
    """

    kind: Literal[
        "url_contains",
        "text_present",
        "text_gone",
        "element_present",
        "element_gone",
        "download",
        "value_is",
        "checked_is",
        "count_is",
        "attribute_is",
    ]
    value: str
    # Which element to look at, for the kinds that check one. The older kinds carry their
    # selector in `value`, so this stays optional and old saved playbooks still load.
    target: str | None = None

    def to_dict(self) -> dict[str, Any]:
        written: dict[str, Any] = {"kind": self.kind, "value": self.value}
        if self.target:
            written["target"] = self.target
        return written

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Postcondition:
        return cls(kind=raw["kind"], value=raw["value"], target=raw.get("target"))


@dataclass
class Step:
    """One move along the trail: what we meant, what we did, how to find it again."""

    index: int
    intent: str
    # Any action in the registry. Kept as a plain str so adding one never means editing
    # a type in a second file — `actions.spec_for` is what rejects a bad name.
    action: str
    postcondition: Postcondition
    locators: list[Locator] = field(default_factory=list)
    value: str | None = None
    repairs: int = 0

    dialog_message: str | None = None
    """The exact words of the confirm box this step answered, if there was one."""
    dialog_choice: str | None = None
    """What was answered: "accept" or "dismiss".

    Both are stored because the choice alone is not safe to replay. A step that recorded
    "click OK" must never blindly accept a box that now reads "delete 400 rows?" — so on
    replay a changed message stops the run instead of answering it."""

    secret: str | None = None
    """Names a value this step needs but must never remember, such as "password".

    When this is set, `value` stays empty and the real value is looked up on the machine
    running the replay. A password in a memory file is a password in a backup, a sync
    folder and a support ticket."""

    page: str = ""
    """The page this step was performed on, as a path.

    Without it, replay cannot tell "this control moved" from "we are on a completely
    different page" — and the second one, reported as the first, invites a repair that
    binds a healthy step to whatever happened to be lying around. Replaying a sign-in
    while already signed in lands on a dashboard and offered twenty-three nav links and
    stat tiles as candidates for an email field.

    Empty on trails saved before this existed, which simply opt out of the check."""

    answered: bool = False
    """Did this READ produce something when the trail was learned?

    A remembered read exists to hand back an answer. If it answered once and comes back
    empty now, the page has moved under it — and because the element still resolved, every
    check passed and the run reported success while returning nothing at all. Seen on a
    real shop, where a stored link locator matched nine product cards and replay read the
    empty one."""

    risky: bool = False
    """The agent marked this step as one that buys, pays, sends, deletes or submits.

    Replay still runs it, since the user asked for the task, but every reply names it so
    nobody is surprised, and nothing ever runs it twice on its own after a later step fails."""

    clears_away: bool = False
    """When learned, this press only took its own element off the page: the address and the
    words stayed as they were. A cookie banner's "Accept" is the usual one. On a visit where
    the banner is not shown at all there is nothing to clear, so a replay that finds nothing
    for this step skips it, as long as the next step can go ahead without it (bench T07)."""

    hits: int = 0
    misses: int = 0
    """This step's own record, used only when it has no locators to speak for it.

    A `goto` carries its destination in the step, not in a locator, and a page-level read
    names no element either. Scoring those zero — which is what "no locators" used to
    mean — made every trail containing one permanently part-broken."""

    @property
    def health(self) -> float:
        """How much this step can be trusted, 0 to 1.

        Normally the best locator we have. A step with no locators is not broken — it
        simply has nothing to find — so it keeps its own record instead, and starts
        neutral rather than at zero.
        """
        if self.locators:
            return max(loc.confidence for loc in self.locators)
        return _confidence(self.hits, self.misses)

    def record_hit(self) -> None:
        self.hits += 1

    def record_miss(self) -> None:
        self.misses += 1

    def without_what_was_typed(self) -> Step:
        """This step with the typed text removed, for handing to another agent.

        `value` on a `fill` or `type` step is the literal thing that went into the box —
        an email address, an account number. It never leaves. The step keeps its shape and
        is marked as needing a value, so the borrower is asked for its own.
        """
        if self.action not in _TYPED_INTO_A_FIELD or self.value is None:
            return self

        return replace(
            self,
            value=None,
            secret=self.secret or _field_name(self.intent),
            postcondition=self._check_without_the_value(),
            locators=list(self.locators),
        )

    def _check_without_the_value(self) -> Postcondition:
        """The step's check, with the typed text taken out of it.

        A `value_is` check literally holds what was typed — so redacting the step and
        leaving the check behind would publish the thing twice over. It cannot survive
        sharing anyway: the borrower is going to type something else.

        What replaces it is "the field is still there", which is what a `fill` step is
        checked with in the ordinary case. If there is nothing safe to point at, the only
        remaining check is that the locator resolved at all — which the replay loop already
        enforces before this is ever reached.
        """
        if not self.value or self.value not in self.postcondition.value:
            return self.postcondition

        where = self.postcondition.target or next(
            (locator.value for locator in self.locators if locator.kind == "css"), ""
        )
        if where:
            return Postcondition("element_present", where)
        return Postcondition("url_contains", "")

    def ranked_locators(self) -> list[Locator]:
        """Most trustworthy first. Replay walks this order and stops at the first hit."""
        return sorted(self.locators, key=lambda loc: loc.confidence, reverse=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "intent": self.intent,
            "action": self.action,
            "value": self.value,
            "postcondition": self.postcondition.to_dict(),
            "locators": [loc.to_dict() for loc in self.locators],
            "repairs": self.repairs,
            "secret": self.secret,
            "page": self.page,
            "answered": self.answered,
            "hits": self.hits,
            "misses": self.misses,
            "dialog_message": self.dialog_message,
            "dialog_choice": self.dialog_choice,
            "risky": self.risky,
            "clears_away": self.clears_away,
            "health": round(self.health, 3),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Step:
        return cls(
            index=raw["index"],
            intent=raw["intent"],
            action=raw["action"],
            value=raw.get("value"),
            postcondition=Postcondition.from_dict(raw["postcondition"]),
            locators=[Locator.from_dict(loc) for loc in raw.get("locators", [])],
            repairs=raw.get("repairs", 0),
            secret=raw.get("secret"),
            page=raw.get("page", ""),
            answered=raw.get("answered", False),
            hits=raw.get("hits", 0),
            misses=raw.get("misses", 0),
            dialog_message=raw.get("dialog_message"),
            dialog_choice=raw.get("dialog_choice"),
            risky=raw.get("risky", False),
            clears_away=raw.get("clears_away", False),
        )


@dataclass
class Playbook:
    """The trail for one task on one site. This is the thing memory holds."""

    domain: str
    task: str
    steps: list[Step] = field(default_factory=list)
    version: int = 1
    runs: int = 0
    repairs: int = 0
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    origin_agent: str | None = None
    """Who first walked this site. Survives every later borrow, so credit does not drift."""
    borrowed_from: str | None = None
    """Who this copy came from, if it was not learned here."""
    contributors: list[str] = field(default_factory=list)
    """Agents who repaired a step in it after the first one wrote it."""
    inherited_runs: int = 0
    """How many clean runs it had behind it when it was borrowed.

    Kept separate from `runs`, which is reset on borrow. A borrowed trail arriving with
    `runs=9` would make the borrower's own journal say something untrue."""

    @property
    def health(self) -> float:
        """Average step health. Used to decide when a playbook is past saving."""
        if not self.steps:
            return 0.0
        return sum(step.health for step in self.steps) / len(self.steps)

    @property
    def is_stale(self) -> bool:
        """More than half the trail is broken — the site has moved on, not drifted.

        A very short trail is exempt. One broken step out of one is 100%, and retiring on
        that is how a perfectly healthy site gets declared rebuilt: found on GitHub, where
        asking about a different repo destroyed the trail for the whole site. A short trail
        gets repaired instead, which is recoverable; retiring is not.
        """
        if not self.steps:
            return True
        if len(self.steps) < MIN_STEPS_TO_JUDGE_STALE:
            return False
        broken = sum(1 for step in self.steps if step.health < 0.5)
        return broken > len(self.steps) / 2

    def for_sharing(self, agent: str | None) -> Playbook:
        """A copy of this trail with everything personal taken out of it.

        The route survives. The identity does not: whatever was typed into a field leaves,
        and the step is marked as needing a value instead — the same mechanism a password
        already uses, so the borrower is asked for its own and told exactly where to put
        it. A shared login trail signs in as whoever is following it.
        """
        return Playbook(
            domain=self.domain,
            task=self.task,
            steps=[step.without_what_was_typed() for step in self.steps],
            version=self.version,
            runs=self.runs,
            repairs=self.repairs,
            created_at=self.created_at,
            updated_at=self.updated_at,
            origin_agent=self.origin_agent or agent,
            contributors=list(self.contributors),
        )

    def as_borrowed_by(self, agent: str | None, *, shared_by: str | None) -> Playbook:
        """This trail, rewritten as the borrower's own copy.

        The locators keep the hits and misses they earned elsewhere — that evidence is the
        whole point of borrowing, and it is what lets the borrower's first replay try the
        route that is already known to work. The RUN counters do not: they belong to the
        agent that did the running, and carrying them over would make the borrower's
        journal claim runs it never made.
        """
        return Playbook(
            domain=self.domain,
            task=self.task,
            steps=self.steps,
            version=self.version,
            runs=0,
            repairs=0,
            created_at=self.created_at,
            origin_agent=self.origin_agent or shared_by,
            borrowed_from=shared_by,
            contributors=list(self.contributors),
            inherited_runs=self.runs,
        )

    def touch(self) -> None:
        self.updated_at = utc_now()
        self.version += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "task": self.task,
            "version": self.version,
            "runs": self.runs,
            "repairs": self.repairs,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "health": round(self.health, 3),
            "steps": [step.to_dict() for step in self.steps],
            "origin_agent": self.origin_agent,
            "borrowed_from": self.borrowed_from,
            "contributors": self.contributors,
            "inherited_runs": self.inherited_runs,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Playbook:
        return cls(
            domain=raw["domain"],
            task=raw["task"],
            steps=[Step.from_dict(step) for step in raw.get("steps", [])],
            version=raw.get("version", 1),
            runs=raw.get("runs", 0),
            repairs=raw.get("repairs", 0),
            origin_agent=raw.get("origin_agent"),
            borrowed_from=raw.get("borrowed_from"),
            contributors=list(raw.get("contributors", [])),
            inherited_runs=raw.get("inherited_runs", 0),
            created_at=raw.get("created_at", utc_now()),
            updated_at=raw.get("updated_at", utc_now()),
        )


@dataclass
class SiteKnowledge:
    """Facts about a site that outlive any particular trail.

    A redesign throws away the playbook's locators but not the fact that the site needs
    two-factor, or which account you log in with, or that it locks you out after five
    wrong passwords. Keeping these separate is why relearning a rebuilt site is cheaper
    than a first visit — and it is the reason throwing a stale trail away is safe.

    `notes` is free text on purpose. The useful facts about a real site do not fit a
    fixed set of fields: "the invoice only appears after the 3rd", "the export takes two
    minutes", "use the finance login, not the admin one". A closed schema would only
    capture the easy ones.
    """

    domain: str
    notes: list[str] = field(default_factory=list)
    needs_login: bool = False
    needs_2fa: bool = False
    account_hint: str | None = None
    overlays: list[str] = field(default_factory=list)
    """Things that pop up over the page at unpredictable moments — cookie banners, "rate
    us", survey invitations. Learned once, then cleared automatically forever after.

    This belongs to the site and not to any one trail: an overlay appears on whichever step
    happens to be running when it decides to show up, so pinning it to a step would be
    recording an accident."""
    updated_at: str = field(default_factory=utc_now)

    def merge(
        self,
        *,
        fact: str | None = None,
        needs_login: bool | None = None,
        needs_2fa: bool | None = None,
        account_hint: str | None = None,
        overlay: str | None = None,
    ) -> SiteKnowledge:
        """Add to what is known. Never replaces the whole record.

        Facts arrive one at a time, from different visits. Overwriting would mean the
        last thing noticed erases everything learned before it.
        """
        if fact:
            cleaned = fact.strip()
            if cleaned and cleaned not in self.notes:
                self.notes.append(cleaned)
        if overlay and overlay not in self.overlays:
            self.overlays.append(overlay)
        if needs_login is not None:
            self.needs_login = needs_login
        if needs_2fa is not None:
            self.needs_2fa = needs_2fa
        if account_hint:
            self.account_hint = account_hint
        self.updated_at = utc_now()
        return self

    @property
    def is_empty(self) -> bool:
        return not (self.notes or self.needs_login or self.needs_2fa or self.account_hint)

    def summary(self) -> list[str]:
        """What to hand an AI that is about to walk this site for the first time."""
        lines = list(self.notes)
        if self.needs_login:
            lines.append("this site needs a login")
        if self.needs_2fa:
            lines.append("this site asks for a second factor, such as a code")
        if self.account_hint:
            lines.append(f"the account used here is {self.account_hint}")
        return lines

    def for_sharing(self) -> SiteKnowledge:
        """What is safe to hand another agent.

        The notes go, because they are usually the most expensive thing here — "the badge
        is cached, trust the Open tab" is an hour of somebody's afternoon. The account
        does not: it names a person's login.

        Whoever shares this sees every note in the result, so nothing goes out unseen.
        """
        return SiteKnowledge(
            domain=self.domain,
            notes=list(self.notes),
            needs_login=self.needs_login,
            needs_2fa=self.needs_2fa,
            account_hint=None,
            overlays=list(self.overlays),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "notes": self.notes,
            "needs_login": self.needs_login,
            "needs_2fa": self.needs_2fa,
            "account_hint": self.account_hint,
            "overlays": self.overlays,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SiteKnowledge:
        return cls(
            domain=raw["domain"],
            notes=raw.get("notes", []),
            needs_login=raw.get("needs_login", False),
            needs_2fa=raw.get("needs_2fa", False),
            account_hint=raw.get("account_hint"),
            overlays=list(raw.get("overlays", [])),
            updated_at=raw.get("updated_at", utc_now()),
        )


def _ago(when: str) -> str:
    """How long ago, in words.

    Everything in a map is something Dejo saw ONCE, at a moment that has passed. Handing
    it back without saying when would be presenting a memory as the present tense, which is
    the one thing a map must never do.
    """
    try:
        then = datetime.fromisoformat(when)
    except ValueError:
        return "at some point"
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    seconds = (datetime.now(UTC) - then).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hours ago"
    return f"{int(seconds // 86400)} days ago"


@dataclass
class Control:
    """One thing on a page that could be acted on, as the map remembers it.

    Deliberately NOT a `Locator`. A locator belongs to a step and carries a track record of
    replaying that step. This is the weaker thing: proof that a control with this name was
    on this page when Dejo last looked. It is a starting point for exploring, never
    something replay trusts.

    There is no `ref` here, on purpose. A ref is only meaningful inside the snapshot that
    produced it, so storing one would hand a later run an address for a page that no longer
    exists.
    """

    role: str
    name: str
    href: str | None = None
    nth: int | None = None
    """Which one, among the controls of this role on the page that have NO name.

    Icon-only buttons — view, approve, reject, suspend — are exactly the controls that
    matter on an admin table, and they carry no text and no aria-label. Leaving them out
    meant the map listed everything except the things worth clicking, on the very page it
    was meant to save the most work on. Position is a weak way to name something, and far
    better than the control being absent."""
    last_seen: str = field(default_factory=utc_now)

    @property
    def identity(self) -> tuple[str, str, int]:
        """What makes two sightings the same control.

        Role and name for anything with a name. For the unnamed, position has to stand in,
        or every icon button on a page would be the same control as every other.
        """
        return (self.role, self.name, -1 if self.name else (self.nth or 0))

    @property
    def use(self) -> str:
        """How to say this control to `dejo_act`, as its `ref`."""
        if self.name:
            return f"role={self.role}|{self.name}"
        return f"role={self.role} >> nth={self.nth or 0}"

    def describe(self) -> str:
        """One line, for a person or an AI reading the map."""
        called = f"{self.name!r}" if self.name else f"(unnamed #{self.nth or 0})"
        return f"{self.role} {called}" + (f" -> {self.href}" if self.href else "")


@dataclass
class PageMemory:
    """One page Dejo has actually looked at, and what was on it.

    Only pages that were genuinely examined get in here. Dejo does not crawl, and a page
    nobody looked at has nothing worth remembering about it.
    """

    path: str
    title: str = ""
    controls: list[Control] = field(default_factory=list)
    first_seen: str = field(default_factory=utc_now)
    last_seen: str = field(default_factory=utc_now)

    def merge_controls(self, seen: list[Control]) -> PageMemory:
        """Add this visit's controls to what was already known. Never replaces.

        This is what makes one map per site work when a site shows different things to
        different logins. An admin sees twelve sidebar items where a customer saw seven;
        the union is kept, and each control remembers when it was last actually there. No
        role is modelled anywhere — the timestamps carry that information honestly, and
        nothing has to be declared by the caller and got right.
        """
        known = {control.identity: control for control in self.controls}
        for fresh in seen:
            already = known.get(fresh.identity)
            if already is None:
                self.controls.append(fresh)
                known[fresh.identity] = fresh
                continue
            already.last_seen = fresh.last_seen
            if fresh.href:
                already.href = fresh.href
        self._trim_controls()
        self.last_seen = utc_now()
        return self

    def _trim_controls(self) -> None:
        """Stay under the cap by dropping what has not been seen for longest.

        Document order is kept for everything that survives, because that order puts a
        site's navigation first on nearly every page, and the navigation is the most useful
        part of a map.
        """
        if len(self.controls) <= MAX_CONTROLS_PER_PAGE:
            return
        survivors = sorted(self.controls, key=lambda control: control.last_seen, reverse=True)
        keep = {id(control) for control in survivors[:MAX_CONTROLS_PER_PAGE]}
        self.controls = [control for control in self.controls if id(control) in keep]

    def describe(self) -> str:
        """One line for the index: where it is, what it is called, how much is known."""
        named = f" — {self.title}" if self.title else ""
        return f"{self.path}{named} — {len(self.controls)} controls, seen {_ago(self.last_seen)}"

    def to_dict(self) -> dict[str, Any]:
        # A control's own `last_seen` is written only when it differs from the page's,
        # which is the rare case: almost every control is seen on the same visit as the
        # page it sits on. Sixty pages of repeated timestamps would be a third of the map's
        # size spent saying nothing.
        return {
            "path": self.path,
            "title": self.title,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "controls": [
                {
                    "role": control.role,
                    "name": control.name,
                    **({"nth": control.nth} if control.nth is not None else {}),
                    **({"href": control.href} if control.href else {}),
                    **(
                        {"last_seen": control.last_seen}
                        if control.last_seen != self.last_seen
                        else {}
                    ),
                }
                for control in self.controls
            ],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PageMemory:
        last_seen = raw.get("last_seen", utc_now())
        return cls(
            path=raw["path"],
            title=raw.get("title", ""),
            controls=[
                Control(
                    role=control["role"],
                    name=control["name"],
                    href=control.get("href"),
                    nth=control.get("nth"),
                    last_seen=control.get("last_seen", last_seen),
                )
                for control in raw.get("controls", [])
            ],
            first_seen=raw.get("first_seen", last_seen),
            last_seen=last_seen,
        )


@dataclass
class SiteMap:
    """Every page Dejo has looked at on one site.

    A trail is a route to one destination. This is the terrain around it — the thing a
    person picks up by walking somewhere once and paying attention on the way.

    It exists because Dejo's memory used to be keyed by (site, task) alone, so a second
    task on a site walked twenty times still started blind. Everything seen while doing the
    first task was thrown away. This is where it goes instead.

    Nothing here is ever presented as current. Each page carries when it was last seen, and
    the caller is told to verify as it goes, exactly as it would with a locator.
    """

    domain: str
    pages: list[PageMemory] = field(default_factory=list)
    updated_at: str = field(default_factory=utc_now)

    def page(self, path: str) -> PageMemory | None:
        """What is known about one page, or nothing."""
        wanted = page_path(path)
        return next((page for page in self.pages if page.path == wanted), None)

    def merge(
        self,
        *,
        url: str | None = None,
        title: str | None = None,
        controls: list[Control] | None = None,
    ) -> SiteMap:
        """Record one visit. Adds to what is known, never replaces it.

        Same contract as `SiteKnowledge.merge`: keyword-only, mutates and returns self, so
        several sightings from different visits accumulate instead of the last one winning.
        """
        if not url:
            return self
        path = page_path(url)
        page = self.page(path)
        if page is None:
            page = PageMemory(path=path)
            self.pages.append(page)
        if title:
            page.title = title.strip()[:MAX_TITLE]
        page.merge_controls(controls or [])
        self._trim_pages()
        self.updated_at = utc_now()
        return self

    def _trim_pages(self) -> None:
        """Stay under the cap by forgetting the pages nobody has been back to."""
        if len(self.pages) <= MAX_PAGES_PER_SITE:
            return
        self.pages.sort(key=lambda page: page.last_seen, reverse=True)
        del self.pages[MAX_PAGES_PER_SITE:]

    @property
    def is_empty(self) -> bool:
        return not self.pages

    def index(self) -> list[dict[str, Any]]:
        """The table of contents, newest first.

        The index goes out; the detail is fetched a page at a time. A forty-page map
        cannot travel inside every reply, and most of it is not relevant to any one task.
        """
        return [
            {
                "path": page.path,
                "title": page.title,
                "controls": len(page.controls),
                "last_seen": page.last_seen,
                "seen": _ago(page.last_seen),
            }
            for page in self._newest_first()
        ]

    def summary(self) -> list[str]:
        """The index as plain lines, for an AI or a person about to walk this site."""
        return [page.describe() for page in self._newest_first()]

    def _newest_first(self) -> list[PageMemory]:
        """Most recently seen first, with visit order breaking a tie.

        Timestamps are stored to the second, so two pages looked at in the same second
        carry the same one. Position is the honest tie-break: pages are appended in the
        order they were first walked, so the later one really was the later one.
        """
        ordered = sorted(
            enumerate(self.pages), key=lambda pair: (pair[1].last_seen, pair[0]), reverse=True
        )
        return [page for _, page in ordered]

    def for_sharing(self) -> SiteMap:
        """What is safe to hand another agent.

        The shape of a site is the valuable part and it travels whole. Paths have already
        had identities generalised away by `page_path`. The one extra cut here is a control
        whose NAME carries an email address — a signed-in header reading "someone@work.com"
        is a real thing on real sites, and it belongs to a person rather than to the site.

        Whoever shares this can read exactly what will go out first, with `dejo map`.
        """
        return SiteMap(
            domain=self.domain,
            pages=[
                PageMemory(
                    path=page.path,
                    title=page.title,
                    controls=[
                        replace(control) for control in page.controls if "@" not in control.name
                    ],
                    first_seen=page.first_seen,
                    last_seen=page.last_seen,
                )
                for page in self.pages
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "pages": [page.to_dict() for page in self.pages],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SiteMap:
        return cls(
            domain=raw["domain"],
            pages=[PageMemory.from_dict(page) for page in raw.get("pages", [])],
            updated_at=raw.get("updated_at", utc_now()),
        )


@dataclass
class RunMetrics:
    """What one run cost. The warm-versus-cold contrast is the whole pitch, so this
    is measured rather than asserted."""

    domain: str
    task: str
    mode: Literal["cold", "warm"]
    duration_ms: int = 0
    steps_total: int = 0
    steps_replayed: int = 0
    # How many times this TRAIL has ever been repaired. Not a per-run count: a run
    # never repairs anything. It stops at the broken step and hands that one step
    # back, and the fix arrives later as a separate call.
    trail_repairs: int = 0
    tool_calls: int = 0
    model_calls: int = 0
    pages_read: int = 0
    succeeded: bool = False
    started_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "task": self.task,
            "mode": self.mode,
            "duration_ms": self.duration_ms,
            "steps_total": self.steps_total,
            "steps_replayed": self.steps_replayed,
            "trail_repairs": self.trail_repairs,
            "tool_calls": self.tool_calls,
            "model_calls": self.model_calls,
            "pages_read": self.pages_read,
            "succeeded": self.succeeded,
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RunMetrics:
        return cls(
            domain=raw["domain"],
            task=raw["task"],
            mode=raw["mode"],
            duration_ms=raw.get("duration_ms", 0),
            steps_total=raw.get("steps_total", 0),
            steps_replayed=raw.get("steps_replayed", 0),
            trail_repairs=raw.get("trail_repairs", 0),
            tool_calls=raw.get("tool_calls", 0),
            model_calls=raw.get("model_calls", 0),
            pages_read=raw.get("pages_read", 0),
            succeeded=raw.get("succeeded", False),
            started_at=raw.get("started_at", utc_now()),
        )
