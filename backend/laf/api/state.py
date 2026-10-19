"""Shared application state attached to FastAPI (app.state.laf)."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field

from laf.config import RuntimePaths


@dataclass
class AppState:
    """One backend session: db handle, resolved paths, auth token."""

    conn: sqlite3.Connection
    runtime: RuntimePaths
    token: str | None
    started_at: float = field(default_factory=time.time)
    applied_migrations: list[int] = field(default_factory=list)

    # -- app_settings helpers ------------------------------------------------

    def all_settings(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT key, value FROM app_settings").fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        return str(row["value"]) if row else default

    def set_settings(self, values: dict[str, str]) -> None:
        """Upsert multiple settings in one transaction."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.executemany(
                """
                INSERT INTO app_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                [(str(k), str(v)) for k, v in values.items()],
            )
            self.conn.execute("COMMIT")
        except sqlite3.Error:
            self.conn.rollback()
            raise
