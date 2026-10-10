"""ResearchClaw config loading and validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


CONFIG_SEARCH_ORDER: tuple[str, ...] = ("config.arc.yaml", "config.yaml")


def _safe_int(val: Any, default: int) -> int:
    """Convert value to int, handling None/null YAML values."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _safe_float(val: Any, default: float) -> float:
    """Convert value to float, handling None/null YAML values.

    BUG-DA8-11: Also rejects NaN/Inf which YAML can produce via .nan/.inf.
    """
    if val is None:
        return default
    try:
        import math

        result = float(val)
        if not math.isfinite(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


EXAMPLE_CONFIG = "config.researchclaw.example.yaml"


def resolve_config_path(explicit: str | None) -> Path | None:
    """Return first existing config from search order, or explicit path if given."""
    if explicit is not None:
        return Path(explicit)
    for name in CONFIG_SEARCH_ORDER:
        candidate = Path(name)
        if candidate.exists():
            return candidate
    return None


REQUIRED_FIELDS = (
    "project.name",
    "research.topic",
    "runtime.timezone",
    "notifications.channel",
    "knowledge_base.root",
    "llm.base_url",
    "llm.api_key_env",
)
KB_SUBDIRS = (
    "questions",
    "literature",
    "findings",
    "decisions",
)
PROJECT_MODES = {"docs-first", "semi-auto", "full-auto"}
KB_BACKENDS = {"markdown", "obsidian"}


def _get_by_path(data: dict[str, Any], dotted_key: str) -> Any:
    cur: Any = data
    for part in dotted_key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    mode: str = "docs-first"
    profile: str = ""  # empty = auto-detect; non-empty forces domain profile by id


@dataclass(frozen=True)
class ResearchConfig:
    topic: str
    domains: tuple[str, ...] = ()
    daily_paper_count: int = 0
    quality_threshold: float = 0.0


@dataclass(frozen=True)
class RuntimeConfig:
    timezone: str
    max_parallel_tasks: int = 1
    approval_timeout_hours: int = 12
    retry_limit: int = 0


@dataclass(frozen=True)
class NotificationsConfig:
    channel: str
    target: str = ""
    on_stage_start: bool = False
    on_stage_fail: bool = False
    on_gate_required: bool = True


@dataclass(frozen=True)
class KnowledgeBaseConfig:
    backend: str
    root: str
    obsidian_vault: str = ""


@dataclass(frozen=True)
class OpenClawBridgeConfig:
    use_cron: bool = False
    use_message: bool = False
    use_memory: bool = False
    use_sessions_spawn: bool = False
    use_web_fetch: bool = False
    use_browser: bool = False


@dataclass(frozen=True)
class AcpConfig:
    """ACP (Agent Client Protocol) settings."""

    agent: str = "claude"
    cwd: str = "."
    acpx_command: str = ""
    session_name: str = "researchclaw"
    timeout_sec: int = 1800
    max_turns: int = 1


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    base_url: str = ""
    proxy_url: str = ""
    wire_api: str = "chat_completions"
    stream: bool = False  # Chat Completions transport
    api_key_env: str = ""
    api_key: str = ""
    primary_model: str = ""
    reasoning_effort: str = ""
    fallback_models: tuple[str, ...] = ()
    s2_api_key: str = ""
    notes: str = ""
    timeout_sec: int = 600
    # Independent reviewer/judge model: breaks the generator == judge
    # self-preference in peer review and the quality gate.
    # Empty reviewer_model => reviewing/judging reuses the generator model
    # (backward-compatible). If only reviewer_model is set, the reviewer reuses
    # the main provider/base_url/key but with a different model. Set
    # reviewer_provider/base_url/api_key(_env) for a fully independent provider
    # (e.g. generator=GPT, reviewer=Claude).
    reviewer_model: str = ""
    reviewer_provider: str = ""
    reviewer_base_url: str = ""
    reviewer_api_key: str = ""
    reviewer_api_key_env: str = ""
    # Multi-model debate engine. Opt-in; the debate panel reuses existing models
    # (primary_model + reviewer_model + fallback_models, deduped), each role
    # bound to a different model. The judge reuses reviewer_model.
    debate_enabled: bool = False
    debate_rounds: int = 1
    # Best-of-N tournament selection. Opt-in; generate N diverse candidates
    # (round-robin over the debate panel when available), then an independent
    # judge (reviewer_model) scores/ranks and the single winner proceeds. Keeps
    # the pipeline linear (one canonical artifact per stage).
    # tournament_candidates < 2 disables the tournament.
    tournament_enabled: bool = False
    tournament_candidates: int = 3
    acp: AcpConfig = field(default_factory=AcpConfig)


@dataclass(frozen=True)
class LiteratureSearchConfig:
    """Configuration for Stage 4 academic literature search backends."""

    sources: tuple[str, ...] = ("openalex", "semantic_scholar", "arxiv")
    max_results_per_query: int = 40
    inter_query_delay_sec: float = 1.5
    openalex_email: str = "researchclaw@users.noreply.github.com"
    openalex_api_key: str = ""
    openalex_api_key_env: str = "OPENALEX_API_KEY"
    s2_api_key: str = ""
    s2_api_key_env: str = "S2_API_KEY"


@dataclass(frozen=True)
class SecurityConfig:
    hitl_required_stages: tuple[int, ...] = (5,)
    redact_sensitive_logs: bool = True


@dataclass(frozen=True)
class MetaClawPRMConfig:
    """PRM quality gate settings for MetaClaw bridge."""

    enabled: bool = False
    api_base: str = ""
    api_key_env: str = ""
    api_key: str = ""
    model: str = "gpt-5.4"
    votes: int = 3
    temperature: float = 0.6
    gate_stages: tuple[int, ...] = (5,)


@dataclass(frozen=True)
class MetaClawLessonToSkillConfig:
    """Settings for converting lessons into MetaClaw skills."""

    enabled: bool = True
    min_severity: str = "warning"
    max_skills_per_run: int = 3


@dataclass(frozen=True)
class MetaClawBridgeConfig:
    """MetaClaw integration bridge configuration."""

    enabled: bool = False
    proxy_url: str = "http://localhost:30000"
    skills_dir: str = "~/.metaclaw/skills"
    fallback_url: str = ""
    fallback_api_key: str = ""
    prm: MetaClawPRMConfig = field(default_factory=MetaClawPRMConfig)
    lesson_to_skill: MetaClawLessonToSkillConfig = field(
        default_factory=MetaClawLessonToSkillConfig
    )


@dataclass(frozen=True)
class WebSearchConfig:
    """Configuration for web search and crawling capabilities."""

    enabled: bool = True
    tavily_api_key: str = ""
    tavily_api_key_env: str = "TAVILY_API_KEY"
    enable_scholar: bool = True
    enable_crawling: bool = True
    enable_pdf_extraction: bool = True
    max_web_results: int = 10
    max_scholar_results: int = 10
    max_crawl_urls: int = 5


@dataclass(frozen=True)
class PromptsConfig:
    """Configuration for prompt externalization.

    ``custom_file`` points at a YAML that can override whole stage templates.
    ``extra_prompts`` maps ``stage_name -> path|inline`` and is appended to
    the user prompt of that stage at render time (alongside evolution-overlay
    memory). Values are treated as file paths when the path exists on disk,
    otherwise as inline text. Useful for domain hints that don't warrant a
    full template override — e.g. extra physics-specific guidance for
    ``synthesis`` or ``paper_draft`` in an HEP run.
    """

    custom_file: str = ""  # Path to custom prompts YAML (empty = use defaults)
    extra_prompts: tuple[tuple[str, str], ...] = ()  # (stage_name, path_or_text)


# ── Agent B: Intelligence & Memory configs ────────────────────────


@dataclass(frozen=True)
class SkillsConfig:
    """Configuration for the dynamic skills library."""

    enabled: bool = True
    builtin_dir: str = ""  # empty = use package default
    custom_dirs: tuple[str, ...] = ()
    external_dirs: tuple[str, ...] = ()
    auto_match: bool = True
    max_skills_per_stage: int = 3
    fallback_matching: bool = True


# ── Web platform configs (Agent A) ──────────────────────────────


# ── Agent C: Infrastructure configs ────────────────────────────────


@dataclass(frozen=True)
class RCConfig:
    project: ProjectConfig
    research: ResearchConfig
    runtime: RuntimeConfig
    notifications: NotificationsConfig
    knowledge_base: KnowledgeBaseConfig
    openclaw_bridge: OpenClawBridgeConfig
    llm: LlmConfig
    literature_search: LiteratureSearchConfig = field(
        default_factory=LiteratureSearchConfig
    )
    security: SecurityConfig = field(default_factory=SecurityConfig)
    prompts: PromptsConfig = field(default_factory=PromptsConfig)
    web_search: WebSearchConfig = field(default_factory=WebSearchConfig)
    metaclaw_bridge: MetaClawBridgeConfig = field(default_factory=MetaClawBridgeConfig)
    # Agent B: Intelligence & Memory
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    # Agent C: Infrastructure
    # Agent A: Web platform
    # Agent D: Research Enhancement
    # HITL Co-Pilot System
    hitl: object = field(default=None)  # HITLConfig (lazy import avoids circular dep)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        project_root: Path | None = None,
        check_paths: bool = True,
    ) -> RCConfig:
        result = validate_config(
            data, project_root=project_root, check_paths=check_paths
        )
        if not result.ok:
            raise ValueError("; ".join(result.errors))

        project = data["project"]
        research = data["research"]
        runtime = data["runtime"]
        notifications = data["notifications"]
        knowledge_base = data["knowledge_base"]
        bridge = data.get("openclaw_bridge") or {}
        llm = data["llm"]
        literature_search = data.get("literature_search") or {}
        security = data.get("security") or {}
        prompts = data.get("prompts") or {}
        web_search = data.get("web_search") or {}
        metaclaw = data.get("metaclaw_bridge") or {}
        skills_data = data.get("skills") or {}
        hitl_data = data.get("hitl") or {}

        return cls(
            project=ProjectConfig(
                name=project["name"],
                mode=project.get("mode", "docs-first"),
                profile=str(project.get("profile", "") or ""),
            ),
            research=ResearchConfig(
                topic=research["topic"],
                domains=tuple(research.get("domains") or ()),
                daily_paper_count=int(research.get("daily_paper_count", 0)),
                quality_threshold=float(research.get("quality_threshold", 0.0)),
            ),
            runtime=RuntimeConfig(
                timezone=runtime["timezone"],
                max_parallel_tasks=int(runtime.get("max_parallel_tasks", 1)),
                approval_timeout_hours=int(runtime.get("approval_timeout_hours", 12)),
                retry_limit=int(runtime.get("retry_limit", 0)),
            ),
            notifications=NotificationsConfig(
                channel=notifications["channel"],
                target=notifications.get("target", ""),
                on_stage_start=bool(notifications.get("on_stage_start", False)),
                on_stage_fail=bool(notifications.get("on_stage_fail", False)),
                on_gate_required=bool(notifications.get("on_gate_required", True)),
            ),
            knowledge_base=KnowledgeBaseConfig(
                backend=knowledge_base.get("backend", "markdown"),
                root=knowledge_base["root"],
                obsidian_vault=knowledge_base.get("obsidian_vault", ""),
            ),
            openclaw_bridge=OpenClawBridgeConfig(
                use_cron=bool(bridge.get("use_cron", False)),
                use_message=bool(bridge.get("use_message", False)),
                use_memory=bool(bridge.get("use_memory", False)),
                use_sessions_spawn=bool(bridge.get("use_sessions_spawn", False)),
                use_web_fetch=bool(bridge.get("use_web_fetch", False)),
                use_browser=bool(bridge.get("use_browser", False)),
            ),
            llm=_parse_llm_config(llm),
            literature_search=_parse_literature_search_config(literature_search),
            security=SecurityConfig(
                hitl_required_stages=tuple(
                    int(s) for s in security.get("hitl_required_stages", (5,))
                ),
                redact_sensitive_logs=bool(security.get("redact_sensitive_logs", True)),
            ),
            prompts=PromptsConfig(
                custom_file=prompts.get("custom_file", ""),
                extra_prompts=tuple(
                    (str(stage), str(value))
                    for stage, value in (prompts.get("extra_prompts") or {}).items()
                    if str(stage).strip() and str(value).strip()
                ),
            ),
            web_search=WebSearchConfig(
                enabled=bool(web_search.get("enabled", True)),
                tavily_api_key=str(web_search.get("tavily_api_key", "")),
                tavily_api_key_env=str(
                    web_search.get("tavily_api_key_env", "TAVILY_API_KEY")
                ),
                enable_scholar=bool(web_search.get("enable_scholar", True)),
                enable_crawling=bool(web_search.get("enable_crawling", True)),
                enable_pdf_extraction=bool(
                    web_search.get("enable_pdf_extraction", True)
                ),
                max_web_results=int(web_search.get("max_web_results", 10)),
                max_scholar_results=int(web_search.get("max_scholar_results", 10)),
                max_crawl_urls=int(web_search.get("max_crawl_urls", 5)),
            ),
            metaclaw_bridge=_parse_metaclaw_bridge_config(metaclaw),
            skills=_parse_skills_config(skills_data),
            hitl=_parse_hitl_config(hitl_data),
        )

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        project_root: str | Path | None = None,
        check_paths: bool = True,
        profile_override: str | None = None,
    ) -> RCConfig:
        config_path = Path(path).expanduser().resolve()
        with config_path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(
                f"Config root must be a mapping, got {type(data).__name__}. "
                f"Check that {config_path} is valid YAML."
            )

        # Profile-driven deployment: if a domain profile is named (via
        # ``project.profile:`` or --profile), let its deployment defaults fill
        # gaps in the config dict. The user's config.yaml always wins; the
        # profile only supplies keys the user left unset.
        profile_id = profile_override
        if not profile_id:
            proj_section = data.get("project") or {}
            if isinstance(proj_section, dict):
                profile_id = proj_section.get("profile") or None
        if profile_id:
            try:
                from researchclaw.domains.deploy import apply_profile_defaults

                data = apply_profile_defaults(data, str(profile_id).strip())
                project_section = data.get("project")
                if not isinstance(project_section, dict):
                    project_section = {}
                project_section["profile"] = str(profile_id).strip()
                data["project"] = project_section
            except FileNotFoundError as exc:
                import logging as _cfg_log

                _cfg_log.getLogger(__name__).warning(
                    "Profile '%s' not found — continuing without deployment defaults: %s",
                    profile_id,
                    exc,
                )

        resolved_root = (
            Path(project_root).expanduser().resolve()
            if project_root
            else config_path.parent
        )
        return cls.from_dict(data, project_root=resolved_root, check_paths=check_paths)


