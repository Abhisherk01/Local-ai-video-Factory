"""Episode routes: create, list, inspect, delete, enqueue script and
storyboard jobs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from laf.api.state import AppState
from laf.episodes import create_episode, delete_episode, get_episode, list_episodes
from laf.jobs import queue
from laf.styles import get_style
from laf.storyboards import get_storyboard

router = APIRouter(prefix="/api/v1/episodes")


class EpisodeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=2000)
    channel: str = Field(min_length=1, max_length=100, default="default")


class ScriptRequest(BaseModel):
    mode: str = Field(default="auto", pattern="^(auto|model|template)$")
    allow_fallback: bool = True
    idempotency_key: str | None = Field(default=None, max_length=200)


@router.post("", status_code=201)
def post_episode(payload: EpisodeCreate, request: Request) -> dict:
    state: AppState = request.app.state.laf
    episode = create_episode(
        state.conn, title=payload.title, topic=payload.topic, channel=payload.channel
    )
    return {"episode": episode}


@router.get("")
def get_episodes(
    request: Request,
    status: str | None = None,
    channel: str | None = None,
    limit: int = 100,
) -> dict:
    state: AppState = request.app.state.laf
    try:
        episodes = list_episodes(
            state.conn, status=status, channel=channel, limit=min(limit, 500)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"episodes": episodes}


@router.get("/{episode_id}")
def get_one(episode_id: int, request: Request) -> dict:
    state: AppState = request.app.state.laf
    episode = get_episode(state.conn, episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="episode not found")
    return {"episode": episode}


@router.delete("/{episode_id}")
def delete_one(episode_id: int, request: Request) -> dict:
    state: AppState = request.app.state.laf
    if not delete_episode(state.conn, episode_id):
        raise HTTPException(status_code=404, detail="episode not found")
    return {"deleted": True, "id": episode_id}


@router.post("/{episode_id}/script", status_code=202)
def enqueue_script(episode_id: int, payload: ScriptRequest, request: Request) -> dict:
    """Queue a script job for the episode.

    mode=model    -> script_gen (Ollama; fails honestly if unavailable
                     unless allow_fallback, then uses the template)
    mode=template -> script_fallback (deterministic template, no model)
    mode=auto     -> script_gen with allow_fallback from the payload
    """
    state: AppState = request.app.state.laf
    episode = get_episode(state.conn, episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="episode not found")

    if payload.mode == "template":
        job_type = "script_fallback"
        job_payload = {"topic": episode["topic"]}
    else:
        job_type = "script_gen"
        job_payload = {
            "topic": episode["topic"],
            "allow_fallback": payload.allow_fallback,
        }

    job, created = queue.enqueue(
        state.conn,
        job_type,
        payload=job_payload,
        episode_id=episode_id,
        idempotency_key=payload.idempotency_key,
    )
    return {"job": job, "created": created}


class StoryboardRequest(BaseModel):
    style_slug: str | None = Field(default=None, max_length=40)
    mode: str = Field(default="auto", pattern="^(auto|model|template)$")
    allow_fallback: bool = True
    idempotency_key: str | None = Field(default=None, max_length=200)


@router.post("/{episode_id}/storyboard", status_code=202)
def enqueue_storyboard(
    episode_id: int, payload: StoryboardRequest, request: Request
) -> dict:
    """Queue a storyboard job for a scripted episode.

    The scene plan needs narration to slice, so the episode must carry
    a script (400 otherwise - queueing a job that cannot run would just
    burn an attempt). Style resolves at enqueue time for fast feedback
    and again inside the handler (registry may change in between).
    """
    state: AppState = request.app.state.laf
    episode = get_episode(state.conn, episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="episode not found")
    if not str(episode["script_text"] or "").strip():
        raise HTTPException(
            status_code=400,
            detail="episode has no script yet - run Script first",
        )

    style_slug = payload.style_slug
    if style_slug is not None and get_style(state.conn, style_slug) is None:
        raise HTTPException(
            status_code=400, detail=f"unknown style slug: {style_slug}"
        )

    if payload.mode == "template":
        job_type = "storyboard_fallback"
    else:
        job_type = "storyboard_gen"
    job, created = queue.enqueue(
        state.conn,
        job_type,
        payload={
            "style_slug": style_slug,
            "allow_fallback": payload.allow_fallback,
        },
        episode_id=episode_id,
        idempotency_key=payload.idempotency_key,
    )
    return {"job": job, "created": created}


@router.get("/{episode_id}/storyboard")
def fetch_storyboard(episode_id: int, request: Request) -> dict:
    state: AppState = request.app.state.laf
    if get_episode(state.conn, episode_id) is None:
        raise HTTPException(status_code=404, detail="episode not found")
    return {"storyboard": get_storyboard(state.conn, episode_id)}
