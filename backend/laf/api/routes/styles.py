"""Style registry routes: list, create, delete (builtins protected)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from laf.api.state import AppState
from laf.styles import SLUG_RE, create_style, delete_style, get_style, list_styles

router = APIRouter(prefix="/api/v1/styles")


class StyleCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    name: str = Field(min_length=1, max_length=80)
    prompt_prefix: str = Field(default="", max_length=500)
    prompt_suffix: str = Field(default="", max_length=500)


@router.get("")
def get_all(request: Request) -> dict:
    state: AppState = request.app.state.laf
    return {"styles": list_styles(state.conn)}


@router.post("", status_code=201)
def post_style(payload: StyleCreate, request: Request) -> dict:
    state: AppState = request.app.state.laf
    try:
        style = create_style(
            state.conn,
            slug=payload.slug,
            name=payload.name,
            prompt_prefix=payload.prompt_prefix,
            prompt_suffix=payload.prompt_suffix,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail=f"style slug already exists: {payload.slug}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"style": style}


@router.delete("/{slug}")
def remove_style(slug: str, request: Request) -> dict:
    state: AppState = request.app.state.laf
    style = get_style(state.conn, slug)
    if style is None:
        raise HTTPException(status_code=404, detail="style not found")
    if style["is_builtin"]:
        raise HTTPException(
            status_code=400, detail="builtin styles cannot be deleted"
        )
    if not delete_style(state.conn, slug):
        raise HTTPException(status_code=404, detail="style not found")
    return {"deleted": True, "slug": slug}
