
from __future__ import annotations

from researchclaw.prompts.manager import (
    PromptManager,
    RenderedPrompt,
    SUPPORTED_DOMAINS,
    _render,
)
from researchclaw.prompts.shared import (
    _DEFAULT_BLOCKS,
    _DEFAULT_SUB_PROMPTS,
)

# Legacy ML constants — re-exported so existing call sites keep working.
from researchclaw.prompts.ml import (
    DEBATE_ROLES_HYPOTHESIS,
    STAGES as _DEFAULT_STAGES,
)

__all__ = [
    "PromptManager",
    "RenderedPrompt",
    "SUPPORTED_DOMAINS",
    "_render",
    "_DEFAULT_BLOCKS",
    "_DEFAULT_SUB_PROMPTS",
    "_DEFAULT_STAGES",
    "DEBATE_ROLES_HYPOTHESIS",
]
