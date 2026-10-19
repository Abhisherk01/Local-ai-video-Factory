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
    """Open (and create) the app database with project-standard pragmas."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        timeout=30.0,
        isolation_level=None,  # autocommit; explicit BEGIN where needed
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn
