"""Runtime path resolution for the backend.

Precedence: explicit argument > environment variable > platform default.
The Tauri shell always passes --data-dir explicitly (ADR-008); the
fallbacks here keep standalone development and tests simple.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import __version__

DATA_DIR_ENV = "LAF_DATA_DIR"
MODELS_DIR_ENV = "LAF_MODELS_DIR"


def default_data_dir() -> Path:
    """Platform default for user data (db, runtime files, exports)."""
    env = os.environ.get(DATA_DIR_ENV)
    if env:
        return Path(env).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "LocalAIVideoFactory"
    return Path.home() / ".local" / "share" / "LocalAIVideoFactory"


@dataclass(frozen=True)
class RuntimePaths:
    """Resolved filesystem locations for one backend session."""

    data_dir: Path
    models_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "laf.db"

    @property
    def runtime_file(self) -> Path:
        """Handshake file consumed by dev tooling (never logs the token)."""
        return self.data_dir / "runtime.json"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)


def resolve_runtime(
    data_dir: str | Path | None = None,
    models_dir: str | Path | None = None,
) -> RuntimePaths:
    """Resolve runtime paths from explicit args, then env, then defaults."""
    d = Path(data_dir).expanduser() if data_dir else default_data_dir()
    env_models = os.environ.get(MODELS_DIR_ENV)
    if models_dir:
        m = Path(models_dir).expanduser()
    elif env_models:
        m = Path(env_models).expanduser()
    else:
        m = d / "models"
    return RuntimePaths(data_dir=d, models_dir=m)


def user_agent() -> str:
    """Identifying string for any future outbound calls (all local in Phase 2)."""
    return f"LocalAIVideoFactory/{__version__}"
