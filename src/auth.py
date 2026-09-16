from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from src.config import settings


async def require_user(authorization: str = Header(default="")) -> None:
    """Shared-password gate for the API. Fails closed unless ALLOW_NO_AUTH is set."""
    if not settings.auth_enabled:
        if settings.allow_no_auth:
            return
        raise HTTPException(
            status_code=503,
            detail=(
                "Authentication not configured: set APP_PASSWORD "
                "(or ALLOW_NO_AUTH=true for local dev)"
            ),
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(token, settings.app_password):
        raise HTTPException(status_code=401, detail="Password required")
