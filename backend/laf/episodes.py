"""Episode CRUD helpers (SQL lives here, not in routes).

Episodes are the unit of production: one short-form vertical video.
Phase 3 uses them for the script stage; later phases attach
storyboards, assets, and renders.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from laf.jobs.queue import row_to_episode

EPISODE_STATUSES = (
    "draft",
    "scripted",
    "storyboarded",
    "rendered",
    "published",
    "failed",
    "cancelled",
)


def create_episode(
    conn: sqlite3.Connection,
    *,
    title: str,
    topic: str,
    channel: str = "default",
    series_id: int | None = None,
) -> dict[str, Any]:
    cur = conn.execute(
        """
        INSERT INTO episodes (title, topic, channel, series_id)
        VALUES (?, ?, ?, ?)
        """,
        (title, topic, channel, int(series_id) if series_id is not None else None),
    )
    return get_episode(conn, int(cur.lastrowid))  # type: ignore[arg-type]


def get_episode(conn: sqlite3.Connection, episode_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM episodes WHERE id = ?", (int(episode_id),)
    ).fetchone()
    return row_to_episode(row) if row else None


def list_episodes(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    channel: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM episodes"
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        if status not in EPISODE_STATUSES:
            raise ValueError(f"invalid episode status filter: {status}")
        clauses.append("status = ?")
        params.append(status)
    if channel:
        clauses.append("channel = ?")
        params.append(channel)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    return [row_to_episode(row) for row in conn.execute(sql, params).fetchall()]


def set_episode_script(
    conn: sqlite3.Connection,
    episode_id: int,
    *,
    script_text: str,
    script_method: str,
) -> dict[str, Any] | None:
    """Store a generated script and move the episode to 'scripted'."""
    conn.execute(
        """
        UPDATE episodes
        SET script_text = ?, script_method = ?, status = 'scripted',
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (script_text, script_method, int(episode_id)),
    )
    return get_episode(conn, int(episode_id))


def set_episode_status(
    conn: sqlite3.Connection, episode_id: int, status: str
) -> dict[str, Any] | None:
    if status not in EPISODE_STATUSES:
        raise ValueError(f"invalid episode status: {status}")
    conn.execute(
        """
        UPDATE episodes SET status = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (status, int(episode_id)),
    )
    return get_episode(conn, int(episode_id))


def delete_episode(conn: sqlite3.Connection, episode_id: int) -> bool:
    """Delete an episode row. Jobs keep their history (episode_id
    becomes NULL via ON DELETE SET NULL) so the audit trail survives."""
    cur = conn.execute("DELETE FROM episodes WHERE id = ?", (int(episode_id),))
    return cur.rowcount > 0
