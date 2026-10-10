
from __future__ import annotations

from typing import Any


# -- Debate role prompts (multi-perspective generation) -------------------

DEBATE_ROLES_HYPOTHESIS: dict[str, dict[str, str]] = {
    "innovator": {
        "system": (
            "You are a bold, creative researcher who thinks outside the box. "
            "You pursue high-risk high-reward ideas, draw cross-domain analogies, "
            "and propose counter-intuitive hypotheses that challenge mainstream thinking."
        ),
        "user": (
            "Generate at least 2 novel, unconventional hypotheses from the synthesis below.\n"
            "CRITICAL REQUIREMENTS for EVERY hypothesis:\n"
            "1. NOVELTY: Must go beyond incremental combination of existing methods.\n"
            "2. FEASIBILITY: Must be testable within 30 minutes of compute on a single GPU.\n"
            "3. FALSIFIABILITY: Must define a specific metric threshold that would reject it.\n"
            "For each hypothesis provide:\n"
            "- A bold claim that pushes boundaries\n"
            "- Cross-domain inspiration (if applicable)\n"
            "- Rationale grounded in the literature gaps\n"
            "- Measurable prediction and failure condition\n"
            "- Estimated risk level (low/medium/high)\n\n"
            "Topic: {topic}\n"
            "Synthesis:\n{synthesis}"
        ),
    },
    "pragmatist": {
        "system": (
            "You are a practical ML engineer focused on what actually works. "
            "You prioritize computational feasibility, engineering simplicity, "
            "reliable baselines, and incremental but solid improvements."
        ),
        "user": (
            "Generate at least 2 feasible, well-grounded hypotheses from the synthesis below.\n"
            "For each hypothesis provide:\n"
            "- A concrete, testable claim with clear methodology\n"
            "- Why this is achievable with limited compute\n"
            "- Rationale based on proven techniques\n"
            "- Measurable prediction and failure condition\n"
            "- Resource requirements estimate\n\n"
            "Topic: {topic}\n"
            "Synthesis:\n{synthesis}"
        ),
    },
    "contrarian": {
        "system": (
            "You are a rigorous devil's advocate who challenges assumptions. "
            "You find blind spots, hidden failure modes, and counter-evidence. "
            "Your value is in finding problems others ignore. Be provocative "
            "but always grounded in evidence."
        ),
        "user": (
            "Critically examine the synthesis and generate at least 2 contrarian hypotheses.\n"
            "For each hypothesis provide:\n"
            "- A challenge to a widely-held assumption in this area\n"
            "- Evidence or reasoning for why the mainstream view may be wrong\n"
            "- An alternative hypothesis that accounts for overlooked factors\n"
            "- Measurable prediction and failure condition\n"
            "- Potential negative results that would be informative\n\n"
            "Topic: {topic}\n"
            "Synthesis:\n{synthesis}"
        ),
    },
}


# Module-level alias retained for backward compatibility with call sites that
# imported ``_DEFAULT_STAGES`` directly (tests / templates / etc.).
# -- Stage prompts (one entry per LLM-calling stage) ---------------------

