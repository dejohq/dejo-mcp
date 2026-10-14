"""THE MEMORY FILE.

Every decision about what Dejo remembers is made here, and nothing else in the project
touches memory. If you want to see whether the memory is load-bearing, this one file is the
whole answer, and `forget_site` below is the deletion test. `memory.py` is the database
underneath; this file is its only user.

What is kept:

    entry    "playbook", <domain>::<task>   the trail: steps, locators, health
    entry    "site_knowledge", <domain>     facts that outlive a redesign
    entry    "site_map", <domain>           the pages Dejo has looked at
    history  every run, drift, repair, share and forget, in order

Two deliberate choices worth knowing about:

1. Entries are unique per (owner, category, name), enforced by the database itself. A site
   therefore cannot end up holding two conflicting trails for one task.

2. Forgetting ARCHIVES, it does not delete. The agent stops being able to follow the trail,
   but the record of it having existed is recoverable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .home import setting
from .memory import (
    AGENT_OWNER_PREFIX,
    COMMONS,
    DEFAULT_OWNER,
    DEFAULT_PATH,
    SIBYL_PATH,
    Database,
    OldMemoryUnreadable,
    SibylDatabase,
    import_sibyl,
)
from .models import Playbook, RunMetrics, SiteKnowledge, SiteMap, utc_now

PLAYBOOK = "playbook"

# Trails offered to other agents live with the `commons` owner in the same database. Every
# read and write names its owner, so publishing and borrowing are deliberate copies: nobody
# accidentally leaks a trail, and nobody silently inherits a stranger's.

# Offers live in their own category, keyed `domain::task::agent`. The agent is IN the key
# on purpose: keyed by task alone, one agent publishing would silently overwrite another's
# offer, and withdrawing would delete somebody else's work.
SHARED = "shared_playbook"

# What an agent with no name is called when it leaves a trail for somebody else.
UNNAMED = "default"

# What Dejo saw while walking a site: the pages it looked at and what was on them.
# Keyed by the bare domain, exactly like site knowledge, so that forgetting a site stays
# one line rather than a second key-scanning loop.
SITE_MAP = "site_map"

# A site this agent was deliberately told to forget. The commons will not offer it
# back without being asked a second time, on purpose.
FORGOTTEN = "forgotten"

# How an MCP server learns which agent it is. `run_stdio` takes no arguments, so an
# environment variable is the only channel `.mcp.json` has.
AGENT_ENV = "DEJO_AGENT"

# Which database holds the memory: Dejo's own unless this says "sibyl".
BACKEND_ENV = "DEJO_MEMORY"
SIBYL = "sibyl"

# A trail is named `domain::task-slug`. Keying on the domain alone meant one task per site.
# A domain never contains "::", so splitting on it is unambiguous.
KEY_SEPARATOR = "::"

# Long enough to tell two tasks apart, short enough to read in a listing.
MAX_SLUG = 60

# How much of a request's wording must be shared with a saved task before they are treated
# as the same job. Low enough to survive rephrasing, high enough that "download the
# invoice" never matches "cancel the subscription".
MATCH_THRESHOLD = 0.4

# Words too common to tell two tasks apart. "the invoice" and "the subscription" share
# "the" and nothing that matters.
_NOISE = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "does",
        "for",
        "from",
        "get",
        "how",
        "i",
        "in",
        "is",
        "it",
        "many",
        "me",
        "my",
        "of",
        "on",
        "or",
        "please",
        "show",
        "that",
        "the",
        "them",
        "then",
        "there",
        "this",
        "to",
        "what",
        "when",
        "where",
        "which",
        "with",
    ]
)
SITE_KNOWLEDGE = "site_knowledge"


class TrailAlreadyHere(RuntimeError):
    """Borrowing would flatten a trail this agent has already repaired."""


class DejoStore:
    """What Dejo remembers, in Dejo's own words: trails, site facts, maps, history.

    Deliberately not clever. Each method is one memory call plus serialisation, so the
    mapping between "what Dejo remembers" and "what is stored" stays readable.
    """

    def __init__(self, *, db_path: str | None = None, agent: str | None = None):
        """Uses `~/.dejo/memory.db` unless a path is given.

        Tests pass a temporary path so they never touch the developer's real memory.

        `agent` names this agent, and becomes the owner of its memory. Left unset, and unset
        is the normal case, it falls back to the `DEJO_AGENT` environment variable and then
        to the `default` owner, which is where every trail learned so far already lives.

        There are TWO views of the database and neither ever changes owner. One reads and
        writes this agent's own memory; the other only ever touches the commons. A single
        view that switched owner around each shared operation would be unsafe: the MCP
        server calls this object from several threads at once, so a switch has a window in
        which another thread's trail is written into the commons. Silently.
        """
        self.agent = agent if agent is not None else setting(AGENT_ENV)
        database = open_memory(db_path)
        self.where = database.path
        self._memory = database.owner(agent_owner(self.agent))
        self._shared = database.owner(COMMONS)

    # ---------------------------------------------------------------- playbooks

    def save_playbook(self, playbook: Playbook) -> None:
        """Write. One trail per TASK per site, overwritten as it improves.

        Keyed by task as well as domain. Keying on the domain alone meant a site could
        hold exactly one task ever — found on GitHub, where asking about a second repo
        collided with the first.
        """
        key = trail_key(playbook.domain, playbook.task)
        self._memory.put(PLAYBOOK, key, playbook.to_dict())

        # Knowing the site again is the opposite of having forgotten it.
        self._memory.archive(FORGOTTEN, playbook.domain, reason="learned again")

    def load_playbook(self, domain: str, task: str | None = None) -> Playbook | None:
        """Read. `None` means we have never walked this site — or it was forgotten.

        The warm path lives or dies on this call. If it returns `None`, replay has
        nothing to follow and the caller has to explore from scratch.

        With a task, the matching trail. Without one, the site's only trail — because a
        caller who does not name a task can only mean the single one that exists. If there
        are several, it has to say which; `trails_for` lists them.
        """
        if task:
            body = self._read_entity_body(PLAYBOOK, trail_key(domain, task))
            if body:
                return Playbook.from_dict(body)

        # Trails saved before trails were keyed by task are named by domain alone. Even a
        # legacy trail has to be the one being asked for: returning it whatever the caller
        # said is the "run the wrong task" accident this function exists to prevent.
        legacy = self._read_entity_body(PLAYBOOK, domain)
        if legacy and self._is_plausible(task, legacy, domain):
            return Playbook.from_dict(legacy)

        keys = self._keys_for(domain)

        # A site with ONE trail. Naming a task used to disable this fallback entirely, so
        # `dejo_run(site)` replayed and `dejo_run(site, task="...")` did not — naming the
        # task was strictly worse than staying silent, and the tool description tells the
        # caller to name it. Measured cost: a real model gave up and re-explored a site it
        # already knew, every single time.
        #
        # The guard that stays is the one that matters. A request sharing NO word with the
        # only trail is refused, so "cancel my subscription" can never run "count open
        # issues" — running the wrong trail is worse than admitting there is none.
        if len(keys) == 1:
            only = self._read_entity_body(PLAYBOOK, keys[0])
            if only and self._is_plausible(task, only, domain):
                return Playbook.from_dict(only)
            return None

        # Nobody words a request the same way twice. "how many open issues does
        # microsoft/playwright have" has to find the trail saved as "count open issues on
        # microsoft/playwright", or the memory may as well not be there.
        if task:
            closest = best_match(task, self.trails_for(domain), domain=domain)
            if closest:
                body = self._read_entity_body(PLAYBOOK, trail_key(domain, closest))
                return Playbook.from_dict(body) if body else None
        return None

    @staticmethod
    def _is_plausible(task: str | None, body: dict[str, Any], domain: str) -> bool:
        """Could this stored trail be the job that was asked for?

        A caller who named nothing can only mean whatever is there. A caller who named
        something has to share at least one meaningful word with it.
        """
        if not task:
            return True
        return shares_meaning(task, str(body.get("task", "")), domain)

    def trails_for(self, domain: str) -> list[str]:
        """The tasks this site has trails for, so a caller can say which one it means."""
        found = []
        for key in self._keys_for(domain):
            body = self._read_entity_body(PLAYBOOK, key)
            if body and body.get("task"):
                found.append(body["task"])
        return sorted(found)

    def _keys_for(self, domain: str) -> list[str]:
        """Every live trail key belonging to one site."""
        return [key for key in self._memory.names(PLAYBOOK) if domain_of_key(key) == domain]

    def list_sites(self) -> list[str]:
        """Every domain Dejo currently knows a trail for.

        Domains, not trail keys — one site with four tasks is still one site.
        """
        return sorted({domain_of_key(key) for key in self._memory.names(PLAYBOOK)})

    # ------------------------------------------------------------- the commons
    #
    # Everything below writes to a DIFFERENT owner through a SECOND view. Neither view
    # ever changes owner, so a trail cannot cross by accident.

    def was_forgotten(self, domain: str) -> bool:
        """Read. Did this agent deliberately forget this site?

        Asked before offering a shared trail back. Forgetting has to mean
        something, and answering "somebody else still has it" one message later
        is not it.
        """
        return self._read_entity_body(FORGOTTEN, domain) is not None

    def my_offers_for(self, domain: str) -> list[dict[str, Any]]:
        """COMMONS read. What THIS agent has published for this site."""
        return [offer for offer in self._offers(domain) if offer["shared_by"] == self.who]

    def share_trail(self, domain: str, task: str | None = None) -> dict[str, Any] | None:
        """COMMONS write. Leave this trail where another agent can pick it up.

        Returns what was published — every note included — so nothing goes out unseen.
        `None` means this agent has no such trail to give.

        What leaves is the route, never the identity: `Playbook.for_sharing` drops whatever
        was typed into a field and marks the step as needing a value instead, so whoever
        follows this signs in as themselves.
        """
        playbook = self.load_playbook(domain, task)
        if playbook is None:
            return None

        knowledge = self.load_site_knowledge(domain)
        publishable = knowledge.for_sharing() if knowledge else None
        # The shape of the site travels too. A trail is one route; the map is every page
        # this agent has looked at, which is what makes a BORROWED trail worth more than
        # the one task it replays — the borrower can go somewhere new on the same site
        # without walking it blind first.
        walked = self.load_site_map(domain)
        publishable_map = walked.for_sharing() if walked else None
        offer = {
            "domain": domain,
            "task": playbook.task,
            "shared_by": self.who,
            "shared_at": utc_now(),
            "playbook": playbook.for_sharing(self.agent).to_dict(),
            "site_knowledge": publishable.to_dict() if publishable else None,
            "site_map": publishable_map.to_dict() if publishable_map else None,
            "borrows": 0,
            "confirmed_by": [],
            "failed_for": [],
        }

        key = offer_key(domain, playbook.task, self.who)
        existing = self._offer(key)
        if existing:
            # Keep the ledger across a re-publish. The trail may have improved; the record
            # of who it has worked for is still true.
            for carried in ("borrows", "confirmed_by", "failed_for"):
                offer[carried] = existing.get(carried, offer[carried])

        self._shared.put(SHARED, key, offer)
        self._both_journals(
            acted=[f"{self.who} shared the trail for {playbook.task} on {domain}"],
            extra={"kind": "shared", "domain": domain, "task": playbook.task, "by": self.who},
        )
        return {
            "domain": domain,
            "task": playbook.task,
            "shared_by": self.who,
            "steps": len(playbook.steps),
            "notes_published": publishable.notes if publishable else [],
            "pages_published": [page.path for page in publishable_map.pages]
            if publishable_map
            else [],
            "values_withheld": [
                step.intent for step in playbook.steps if step.action in ("fill", "type")
            ],
        }

    def unshare_trail(self, domain: str, task: str | None = None) -> bool:
        """COMMONS write. Withdraw a trail THIS agent published.

        Only ever this agent's own offer — the key carries the publisher, so there is no
        way to reach into somebody else's.
        """
        wanted = task or ""
        for offer in self._offers(domain):
            if offer["shared_by"] != self.who:
                continue
            if wanted and offer["task"] != wanted and best_match(wanted, [offer["task"]]) is None:
                continue
            if not self._shared.archive(
                SHARED, offer_key(domain, offer["task"], self.who), reason="withdrawn"
            ):
                continue
            self._both_journals(
                acted=[f"{self.who} withdrew the trail for {offer['task']} on {domain}"],
                extra={"kind": "withdrawn", "domain": domain, "by": self.who},
            )
            return True
        return False

    def offers_for(self, domain: str) -> list[dict[str, Any]]:
        """COMMONS read. What other agents have left for this site, best first.

        Ranked by what actually happened, not by who shared it: a trail that worked for
        three agents and failed for none is offered ahead of one nobody has tried.
        """
        return sorted(
            (self.describe_offer(offer) for offer in self._offers(domain)),
            key=lambda o: (o["worked_for"] - o["failed_for"], o["borrows"], o["runs"]),
            reverse=True,
        )

    def every_offer(self) -> list[dict[str, Any]]:
        """COMMONS read. Everything in the shared memory, and who left it."""
        return sorted(
            (self.describe_offer(offer) for offer in self._all_offers()),
            key=lambda o: (o["domain"], o["task"]),
        )

    def borrow_trail(
        self, domain: str, task: str | None = None, *, force: bool = False
    ) -> Playbook | None:
        """COMMONS read, then a write into this agent's own memory.

        The trail is COPIED, not followed in place. That matters: the borrower ends up with
        something of its own that it can run, repair, and be made to forget. Reading the
        commons at replay time would look tidier and would gut the deletion test.

        Refuses to flatten a trail this agent has already repaired unless told to.
        """
        offers = self.offers_for(domain)
        if not offers:
            return None

        chosen = self._pick(offers, task)
        if chosen is None:
            return None

        offer = self._offer(offer_key(domain, chosen["task"], chosen["shared_by"]))
        if offer is None:
            return None

        borrowed = self._import_offer(offer, force=force)

        offer["borrows"] = offer.get("borrows", 0) + 1
        self._shared.put(SHARED, offer_key(domain, chosen["task"], offer["shared_by"]), offer)

        self._both_journals(
            evaluated=[f"{self.who} had never walked {domain}"],
            acted=[
                f"{self.who} borrowed the trail for {chosen['task']} that {offer['shared_by']} left"
            ],
            extra={
                "kind": "borrowed",
                "domain": domain,
                "task": chosen["task"],
                "by": self.who,
                "from": offer["shared_by"],
                "inherited_runs": borrowed.inherited_runs,
            },
        )
        return borrowed

    def record_outcome(self, domain: str, task: str, *, worked: bool) -> None:
        """COMMONS write. Say whether a borrowed trail actually worked here.

        This is what stops the commons being a pile of files. An offer accumulates the
        agents it has worked for and the ones it failed, and `offers_for` ranks on it — so
        what is stored changes because agents used it.
        """
        for offer in self._offers(domain):
            if offer["task"] != task:
                continue
            side = "confirmed_by" if worked else "failed_for"
            if self.who not in offer[side]:
                offer[side] = [*offer[side], self.who]
                self._shared.put(SHARED, offer_key(domain, task, offer["shared_by"]), offer)
            return

    def contribute_repair(self, domain: str, task: str) -> bool:
        """COMMONS write. Push a fix this agent made back into somebody else's offer.

        A merge, not a re-share: the repaired locators go to the front of that step, the
        version moves on, and this agent is added to the contributors. Authorship stays
        with whoever first walked the site.
        """
        mine = self.load_playbook(domain, task)
        if mine is None:
            return False

        for offer in self._offers(domain):
            if offer["task"] != task:
                continue

            theirs = Playbook.from_dict(offer["playbook"])
            by_index = {step.index: step for step in mine.steps}
            for step in theirs.steps:
                fixed = by_index.get(step.index)
                if fixed is not None and fixed.repairs > step.repairs:
                    step.locators = fixed.without_what_was_typed().locators
                    step.repairs = fixed.repairs

            theirs.touch()
            if self.who not in theirs.contributors:
                theirs.contributors.append(self.who)
            offer["playbook"] = theirs.to_dict()

            self._shared.put(SHARED, offer_key(domain, task, offer["shared_by"]), offer)
            self._both_journals(
                acted=[f"{self.who} contributed a fix to {offer['shared_by']}'s trail for {task}"],
                extra={"kind": "contributed", "domain": domain, "task": task, "by": self.who},
            )
            return True
        return False

    # ------------------------------------------------------- commons helpers

    def _import_offer(self, offer: dict[str, Any], *, force: bool) -> Playbook:
        """Write. Turn somebody else's offer into a trail this agent owns.

        Copied, never followed in place: the taker ends up with something of its own that it
        can run, repair, and be made to forget.
        """
        domain, task = offer["domain"], offer["task"]
        mine = self.load_playbook(domain, task)
        if mine is not None and mine.repairs and not force:
            raise TrailAlreadyHere(
                f"you already have a trail for {task!r} that you repaired {mine.repairs} "
                "time(s). Taking this one would throw that away — say so on purpose if you "
                "mean it."
            )

        taken = Playbook.from_dict(offer["playbook"]).as_borrowed_by(
            self.agent, shared_by=offer["shared_by"]
        )
        self.save_playbook(taken)
        self._take_their_notes(offer)
        self._take_their_map(offer)
        return taken

    @property
    def who(self) -> str:
        """This agent's name, as it appears to other agents."""
        return self.agent or UNNAMED

    def _offers(self, domain: str) -> list[dict[str, Any]]:
        return [offer for offer in self._all_offers() if offer.get("domain") == domain]

    def _all_offers(self) -> list[dict[str, Any]]:
        return [body for _, body in self._shared.items(SHARED) if body.get("domain")]

    def _offer(self, key: str) -> dict[str, Any] | None:
        return self._shared.get(SHARED, key)

    @staticmethod
    def describe_offer(offer: dict[str, Any]) -> dict[str, Any]:
        """One offer, as a caller should see it: enough to judge it, not enough to run it.

        Every listing of the commons goes through this, which is what guarantees a browsing
        agent never receives steps or locators — there are none in the shape below to leak.
        """
        trail = offer.get("playbook", {})
        return {
            "domain": offer["domain"],
            "task": offer["task"],
            "shared_by": offer["shared_by"],
            "shared_at": offer.get("shared_at", ""),
            "steps": len(trail.get("steps", [])),
            # How many pages of the site come with it — a number, never the pages. Enough
            # to see a map is worth borrowing; the map itself arrives only with the trail.
            "pages_mapped": len((offer.get("site_map") or {}).get("pages", [])),
            "runs": trail.get("runs", 0),
            "borrows": offer.get("borrows", 0),
            "worked_for": len(offer.get("confirmed_by", [])),
            "failed_for": len(offer.get("failed_for", [])),
            "contributors": trail.get("contributors", []),
        }

    @staticmethod
    def _pick(offers: list[dict[str, Any]], task: str | None) -> dict[str, Any] | None:
        """Which offer the caller meant. Best-ranked when they did not say."""
        if not task:
            return offers[0]
        exact = [offer for offer in offers if offer["task"] == task]
        if exact:
            return exact[0]
        closest = best_match(task, [offer["task"] for offer in offers])
        return next((offer for offer in offers if offer["task"] == closest), None)

    def _take_their_notes(self, offer: dict[str, Any]) -> None:
        """Fold a borrowed trail's site facts into whatever this agent already knew."""
        raw = offer.get("site_knowledge")
        if not raw:
            return
        theirs = SiteKnowledge.from_dict(raw)
        mine = self.load_site_knowledge(theirs.domain) or SiteKnowledge(domain=theirs.domain)
        for note in theirs.notes:
            mine = mine.merge(fact=note)
        for overlay in theirs.overlays:
            mine = mine.merge(overlay=overlay)
        self.save_site_knowledge(
            mine.merge(needs_login=theirs.needs_login or None, needs_2fa=theirs.needs_2fa or None)
        )

    def _take_their_map(self, offer: dict[str, Any]) -> None:
        """Fold a borrowed trail's map of the site into whatever this agent already knew.

        Merged rather than replaced, exactly like the notes. Two agents who have walked
        different corners of one site should end up knowing both corners, and neither
        should be able to erase the other's by sharing later.
        """
        raw = offer.get("site_map")
        if not raw:
            return
        theirs = SiteMap.from_dict(raw)
        mine = self.load_site_map(theirs.domain) or SiteMap(domain=theirs.domain)
        for page in theirs.pages:
            mine.merge(url=page.path, title=page.title, controls=page.controls)
        self.save_site_map(mine)

    def _both_journals(self, **event: Any) -> None:
        """History, twice: this agent's own, and the shared one.

        Two explicit writes because each view only ever writes to its own owner. A handoff
        that only appeared in one of the two would be half a record.
        """
        self._memory.record(**event)
        self._shared.record(**event)

    # ----------------------------------------------------------- site knowledge

    def save_site_knowledge(self, knowledge: SiteKnowledge) -> None:
        """Write. Survives a playbook being rebuilt from nothing."""
        self._memory.put(SITE_KNOWLEDGE, knowledge.domain, knowledge.to_dict())

    def load_site_knowledge(self, domain: str) -> SiteKnowledge | None:
        body = self._read_entity_body(SITE_KNOWLEDGE, domain)
        return SiteKnowledge.from_dict(body) if body else None

    # ------------------------------------------------------------------ the map

    def save_site_map(self, site_map: SiteMap) -> None:
        """Write. The pages Dejo has looked at on one site, and what was on them.

        Separate from the playbook on purpose: a trail is one route, and this is the
        terrain. A second task on the same site reads this instead of exploring blind,
        which is the whole reason it exists.
        """
        self._memory.put(SITE_MAP, site_map.domain, site_map.to_dict())

    def load_site_map(self, domain: str) -> SiteMap | None:
        body = self._read_entity_body(SITE_MAP, domain)
        return SiteMap.from_dict(body) if body else None

    def mapped_sites(self) -> list[str]:
        """Every site with a map, including ones no trail was ever saved for.

        `list_sites` reads the playbook category alone, so a site that was explored and
        then abandoned would be invisible while Dejo still held its shape. Memory that
        exists but cannot be seen is indistinguishable from memory that does not.
        """
        return self._memory.names(SITE_MAP)

    # ------------------------------------------------------------ cold journal

    def journal_run(self, metrics: RunMetrics) -> None:
        """History. The time-ordered record of what every run actually cost."""
        self._memory.record(
            acted=[f"{metrics.mode} run on {metrics.domain}: {metrics.task}"],
            extra={"kind": "run", **metrics.to_dict()},
        )

    def journal_repair(self, domain: str, step_index: int, before: str, after: str) -> None:
        """History. Every repair is recorded, so drift over time is inspectable."""
        self._memory.record(
            evaluated=[f"step {step_index} on {domain} no longer matched"],
            acted=[f"repaired step {step_index}: {before} -> {after}"],
            extra={
                "kind": "repair",
                "domain": domain,
                "step_index": step_index,
                "before": before,
                "after": after,
            },
        )

    def read_journal(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """History, newest first. Shows memory working, run by run."""
        return self._memory.history(limit=limit)

    def retire_playbook(self, domain: str, task: str | None = None) -> bool:
        """Archive only the trail, keeping what we know about the site.

        Used when a playbook goes stale: the steps are worthless because the site was
        rebuilt, but "needs a login, sends a code to your phone, use the finance account"
        is all still true. This is what makes relearning cheaper than a first visit.
        """
        key = trail_key(domain, task) if task else domain
        if not self._memory.archive(PLAYBOOK, key, reason="stale, site was rebuilt"):
            return False

        self._memory.record(
            evaluated=[f"most of the trail for {domain} no longer matches the site"],
            acted=[f"retired the trail for {domain}, kept what is known about the site"],
            extra={"kind": "retired", "domain": domain},
        )
        return True

    # ------------------------------------------------------- the deletion test

    def forget_site(self, domain: str) -> bool:
        """Archive everything Dejo knows about one site.

        THIS IS THE GATE. After this call `load_playbook(domain)` returns `None`, so
        replay has nothing to follow and the agent is back to exploring from scratch.
        Archived rather than deleted, so the fact that a trail once existed is not lost.

        Returns True if anything was actually forgotten.
        """
        forgotten = False

        # The commons first, and wrapped: a shared memory that is full, locked or
        # simply broken must never be able to stop a site being forgotten here.
        try:
            for offer in self.my_offers_for(domain):
                key = offer_key(domain, offer["task"], self.who)
                forgotten = self._shared.archive(SHARED, key, reason="dejo forget") or forgotten
        except Exception:  # noqa: BLE001 - forgetting matters more than the reason
            pass

        # Every trail for the site, not just one. A site with four tasks has four trails,
        # and "forget this site" has to mean all of them or the gate does not hold.
        for key in self._keys_for(domain):
            forgotten = self._memory.archive(PLAYBOOK, key, reason="dejo forget") or forgotten

        for category in (PLAYBOOK, SITE_KNOWLEDGE, SITE_MAP):
            forgotten = self._memory.archive(category, domain, reason="dejo forget") or forgotten

        # The tombstone goes down whether or not anything was there to archive, so
        # that a site forgotten twice stays forgotten.
        self._memory.put(FORGOTTEN, domain, {"at": utc_now(), "by": self.who})

        if forgotten:
            self._memory.record(
                acted=[f"{self.who} forgot everything about {domain}"],
                extra={"kind": "forget", "domain": domain, "by": self.who},
            )

        return forgotten

    # ------------------------------------------------------------------ helpers

    def _read_entity_body(self, category: str, name: str) -> dict[str, Any] | None:
        """One remembered entry. Missing and forgotten alike read as 'we do not know'."""
        return self._memory.get(category, name)


def trail_key(domain: str, task: str | None) -> str:
    """The memory name for one task on one site.

    A site holds many trails. Without the task in the key they overwrite each other, which
    is what happened the first time Dejo was asked about a second GitHub repo.
    """
    if not task:
        return domain
    return f"{domain}{KEY_SEPARATOR}{slug(task)}"


def domain_of_key(key: str) -> str:
    """The site a trail key belongs to. Trails saved before this are named by domain."""
    return key.split(KEY_SEPARATOR, 1)[0]


def slug(task: str) -> str:
    """A task in plain words, reduced to something safe to use as a name.

    Idempotent: slugging an already-slugged name returns it unchanged.
    """
    kept = [character if character.isalnum() else "-" for character in task.lower()]
    slug = "".join(kept)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:MAX_SLUG] or "task"


