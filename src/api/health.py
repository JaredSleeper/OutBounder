from fastapi import APIRouter

from src.config import settings
from src.db import pool

router = APIRouter()


@router.get("/healthz")
async def healthz():
    await pool().fetchval("SELECT 1")
    return {"ok": True}


@router.get("/api/status")
async def status():
    return {
        "auth_enabled": settings.auth_enabled,
        "llm": settings.llm_configured,
        "exa": settings.exa_configured,
        "firecrawl": bool(settings.firecrawl_api_key),
        "hunter": bool(settings.hunter_api_key),
        "smtp_verify": settings.smtp_verify_enabled,
    }