def validate_config(
    data: dict[str, Any],
    *,
    project_root: Path | None = None,
    check_paths: bool = True,
) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    llm_provider = _get_by_path(data, "llm.provider")
    for key in REQUIRED_FIELDS:
        # ACP and Ollama don't need api_key_env (local/keyless providers)
        if llm_provider in ("acp", "ollama") and key == "llm.api_key_env":
            continue
        if llm_provider == "acp" and key == "llm.base_url":
            continue
        value = _get_by_path(data, key)
        if _is_blank(value):
            errors.append(f"Missing required field: {key}")

    project_mode = _get_by_path(data, "project.mode")
    if not _is_blank(project_mode) and project_mode not in PROJECT_MODES:
        errors.append(f"Invalid project.mode: {project_mode}")

    kb_backend = _get_by_path(data, "knowledge_base.backend")
    if not _is_blank(kb_backend) and kb_backend not in KB_BACKENDS:
        errors.append(f"Invalid knowledge_base.backend: {kb_backend}")

    llm_wire_api = _get_by_path(data, "llm.wire_api")
    if not _is_blank(llm_wire_api) and llm_wire_api not in (
        "chat_completions",
        "responses",
    ):
        errors.append(f"Invalid llm.wire_api: {llm_wire_api}")

    reasoning_effort = _get_by_path(data, "llm.reasoning_effort")
    if reasoning_effort not in (
        None, "", "none", "minimal", "low", "medium", "high", "xhigh", "max"
    ):
        errors.append(f"Invalid llm.reasoning_effort: {reasoning_effort}")

    hitl_required_stages = _get_by_path(data, "security.hitl_required_stages")
    if hitl_required_stages is not None:
        if not isinstance(hitl_required_stages, list):
            errors.append("security.hitl_required_stages must be a list")
        else:
            for stage in hitl_required_stages:
                if not isinstance(stage, int) or not 1 <= stage <= 23:
                    errors.append(
                        f"Invalid security.hitl_required_stages entry: {stage}"
                    )

    kb_root_raw = _get_by_path(data, "knowledge_base.root")
    if check_paths and not _is_blank(kb_root_raw) and project_root is not None:
        kb_root = project_root / str(kb_root_raw)
        if not kb_root.exists():
            errors.append(f"Missing path: {kb_root}")
        else:
            for subdir in KB_SUBDIRS:
                candidate = kb_root / subdir
                if not candidate.exists():
                    warnings.append(f"Missing recommended kb subdir: {candidate}")

    return ValidationResult(
        ok=not errors, errors=tuple(errors), warnings=tuple(warnings)
    )


