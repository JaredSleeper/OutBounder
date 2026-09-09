from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from src.config import settings


async def require_user(authorization: str = Header(default="")) -> None:
    """Shared-password gate for the API. No-op when APP_PASSWORD is unset."""
    if not settings.auth_enabled:
        return
    token = authorization.removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(token, settings.app_password):
        raise HTTPException(status_code=401, detail="Password required")
