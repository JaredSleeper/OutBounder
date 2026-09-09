"""Thin Anthropic wrapper. Returns None-ish results in mock mode (no key)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import anthropic
import structlog

from src.config import settings

logger = structlog.get_logger("llm")


@dataclass
class LLMResult:
    text: str
    mock: bool = False


def configured() -> bool:
    return settings.llm_configured


async def complete(
    system: str, prompt: str, max_tokens: int = 4000, web_searches: int = 0
) -> LLMResult:
    if not configured():
        return LLMResult(text="", mock=True)
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    kwargs: dict = {}
    if web_searches > 0:
        kwargs["tools"] = [
            {"type": "web_search_20250305", "name": "web_search", "max_uses": web_searches}
        ]
    resp = await client.messages.create(
        model=settings.default_llm_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    if resp.stop_reason == "max_tokens":
        logger.warning("llm_truncated", max_tokens=max_tokens)
    return LLMResult(text=text)


async def complete_json(
    system: str, prompt: str, max_tokens: int = 4000, web_searches: int = 0
) -> dict | list | None:
    result = await complete(system, prompt, max_tokens=max_tokens, web_searches=web_searches)
    if result.mock:
        return None
    parsed = extract_json(result.text)
    if parsed is None:
        logger.warning("llm_no_json", head=result.text[:200])
    return parsed


def extract_json(text: str) -> dict | list | None:
    """Pull the first JSON object/array out of a model response (handles ``` fences)."""
    candidates: list[str] = []
    for m in re.finditer(r"```(?:json)?\s*([\[{].*?[\]}])\s*```", text, re.DOTALL):
        candidates.append(m.group(1))
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])
    for c in candidates:
        try:
            out = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(out, dict | list):
            return out
    return None
