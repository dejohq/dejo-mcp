"""The map: what Dejo saw on the way, not just where it was going.

Dejo's memory used to be keyed by (site, task) and nothing else. So walking to the
requests page to submit a request meant SEEING the list, the view button and the other six
sidebar items — and throwing every bit of it away. The next day, "view a request" explored
that same page blind.

Found on a real client marketplace, driving its end-to-end tests: the first run
cost the same as plain Playwright, because every task was a stranger on a site Dejo had
already walked twenty times.

This file proves the four things that make the map trustworthy rather than merely present:
it records what was actually seen, it cannot grow without end, it never claims to be
current, and `dejo forget` takes it with everything else.
"""

from __future__ import annotations

import json

import pytest
from tests.conftest import cold_run

from dejo.cli import main
from dejo.models import (
    MAX_CONTROLS_PER_PAGE,
    MAX_PAGES_PER_SITE,
    Control,
    Playbook,
    SiteMap,
    link_target,
    page_path,
)
from dejo.operations import ActionFailed, Session, _where_it_goes
from dejo.store import DejoStore

DOMAIN = "shop.example.com"
TASK = "read the invoice total"

# One full map — every page, every control — has to stay small enough that a person could
# hold a lot of sites without going near Sibyl's whole-database limit.
MAX_STORED_BYTES = 200_000


@pytest.fixture
def shared_db(tmp_path) -> str:
    """One database, the way two agents on one machine would have it."""
    return str(tmp_path / "memory.db")


def seen(*names: str, role: str = "link", at: str | None = None) -> list[Control]:
    """Controls as a page would hand them over, named the way a person reads them."""
    return [
        Control(role=role, name=name, href=f"/{name.lower()}", **({"last_seen": at} if at else {}))
        for name in names
    ]


# ------------------------------------------------------------------ which page is this


class TestOnePageIsOnePlace:
    """A page is a place. Two visits to two invoices are not two pages."""

    def test_an_id_in_the_path_is_not_a_different_page(self) -> None:
        assert page_path("/requests/1234/edit") == "/requests/:id/edit"
        assert page_path("/requests/1234/edit") == page_path("/requests/5678/edit")

    def test_a_uuid_is_an_id_too(self) -> None:
        assert page_path("/orders/3f2504e0-4f89-41d3-9a0c-0305e82c3301") == "/orders/:id"

    def test_and_so_is_a_long_hash(self) -> None:
        """Mongo-style ids are 24 hex characters and appear in paths constantly."""
        assert page_path("/doc/507f1f77bcf86cd799439011") == "/doc/:id"

    def test_an_email_in_the_path_never_survives(self) -> None:
        """Twice earned: it stops the map multiplying, and a map can now be shared."""
        assert page_path("/users/someone@work.com/settings") == "/users/:id/settings"

    def test_the_query_string_and_fragment_are_not_the_page(self) -> None:
        assert page_path("https://x.com/invoices?variant=b#top") == "/invoices"

    def test_a_bare_site_is_the_root(self) -> None:
        assert page_path("https://x.com") == "/"

    def test_an_ordinary_word_is_left_alone(self) -> None:
        assert page_path("/vendor/requests/new") == "/vendor/requests/new"


class TestWhereALinkActuallyPoints:
    """Found on GitHub, and it was a real bug in stored trails too.

    GitHub writes its own navigation absolutely — `href="https://github.com/pricing"`. The
    old code stripped that to `/pricing` before building a locator from it, so the selector
    `[href="/pricing"]` could never match the attribute it came from. Every trail carrying
    a link locator on such a site had one that silently missed.
    """

    def test_the_host_is_kept_when_the_page_wrote_one(self) -> None:
        assert link_target("https://github.com/pricing") == "https://github.com/pricing"

    def test_a_relative_link_stays_relative(self) -> None:
        assert link_target("/invoices") == "/invoices"

    def test_the_query_string_still_goes(self) -> None:
        """Session ids and tracking hang off links; the demo site hangs `?variant=` off
        every one of them."""
        assert link_target("/invoices?variant=b#top") == "/invoices"
        assert link_target("https://x.com/a?s=1") == "https://x.com/a"

    def test_a_link_to_another_site_is_not_mistaken_for_a_page_of_this_one(self) -> None:
        """On Hacker News every story link is somewhere else entirely. Stripped to a path,
        they read as pages of news.ycombinator.com, which is simply false."""
        assert link_target("https://lean.example/research/proof") != "/research/proof"

    def test_a_fragment_only_link_is_left_as_it_was(self) -> None:
        assert link_target("#start-of-content") == "#start-of-content"

    def test_but_the_map_does_not_record_one_as_a_destination(self) -> None:
        """Every real site starts with a "Skip to content" link a screen reader uses.

        It is not a place. Offering `#main-content` as somewhere to go would send an AI to
        where it already is — seen on GitHub and PostHog both. The control is still kept,
        because a site can hang `href="#"` on a button worth pressing.
        """
        assert _where_it_goes("#main-content") is None
        assert _where_it_goes("/vendor/requests") == "/vendor/requests"
        assert _where_it_goes(None) is None


