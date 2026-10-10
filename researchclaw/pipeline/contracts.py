"""Stage I/O contracts for the 23-stage ResearchClaw pipeline.

Each StageContract declares:
  - input_files: artifacts this stage reads (produced by prior stages)
  - output_files: artifacts this stage must produce
  - dod: Definition of Done — human-readable acceptance criterion
  - error_code: unique error identifier for diagnostics
  - max_retries: how many times the stage may be retried on failure
"""

from __future__ import annotations

from dataclasses import dataclass

from researchclaw.pipeline.stages import Stage


@dataclass(frozen=True)
class StageContract:
    stage: Stage
    input_files: tuple[str, ...]
    output_files: tuple[str, ...]
    dod: str
    error_code: str
    max_retries: int = 1


CONTRACTS: dict[Stage, StageContract] = {
    # Phase A: Research Scoping
    Stage.TOPIC_INIT: StageContract(
        stage=Stage.TOPIC_INIT,
        input_files=(),
        output_files=("goal.md",),
        dod="SMART goal statement with topic, scope, and constraints",
        error_code="E01_INVALID_GOAL",
        max_retries=0,
    ),
    Stage.PROBLEM_DECOMPOSE: StageContract(
        stage=Stage.PROBLEM_DECOMPOSE,
        input_files=("goal.md",),
        output_files=("problem_tree.md",),
        dod=">=3 prioritized sub-questions identified",
        error_code="E02_DECOMP_FAIL",
    ),
    # Phase B: Literature Discovery
    Stage.SEARCH_STRATEGY: StageContract(
        stage=Stage.SEARCH_STRATEGY,
        input_files=("problem_tree.md",),
        output_files=("search_plan.yaml", "sources.json", "queries.json"),
        dod=">=2 search strategies defined with verified data sources",
        error_code="E03_STRATEGY_BAD",
    ),
    Stage.LITERATURE_COLLECT: StageContract(
        stage=Stage.LITERATURE_COLLECT,
        input_files=("search_plan.yaml",),
        output_files=("candidates.jsonl",),
        dod=">=N candidate papers collected from specified sources",
        error_code="E04_COLLECT_EMPTY",
        max_retries=2,
    ),
    Stage.LITERATURE_SCREEN: StageContract(
        stage=Stage.LITERATURE_SCREEN,
        input_files=("candidates.jsonl",),
        output_files=("shortlist.jsonl",),
        dod="Relevance + quality dual screening completed and approved",
        error_code="E05_GATE_REJECT",
        max_retries=0,
    ),
    Stage.KNOWLEDGE_EXTRACT: StageContract(
        stage=Stage.KNOWLEDGE_EXTRACT,
        input_files=("shortlist.jsonl",),
        output_files=("cards/",),
        dod="Structured knowledge card per shortlisted paper",
        error_code="E06_EXTRACT_FAIL",
    ),
    # Phase C: Knowledge Synthesis
    Stage.SYNTHESIS: StageContract(
        stage=Stage.SYNTHESIS,
        input_files=("cards/",),
        output_files=("synthesis.md",),
        dod="Topic clusters + >=2 research gaps identified",
        error_code="E07_SYNTHESIS_WEAK",
    ),
    Stage.HYPOTHESIS_GEN: StageContract(
        stage=Stage.HYPOTHESIS_GEN,
        input_files=("synthesis.md",),
        output_files=("hypotheses.md",),
        dod=">=2 falsifiable research hypotheses",
        error_code="E08_HYP_INVALID",
    ),
    # Phase D: Experiment Design
    # Phase E: Experiment Execution
    # Phase F: Analysis & Decision
    # Phase G: Paper Writing
    # Phase H: Finalization
}
