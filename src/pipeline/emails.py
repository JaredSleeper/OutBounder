"""Email discovery: web evidence + company pattern inference + permutations + SMTP checks."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from src.providers import exa, hunter, mailcheck

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# pattern name -> formatter(first, last, f, l)
PATTERNS: dict[str, str] = {
    "first.last": "{first}.{last}",
    "first": "{first}",
    "flast": "{f}{last}",
    "firstlast": "{first}{last}",
    "first_last": "{first}_{last}",
    "first.l": "{first}.{l}",
    "last.first": "{last}.{first}",
    "lastf": "{last}{f}",
    "f.last": "{f}.{last}",
    "last": "{last}",
    "firstl": "{first}{l}",
    "last.f": "{last}.{f}",
}
# Prior likelihood when nothing else is known (rough B2B base rates).
PRIOR: dict[str, float] = {
    "first.last": 0.42,
    "first": 0.22,
    "flast": 0.15,
    "firstlast": 0.08,
    "first_last": 0.03,
    "first.l": 0.03,
    "last.first": 0.02,
    "lastf": 0.02,
    "f.last": 0.01,
    "last": 0.01,
    "firstl": 0.01,
    "last.f": 0.01,
}

_GENERIC_LOCAL = {
    "info",
    "contact",
    "hello",
    "support",
    "sales",
    "press",
    "media",
    "careers",
    "jobs",
    "admin",
    "noreply",
    "no-reply",
    "team",
    "help",
    "privacy",
    "legal",
    "security",
    "marketing",
    "hr",
    "office",
    "webmaster",
    "billing",
}


@dataclass
class EmailCandidate:
    email: str
    confidence: float
    source: str  # found_on_web | hunter | pattern:<name>
    evidence: list[str] = field(default_factory=list)
    verification: str = "unknown"  # valid | invalid | unknown | catch_all

    def to_dict(self) -> dict:
        return {
            "email": self.email,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "evidence": self.evidence[:5],
            "verification": self.verification,
        }


@dataclass
class EmailFinding:
    candidates: list[EmailCandidate]
    best: str | None
    pattern: str | None
    domain_checks: dict
    sources: list[dict] = field(default_factory=list)


def _ascii(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", s.lower())


def split_name(full: str) -> tuple[str, str]:
    """('Mary-Anne O'Neil Jr.') -> ('maryanne', 'oneil'); drops honorifics/suffixes."""
    parts = [p for p in re.split(r"\s+", full.strip()) if p]
    drop = {"mr", "mrs", "ms", "dr", "prof", "jr", "sr", "ii", "iii", "iv", "phd", "mba", "md"}
    parts = [p for p in parts if _ascii(p) not in drop and _ascii(p)]
    # drop parenthesised nicknames / quoted names
    parts = [p for p in parts if not (p.startswith("(") or p.startswith('"'))]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return _ascii(parts[0]), ""
    return _ascii(parts[0]), _ascii(parts[-1])


def permutations(first: str, last: str, domain: str) -> dict[str, str]:
    """pattern -> address."""
    if not first or not domain:
        return {}
    f, l = first[:1], last[:1]  # noqa: E741
    out: dict[str, str] = {}
    for pat, tpl in PATTERNS.items():
        if not last and ("last" in tpl or "{l}" in tpl):
            continue
        local = tpl.format(first=first, last=last, f=f, l=l)
        if local:
            out[pat] = f"{local}@{domain}"
    return out


def infer_pattern(sample: str, first: str, last: str) -> str | None:
    """Given someone else's address at the domain and their name, work out the pattern."""
    local = sample.split("@")[0].lower()
    for pat, tpl in PATTERNS.items():
        if not first:
            break
        if not last and ("last" in tpl or "{l}" in tpl):
            continue
        if tpl.format(first=first, last=last, f=first[:1], l=last[:1]) == local:
            return pat
    return None


def extract_emails(text: str, domain: str) -> list[str]:
    found = set()
    for m in EMAIL_RE.findall(text or ""):
        e = m.lower().strip(".")
        if e.endswith("@" + domain) and e.split("@")[0] not in _GENERIC_LOCAL:
            found.add(e)
    return sorted(found)


def _name_in_local(local: str, first: str, last: str) -> bool:
    local = re.sub(r"[^a-z]", "", local)
    if last and len(last) >= 3 and last in local:
        return True
    return bool(first and len(first) >= 3 and first in local)


async def _web_evidence(
    full_name: str, first: str, last: str, domain: str
) -> tuple[list[EmailCandidate], str | None, list[dict], list[str]]:
    """Search the web for the person's address and for colleagues' addresses (pattern)."""
    cands: list[EmailCandidate] = []
    sources: list[dict] = []
    pattern_votes: dict[str, int] = {}
    if not exa.configured() or not domain:
        return cands, None, sources, []

    queries = [
        (f'"{full_name}" "@{domain}" email', 6),
        (f'"@{domain}" email contact', 8),
    ]
    seen_urls: set[str] = set()
    colleague_hits: list[str] = []
    for q, n in queries:
        results = await exa.search(q, num_results=n, search_type="keyword", max_chars=4000)
        for r in results:
            emails = extract_emails(r.text, domain)
            if not emails:
                continue
            if r.url not in seen_urls:
                seen_urls.add(r.url)
                sources.append({"title": r.title, "url": r.url})
            for e in emails:
                local = e.split("@")[0]
                if _name_in_local(local, first, last):
                    existing = next((c for c in cands if c.email == e), None)
                    if existing:
                        existing.evidence.append(r.url)
                        existing.confidence = min(0.97, existing.confidence + 0.03)
                    else:
                        cands.append(
                            EmailCandidate(
                                email=e, confidence=0.9, source="found_on_web", evidence=[r.url]
                            )
                        )
                else:
                    colleague_hits.append(e)
                    # guess the colleague's name from nearby text is unreliable; instead
                    # vote on the structural shape of the local part
                    shape = _shape(local)
                    if shape:
                        pattern_votes[shape] = pattern_votes.get(shape, 0) + 1
    inferred = max(pattern_votes, key=pattern_votes.get) if pattern_votes else None
    return cands, inferred, sources, colleague_hits


def _shape(local: str) -> str | None:
    """Structural guess for a local part when we don't know the owner's name."""
    if "." in local:
        a, b = local.split(".", 1)
        if len(a) == 1:
            return "f.last"
        if len(b) == 1:
            return "first.l"
        return "first.last"
    if "_" in local:
        return "first_last"
    if len(local) <= 6:
        return "first"
    return None  # firstlast vs flast is ambiguous without the name


async def find_emails(full_name: str, domain: str | None) -> EmailFinding:
    first, last = split_name(full_name)
    if not domain or not first:
        return EmailFinding(
            candidates=[],
            best=None,
            pattern=None,
            domain_checks={"note": "No company domain or unusable name — nothing to guess from"},
        )
    domain = domain.lower()

    web_cands, inferred, sources, _ = await _web_evidence(full_name, first, last, domain)
    checks = await mailcheck.check_domain(domain)

    cands: dict[str, EmailCandidate] = {c.email: c for c in web_cands}

    hunter_hit = await hunter.find_email(first, last, domain)
    if hunter_hit:
        e = hunter_hit["email"].lower()
        score = (hunter_hit.get("score") or 50) / 100
        c = cands.get(e) or EmailCandidate(email=e, confidence=score, source="hunter")
        c.confidence = max(c.confidence, score)
        c.evidence.append(f"hunter score {hunter_hit.get('score')}")
        cands[e] = c
        inferred = infer_pattern(e, first, last) or inferred

    perms = permutations(first, last, domain)
    for pat, addr in perms.items():
        prior = PRIOR.get(pat, 0.01)
        conf = prior
        if inferred == pat:
            conf = max(conf, 0.7)
        elif inferred:
            conf *= 0.5
        if addr in cands:
            cands[addr].evidence.append(f"matches pattern {pat}")
            cands[addr].confidence = min(0.98, cands[addr].confidence + 0.02)
            if inferred is None:
                inferred = pat
        else:
            cands[addr] = EmailCandidate(email=addr, confidence=conf, source=f"pattern:{pat}")

    ordered = sorted(cands.values(), key=lambda c: -c.confidence)

    # SMTP verification on the most plausible handful
    to_check = [c.email for c in ordered[:6]]
    statuses = await mailcheck.verify_addresses(checks, to_check)
    for c in ordered:
        c.verification = statuses.get(c.email, "unknown")
        if c.verification == "valid":
            c.confidence = max(c.confidence, 0.95)
        elif c.verification == "invalid":
            c.confidence = min(c.confidence, 0.05)
        elif c.verification == "catch_all":
            c.confidence = min(c.confidence, 0.85)
    if not checks.mx_hosts:
        for c in ordered:
            c.confidence = min(c.confidence, 0.05)

    ordered.sort(key=lambda c: -c.confidence)
    best = ordered[0].email if ordered and ordered[0].confidence >= 0.15 else None
    if best is None and ordered:
        best = ordered[0].email
    if inferred is None and best:
        inferred = infer_pattern(best, first, last)
    return EmailFinding(
        candidates=ordered[:8],
        best=best,
        pattern=inferred,
        domain_checks=checks.to_dict(),
        sources=sources,
    )