# ------------------------------------------------------------------------ what it keeps


class TestItRemembersWhatWasSeen:
    def test_a_page_looked_at_once_is_in_the_map(self) -> None:
        site = SiteMap(domain=DOMAIN).merge(
            url="https://shop.example.com/vendor/requests",
            title="Requests",
            controls=seen("New Request", "Filter"),
        )

        page = site.page("/vendor/requests")

        assert page is not None
        assert page.title == "Requests"
        assert {control.name for control in page.controls} == {"New Request", "Filter"}

    def test_a_second_visit_adds_rather_than_replaces(self) -> None:
        """The whole reason one merged map works for a site with three logins.

        An admin sees sidebar items a customer never will. Overwriting would mean whichever
        role looked last decided what the site contains.
        """
        site = SiteMap(domain=DOMAIN)
        site.merge(url="/dashboard", controls=seen("Orders", "Profile"))

        site.merge(url="/dashboard", controls=seen("Orders", "Users", "Billing"))

        names = {control.name for control in site.page("/dashboard").controls}
        assert names == {"Orders", "Profile", "Users", "Billing"}

    def test_the_map_holds_one_entry_for_a_page_however_often_it_is_seen(self) -> None:
        site = SiteMap(domain=DOMAIN)
        for invoice in range(20):
            site.merge(url=f"/invoices/{invoice}", controls=seen("Download"))

        assert [page.path for page in site.pages] == ["/invoices/:id"]

    def test_a_link_target_is_kept_because_it_says_where_the_page_is(self) -> None:
        site = SiteMap(domain=DOMAIN).merge(url="/", controls=seen("Requests"))

        assert site.page("/").controls[0].href == "/requests"

    def test_a_title_is_recorded_and_kept_short(self) -> None:
        site = SiteMap(domain=DOMAIN).merge(url="/", title="x" * 500)

        assert len(site.page("/").title) == 80

    def test_an_empty_map_says_so(self) -> None:
        assert SiteMap(domain=DOMAIN).is_empty
        assert not SiteMap(domain=DOMAIN).merge(url="/").is_empty


# --------------------------------------------------------------------------- the limits


class TestItCannotGrowWithoutEnd:
    """Sibyl's cap is on the whole DATABASE, and the error is database-wide.

    So a runaway map would not merely spoil itself — it would stop trails, site knowledge
    and the commons being written at all, in the middle of somebody's run. These limits are
    load-bearing, which is why they are tested rather than commented.
    """

    def test_a_page_stops_at_the_control_limit(self) -> None:
        site = SiteMap(domain=DOMAIN).merge(
            url="/busy",
            controls=seen(*[f"Control {n}" for n in range(MAX_CONTROLS_PER_PAGE * 3)]),
        )

        assert len(site.page("/busy").controls) == MAX_CONTROLS_PER_PAGE

    def test_and_drops_what_has_not_been_seen_for_longest(self) -> None:
        site = SiteMap(domain=DOMAIN)
        site.merge(url="/busy", controls=seen("Ancient", at="2020-01-01T00:00:00+00:00"))
        site.merge(
            url="/busy",
            controls=seen(*[f"Fresh {n}" for n in range(MAX_CONTROLS_PER_PAGE)]),
        )

        names = {control.name for control in site.page("/busy").controls}
        assert "Ancient" not in names
        assert len(names) == MAX_CONTROLS_PER_PAGE

    def test_a_site_stops_at_the_page_limit(self) -> None:
        site = SiteMap(domain=DOMAIN)
        for n in range(MAX_PAGES_PER_SITE * 2):
            site.merge(url=f"/page-{n}", controls=seen("Next"))

        assert len(site.pages) == MAX_PAGES_PER_SITE

    def test_a_completely_full_map_is_still_small(self) -> None:
        """The number that matters: a worst case, measured rather than assumed.

        The paths here are deliberately word-shaped. The first version of this test used
        `/section/0/overview`, and every one of them normalised to `/section/:id/overview`
        — so it built ONE page and measured nothing. The page-count assertion below is
        there so that can never happen again quietly.
        """
        site = SiteMap(domain=DOMAIN)
        for n in range(MAX_PAGES_PER_SITE):
            site.merge(
                url=f"/vendor/section-{n:x}x/overview",
                title=f"Section {n} overview",
                controls=seen(*[f"Some control number {c}" for c in range(MAX_CONTROLS_PER_PAGE)]),
            )

        size = len(json.dumps(site.to_dict()))

        assert len(site.pages) == MAX_PAGES_PER_SITE, "the test must actually build a full map"
        assert size < MAX_STORED_BYTES, f"a full map is {size} bytes"

    def test_a_control_seen_with_its_page_costs_no_timestamp(self) -> None:
        """Sixty pages of repeated timestamps would be a third of the map saying nothing."""
        site = SiteMap(domain=DOMAIN).merge(url="/", controls=seen("Orders"))

        stored = site.to_dict()["pages"][0]["controls"][0]

        assert "last_seen" not in stored


# ------------------------------------------------------------------------ reading it back


class TestItSurvivesBeingStored:
    def test_a_map_round_trips(self) -> None:
        site = SiteMap(domain=DOMAIN)
        site.merge(url="/vendor/requests", title="Requests", controls=seen("New Request"))
        site.merge(url="/vendor/reports", title="Reports", controls=seen("Export"))

        back = SiteMap.from_dict(json.loads(json.dumps(site.to_dict())))

        assert back.domain == DOMAIN
        assert {page.path for page in back.pages} == {"/vendor/requests", "/vendor/reports"}
        assert back.page("/vendor/requests").controls[0].href == "/new request"

    def test_a_control_that_vanished_keeps_its_own_older_date(self) -> None:
        site = SiteMap(domain=DOMAIN)
        site.merge(url="/", controls=seen("Gone", at="2020-01-01T00:00:00+00:00"))
        site.merge(url="/", controls=seen("Here"))

        back = SiteMap.from_dict(site.to_dict())
        dates = {control.name: control.last_seen for control in back.page("/").controls}

        assert dates["Gone"].startswith("2020")
        assert not dates["Here"].startswith("2020")


class TestItNeverPretendsToBeCurrent:
    """A map is a memory. Handing it back without a date would make it a claim."""

    def test_every_line_of_the_index_says_when_it_was_seen(self) -> None:
        site = SiteMap(domain=DOMAIN).merge(url="/orders", title="Orders", controls=seen("New"))

        line = site.summary()[0]

        assert "/orders" in line
        assert "Orders" in line
        assert "seen" in line

    def test_the_index_puts_the_freshest_page_first(self) -> None:
        site = SiteMap(domain=DOMAIN)
        site.merge(url="/old")
        site.merge(url="/new")

        assert [row["path"] for row in site.index()][0] == "/new"

    def test_the_index_counts_the_controls_without_carrying_them(self) -> None:
        """A forty-page map cannot travel inside every reply, so the index is a summary."""
        site = SiteMap(domain=DOMAIN).merge(url="/", controls=seen("A", "B", "C"))

        row = site.index()[0]

        assert row["controls"] == 3
        assert "name" not in json.dumps(row)


# --------------------------------------------------------------------------- sharing it


class TestWhatTravelsToAnotherAgent:
    def test_the_shape_of_the_site_goes(self) -> None:
        site = SiteMap(domain=DOMAIN).merge(
            url="/vendor/requests", title="Requests", controls=seen("New Request")
        )

        shared = site.for_sharing()

        assert shared.page("/vendor/requests").controls[0].name == "New Request"

    def test_a_control_naming_a_person_does_not(self) -> None:
        """ "Signed in as someone@work.com" in a header is a real thing on real sites.

        The path had its identities generalised away already; this is the other half.
        """
        site = SiteMap(domain=DOMAIN).merge(
            url="/", controls=seen("Orders") + seen("someone@work.com", role="button")
        )

        names = {control.name for control in site.for_sharing().page("/").controls}

        assert names == {"Orders"}

    def test_sharing_does_not_disturb_what_is_kept(self) -> None:
        site = SiteMap(domain=DOMAIN).merge(url="/", controls=seen("someone@work.com"))

        site.for_sharing()

        assert site.page("/").controls[0].name == "someone@work.com"


