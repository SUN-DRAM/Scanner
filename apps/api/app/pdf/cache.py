"""Redis cache for rendered PDF bytes (contract §7.14, v2.9).

A completed scan is immutable, so its rendered PDF is too — cached by
`scan_id`, TTL `PDF_CACHE_TTL_SECONDS`. A shared scan link posted in a
WhatsApp/Slack group means many people hitting download on the same
`scan_id`; this is what keeps that from re-rendering on every request.
"""

from __future__ import annotations

from typing import cast

from redis.asyncio import Redis

# A render this large is almost certainly pathological (a runaway findings
# list, a corrupt template) rather than a legitimately huge report — skip
# caching it rather than filling Redis with an outlier.
MAX_CACHEABLE_BYTES = 10 * 1024 * 1024


def _cache_key(scan_id: str) -> str:
    return f"pdf_report:{scan_id}"


async def get_cached_pdf(redis: Redis, scan_id: str) -> bytes | None:
    return cast("bytes | None", await redis.get(_cache_key(scan_id)))


async def set_cached_pdf(redis: Redis, scan_id: str, pdf_bytes: bytes, ttl_seconds: int) -> None:
    if len(pdf_bytes) > MAX_CACHEABLE_BYTES:
        return
    await redis.set(_cache_key(scan_id), pdf_bytes, ex=ttl_seconds)
