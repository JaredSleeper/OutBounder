"""Find the right person: LinkedIn profile, confirmed title/company, company domain."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from src.providers import exa, llm

SYSTEM = """You are a meticulous sales researcher. Given a target (name/company/title/hints)
and raw web search results, decide which result (if any) is the target person, and identify
their employer's primary website domain.
Return ONLY a JSON object:
{"linkedin_url": str|null, "confirmed_name": str, "confirmed_title": str|null,
 "confirmed_company": str|null, "location": str|null, "company_domain": str|null,
 "company_url": str|null, "confidence": 0-1, "notes": str,
 "other_links": [{"label": str, "url": str}]}
- confidence: how sure you are that linkedin_url/title/company belong to the intended person.
  Below 0.5 means you could not confidently identify them; say why in notes.
- company_domain: bare domain used for corporate email (e.g. "stripe.com", not "www." or a
  LinkedIn URL). If the company is known to you but no result shows the domain, use your
  knowledge. null if genuinely unknown.
- other_links: personal site, X/Twitter, GitHub, company team page — only if they appear in
  the results or you are certain of them.
Never fabricate a LinkedIn URL: only return one that appears verbatim in the results.
"""

_GENERIC_DOMAINS = {
    "linkedin.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "crunchbase.com",
    "wikipedia.org",
    "bloomberg.com",
    "zoominfo.com",
    "rocketreach.co",
    "apollo.io",
    "theorg.com",
    "github.com",
    "medium.com",
    "youtube.com",
    "glassdoor.com",
    "indeed.com",
    "signalhire.com",
    "contactout.com",
}


@dataclass
class Identity:
    linkedin_url: str | None = None
    confirmed_name: str = ""
    confirmed_title: str | None = None
    confirmed_company: str | None = None
    location: str | None = None
    company_domain: str | None = None
    company_url: str | None = None
    confidence: float = 0.0
    notes: str = ""
    other_links: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    profile_text: str = ""


def _domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return re.sub(r"^www\.", "", host)


def _is_generic(domain: str) -> bool:
    return any(domain == g or domain.endswith("." + g) for g in _GENERIC_DOMAINS)


def _linkedin_from_hints(hints: str) -> str | None:
    m = re.search(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w\-%.]+/?", hints or "", re.I)
    return m.group(0) if m else None


def _fmt(results: list[exa.ExaResult], limit: int = 1200) -> str:
    chunks = []
    for i, r in enumerate(results, 1):
        chunks.append(f"[{i}] {r.title}\nURL: {r.url}\n{r.text[:limit]}\n")
    return "\n".join(chunks) or "(no results)"


async def identify(name: str, company: str, title: str, hints: str) -> Identity:
    ident = Identity(confirmed_name=name)
    if not exa.configured():
        ident.notes = "EXA_API_KEY not configured — identification skipped"
        ident.linkedin_url = _linkedin_from_hints(hints)
        return ident

    who = " ".join(p for p in (name, title, company) if p).strip() or company
    profile_q = f"{who} LinkedIn profile"
    profiles = await exa.search(
        profile_q, num_results=5, include_domains=["linkedin.com"], max_chars=1500
    )
    hinted = _linkedin_from_hints(hints)
    if hinted and not any(hinted.rstrip("/") in r.url for r in profiles):
        extra = await exa.search(hinted, num_results=1, include_domains=["linkedin.com"])
        profiles = extra + profiles

    company_results: list[exa.ExaResult] = []
    if company:
        company_results = await exa.search(
            f"{company} official website",
            num_results=4,
            exclude_domains=sorted(_GENERIC_DOMAINS),
            max_chars=600,
        )
    general = await exa.search(
        f"{who}", num_results=4, exclude_domains=["linkedin.com"], max_chars=800
    )

    ident.sources = [
        {"title": r.title, "url": r.url} for r in [*profiles, *company_results, *general] if r.url
    ]

    prompt = (
        f"TARGET\nname: {name or '(unknown)'}\ncompany: {company or '(unknown)'}\n"
        f"title: {title or '(unknown)'}\nhints: {hints or '(none)'}\n\n"
        f"LINKEDIN RESULTS\n{_fmt(profiles)}\n\nCOMPANY RESULTS\n{_fmt(company_results, 500)}\n\n"
        f"OTHER RESULTS\n{_fmt(general, 700)}"
    )
    data = await llm.complete_json(SYSTEM, prompt, max_tokens=1500)

    if isinstance(data, dict):
        li = data.get("linkedin_url")
        if li and not any(str(li).rstrip("/") in r.url for r in profiles):
            li = None  # refuse fabricated profile URLs
        ident.linkedin_url = li or hinted
        ident.confirmed_name = str(data.get("confirmed_name") or name)
        ident.confirmed_title = data.get("confirmed_title") or None
        ident.confirmed_company = data.get("confirmed_company") or None
        ident.location = data.get("location") or None
        dom = str(data.get("company_domain") or "").lower().strip()
        dom = re.sub(r"^https?://", "", dom).split("/")[0]
        dom = re.sub(r"^www\.", "", dom)
        ident.company_domain = dom or None
        ident.company_url = data.get("company_url") or (f"https://{dom}" if dom else None)
        try:
            ident.confidence = max(0.0, min(1.0, float(data.get("confidence") or 0)))
        except (TypeError, ValueError):
            ident.confidence = 0.0
        ident.notes = str(data.get("notes") or "")
        ident.other_links = [
            {"label": str(x.get("label") or "Link"), "url": str(x.get("url"))}
            for x in data.get("other_links") or []
            if isinstance(x, dict) and x.get("url")
        ]
    else:
        # Mock/no-LLM fallback: top LinkedIn hit + first non-generic company domain.
        top = next((r for r in profiles if "/in/" in r.url), None)
        ident.linkedin_url = hinted or (top.url if top else None)
        for r in company_results:
            d = _domain_of(r.url)
            if d and not _is_generic(d):
                ident.company_domain = d
                ident.company_url = f"https://{d}"
                break
        ident.confidence = 0.4 if top else 0.1
        ident.notes = "Heuristic match (no LLM configured)"

    if ident.linkedin_url:
        match = next((r for r in profiles if ident.linkedin_url.rstrip("/") in r.url), None)
        if match:
            ident.profile_text = match.text
    return ident
