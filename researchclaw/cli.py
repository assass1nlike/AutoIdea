"""ResearchClaw CLI — run the autonomous research pipeline."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping
from typing import cast

from researchclaw.adapters import AdapterBundle
from researchclaw.config import (
    CONFIG_SEARCH_ORDER,
    EXAMPLE_CONFIG,
    RCConfig,
    resolve_config_path,
)


# ---------------------------------------------------------------------------
# OpenCode installation helpers
# ---------------------------------------------------------------------------


def _resolve_config_or_exit(args: argparse.Namespace) -> Path | None:
    """Resolve config path from args, printing helpful errors on failure.

    Returns the resolved Path on success, or None if the config cannot be found
    (after printing an error message to stderr).
    """
    path = resolve_config_path(getattr(args, "config", None))
    if path is not None and not path.exists():
        print(f"Error: config file not found: {path}", file=sys.stderr)
        return None
    if path is None:
        search_list = ", ".join(CONFIG_SEARCH_ORDER)
        print(
            f"Error: no config file found (searched: {search_list}).\n"
            f"Run 'researchclaw init' to create one from the example template.",
            file=sys.stderr,
        )
        return None
    return path


def _generate_run_id(topic: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    topic_hash = hashlib.sha256(topic.encode()).hexdigest()[:6]
    return f"rc-{ts}-{topic_hash}"


def cmd_run(args: argparse.Namespace) -> int:
    resolved = _resolve_config_or_exit(args)
    if resolved is None:
        return 1
    config_path = resolved
    topic = cast(str | None, args.topic)
    output = cast(str | None, args.output)
    from_stage_name = cast(str | None, args.from_stage)
    to_stage_name = cast(str | None, getattr(args, "to_stage", None))
    auto_approve = cast(bool, args.auto_approve)
    skip_preflight = cast(bool, args.skip_preflight)
    resume = cast(bool, args.resume)
    hitl_mode = cast(str | None, getattr(args, "mode", None))

    kb_root_path = None
    profile_override = cast(str | None, getattr(args, "profile", None))
    config = RCConfig.load(
        config_path, check_paths=False, profile_override=profile_override
    )

    # If the user deployed a profile, force every detector call to agree
    # with it — otherwise Stage 10/18/22 may keyword-detect a different
    # domain from the topic and mix prompt styles.
    if config.project.profile:
        try:
            from researchclaw.domains.detector import set_forced_profile
            set_forced_profile(config.project.profile)
        except Exception:  # noqa: BLE001
            pass

    # Derive gate behavior from project.mode (CLI --auto-approve overrides)
    mode = config.project.mode.lower()
    if auto_approve:
        # Explicit CLI flag takes precedence over config mode
        stop_on_gate = False
    elif mode == "full-auto":
        auto_approve = True
        stop_on_gate = False
    else:
        # "semi-auto" and "docs-first" should block on gates
        stop_on_gate = True

    if topic:
        import dataclasses

        new_research = dataclasses.replace(config.research, topic=topic)
        config = dataclasses.replace(config, research=new_research)

    # --- LLM Preflight ---
    if not skip_preflight:
        from researchclaw.llm import create_llm_client

        client = create_llm_client(config)
        print("Preflight check...", end=" ", flush=True)
        ok, msg = client.preflight()
        if ok:
            print(msg)
        else:
            print(f"FAILED — {msg}", file=sys.stderr)
            return 1

    run_id = _generate_run_id(config.research.topic)
    run_dir = Path(output or f"artifacts/{run_id}")

    # BUG-119 / BUG-216: When --resume or --from-stage is used without
    # --output, search for the most recent existing run directory that
    # matches the topic.  Without this, --from-stage creates a new empty
    # directory that has no prior stage artifacts.
    if (resume or from_stage_name) and not output:
        topic_hash = hashlib.sha256(config.research.topic.encode()).hexdigest()[:6]
        artifacts_root = Path("artifacts")
        if artifacts_root.is_dir():
            candidates = sorted(
                (
                    d for d in artifacts_root.iterdir()
                    if d.is_dir()
                    and d.name.startswith("rc-")
                    and d.name.endswith(f"-{topic_hash}")
                    and (d / "checkpoint.json").exists()
                ),
                key=lambda d: d.name,
                reverse=True,  # newest first (timestamp in name)
            )
            if candidates:
                run_dir = candidates[0]
                run_id = run_dir.name
                print(f"Found existing run: {run_dir}")
            elif from_stage_name:
                print(
                    f"Error: --from-stage {from_stage_name} requires prior "
                    f"stage artifacts, but no existing run found for topic "
                    f"hash '{topic_hash}'. Use --output to specify the run "
                    f"directory containing prior artifacts.",
                    file=sys.stderr,
                )
                return 1
            else:
                print(
                    "Warning: --resume specified but no checkpoint found "
                    f"for topic hash '{topic_hash}'. Starting new run.",
                    file=sys.stderr,
                )

    run_dir.mkdir(parents=True, exist_ok=True)

    # Config snapshot — copy the active YAML into the run directory so each
    # task's run_dir is self-describing (profile, topic, experiment mode,
    # LLM provider). On resume, snapshot under a timestamped name to avoid
    # overwriting the original.
    try:
        snapshot_path = run_dir / "config.yaml"
        if snapshot_path.exists():
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            snapshot_path = run_dir / f"config.resumed-{ts}.yaml"
        shutil.copy2(config_path, snapshot_path)
    except Exception as _snap_exc:  # noqa: BLE001
        print(f"Warning: config snapshot failed: {_snap_exc}", file=sys.stderr)

    if config.knowledge_base.root:
        kb_root_path = Path(config.knowledge_base.root)
        kb_root_path.mkdir(parents=True, exist_ok=True)

    adapters = AdapterBundle()

    # --- HITL session setup ---
    hitl_session = None
    try:
        from researchclaw.hitl.config import HITLConfig
        from researchclaw.hitl.session import HITLSession
        from researchclaw.hitl.presets import get_preset

        hitl_config = None
        if hitl_mode:
            # CLI --mode flag takes precedence
            hitl_config = get_preset(hitl_mode)
            if hitl_config is None:
                hitl_config = HITLConfig(enabled=True, mode=hitl_mode)
        elif hasattr(config, "hitl") and config.hitl is not None:
            hitl_config = config.hitl
        # If HITL is enabled, auto_approve should be False
        if hitl_config and hitl_config.enabled:
            auto_approve = False
            stop_on_gate = False  # HITL handles gates directly
    except ImportError:
        hitl_config = None

    from researchclaw.pipeline.runner import execute_pipeline, read_checkpoint
    from researchclaw.pipeline.stages import Stage

    # --- Determine start stage ---
    from_stage = Stage.TOPIC_INIT
    if from_stage_name:
        try:
            from_stage = Stage[from_stage_name.upper()]
        except KeyError:
            valid = ", ".join(s.name for s in Stage)
            print(
                f"Error: unknown stage '{from_stage_name}'. "
                f"Valid stages: {valid}",
                file=sys.stderr,
            )
            return 1
    elif resume:
        resumed = read_checkpoint(run_dir)
        if resumed is not None:
            from_stage = resumed
            print(f"Resuming from checkpoint: Stage {int(from_stage)}: {from_stage.name}")

    # --- Determine stop stage ---
    to_stage: Stage | None = None
    if to_stage_name:
        try:
            to_stage = Stage[to_stage_name.upper()]
        except KeyError:
            valid = ", ".join(s.name for s in Stage)
            print(
                f"Error: unknown stage '{to_stage_name}'. "
                f"Valid stages: {valid}",
                file=sys.stderr,
            )
            return 1
        if int(to_stage) < int(from_stage):
            print(
                f"Error: --to-stage {to_stage.name} (stage {int(to_stage)}) "
                f"must be >= --from-stage {from_stage.name} (stage {int(from_stage)})",
                file=sys.stderr,
            )
            return 1

    # --- Create HITL session and wire to adapters ---
    if hitl_config and hitl_config.enabled:
        try:
            hitl_session = HITLSession(
                run_id=run_id,
                config=hitl_config,
                run_dir=run_dir,
            )
            # Check for scripted intervention file (env var or CLI flag)
            interventions_file = os.environ.get("HITL_INTERVENTIONS_FILE", "")
            if not interventions_file:
                interventions_file = getattr(args, "interventions", None) or ""
            if interventions_file and Path(interventions_file).is_file():
                from researchclaw.hitl.adapters.scripted_adapter import (
                    ScriptedHITLAdapter,
                )

                scripted = ScriptedHITLAdapter.from_file(interventions_file)
                hitl_session.set_input_callback(scripted.collect_input)
                print(f"  HITL:    scripted ({len(scripted.pending_stages)} interventions)")
            else:
                # Wire CLI adapter for interactive input
                from researchclaw.hitl.adapters.cli_adapter import CLIAdapter

                cli_adapter = CLIAdapter(run_dir=run_dir)
                hitl_session.set_input_callback(cli_adapter.collect_input)
            adapters.hitl = hitl_session
        except Exception as _hitl_exc:
            import logging
            logging.getLogger(__name__).warning(
                "HITL session setup failed: %s", _hitl_exc
            )

    from researchclaw import __version__
    print(f"ResearchClaw v{__version__} — Starting pipeline")
    print(f"  Run ID:  {run_id}")
    print(f"  Topic:   {config.research.topic}")
    print(f"  Output:  {run_dir}")
    print(f"  Mode:    {config.project.mode}")
    if hitl_config and hitl_config.enabled:
        print(f"  HITL:    {hitl_config.mode}")
    if config.project.profile:
        print(f"  Profile: {config.project.profile}")
    print(f"  From:    Stage {int(from_stage)}: {from_stage.name}")
    if to_stage:
        print(f"  To:      Stage {int(to_stage)}: {to_stage.name}")

    print()

    results = execute_pipeline(
        run_dir=run_dir,
        run_id=run_id,
        config=config,
        adapters=adapters,
        from_stage=from_stage,
        to_stage=to_stage,
        auto_approve_gates=auto_approve,
        stop_on_gate=stop_on_gate,
        kb_root=kb_root_path,
    )

    done = sum(1 for r in results if r.status.value == "done")
    paused = sum(1 for r in results if r.status.value == "paused")
    failed = sum(1 for r in results if r.status.value == "failed")

    # --- Complete HITL session ---
    if hitl_session is not None:
        hitl_session.complete()
        if hitl_session.interventions_count > 0:
            print(
                f"  HITL: {hitl_session.interventions_count} interventions, "
                f"{hitl_session.total_human_time_sec:.0f}s human time"
            )

    if paused:
        print(
            f"\nPipeline paused: {done}/{len(results)} stages done, "
            f"{paused} paused, {failed} failed"
        )
    else:
        print(f"\nPipeline complete: {done}/{len(results)} stages done, {failed} failed")
    return 0 if failed == 0 else 1


def cmd_validate(args: argparse.Namespace) -> int:
    from researchclaw.config import validate_config
    import yaml

    resolved = _resolve_config_or_exit(args)
    if resolved is None:
        return 1
    config_path = resolved
    no_check_paths = cast(bool, args.no_check_paths)

    with config_path.open(encoding="utf-8") as f:
        loaded = cast(object, yaml.safe_load(f))

    if loaded is None:
        data: dict[str, object] = {}
    elif isinstance(loaded, dict):
        loaded_map = cast(Mapping[object, object], loaded)
        data = {str(key): value for key, value in loaded_map.items()}
    else:
        print("Config validation FAILED:")
        print("  Error: Config root must be a mapping")
        return 1

    result = validate_config(data, check_paths=not no_check_paths)
    if result.ok:
        print("Config validation passed")
        for w in result.warnings:
            print(f"  Warning: {w}")
        return 0
    else:
        print("Config validation FAILED:")
        for e in result.errors:
            print(f"  Error: {e}")
        return 1


def cmd_info(args: argparse.Namespace) -> int:
    """Summarise resolved config: profile, prompt bank, stages, extras."""
    from researchclaw.pipeline._domain import _prompt_bank_domain_from_config
    from researchclaw.prompts import PromptManager

    resolved = _resolve_config_or_exit(args)
    if resolved is None:
        return 1
    config_path = resolved
    profile_override = cast(str | None, getattr(args, "profile", None))
    try:
        config = RCConfig.load(
            config_path,
            check_paths=False,
            profile_override=profile_override,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error loading config: {exc}", file=sys.stderr)
        return 1

    bank = _prompt_bank_domain_from_config(config)
    profile_id = str(getattr(config.project, "profile", "") or "").strip() or "(none)"
    topic = str(getattr(config.research, "topic", "") or "").strip() or "(unset)"
    domains_raw = getattr(config.research, "domains", ()) or ()
    domains = ", ".join(str(d) for d in domains_raw) or "(none)"

    extras_cfg = getattr(config.prompts, "extra_prompts", ()) or ()
    extras_pairs: dict[str, str] = {}
    for item in extras_cfg:
        try:
            stage_key, value = item
        except (TypeError, ValueError):
            continue
        extras_pairs[str(stage_key)] = str(value)

    pm = PromptManager(
        config.prompts.custom_file or None,
        domain=bank,
        extra_prompts=extras_pairs or None,
    )
    resolved_extras = pm.extra_prompts()
    hyp_roles = sorted(pm.debate_roles_hypothesis().keys())

    bank_label = {"ml": "ML (machine learning)", "hep_ph": "HEP-ph (particle phenomenology)"}.get(bank, bank)

    print("=" * 68)
    print("ResearchClaw configuration summary")
    print("=" * 68)
    print(f"  Config file      : {config_path}")
    print(f"  Project profile  : {profile_id}")
    print(f"  Research topic   : {topic}")
    print(f"  Declared domains : {domains}")
    print(f"  Resolved bank    : {bank}  [{bank_label}]")
    if config.prompts.custom_file:
        print(f"  Prompt overrides : {config.prompts.custom_file}")
    print()
    print("  Debate roles (hypothesis): " + ", ".join(hyp_roles))
    print()
    print("Pipeline stages  (mark [EXTRA] = prompts.extra_prompts configured)")
    print("-" * 68)
    for stage in pm.stage_names():
        marker = " [EXTRA]" if stage in resolved_extras else ""
        print(f"  - {stage}{marker}")
    if resolved_extras:
        print()
        print("Configured extra prompts")
        print("-" * 68)
        for stage, text in resolved_extras.items():
            preview = text.replace("\n", " ")
            if len(preview) > 72:
                preview = preview[:72] + "..."
            print(f"  {stage}: {preview}")
    else:
        print()
        print("  (no prompts.extra_prompts configured — any stage above can")
        print("   receive custom guidance via config.yaml -> prompts.extra_prompts)")
    print("=" * 68)
    return 0


_PROVIDER_CHOICES = {
    "1": ("openai", "OPENAI_API_KEY"),
    "2": ("openrouter", "OPENROUTER_API_KEY"),
    "3": ("deepseek", "DEEPSEEK_API_KEY"),
    "4": ("minimax", "MINIMAX_API_KEY"),
    "5": ("acp", ""),
    "6": ("ollama", ""),
    "7": ("minimax-global", "MINIMAX_API_KEY"),
    "8": ("minimax-anthropic", "MINIMAX_API_KEY"),
    "9": ("minimax-anthropic-cn", "MINIMAX_API_KEY"),
    "10": ("atlascloud", "ATLASCLOUD_API_KEY"),
}

_PROVIDER_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "minimax": "https://api.minimaxi.com/v1",
    "minimax-global": "https://api.minimax.io/v1",
    "minimax-anthropic": "https://api.minimax.io/anthropic",
    "minimax-anthropic-cn": "https://api.minimaxi.com/anthropic",
    "ollama": "http://localhost:11434/v1",
    "atlascloud": "https://api.atlascloud.ai/v1",
}

_MINIMAX_MODELS = (
    "MiniMax-M3",
    ["MiniMax-M2.7"],
)

_PROVIDER_MODELS = {
    "openai": ("gpt-4o", ["gpt-4.1", "gpt-4o-mini"]),
    "openrouter": (
        "anthropic/claude-3.5-sonnet",
        ["google/gemini-pro-1.5", "meta-llama/llama-3.1-70b-instruct"],
    ),
    "deepseek": ("deepseek-chat", ["deepseek-reasoner"]),
    "minimax": _MINIMAX_MODELS,
    "minimax-global": _MINIMAX_MODELS,
    "minimax-anthropic": _MINIMAX_MODELS,
    "minimax-anthropic-cn": _MINIMAX_MODELS,
    "ollama": ("llama3.2", ["mistral", "qwen2.5:7b"]),
    "atlascloud": (
        "deepseek-ai/deepseek-v4-pro",
        ["deepseek-ai/deepseek-v4-flash"],
    ),
}


def cmd_init(args: argparse.Namespace) -> int:
    force = cast(bool, args.force)
    dest = Path("config.arc.yaml")

    if dest.exists() and not force:
        print(f"{dest} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1

    # Look for the example config: first in repo root (relative to package),
    # then in CWD (for development), then bundled in the package data dir.
    _candidates = [
        Path(__file__).resolve().parent.parent / EXAMPLE_CONFIG,  # repo root
        Path.cwd() / EXAMPLE_CONFIG,                              # cwd fallback
        Path(__file__).resolve().parent / "data" / EXAMPLE_CONFIG, # packaged
    ]
    example = next((p for p in _candidates if p.exists()), None)
    if example is None:
        print(
            f"Error: example config not found.\n"
            f"Searched: {', '.join(str(c) for c in _candidates)}",
            file=sys.stderr,
        )
        return 1

    # Interactive provider prompt (TTY only, else default to openai)
    choice = "1"
    if sys.stdin.isatty():
        print("Select LLM provider:")
        print("  1) openai       (requires OPENAI_API_KEY)")
        print("  2) openrouter   (requires OPENROUTER_API_KEY)")
        print("  3) deepseek     (requires DEEPSEEK_API_KEY)")
        print("  4) minimax-cn-openai        (requires MINIMAX_API_KEY)")
        print("  5) acp          (local AI agent — no API key needed)")
        print("  6) ollama       (local Ollama server — no API key needed)")
        print("  7) minimax-global-openai    (requires MINIMAX_API_KEY)")
        print("  8) minimax-global-anthropic (requires MINIMAX_API_KEY)")
        print("  9) minimax-cn-anthropic     (requires MINIMAX_API_KEY)")
        print(" 10) atlascloud   (requires ATLASCLOUD_API_KEY)")
        try:
            raw = input("Choice [1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            raw = ""
        if raw in _PROVIDER_CHOICES:
            choice = raw

    provider, api_key_env = _PROVIDER_CHOICES[choice]

    content = example.read_text(encoding="utf-8")

    # String-based replacement to preserve YAML comments
    content = content.replace(
        'provider: "openai-compatible"', f'provider: "{provider}"'
    )

    if provider == "acp":
        # ACP doesn't need base_url or api_key
        content = content.replace(
            'base_url: "https://api.openai.com/v1"', 'base_url: ""'
        )
        content = content.replace('api_key_env: "OPENAI_API_KEY"', 'api_key_env: ""')
    elif provider == "ollama":
        # Ollama runs locally — set base_url, clear api_key_env, set dummy key
        base_url = _PROVIDER_URLS["ollama"]
        content = content.replace(
            'base_url: "https://api.openai.com/v1"', f'base_url: "{base_url}"'
        )
        content = content.replace('api_key_env: "OPENAI_API_KEY"', 'api_key_env: ""')
        content = content.replace('api_key: ""', 'api_key: "ollama"')
    else:
        base_url = _PROVIDER_URLS.get(provider, "https://api.openai.com/v1")
        content = content.replace(
            'base_url: "https://api.openai.com/v1"', f'base_url: "{base_url}"'
        )
        if api_key_env:
            content = content.replace(
                'api_key_env: "OPENAI_API_KEY"', f'api_key_env: "{api_key_env}"'
            )

    if provider in _PROVIDER_MODELS:
        primary, fallbacks = _PROVIDER_MODELS[provider]
        content = content.replace('primary_model: "gpt-4o"', f'primary_model: "{primary}"')
        # Replace fallback models block
        old_fallbacks = '  fallback_models:\n    - "gpt-4.1"\n    - "gpt-4o-mini"'
        new_fallbacks = "  fallback_models:\n" + "".join(
            f'    - "{m}"\n' for m in fallbacks
        )
        content = content.replace(old_fallbacks, new_fallbacks.rstrip("\n"))

    dest.write_text(content, encoding="utf-8")
    print(f"Created {dest} (provider: {provider})")

    if provider == "acp":
        print("\nNext steps:")
        print("  1. Ensure your ACP agent is installed and on PATH")
        print("  2. Edit config.arc.yaml to set llm.acp.agent if needed")
    elif provider == "ollama":
        print("\nNext steps:")
        print("  1. Ensure Ollama is running: ollama serve")
        print("  2. Pull your model: ollama pull llama3.2")
        print("  3. Edit config.arc.yaml to set llm.primary_model to your model name")
    elif provider in ("minimax-anthropic", "minimax-anthropic-cn"):
        print("\nNext steps:")
        print('  1. Install the adapter: pip install "researchclaw[anthropic]"')
        print("  2. Export your API key: export MINIMAX_API_KEY=...")
        print("  3. Edit config.arc.yaml to customize your settings")
    else:
        env_var = api_key_env or "OPENAI_API_KEY"
        print(f"\nNext steps:")
        print(f"  1. Export your API key: export {env_var}=sk-...")
        print("  2. Edit config.arc.yaml to customize your settings")


    return 0


# ── Research Enhancement commands (Agent D) ───────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Construct and return the top-level argument parser (without parsing)."""
    parser = argparse.ArgumentParser(
        prog="researchclaw",
        description="ResearchClaw — Autonomous Research Pipeline",
    )
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run the research pipeline")
    _ = run_p.add_argument("--topic", "-t", help="Override research topic")
    _ = run_p.add_argument(
        "--config", "-c", default=None,
        help="Config file (default: auto-detect config.arc.yaml or config.yaml)",
    )
    _ = run_p.add_argument("--output", "-o", help="Output directory")
    _ = run_p.add_argument(
        "--from-stage", help="Start from a specific stage"
    )
    _ = run_p.add_argument(
        "--to-stage", help="Stop after this stage completes"
    )
    _ = run_p.add_argument(
        "--auto-approve", action="store_true", help="Auto-approve gate stages"
    )
    _ = run_p.add_argument(
        "--mode", "-m",
        choices=["full-auto", "gate-only", "checkpoint", "step-by-step",
                 "co-pilot", "express", "thorough", "learning"],
        default=None,
        help="HITL intervention mode (overrides config)",
    )
    _ = run_p.add_argument(
        "--skip-preflight", action="store_true", help="Skip LLM preflight check"
    )
    _ = run_p.add_argument(
        "--resume", action="store_true", help="Resume from last checkpoint"
    )
    _ = run_p.add_argument(
        "--interventions",
        default=None,
        help="Path to scripted HITL interventions JSON file",
    )
    _ = run_p.add_argument(
        "--profile", "-p",
        default=None,
        help=(
            "Domain profile id to deploy (e.g. hep_ph, ml_vision)."
        ),
    )
    val_p = sub.add_parser("validate", help="Validate config file")
    _ = val_p.add_argument(
        "--config", "-c", default=None,
        help="Config file (default: auto-detect config.arc.yaml or config.yaml)",
    )
    _ = val_p.add_argument(
        "--no-check-paths", action="store_true", help="Skip path existence checks"
    )


    init_p = sub.add_parser("init", help="Create config.arc.yaml from example template")
    _ = init_p.add_argument(
        "--force", action="store_true", help="Overwrite existing config.arc.yaml"
    )


    # Introspection: show resolved domain / prompt bank / stage extras
    info_p = sub.add_parser(
        "info",
        help="Show resolved config: profile, prompt bank, stage list, extras",
        description=(
            "Summarise the current run configuration — project profile, research "
            "topic, resolved prompt bank (ml or hep_ph), debate role roster, and "
            "the full pipeline stage list with [EXTRA] markers for any stages "
            "that have custom guidance configured via prompts.extra_prompts."
        ),
    )
    _ = info_p.add_argument(
        "--config", "-c", default=None,
        help="Config file (default: auto-detect config.arc.yaml or config.yaml)",
    )
    _ = info_p.add_argument(
        "--profile", "-p", default=None,
        help="Override project.profile for this invocation",
    )


    # A: Web platform


    # C1: Multi-project management

    # C3: MCP integration

    # C4: Overleaf sync

    # D1: Research trend tracking

    # Domain profiles (deployable — bundle prompts + infra defaults per domain)
    # `create` wizard + non-interactive path
    # Direct spec flags for scripted `create` (alternative to --from-yaml)

    # Skills management

    # D4: Conference deadline calendar

    # HITL: Attach to running pipeline

    # HITL: Check pipeline status
    status_p = sub.add_parser("status", help="Show pipeline and HITL status")
    _ = status_p.add_argument("run_dir", help="Path to run artifacts directory")

    # HITL: Approve a gate
    approve_p = sub.add_parser("approve", help="Approve the current HITL gate")
    _ = approve_p.add_argument("run_dir", help="Path to run artifacts directory")
    _ = approve_p.add_argument("--message", "-m", default="", help="Approval note")

    # HITL: Reject a gate
    reject_p = sub.add_parser("reject", help="Reject the current HITL gate")
    _ = reject_p.add_argument("run_dir", help="Path to run artifacts directory")
    _ = reject_p.add_argument("--reason", "-r", default="", help="Rejection reason")

    # HITL: Inject guidance
    guide_p = sub.add_parser("guide", help="Inject guidance for a pipeline stage")
    _ = guide_p.add_argument("run_dir", help="Path to run artifacts directory")
    _ = guide_p.add_argument("--stage", "-s", type=int, required=True, help="Target stage number")
    _ = guide_p.add_argument("--message", "-m", required=True, help="Guidance text")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    command = cast(str | None, args.command)

    if command == "run":
        return cmd_run(args)
    elif command == "validate":
        return cmd_validate(args)
    elif command == "init":
        return cmd_init(args)
    elif command == "info":
        return cmd_info(args)
    elif command == "status":
        return cmd_status(args)
    elif command == "approve":
        return cmd_hitl_approve(args)
    elif command == "reject":
        return cmd_hitl_reject(args)
    elif command == "guide":
        return cmd_hitl_guide(args)
    else:
        parser.print_help()
        return 0