def best_match(wanted: str, known: list[str], *, domain: str | None = None) -> str | None:
    """Which saved task is the one being asked for, if any.

    Compares the words that carry meaning, so rewording survives but two genuinely
    different jobs never collide. Returns nothing when the best candidate is weak or when
    two are equally good — guessing between them would run the wrong task, which is worse
    than asking.
    """
    scored = sorted(
        ((_overlap(wanted, candidate, domain), candidate) for candidate in known), reverse=True
    )
    if not scored:
        return None

    best, winner = scored[0]
    if best < MATCH_THRESHOLD:
        return None
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    return winner if best > runner_up else None


def rank_tasks(wanted: str, known: list[str], *, domain: str | None = None) -> list[str]:
    """The saved tasks, closest first.

    So a caller who has to be asked "which one?" is shown the likeliest answer at the top
    rather than whatever happens to be first alphabetically.
    """
    return [
        task for _, task in sorted(((_overlap(wanted, t, domain), t) for t in known), reverse=True)
    ]


def shares_meaning(wanted: str, candidate: str, domain: str | None = None) -> bool:
    """Do these two describe jobs with ANY word in common?

    A far weaker question than `best_match`, and it exists for one specific case: a site
    with exactly one trail. "Which of the four?" needs a confident answer, but "is this
    plausibly the only thing I know how to do here?" does not — and refusing there is what
    made naming a task WORSE than saying nothing at all.

    Zero words in common is still a refusal, because that is the case that matters:
    "cancel my subscription" must never run "count open issues".
    """
    return bool(_meaningful(wanted, domain) & _meaningful(candidate, domain))


