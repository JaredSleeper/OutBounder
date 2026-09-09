from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from src import worker
from src.db import pool
from src.models import TargetUpdate

router = APIRouter()

_NULLABLE = {"company_domain", "linkedin_url", "best_email"}


@router.get("/{target_id}")
async def get_target(target_id: UUID):
    row = await pool().fetchrow("SELECT * FROM targets WHERE id=$1", target_id)
    if row is None:
        raise HTTPException(404, "Target not found")
    return dict(row)


@router.patch("/{target_id}")
async def update_target(target_id: UUID, body: TargetUpdate):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "Nothing to update")
    for k in _NULLABLE:
        if k in fields and not (fields[k] or "").strip():
            fields[k] = None
    for k, v in fields.items():
        if k not in _NULLABLE and v is None:
            fields[k] = ""
    sets = ", ".join(f"{k}=${i + 2}" for i, k in enumerate(fields))
    row = await pool().fetchrow(
        f"UPDATE targets SET {sets}, updated_at=now() WHERE id=$1 RETURNING *",
        target_id,
        *fields.values(),
    )
    if row is None:
        raise HTTPException(404, "Target not found")
    return dict(row)


@router.post("/{target_id}/rerun")
async def rerun_target(target_id: UUID):
    row = await pool().fetchrow(
        """
        UPDATE targets SET status='queued', error=NULL, attempts=0, updated_at=now()
        WHERE id=$1 RETURNING *
        """,
        target_id,
    )
    if row is None:
        raise HTTPException(404, "Target not found")
    worker.kick()
    return dict(row)


@router.delete("/{target_id}", status_code=204)
async def delete_target(target_id: UUID):
    await pool().execute("DELETE FROM targets WHERE id=$1", target_id)
