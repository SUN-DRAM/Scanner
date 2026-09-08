"""The `X-Admin-Token` gate for every `/api/v1/admin/*` JSON route
(contract §7.13).

One shared operator credential — no session, no user, no org. The same
trust model `GET /admin/stats` (§7.5) already uses, but header-based and
producing the standard JSON error envelope (§7.4) rather than `text/plain`.
A missing or wrong token, or an unset `ADMIN_TOKEN`, is `403 FORBIDDEN`.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, Header, Query

from app.config import Settings, get_settings
from app.errors import ApiException, ErrorCode


async def require_admin_token(
    x_admin_token: str | None = Header(default=None),
    # `?token=` is also accepted, for manual curl/browser use — matching the
    # existing `GET /admin/stats` (§7.5). The header is the path the
    # frontend uses (it forwards the operator's `sd_admin` cookie value).
    token: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    configured = settings.admin_token
    presented = x_admin_token or token
    if not configured or not presented or not secrets.compare_digest(presented, configured):
        raise ApiException(
            ErrorCode.FORBIDDEN,
            "Admin access requires a valid token.",
        )
