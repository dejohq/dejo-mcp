"""One Dejo session per browser profile, and a sentence that names the other one.

Chrome lets one browser at a time open a profile. When a second Dejo session (another agent,
another terminal) asked for a profile the first one held, Chrome refused, Dejo fell back to the
bundled Chromium, and the reply said only "Chrome would not open Dejo's browser profile". That
is true and says nothing about what to do: the cause was a session the person could close.

So a session that opens a profile holds a lock on a file inside it, and writes who it is
there. The lock is the operating system's own, so it goes away when the session ends, even
when it crashes: no stale lock is ever left to clean up by hand.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .home import PROFILE_IN_USE, setting

# The byte that is locked, far past the words about the holder. A lock on Windows is
# mandatory, so a lock over the words would stop the second session reading who holds it.
LOCKED_BYTE = 1 << 20


class ProfileHeld(RuntimeError):
    """Another live Dejo session holds this profile. The message names it."""


class ProfileLock:
    """The hold one session has on one profile. Released by `release`, or by the session
    ending."""

    def __init__(self, profile: Path) -> None:
        self.profile = profile
        self._fd: int | None = None

    def acquire(self) -> ProfileLock:
        """Take the profile, or raise `ProfileHeld` naming the session that has it."""
        path = self.profile / PROFILE_IN_USE
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        if not _lock(fd):
            os.close(fd)
            raise ProfileHeld(_holder(path))
        self._fd = fd
        os.lseek(fd, 0, os.SEEK_SET)
        # One line, and no truncating: on Windows a file cannot be cut shorter across a
        # locked byte. A reader takes the first line, so what an older holder left after it
        # is never read.
        os.write(fd, (json.dumps(_who_am_i()) + "\n").encode("utf-8"))
        return self

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        _unlock(fd)
        os.close(fd)


def _who_am_i() -> dict[str, object]:
    return {
        "pid": os.getpid(),
        "program": Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "python",
        "agent": setting("DEJO_AGENT") or "",
        "since": datetime.now().astimezone().strftime("%d %b %H:%M"),
    }


def _holder(path: Path) -> str:
    """The session holding `path`, in words, from what it wrote there."""
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
        held = json.loads(first)
    except (OSError, IndexError, ValueError):
        return "another Dejo session"
    agent = f", agent {held['agent']}" if held.get("agent") else ""
    return (
        f"another Dejo session (process {held.get('pid', '?')}, {held.get('program', 'dejo')}"
        f"{agent}, open since {held.get('since', '?')})"
    )


if sys.platform == "win32":
    import msvcrt

    def _lock(fd: int) -> bool:
        os.lseek(fd, LOCKED_BYTE, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, LOCKED_BYTE, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            return  # closing the file lets go of it anyway

else:
    import fcntl

    def _lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
