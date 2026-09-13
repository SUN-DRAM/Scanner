"""PDF report export (contract §7.14, v2.9).

An export layer over an already-completed `Scan` (§6.1) — every module here
reads `scans.result`, renders it, and caches the bytes. Nothing here re-scans,
re-grades, or invents a value the stored `Scan` doesn't already have.
"""
