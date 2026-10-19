"""Tests for the SQLite connection layer (WAL, pragmas)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from laf.db import connect


def test_connect_creates_database_and_parent_dirs(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "dir" / "laf.db"
    assert not db_path.exists()
    conn = connect(db_path)
    try:
        assert db_path.exists()
        assert isinstance(conn, sqlite3.Connection)
    finally:
        conn.close()


def test_wal_mode_is_persistent_setting(tmp_path: Path) -> None:
    db_path = tmp_path / "laf.db"
    conn = connect(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"
    finally:
        conn.close()


def test_foreign_keys_and_busy_timeout_applied(tmp_path: Path) -> None:
    conn = connect(tmp_path / "laf.db")
    try:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert int(fk) == 1
        assert int(busy) >= 5000
    finally:
        conn.close()


def test_row_factory_returns_mapping_rows(tmp_path: Path) -> None:
    conn = connect(tmp_path / "laf.db")
    try:
        conn.executescript(
            "CREATE TABLE t (a INTEGER, b TEXT); INSERT INTO t VALUES (1, 'x');"
        )
        row = conn.execute("SELECT a, b FROM t").fetchone()
        assert row["a"] == 1 and row["b"] == "x"
    finally:
        conn.close()
