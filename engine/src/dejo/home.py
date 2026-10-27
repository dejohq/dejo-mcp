"""Where Dejo keeps things on this computer, and the one-time move from its old name.

Everything Dejo writes outside its memory lives under one folder, `~/.dejo`: the signed-in
browser profiles, downloaded files, and the optional secrets file.

Dejo was called Cairn until October 2026 and kept the same things in `~/.cairn`. The first
time Dejo starts on a machine that has the old folder and not the new one, it moves the old
folder to the new name, so nobody has to sign in to every site again. A move, not a copy: a
real user's folder held 1.5 GB of signed-in browser profiles, and copying that took longer
than an MCP client waits for a server to start, so the first start looked like a failure. A
rename is instant, doubles no disk space, and happens completely or not at all.

The old `CAIRN_*` environment variables are still read when the `DEJO_*` one is not set, so
an existing MCP config keeps working after the upgrade.
"""

from __future__ import annotations

import os
from pathlib import Path

HOME = Path.home() / ".dejo"
OLD_HOME = Path.home() / ".cairn"

SETTING_PREFIX = "DEJO_"
OLD_SETTING_PREFIX = "CAIRN_"

# Written inside every browser profile to say which browser made it (see browser.py). The
# old name is renamed in each moved profile, so the browser that made it is still known.
PROFILE_OWNER = ".dejo-browser"
OLD_PROFILE_OWNER = ".cairn-browser"

# Written inside a browser profile while a Dejo session has it open, saying which session
# (see locks.py). The operating system lets go of it when that session ends, however it ends.
PROFILE_IN_USE = ".dejo-in-use"


class OldHomeNotMoved(RuntimeError):
    """`~/.cairn` exists and could not be moved to `~/.dejo`.

    Raised rather than worked around. Starting with an empty `~/.dejo` would quietly sign
    the person out of every site they had signed in to, with nothing telling them why.
    """


def setting(name: str) -> str | None:
    """One `DEJO_` environment variable, or its old `CAIRN_` twin when only that is set.

    Takes the full new name, `DEJO_AGENT` or `DEJO_SECRET_ACME_COM_PASSWORD`. An empty value
    counts as unset, the same as everywhere else in Dejo.
    """
    found = os.environ.get(name)
    if found:
        return found
    if name.startswith(SETTING_PREFIX):
        return os.environ.get(OLD_SETTING_PREFIX + name[len(SETTING_PREFIX) :]) or None
    return None


def adopt_old_home(home: Path | None = None, old: Path | None = None) -> bool:
    """Move `~/.cairn` to `~/.dejo` the first time Dejo starts. True if it moved.

    Does nothing when `~/.dejo` already exists or there was never a `~/.cairn`. Called by the
    `dejo` and `dejo-mcp` commands before anything else runs, never by the library, so a
    test or a program importing Dejo never touches the real folders.
    """
    home = home or HOME
    old = old or OLD_HOME
    if home.exists() or not old.is_dir():
        return False

    try:
        old.rename(home)
    except OSError as failed:
        # On Windows a folder with a file still open in it cannot be renamed at all. Nothing
        # has moved, so the next start simply tries again.
        raise OldHomeNotMoved(
            f"Dejo found your old Cairn folder at {old} but could not move it to {home}: "
            f"{failed}. Close any Cairn or Dejo that is still running, including old MCP "
            f"servers, and start Dejo again."
        ) from failed
    _rename_profile_owners(home)
    return True


def _rename_profile_owners(moved: Path) -> None:
    """Give every moved browser profile the new name for its owner marker.

    The marker sits at the top of a profile, and profiles live in exactly two places: the
    original one, and one folder each for the named ones.
    """
    profiles = moved / "profiles"
    named = (
        [folder for folder in profiles.iterdir() if folder.is_dir()] if profiles.is_dir() else []
    )
    for profile in [moved / "browser-profile", *named]:
        marker = profile / OLD_PROFILE_OWNER
        if marker.is_file():
            marker.rename(profile / PROFILE_OWNER)
