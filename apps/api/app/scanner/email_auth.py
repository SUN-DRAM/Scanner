"""The `email_auth` module — SPF parse with (recursive) lookup counting,
DMARC parse, best-effort DKIM selector probing.
"""

from __future__ import annotations

import asyncio
import re

import dns.asyncresolver

from app.enums import DmarcPolicy, ModuleName, SpfPolicy
from app.findings import build_finding
from app.grading import worst_finding
from app.scanner import ScanContext, run_module
from app.schemas import DkimData, DmarcData, EmailAuthData, Finding, ModuleResult, SpfData

LABEL = "Email authentication"

_LOOKUP_TIMEOUT_SECONDS = 5.0
_SPF_LOOKUP_MECHANISMS = ("include", "a", "mx", "ptr", "exists", "redirect")
_SPF_LOOKUP_LIMIT = 10
_MAX_SPF_RECURSION = 10
_DKIM_SELECTORS_CHECKED = ["default", "google", "selector1", "selector2", "k1", "mail"]

_ALL_QUALIFIER_PATTERN = re.compile(r"(?:^|\s)([+\-~?]?)all(?:\s|$)")
_QUALIFIER_TO_POLICY: dict[str, SpfPolicy] = {
    "-": SpfPolicy.FAIL,
    "~": SpfPolicy.SOFTFAIL,
    "?": SpfPolicy.NEUTRAL,
    "+": SpfPolicy.NONE,
}


async def _fetch_txt_records(resolver: dns.asyncresolver.Resolver, name: str) -> list[str]:
    try:
        answer = await resolver.resolve(name, "TXT")
    except Exception:
        return []
    records = []
    for rdata in answer:
        strings = getattr(rdata, "strings", None)
        text = b"".join(strings).decode("utf-8", errors="ignore") if strings else str(rdata)
        records.append(text)
    return records


async def _fetch_spf_record(resolver: dns.asyncresolver.Resolver, domain: str) -> str | None:
    for text in await _fetch_txt_records(resolver, domain):
        if text.lower().startswith("v=spf1"):
            return text
    return None


def _spf_all_qualifier(record: str) -> str | None:
    match = _ALL_QUALIFIER_PATTERN.search(record)
    if not match:
        return None
    return match.group(1) or "+"


def _spf_policy(record: str | None) -> SpfPolicy:
    if record is None:
        return SpfPolicy.ABSENT
    qualifier = _spf_all_qualifier(record)
    if qualifier is None:
        return SpfPolicy.NONE
    return _QUALIFIER_TO_POLICY[qualifier]


async def _count_spf_lookups(
    resolver: dns.asyncresolver.Resolver,
    domain: str,
    record: str,
    *,
    depth: int = 0,
    visited: set[str] | None = None,
) -> int:
    if visited is None:
        visited = set()
    if domain in visited or depth >= _MAX_SPF_RECURSION:
        return 0
    visited.add(domain)

    count = 0
    for token in record.split():
        for mechanism in _SPF_LOOKUP_MECHANISMS:
            if (
                token == mechanism
                or token.startswith(f"{mechanism}:")
                or token.startswith(f"{mechanism}/")
            ):
                count += 1
                if mechanism in ("include", "redirect") and ":" in token:
                    included_domain = token.split(":", 1)[1]
                    included_record = await _fetch_spf_record(resolver, included_domain)
                    if included_record:
                        count += await _count_spf_lookups(
                            resolver,
                            included_domain,
                            included_record,
                            depth=depth + 1,
                            visited=visited,
                        )
                break
    return count


async def _detect_spf(resolver: dns.asyncresolver.Resolver, hostname: str) -> SpfData:
    record = await _fetch_spf_record(resolver, hostname)
    if record is None:
        return SpfData(
            present=False, record=None, policy=SpfPolicy.ABSENT, lookup_count=0, issues=[]
        )

    lookup_count = await _count_spf_lookups(resolver, hostname, record)
    issues: list[str] = []
    if lookup_count > _SPF_LOOKUP_LIMIT:
        issues.append(
            f"{lookup_count} DNS lookups required, over the limit of {_SPF_LOOKUP_LIMIT}."
        )

    return SpfData(
        present=True,
        record=record,
        policy=_spf_policy(record),
        lookup_count=lookup_count,
        issues=issues,
    )


