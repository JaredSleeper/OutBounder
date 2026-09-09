"""Basic research: who they are, what the company does, what's recent, hooks for an email."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

from src.providers import exa, firecrawl, llm

SYSTEM = """You are a sharp sales-research analyst preparing a one-page brief so a founder can
write a personal cold email in two minutes. Today is {today}.
Use ONLY the supplied material (plus well-established public knowledge about the company).
Return ONLY a JSON object:
{{
 "bio": [str, ...],            // 2-4 crisp bullets on the person: role scope, background, tenure
 "company_summary": str,       // 1-2 sentences: what the company does, size/stage if known
 "recent": [{{"text": str, "url": str|null, "date": str|null}}, ...],
                               // up to 4 recent items (news, posts, talks, hires, funding),
                               // newest first
 "hooks": [str, ...],          // 3 specific, non-generic angles to open an email with;
                               // reference concrete facts
 "talking_points": [str, ...], // 2-4 things relevant to the sender's context (below)
 "caveats": str                // anything uncertain (e.g. "could not confirm current role")
}}
Do not pad. Empty arrays are fine when the material is thin. No marketing fluff.
Keep every string under 200 characters. Output the JSON only, no code fences or commentary.
"""


@dataclass
class Research:
    data: dict = field(default_factory=dict)
    links: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)


def _fmt(results: list[exa.ExaResult], limit: int) -> str:
    chunks = []
    for i, r in enumerate(results, 1):
        date = f" ({r.published[:10]})" if r.published else ""
        chunks.append(f"[{i}] {r.title}{date}\nURL: {r.url}\n{r.text[:limit]}\n")
    return "\n".join(chunks) or "(none)"


def build_links(
    name: str,
    company: str | None,
    linkedin_url: str | None,
    company_url: str | None,
    other: list[dict],
    articles: list[dict],
) -> list[dict]:
    links: list[dict] = []
    if linkedin_url:
        links.append({"label": "LinkedIn", "url": linkedin_url, "kind": "profile"})
    if company_url:
        links.append({"label": "Company site", "url": company_url, "kind": "company"})
    for o in other:
        if o.get("url") and o["url"] not in {x["url"] for x in links}:
            links.append({"label": o.get("label") or "Link", "url": o["url"], "kind": "profile"})
    q_person = quote_plus(f'"{name}" {company or ""}'.strip())
    links.append(
        {
            "label": "Google News",
            "url": f"https://news.google.com/search?q={q_person}",
            "kind": "search",
        }
    )
    links.append(
        {"label": "Google", "url": f"https://www.google.com/search?q={q_person}", "kind": "search"}
    )
    links.append(
        {
            "label": "X search",
            "url": f"https://x.com/search?q={q_person}&f=user",
            "kind": "search",
        }
    )
    if company:
        links.append(
            {
                "label": "Crunchbase",
                "url": f"https://www.crunchbase.com/textsearch?q={quote_plus(company)}",
                "kind": "search",
            }
        )
        links.append(
            {
                "label": "Company news",
                "url": f"https://news.google.com/search?q={quote_plus(company)}",
                "kind": "search",
            }
        )
    for a in articles[:6]:
        if a.get("url") and a["url"] not in {x["url"] for x in links}:
            links.append(
                {"label": (a.get("title") or "Article")[:70], "url": a["url"], "kind": "article"}
            )
    return links


async def research(
    *,
    name: str,
    title: str | None,
    company: str | None,
    company_url: str | None,
    linkedin_url: str | None,
    profile_text: str,
    hints: str,
    context: str,
    other_links: list[dict],
) -> Research:
    out = Research()
    who = " ".join(p for p in (name, title, company) if p)
    recent_since = (datetime.now(tz=UTC) - timedelta(days=540)).strftime("%Y-%m-%d")

    person_news: list[exa.ExaResult] = []
    company_news: list[exa.ExaResult] = []
    homepage = ""
    if exa.configured():
        person_news = await exa.search(
            f'"{name}" {company or ""} interview OR announcement OR post OR talk',
            num_results=6,
            exclude_domains=["linkedin.com"],
            max_chars=1800,
            start_published=recent_since,
        )
        if company:
            company_news = await exa.search(
                f"{company} news funding launch product",
                num_results=5,
                category="news",
                max_chars=1200,
                start_published=recent_since,
            )
    if company_url:
        homepage = await firecrawl.scrape_markdown(company_url, max_chars=4000)
        if not homepage and exa.configured():
            hp = await exa.search(company_url, num_results=1, max_chars=4000)
            homepage = hp[0].text if hp else ""

    articles = [
        {"title": r.title, "url": r.url, "date": r.published}
        for r in [*person_news, *company_news]
        if r.url
    ]
    out.sources = articles
    out.links = build_links(name, company, linkedin_url, company_url, other_links, articles)

    prompt = (
        f"TARGET: {who}\nLinkedIn: {linkedin_url or 'n/a'}\nHints from my list: {hints or 'none'}\n"
        f"SENDER CONTEXT (what I'm reaching out about): {context or 'not specified'}\n\n"
        f"LINKEDIN PROFILE TEXT\n{profile_text[:2500] or '(none)'}\n\n"
        f"COMPANY HOMEPAGE\n{homepage[:3000] or '(none)'}\n\n"
        f"RESULTS ABOUT THE PERSON\n{_fmt(person_news, 1500)}\n\n"
        f"RESULTS ABOUT THE COMPANY\n{_fmt(company_news, 900)}"
    )
    system = SYSTEM.format(today=datetime.now(tz=UTC).strftime("%Y-%m-%d"))
    # When Exa isn't available let the model do a couple of live searches itself.
    web_searches = 0 if exa.configured() else 3
    data = await llm.complete_json(system, prompt, max_tokens=4000, web_searches=web_searches)
    if isinstance(data, dict):
        out.data = {
            "bio": [str(x) for x in data.get("bio") or []],
            "company_summary": str(data.get("company_summary") or ""),
            "recent": [
                {
                    "text": str(x.get("text") or ""),
                    "url": x.get("url") or None,
                    "date": x.get("date") or None,
                }
                for x in data.get("recent") or []
                if isinstance(x, dict)
            ],
            "hooks": [str(x) for x in data.get("hooks") or []],
            "talking_points": [str(x) for x in data.get("talking_points") or []],
            "caveats": str(data.get("caveats") or ""),
        }
    else:
        out.data = {
            "bio": [profile_text[:300]] if profile_text else [],
            "company_summary": homepage[:300],
            "recent": [
                {"text": r.title, "url": r.url, "date": (r.published or "")[:10] or None}
                for r in person_news[:4]
            ],
            "hooks": [],
            "talking_points": [],
            "caveats": (
                "Research synthesis failed — raw material only; rerun this row"
                if llm.configured()
                else "No LLM configured — raw material only"
            ),
        }
    return out
