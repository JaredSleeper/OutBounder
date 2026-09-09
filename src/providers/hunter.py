"""Hunter.io email finder / domain pattern / verifier. Only used when HUNTER_API_KEY is set."""

from __future__ import annotations

import httpx
import structlog

from src.config import settings

logger = structlog.get_logger("hunter")

BASE = "https://api.hunter.io/v2"

# Hunter verification statuses -> our EmailCandidate.verification vocabulary
VERIFICATION_MAP = {
    "valid": "valid",
    "accept_all": "catch_all",
    "invalid": "invalid",
    "disposable": "invalid",
    "webmail": "unknown",
    "unknown": "unknown",
}


def configured() -> bool:
    return bool(settings.hunter_api_key)


async def _get(path: str, **params) -> dict | None:
    if not configured():
        return None
    params["api_key"] = settings.hunter_api_key
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{BASE}/{path}", params=params)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json().get("data") or None
    except httpx.HTTPError as exc:
        logger.warning("hunter_error", path=path, error=str(exc))
        return None


async def find_email(first: str, last: str, domain: str) -> dict | None:
    """Returns {email, score, verification, sources[]} or None."""
    if not (first and last and domain):
        return None
    data = await _get("email-finder", domain=domain, first_name=first, last_name=last)
    if not data or not data.get("email"):
        return None
    return {
        "email": data["email"],
        "score": data.get("score"),
        "verification": VERIFICATION_MAP.get(
            (data.get("verification") or {}).get("status") or "", "unknown"
        ),
        "sources": [s.get("uri") for s in data.get("sources") or [] if s.get("uri")][:3],
    }


async def domain_pattern(domain: str) -> str | None:
    """The most common address format Hunter has seen at this domain, e.g. '{first}.{last}'."""
    if not domain:
        return None
    data = await _get("domain-search", domain=domain, limit=1)
    return (data or {}).get("pattern") or None


async def verify(email: str) -> dict | None:
    """Returns {status, score} with status in our vocabulary, or None."""
    data = await _get("email-verifier", email=email)
    if not data:
        return None
    return {
        "status": VERIFICATION_MAP.get(data.get("status") or "", "unknown"),
        "score": data.get("score"),
    }