def _parse_llm_config(data: dict[str, Any]) -> LlmConfig:
    acp_data = data.get("acp") or {}
    return LlmConfig(
        provider=data.get("provider", "openai-compatible"),
        base_url=data.get("base_url", ""),
        proxy_url=data.get("proxy_url") or "",
        wire_api=data.get("wire_api", "chat_completions"),
        stream=bool(data.get("stream", False)),
        api_key_env=data.get("api_key_env", ""),
        api_key=data.get("api_key", ""),
        primary_model=data.get("primary_model", ""),
        reasoning_effort=data.get("reasoning_effort") or "",
        fallback_models=tuple(data.get("fallback_models") or ()),
        s2_api_key=data.get("s2_api_key", ""),
        notes=data.get("notes", ""),
        timeout_sec=_safe_int(data.get("timeout_sec"), 600),
        reviewer_model=data.get("reviewer_model", ""),
        reviewer_provider=data.get("reviewer_provider", ""),
        reviewer_base_url=data.get("reviewer_base_url", ""),
        reviewer_api_key=data.get("reviewer_api_key", ""),
        reviewer_api_key_env=data.get("reviewer_api_key_env", ""),
        debate_enabled=bool(data.get("debate_enabled", False)),
        debate_rounds=_safe_int(data.get("debate_rounds"), 1),
        tournament_enabled=bool(data.get("tournament_enabled", False)),
        tournament_candidates=_safe_int(data.get("tournament_candidates"), 3),
        acp=AcpConfig(
            agent=acp_data.get("agent", "claude"),
            cwd=acp_data.get("cwd", "."),
            acpx_command=acp_data.get("acpx_command", ""),
            session_name=acp_data.get("session_name", "researchclaw"),
            timeout_sec=int(acp_data.get("timeout_sec", 1800)),
            max_turns=_safe_int(acp_data.get("max_turns"), 1),
        ),
    )


