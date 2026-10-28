"""Replaying a trail somewhere it does not start.

The dangerous lookalike. "This control moved" and "we are on a completely different page"
look identical from inside a step, and reporting the second as the first invites a repair
that binds a healthy step to whatever happened to be lying around. Replaying a sign-in while
already signed in lands on a dashboard and offered twenty-three nav links as candidates for
an email field.

The version of this that shipped could not fire at all on a real trail. It read `Step.page`,
which only exists on trails learned after that field was added and which nothing backfills —
so every trail saved before it opted out silently, forever, and the tests all passed because
every one of them set `page=` by hand. The trail is now read for its own geography instead.
"""

from __future__ import annotations

import pytest

from dejo import program
from dejo.browser import Browser, domain_of
from dejo.executor import Executor, pages_along
from dejo.models import Locator, Playbook, Postcondition, Step, signs_in_at
from dejo.operations import Session
from dejo.runner import Runner
from dejo.store import DejoStore

SITE = "billing.example"
TASK = "sign in"

# The demo site answers /admin with a redirect to /invoices, exactly the way a sign-in page
# bounces you once you are already signed in. /settings is served normally.
BOUNCES = "/admin"
SERVED = "/settings"


def a_trail(*, belongs_on: str, reads: bool = False) -> Playbook:
    """Open a page, then use a field that only exists on `belongs_on`.

    The shape every sign-in trail has: step one says WHERE, step two needs something that
    is only there.
    """
    steps = [
        Step(
            index=1,
            intent="open the sign-in page",
            action="goto",
            value=BOUNCES,
            postcondition=Postcondition("url_contains", BOUNCES),
        ),
        Step(
            index=2,
            intent="type the billing email",
            action="fill",
            value="finance@acme.com",
            postcondition=Postcondition("element_present", "#billing-email"),
            locators=[Locator("css", "#billing-email")],
            page=belongs_on,
        ),
    ]
    if reads:
        steps.append(
            Step(
                index=3,
                intent="read the billing email",
                action="read",
                postcondition=Postcondition("element_present", "#billing-email"),
                locators=[Locator("css", "#billing-email")],
                page=belongs_on,
            )
        )
    return Playbook(domain=SITE, task=TASK, steps=steps)


@pytest.fixture
def refused(store: DejoStore) -> DejoStore:
    """A trail whose page the site will not serve — the already-signed-in shape.

    Step two belongs on /admin, and /admin redirects to /invoices however often you ask.
    """
    store.save_playbook(a_trail(belongs_on=BOUNCES))
    return store


