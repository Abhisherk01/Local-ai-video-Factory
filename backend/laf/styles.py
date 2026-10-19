"""Style registry CRUD (ADR-011).

A style is a reusable pair of prompt fragments that condition every
scene visual prompt of a storyboard: prefix (look/feel) + suffix
(framing/medium). Builtin rows are seeded by migration 0003; users can
add custom styles. Builtins cannot be deleted - they are part of the
product contract the UI dropdown relies on.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

SLUG_RE = re.compile(r"^[a-z0-9_]{2,40}$")

# The storyboard request uses this when the caller does not pick one.
DEFAULT_STYLE_SLUG = "dark_cinematic"


def list_styles(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, slug, name, prompt_prefix, prompt_suffix, is_builtin,
               created_at, updated_at
        FROM styles ORDER BY is_builtin DESC, slug ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_style(conn: sqlite3.Connection, slug: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, slug, name, prompt_prefix, prompt_suffix, is_builtin,
               created_at, updated_at
        FROM styles WHERE slug = ?
        """,
        (str(slug),),
    ).fetchone()
    return dict(row) if row else None


def create_style(
    conn: sqlite3.Connection,
    *,
    slug: str,
    name: str,
    prompt_prefix: str = "",
    prompt_suffix: str = "",
) -> dict[str, Any]:
    if not SLUG_RE.match(slug):
        raise ValueError("slug must match [a-z0-9_]{2,40}")
    conn.execute(
        """
        INSERT INTO styles (slug, name, prompt_prefix, prompt_suffix, is_builtin)
        VALUES (?, ?, ?, ?, 0)
        """,
        (slug, name, prompt_prefix, prompt_suffix),
    )
    return get_style(conn, slug)


def delete_style(conn: sqlite3.Connection, slug: str) -> bool:
    """Delete a custom style. Builtin rows are guarded by the route."""
    cur = conn.execute("DELETE FROM styles WHERE slug = ?", (str(slug),))
    return cur.rowcount > 0