# ------------------------------------------------------------------------ in the store


class TestTheStoreKeepsIt:
    def test_a_map_written_is_a_map_read_back(self, store) -> None:
        store.save_site_map(SiteMap(domain=DOMAIN).merge(url="/orders", controls=seen("New")))

        assert store.load_site_map(DOMAIN).page("/orders") is not None

    def test_a_site_nobody_mapped_has_no_map(self, store) -> None:
        assert store.load_site_map("never.seen.example.com") is None

    def test_a_site_explored_but_never_saved_is_still_visible(self, store) -> None:
        """Memory that exists but cannot be seen is indistinguishable from memory that
        does not. `list_sites` reads trails alone, so a site abandoned mid-exploration
        would hold a map nothing would ever show."""
        store.save_site_map(SiteMap(domain=DOMAIN).merge(url="/"))

        assert store.list_sites() == []
        assert store.mapped_sites() == [DOMAIN]

    def test_forgetting_a_site_takes_its_map(self, store) -> None:
        """The gate. Delete the memory and Dejo must not still know the site."""
        store.save_site_map(SiteMap(domain=DOMAIN).merge(url="/orders", controls=seen("New")))

        store.forget_site(DOMAIN)

        assert store.load_site_map(DOMAIN) is None
        assert store.mapped_sites() == []


# ------------------------------------------------------- against a real browser


class TestItRecordsARealWalk:
    def test_the_pages_walked_are_in_the_map_afterwards(self, browser, store, demo_server) -> None:
        session = Session(browser, store)

        cold_run(session, demo_server)

        walked = store.load_site_map(session._map.domain)
        assert {page.path for page in walked.pages} == {"/", "/invoices", "/invoices/:id"}

    def test_and_what_was_on_them(self, browser, store, demo_server) -> None:
        session = Session(browser, store)

        cold_run(session, demo_server)

        names = {
            control.name for control in store.load_site_map(session._map.domain).page("/").controls
        }
        assert {"Email", "Password", "Sign in"} <= names

    def test_recording_costs_no_extra_page_read(self, browser, store, demo_server) -> None:
        """The point of the whole design: the snapshot was already built and paid for.

        Nine is the number the README and the benchmark both quote for a first visit. If
        it ever moves, the map has started costing what it was meant to save.
        """
        session = Session(browser, store)

        cold_run(session, demo_server)

        assert session.tool_calls == 9

    def test_an_unchanged_page_is_not_written_again(self, browser, store, demo_server) -> None:
        """One body per site, re-indexed for search on every write. Looking at the same
        unchanged page twenty times must not mean twenty writes of the same thing."""
        session = Session(browser, store)
        writes = []
        real = store.save_site_map
        store.save_site_map = lambda site_map: (writes.append(1), real(site_map))[1]

        session.act("open the portal", "goto", value=demo_server)
        for _ in range(5):
            session.look()

        assert len(writes) == 1

    def test_a_session_with_no_memory_still_works(self, browser, demo_server) -> None:
        """`Session(browser)` with no store is a supported shape, and must not break."""
        session = Session(browser)

        session.act("open the portal", "goto", value=demo_server)

        assert session.look()["elements"]


# ------------------------------------------------------- between two agents


