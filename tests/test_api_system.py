"""Tests for system routes: paths, validation, prerequisite detection."""

from __future__ import annotations


def test_paths_endpoint_shape(client, tmp_path) -> None:
    body = client.get("/api/v1/system/paths").json()
    assert set(body.keys()) == {"data_dir", "models_dir", "db_path"}
    assert body["data_dir"] == str(tmp_path / "data")
    assert body["db_path"].endswith("laf.db")


def test_validate_existing_writable_dir(client, tmp_path) -> None:
    response = client.post("/api/v1/system/paths/validate", json={"path": str(tmp_path)})
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["writable"] is True
    assert body["free_gb"] > 0.0


def test_validate_missing_dir_reports_honestly(client, tmp_path) -> None:
    missing = tmp_path / "does" / "not" / "exist"
    body = client.post(
        "/api/v1/system/paths/validate", json={"path": str(missing)}
    ).json()
    assert body["exists"] is False
    # Parent chain exists and is writable, so the wizard can offer to create it.
    assert body["writable"] is True
    assert body["free_gb"] > 0.0


def test_prereq_checks_have_honest_shape(client) -> None:
    checks = client.get("/api/v1/system/prereq").json()
    assert isinstance(checks, list) and len(checks) >= 4
    for item in checks:
        assert set(item.keys()) == {"name", "ok", "required", "detail"}
        assert isinstance(item["ok"], bool)
        assert isinstance(item["required"], bool)

    by_name = {item["name"]: item for item in checks}
    assert by_name["python"]["ok"] is True
    assert by_name["python"]["required"] is True
    # ffmpeg/ollama/disk are advisory in Phase 2 (not required).
    assert by_name["ffmpeg"]["required"] is False
    assert by_name["ollama"]["required"] is False
