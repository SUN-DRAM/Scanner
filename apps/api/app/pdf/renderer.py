"""Renders a `Scan` to PDF bytes (contract §7.14, v2.9).

Synchronous and CPU-bound (WeasyPrint has no async API) — `render_scan_pdf`
runs the actual render in a thread pool behind a semaphore capped at
`PDF_MAX_CONCURRENT`, so the export path can never starve the scanner, the
same priority rule the scheduler already follows (§7.9).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.pdf.fonts import PDF_DIR
from app.pdf.template import render_html
from app.schemas import Scan

if TYPE_CHECKING:
    from weasyprint.text.fonts import FontConfiguration

# Relative `url(...)`s in styles.py/template.py (fonts/*.woff, assets/logo.svg)
# resolve against this — this package's own directory — regardless of the
# process's current working directory or the container it runs in.
_BASE_URL = PDF_DIR.as_uri() + "/"

_render_semaphore: asyncio.Semaphore | None = None
_font_config: FontConfiguration | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _render_semaphore
    if _render_semaphore is None:
        _render_semaphore = asyncio.Semaphore(get_settings().pdf_max_concurrent)
    return _render_semaphore


def _get_font_config() -> FontConfiguration:
    # Imported lazily so importing this module (e.g. for type-checking, or
    # from code paths that never render a PDF) never requires WeasyPrint's
    # native Pango/HarfBuzz libraries to be loadable.
    from weasyprint.text.fonts import FontConfiguration

    global _font_config
    if _font_config is None:
        _font_config = FontConfiguration()
    return _font_config


def render_scan_pdf_bytes(scan: Scan) -> bytes:
    """The synchronous render — call via `render_scan_pdf` from async code."""
    from weasyprint import HTML

    html_document = render_html(scan)
    pdf_bytes: bytes = HTML(string=html_document, base_url=_BASE_URL).write_pdf(
        font_config=_get_font_config()
    )
    return pdf_bytes


async def render_scan_pdf(scan: Scan) -> bytes:
    async with _get_semaphore():
        return await run_in_threadpool(render_scan_pdf_bytes, scan)
