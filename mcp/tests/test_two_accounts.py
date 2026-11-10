"""Two accounts on one site, one task name: each account keeps its own route.

The safety lab's shop has a customer and a vendor. "Show my orders" is the customer's
purchases on one page and the vendor's sales on another. Learned as the customer, asked as
the vendor, the vendor gets a route of its own, and neither ever overwrites or blocks the
other's. Each signed-in role is a Dejo profile, so the profile is part of what a trail is.
"""

from __future__ import annotations

import pytest
from dejo.browser import domain_of
from dejo.store import DejoStore

from dejo_mcp.server import build_server
from helpers import call

TASK = "show my orders"
CUSTOMER = "asha@shop.test"
VENDOR = "sales@potters.test"
SHOP_COOKIE = "lab-shop"
CUSTOMER_STEPS = 'click link "My orders"\nread css "#orders" as orders'
VENDOR_STEPS = 'click link "Orders to ship"\nread css "#orders" as orders'


def vendor_steps(demo_server: str) -> str:
    """The vendor's own route, from the shop's home: a new task opens the site's front."""
    return f"go {demo_server}/safety/shop/home\n{VENDOR_STEPS}"


@pytest.fixture
def server(tmp_path):
    built = build_server(
        db_path=str(tmp_path / "memory.db"),
        headless=True,
        downloads=str(tmp_path / "downloads"),
        profile=str(tmp_path / "default-profile"),
        profiles_dir=str(tmp_path / "profiles"),
    )
    yield built
    built.dejo_tools.close()


def signed_in(server, demo_server: str, profile: str, email: str) -> None:
    """This profile's browser is signed in to the shop as `email`."""
    call(server, "dejo_profile", name=profile)
    tools = server.dejo_tools
    tools.worker.start()
    tools.worker.submit(
        lambda browser: browser._context.add_cookies(
            [{"name": SHOP_COOKIE, "value": email, "url": demo_server}]
        )
    )


def learn(server, demo_server: str, profile: str, steps: str) -> str:
    call(
        server,
        "dejo_run",
        site=demo_server,
        task=TASK,
        url=f"{demo_server}/safety/shop/home",
        profile=profile,
    )
    return call(server, "dejo_run", site=demo_server, task=TASK, steps=steps, profile=profile)


def ask(server, demo_server: str, profile: str) -> str:
    return call(server, "dejo_run", site=demo_server, task=TASK, profile=profile)


@pytest.fixture
def both_learned(server, demo_server):
    signed_in(server, demo_server, "customer", CUSTOMER)
    signed_in(server, demo_server, "vendor", VENDOR)
    saved = learn(server, demo_server, "customer", CUSTOMER_STEPS)
    assert "orders = 2 orders on the way" in saved, saved
    return server


def test_the_vendor_is_not_handed_the_customer_s_route(both_learned, demo_server):
    asked = ask(both_learned, demo_server, "vendor")

    assert "signed in as" not in asked, f"the vendor was blocked by the customer's trail:\n{asked}"
    assert "orders on the way" not in asked
    assert "Nothing saved for it yet" in asked, asked


def test_each_account_keeps_its_own_route(both_learned, demo_server):
    ask(both_learned, demo_server, "vendor")
    saved = call(
        both_learned,
        "dejo_run",
        site=demo_server,
        task=TASK,
        steps=vendor_steps(demo_server),
        profile="vendor",
    )
    assert "orders = 7 orders to ship" in saved, saved

    customer = ask(both_learned, demo_server, "customer")
    vendor = ask(both_learned, demo_server, "vendor")

    assert "orders = 2 orders on the way" in customer, customer
    assert "orders = 7 orders to ship" in vendor, vendor


def test_forgetting_the_site_forgets_every_account_s_route(both_learned, demo_server):
    ask(both_learned, demo_server, "vendor")
    call(both_learned, "dejo_run", site=demo_server, task=TASK, steps=vendor_steps(demo_server))

    said = call(both_learned, "dejo_manage", do="forget", site=demo_server)

    assert said.startswith("forgot"), said
    store = both_learned.dejo_tools.store
    key = domain_of(demo_server)
    for profile in ("customer", "vendor", "default"):
        assert store.for_profile(profile).load_playbook(key, TASK) is None, profile
    assert "Nothing saved for it yet" in ask(both_learned, demo_server, "customer")


def test_sharing_shares_the_route_of_the_account_in_use(both_learned, demo_server):
    ask(both_learned, demo_server, "vendor")
    call(both_learned, "dejo_run", site=demo_server, task=TASK, steps=vendor_steps(demo_server))

    call(both_learned, "dejo_manage", do="share", site=demo_server, task=TASK)
    store = both_learned.dejo_tools.store
    offers = store.offers_for(domain_of(demo_server))

    assert len(offers) == 1
    shared = store._offer(f"{domain_of(demo_server)}::show-my-orders::default")
    steps = [step["intent"] for step in shared["playbook"]["steps"]]
    assert any("Orders to ship" in intent for intent in steps), steps
    assert "signed_in_as" not in shared["playbook"]


def test_a_trail_saved_before_profiles_were_kept_apart_is_still_found(tmp_path, demo_server):
    """0.5.0 saved every profile's trails under one name. They must still replay."""
    db = str(tmp_path / "memory.db")
    old = DejoStore(db_path=db)
    from dejo.models import Playbook, Postcondition, Step

    old.save_playbook(
        Playbook(
            domain=domain_of(demo_server),
            task="open the shop",
            steps=[
                Step(
                    index=1,
                    intent="open the shop",
                    action="goto",
                    value=f"{demo_server}/safety/shop/home",
                    postcondition=Postcondition("url_contains", "/safety/shop/home"),
                )
            ],
        )
    )
    old.close()
    server = build_server(
        db_path=db,
        headless=True,
        profile=str(tmp_path / "default-profile"),
        profiles_dir=str(tmp_path / "profiles"),
    )
    try:
        for profile in ("default", "vendor"):
            said = call(server, "dejo_run", site=demo_server, task="open the shop", profile=profile)
            assert said.startswith('done: "open the shop"'), said
    finally:
        server.dejo_tools.close()


def test_a_trail_every_profile_reads_does_not_block_another_account(server, demo_server):
    """Learned in the default profile (or in 0.5.0 and older), so every profile reads it. The vendor
    finds it, the page names someone else, and the vendor learns its own instead of being
    told to switch away."""
    signed_in(server, demo_server, "default", CUSTOMER)
    signed_in(server, demo_server, "vendor", VENDOR)
    saved = learn(server, demo_server, "default", CUSTOMER_STEPS)
    assert "orders = 2 orders on the way" in saved, saved

    asked = ask(server, demo_server, "vendor")

    assert "this profile learns its own" in asked, asked
    assert "Nothing saved for it yet" in asked, asked
    learned = call(server, "dejo_run", site=demo_server, task=TASK, steps=vendor_steps(demo_server))
    assert "orders = 7 orders to ship" in learned, learned
    assert "orders = 2 orders on the way" in ask(server, demo_server, "default")
    assert "orders = 7 orders to ship" in ask(server, demo_server, "vendor")
