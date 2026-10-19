"""Adapter status route: one honest probe per generation backend."""

from __future__ import annotations

from fastapi import APIRouter, Request

from laf.adapters import status_summary
from laf.api.state import AppState

router = APIRouter(prefix="/api/v1/adapters")


@router.get("")
def get_adapters(request: Request) -> dict:
    state: AppState = request.app.state.laf
    worker = state.worker
    return {
        "adapters": status_summary(state.runtime.models_dir),
        "worker": {
            "running": worker.is_alive() if worker else False,
            "worker_id": worker.worker_id if worker else None,
        },
    }
