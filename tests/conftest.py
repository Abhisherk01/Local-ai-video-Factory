"""Shared fixtures for API tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from laf.api.main import create_app

TEST_TOKEN = "test-token-1234"


@pytest.fixture()
def client(tmp_path):
    """TestClient with the session token pre-set on every request."""
    app = create_app(data_dir=tmp_path / "data", token=TEST_TOKEN)
    with TestClient(app) as test_client:
        test_client.headers.update({"X-LAF-Token": TEST_TOKEN})
        yield test_client
