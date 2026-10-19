"""Storyboard persistence (ADR-011).

One storyboard per episode (latest wins): re-planning deletes the old
rows and inserts fresh ones inside a single transaction, then moves the
episode to 'storyboarded'. Scene rows are ordered by idx (1-based) and
carry the narration slice + composed visual prompt + estimated duration
that the Phase 5 renderer will consume one by one.

Durations are estimated locally from narration length at ~2.5 words per
second (150 wpm presentation pace) - never fabricated per-scene by the
model. Total duration is the honest sum of those estimates.
"""

from __future__ import annotations

import sqlite3
from typing import Any

WORDS_PER_SECOND = 2.5
MIN_SCENE_SECONDS = 2.0


def estimate_duration_s(narration: str) -> float:
    """Presentation-pace duration estimate for one scene's narration."""
    words = len(narration.split())
    return round(max(MIN_SCENE_SECONDS, words / WORDS_PER_SECOND), 1)


def replace_storyboard(
    conn: sqlite3.Connection,
    *,
    episode_id: int,
    style_slug: str,
    method: str,
    scenes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Store a fresh storyboard for the episode (replaces any old one).

    `scenes` items need keys narration / visual_prompt; duration is
    computed here. Returns the stored storyboard (with scenes), or None
    when the episode no longer exists.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        ep = conn.execute(
            "SELECT id FROM episodes WHERE id = ?", (int(episode_id),)
        ).fetchone()
        if ep is None:
            conn.execute("COMMIT")
            return None

        row = conn.execute(
            "SELECT id FROM storyboards WHERE episode_id = ?", (int(episode_id),)
        ).fetchone()
        if row is not None:  # replaces cascade to old scenes
            conn.execute(
                "DELETE FROM storyboards WHERE id = ?", (int(row["id"]),)
            )

        total = round(sum(estimate_duration_s(str(s.get("narration", ""))) for s in scenes), 1)
        cur = conn.execute(
            """
            INSERT INTO storyboards (episode_id, style_slug, method,
                                     scene_count, total_duration_s)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(episode_id), str(style_slug), method, len(scenes), total),
        )
        storyboard_id = int(cur.lastrowid)
        conn.executemany(
            """
            INSERT INTO storyboard_scenes
                (storyboard_id, idx, narration, visual_prompt, duration_s)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    storyboard_id,
                    i + 1,
                    str(s.get("narration", "")),
                    str(s.get("visual_prompt", "")),
                    estimate_duration_s(str(s.get("narration", ""))),
                )
                for i, s in enumerate(scenes)
            ],
        )
        conn.execute(
            """
            UPDATE episodes SET status = 'storyboarded',
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (int(episode_id),),
        )
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.rollback()
        raise
    return get_storyboard(conn, int(episode_id))


def get_storyboard(conn: sqlite3.Connection, episode_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, episode_id, style_slug, method, scene_count,
               total_duration_s, created_at, updated_at
        FROM storyboards WHERE episode_id = ?
        """,
        (int(episode_id),),
    ).fetchone()
    if row is None:
        return None
    storyboard = dict(row)
    storyboard["scenes"] = [
        dict(r)
        for r in conn.execute(
            """
            SELECT idx, narration, visual_prompt, duration_s
            FROM storyboard_scenes WHERE storyboard_id = ?
            ORDER BY idx ASC
            """,
            (int(row["id"]),),
        ).fetchall()
    ]
    return storyboard
