"""Shared constants, data classes, and utility functions for the pipeline executor."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


from researchclaw.llm.client import LLMClient
from researchclaw.pipeline.stages import (
    NEXT_STAGE,
    Stage,
    StageStatus,
)
from researchclaw.prompts import PromptManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageResult:
    """Outcome of executing a single stage."""

    stage: Stage
    status: StageStatus
    artifacts: tuple[str, ...]
    error: str | None = None
    decision: str = "proceed"
    evidence_refs: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_METACLAW_SKILLS_DIR = str(Path.home() / ".metaclaw" / "skills")

# User-level custom skills directory (cross-project)
_USER_SKILLS_DIR = Path.home() / ".researchclaw" / "skills"

# Lazy-initialized skill registry (singleton for the process)
_skill_registry: object | None = None


def _get_skill_registry(config: object | None = None) -> object:
    """Return the global SkillRegistry, creating it on first call.

    Loads skills from (in priority order):
    1. Built-in skills shipped with the package
    2. User-level ``~/.researchclaw/skills/``
    3. Project-level ``.claude/skills/``
    4. MetaClaw cross-run skills ``~/.metaclaw/skills/``
    5. User-configured ``config.yaml → skills.custom_dirs``
    """
    global _skill_registry  # noqa: PLW0603
    if _skill_registry is not None:
        return _skill_registry
    try:
        from researchclaw.skills.registry import SkillRegistry

        custom_dirs: list[str] = []

        # User-level skills
        if _USER_SKILLS_DIR.is_dir():
            custom_dirs.append(str(_USER_SKILLS_DIR))

        # Project-level .claude/skills/
        project_skills = Path(__file__).resolve().parent.parent.parent / ".claude" / "skills"
        if project_skills.is_dir():
            custom_dirs.append(str(project_skills))

        # MetaClaw skills
        metaclaw = Path(_METACLAW_SKILLS_DIR)
        if metaclaw.is_dir():
            custom_dirs.append(str(metaclaw))

        # Config-specified custom dirs
        if config is not None:
            skills_cfg = getattr(config, "skills", None)
            if skills_cfg:
                for d in getattr(skills_cfg, "custom_dirs", ()):
                    if d:
                        custom_dirs.append(str(d))
                for d in getattr(skills_cfg, "external_dirs", ()):
                    if d:
                        custom_dirs.append(str(d))

        _skill_registry = SkillRegistry(
            custom_dirs=custom_dirs,
            auto_match=True,
            max_skills_per_stage=getattr(
                getattr(config, "skills", None), "max_skills_per_stage", 3
            ) if config else 3,
            fallback_matching=True,
        )
        logger.info(
            "Skill registry initialized: %d skills from %d sources",
            _skill_registry.count(),
            1 + len(custom_dirs),
        )
    except Exception:  # noqa: BLE001
        # Fallback: create empty registry so we never crash
        from researchclaw.skills.registry import SkillRegistry
        _skill_registry = SkillRegistry(builtin_dir="/dev/null")
        logger.debug("Skill registry init failed, using empty registry")
    return _skill_registry

# --- P1-1: Topic keyword extraction for domain pre-filter ---
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "of",
        "for",
        "to",
        "with",
        "by",
        "at",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "not",
        "no",
        "nor",
        "so",
        "yet",
        "both",
        "each",
        "every",
        "all",
        "any",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "than",
        "too",
        "very",
        "just",
        "about",
        "above",
        "after",
        "again",
        "between",
        "into",
        "through",
        "during",
        "before",
        "after",
        "under",
        "over",
        "using",
        "based",
        "via",
        "toward",
        "towards",
        "new",
        "novel",
        "approach",
        "method",
        "study",
        "research",
        "paper",
        "work",
        "propose",
        "proposed",
    }
)

# ---------------------------------------------------------------------------
# Timestamp utility
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Fallback query builder
# ---------------------------------------------------------------------------


def _build_fallback_queries(topic: str) -> list[str]:
    """Extract meaningful search queries from a long topic string.

    Instead of using the raw topic as a query (which is often 200+ chars
    and returns garbage from search engines), extract noun phrases and
    domain keywords. Returns 5-10 targeted queries.
    """
    # Split on common delimiters and extract meaningful chunks
    chunks = re.split(r"[,:;()\[\]]+", topic)
    chunks = [c.strip() for c in chunks if len(c.strip()) > 8]
    cleaned_chunks = []
    for c in chunks:
        c = re.sub(
            r"^(and|or|the|a|an|in|of|for|with|across|multiple|three|various)\s+",
            "", c, flags=re.IGNORECASE,
        )
        c = c.strip()
        if len(c) > 8:
            cleaned_chunks.append(c)
    chunks = cleaned_chunks

    # Extract key terms (words that look like domain terms, not stopwords)
    _stop = {
        "the", "and", "for", "with", "from", "that", "this", "into",
        "over", "across", "multiple", "three", "result", "comprehensive",
        "using", "based", "between", "various", "different", "several",
        "parameter", "parameters", "analysis", "approach", "method",
        "framework", "frameworks",
    }
    words = topic.lower().split()
    key_terms = [w for w in words if len(w) > 3 and w not in _stop]

    queries: list[str] = []

    # Strategy 1: Use meaningful chunks (up to 60 chars each)
    for chunk in chunks[:4]:
        if len(chunk) > 60:
            chunk = " ".join(chunk.split()[:6])
        if chunk and chunk not in queries:
            queries.append(chunk)

    # Strategy 2: Bigrams of key terms
    clean_terms = [t for t in key_terms if re.match(r"^[a-z]", t) and ":" not in t]
    for i in range(min(len(clean_terms) - 1, 4)):
        bigram = f"{clean_terms[i]} {clean_terms[i + 1]}"
        if bigram not in queries:
            queries.append(bigram)

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        q_lower = q.strip().lower()
        if q_lower and q_lower not in seen:
            seen.add(q_lower)
            unique.append(q.strip())

    # Ensure we have at least a few useful queries
    topic_short = topic[:60].strip()
    for suffix in ("survey", "review", "benchmark", "state of the art", "recent advances"):
        if len(unique) >= 5:
            break
        candidate = f"{topic_short} {suffix}".strip()
        if candidate.lower() not in seen:
            seen.add(candidate.lower())
            unique.append(candidate)

    return unique[:10]


# ---------------------------------------------------------------------------
# Stage metadata I/O
# ---------------------------------------------------------------------------


def _write_stage_meta(
    stage_dir: Path, stage: Stage, run_id: str, result: "StageResult"
) -> None:
    if result.status is StageStatus.DONE:
        next_stage = NEXT_STAGE[stage]
    else:
        # Failed / paused / blocked stages should point back to themselves so
        # retry-resume tooling does not imply that the pipeline advanced.
        next_stage = stage
    meta = {
        "stage_id": f"{int(stage):02d}-{stage.name.lower()}",
        "run_id": run_id,
        "status": result.status.value,
        "decision": result.decision,
        "output_artifacts": list(result.artifacts),
        "evidence_refs": list(result.evidence_refs),
        "error": result.error,
        "ts": _utcnow_iso(),
        "next_stage": int(next_stage) if next_stage is not None else None,
    }
    (stage_dir / "decision.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Sandbox dependency helper
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Prior artifact I/O
# ---------------------------------------------------------------------------


def _read_prior_artifact(run_dir: Path, filename: str) -> str | None:
    # R14-2: Sort so non-versioned dirs (stage-13) come before versioned (stage-13_v1).
    # Within the same stage number, prefer the latest (non-versioned) copy.
    def _stage_sort_key(p: Path) -> tuple[str, int]:
        name = p.name
        # Extract base stage name and version
        if "_v" in name:
            base, _, ver = name.rpartition("_v")
            try:
                return (base, -int(ver))  # Versioned: lower priority (negative version)
            except ValueError:
                return (name, -999)
        return (name, 0)  # Non-versioned: highest priority

    for stage_subdir in sorted(run_dir.glob("stage-*"), key=_stage_sort_key, reverse=True):
        candidate = stage_subdir / filename
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as exc:
                logger.warning("Cannot read %s: %s — skipping", candidate, exc)
                continue
        if filename.endswith("/") and (stage_subdir / filename.rstrip("/")).is_dir():
            return str(stage_subdir / filename.rstrip("/"))
    return None


def _find_prior_file(run_dir: Path, filename: str) -> Path | None:
    """Like ``_read_prior_artifact`` but returns the *Path* instead of content."""
    def _stage_sort_key(p: Path) -> tuple[str, int]:
        name = p.name
        if "_v" in name:
            base, _, ver = name.rpartition("_v")
            try:
                return (base, -int(ver))
            except ValueError:
                return (name, -999)
        return (name, 0)

    for stage_subdir in sorted(run_dir.glob("stage-*"), key=_stage_sort_key, reverse=True):
        candidate = stage_subdir / filename
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Parsing utilities
# ---------------------------------------------------------------------------


def _extract_yaml_block(text: str) -> str:
    """Extract YAML from text that may contain ACP noise.

    Strips [thinking] blocks, insight blocks, and other ACP artifacts
    before looking for YAML in markdown fences or raw text.
    """
    # Strip ACP noise: [thinking]..., insight blocks, [plan]...
    cleaned = re.sub(
        r"\[thinking\].*?(?=\n```|\n[A-Z]|\Z)",
        "", text, flags=re.DOTALL,
    )
    cleaned = re.sub(r"\[plan\].*?\n\n", "", cleaned, flags=re.DOTALL)

    # Try markdown fences first (most reliable) — on cleaned text
    if "```yaml" in cleaned:
        return cleaned.split("```yaml", 1)[1].split("```", 1)[0].strip()
    if "```yml" in cleaned:
        return cleaned.split("```yml", 1)[1].split("```", 1)[0].strip()
    if "```" in cleaned:
        block = cleaned.split("```", 1)[1].split("```", 1)[0].strip()
        if block:
            return block

    # Try the original text too (in case cleaning removed too much)
    if "```yaml" in text:
        return text.split("```yaml", 1)[1].split("```", 1)[0].strip()
    if "```yml" in text:
        return text.split("```yml", 1)[1].split("```", 1)[0].strip()
    if "```" in text:
        block = text.split("```", 1)[1].split("```", 1)[0].strip()
        if block:
            return block

    # Last resort: try to find YAML-like content (lines starting with key:)
    yaml_lines: list[str] = []
    in_yaml = False
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not in_yaml and re.match(r"^[a-z_]+:", stripped):
            in_yaml = True
        if in_yaml:
            if stripped and not stripped.startswith("#"):
                yaml_lines.append(line)
            elif not stripped and yaml_lines:
                yaml_lines.append(line)
    if yaml_lines:
        return "\n".join(yaml_lines).strip()

    return text.strip()


def _safe_json_loads(text: str, default: Any) -> Any:
    """Parse JSON from text, handling noisy ACP output.

    Tries multiple strategies: direct parse, markdown fence extraction,
    balanced brace matching (largest dict wins), and array brackets.
    """
    if not text or not text.strip():
        return default

    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError, RecursionError):
        pass

    # Strategy 2: Find JSON in markdown code fences
    fence_pattern = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)
    for match in fence_pattern.finditer(text):
        candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue

    # Strategy 3: Find outermost balanced braces
    brace_depth = 0
    start = -1
    candidates: list[str] = []
    for i, ch in enumerate(text):
        if ch == "{":
            if brace_depth == 0:
                start = i
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
            if brace_depth == 0 and start >= 0:
                candidates.append(text[start : i + 1])
                start = -1

    # Try candidates from largest to smallest
    candidates.sort(key=len, reverse=True)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            continue

    # Strategy 4: Same for array [ ]
    bracket_depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "[":
            if bracket_depth == 0:
                start = i
            bracket_depth += 1
        elif ch == "]":
            bracket_depth -= 1
            if bracket_depth == 0 and start >= 0:
                try:
                    parsed = json.loads(text[start : i + 1])
                    if isinstance(parsed, list):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass
                start = -1

    return default


def _parse_jsonl_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = _safe_json_loads(line, {})
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


def _chat_with_prompt(
    llm: LLMClient,
    system: str,
    user: str,
    *,
    json_mode: bool = False,
    max_tokens: int | None = None,
    retries: int = 0,
    strip_thinking: bool = True,
) -> Any:
    """Send a chat request with optional retry on timeout/transient errors.

    Parameters
    ----------
    retries:
        Number of extra attempts after the first failure (0 = no retry).
        Uses exponential backoff: 2s, 4s, 8s, ...
    strip_thinking:
        If True (default for pipeline usage), strip ``<think>`` tags from
        the LLM response.  This prevents chain-of-thought leakage from
        breaking YAML / JSON / LaTeX parsers downstream.
    """
    import time

    messages = [{"role": "user", "content": user}]
    last_exc: Exception | None = None
    _effective_json_mode = json_mode
    for attempt in range(1 + retries):
        try:
            if _effective_json_mode and max_tokens is not None:
                return llm.chat(messages, system=system, json_mode=True, max_tokens=max_tokens, strip_thinking=strip_thinking)
            if _effective_json_mode:
                return llm.chat(messages, system=system, json_mode=True, strip_thinking=strip_thinking)
            if max_tokens is not None:
                return llm.chat(messages, system=system, max_tokens=max_tokens, strip_thinking=strip_thinking)
            return llm.chat(messages, system=system, strip_thinking=strip_thinking)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            # Auto-disable json_mode on HTTP 400 — likely provider incompatibility
            _err_str = str(exc)
            if _effective_json_mode and "400" in _err_str:
                logger.warning(
                    "HTTP 400 with json_mode=True — disabling json_mode for retry "
                    "(provider may not support response_format)."
                )
                _effective_json_mode = False
            if attempt < retries:
                delay = 2 ** (attempt + 1)
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s. Retrying in %ds...",
                    attempt + 1,
                    1 + retries,
                    exc,
                    delay,
                )
                time.sleep(delay)
            else:
                raise last_exc from None
    raise last_exc  # type: ignore[misc]  # unreachable but satisfies type checker


def _get_evolution_overlay(
    run_dir: Path | None,
    stage_name: str,
    *,
    config: object | None = None,
    topic: str = "",
) -> str:
    """Load evolution lessons + matched skills for prompt injection.

    Combines three sources:
    1. Intra-run lessons (from current run's evolution dir)
    2. Cross-run MetaClaw skills (from ~/.metaclaw/skills/)
    3. Matched skills from the SkillRegistry (builtin + user + external)

    The SkillRegistry automatically matches skills to the current stage
    using trigger keywords and stage applicability metadata.

    Returns empty string if no relevant lessons/skills exist or on any error.
    """
    parts: list[str] = []

    # --- Section 1: Evolution lessons + MetaClaw arc-* skills ---
    if run_dir is not None:
        try:
            from researchclaw.evolution import EvolutionStore

            store = EvolutionStore(run_dir / "evolution")
            evo_overlay = store.build_overlay(
                stage_name, max_lessons=5, skills_dir=_METACLAW_SKILLS_DIR
            )
            if evo_overlay:
                parts.append(evo_overlay)
        except Exception:  # noqa: BLE001
            pass

    # --- Section 2: Matched skills from SkillRegistry ---
    try:
        registry = _get_skill_registry(config)
        context = f"{stage_name} {topic}".strip()
        matched = registry.match(context, stage_name)
        if matched:
            skills_text = registry.export_for_prompt(matched, max_chars=4000)
            if skills_text:
                parts.append(f"\n## Matched Domain Skills\n{skills_text}")
    except Exception:  # noqa: BLE001
        pass

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Topic keywords and constraints
# ---------------------------------------------------------------------------


def _extract_topic_keywords(
    topic: str, domains: tuple[str, ...] | list[str] = ()
) -> list[str]:
    """Extract meaningful keywords from the research topic + domain list.

    Returns lowercased keyword list (2+ chars, no stop words).
    Used by the domain pre-filter to drop obviously irrelevant papers.
    """
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", topic.lower())
    keywords = [t for t in tokens if t not in _STOP_WORDS and len(t) >= 3]
    # Add domain names as keywords
    for d in domains:
        for part in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", d.lower()):
            if part not in _STOP_WORDS and len(part) >= 2:
                keywords.append(part)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return unique


# --- P1-2: Topic constraint block for paper generation stages ---


# ---------------------------------------------------------------------------
# Runtime issue detection
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# NeurIPS checklist
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Paper title extraction
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Framework diagram prompt
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Filename and data helpers
# ---------------------------------------------------------------------------


def _safe_filename(name: str) -> str:
    name = name.replace("/", "_").replace("\\", "_").replace("..", "_")
    name = re.sub(r"[^a-zA-Z0-9_\-.]", "_", name)
    return name[:100] or "unnamed"


# ---------------------------------------------------------------------------
# Default fallbacks
# ---------------------------------------------------------------------------


def _default_hypotheses(topic: str) -> str:
    return f"""# Hypotheses

## H1
Increasing protocol control for {topic} improves metric stability across random seeds.

## H2
Adding robustness-aware objectives for {topic} improves out-of-domain performance without major in-domain regression.

## H3
The combined approach outperforms either component under fixed compute budget.

## Generated
{_utcnow_iso()}
"""


# ---------------------------------------------------------------------------
# Multi-perspective generation
# ---------------------------------------------------------------------------


def _multi_perspective_generate(
    llm: LLMClient,
    roles: dict[str, dict[str, str]],
    variables: dict[str, str],
    perspectives_dir: Path,
) -> dict[str, str]:
    """Generate outputs from multiple debate perspectives.

    Each role has its own system/user prompt. Outputs are saved to
    *perspectives_dir* and returned as ``{role_name: response_text}``.
    """
    import os as _os  # noqa: PLC0415
    from researchclaw.prompts import _render  # noqa: PLC0415

    # Ablation hook: ARC_ABL_DISABLE_DEBATE=1 collapses the debate to a
    # single role so the multi-perspective synthesizer degenerates into a
    # plain prompt. Used by experiments/component_ablation only.
    if _os.environ.get("ARC_ABL_DISABLE_DEBATE", "").strip() == "1" and roles:
        first_key = next(iter(roles))
        roles = {first_key: roles[first_key]}
        logger.info("ARC_ABL_DISABLE_DEBATE=1 — debate collapsed to role %s", first_key)

    perspectives_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}
    for role_name, role_prompts in roles.items():
        try:
            system = _render(role_prompts["system"], variables)
            user = _render(role_prompts["user"], variables)
            resp = llm.chat(
                [{"role": "user", "content": user}],
                system=system,
            )
            results[role_name] = resp.content
            (perspectives_dir / f"{role_name}.md").write_text(
                resp.content, encoding="utf-8"
            )
            logger.info("Debate perspective '%s' generated (%d chars)", role_name, len(resp.content))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Debate perspective '%s' failed: %s", role_name, exc)
    if len(results) < 2:
        logger.error("Multi-perspective debate: only %d/%d roles succeeded", len(results), len(roles))
    return results


def _synthesize_perspectives(
    llm: LLMClient,
    perspectives: dict[str, str],
    sub_prompt_name: str,
    prompts: PromptManager,
) -> str:
    """Synthesize multiple perspective outputs into a unified result."""
    parts = []
    for role_name, text in perspectives.items():
        parts.append(f"### Perspective: {role_name}\n{text}")
    combined = "\n\n---\n\n".join(parts)
    sp = prompts.sub_prompt(sub_prompt_name, perspectives=combined)
    resp = llm.chat(
        [{"role": "user", "content": sp.user}],
        system=sp.system,
    )
    return resp.content
