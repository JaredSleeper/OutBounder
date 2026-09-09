"""In-process queue: claims queued targets (SKIP LOCKED) and enriches them concurrently."""

from __future__ import annotations

import asyncio
import contextlib

import structlog

from src.config import settings
from src.db import pool
from src.pipeline.run import enrich_target

logger = structlog.get_logger("worker")

_task: asyncio.Task | None = None
_stop = asyncio.Event()
_wake = asyncio.Event()

# Rows stuck mid-stage (e.g. after a redeploy) are re-queued after this long.
STALE_MINUTES = 15


def kick() -> None:
    _wake.set()


async def _claim_one():
    return await pool().fetchrow(
        """
        WITH next AS (
          SELECT id FROM targets
          WHERE status = 'queued'
          ORDER BY created_at, position
          FOR UPDATE SKIP LOCKED
          LIMIT 1
        )
        UPDATE targets t SET status='identifying', stage_started_at=now(),
          attempts = attempts + 1, updated_at=now()
        FROM next WHERE t.id = next.id
        RETURNING t.id
        """
    )


async def _requeue_stale() -> None:
    await pool().execute(
        """
        UPDATE targets SET status='queued', updated_at=now()
        WHERE status IN ('identifying','finding_email','researching')
          AND stage_started_at < now() - make_interval(mins => $1)
          AND attempts < 3
        """,
        STALE_MINUTES,
    )


async def _runner(sem: asyncio.Semaphore, target_id) -> None:
    async with sem:
        await enrich_target(target_id)


async def _loop() -> None:
    sem = asyncio.Semaphore(settings.worker_concurrency)
    inflight: set[asyncio.Task] = set()
    await _requeue_stale()
    while not _stop.is_set():
        try:
            while len(inflight) < settings.worker_concurrency:
                row = await _claim_one()
                if row is None:
                    break
                t = asyncio.create_task(_runner(sem, row["id"]))
                inflight.add(t)
                t.add_done_callback(inflight.discard)
        except Exception:  # noqa: BLE001
            logger.exception("worker_claim_failed")
        _wake.clear()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_wake.wait(), timeout=settings.worker_poll_seconds)
    if inflight:
        await asyncio.gather(*inflight, return_exceptions=True)


def start() -> None:
    global _task
    if not settings.worker_enabled or _task is not None:
        return
    _stop.clear()
    _task = asyncio.create_task(_loop())
    logger.info("worker_started", concurrency=settings.worker_concurrency)


async def stop() -> None:
    global _task
    if _task is None:
        return
    _stop.set()
    _wake.set()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(_task, timeout=10)
    _task = None
