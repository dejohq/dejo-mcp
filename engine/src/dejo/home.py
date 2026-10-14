"""Where Dejo keeps things on this computer, and the one-time move from its old name.

Everything Dejo writes outside its memory lives under one folder, `~/.dejo`: the signed-in
browser profiles, downloaded files, and the optional secrets file.

Dejo was called Cairn until October 2026 and kept the same things in `~/.cairn`. The first
time Dejo starts on a machine that has the old folder and not the new one, it copies the old
one across, so nobody has to sign in to every site again. Copied, never moved: if anything
goes wrong, the original is untouched and the copy can simply be tried again.

The old `CAIRN_*` environment variables are still read when the `DEJO_*` one is not set, so
an existing MCP config keeps working after the upgrade.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

HOME = Path.home() / ".dejo"
OLD_HOME = Path.home() / ".cairn"

SETTING_PREFIX = "DEJO_"
OLD_SETTING_PREFIX = "CAIRN_"

# Written inside every browser profile to say which browser made it (see browser.py). The
# old name is renamed in each copied profile, so the browser that made it is still known.
PROFILE_OWNER = ".dejo-browser"
OLD_PROFILE_OWNER = ".cairn-browser"

# Left behind on purpose. Chrome's lock files belong to a browser that may still be running
# and mean nothing in a copy. The wallet files belonged to a payment feature Dejo no longer
# has, and a private key is not something to spread to a second folder.
NOT_COPIED = (
    "SingletonLock",
    "SingletonSocket",
    "SingletonCookie",
    "lockfile",
    "wallet.env",
    "*-shop.env",
)

# Where a copy is assembled before it becomes ~/.dejo. Renamed into place only once it is
# complete, so a copy that fails halfway never looks like a finished one.
PARTIAL_SUFFIX = ".partial"


class OldHomeNotCopied(RuntimeError):
    """`~/.cairn` exists and could not be copied to `~/.dejo`.

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
    """Copy `~/.cairn` to `~/.dejo` the first time Dejo starts. True if it copied.

    Does nothing when `~/.dejo` already exists or there was never a `~/.cairn`. Called by the
    `dejo` and `dejo-mcp` commands before anything else runs, never by the library, so a
    test or a program importing Dejo never touches the real folders.
    """
    home = home or HOME
    old = old or OLD_HOME
    if home.exists() or not old.is_dir():
        return False

    partial = home.with_name(home.name + PARTIAL_SUFFIX)
    shutil.rmtree(partial, ignore_errors=True)
    try:
        shutil.copytree(old, partial, ignore=shutil.ignore_patterns(*NOT_COPIED))
        _rename_profile_owners(partial)
        partial.rename(home)
    except OSError as failed:
        shutil.rmtree(partial, ignore_errors=True)
        raise OldHomeNotCopied(
            f"Dejo found your old Cairn folder at {old} but could not copy it to {home}: "
            f"{failed}. Close any Cairn or Dejo that is still running and start Dejo again. "
            f"To start fresh without your old sign-ins instead, create an empty folder at "
            f"{home}."
        ) from failed
    return True


def _rename_profile_owners(copied: Path) -> None:
    """Give every copied browser profile the new name for its owner marker.

    The marker sits at the top of a profile, and profiles live in exactly two places: the
    original one, and one folder each for the named ones.
    """
    profiles = copied / "profiles"
    named = (
        [folder for folder in profiles.iterdir() if folder.is_dir()] if profiles.is_dir() else []
    )
    for profile in [copied / "browser-profile", *named]:
        marker = profile / OLD_PROFILE_OWNER
        if marker.is_file():
            marker.rename(profile / PROFILE_OWNER)
