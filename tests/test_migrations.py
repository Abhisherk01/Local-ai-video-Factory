"""Tests for the migration runner (order, idempotency, atomicity)."""

from __future__ import annotations

from pathlib import Path

import pytest

from laf.db import MigrationError, connect, current_version, ensure_schema


def test_initial_migration_applies_and_is_idempotent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "laf.db")
    try:
        applied_first = ensure_schema(conn)
        assert applied_first == [1]
        assert current_version(conn) == 1

        # Second run must be a no-op.
        applied_second = ensure_schema(conn)
        assert applied_second == []
        assert current_version(conn) == 1

        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"schema_migrations", "app_settings", "schema_info"} <= names
    finally:
        conn.close()


def test_schema_info_marker_row_exists(tmp_path: Path) -> None:
    conn = connect(tmp_path / "laf.db")
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT schema_version FROM schema_info WHERE id = 1"
        ).fetchone()
        assert row is not None and int(row[0]) == 1
    finally:
        conn.close()


def test_app_settings_upsert_semantics(tmp_path: Path) -> None:
    conn = connect(tmp_path / "laf.db")
    try:
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES ('onboarding_complete', 'false')"
        )
        conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES ('onboarding_complete', 'true')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                           updated_at = excluded.updated_at
            """
        )
        value = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'onboarding_complete'"
        ).fetchone()[0]
        assert value == "true"
    finally:
        conn.close()


def test_failed_migration_rolls_back_fully(tmp_path: Path) -> None:
    from laf.db import migrations as mig

    conn2 = connect(tmp_path / "laf.db")
    try:
        ensure_schema(conn2)  # baseline applied
        fake_dir = tmp_path / "fake_migrations"
        fake_dir.mkdir()
        (fake_dir / "0002_bad.sql").write_text(
            "CREATE TABLE should_exist (id INTEGER);\nTHIS IS NOT VALID SQL;\n",
            encoding="utf-8",
        )

        original = mig.migrations_dir
        mig.migrations_dir = lambda: fake_dir  # type: ignore[assignment]
        try:
            with pytest.raises(MigrationError, match="0002"):
                ensure_schema(conn2)
        finally:
            mig.migrations_dir = original  # type: ignore[assignment]

        # Rollback guarantees: no partial table, no version recorded.
        tables = {
            row[0]
            for row in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "should_exist" not in tables
        assert current_version(conn2) == 1
    finally:
        conn2.close()


def test_migration_files_are_sorted_by_numeric_prefix(tmp_path: Path) -> None:
    from laf.db import migrations as mig

    discovered = mig._discover()
    versions = [v for v, _ in discovered]
    assert versions == sorted(versions)
    assert len(versions) >= 1
    assert all(isinstance(p.suffix, str) and p.suffix == ".sql" for _, p in discovered)
