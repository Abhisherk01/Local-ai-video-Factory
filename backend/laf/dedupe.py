"""Duplicate detection for series outlines (ADR-011).

Why not embeddings or an LLM judge: duplicate detection must be
deterministic, explainable, and testable without a model - the roadmap
gate ("20-episode sample outline passes duplicate detection") has to
hold on a machine with nothing installed. Normalized token-set Jaccard
similarity does that with stdlib only.

Rules:
- normalize(): lowercase, keep [a-z0-9] tokens, drop a small closed
  function-word list, and fold one trailing "s" off longer words
  (makes->make, mistakes->mistake) so listicle paraphrases collide.
  Numbers stay in (5 vs 7 mistakes is a real difference). No general
  stemming: story/stories stay distinct, which keeps the detector
  conservative (fewer false positives).
- similarity: |A∩B| / |A∪B| on the normalized token sets. Two topics
  are duplicates at >= threshold (default 0.6).
- filter_duplicates(): first occurrence wins. Each candidate is
  compared against the existing corpus AND previously accepted
  candidates, so a batch cannot repeat itself either.
"""

from __future__ import annotations

import re

# Function words only. Removing content words (mistakes, history,
# science...) would merge genuinely different angles.
_STOPWORDS = frozenset(
    """
    the a an and or but of to in on for with about into over under after
    before is are was were be been being am do does did doing can could
    should would will shall may might must have has had having i you your
    yours we our ours they their them he she his her it its this that
    these those there here what which who whom when where why how not no
    nor so if then than as at by from up down out off very too also just
    s t don now
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> frozenset[str]:
    """Content tokens of a title/topic, lowercased, stopwords removed,
    one trailing "s" folded off words longer than 4 letters."""

    def _fold(tok: str) -> str:
        if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
            return tok[:-1]
        return tok

    return frozenset(
        _fold(tok)
        for tok in _TOKEN_RE.findall(text.lower())
        if tok not in _STOPWORDS
    )


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity of two token sets (0.0 for two empty sets)."""
    if not a and not b:
        return 1.0  # two empty topics say the same thing (nothing)
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def is_duplicate(
    candidate: str, existing: frozenset[str], *, threshold: float = 0.6
) -> bool:
    """True when candidate topics overlap an existing token set."""
    return jaccard(normalize(candidate), existing) >= threshold


def filter_duplicates(
    candidates: list[str],
    existing: list[str] | None = None,
    *,
    threshold: float = 0.6,
) -> list[bool]:
    """Per-candidate duplicate flags; True = skip this candidate.

    Order matters: the first occurrence of a near-duplicate group is
    accepted, later ones are flagged. Candidates are also checked
    against previously accepted candidates in the same batch.
    """
    seen: list[frozenset[str]] = [normalize(e) for e in (existing or [])]
    flags: list[bool] = []
    for text in candidates:
        tokens = normalize(text)
        dup = any(jaccard(tokens, s) >= threshold for s in seen)
        flags.append(dup)
        if not dup:
            seen.append(tokens)
    return flags
