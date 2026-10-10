"""Maps AutoResearchClaw pipeline stages to MetaClaw skill categories.

Each stage maps to:
- task_type: MetaClaw's task category for skill retrieval
- skills: Preferred research-specific skills to inject
- top_k: Number of skills to inject at this stage
"""

from __future__ import annotations

from typing import Any

STAGE_SKILL_MAP: dict[str, dict[str, Any]] = {
    "topic_init": {
        "task_type": "research",
        "skills": ["literature-search-strategy"],
        "top_k": 4,
    },
    "problem_decompose": {
        "task_type": "research",
        "skills": ["research-gap-identification"],
        "top_k": 4,
    },
    "search_strategy": {
        "task_type": "research",
        "skills": ["literature-search-strategy"],
        "top_k": 6,
    },
    "literature_collect": {
        "task_type": "research",
        "skills": ["literature-search-strategy"],
        "top_k": 4,
    },
    "literature_screen": {
        "task_type": "research",
        "skills": ["paper-relevance-screening"],
        "top_k": 6,
    },
    "knowledge_extract": {
        "task_type": "research",
        "skills": ["knowledge-card-extraction"],
        "top_k": 4,
    },
    "synthesis": {
        "task_type": "research",
        "skills": ["research-gap-identification"],
        "top_k": 6,
    },
    "hypothesis_gen": {
        "task_type": "research",
        "skills": ["hypothesis-formulation"],
        "top_k": 6,
    },
}

# Mapping from AutoResearchClaw lesson categories to skill categories.
# Uses the new taxonomy: writing, domain, experiment, tooling.
LESSON_CATEGORY_TO_SKILL_CATEGORY: dict[str, str] = {
    "system": "tooling",
    "experiment": "experiment",
    "writing": "writing",
    "analysis": "experiment",
    "literature": "experiment",
    "pipeline": "tooling",
}


def get_stage_config(stage_name: str) -> dict[str, Any]:
    """Return the MetaClaw skill config for a given pipeline stage.

    Falls back to a generic research config if the stage is unknown.
    """
    return STAGE_SKILL_MAP.get(
        stage_name,
        {"task_type": "research", "skills": [], "top_k": 4},
    )