def swapped_subject(
    wanted: str, candidate: str, domain: str | None = None
) -> tuple[str, str] | None:
    """The one thing that changed between two ways of naming the same job.

    "message ankush" and "message riya" are the same route with a different subject, and so
    are "clicks for vouchley" and "clicks for pannly". Every word matches but one, and that
    one word is the entire point of the request.

    Without this the matcher scores those two as nearly identical and runs the stored trail
    unchanged — reporting vouchley's number for a question about pannly, or worse, sending
    a message to the wrong person. Recognising the swap is what turns the most dangerous
    kind of near-miss into the feature it was trying to be.

    Returns (was, now) or None. Exactly one word may differ each way: two changes is a
    different request, not the same one aimed somewhere else.
    """
    asked = _meaningful(wanted, domain)
    known = _meaningful(candidate, domain)
    added, dropped = asked - known, known - asked
    if len(added) != 1 or len(dropped) != 1:
        return None
    if not asked & known:
        # Nothing shared at all, so there is no route in common to reuse — a one-word
        # request against a one-word trail is not a swap, it is a different job.
        return None
    return (dropped.pop(), added.pop())


def _overlap(wanted: str, candidate: str, domain: str | None = None) -> float:
    """How alike two descriptions of a job are, 0 to 1.

    Measured against the SHORTER of the two, not against the request. Dividing by the
    request's own length punished a caller for being wordy: "find the top quote on
    quotes.toscrape.com and tell me who said it" scored 0.11 against the trail saved as
    "read the first quote", purely because it said more. Every extra word made a correct
    match look worse.
    """
    asked = _meaningful(wanted, domain)
    against = _meaningful(candidate, domain)
    if not asked or not against:
        return 0.0
    return len(asked & against) / min(len(asked), len(against))


