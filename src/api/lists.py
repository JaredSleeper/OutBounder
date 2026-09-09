from __future__ import annotations

import asyncio
import contextlib
import csv
import io
from datetime import UTC, datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from src import worker
from src.db import pool
from src.models import AppendTargets, ListCreate, ListUpdate
from src.pipeline.parse import parse_list

logger = structlog.get_logger("lists")
router = APIRouter()

_bg: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


async def _parse_and_insert(list_id: UUID, raw: str) -> None:
    db = pool()
    try:
        rows = await parse_list(raw)
        start = await db.fetchval(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM targets WHERE list_id=$1", list_id
        )
        await db.executemany(
            """
            INSERT INTO targets (list_id, position, raw_line, name, company, title, hints)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            [
                (list_id, start + i, r.raw_line, r.name, r.company, r.title, r.hints)
                for i, r in enumerate(rows)
            ],
        )
        await db.execute(
            "UPDATE lists SET status='ready', error=NULL, updated_at=now() WHERE id=$1", list_id
        )
        worker.kick()
    except Exception as exc:  # noqa: BLE001
        logger.exception("parse_failed", list_id=str(list_id))
        await db.execute(
            "UPDATE lists SET status='error', error=$2, updated_at=now() WHERE id=$1",
            list_id,
            f"{type(exc).__name__}: {exc}"[:500],
        )


@router.get("")
async def list_lists():
    rows = await pool().fetch(
        """
        SELECT l.*,
          COUNT(t.id) AS total,
          COUNT(t.id) FILTER (WHERE t.status='done') AS done,
          COUNT(t.id) FILTER (WHERE t.status='error') AS errors,
          COUNT(t.id) FILTER (WHERE t.status NOT IN ('done','error')) AS pending
        FROM lists l LEFT JOIN targets t ON t.list_id=l.id
        GROUP BY l.id ORDER BY l.created_at DESC
        """
    )
    return [dict(r) for r in rows]


@router.post("", status_code=201)
async def create_list(body: ListCreate):
    name = body.name.strip() or f"List {datetime.now(tz=UTC).strftime('%b %d, %H:%M')}"
    row = await pool().fetchrow(
        """
        INSERT INTO lists (name, raw_input, context, status)
        VALUES ($1, $2, $3, 'parsing') RETURNING *
        """,
        name,
        body.raw_input,
        body.context.strip(),
    )
    _spawn(_parse_and_insert(row["id"], body.raw_input))
    return dict(row)


@router.get("/{list_id}")
async def get_list(list_id: UUID):
    row = await pool().fetchrow("SELECT * FROM lists WHERE id=$1", list_id)
    if row is None:
        raise HTTPException(404, "List not found")
    targets = await pool().fetch(
        "SELECT * FROM targets WHERE list_id=$1 ORDER BY position, created_at", list_id
    )
    return {**dict(row), "targets": [dict(t) for t in targets]}


@router.patch("/{list_id}")
async def update_list(list_id: UUID, body: ListUpdate):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "Nothing to update")
    sets = ", ".join(f"{k}=${i + 2}" for i, k in enumerate(fields))
    row = await pool().fetchrow(
        f"UPDATE lists SET {sets}, updated_at=now() WHERE id=$1 RETURNING *",
        list_id,
        *fields.values(),
    )
    if row is None:
        raise HTTPException(404, "List not found")
    return dict(row)


@router.delete("/{list_id}", status_code=204)
async def delete_list(list_id: UUID):
    await pool().execute("DELETE FROM lists WHERE id=$1", list_id)


@router.post("/{list_id}/append", status_code=202)
async def append_targets(list_id: UUID, body: AppendTargets):
    row = await pool().fetchrow(
        """
        UPDATE lists SET raw_input = raw_input || E'\\n' || $2, status='parsing', updated_at=now()
        WHERE id=$1 RETURNING id
        """,
        list_id,
        body.raw_input,
    )
    if row is None:
        raise HTTPException(404, "List not found")
    _spawn(_parse_and_insert(list_id, body.raw_input))
    return {"ok": True}


@router.post("/{list_id}/rerun")
async def rerun_list(list_id: UUID, only_errors: bool = False):
    where = "AND status='error'" if only_errors else "AND status IN ('done','error')"
    n = await pool().execute(
        f"UPDATE targets SET status='queued', error=NULL, updated_at=now() "
        f"WHERE list_id=$1 {where}",
        list_id,
    )
    worker.kick()
    with contextlib.suppress(ValueError):
        return {"requeued": int(n.split()[-1])}
    return {"requeued": 0}


@router.get("/{list_id}/export.csv")
async def export_csv(list_id: UUID):
    rows = await pool().fetch(
        "SELECT * FROM targets WHERE list_id=$1 ORDER BY position, created_at", list_id
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "name",
            "title",
            "company",
            "location",
            "email",
            "email_confidence",
            "email_verification",
            "all_emails",
            "linkedin",
            "company_url",
            "hooks",
            "bio",
            "recent",
            "outreach_status",
            "notes",
            "status",
        ]
    )
    for t in rows:
        emails = t["emails"] or []
        best = next((e for e in emails if e["email"] == t["best_email"]), None)
        r = t["research"] or {}
        w.writerow(
            [
                t["confirmed_name"] or t["name"],
                t["confirmed_title"] or t["title"],
                t["confirmed_company"] or t["company"],
                t["location"] or "",
                t["best_email"] or "",
                best["confidence"] if best else "",
                best["verification"] if best else "",
                "; ".join(e["email"] for e in emails),
                t["linkedin_url"] or "",
                t["company_url"] or "",
                " | ".join(r.get("hooks") or []),
                " | ".join(r.get("bio") or []),
                " | ".join(x.get("text", "") for x in r.get("recent") or []),
                t["outreach_status"],
                t["notes"],
                t["status"],
            ]
        )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="outbounder-{list_id}.csv"'},
    )
