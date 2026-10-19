"""Job routes: enqueue (generic), inspect, list, cancel, stats.

NOTE: `/stats` is declared before `/{job_id}` on purpose - FastAPI
matches routes in declaration order, and "stats" would otherwise be
captured by the int path parameter.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from laf.api.state import AppState
from laf.jobs import JOB_STATUSES, queue
from laf.jobs.handlers import known_types

router = APIRouter(prefix="/api/v1/jobs")


class JobCreate(BaseModel):
    type: str = Field(min_length=1, max_length=100)
    payload: dict = Field(default_factory=dict)
    episode_id: int | None = None
    priority: int = Field(default=100, ge=1, le=10_000)
    gpu: bool = False
    max_attempts: int = Field(default=3, ge=1, le=10)
    idempotency_key: str | None = Field(default=None, max_length=200)


@router.get("/stats")
def stats(request: Request) -> dict:
    state: AppState = request.app.state.laf
    worker = state.worker
    return {
        "stats": queue.job_stats(state.conn),
        "known_types": known_types(),
        "worker": {
            "running": worker.is_alive() if worker else False,
            "worker_id": worker.worker_id if worker else None,
        },
    }


@router.post("", status_code=201)
def enqueue_job(payload: JobCreate, request: Request) -> dict:
    state: AppState = request.app.state.laf
    if payload.type not in known_types():
        raise HTTPException(
            status_code=400,
            detail=f"unknown job type '{payload.type}' (known: {known_types()})",
        )
    if payload.episode_id is not None:
        from laf.episodes import get_episode

        if get_episode(state.conn, payload.episode_id) is None:
            raise HTTPException(status_code=404, detail="episode not found")
    job, created = queue.enqueue(
        state.conn,
        payload.type,
        payload=payload.payload,
        episode_id=payload.episode_id,
        priority=payload.priority,
        gpu=payload.gpu,
        max_attempts=payload.max_attempts,
        idempotency_key=payload.idempotency_key,
    )
    return {"job": job, "created": created}


@router.get("")
def list_all(
    request: Request,
    status: str | None = None,
    episode_id: int | None = None,
    limit: int = 50,
) -> dict:
    state: AppState = request.app.state.laf
    try:
        jobs = queue.list_jobs(
            state.conn,
            status=status,
            episode_id=episode_id,
            limit=min(limit, 500),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"jobs": jobs, "stats": queue.job_stats(state.conn)}


@router.get("/{job_id}")
def get_one(job_id: int, request: Request) -> dict:
    state: AppState = request.app.state.laf
    job = queue.get_job(state.conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"job": job}


@router.post("/{job_id}/cancel")
def cancel_one(job_id: int, request: Request) -> dict:
    state: AppState = request.app.state.laf
    if queue.get_job(state.conn, job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    job = queue.cancel(state.conn, job_id)
    if job is None:
        raise HTTPException(
            status_code=409,
            detail=f"only queued jobs can be cancelled (statuses: {JOB_STATUSES})",
        )
    return {"job": job}