def _parse_literature_search_config(data: dict[str, Any]) -> LiteratureSearchConfig:
    if not data:
        return LiteratureSearchConfig()

    sources_raw = data.get("sources", LiteratureSearchConfig.sources)
    if isinstance(sources_raw, str):
        sources = tuple(
            source.strip()
            for source in sources_raw.split(",")
            if source.strip()
        )
    else:
        sources = tuple(str(source) for source in (sources_raw or ()))
    if not sources:
        sources = LiteratureSearchConfig.sources

    return LiteratureSearchConfig(
        sources=sources,
        max_results_per_query=max(
            1,
            _safe_int(
                data.get("max_results_per_query"),
                LiteratureSearchConfig.max_results_per_query,
            ),
        ),
        inter_query_delay_sec=max(
            0.0,
            _safe_float(
                data.get("inter_query_delay_sec"),
                LiteratureSearchConfig.inter_query_delay_sec,
            ),
        ),
        openalex_email=str(
            data.get("openalex_email", LiteratureSearchConfig.openalex_email)
        ),
        openalex_api_key=str(data.get("openalex_api_key", "")),
        openalex_api_key_env=str(
            data.get(
                "openalex_api_key_env",
                LiteratureSearchConfig.openalex_api_key_env,
            )
        ),
        s2_api_key=str(data.get("s2_api_key", "")),
        s2_api_key_env=str(
            data.get("s2_api_key_env", LiteratureSearchConfig.s2_api_key_env)
        ),
    )


