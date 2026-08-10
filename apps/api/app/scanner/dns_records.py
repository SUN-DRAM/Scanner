"""The `dns` module — `dnspython` for A/AAAA/CNAME/NS/MX/CAA/DNSSEC, WHOIS
for registrar and domain expiry.

WHOIS is unreliable by nature (inconsistent formats across registrars, rate
limiting, unsupported TLDs). Contract §7's rule 7 applies hardest here: on
any doubt, every WHOIS-derived field is `None` and no `DOMAIN_EXPIRING_*`
finding is ever emitted from an uncertain lookup — a wrong expiry date is
worse than no date.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import dns.asyncresolver
import dns.resolver
import whois as whois_lib

from app.enums import ModuleName
from app.findings import build_finding
from app.grading import worst_finding
from app.scanner import ScanContext, run_module
from app.schemas import DnsData, Finding, ModuleResult, MxRecord

LABEL = "DNS"

_LOOKUP_TIMEOUT_SECONDS = 5.0


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


async def _lookup(resolver: dns.asyncresolver.Resolver, name: str, rdtype: str) -> list[str]:
    try:
        answer = await resolver.resolve(name, rdtype)
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
        return []
    except Exception:
        # A genuine lookup failure (timeout, SERVFAIL). The schema has no
        # "unknown" state for these fields (contract §6.4 shows them as
        # plain lists, never null) — an empty list is the closest honest
        # answer the type allows.
        return []
    return [str(record) for record in answer]


async def _lookup_mx(resolver: dns.asyncresolver.Resolver, hostname: str) -> list[MxRecord]:
    try:
        answer = await resolver.resolve(hostname, "MX")
    except Exception:
        return []
    records = []
    for record in answer:
        records.append(MxRecord(priority=int(record.preference), host=str(record.exchange)))
    return sorted(records, key=lambda r: r.priority)


async def _lookup_cname(resolver: dns.asyncresolver.Resolver, hostname: str) -> str | None:
    try:
        answer = await resolver.resolve(hostname, "CNAME")
    except Exception:
        return None
    return str(answer[0].target) if len(answer) > 0 else None


async def _check_dnssec(resolver: dns.asyncresolver.Resolver, hostname: str) -> bool:
    records = await _lookup(resolver, hostname, "DNSKEY")
    return len(records) > 0


def _normalize_whois_date(value: Any) -> datetime | None:
    """WHOIS parsers sometimes return a list when the raw record has more
    than one date-like line. Only trust it if every parsed value agrees on
    the calendar date — a genuine disagreement is exactly the kind of
    uncertainty rule 7 says to return null for, not guess at."""
    if isinstance(value, list):
        parsed = [v for v in value if isinstance(v, datetime)]
        if not parsed:
            return None
        if len({v.date() for v in parsed}) > 1:
            return None
        value = parsed[0]
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _lookup_whois_sync(hostname: str) -> Any:
    return whois_lib.whois(hostname)


async def _lookup_whois(hostname: str) -> tuple[str | None, datetime | None, datetime | None]:
    try:
        record = await asyncio.wait_for(
            asyncio.to_thread(_lookup_whois_sync, hostname), timeout=_LOOKUP_TIMEOUT_SECONDS
        )
    except Exception:
        return None, None, None

    registrar = getattr(record, "registrar", None)
    registrar = registrar if isinstance(registrar, str) and registrar.strip() else None

    created = _normalize_whois_date(getattr(record, "creation_date", None))
    expires = _normalize_whois_date(getattr(record, "expiration_date", None))
    return registrar, created, expires


async def _detect(ctx: ScanContext) -> tuple[DnsData, list[Finding], str]:
    resolver = dns.asyncresolver.Resolver()
    resolver.timeout = _LOOKUP_TIMEOUT_SECONDS
    resolver.lifetime = _LOOKUP_TIMEOUT_SECONDS

    # Two gathers, not one seven-way gather: mypy's typeshed overloads for
    # asyncio.gather only preserve each awaitable's distinct return type up
    # to a handful of positional arguments — beyond that it collapses to a
    # union of all of them, which broke every field below with a type error.
    a_records, aaaa_records, cname, nameservers = await asyncio.gather(
        _lookup(resolver, ctx.hostname, "A"),
        _lookup(resolver, ctx.hostname, "AAAA"),
        _lookup_cname(resolver, ctx.hostname),
        _lookup(resolver, ctx.hostname, "NS"),
    )
    mx_records, caa_records, dnssec_enabled = await asyncio.gather(
        _lookup_mx(resolver, ctx.hostname),
        _lookup(resolver, ctx.hostname, "CAA"),
        _check_dnssec(resolver, ctx.hostname),
    )
    registrar, domain_created_at, domain_expires_at = await _lookup_whois(ctx.hostname)

    days_until_domain_expiry = (
        (domain_expires_at - ctx.now).days if domain_expires_at is not None else None
    )

    data = DnsData(
        a_records=a_records,
        aaaa_records=aaaa_records,
        cname=cname,
        nameservers=nameservers,
        mx_records=mx_records,
        caa_records=caa_records,
        caa_present=len(caa_records) > 0,
        dnssec_enabled=dnssec_enabled,
        registrar=registrar,
        domain_created_at=domain_created_at,
        domain_expires_at=domain_expires_at,
        days_until_domain_expiry=days_until_domain_expiry,
    )

    findings: list[Finding] = []
    base_evidence = {"hostname": ctx.hostname}

    if not data.caa_present:
        findings.append(build_finding("DNS_NO_CAA", base_evidence))

    if not data.dnssec_enabled:
        findings.append(build_finding("DNS_NO_DNSSEC", base_evidence))

    if data.days_until_domain_expiry is not None and data.domain_expires_at is not None:
        expiry_evidence = {
            **base_evidence,
            "domain_expires_at": _iso(data.domain_expires_at),
            "days_until_domain_expiry": data.days_until_domain_expiry,
        }
        if data.days_until_domain_expiry <= 14:
            findings.append(build_finding("DOMAIN_EXPIRING_CRITICAL", expiry_evidence))
        elif data.days_until_domain_expiry <= 45:
            findings.append(
                build_finding(
                    "DOMAIN_EXPIRING_SOON",
                    {**expiry_evidence, "registrar": data.registrar or "an unknown registrar"},
                )
            )

    if len(data.nameservers) == 1:
        findings.append(build_finding("DNS_SINGLE_NAMESERVER", base_evidence))

    top = worst_finding(findings)
    if top is not None:
        summary = top.title + "."
    else:
        summary = f"{len(data.nameservers)} nameservers, CAA and DNSSEC both in place."

    return data, findings, summary


async def run(ctx: ScanContext) -> ModuleResult[DnsData]:
    return await run_module(module=ModuleName.DNS, label=LABEL, ctx=ctx, detect=_detect)
