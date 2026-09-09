"""Hunter.io email finder. Optional; only used when HUNTER_API_KEY is set."""

from __future__ import annotations

import httpx
import structlog

from src.config import settings

logger = structlog.get_logger("hunter")


def configured() -> bool:
    return bool(settings.hunter_api_key)


async def find_email(first: str, last: str, domain: str) -> dict | None:
    """Returns {email, score, verification} or None."""
    if not configured() or not (first and last and domain):
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                "https://api.hunter.io/v2/email-finder",
                params={
                    "domain": domain,
                    "first_name": first,
                    "last_name": last,
                    "api_key": settings.hunter_api_key,
                },
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            data = r.json().get("data", {})
    except httpx.HTTPError as exc:
        logger.warning("hunter_error", domain=domain, error=str(exc))
        return None
    if not data.get("email"):
        return None
    return {
        "email": data["email"],
        "score": data.get("score"),
        "verification": (data.get("verification") or {}).get("status"),
    }
