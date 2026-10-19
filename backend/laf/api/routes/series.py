"""Series routes: create (with outline job), list, inspect, delete."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from laf.api.state import AppState
from laf.jobs import queue
from laf.series import (
    create_series,
    delete_series,
    get_series,
    list_series,
    list_series_episodes,
)

router = APIRouter(prefix="/api/v1/series")


class SeriesCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    premise: str = Field(min_length=1, max_length=4000)
    count: int = Field(default=20, ge=3, le=30)
    mode: str = Field(default="auto", pattern="^(auto|model|template)$")
    allow_fallback: bool = True
    idempotency_key: str | None = Field(default=None, max_length=200)


@router.get("")
def get_all(request: Request) -> dict:
    state: AppState = request.app.state.laf
    return {"series": list_series(state.conn)}


@router.post("", status_code=202)
def post_series(payload: SeriesCreate, request: Request) -> dict:
    """Create the series row and queue its outline job.

    mode=model    -> series_outline_gen (Ollama; honest failure unless
                     allow_fallback, then the deterministic 20 angles)
    mode=template -> series_outline_fallback
    mode=auto     -> series_outline_gen with allow_fallback from payload
    """
    state: AppState = request.app.state.laf
    series = create_series(
        state.conn,
        name=payload.name,
        premise=payload.premise,
        requested_count=payload.count,
    )
    series_id = int(series["id"])
    if payload.mode == "template":
        job_type = "series_outline_fallback"
    else:
        job_type = "series_outline_gen"
    job, created = queue.enqueue(
        state.conn,
        job_type,
        payload={
            "series_id": series_id,
            "allow_fallback": payload.allow_fallback,
        },
        idempotency_key=payload.idempotency_key,
    )
    return {"series": series, "job": job, "created": created}


@router.get("/{series_id}")
def get_one(series_id: int, request: Request) -> dict:
    state: AppState = request.app.state.laf
    series = get_series(state.conn, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="series not found")
    return {"series": series, "episodes": list_series_episodes(state.conn, series_id)}


@router.delete("/{series_id}")
def remove_one(series_id: int, request: Request) -> dict:
    state: AppState = request.app.state.laf
    if not delete_series(state.conn, series_id):
        raise HTTPException(status_code=404, detail="series not found")
    return {"deleted": True, "id": series_id}
