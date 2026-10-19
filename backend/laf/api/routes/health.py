"""GET /health - open startup probe (no token required)."""

from __future__ import annotations

import logging
import sqlite3
import time

from fastapi import APIRouter, Request

from laf import __version__
from laf.api.state import AppState

router = APIRouter()
logger = logging.getLogger("laf.health")


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    state: AppState = request.app.state.laf

    db_ok = True
    journal_mode = "unknown"
    try:
        row = state.conn.execute("PRAGMA journal_mode").fetchone()
        journal_mode = str(row[0]) if row else "unknown"
        state.conn.execute("SELECT 1")
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        db_ok = False
        logger.error("health probe db failure", extra={"error": str(exc)})

    return {
        "status": "ok",
        "version": __version__,
        "db": {"ok": db_ok, "journal_mode": journal_mode},
        "uptime_s": round(time.time() - state.started_at, 1),
    }
