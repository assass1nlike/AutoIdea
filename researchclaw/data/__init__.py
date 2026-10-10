"""Static data assets for the ResearchClaw pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Framework documentation
# ---------------------------------------------------------------------------


# Map of framework identifier -> (doc filename, keyword patterns for detection)


_SEMINAL_PAPERS_PATH = Path(__file__).parent / "seminal_papers.yaml"
_CACHE: list[dict[str, Any]] | None = None


def _load_all() -> list[dict[str, Any]]:
    """Load and cache the seminal papers list."""
    global _CACHE  # noqa: PLW0603
    if _CACHE is not None:
        return _CACHE
    try:
        data = yaml.safe_load(_SEMINAL_PAPERS_PATH.read_text(encoding="utf-8"))
        _CACHE = data.get("papers", []) if isinstance(data, dict) else []
    except Exception:  # noqa: BLE001
        logger.warning("Failed to load seminal_papers.yaml", exc_info=True)
        _CACHE = []
    return _CACHE


def load_seminal_papers(topic: str) -> list[dict[str, Any]]:
    """Return seminal papers whose keywords overlap with *topic*.

    Each returned dict has: title, authors, year, venue, cite_key, keywords.
    Matching is case-insensitive substring on the topic string.
    """
    all_papers = _load_all()
    topic_lower = topic.lower()
    matched: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for paper in all_papers:
        keywords = paper.get("keywords", [])
        if not isinstance(keywords, list):
            continue
        for kw in keywords:
            if isinstance(kw, str) and kw.lower() in topic_lower:
                ck = paper.get("cite_key", "")
                if ck not in seen_keys:
                    seen_keys.add(ck)
                    matched.append(paper)
                break

    logger.debug(
        "load_seminal_papers(%r): matched %d papers", topic, len(matched)
    )
    return matched
