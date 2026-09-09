"""Run the enrichment stages for one target, persisting after each stage."""

from __future__ import annotations

import structlog

from src.db import pool
from src.pipeline import emails, identify, research

logger = structlog.get_logger("pipeline")


async def _set_status(target_id, status: str) -> None:
    await pool().execute(
        "UPDATE targets SET status=$2, stage_started_at=now(), updated_at=now() WHERE id=$1",
        target_id,
        status,
    )


async def enrich_target(target_id) -> None:
    db = pool()
    row = await db.fetchrow(
        "SELECT t.*, l.context FROM targets t JOIN lists l ON l.id=t.list_id WHERE t.id=$1",
        target_id,
    )
    if row is None:
        return
    name = row["name"] or ""
    company = row["company"] or ""
    title = row["title"] or ""
    hints = row["hints"] or ""
    # Values already on the row (user-edited or from a previous run) are pinned: they are
    # passed as hints and win over whatever the search turns up. Clear them to re-detect.
    pinned_linkedin = row["linkedin_url"]
    pinned_domain = row["company_domain"]
    search_hints = " | ".join(
        p
        for p in (
            hints,
            f"LinkedIn: {pinned_linkedin}" if pinned_linkedin else "",
            f"company email domain: {pinned_domain}" if pinned_domain else "",
        )
        if p
    )
    try:
        # 1. identify -----------------------------------------------------
        await _set_status(target_id, "identifying")
        ident = await identify.identify(name, company, title, search_hints)
        if pinned_linkedin:
            ident.linkedin_url = pinned_linkedin
        if pinned_domain:
            ident.company_domain = pinned_domain
            ident.company_url = ident.company_url or f"https://{pinned_domain}"
        display_name = ident.confirmed_name or name
        await db.execute(
            """
            UPDATE targets SET
              linkedin_url=$2, company_domain=$3, company_url=$4, location=$5,
              confirmed_name=$6, confirmed_title=$7, confirmed_company=$8,
              identity_confidence=$9, identity_notes=$10, sources=$11::jsonb,
              links=$12::jsonb, updated_at=now()
            WHERE id=$1
            """,
            target_id,
            ident.linkedin_url,
            ident.company_domain,
            ident.company_url,
            ident.location,
            display_name,
            ident.confirmed_title,
            ident.confirmed_company,
            ident.confidence,
            ident.notes,
            ident.sources,
            research.build_links(
                display_name,
                ident.confirmed_company or company,
                ident.linkedin_url,
                ident.company_url,
                ident.other_links,
                [],
            ),
        )

        # 2. emails -------------------------------------------------------
        await _set_status(target_id, "finding_email")
        finding = await emails.find_emails(display_name, ident.company_domain)
        await db.execute(
            """
            UPDATE targets SET emails=$2::jsonb, best_email=$3, email_pattern=$4,
              domain_checks=$5::jsonb, sources = sources || $6::jsonb, updated_at=now()
            WHERE id=$1
            """,
            target_id,
            [c.to_dict() for c in finding.candidates],
            finding.best,
            finding.pattern,
            finding.domain_checks,
            finding.sources,
        )

        # 3. research -----------------------------------------------------
        await _set_status(target_id, "researching")
        res = await research.research(
            name=display_name,
            title=ident.confirmed_title or title,
            company=ident.confirmed_company or company,
            company_url=ident.company_url,
            linkedin_url=ident.linkedin_url,
            profile_text=ident.profile_text,
            hints=hints,
            context=row["context"] or "",
            other_links=ident.other_links,
        )
        await db.execute(
            """
            UPDATE targets SET research=$2::jsonb, links=$3::jsonb,
              sources = sources || $4::jsonb, status='done', error=NULL,
              enriched_at=now(), updated_at=now()
            WHERE id=$1
            """,
            target_id,
            res.data,
            res.links,
            res.sources,
        )
        logger.info("target_enriched", target=str(target_id), name=display_name)
    except Exception as exc:  # noqa: BLE001 — surface any stage failure on the row
        logger.exception("target_failed", target=str(target_id))
        await db.execute(
            "UPDATE targets SET status='error', error=$2, updated_at=now() WHERE id=$1",
            target_id,
            f"{type(exc).__name__}: {exc}"[:800],
        )
