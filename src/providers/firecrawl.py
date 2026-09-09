"""Firecrawl scrape → markdown. Optional; returns '' when not configured or on error."""

from __future__ import annotations

import httpx
import structlog

from src.config import settings

logger = structlog.get_logger("firecrawl")
BASE_URL = "https://api.firecrawl.dev/v1"


def configured() -> bool:
    return bool(settings.firecrawl_api_key)


async def scrape_markdown(url: str, max_chars: int = 6000) -> str:
    if not configured() or not url:
        return ""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{BASE_URL}/scrape",
                headers={"Authorization": f"Bearer {settings.firecrawl_api_key}"},
                json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
            )
            r.raise_for_status()
            data = r.json().get("data", {})
    except httpx.HTTPError as exc:
        logger.warning("firecrawl_error", url=url, error=str(exc))
        return ""
    return (data.get("markdown") or "")[:max_chars]
