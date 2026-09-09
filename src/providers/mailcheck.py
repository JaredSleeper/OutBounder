"""Deliverability signals for a domain / address: MX lookup, SMTP RCPT probe, catch-all.

SMTP probing needs outbound port 25, which many hosts block; results degrade to
"unknown" rather than failing the pipeline.
"""

from __future__ import annotations

import asyncio
import secrets
import smtplib
from dataclasses import dataclass, field

import dns.asyncresolver
import dns.exception
import structlog

from src.config import settings

logger = structlog.get_logger("mailcheck")


@dataclass
class DomainChecks:
    mx_hosts: list[str] = field(default_factory=list)
    smtp_reachable: bool | None = None  # None = not attempted / blocked
    catch_all: bool | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "mx_hosts": self.mx_hosts,
            "smtp_reachable": self.smtp_reachable,
            "catch_all": self.catch_all,
            "note": self.note,
        }


async def mx_hosts(domain: str) -> list[str]:
    try:
        answers = await dns.asyncresolver.resolve(domain, "MX", lifetime=6.0)
    except (dns.exception.DNSException, OSError):
        return []
    ranked = sorted(answers, key=lambda r: r.preference)
    return [str(r.exchange).rstrip(".") for r in ranked]


def _rcpt_probe_sync(mx: str, address: str, timeout: float) -> bool | None:
    """True = accepted, False = rejected (5xx), None = couldn't tell."""
    try:
        with smtplib.SMTP(timeout=timeout) as smtp:
            smtp.connect(mx, 25)
            smtp.helo("mail.outbounder.app")
            smtp.mail("probe@outbounder.app")
            code, _ = smtp.rcpt(address)
    except (TimeoutError, smtplib.SMTPException, OSError):
        return None
    if 200 <= code < 300:
        return True
    if 500 <= code < 600:
        return False
    return None


async def rcpt_probe(mx: str, address: str) -> bool | None:
    return await asyncio.to_thread(_rcpt_probe_sync, mx, address, settings.smtp_timeout_seconds)


async def check_domain(domain: str) -> DomainChecks:
    checks = DomainChecks()
    checks.mx_hosts = await mx_hosts(domain)
    if not checks.mx_hosts:
        checks.note = "No MX records — domain does not accept mail"
        return checks
    if not settings.smtp_verify_enabled:
        checks.note = "SMTP probing disabled"
        return checks
    bogus = f"zq{secrets.token_hex(6)}@{domain}"
    result = await rcpt_probe(checks.mx_hosts[0], bogus)
    if result is None:
        checks.smtp_reachable = False
        checks.note = "SMTP unreachable (port 25 blocked or greylisted); pattern-only confidence"
        return checks
    checks.smtp_reachable = True
    checks.catch_all = result is True
    checks.note = (
        "Catch-all domain: SMTP accepts every address, cannot verify individual mailboxes"
        if checks.catch_all
        else "SMTP verification available"
    )
    return checks


async def verify_addresses(domain_checks: DomainChecks, addresses: list[str]) -> dict[str, str]:
    """Map address -> 'valid' | 'invalid' | 'unknown' | 'catch_all'."""
    out: dict[str, str] = {}
    if not domain_checks.mx_hosts:
        return dict.fromkeys(addresses, "invalid")
    if not domain_checks.smtp_reachable:
        return dict.fromkeys(addresses, "unknown")
    if domain_checks.catch_all:
        return dict.fromkeys(addresses, "catch_all")
    mx = domain_checks.mx_hosts[0]
    for addr in addresses:
        res = await rcpt_probe(mx, addr)
        out[addr] = "valid" if res is True else "invalid" if res is False else "unknown"
        if res is True:
            break  # first accepted address is enough; leave the rest unknown
    for addr in addresses:
        out.setdefault(addr, "unknown")
    return out
