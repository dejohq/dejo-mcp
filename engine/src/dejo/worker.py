"""Keeps one browser on one thread, so it can be driven from anywhere.

Playwright's sync API binds every object it creates to the thread that created it, and it
refuses to start inside a running asyncio loop. An MCP server breaks both rules: it runs an
event loop, and it hands each tool call to whichever worker thread happens to be free.

So instead of fighting it, the browser gets a thread of its own and every call is posted to
that thread. `dejo_look` and `dejo_act` arriving on different threads is then irrelevant —
the browser only ever sees one.

This lives in the engine rather than in `mcp/` because it is a property of driving a
browser, not a property of speaking MCP. The backend will need exactly the same thing.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import Any, TypeVar

from .browser import Browser

T = TypeVar("T")

_STOP = object()

# How long the browser is kept answered between looks at the job queue: the most a job can
# wait to start. Short enough that nobody notices, long enough that an idle worker is
# not a busy loop.
IDLE_SLICE_MS = 100


class BrowserWorker:
    """A browser that lives on its own thread, driven by posting callables to it."""

    def __init__(
        self,
        *,
        headless: bool = True,
        downloads: str | None = None,
        profile: str | None = None,
    ):
        self._headless = headless
        self._downloads = downloads
        self._profile = profile
        self._jobs: queue.Queue[Any] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._failure: BaseException | None = None
        self.browser: Browser | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._serve, name="dejo", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=60)
        if self._failure is not None:
            raise self._failure

    def submit(self, job: Callable[[Browser], T]) -> T:
        """Run `job` on the browser thread and wait for its result.

        Exceptions are re-raised here, on the caller's thread, so the caller sees a normal
        failure rather than a silent one buried in a background thread.
        """
        if not self.running:
            self.start()

        future: Future[T] = Future()
        self._jobs.put((job, future))
        return future.result()

    def stop(self) -> None:
        if not self.running:
            return
        self._jobs.put(_STOP)
        if self._thread is not None:
            self._thread.join(timeout=30)
        self._thread = None
        self.browser = None

    def _serve(self) -> None:
        try:
            self.browser = Browser(
                headless=self._headless,
                downloads=Path(self._downloads) if self._downloads else None,
                profile=Path(self._profile) if self._profile else None,
            ).start()
        except BaseException as failure:  # noqa: BLE001 - surfaced to start()
            self._failure = failure
            self._ready.set()
            return

        self._ready.set()
        try:
            while True:
                try:
                    job = self._jobs.get_nowait()
                except queue.Empty:
                    # Never block here: a browser nobody answers stalls (see Browser.idle).
                    self.browser.idle(IDLE_SLICE_MS)
                    continue
                if job is _STOP:
                    return
                call, future = job
                if future.set_running_or_notify_cancel():
                    try:
                        future.set_result(call(self.browser))
                    except BaseException as failure:  # noqa: BLE001 - handed to the caller
                        future.set_exception(failure)
        finally:
            if self.browser is not None:
                self.browser.stop()
            self.browser = None
