"""A task half-learned by one account is never resumed, or dropped, by another.

Dejo keeps the steps of a task still being learned as a draft, so a lost session loses
nothing. The customer gets as far as opening "My orders" and stops before the read. The
vendor then starts the same task in its own profile: it must start fresh, and the
customer's draft must still be there when the customer comes back.
"""

from __future__ import annotations

import pytest
from dejo.browser import domain_of

from dejo_mcp.server import build_server
from helpers import call

TASK = "show my orders"
SHOP_COOKIE = "lab-shop"


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
    call(server, "dejo_profile", name=profile)
    server.dejo_tools.worker.start()
    server.dejo_tools.worker.submit(
        lambda browser: browser._context.add_cookies(
            [{"name": SHOP_COOKIE, "value": email, "url": demo_server}]
        )
    )


def start(server, demo_server: str, profile: str) -> str:
    return call(
        server,
        "dejo_run",
        site=demo_server,
        task=TASK,
        url=f"{demo_server}/safety/shop/home",
        profile=profile,
    )


def test_another_account_never_picks_up_a_half_learned_task(server, demo_server):
    signed_in(server, demo_server, "customer", "asha@shop.test")
    signed_in(server, demo_server, "vendor", "sales@potters.test")
    start(server, demo_server, "customer")
    halfway = call(server, "dejo_run", site=demo_server, task=TASK, steps='click link "My orders"')
    assert "Nothing saved yet" in halfway, halfway

    vendor = start(server, demo_server, "vendor")

    assert "draft" not in vendor, f"the vendor was handed the customer's draft:\n{vendor}"
    call(server, "dejo_profile", name="customer")
    kept = server.dejo_tools.store.load_draft(domain_of(demo_server), TASK)
    assert kept is not None, "the vendor's start threw the customer's draft away"
    assert [step.intent for step in kept.steps][-1] == 'click link "My orders"'
