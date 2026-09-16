from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import src.auth as auth
import src.main as main


@pytest.mark.asyncio
async def test_require_user_without_password_fails_closed(monkeypatch):
    monkeypatch.setattr(auth.settings, "app_password", "")
    monkeypatch.setattr(auth.settings, "allow_no_auth", False)

    with pytest.raises(HTTPException) as exc_info:
        await auth.require_user()

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_require_user_allows_explicit_no_auth(monkeypatch):
    monkeypatch.setattr(auth.settings, "app_password", "")
    monkeypatch.setattr(auth.settings, "allow_no_auth", True)

    assert await auth.require_user() is None


@pytest.mark.asyncio
async def test_require_user_accepts_matching_password(monkeypatch):
    monkeypatch.setattr(auth.settings, "app_password", "s3cret")
    monkeypatch.setattr(auth.settings, "allow_no_auth", False)

    assert await auth.require_user("Bearer s3cret") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["", "Bearer wrong"])
async def test_require_user_rejects_missing_or_wrong_password(monkeypatch, header):
    monkeypatch.setattr(auth.settings, "app_password", "s3cret")
    monkeypatch.setattr(auth.settings, "allow_no_auth", False)

    with pytest.raises(HTTPException) as exc_info:
        await auth.require_user(header)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_lifespan_refuses_to_start_without_password(monkeypatch):
    async def init_db_noop():
        pass

    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(auth_enabled=False, allow_no_auth=False),
    )
    monkeypatch.setattr(main, "init_db", init_db_noop)
    monkeypatch.setattr(main.worker, "start", lambda: None)

    with pytest.raises(RuntimeError, match="APP_PASSWORD is not set"):
        async with main.lifespan(None):
            pass
