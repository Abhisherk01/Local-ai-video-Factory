"""Shared fixtures for API tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from laf.api.main import create_app

# Hermetic test session: handler tests expect Ollama to be ABSENT. With a
# live Ollama on 11434 they dial the real model and appear to freeze for
# minutes. Pin a dead port for every test process; tests that need a
# specific URL (fake servers) monkeypatch.setenv it and still win, because
# adapters read the env at construction time.
os.environ["LAF_OLLAMA_URL"] = "http://127.0.0.1:9"
os.environ["LAF_OLLAMA_TIMEOUT"] = "30"

TEST_TOKEN = "test-token-1234"


@pytest.fixture()
def client(tmp_path):
    """Quiet TestClient (no background worker) for deterministic API tests."""
    app = create_app(data_dir=tmp_path / "data", token=TEST_TOKEN, worker_enabled=False)
    with TestClient(app) as test_client:
        test_client.headers.update({"X-LAF-Token": TEST_TOKEN})
        yield test_client