_DEFAULT_STAGES: dict[str, dict[str, Any]] = {
    # ── Phase A: Research Scoping ────────────────────────────────────────
    "topic_init": {
        "system": (
            "You are a rigorous research planner who identifies NOVEL, TIMELY "
            "research angles. You follow recent trends from top venues in the "
            "relevant domain and propose research that advances "
            "the frontier rather than repeating known results.\n\n"
            "NOVELTY PRINCIPLES:\n"
            "- A good research angle addresses a GAP not yet covered by existing work.\n"
            "- Avoid pure benchmark/comparison studies unless the methodology is novel.\n"
            "- Prefer angles that combine existing techniques in new ways, apply methods "
            "to underexplored domains, or challenge common assumptions.\n"
            "- The research must be FEASIBLE with limited compute (single GPU, hours not days).\n"
            "- Check: would a reviewer say 'this is already well-known'? If so, find a sharper angle."
        ),
        "user": (
            "Create a SMART research goal in markdown.\n"
            "Topic: {topic}\n"
            "Domains: {domains}\n"
            "Project: {project_name}\n"
            "Quality threshold: {quality_threshold}\n\n"
            "Required sections:\n"
            "- **Topic**: The broad area\n"
            "- **Novel Angle**: What specific aspect has NOT been well-studied? "
            "Why is this timely? What recent development creates "
            "an opportunity? How does this differ from standard approaches?\n"
            "- **Scope**: Focused enough for a single paper\n"
            "- **SMART Goal**: Specific, Measurable, Achievable, Relevant, Time-bound\n"
            "- **Constraints**: Compute budget, available tools, data access\n"
            "- **Success Criteria**: What results would make this publishable?\n"
            "- **Generated**: Timestamp\n\n"
            "IMPORTANT: The 'Novel Angle' section must convincingly argue why this "
            "specific research direction is NOT already covered by existing work. "
            "If the topic is well-studied (e.g., 'comparing optimizers'), you MUST "
            "find a specific unexplored aspect (e.g., 'under distribution shift with "
            "noisy gradients', 'in the few-shot regime', 'with modern architectures').\n\n"
            "TREND VALIDATION (MANDATORY):\n"
            "- Describe the research trend or gap that motivates this work. "
            "Do NOT fabricate specific paper titles or citations — actual papers "
            "will be retrieved in the literature search stage.\n"
            "- Name the specific benchmark/dataset that will be used for evaluation.\n"
            "- If no standard benchmark exists, explain how results will be measured.\n"
            "- Note whether SOTA results are commonly tracked on this benchmark "
            "(do NOT state specific model names or performance numbers — these "
            "will be verified in the literature search stage).\n"
            "- Add a 'Benchmark' subsection listing: name, source, and typical "
            "metrics — omit unverified performance numbers."
        ),
    },
    "problem_decompose": {
        "system": "You are a senior research strategist.",
        "user": (
            "Decompose this research problem into at least 4 prioritized "
            "sub-questions.\n"
            "Topic: {topic}\n"
            "Output markdown with sections: Source, Sub-questions, Priority "
            "Ranking, Risks.\n"
            "Goal context:\n{goal_text}"
        ),
    },
    # ── Phase B: Literature Discovery ────────────────────────────────────
    "search_strategy": {
        "system": (
            "You design literature retrieval strategies and source verification plans."
        ),
        "user": (
            "Create a merged search strategy package.\n"
            "Return a JSON object with keys: search_plan_yaml, sources.\n"
            "\n"
            "search_plan_yaml MUST be valid YAML text that INCLUDES this "
            "required query block (additional non-query metadata fields are "
            "allowed alongside it):\n"
            "\n"
            "  topic: <YOUR_TOPIC>\n"
            "  search_strategies:\n"
            "    - name: <CATEGORY_LABEL_1>\n"
            "      queries:\n"
            "        - <SHORT_QUERY_1>\n"
            "        - <SHORT_QUERY_2>\n"
            "    - name: <CATEGORY_LABEL_2>\n"
            "      queries:\n"
            "        - <SHORT_QUERY_3>\n"
            "        - <SHORT_QUERY_4>\n"
            "\n"
            "Requirements:\n"
            "- At least 3 strategies. Each strategy MUST have 3-5 queries.\n"
            "- At least 8 total queries across all strategies.\n"
            "- Each query MUST be a plain string of 3-6 words.\n"
            "- Cover: core topic, related methods, benchmarks/datasets, "
            "theoretical foundations, applications.\n"
            "- Additional fields such as `filters`, `sources`, "
            "`max_results_per_query`, `deduplication`, `date_window`, or "
            "per-strategy metadata may appear alongside the required block.\n"
            "\n"
            "STRICT — all actual search queries MUST live only under "
            "`search_strategies[].queries`. Do NOT place queries elsewhere:\n"
            "- Do NOT use `query_strategies`, `sub_question_map`, "
            "`sub_questions`, or a top-level `queries:` list.\n"
            "- Do NOT use `keyword_groups`, `boolean_seeds`, `keywords`, "
            "`seeds`, or `search_terms` as the query list.\n"
            "- Each query MUST be a plain string, not a dict like "
            "`{id: Q1, string: ...}`.\n"
            "\n"
            "sources must include id,name,type,url,status,query,verified_at.\n"
            "Topic: {topic}\n"
            "Problem tree:\n{problem_tree}"
        ),
        "json_mode": True,
    },
    "literature_collect": {
        "system": "You are a literature mining assistant.",
        "user": (
            "Generate candidate papers from the search plan.\n"
            "Return JSON: {candidates:[...]} with >=8 rows.\n"
            "Each candidate must include id,title,source,url,year,abstract,"
            "collected_at.\n"
            "Topic: {topic}\n"
            "Search plan:\n{plan_text}"
        ),
        "json_mode": True,
    },
    "literature_screen": {
        "system": (
            "You are a strict domain-aware reviewer with zero tolerance for "
            "cross-domain false positives. You MUST reject papers that are "
            "from unrelated fields, even if they share superficial keyword "
            "overlap. A paper about 'normalization in database systems' is "
            "NOT relevant to 'normalization in deep learning'. A paper about "
            "'graph theory in social networks' is NOT relevant to 'graph "
            "neural networks for molecular property prediction'."
        ),
        "user": (
            "Perform merged relevance+quality screening and return shortlist.\n"
            "Return JSON: {shortlist:[...]} each with title, cite_key "
            "(if present), relevance_score (0-1), quality_score (0-1), "
            "keep_reason.\n"
            "Preserve all original fields (paper_id, doi, arxiv_id, cite_key, "
            "etc.) from the input.\n"
            "Topic: {topic}\n"
            "Domains: {domains}\n"
            "Threshold: {quality_threshold}\n\n"
            "SCREENING RULES (apply strictly):\n"
            "1. DOMAIN MATCH: The paper's actual research domain must match "
            "the topic's domain. Shared keywords across domains do NOT count.\n"
            "2. METHOD RELEVANCE: The paper must discuss methods, benchmarks, "
            "or findings directly applicable to the research topic.\n"
            "3. CROSS-DOMAIN REJECTION: Reject papers from unrelated fields "
            "(e.g., wireless communications, database systems, social science) "
            "even if they use similar terminology.\n"
            "4. RECENCY PREFERENCE: Prefer papers from 2020+ for methodology, "
            "but accept foundational papers (pre-2020) if they introduced key "
            "techniques still in use today.\n"
            "5. SEMINAL PAPERS: Papers marked as source='seminal_library' are "
            "pre-vetted foundational references — keep them if their keywords "
            "match the topic (relevance_score >= 0.7).\n"
            "6. QUALITY FLOOR: Reject papers with no abstract, no venue, and "
            "no citation count (likely not real papers).\n"
            "Candidates JSONL:\n{candidates_text}"
        ),
        "json_mode": True,
    },
    "knowledge_extract": {
        "system": "You extract high-signal evidence cards from papers.",
        "user": (
            "Extract structured knowledge cards from shortlist.\n"
            "Return JSON: {cards:[{card_id,title,cite_key,problem,method,"
            "data,metrics,findings,limitations,citation}]}.\n"
            "IMPORTANT: If the input contains cite_key fields, preserve them "
            "exactly in the output.\n"
            "Shortlist:\n{shortlist}"
        ),
        "json_mode": True,
    },
    # ── Phase C: Knowledge Synthesis ─────────────────────────────────────
    "synthesis": {
        "system": "You are a synthesis specialist for literature reviews.",
        "user": (
            "Produce merged synthesis output (topic clusters + research gaps).\n"
            "Output markdown with sections: Cluster Overview, Cluster 1..N, "
            "Gap 1..N, Prioritized Opportunities.\n"
            "Topic: {topic}\n"
            "{domain_context}"
            "Cards context:\n{cards_context}"
        ),
        "max_tokens": 8192,
    },
    "hypothesis_gen": {
        "system": (
            "You formulate testable scientific hypotheses that address gaps "
            "NOT covered by existing literature. Your hypotheses must be:\n"
            "1. NOVEL: Not simply replicating known results or testing obvious things.\n"
            "2. GAP-FILLING: Address specific weaknesses or blind spots identified "
            "in the literature synthesis.\n"
            "3. FEASIBLE: Testable within the constraints of this research domain.\n"
            "{feasibility_constraint}"
            "4. FALSIFIABLE: Have clear failure conditions that would definitively "
            "reject the hypothesis.\n"
            "5. SURPRISING: At least one hypothesis should challenge conventional "
            "wisdom or test a counter-intuitive prediction."
        ),
        "user": (
            "Generate at least 2 falsifiable hypotheses from the synthesis below.\n"
            "For each hypothesis provide:\n"
            "- **Hypothesis statement**: A clear, testable claim\n"
            "- **Novelty argument**: Why this has NOT been tested before, citing "
            "specific gaps from the synthesis\n"
            "- **Rationale**: Theoretical or empirical basis for expecting this result\n"
            "- **Measurable prediction**: Specific quantitative outcome expected\n"
            "- **Failure condition**: What result would reject this hypothesis?\n"
            "- **Required baselines**: What modern, state-of-the-art methods must be "
            "compared against to make the finding meaningful?\n\n"
            "AVOID:\n"
            "- Hypotheses that are trivially obvious\n"
            "- Hypotheses that replicate well-known results already in the literature\n"
            "- Hypotheses that cannot be tested within the domain's feasibility constraints\n\n"
            "{domain_context}"
            "Synthesis:\n{synthesis}"
        ),
    },
    # ── Phase D: Experiment Design ───────────────────────────────────────
    # ── Phase F: Analysis & Decision ─────────────────────────────────────
    # ── Phase G: Paper Writing ───────────────────────────────────────────
    # ── Phase H: Finalization ────────────────────────────────────────────
}

# Public name — prefer ``STAGES`` in new code.
STAGES: dict[str, dict[str, Any]] = _DEFAULT_STAGES
