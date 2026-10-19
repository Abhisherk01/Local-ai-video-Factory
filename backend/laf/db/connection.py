"""SQLite connection factory.

Decisions (ADR-002):
- WAL journal mode: concurrent readers while a job writes, crash-safe.
- autocommit connection (isolation_level=None): the migration runner
  manages transactions explicitly; everything else is single-statement.
- busy_timeout + NORMAL sync: durability with laptop-friendly latency.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (and create) the app database with project-standard pragmas.

    check_same_thread=False: FastAPI runs sync handlers on a worker
    thread pool while the connection is opened during startup. Phase 2
    access is effectively serialized (single user, single process, short
    queries), so one shared connection is safe here. Phase 3 (durable
    job queue with real write concurrency) will switch to per-thread
    connections - tracked in ROADMAP.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        timeout=30.0,
        isolation_level=None,  # autocommit; explicit BEGIN where needed
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn
