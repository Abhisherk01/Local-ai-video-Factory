"""Tests for settings routes + token enforcement."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from laf.api.main import create_app
from tests.conftest import TEST_TOKEN


def test_data_routes_require_token(tmp_path) -> None:
    app = create_app(data_dir=tmp_path / "data", token=TEST_TOKEN)
    with TestClient(app) as anonymous:  # no token header at all
        assert anonymous.get("/api/v1/settings").status_code == 401
        assert anonymous.get("/api/v1/system/paths").status_code == 401
        response = anonymous.get("/health")
        assert response.status_code == 200  # health stays open


def test_wrong_token_rejected(tmp_path) -> None:
    app = create_app(data_dir=tmp_path / "data", token=TEST_TOKEN)
    with TestClient(app) as wrong:
        wrong.headers.update({"X-LAF-Token": "not-the-token"})
        assert wrong.get("/api/v1/settings").status_code == 401


def test_settings_roundtrip(client) -> None:
    put = client.put("/api/v1/settings", json={"values": {"theme": "laf-dark-graphite"}})
    assert put.status_code == 200
    got = client.get("/api/v1/settings").json()["values"]
    assert got["theme"] == "laf-dark-graphite"


def test_settings_upsert_overwrites(client) -> None:
    client.put("/api/v1/settings", json={"values": {"k": "v1"}})
    client.put("/api/v1/settings", json={"values": {"k": "v2"}})
    got = client.get("/api/v1/settings").json()["values"]
    assert got["k"] == "v2"


def test_settings_persisted_in_sqlite(client, tmp_path) -> None:
    client.put("/api/v1/settings", json={"values": {"onboarding_complete": "true"}})
    # Fresh raw connection proves it hit disk, not memory.
    conn = sqlite3.connect(str(tmp_path / "data" / "laf.db"))
    try:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'onboarding_complete'"
        ).fetchone()
        assert row is not None and row[0] == "true"
    finally:
        conn.close()
