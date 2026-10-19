"""Series CRUD + deterministic outline angles (ADR-011).

A series is one premise expanded into many episode stubs. The model
path (series_outline_gen) proposes candidates; the fallback path uses
the 20 fixed angles below - each angle names a different facet of the
premise, so the batch passes duplicate detection (laf.dedupe) by
construction, which is exactly the roadmap gate.
"""

from __future__ import annotations

import sqlite3
from typing import Any

# (title template, topic template) - {p} is the series premise.
# Keep angle wording lexically distinct: the duplicate detector works
# on content tokens, and the 20-item gate must pass without a model.
OUTLINE_ANGLES: list[tuple[str, str]] = [
    ("The origin story of {p}", "where {p} came from and how it quietly started"),
    ("5 mistakes people make with {p}", "the most common {p} mistakes and what to do instead"),
    ("The science behind {p}", "what actually happens mechanically when {p} works"),
    ("{p} for absolute beginners", "a zero-experience starting guide to {p}"),
    ("The tools you need for {p}", "gear and equipment that genuinely matter for {p}"),
    ("{p} myths debunked", "widely believed falsehoods about {p} and the truth"),
    ("Fixing broken {p}", "troubleshooting the most frequent {p} failures step by step"),
    ("What {p} really costs", "the true price of {p} in time, money and effort"),
    ("{p} in 60 seconds", "a compressed overview of the whole {p} landscape"),
    ("Advanced {p} techniques", "next-level methods once the basics of {p} are mastered"),
    ("The untold history of {p}", "overlooked stories behind how {p} evolved"),
    ("{p} versus the alternatives", "how {p} compares against its main substitutes"),
    ("Timing rules for {p}", "when to do each step of {p} and why timing decides the result"),
    ("Storing and caring for {p}", "keeping {p} in good condition over the long term"),
    ("{p} on a budget", "the cheapest sensible way to approach {p} without regret"),
    ("Expert habits around {p}", "small routines experienced people apply to {p}"),
    ("Quick wins for {p}", "fast improvements anyone can apply to {p} today"),
    ("The biggest {p} controversies", "real debates and disagreements surrounding {p}"),
    ("{p} questions everyone asks", "short direct answers to the questions novices raise about {p}"),
    ("What nobody warns you about {p}", "surprising downsides and risks of {p} before starting"),
]


def create_series(
    conn: sqlite3.Connection,
    *,
    name: str,
    premise: str,
    requested_count: int = 20,
) -> dict[str, Any]:
    cur = conn.execute(
        """
        INSERT INTO series (name, premise, requested_count) VALUES (?, ?, ?)
        """,
        (name, premise, int(requested_count)),
    )
    return get_series(conn, int(cur.lastrowid))  # type: ignore[arg-type]


def get_series(conn: sqlite3.Connection, series_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, name, premise, requested_count, method, created_at, updated_at
        FROM series WHERE id = ?
        """,
        (int(series_id),),
    ).fetchone()
    return dict(row) if row else None


def delete_series(conn: sqlite3.Connection, series_id: int) -> bool:
    """Delete the series row. Episodes survive with series_id = NULL
    (ON DELETE SET NULL); their job history keeps the audit trail."""
    cur = conn.execute("DELETE FROM series WHERE id = ?", (int(series_id),))
    return cur.rowcount > 0


def list_series(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT s.id, s.name, s.premise, s.requested_count, s.method,
               s.created_at, s.updated_at,
               (SELECT COUNT(*) FROM episodes e WHERE e.series_id = s.id)
                   AS episode_count
        FROM series s ORDER BY s.id DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def list_series_episodes(conn: sqlite3.Connection, series_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, title, topic, channel, status, script_method, created_at
        FROM episodes WHERE series_id = ? ORDER BY id ASC
        """,
        (int(series_id),),
    ).fetchall()
    return [dict(r) for r in rows]


def set_series_method(
    conn: sqlite3.Connection, series_id: int, method: str
) -> None:
    conn.execute(
        """
        UPDATE series SET method = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (method, int(series_id)),
    )


def fallback_outline(premise: str, count: int) -> list[dict[str, str]]:
    """Deterministic distinct-angle outline; capped at the 20 angles."""
    p = premise.strip() or "your topic"
    take = max(1, min(int(count), len(OUTLINE_ANGLES)))
    return [
        {"title": t.format(p=p), "topic": d.format(p=p)}
        for t, d in OUTLINE_ANGLES[:take]
    ]