# ---------------------------------------------------------------------------
# Profile subcommand
# ---------------------------------------------------------------------------


# ---- Wizard helpers (TTY prompts + autocomplete pick-lists) ---------------


# ---- Main dispatcher -------------------------------------------------------


# ---------------------------------------------------------------------------
# HITL subcommands
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    """Show pipeline and HITL status."""
    run_dir = Path(cast(str, args.run_dir))
    if not run_dir.is_dir():
        print(f"Error: run directory not found: {run_dir}", file=sys.stderr)
        return 1

    from researchclaw.hitl.store import HITLStore
    from researchclaw.hitl.tui.panel import show_pipeline_status, show_intervention_log

    store = HITLStore(run_dir)
    session_data = store.load_session()
    mode = session_data.get("mode", "unknown") if session_data else "N/A"

    show_pipeline_status(run_dir, mode=mode)
    print()

    summary = store.get_summary()
    print(f"  HITL interventions: {summary['intervention_count']}")
    print(f"  Chat sessions: stages {summary['chat_stages']}")
    print(f"  Guidance injected: stages {summary['guidance_stages']}")
    print(f"  Snapshots: {summary['snapshot_count']}")

    if store.is_waiting():
        waiting = store.load_waiting()
        if waiting:
            print(f"\n  ⚠ WAITING for input at Stage {waiting['stage']}")
            print(f"    Reason: {waiting.get('reason', '?')}")
            print(f"    Since: {waiting.get('since', '?')}")

    print()
    show_intervention_log(run_dir)
    return 0


