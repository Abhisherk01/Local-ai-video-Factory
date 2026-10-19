"""System routes: runtime paths, path validation, prerequisite detection.

Phase 2 detection is real (executed checks, not placeholders), but the
actions are read-only: the wizard only reports and validates. Installs
stay manual / scripted (see scripts/setup-windows.ps1).
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from laf.api.state import AppState

router = APIRouter(prefix="/api/v1/system")
logger = logging.getLogger("laf.system")

_SMI_TIMEOUT_S = 4


@router.get("/paths")
def paths(request: Request) -> dict[str, str]:
    state: AppState = request.app.state.laf
    return {
        "data_dir": str(state.runtime.data_dir),
        "models_dir": str(state.runtime.models_dir),
        "db_path": str(state.runtime.db_path),
    }


class PathValidateRequest(BaseModel):
    path: str


def _dir_writable(directory: Path) -> bool:
    """Check write access by creating+deleting a temp file (no side effects)."""
    try:
        fd, probe = tempfile.mkstemp(prefix=".laf-write-", dir=str(directory))
        os.close(fd)
        os.unlink(probe)
        return True
    except OSError:
        return False


def _nearest_existing_ancestor(path: Path) -> Path:
    candidate = path
    for _ in range(32):
        if candidate.exists():
            return candidate
        if candidate.parent == candidate:
            return candidate
        candidate = candidate.parent
    return candidate


@router.post("/paths/validate")
def validate_path(payload: PathValidateRequest) -> dict[str, object]:
    raw = payload.path.strip()
    target = Path(raw).expanduser()
    exists = target.is_dir()

    probe = _nearest_existing_ancestor(target)
    writable = _dir_writable(probe) if probe.is_dir() else False

    free_gb: float | None = None
    try:
        free_gb = round(shutil.disk_usage(probe).free / 1_000_000_000, 1)
    except OSError:
        free_gb = None

    return {
        "path": str(target),
        "exists": exists,
        "writable": writable,
        "free_gb": free_gb,
    }


def _gpu_check() -> dict[str, object]:
    """Detect NVIDIA GPU via nvidia-smi (name + VRAM). Never installs."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return {
            "name": "gpu",
            "ok": False,
            "required": False,
            "detail": "no NVIDIA GPU detected - CPU/vector engines will be used "
            "until one is available",
        }
    try:
        result = subprocess.run(
            [
                smi,
                "--query-gpu=name,memory.total",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=_SMI_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "name": "gpu",
            "ok": False,
            "required": False,
            "detail": "nvidia-smi present but did not respond",
        }
    line = (result.stdout or "").strip().splitlines()
    if result.returncode == 0 and line:
        return {
            "name": "gpu",
            "ok": True,
            "required": False,
            "detail": line[0].strip(),
        }
    return {
        "name": "gpu",
        "ok": False,
        "required": False,
        "detail": "nvidia-smi present but reported no usable GPU",
    }


@router.get("/prereq")
def prereq(request: Request) -> list[dict[str, object]]:
    """Real detection, honest labels. Nothing here installs anything."""
    state: AppState = request.app.state.laf
    checks: list[dict[str, object]] = []

    checks.append(
        {
            "name": "python",
            "ok": True,
            "required": True,
            "detail": f"{platform.python_version()} (backend runtime)",
        }
    )

    ffmpeg_path = shutil.which("ffmpeg")
    checks.append(
        {
            "name": "ffmpeg",
            "ok": ffmpeg_path is not None,
            "required": False,
            "detail": ffmpeg_path
            or "not installed - needed from Phase 5 (rendering)",
        }
    )

    ollama_path = shutil.which("ollama")
    checks.append(
        {
            "name": "ollama",
            "ok": ollama_path is not None,
            "required": False,
            "detail": ollama_path or "optional until Phase 4 (LLM scripting)",
        }
    )

    node_path = shutil.which("node")
    checks.append(
        {
            "name": "node",
            "ok": node_path is not None,
            "required": False,
            "detail": node_path or "development builds only (frontend tooling)",
        }
    )

    checks.append(_gpu_check())

    try:
        free_gb = round(
            shutil.disk_usage(state.runtime.data_dir).free / 1_000_000_000, 1
        )
        checks.append(
            {
                "name": "disk",
                "ok": free_gb >= 60.0,
                "required": False,
                "detail": f"{free_gb} GB free at data dir (target: >= 60 GB before Phase 3)",
            }
        )
    except OSError:
        checks.append(
            {
                "name": "disk",
                "ok": False,
                "required": False,
                "detail": "free space could not be determined",
            }
        )

    return checks
