"""Tests for GET /health (open endpoint, no token required)."""

from __future__ import annotations

from laf import __version__


def test_health_ok_without_token(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_health_reports_db_status(client) -> None:
    body = client.get("/health").json()
    assert body["db"]["ok"] is True
    assert str(body["db"]["journal_mode"]).lower() == "wal"


def test_health_reports_uptime(client) -> None:
    body = client.get("/health").json()
    assert isinstance(body["uptime_s"], (int, float))
    assert body["uptime_s"] >= 0.0