def _meaningful(text: str, domain: str | None = None) -> set[str]:
    """The words in a request that say what the job IS.

    The site's own name is dropped, because the caller already said which site in a
    separate argument. Leaving it in meant "read the first quote on quotes.toscrape.com"
    scored worse than "read the first quote" against the very trail it belonged to.
    """
    ignore = _NOISE | (_meaningful(domain.replace(".", " ")) if domain else set())
    words = "".join(character if character.isalnum() else " " for character in text.lower())
    return {word for word in words.split() if word not in ignore}


def agent_owner(agent: str | None) -> str:
    """Whose memory one agent reads and writes.

    No name means the `default` owner, which is where everything learned before agents
    existed already is, so nothing has to be migrated and nothing is lost. A named agent is
    prefixed, so an agent literally called "commons" can never collide with the commons.
    """
    if agent is None:
        return DEFAULT_OWNER

    name = agent.strip()
    if not name:
        raise ValueError("an agent name cannot be blank")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in name):
        raise ValueError(f"{agent!r} has a control character in it")

    return f"{AGENT_OWNER_PREFIX}{name}"


def open_memory(db_path: str | Path | None = None) -> Database | SibylDatabase:
    """The database this machine's memory lives in: Dejo's own, unless DEJO_MEMORY=sibyl."""
    if (setting(BACKEND_ENV) or "").strip().lower() == SIBYL:
        return SibylDatabase(db_path or SIBYL_PATH)
    return Database(db_path or DEFAULT_PATH)


