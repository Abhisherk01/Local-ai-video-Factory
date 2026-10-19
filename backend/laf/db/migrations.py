"""Versioned SQL migration runner.

Conventions:
- Migration files live in laf/db/migrations/ and are named NNNN_name.sql.
- Files run in ascending numeric order, exactly once.
- Applied versions are recorded in schema_migrations.
- Each file runs inside one explicit transaction (BEGIN IMMEDIATE ...
  COMMIT). On any SQLite error the transaction is rolled back and
  MigrationError is raised with the failing file identified.

Phase 2 keeps the schema minimal (app_settings + schema_info); the full
domain model (projects, episodes, jobs, assets, accounts) lands in its
own migrations in later phases.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class MigrationError(RuntimeError):
    """Raised when a migration fails; the transaction is rolled back."""


def migrations_dir() -> Path:
    return Path(__file__).parent / "migrations"


def _discover() -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for path in sorted(migrations_dir().iterdir()):
        match = _MIGRATION_RE.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    found.sort(key=lambda pair: pair[0])
    return found


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    return {int(row[0]) for row in conn.execute("SELECT version FROM schema_migrations")}


def ensure_schema(conn: sqlite3.Connection) -> list[int]:
    """Apply all pending migrations. Returns the versions applied now."""
    done: list[int] = []
    already = applied_versions(conn)
    for version, path in _discover():
        if version in already:
            continue
        sql = path.read_text(encoding="utf-8")
        # Strip leading/collar comments but keep statements intact.
        safe_name = path.name.replace("'", "''")
        script = (
            f"BEGIN IMMEDIATE;\n{sql}\n"
            f"INSERT INTO schema_migrations (version, name) VALUES ({version}, '{safe_name}');\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error as exc:
            conn.rollback()  # no-op if no transaction is open
            raise MigrationError(
                f"migration {version:04d} ({path.name}) failed: {exc}"
            ) from exc
        done.append(version)
    return done


def current_version(conn: sqlite3.Connection) -> int:
    """Highest applied migration version, or 0 on a fresh database."""
    applied_versions(conn)  # ensure tracking table exists
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0]) if row and row[0] is not None else 0
