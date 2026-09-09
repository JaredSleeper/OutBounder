"""Exa search (neural + keyword) with page text."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx
import structlog

from src.config import settings

logger = structlog.get_logger("exa")
BASE_URL = "https://api.exa.ai"


@dataclass
class ExaResult:
    title: str
    url: str
    text: str
    published: str | None = None
    author: str | None = None
    extra: dict = field(default_factory=dict)


def configured() -> bool:
    return settings.exa_configured


async def search(
    query: str,
    *,
    num_results: int = 5,
    search_type: str = "auto",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    max_chars: int = 2500,
    category: str | None = None,
    start_published: str | None = None,
) -> list[ExaResult]:
    if not configured():
        return []
    body: dict = {
        "query": query,
        "type": search_type,
        "numResults": num_results,
        "contents": {"text": {"maxCharacters": max_chars}},
    }
    if include_domains:
        body["includeDomains"] = include_domains
    if exclude_domains:
        body["excludeDomains"] = exclude_domains
    if category:
        body["category"] = category
    if start_published:
        body["startPublishedDate"] = start_published
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(
                f"{BASE_URL}/search", headers={"x-api-key": settings.exa_api_key}, json=body
            )
            r.raise_for_status()
            payload = r.json()
    except httpx.HTTPError as exc:
        logger.warning("exa_error", query=query, error=str(exc))
        return []
    out: list[ExaResult] = []
    for res in payload.get("results", []):
        out.append(
            ExaResult(
                title=res.get("title") or "",
                url=res.get("url") or "",
                text=res.get("text") or "",
                published=res.get("publishedDate"),
                author=res.get("author"),
            )
        )
    return out