def adopt_old_memory(into: Path | None = None, sibyl: Path | None = None) -> int:
    """Bring a Sibyl memory across the first time Dejo starts. Returns how much came.

    Before October 2026 Dejo kept its memory in Sibyl. On a machine with that memory and no
    Dejo memory yet, every trail, fact, map and the whole history are copied in, so nothing
    learned is lost. Built under a temporary name and renamed into place only when complete,
    so a failure part-way leaves no half-memory behind to be mistaken for the real thing.

    Called by the `dejo` and `dejo-mcp` commands, never by the library, so tests and
    programs importing Dejo never touch the real memory.
    """
    into = into or DEFAULT_PATH
    sibyl = sibyl or SIBYL_PATH
    if into.exists() or not sibyl.is_file():
        return 0
    partial = into.with_name(into.name + ".partial")
    for leftover in (partial, *_sidecars(partial)):
        leftover.unlink(missing_ok=True)
    database = Database(partial)
    try:
        brought = import_sibyl(sibyl, database)
    except OldMemoryUnreadable:
        database.close()
        for leftover in (partial, *_sidecars(partial)):
            leftover.unlink(missing_ok=True)
        raise
    database.close()
    if brought == 0:
        # Nothing of Dejo's was in there. Leave no file, so nothing claims an import happened.
        for leftover in (partial, *_sidecars(partial)):
            leftover.unlink(missing_ok=True)
        return 0
    partial.rename(into)
    return brought


def _sidecars(database: Path) -> tuple[Path, Path]:
    """The two files SQLite keeps beside a database while it is open in WAL mode."""
    return database.with_name(database.name + "-wal"), database.with_name(database.name + "-shm")


def offer_key(domain: str, task: str, agent: str) -> str:
    """The name one agent's offer of one trail is stored under.

    The publisher is part of the key. Without it, two agents offering the same task would
    overwrite each other in silence, and withdrawing would delete whichever happened to be
    there — including somebody else's.
    """
    return f"{domain}{KEY_SEPARATOR}{slug(task)}{KEY_SEPARATOR}{slug(agent)}"
