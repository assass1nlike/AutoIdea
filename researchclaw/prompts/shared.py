
from __future__ import annotations

from typing import Any


# -- Canonical section word-count targets ----------------------------------
# Single source of truth for per-section word-count ranges.
# Used by executor._validate_draft_quality() and converter.check_paper_completeness().

# Aliases mapping heading variants to canonical names in SECTION_WORD_TARGETS.

# -- Reusable blocks -----------------------------------------------------

_DEFAULT_BLOCKS: dict[str, str] = {
}

# -- Sub-prompts (secondary LLM calls within a stage) --------------------

_DEFAULT_SUB_PROMPTS: dict[str, dict[str, Any]] = {
    "hypothesis_synthesize": {
        "system": (
            "You are a senior research director synthesizing multiple perspectives "
            "into a decisive research proposal. The best synthesis is not a "
            "compromise but takes the strongest elements from each viewpoint. "
            "Preserve genuine disagreements — do not flatten controversy."
        ),
        "user": (
            "Below are hypotheses generated from three different research perspectives.\n"
            "Synthesize them into a final set of 2-4 hypotheses that:\n"
            "1. Take the strongest, most novel ideas\n"
            "2. Address critical concerns raised by the contrarian\n"
            "3. Ensure feasibility (pragmatist's input)\n"
            "4. Note unresolved disagreements between perspectives\n"
            "5. For each final hypothesis: rationale, measurable prediction, "
            "failure condition\n\n"
            "{perspectives}"
        ),
    },
    "tournament_rank": {
        "system": (
            "You score and rank competing research artifacts, distinct from the "
            "authors. Score each candidate 1-10 on novelty, feasibility, and "
            "rigor, then pick the SINGLE best. Be decisive and critical — do not "
            "average or hedge."
        ),
        "user": (
            "Below are {n} candidate research artifacts. Score and rank them, "
            "then choose the best.\n"
            "Return ONLY JSON (no prose, no markdown fences):\n"
            '{"rankings": [{"id": <int>, "score": <1-10>, "reason": <str>}], '
            '"winner": <int>}\n\n'
            "{candidates}"
        ),
    },
    "debate_rebuttal": {
        "system": (
            "You are participating in a structured research debate as the "
            "{role} perspective. You have seen the other perspectives. Push back "
            "on their weak points, defend or REVISE your own position with "
            "evidence, and concede where they are right. Be rigorous, not "
            "stubborn."
        ),
        "user": (
            "Your previous position ({role}):\n{own_position}\n\n"
            "Other perspectives this round:\n{others}\n\n"
            "Write your rebuttal and updated position."
        ),
    },
}