async def _detect_dmarc(resolver: dns.asyncresolver.Resolver, hostname: str) -> DmarcData:
    records = await _fetch_txt_records(resolver, f"_dmarc.{hostname}")
    record = next((text for text in records if text.lower().startswith("v=dmarc1")), None)
    if record is None:
        return DmarcData(
            present=False, record=None, policy=DmarcPolicy.ABSENT, pct=0, rua_present=False
        )

    policy_match = re.search(r"p=(none|quarantine|reject)", record, re.IGNORECASE)
    policy = DmarcPolicy(policy_match.group(1).lower()) if policy_match else DmarcPolicy.NONE
    pct_match = re.search(r"pct=(\d{1,3})", record)
    pct = int(pct_match.group(1)) if pct_match else 100
    rua_present = "rua=" in record.lower()

    return DmarcData(present=True, record=record, policy=policy, pct=pct, rua_present=rua_present)


async def _detect_dkim(resolver: dns.asyncresolver.Resolver, hostname: str) -> DkimData:
    async def _check(selector: str) -> str | None:
        name = f"{selector}._domainkey.{hostname}"
        for text in await _fetch_txt_records(resolver, name):
            if "v=dkim1" in text.lower() or "p=" in text.lower():
                return selector
        return None

    results = await asyncio.gather(*(_check(s) for s in _DKIM_SELECTORS_CHECKED))
    found = [selector for selector in results if selector is not None]
    return DkimData(selectors_checked=list(_DKIM_SELECTORS_CHECKED), selectors_found=found)


async def _detect(ctx: ScanContext) -> tuple[EmailAuthData, list[Finding], str]:
    resolver = dns.asyncresolver.Resolver()
    resolver.timeout = _LOOKUP_TIMEOUT_SECONDS
    resolver.lifetime = _LOOKUP_TIMEOUT_SECONDS

    spf, dmarc, dkim = await asyncio.gather(
        _detect_spf(resolver, ctx.hostname),
        _detect_dmarc(resolver, ctx.hostname),
        _detect_dkim(resolver, ctx.hostname),
    )
    data = EmailAuthData(spf=spf, dmarc=dmarc, dkim=dkim)

    findings: list[Finding] = []
    base_evidence = {"hostname": ctx.hostname}

    if not spf.present:
        findings.append(build_finding("SPF_MISSING", base_evidence))
    else:
        qualifier = _spf_all_qualifier(spf.record or "")
        if qualifier in ("+", "?"):
            findings.append(
                build_finding("SPF_WEAK_POLICY", {**base_evidence, "policy": spf.policy.value})
            )
        if spf.lookup_count > _SPF_LOOKUP_LIMIT:
            findings.append(
                build_finding(
                    "SPF_TOO_MANY_LOOKUPS", {**base_evidence, "lookup_count": spf.lookup_count}
                )
            )

    if not dmarc.present:
        findings.append(build_finding("DMARC_MISSING", base_evidence))
    elif dmarc.policy == DmarcPolicy.NONE:
        findings.append(build_finding("DMARC_POLICY_NONE", base_evidence))

    if not dkim.selectors_found:
        findings.append(build_finding("DKIM_NOT_FOUND", base_evidence))

    top = worst_finding(findings)
    if top is not None:
        summary = top.title + "."
    else:
        summary = "SPF, DMARC and DKIM all look correctly configured."

    return data, findings, summary


async def run(ctx: ScanContext) -> ModuleResult[EmailAuthData]:
    return await run_module(module=ModuleName.EMAIL_AUTH, label=LABEL, ctx=ctx, detect=_detect)
