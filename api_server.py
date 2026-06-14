"""
api_server.py — War Machine v2 FastAPI (Railway)
──────────────────────────────────────────────────────────────────────────────
ForgeGuard admin dispatches POST /scrape via forgeguard-ai /api/admin/war-machine.
Auth: x-internal-scan-token or Authorization: Bearer (INTERNAL_SCAN_TOKEN).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from config import MAX_LEADS_PER_RUN, INTERNAL_SCAN_TOKEN
from db import sync_war_machine_stats
from scraper import run_scraper

logger = logging.getLogger("war-machine.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")

app = FastAPI(title="War Machine API", version="2.0.0")

SOURCE_MAP: dict[str, str] = {
    "producthunt_ai": "producthunt",
    "producthunt": "producthunt",
    "ph": "producthunt",
    "yc": "yc",
    "all": "all",
}

_scrape_lock = asyncio.Lock()
_scrape_running = False


class ScrapeRequest(BaseModel):
    hours: int = Field(default=24, ge=1, le=168)
    source: str = "producthunt_ai"
    max: Optional[int] = Field(default=None, ge=1, le=500)


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    lower = authorization.strip()
    if lower.lower().startswith("bearer "):
        return lower[7:].strip()
    return None


def _verify_internal_token(
    x_internal_scan_token: Optional[str],
    authorization: Optional[str],
) -> None:
    expected = (INTERNAL_SCAN_TOKEN or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="INTERNAL_SCAN_TOKEN not configured")

    provided = (x_internal_scan_token or _extract_bearer(authorization) or "").strip()
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


async def _run_scrape_job(source: str, max_leads: int, hours: int) -> None:
    global _scrape_running
    async with _scrape_lock:
        _scrape_running = True
        try:
            logger.info("Scrape started source=%s max=%s hours=%s", source, max_leads, hours)
            count = await run_scraper(source=source, max_leads=max_leads)
            sync_war_machine_stats()
            logger.info("Scrape finished — %s leads upserted", count)
        except Exception:
            logger.exception("Scrape job failed")
        finally:
            _scrape_running = False


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "war-machine",
        "status": "healthy",
        "scrape_running": _scrape_running,
    }


@app.post("/scrape", status_code=202)
async def scrape(
    body: ScrapeRequest,
    x_internal_scan_token: Optional[str] = Header(None, alias="x-internal-scan-token"),
    authorization: Optional[str] = Header(None),
) -> dict[str, Any]:
    _verify_internal_token(x_internal_scan_token, authorization)

    mapped_source = SOURCE_MAP.get(body.source.strip().lower(), "producthunt")
    max_leads = body.max if body.max is not None else MAX_LEADS_PER_RUN

    if _scrape_running:
        raise HTTPException(status_code=409, detail="Scrape already in progress")

    asyncio.create_task(_run_scrape_job(mapped_source, max_leads, body.hours))

    return {
        "ok": True,
        "status": "accepted",
        "source": mapped_source,
        "hours": body.hours,
        "max": max_leads,
    }
