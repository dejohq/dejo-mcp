"""Fixtures for driving the MCP server the way a host AI would.

The demo billing site lives in the engine's test folder. It is loaded here by file path
rather than by putting that folder on `sys.path`, because both folders have a `tests`
package and the import would collide. One demo site is better than two that can drift.

It is loaded as a package rather than as a single file, because it is one: `app.py` imports
`hard.py` beside it, and a module loaded on its own cannot resolve a relative import.
"""

from __future__ import annotations

import importlib
import importlib.util
import socket
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

DEMO_SITE = Path(__file__).resolve().parents[2] / "engine" / "tests" / "demo_site"


DEMO_PACKAGE = "dejo_demo_site"


def _load_demo_app():
    """Import the demo site under a name of our own, so its own imports resolve."""
    spec = importlib.util.spec_from_file_location(
        DEMO_PACKAGE,
        DEMO_SITE / "__init__.py",
        submodule_search_locations=[str(DEMO_SITE)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the demo site from {DEMO_SITE}")

    package = importlib.util.module_from_spec(spec)
    sys.modules[DEMO_PACKAGE] = package
    spec.loader.exec_module(package)

    return importlib.import_module(f"{DEMO_PACKAGE}.app").app


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def demo_server() -> Iterator[str]:
    port = _free_port()
    config = uvicorn.Config(_load_demo_app(), host="127.0.0.1", port=port, log_level="error")
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
    """Dejo never stores passwords, so replay is given one the way a real user would."""
    from dejo.browser import domain_of
    from dejo.secrets import env_var_name

    monkeypatch.setenv(env_var_name(domain_of(demo_server), "password"), "hunter2")


@pytest.fixture
def mcp_server(tmp_path):
    """A server with its own memory database, torn down properly after each test."""
    from dejo_mcp.server import build_server

    # profile="" means a clean browser. Tests must never touch the real signed-in one.
    # profiles_dir matters as much: the server reopens whichever profile this machine used
    # last, and without a folder of its own a test inherits the developer's real choice —
    # which opened a signed-in Google profile already held by a running Dejo, and failed
    # 61 tests at once.
    server = build_server(
        db_path=str(tmp_path / "memory.db"),
        headless=True,
        downloads=str(tmp_path / "downloads"),
        profile="",
        profiles_dir=str(tmp_path / "profiles"),
    )
    yield server
    server.dejo_tools.close()
