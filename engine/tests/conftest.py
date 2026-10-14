"""Shared fixtures: a real demo server, a real browser, and a scripted cold run.

The cold run helper stands in for the host AI. In production that is the user's Claude
Code calling look/act/verify through the MCP server; in tests it is a fixed script. Either
way Dejo's own code is identical, which is the point of keeping the brain outside the
engine.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from tests.demo_site.app import app

from dejo.browser import Browser, domain_of
from dejo.operations import Session
from dejo.secrets import env_var_name
from dejo.store import DejoStore

TASK = "download this month's invoice"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def demo_server() -> Iterator[str]:
    """The demo billing site, running for real over HTTP for the whole test session."""
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("demo site did not start")
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(autouse=True)
def demo_password(demo_server, monkeypatch):
    """Give this machine the demo site's password.

    Dejo deliberately never stores passwords, so a replay cannot supply one from memory.
    This is the same thing a real user does with an environment variable — and it means
    the suite proves the secret path works rather than skipping past it.
    """
    monkeypatch.setenv(env_var_name(domain_of(demo_server), "password"), "hunter2")


@pytest.fixture(autouse=True)
def nothing_real_is_touched(tmp_path_factory, monkeypatch) -> None:
    """Every place Dejo keeps things on this machine, moved somewhere throwaway.

    A test once ran the doctor's real checks, which made ~/.dejo/downloads and an empty
    ~/.dejo/memory.db in the developer's own home folder. Dejo only brings an old ~/.cairn
    across when ~/.dejo does not exist yet, so that empty folder would have silently cost
    the developer every sign-in. A test passes its own paths where it can; this catches
    every place it forgot to.
    """
    import dejo.browser
    import dejo.home
    import dejo.memory
    import dejo.secrets
    import dejo.store

    fake = tmp_path_factory.mktemp("home")
    places = {
        (dejo.home, "HOME"): fake / ".dejo",
        (dejo.home, "OLD_HOME"): fake / ".cairn",
        (dejo.browser, "DEFAULT_DOWNLOADS"): fake / ".dejo" / "downloads",
        (dejo.browser, "DEFAULT_PROFILE"): fake / ".dejo" / "browser-profile",
        (dejo.browser, "DEFAULT_PROFILES_DIR"): fake / ".dejo" / "profiles",
        (dejo.secrets, "SECRETS_FILE"): fake / ".dejo" / "secrets.json",
        (dejo.memory, "DEFAULT_PATH"): fake / ".dejo" / "memory.db",
        (dejo.memory, "SIBYL_PATH"): fake / ".sibyl-memory" / "memory.db",
        (dejo.store, "DEFAULT_PATH"): fake / ".dejo" / "memory.db",
        (dejo.store, "SIBYL_PATH"): fake / ".sibyl-memory" / "memory.db",
    }
    for (module, name), where in places.items():
        monkeypatch.setattr(module, name, where)


@pytest.fixture
def browser(tmp_path) -> Iterator[Browser]:
    """Downloads go into the test's own folder, never the real ~/.dejo/downloads."""
    with Browser(headless=True, downloads=tmp_path / "downloads") as running:
        yield running


@pytest.fixture
def store(tmp_path) -> DejoStore:
    """Its own database every time, so tests never touch real memory."""
    return DejoStore(db_path=str(tmp_path / "memory.db"))


def ref_named(snapshot: dict[str, Any], name: str) -> str:
    """Find a control by its visible name, the way a person would."""
    for element in snapshot["elements"]:
        if element["name"] == name:
            return element["ref"]
    names = [element["name"] for element in snapshot["elements"]]
    raise AssertionError(f"no control named {name!r} on this page. saw: {names}")


def cold_run(session: Session, base_url: str, *, variant: str = "a") -> None:
    """What the host AI does on the first visit: look, act, look, act.

    Seven calls. Every later run replays this in one.
    """
    suffix = "" if variant == "a" else f"?variant={variant}"
    session.act("open the billing portal", "goto", value=f"{base_url}/{suffix}")

    page = session.look()
    session.act(
        "type the account email", "fill", ref=ref_named(page, "Email"), value="finance@acme.com"
    )
    session.act("type the password", "fill", ref=ref_named(page, "Password"), value="hunter2")
    session.act("sign in", "click", ref=ref_named(page, "Sign in"))

    page = session.look()
    session.act("open this month's invoice", "click", ref=ref_named(page, "September 2026"))

    page = session.look()
    label = "Download" if variant == "a" else "Get PDF"
    session.act("download the PDF", "click", ref=ref_named(page, label))
