"""Background poller for Cloud -> Print.

Runs inside the web process as an asyncio task. Each tick, if auto-print is on,
it checks the watched cloud folders and prints new files. The blocking network
and print work runs in a thread so the event loop stays responsive.
"""
from __future__ import annotations

import asyncio
import logging

from starlette.concurrency import run_in_threadpool

from .core import Core

log = logging.getLogger("printbridge")


class Poller:
    def __init__(self, core: Core, interval_seconds: int) -> None:
        self.core = core
        self.interval = max(10, int(interval_seconds))  # floor to avoid hammering
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                if self.core.autoprint_enabled():
                    count = await run_in_threadpool(self.core.poll_incoming_once)
                    if count:
                        log.info("auto-print: printed %d document(s)", count)
            except Exception:  # never let the loop die
                log.exception("auto-print poll failed")
            await asyncio.sleep(self.interval)
