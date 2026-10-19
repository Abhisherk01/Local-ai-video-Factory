"""App settings routes backed by the app_settings table."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from laf.api.state import AppState

router = APIRouter(prefix="/api/v1/settings")


class SettingsUpdate(BaseModel):
    values: dict[str, str]


@router.get("")
def get_settings(request: Request) -> dict[str, dict[str, str]]:
    state: AppState = request.app.state.laf
    return {"values": state.all_settings()}


@router.put("")
def put_settings(payload: SettingsUpdate, request: Request) -> dict[str, dict[str, str]]:
    state: AppState = request.app.state.laf
    state.set_settings(payload.values)
    return {"values": state.all_settings()}
