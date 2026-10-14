"""The MCP Registry listing has to agree with the package it points at.

The official registry proves we own `dejo-mcp` on PyPI by finding `mcp-name: <server name>` in
the package README, and it rejects a listing whose version is not a real release. Three files
carry those facts — server.json, mcp/README.md and mcp/pyproject.toml — so a release that bumps
one and forgets another would fail to publish. These tests make the forgetting impossible.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def server() -> dict:
    return json.loads((REPO / "server.json").read_text(encoding="utf-8"))


def mcp_project() -> dict:
    return tomllib.loads((REPO / "mcp" / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_the_readme_on_pypi_proves_ownership() -> None:
    readme = (REPO / "mcp" / "README.md").read_text(encoding="utf-8")

    assert f"mcp-name: {server()['name']} -->" in readme


def test_the_listing_points_at_this_package_and_version() -> None:
    project = mcp_project()
    listing = server()
    package = listing["packages"][0]

    assert package["registryType"] == "pypi"
    assert package["identifier"] == project["name"]
    assert package["version"] == listing["version"] == project["version"]


def test_the_engine_and_server_are_released_together() -> None:
    engine = tomllib.loads((REPO / "engine" / "pyproject.toml").read_text(encoding="utf-8"))

    assert engine["project"]["version"] == mcp_project()["version"]
    assert f"dejo>={engine['project']['version']}" in mcp_project()["dependencies"]