def _parse_metaclaw_bridge_config(data: dict[str, Any]) -> MetaClawBridgeConfig:
    prm_data = data.get("prm") or {}
    l2s_data = data.get("lesson_to_skill") or {}
    return MetaClawBridgeConfig(
        enabled=bool(data.get("enabled", False)),
        proxy_url=data.get("proxy_url", "http://localhost:30000"),
        skills_dir=data.get("skills_dir", "~/.metaclaw/skills"),
        fallback_url=data.get("fallback_url", ""),
        fallback_api_key=data.get("fallback_api_key", ""),
        prm=MetaClawPRMConfig(
            enabled=bool(prm_data.get("enabled", False)),
            api_base=prm_data.get("api_base", ""),
            api_key_env=prm_data.get("api_key_env", ""),
            api_key=prm_data.get("api_key", ""),
            model=prm_data.get("model", "gpt-5.4"),
            votes=_safe_int(prm_data.get("votes"), 3),
            temperature=_safe_float(prm_data.get("temperature"), 0.6),
            gate_stages=tuple(
                int(s) for s in prm_data.get("gate_stages", (5,))
            ),
        ),
        lesson_to_skill=MetaClawLessonToSkillConfig(
            enabled=bool(l2s_data.get("enabled", True)),
            min_severity=l2s_data.get("min_severity", "warning"),
            max_skills_per_run=_safe_int(l2s_data.get("max_skills_per_run"), 3),
        ),
    )


def _parse_skills_config(data: dict[str, Any]) -> SkillsConfig:
    if not data:
        return SkillsConfig()
    return SkillsConfig(
        enabled=bool(data.get("enabled", True)),
        builtin_dir=str(data.get("builtin_dir", "")),
        custom_dirs=tuple(str(d) for d in (data.get("custom_dirs") or ())),
        external_dirs=tuple(str(d) for d in (data.get("external_dirs") or ())),
        auto_match=bool(data.get("auto_match", True)),
        max_skills_per_stage=int(data.get("max_skills_per_stage", 3)),
        fallback_matching=bool(data.get("fallback_matching", True)),
    )


def _parse_hitl_config(data: dict[str, Any]) -> object:
    """Parse HITL config section. Returns HITLConfig or None."""
    if not data:
        return None
    try:
        from researchclaw.hitl.config import HITLConfig

        return HITLConfig.from_dict(data)
    except Exception:
        return None


def load_config(
    path: str | Path,
    *,
    project_root: str | Path | None = None,
    check_paths: bool = True,
    profile_override: str | None = None,
) -> RCConfig:
    return RCConfig.load(
        path,
        project_root=project_root,
        check_paths=check_paths,
        profile_override=profile_override,
    )
