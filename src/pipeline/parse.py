"""Turn a rough pasted list into structured target rows."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.providers import llm

SYSTEM = """You turn messy pasted lists of people into structured outbound targets.
Return ONLY a JSON array. Each element: {"name": str, "company": str, "title": str,
"hints": str, "raw_line": str}.
- name: the person's full name if given, else "" (e.g. the line names only a role/company).
- company: organisation name, "" if unknown. title: role, "" if unknown.
- hints: any other useful detail from the input (location, LinkedIn URL, why they matter,
  mutual connections, product area) — keep it short; "" if none.
- raw_line: the original text this row came from.
Rules: one element per person. If a line lists several people, split them. Ignore headers,
bullets, numbering, blank lines and commentary that names nobody. Never invent people.
"""


@dataclass
class ParsedTarget:
    name: str
    company: str
    title: str
    hints: str
    raw_line: str


async def parse_list(raw: str) -> list[ParsedTarget]:
    raw = raw.strip()
    if not raw:
        return []
    data = await llm.complete_json(SYSTEM, f"Input list:\n\n{raw}", max_tokens=8000)
    rows: list[ParsedTarget] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            company = str(item.get("company") or "").strip()
            if not name and not company:
                continue
            rows.append(
                ParsedTarget(
                    name=name,
                    company=company,
                    title=str(item.get("title") or "").strip(),
                    hints=str(item.get("hints") or "").strip(),
                    raw_line=str(item.get("raw_line") or "").strip(),
                )
            )
    if rows:
        return rows
    return heuristic_parse(raw)


_SEP = re.compile(r"\s+[-–—]\s+|\s*[,|;]\s*|\t+")
_AT = re.compile(r"\s+(?:at|@)\s+", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def heuristic_parse(raw: str) -> list[ParsedTarget]:
    """Fallback for mock mode: 'Name - Title at Company' / 'Name, Company' / tabs / CSV."""
    rows: list[ParsedTarget] = []
    for line in raw.splitlines():
        line = _BULLET.sub("", line).strip()
        if not line or line.endswith(":"):
            continue
        parts = [p.strip() for p in _SEP.split(line) if p and p.strip()]
        if not parts:
            continue
        name = parts[0]
        title = company = ""
        rest = parts[1:]
        if len(rest) == 1:
            title_company = _AT.split(rest[0], maxsplit=1)
            if len(title_company) == 2:
                title, company = title_company
            else:
                company = rest[0]
        elif len(rest) >= 2:
            title, company = rest[0], rest[1]
        hints = " ".join(rest[2:])
        rows.append(
            ParsedTarget(name=name, company=company, title=title, hints=hints, raw_line=line)
        )
    return rows
