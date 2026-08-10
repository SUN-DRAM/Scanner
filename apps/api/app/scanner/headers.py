"""The `headers` module — one GET to `http://` (the redirect probe, contract
§10 rule 3 v1.1 amendment), one GET to `https://`, every header in §6.4.
"""

from __future__ import annotations

import re

from app.enums import ModuleName
from app.findings import build_finding
from app.grading import worst_finding
from app.safety import SafeFetchResult, safe_get
from app.scanner import ScanContext, run_module
from app.schemas import Finding, HeaderPresence, HeadersData, HstsData, ModuleResult

LABEL = "Security headers"

_SERVER_VERSION_PATTERN = re.compile(r"\d+\.\d")


def _presence(headers: dict[str, str], name: str) -> HeaderPresence:
    value = headers.get(name.lower())
    return HeaderPresence(present=value is not None, value=value)


def _parse_hsts(value: str | None) -> HstsData:
    if value is None:
        return HstsData(
            present=False, max_age_seconds=None, include_subdomains=False, preload=False
        )
    max_age_match = re.search(r"max-age\s*=\s*(\d+)", value, re.IGNORECASE)
    max_age = int(max_age_match.group(1)) if max_age_match else None
    return HstsData(
        present=True,
        max_age_seconds=max_age,
        include_subdomains="includesubdomains" in value.lower(),
        preload="preload" in value.lower(),
    )


async def _detect(ctx: ScanContext) -> tuple[HeadersData, list[Finding], str]:
    http_result: SafeFetchResult | None = None
    try:
        http_result = await safe_get(
            "http", ctx.hostname, 80, "/", allow_redirect_probe_port_80=True
        )
    except Exception:
        http_result = None

    https_result = await safe_get("https", ctx.hostname, ctx.port, "/")

    headers = {name.lower(): value for name, value in https_result.headers.items()}
    http_to_https_redirect = http_result is not None and http_result.final_url.startswith(
        "https://"
    )
    redirect_chain = (
        http_result.redirect_chain if http_result is not None else https_result.redirect_chain
    )

    hsts = _parse_hsts(headers.get("strict-transport-security"))
    csp = _presence(headers, "content-security-policy")
    xcto = _presence(headers, "x-content-type-options")
    xfo = _presence(headers, "x-frame-options")
    referrer_policy = _presence(headers, "referrer-policy")
    permissions_policy = _presence(headers, "permissions-policy")
    server_header = headers.get("server")

    missing: list[str] = []
    if not hsts.present:
        missing.append("hsts")
    if not csp.present:
        missing.append("content_security_policy")
    if not xcto.present:
        missing.append("x_content_type_options")
    if not xfo.present:
        missing.append("x_frame_options")
    if not referrer_policy.present:
        missing.append("referrer_policy")
    if not permissions_policy.present:
        missing.append("permissions_policy")

    data = HeadersData(
        final_url=https_result.final_url,
        status_code=https_result.status_code,
        redirect_chain=redirect_chain,
        http_to_https_redirect=http_to_https_redirect,
        hsts=hsts,
        content_security_policy=csp,
        x_content_type_options=xcto,
        x_frame_options=xfo,
        referrer_policy=referrer_policy,
        permissions_policy=permissions_policy,
        server_header=server_header,
        missing=missing,
    )

    findings: list[Finding] = []
    base_evidence = {"hostname": ctx.hostname}

    if not hsts.present:
        findings.append(build_finding("HSTS_MISSING", base_evidence))
    elif hsts.max_age_seconds is not None and hsts.max_age_seconds < 15552000:
        findings.append(
            build_finding(
                "HSTS_SHORT_MAX_AGE", {**base_evidence, "max_age_seconds": hsts.max_age_seconds}
            )
        )

    if not http_to_https_redirect:
        findings.append(build_finding("NO_HTTPS_REDIRECT", base_evidence))

    if not csp.present:
        findings.append(build_finding("CSP_MISSING", base_evidence))

    has_frame_ancestors = (
        csp.present and csp.value is not None and "frame-ancestors" in csp.value.lower()
    )
    if not xfo.present and not has_frame_ancestors:
        findings.append(build_finding("XFO_MISSING", base_evidence))

    if not xcto.present:
        findings.append(build_finding("XCTO_MISSING", base_evidence))

    if not referrer_policy.present:
        findings.append(build_finding("REFERRER_POLICY_MISSING", base_evidence))

    if not permissions_policy.present:
        findings.append(build_finding("PERMISSIONS_POLICY_MISSING", base_evidence))

    if server_header and _SERVER_VERSION_PATTERN.search(server_header):
        findings.append(
            build_finding(
                "SERVER_VERSION_DISCLOSED", {**base_evidence, "server_header": server_header}
            )
        )

    top = worst_finding(findings)
    if top is not None:
        summary = top.title + "."
    else:
        summary = "HTTPS redirect and every recommended security header are in place."

    return data, findings, summary


async def run(ctx: ScanContext) -> ModuleResult[HeadersData]:
    return await run_module(module=ModuleName.HEADERS, label=LABEL, ctx=ctx, detect=_detect)
