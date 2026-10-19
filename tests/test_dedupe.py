"""Duplicate detection: normalization, Jaccard, batch filtering, gate."""

from __future__ import annotations

from laf.dedupe import filter_duplicates, is_duplicate, jaccard, normalize
from laf.series import fallback_outline


def test_normalize_drops_function_words_keeps_content_and_numbers() -> None:
    assert normalize("The History of Sourdough") == frozenset({"history", "sourdough"})
    assert normalize("5 mistakes people make") >= frozenset({"5", "mistake"})


def test_identical_topics_score_one_disjoint_score_zero() -> None:
    a = normalize("sourdough starter smells like nail polish")
    b = normalize("Sourdough starter! Smells? Like... nail polish.")
    assert jaccard(a, b) == 1.0
    assert jaccard(a, normalize("quantum tunneling in semiconductors")) == 0.0


def test_reordered_or_recased_topic_is_a_duplicate() -> None:
    existing = normalize("history of sourdough bread")
    assert is_duplicate("The History of Sourdough Bread!", existing)
    assert not is_duplicate("sourdough bread storage mistakes", existing)


def test_filter_duplicates_flags_later_batch_members_only() -> None:
    flags = filter_duplicates(
        [
            "5 mistakes everyone makes with sourdough",
            "7 sourdough mistakes beginners make",  # related but distinct
            "5 MISTAKES people make with sourdough",  # dup of the first
        ]
    )
    assert flags == [False, False, True]


def test_filter_duplicates_checks_against_existing_corpus() -> None:
    flags = filter_duplicates(
        ["SOURDOUGH tools you need!"], existing=["the tools you need for sourdough"]
    )
    assert flags == [True]


def test_gate_20_episode_fallback_outline_passes_duplicate_detection() -> None:
    """Roadmap phase-4 gate, model-free: the deterministic 20-angle
    outline must survive dedupe against itself with zero skips."""
    ideas = fallback_outline("sourdough baking", 20)
    assert len(ideas) == 20
    flags = filter_duplicates([i["topic"] for i in ideas])
    assert not any(flags), [
        i["topic"] for i, dup in zip(ideas, flags) if dup
    ]