class TestTheMapTravelsWithATrail:
    """Decided 2026-09-04: the map goes with a shared trail.

    It is what makes a borrowed trail worth more than the one task it replays. The
    borrower can go somewhere ELSE on that site afterwards without walking it blind — which
    is the same saving the map gives its owner, handed to a stranger.
    """

    def test_a_borrowed_trail_brings_the_shape_of_the_site(self, shared_db) -> None:
        alice = DejoStore(db_path=shared_db, agent="alice")
        alice.save_playbook(Playbook(domain=DOMAIN, task=TASK))
        alice.save_site_map(
            SiteMap(domain=DOMAIN).merge(
                url="/vendor/requests", title="Requests", controls=seen("New Request")
            )
        )
        alice.share_trail(DOMAIN)
        bob = DejoStore(db_path=shared_db, agent="bob")

        bob.borrow_trail(DOMAIN)

        theirs = bob.load_site_map(DOMAIN)
        assert theirs is not None
        assert theirs.page("/vendor/requests").controls[0].name == "New Request"

    def test_borrowing_adds_to_a_map_rather_than_flattening_it(self, shared_db) -> None:
        """Two agents who walked different corners should end up knowing both."""
        alice = DejoStore(db_path=shared_db, agent="alice")
        alice.save_playbook(Playbook(domain=DOMAIN, task=TASK))
        alice.save_site_map(SiteMap(domain=DOMAIN).merge(url="/alice-was-here"))
        alice.share_trail(DOMAIN)
        bob = DejoStore(db_path=shared_db, agent="bob")
        bob.save_site_map(SiteMap(domain=DOMAIN).merge(url="/bob-was-here"))

        bob.borrow_trail(DOMAIN)

        paths = {page.path for page in bob.load_site_map(DOMAIN).pages}
        assert paths == {"/alice-was-here", "/bob-was-here"}

    def test_a_listing_advertises_the_size_but_not_the_pages(self, shared_db) -> None:
        """Every listing of the commons is built from `describe_offer`. Another agent should
        be able to see that a map is worth borrowing without being handed it."""
        alice = DejoStore(db_path=shared_db, agent="alice")
        alice.save_playbook(Playbook(domain=DOMAIN, task=TASK))
        alice.save_site_map(
            SiteMap(domain=DOMAIN).merge(url="/vendor/requests", controls=seen("New Request"))
        )
        alice.share_trail(DOMAIN)

        # `offers_for` is already the public projection — the shape every listing uses.
        listed = alice.offers_for(DOMAIN)[0]

        assert listed["pages_mapped"] == 1
        assert "vendor" not in json.dumps(listed)
        assert "New Request" not in json.dumps(listed)

    def test_whoever_shares_is_told_exactly_which_pages_left(self, shared_db) -> None:
        """Consent by inspection, the same guarantee the notes already have."""
        alice = DejoStore(db_path=shared_db, agent="alice")
        alice.save_playbook(Playbook(domain=DOMAIN, task=TASK))
        alice.save_site_map(SiteMap(domain=DOMAIN).merge(url="/vendor/requests"))

        published = alice.share_trail(DOMAIN)

        assert published["pages_published"] == ["/vendor/requests"]

    def test_a_trail_with_no_map_shares_perfectly_well(self, shared_db) -> None:
        alice = DejoStore(db_path=shared_db, agent="alice")
        alice.save_playbook(Playbook(domain=DOMAIN, task=TASK))

        published = alice.share_trail(DOMAIN)

        assert published["pages_published"] == []
        assert alice.offers_for(DOMAIN)[0]["pages_mapped"] == 0


# --------------------------------------------------- acting on what the map knows


class TestActingOnWhatTheMapRemembers:
    """A map you cannot act on is only a hint.

    The map stores what a trail stores — a role and a name, a link target — so `dejo_act`
    accepts those directly. Without this the AI would know the Sign in button was there and
    STILL have to read the whole page to get a ref before pressing it, which is exactly the
    cost the map exists to remove.
    """

    def test_a_button_can_be_pressed_by_what_the_map_calls_it(
        self, browser, store, demo_server
    ) -> None:
        session = Session(browser, store)
        session.act("open the portal", "goto", value=demo_server)

        session.act("type the email", "fill", ref="role=textbox|Email", value="a@b.com")
        session.act("type the password", "fill", ref="role=textbox|Password", value="hunter2")
        result = session.act("sign in", "click", ref="role=button|Sign in")

        assert result["navigated"] is True
        assert "/invoices" in result["url"]

    def test_and_none_of_that_needed_a_single_page_read(self, browser, store, demo_server) -> None:
        """The whole claim, as a number."""
        session = Session(browser, store)
        session.act("open the portal", "goto", value=demo_server)

        session.act("type the email", "fill", ref="role=textbox|Email", value="a@b.com")
        session.act("type the password", "fill", ref="role=textbox|Password", value="hunter2")
        session.act("sign in", "click", ref="role=button|Sign in")

        assert session.tool_calls == 4, "four acts, zero looks"

    def test_a_link_can_be_followed_by_the_target_the_map_recorded(
        self, browser, store, demo_server
    ) -> None:
        session = Session(browser, store)
        session.act("open the portal", "goto", value=f"{demo_server}/invoices")

        result = session.act("open settings", "click", ref="href=/settings")

        assert "/settings" in result["url"]

    def test_a_css_selector_still_means_a_css_selector(self, browser, store, demo_server) -> None:
        """The old form has to keep working — dashboards name plain divs this way."""
        session = Session(browser, store)
        session.act("open the portal", "goto", value=f"{demo_server}/payments")

        assert session.read("text", ref="#next-charge")

    def test_a_control_that_has_moved_says_so_instead_of_failing_quietly(
        self, browser, store, demo_server
    ) -> None:
        """The map is a memory. When it is wrong, the message has to say what to do."""
        session = Session(browser, store)
        session.act("open the portal", "goto", value=demo_server)

        with pytest.raises(ActionFailed) as refused:
            session.act("press what is not there", "click", ref="role=button|Long Gone")

        assert "dejo_read" in str(refused.value)


