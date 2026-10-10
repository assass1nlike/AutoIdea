
from __future__ import annotations

from typing import Any

from researchclaw.prompts.ml import (
    DEBATE_ROLES_HYPOTHESIS as _ML_DEBATE_HYPOTHESIS,
    STAGES as _ML_STAGES,
)


# ---------------------------------------------------------------------------
# Stage bank — start from ML and overwrite five stages
# ---------------------------------------------------------------------------


STAGES: dict[str, dict[str, Any]] = {k: dict(v) for k, v in _ML_STAGES.items()}


# ── hypothesis_gen ─────────────────────────────────────────────────────────
# ML placeholders preserved: system uses {feasibility_constraint};
# user uses {domain_context} and {synthesis}.
STAGES["hypothesis_gen"] = {
    "system": (
        "You formulate testable hypotheses about metabolic phenotypes (gene "
        "essentiality, growth rate, flux distribution, by-product yield, "
        "phenotypic phase planes, knockout viability). Your hypotheses must be:\n"
        "1. NOVEL: Not simply re-deriving textbook FBA predictions for the "
        "wild-type strain — target a perturbation, condition, or mechanism that "
        "the cited literature has not pinned down.\n"
        "2. ORGANISM-SPECIFIC: Reference an exact genome-scale metabolic model "
        "(GEM) — e.g. *E. coli* iJO1366 / iML1515, *S. cerevisiae* iMM904 / "
        "Yeast8, *human* Recon3D — and state why that model is appropriate.\n"
        "3. FEASIBLE in-silico: Solvable as an LP / MILP within COBRApy "
        "(FBA / pFBA / FVA / single- or double-knockout / phase plane).\n"
        "{feasibility_constraint}"
        "4. FALSIFIABLE with a numeric threshold: e.g. \"growth rate ratio "
        "KO/WT < 0.05\", \"succinate yield > 0.6 mol/mol glucose\", "
        "\"FVA flux range > 5 mmol/gDW/h\".\n"
        "5. CONTRASTIVE: At least one hypothesis should challenge a canonical "
        "FBA prediction — e.g. predict a synthetically lethal pair the GEM "
        "currently misses, or a medium under which an essential gene becomes "
        "dispensable."
    ),
    "user": (
        "Generate at least 2 falsifiable metabolic-modelling hypotheses from "
        "the synthesis below. For EACH hypothesis provide:\n"
        "- **Hypothesis statement**: A clear, testable claim referencing a "
        "specific organism / GEM, a measurable observable (growth rate, flux, "
        "yield, essentiality), and a perturbation (gene KO, medium swap, "
        "exchange-bound change, double-KO).\n"
        "- **Novelty argument**: Why this prediction is not already in the "
        "synthesis literature — cite the specific gap.\n"
        "- **Rationale**: Stoichiometric / pathway / regulatory reasoning that "
        "motivates the prediction. Reference the relevant subsystem "
        "(e.g. central carbon metabolism, oxidative phosphorylation).\n"
        "- **Measurable prediction**: Numeric threshold with units "
        "(mmol/gDW/h for fluxes, 1/h for growth, dimensionless ratios).\n"
        "- **Failure condition**: What in-silico result rejects the hypothesis "
        "(e.g. KO ratio > 0.5, FVA range < 0.1).\n"
        "- **Required references / baselines**: Published GEM, experimental "
        "essentiality set (Keio / OGEE), 13C-MFA fluxes, Edwards-Palsson "
        "phase-plane data — whichever is needed to make the test meaningful.\n\n"
        "AVOID:\n"
        "- Hypotheses that simply restate the GEM's textbook biomass coefficient.\n"
        "- Hypotheses that depend on dynamic / kinetic modelling (FBA is "
        "steady-state by construction).\n"
        "- ML-style 'predict X with a neural network' — FBA is a linear "
        "program; learning is not the right tool here.\n\n"
        "{domain_context}"
        "Synthesis:\n{synthesis}"
    ),
}


# ── experiment_design ──────────────────────────────────────────────────────
# Preserves ML placeholders: {preamble}, {domain_design_context},
# {metric_key}, {metric_direction}, {dataset_guidance},
# {hardware_profile}, {time_budget_sec}, {per_condition_budget_sec},
# {available_tier1_datasets}, {hypotheses}.


# ── code_generation ────────────────────────────────────────────────────────
# Preserves ML placeholders: {topic}, {metric}, {pkg_hint},
# {metric_direction_hint}, {time_budget}, {exp_plan}.


# ── result_analysis ────────────────────────────────────────────────────────
# Preserves ML placeholders: {preamble}, {data_context}, {context}.


# ── paper_outline ──────────────────────────────────────────────────────────
# Preserves ML placeholders: system uses {venue_guidance}; user uses
# {preamble}, {academic_style_guide}, {topic_constraint}, {feedback},
# {analysis}, {decision}.


# ---------------------------------------------------------------------------
# Debate roles — biology vocabulary
# ---------------------------------------------------------------------------


DEBATE_ROLES_HYPOTHESIS: dict[str, dict[str, str]] = {
    "model_builder": {
        "system": (
            "You are a genome-scale metabolic-model builder. You think in "
            "stoichiometric matrices, gene-protein-reaction (GPR) rules, "
            "biomass coefficients, and curated BIGG / BioModels GEMs. You "
            "champion hypotheses that exploit the structure of the "
            "metabolic network and that a published GEM can actually solve."
        ),
        "user": (
            "Propose hypotheses that lean on the strengths of the chosen "
            "GEM (clear GPR rules, well-curated subsystems). Identify "
            "reactions / genes / subsystems where the model is most likely "
            "to make a confident prediction."
        ),
    },
    "fba_analyst": {
        "system": (
            "You are an FBA / pFBA / FVA analyst. You insist on parsimonious "
            "flux distributions, explicit medium bounds, and FVA envelopes "
            "before drawing any conclusion. You favour hypotheses whose "
            "in-silico test is a single FBA / pFBA / FVA / knockout call."
        ),
        "user": (
            "Critique each candidate hypothesis on testability with the "
            "FBA / pFBA / FVA / sampling / knockout toolkit. Flag any that "
            "would require kinetic, regulatory, or dynamic modelling — those "
            "fall outside constraint-based scope."
        ),
    },
    "experimentalist": {
        "system": (
            "You are a wet-lab metabolic engineer. You ground every "
            "hypothesis in measurable phenotypes (growth rate, doubling "
            "time, by-product secretion, gene-essentiality calls from "
            "Keio / OGEE). You veto purely in-silico claims that have no "
            "experimental anchor."
        ),
        "user": (
            "For each hypothesis, ask: which lab measurement (growth rate, "
            "yield, gene-essentiality assay, ¹³C-MFA flux) would falsify it? "
            "If no realistic measurement exists, demote the hypothesis."
        ),
    },
}


# Sanity: silence unused-import warnings if the ML debate banks ever shrink.
_ = (_ML_DEBATE_HYPOTHESIS)
