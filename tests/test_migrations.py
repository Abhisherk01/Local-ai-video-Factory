"""Tests for the migration runner (order, idempotency, atomicity)."""

from __future__ import annotations

from pathlib import Path

import pytest

from laf.db import MigrationError, connect, current_version, ensure_schema


def test_all_migrations_apply_and_are_idempotent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "laf.db")
    try:
        applied_first = ensure_schema(conn)
        assert applied_first and applied_first == sorted(applied_first)
        assert applied_first[0] == 1
        version = current_version(conn)
        assert applied_first[-1] == version

        # Second run must be a no-op.
        applied_second = ensure_schema(conn)
        assert applied_second == []
        assert current_version(conn) == version

        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"schema_migrations", "app_settings", "schema_info"} <= names
        # Phase 3 content pipeline tables (0002_episodes_jobs).
        assert {"episodes", "jobs"} <= names
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
        version_before = current_version(conn2)
        fake_dir = tmp_path / "fake_migrations"
        fake_dir.mkdir()
        bad_version = version_before + 1
        (fake_dir / f"{bad_version:04d}_bad.sql").write_text(
            "CREATE TABLE should_exist (id INTEGER);\nTHIS IS NOT VALID SQL;\n",
            encoding="utf-8",
        )

        original = mig.migrations_dir
        mig.migrations_dir = lambda: fake_dir  # type: ignore[assignment]
        try:
            with pytest.raises(MigrationError, match=f"{bad_version:04d}"):
                ensure_schema(conn2)
        finally:
            mig.migrations_dir = original  # type: ignore[assignment]

        # Rollback guarantees: no partial table, no version recorded.
        tables = {
            row[0]
            for row in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "should_exist" not in tables
        assert current_version(conn2) == version_before
    finally:
        conn2.close()


def test_migration_files_are_sorted_by_numeric_prefix(tmp_path: Path) -> None:
    from laf.db import migrations as mig

    discovered = mig._discover()
    versions = [v for v, _ in discovered]
    assert versions == sorted(versions)
    assert len(versions) >= 1
    assert all(isinstance(p.suffix, str) and p.suffix == ".sql" for _, p in discovered)
