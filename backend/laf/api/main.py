"""FastAPI application factory for the Local AI Video Factory backend."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from laf import __version__
from laf.api.middleware import TokenMiddleware
from laf.api.routes import adapters, health, jobs, settings, system, episodes
from laf.api.state import AppState
from laf.config import resolve_runtime
from laf.db import connect, ensure_schema
from laf.jobs.worker import Worker

logger = logging.getLogger("laf.app")

# Origins allowed to call the API from the embedded WebView / dev server.
CORS_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def create_app(
    data_dir: str | Path | None = None,
    models_dir: str | Path | None = None,
    token: str | None = None,
    worker_enabled: bool = True,
) -> FastAPI:
    """Build the FastAPI app: connect db, run migrations, wire routes."""
    runtime = resolve_runtime(data_dir, models_dir)
    runtime.ensure_dirs()

    conn = connect(runtime.db_path)
    applied = ensure_schema(conn)
    if applied:
        logger.info(
            "migrations applied",
            extra={"versions": applied, "db": str(runtime.db_path)},
        )

    state = AppState(
        conn=conn,
        runtime=runtime,
        token=token,
        applied_migrations=applied,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        worker: Worker | None = None
        if worker_enabled:
            worker = Worker(
                runtime.db_path,
                data_dir=runtime.data_dir,
                models_dir=runtime.models_dir,
            )
            state.worker = worker
            worker.start()
        logger.info(
            "backend ready",
            extra={
                "data_dir": str(runtime.data_dir),
                "db": str(runtime.db_path),
                "token_auth": bool(token),
                "worker": worker_enabled,
            },
        )
        yield
        try:
            if worker is not None:
                worker.stop()
        except Exception:  # pragma: no cover - defensive shutdown
            pass
        try:
            conn.close()
        except Exception:  # pragma: no cover - defensive shutdown
            pass

    app = FastAPI(
        title="Local AI Video Factory",
        version=__version__,
        lifespan=lifespan,
        # OpenAPI docs disabled: this is a local-only, token-gated API,
        # not a public surface. Enable temporarily via env if ever needed.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.laf = state

    # Order matters: CORS must wrap the token middleware so preflight
    # OPTIONS requests (which carry no custom headers) succeed.
    app.add_middleware(TokenMiddleware, token=token or "")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["X-LAF-Token", "Content-Type"],
    )

    app.include_router(health.router)
    app.include_router(system.router)
    app.include_router(settings.router)
    app.include_router(episodes.router)
    app.include_router(jobs.router)
    app.include_router(adapters.router)
    return app
