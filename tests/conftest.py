"""Shared fixtures for API tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from laf.api.main import create_app

TEST_TOKEN = "test-token-1234"


@pytest.fixture()
def client(tmp_path):
    """Quiet TestClient (no background worker) for deterministic API tests."""
    app = create_app(data_dir=tmp_path / "data", token=TEST_TOKEN, worker_enabled=False)
    with TestClient(app) as test_client:
        test_client.headers.update({"X-LAF-Token": TEST_TOKEN})
        yield test_client