class TestWhenTheSiteKeepsRefusingTheTrailsStartingPage:
    """Dejo walks back to the page and is sent away a second time. That is not a broken
    trail — it is the site saying the state this trail creates is already there."""

    def test_it_is_reported_as_done_not_as_a_failure(
        self, refused: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        result = Executor(refused, browser).run(SITE, task=TASK, start_url=f"{demo_server}/admin")

        assert result.ok is True
        assert result.already_done is True

    def test_and_nothing_is_offered_to_bind_the_step_to(
        self, refused: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        """Offering candidates IS the damage."""
        result = Executor(refused, browser).run(SITE, task=TASK, start_url=f"{demo_server}/admin")

        assert result.repair is None
        assert result.needs_repair is False

    def test_it_says_which_page_the_site_refused_and_where_it_sent_us(
        self, refused: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        result = Executor(refused, browser).run(SITE, task=TASK, start_url=f"{demo_server}/admin")

        assert BOUNCES in result.reason
        assert "/invoices" in result.reason
        assert "already" in result.reason.lower()


class TestItDoesNotDamageTheTrailItDidNotRun:
    """The fault that was worse than the one reported.

    Deciding late — after the locators had been tried — meant every wrong-place replay
    recorded a miss against a perfectly good locator. A few of those drag the trail's health
    under half, `is_stale` turns true, and the trail is RETIRED. Measured on the real
    marketplace trail: four replays while signed in put four misses on every locator of a
    step that was never broken.
    """

    def test_the_healthy_locator_is_not_marked_as_drift(
        self, refused: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        before = refused.load_playbook(SITE, TASK).steps[1].locators[0].misses

        Executor(refused, browser).run(SITE, task=TASK, start_url=f"{demo_server}/admin")

        after = refused.load_playbook(SITE, TASK).steps[1].locators[0].misses
        assert after == before

    def test_and_the_trail_is_never_condemned_however_often_you_do_it(
        self, refused: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        for _ in range(5):
            Executor(refused, browser).run(SITE, task=TASK, start_url=f"{demo_server}/admin")

        assert refused.load_playbook(SITE, TASK).is_stale is False


class TestWhenTheBrowserWasSimplyLeftSomewhereElse:
    """The common case, and the one that must never reach the user at all.

    Being on the wrong page usually means the last run stopped somewhere. Dejo walks back
    to the page the step belongs on and carries on, silently.
    """

    def test_it_walks_back_and_finishes_the_trail(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        store.save_playbook(a_trail(belongs_on=SERVED))

        result = Executor(store, browser).run(SITE, task=TASK, start_url=f"{demo_server}/admin")

        assert result.ok is True
        assert result.already_done is False
        assert result.repair is None

    def test_a_step_replayed_where_it_belongs_still_runs(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        """The check must not fire when everything is fine. A site that canonicalises its
        own URL has to keep working."""
        store.save_playbook(a_trail(belongs_on=SERVED))

        result = Executor(store, browser).run(SITE, task=TASK, start_url=f"{demo_server}/settings")

        assert result.ok is True
        assert result.wrong_place is False
        assert result.already_done is False


class TestATrailThatOwesAnAnswer:
    def test_it_is_never_called_already_done(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        """ "It was already true" is not a number. A trail with a READ in it was asked to
        come back with something, so reporting success without it would be a lie."""
        store.save_playbook(a_trail(belongs_on=BOUNCES, reads=True))

        result = Executor(store, browser).run(SITE, task=TASK, start_url=f"{demo_server}/admin")

        assert result.already_done is False
        assert result.ok is False
        assert result.wrong_place is True
        assert result.repair is None


class TestTrailsThatNeverRecordedTheirPage:
    """The bug. Every trail saved before `Step.page` existed carries an empty one, nothing
    backfills it, and the check used to return on its first line because of that."""

    def test_a_trail_with_no_stored_page_is_still_protected(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        store.save_playbook(a_trail(belongs_on=""))

        result = Executor(store, browser).run(SITE, task=TASK, start_url=f"{demo_server}/admin")

        assert result.repair is None
        assert result.already_done is True

    def test_and_its_locators_are_not_blamed_either(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        store.save_playbook(a_trail(belongs_on=""))
        before = store.load_playbook(SITE, TASK).steps[1].locators[0].misses

        Executor(store, browser).run(SITE, task=TASK, start_url=f"{demo_server}/admin")

        assert store.load_playbook(SITE, TASK).steps[1].locators[0].misses == before


class TestWorkingOutWhereAStepBelongs:
    def test_every_step_after_a_goto_belongs_on_what_the_goto_asked_for(self) -> None:
        steps = a_trail(belongs_on="").steps

        assert pages_along(steps) == {2: BOUNCES}

    def test_the_caller_redirecting_step_one_moves_the_whole_trail_with_it(self) -> None:
        """`start_url` is what step one really asked for, so everything after it belongs on
        the new page. Comparing against the saved address instead would report a redirected
        demo replay as off-trail on its very first step."""
        steps = a_trail(belongs_on="").steps

        assert pages_along(steps, "https://example.test/settings") == {
            2: "https://example.test/settings"
        }

    def test_a_click_that_navigates_moves_the_trail_on(self) -> None:
        """Most trails reach their page by clicking, not by a goto."""
        steps = [
            Step(
                index=1,
                intent="open the account menu",
                action="click",
                postcondition=Postcondition("url_contains", "/settings"),
                locators=[Locator("css", "#account-menu")],
            ),
            Step(
                index=2,
                intent="type the billing email",
                action="fill",
                postcondition=Postcondition("element_present", "#billing-email"),
                locators=[Locator("css", "#billing-email")],
            ),
        ]

        assert pages_along(steps) == {2: "/settings"}

    def test_an_expectation_does_not_survive_a_step_that_could_navigate(self) -> None:
        """A sign-in ends by pressing a button and the app redirects. Carrying the sign-in
        page forward past that click made every later step look off-trail on a run that was
        going perfectly — it broke three tests before CI caught it. Not knowing is the
        honest answer, and it costs a check rather than a false accusation."""
        steps = [
            Step(
                index=1,
                intent="open the sign-in page",
                action="goto",
                value=BOUNCES,
                postcondition=Postcondition("url_contains", BOUNCES),
            ),
            Step(
                index=2,
                intent="type the email",
                action="fill",
                postcondition=Postcondition("element_present", "#billing-email"),
                locators=[Locator("css", "#billing-email")],
            ),
            Step(
                index=3,
                intent="submit",
                action="click",
                postcondition=Postcondition("text_present", "Signing in..."),
                locators=[Locator("css", "button")],
            ),
            Step(
                index=4,
                intent="read the greeting",
                action="read",
                postcondition=Postcondition("element_present", "h1"),
                locators=[Locator("css", "h1")],
            ),
        ]

        pages = pages_along(steps)

        assert pages[2] == BOUNCES, "a fill cannot have moved us"
        assert pages[3] == BOUNCES, "the click itself still happens on the sign-in page"
        assert 4 not in pages, "after the click, where we are is genuinely unknown"

    def test_steps_before_any_navigation_have_nothing_to_compare(self) -> None:
        """Opting out is right here — we genuinely do not know, and guessing would refuse
        trails that are perfectly fine."""
        steps = [
            Step(
                index=1,
                intent="open the account menu",
                action="click",
                postcondition=Postcondition("element_present", "#account-menu"),
                locators=[Locator("css", "#account-menu")],
            )
        ]

        assert pages_along(steps) == {}


class TestATrailThatNavigatesByClicking:
    """The shape the first attempt could not see at all.

    That version only noticed when step 1 was a `goto` whose URL check failed. A trail that
    reaches its page by CLICKING a link never went through that branch, so it was offered
    for repair every time — and most real trails are this shape.
    """

    def clicking_trail(self) -> Playbook:
        return Playbook(
            domain=SITE,
            task=TASK,
            steps=[
                Step(
                    index=1,
                    intent="open the account menu",
                    action="click",
                    postcondition=Postcondition("element_present", "#account-menu"),
                    locators=[Locator("css", "#account-menu")],
                    page="/settings",
                )
            ],
        )

    def test_it_is_still_caught(self, store: DejoStore, browser: Browser, demo_server: str) -> None:
        store.save_playbook(self.clicking_trail())

        result = Executor(store, browser).run(SITE, task=TASK, start_url=f"{demo_server}/invoices")

        assert result.needs_repair is False
        assert result.repair is None


class TestATrailThatSignsInOnTheWayToItsWork:
    """28 Oct, launchit.site, "submit a product to Launchit": the trail was learned signed
    out, so it signs in with Google on /register before it fills the submit form. Replayed
    signed in, the site sends /register straight on to the form, and the replay stopped
    with "the work is already done". The sign-in was done; the submit was not."""

    TASK = "submit Dejo to the demo site"

    def learned_signed_out(self, store: DejoStore, browser: Browser, demo_server: str) -> None:
        """Learn the trail the way the agent did: signed out, so the form first sends it to
        sign in. "Continue with Google" leaves the browser signed in for the replay."""
        outcome = Runner(Session(browser=browser, store=store), task=self.TASK, store=store).run(
            program.parse(
                f"go {demo_server}/new-product\n"
                'click button "Continue with Google"\n'
                'fill label "Product name" "Dejo"\n'
                'click! button "Submit"\n'
            ),
            done=True,
        )
        assert outcome.ok and outcome.saved is not None, outcome.text()
        assert outcome.saved.steps[1].page == "/register"
        browser.page.goto("about:blank")

    def test_the_sign_in_is_skipped_and_the_rest_of_the_trail_runs(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        self.learned_signed_out(store, browser, demo_server)

        result = Executor(store, browser).run(domain_of(demo_server), task=self.TASK)

        assert result.ok is True, result.reason
        assert result.already_done is False
        assert browser.page.inner_text("#sent") == "Submitted Dejo"
        assert result.signed_in_already == ['step 2 (click button "Continue with Google")']

    def test_the_skipped_sign_in_is_not_blamed(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        self.learned_signed_out(store, browser, demo_server)

        Executor(store, browser).run(domain_of(demo_server), task=self.TASK)

        sign_in = store.load_playbook(domain_of(demo_server), self.TASK).steps[1]
        assert all(locator.misses == 0 for locator in sign_in.locators)

    def test_when_the_site_sends_its_sign_in_to_a_dashboard_the_rest_is_walked_to(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        """Most sites send their sign-in page to a dashboard, not to the page the trail goes
        on from. Dejo asks for the sign-in page, is sent away from it, and then opens the
        page the rest of the trail belongs on."""
        self.learned_signed_out(store, browser, demo_server)
        playbook = store.load_playbook(domain_of(demo_server), self.TASK)
        playbook.steps[0].value = f"{demo_server}/payments"
        playbook.steps[0].postcondition = Postcondition("url_contains", "/payments")
        playbook.steps[1].page = "/sign-in"
        store.save_playbook(playbook)

        result = Executor(store, browser).run(domain_of(demo_server), task=self.TASK)

        assert result.ok is True, result.reason
        assert browser.page.inner_text("#sent") == "Submitted Dejo"

    def test_a_tab_left_on_another_page_is_not_taken_for_signed_in(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        """Signed out, the sign-in page is shown when asked for, so nothing is skipped."""
        self.learned_signed_out(store, browser, demo_server)
        browser.page.context.clear_cookies()
        playbook = store.load_playbook(domain_of(demo_server), self.TASK)
        playbook.steps[0].value = f"{demo_server}/payments"
        playbook.steps[0].postcondition = Postcondition("url_contains", "/payments")
        store.save_playbook(playbook)

        result = Executor(store, browser).run(domain_of(demo_server), task=self.TASK)

        assert result.ok is True, result.reason
        assert result.signed_in_already == []
        assert browser.page.inner_text("#sent") == "Submitted Dejo"

    def test_a_trail_that_only_signs_in_is_still_already_done(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        """Nothing comes after the sign-in, so there is nothing left to do."""
        store.save_playbook(
            Playbook(
                domain=domain_of(demo_server),
                task="sign in to the demo site",
                steps=[
                    Step(
                        1,
                        "open the sign-up page",
                        "goto",
                        Postcondition("url_contains", "/register"),
                        value=f"{demo_server}/register",
                    ),
                    Step(
                        2,
                        'click button "Continue with Google"',
                        "click",
                        Postcondition("url_contains", "/new-product"),
                        [Locator("role", "button|Continue with Google")],
                        page="/register",
                    ),
                ],
            )
        )
        browser.page.goto(f"{demo_server}/register")
        browser.page.click("text=Continue with Google")

        result = Executor(store, browser).run(
            domain_of(demo_server), task="sign in to the demo site"
        )

        assert result.already_done is True
        assert result.signed_in_already == []

    def test_signed_out_the_whole_trail_still_runs(
        self, store: DejoStore, browser: Browser, demo_server: str
    ) -> None:
        self.learned_signed_out(store, browser, demo_server)
        browser.page.context.clear_cookies()

        result = Executor(store, browser).run(domain_of(demo_server), task=self.TASK)

        assert result.ok is True, result.reason
        assert result.signed_in_already == []
        assert browser.page.inner_text("#sent") == "Submitted Dejo"


class TestWhichPagesSignIn:
    @pytest.mark.parametrize(
        "address",
        [
            "/register",
            "/login",
            "https://launchit.site/sign-in?next=/submit",
            "/users/sign_in",
            "/Login.aspx",
            "https://accounts.google.com/v3/signin/identifier",
            "https://accounts.google.com/o/oauth2/v2/auth",
            "/api/auth/callback/google",
            "/signup",
        ],
    )
    def test_a_sign_in_page(self, address: str) -> None:
        assert signs_in_at(address)

    @pytest.mark.parametrize(
        "address", ["/submit", "/authors", "/blog/how-to-login-faster", "/", "/registry"]
    )
    def test_not_a_sign_in_page(self, address: str) -> None:
        assert not signs_in_at(address)