def cmd_hitl_approve(args: argparse.Namespace) -> int:
    """Approve the current HITL gate (non-interactive)."""
    run_dir = Path(cast(str, args.run_dir))
    message = cast(str, args.message)

    import json

    response = {"action": "approve", "message": message}
    response_path = run_dir / "hitl" / "response.json"
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(
        json.dumps(response, indent=2), encoding="utf-8"
    )
    print(f"  Approved. Response saved to {response_path}")
    return 0


def cmd_hitl_reject(args: argparse.Namespace) -> int:
    """Reject the current HITL gate (non-interactive)."""
    run_dir = Path(cast(str, args.run_dir))
    reason = cast(str, args.reason)

    import json

    response = {"action": "reject", "message": reason}
    response_path = run_dir / "hitl" / "response.json"
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(
        json.dumps(response, indent=2), encoding="utf-8"
    )
    print(f"  Rejected. Response saved to {response_path}")
    return 0


def cmd_hitl_guide(args: argparse.Namespace) -> int:
    """Inject guidance for a pipeline stage."""
    run_dir = Path(cast(str, args.run_dir))
    stage = cast(int, args.stage)
    message = cast(str, args.message)

    from researchclaw.hitl.store import HITLStore

    store = HITLStore(run_dir)
    store.save_guidance(stage, message)

    # Also write to stage dir
    stage_dir = run_dir / f"stage-{stage:02d}"
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / "hitl_guidance.md").write_text(message, encoding="utf-8")

    print(f"  Guidance saved for Stage {stage} ({len(message)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
