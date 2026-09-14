"""The `chain` module — completeness, order, trusted root, intermediate
expiry. Reuses the same pinned handshake primitive as certificate.py for the
raw chain, plus a second, normally-verifying handshake (stdlib `ssl`,
default trust store) purely to answer "does this validate at all" — that's
the one thing a from-scratch chain walk can't answer without re-implementing
a trust store.
"""

from __future__ import annotations

import asyncio
import contextlib
import ssl
from collections.abc import Sequence
from datetime import datetime

from cryptography import x509
from cryptography.x509.oid import NameOID

from app.enums import ModuleName
from app.findings import build_finding
from app.grading import module_summary
from app.safety import CONNECTION_CLOSE_TIMEOUT_SECONDS, open_pinned_connection
from app.scanner import HandshakeTask, ScanContext, fetch_handshake, run_module
from app.schemas import ChainCertificate, ChainData, Finding, ModuleResult

LABEL = "Chain"
INTERMEDIATE_EXPIRY_WARNING_DAYS = 30


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _common_name(name: x509.Name) -> str:
    attrs = name.get_attributes_for_oid(NameOID.COMMON_NAME)
    return str(attrs[0].value) if attrs else ""


def _is_continuous(chain: Sequence[x509.Certificate]) -> bool:
    if len(chain) < 2:
        return True
    return all(chain[i].issuer == chain[i + 1].subject for i in range(len(chain) - 1))


async def _validates_against_trust_store(ip: str, port: int, hostname: str) -> bool:
    ctx = ssl.create_default_context()
    try:
        _reader, writer = await open_pinned_connection(
            ip, port, server_hostname=hostname, ssl_context=ctx
        )
    except ssl.SSLCertVerificationError:
        return False
    writer.close()
    # docs/fix_connection_footprint.md Step 1: confirmed directly, not
    # guessed — a peer that never sends a close_notify/FIN back leaves
    # wait_closed() hanging indefinitely, silently consuming the rest of
    # this module's PER_MODULE_TIMEOUT_SECONDS budget with nothing else
    # running. This is the one place that can happen, so it gets its own
    # short, independent cap.
    with contextlib.suppress(Exception):
        await asyncio.wait_for(writer.wait_closed(), timeout=CONNECTION_CLOSE_TIMEOUT_SECONDS)
    return True


async def _detect(
    ctx: ScanContext, handshake_task: HandshakeTask | None = None
) -> tuple[ChainData, list[Finding], str]:
    # docs/fix_connection_footprint.md Step 2.1: certificate.py fetches this
    # exact same handshake independently — two connections for data that
    # arrives together in one. orchestrator.py starts one shared fetch and
    # passes it to both; `handshake_task is None` (direct/standalone calls,
    # e.g. every test in this file) falls back to fetching it here, same as
    # before this change.
    if handshake_task is None:
        target, handshake = await fetch_handshake(ctx)
    else:
        target, handshake = await handshake_task
    chain = handshake.chain
    trusted = await _validates_against_trust_store(target.ip, ctx.port, ctx.hostname)

    order_valid = _is_continuous(chain)
    is_complete = len(chain) >= 2 or chain[0].subject == chain[0].issuer
    trusted_root = _common_name(chain[-1].subject) if trusted and chain else None

    certificates: list[ChainCertificate] = []
    for position, cert in enumerate(chain):
        is_last = position == len(chain) - 1
        is_self_signed = cert.subject == cert.issuer
        if position == 0:
            role = "leaf"
        elif is_last and is_self_signed:
            role = "root"
        else:
            role = "intermediate"
        certificates.append(
            ChainCertificate(
                position=position,
                role=role,  # type: ignore[arg-type]
                subject=_common_name(cert.subject) or cert.subject.rfc4514_string(),
                issuer=_common_name(cert.issuer) or cert.issuer.rfc4514_string(),
                not_after=cert.not_valid_after_utc,
            )
        )

    data = ChainData(
        chain_length=len(chain),
        is_complete=is_complete,
        order_valid=order_valid,
        trusted_root=trusted_root,
        certificates=certificates,
    )

    findings: list[Finding] = []
    base_evidence = {"hostname": ctx.hostname}

    if not data.is_complete:
        findings.append(build_finding("CHAIN_INCOMPLETE", base_evidence))

    if not data.order_valid:
        findings.append(build_finding("CHAIN_OUT_OF_ORDER", base_evidence))

    if not trusted:
        findings.append(build_finding("CHAIN_UNTRUSTED_ROOT", base_evidence))

    for cert, entry in zip(chain[1:], certificates[1:], strict=True):
        days_left = (cert.not_valid_after_utc - ctx.now).days
        if days_left <= INTERMEDIATE_EXPIRY_WARNING_DAYS:
            findings.append(
                build_finding(
                    "CHAIN_INTERMEDIATE_EXPIRING",
                    {
                        **base_evidence,
                        "intermediate_subject": entry.subject,
                        "not_after": _iso(cert.not_valid_after_utc),
                        "days_until_expiry": days_left,
                    },
                )
            )

    summary = module_summary(
        findings,
        f"Complete, correctly ordered chain of {data.chain_length} "
        "certificates to a trusted root.",
    )

    return data, findings, summary


async def run(
    ctx: ScanContext, handshake_task: HandshakeTask | None = None
) -> ModuleResult[ChainData]:
    async def _bound_detect(context: ScanContext) -> tuple[ChainData, list[Finding], str]:
        return await _detect(context, handshake_task)

    return await run_module(module=ModuleName.CHAIN, label=LABEL, ctx=ctx, detect=_bound_detect)
