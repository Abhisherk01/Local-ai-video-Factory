"""Voice routes: the piper voice registry for the UI dropdown (0.4.5).

GET /api/v1/voices
  voices  -> every voice installed on disk, catalog metadata merged
             (custom/non-catalog models included, flagged honestly)
  catalog -> the ten curated catalog entries with an installed flag,
             so the UI can point at scripts/add_voice.ps1 for the rest
  voices_dir -> where voice files live (copy target for manual installs)
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from laf.api.state import AppState
from laf.voices import catalog_summary, installed_voices, voices_dir

router = APIRouter(prefix="/api/v1/voices")


@router.get("")
def get_voices(request: Request) -> dict:
    state: AppState = request.app.state.laf
    models_dir = state.runtime.models_dir
    return {
        "voices": installed_voices(models_dir),
        "catalog": catalog_summary(models_dir),
        "voices_dir": str(voices_dir(models_dir)),
    }