# ------------------------------------------------------------- from a terminal


def cli(db: str, *argv: str) -> int:
    return main(["--db", db, *argv])


class TestTheTerminalCommands:
    """Someone with a terminal and no MCP client has to be able to see all of this."""

    def test_the_index_prints_every_page_with_a_date(self, tmp_path, capsys) -> None:
        db = str(tmp_path / "memory.db")
        DejoStore(db_path=db).save_site_map(
            SiteMap(domain=DOMAIN).merge(
                url="/vendor/requests", title="Requests", controls=seen("New Request")
            )
        )

        assert cli(db, "map", DOMAIN) == 0
        said = capsys.readouterr().out
        assert "/vendor/requests" in said
        assert "seen" in said
        assert "not what is on the site now" in said

    def test_one_page_prints_its_controls(self, tmp_path, capsys) -> None:
        db = str(tmp_path / "memory.db")
        DejoStore(db_path=db).save_site_map(
            SiteMap(domain=DOMAIN).merge(url="/vendor/requests", controls=seen("New Request"))
        )

        assert cli(db, "map", DOMAIN, "--path", "/vendor/requests") == 0
        assert "New Request" in capsys.readouterr().out

    def test_the_leading_slash_is_optional(self, tmp_path, capsys) -> None:
        """Git Bash rewrites `/settings` into a Windows path before Dejo ever sees it.

        Nothing here can stop that, so the slashless form has to work.
        """
        db = str(tmp_path / "memory.db")
        DejoStore(db_path=db).save_site_map(
            SiteMap(domain=DOMAIN).merge(url="/settings", controls=seen("Save changes"))
        )

        assert cli(db, "map", DOMAIN, "--path", "settings") == 0
        assert "Save changes" in capsys.readouterr().out

    def test_a_site_with_no_map_exits_non_zero(self, tmp_path, capsys) -> None:
        db = str(tmp_path / "memory.db")

        assert cli(db, "map", DOMAIN) == 2
        assert "has not looked at any page" in capsys.readouterr().out

    def test_sites_shows_every_trail_not_just_the_first(self, tmp_path, capsys) -> None:
        """The regression this phase found.

        `dejo sites` used to call `load_playbook(site)` with no task, which returns None
        the moment a site has more than one — and then skipped it in silence. A site with
        two tasks vanished completely, which is the exact shape of site this whole phase is
        about.
        """
        db = str(tmp_path / "memory.db")
        store = DejoStore(db_path=db)
        store.save_playbook(Playbook(domain=DOMAIN, task="submit a new request"))
        store.save_playbook(Playbook(domain=DOMAIN, task="view a request"))

        assert cli(db, "sites") == 0
        said = capsys.readouterr().out
        assert "submit a new request" in said
        assert "view a request" in said

    def test_and_a_site_explored_but_never_saved(self, tmp_path, capsys) -> None:
        db = str(tmp_path / "memory.db")
        DejoStore(db_path=db).save_site_map(SiteMap(domain=DOMAIN).merge(url="/"))

        assert cli(db, "sites") == 0
        said = capsys.readouterr().out
        assert DOMAIN in said
        assert "no trail yet" in said
        assert "1 pages mapped" in said
