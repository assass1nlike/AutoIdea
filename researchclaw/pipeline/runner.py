from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time as _time
from pathlib import Path

from researchclaw.adapters import AdapterBundle
from researchclaw.config import RCConfig
from researchclaw.evolution import EvolutionStore, extract_lessons
from researchclaw.knowledge.base import write_stage_to_kb
from researchclaw.pipeline.executor import StageResult, execute_stage
from researchclaw.pipeline.stages import (
    STAGE_SEQUENCE,
    Stage,
    StageStatus,
)


def _utcnow_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _should_start(stage: Stage, from_stage: Stage, started: bool) -> bool:
    if started:
        return True
    return stage == from_stage


def _build_pipeline_summary(
    *,
    run_id: str,
    results: list[StageResult],
    from_stage: Stage,
    run_dir: Path | None = None,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "run_id": run_id,
        "stages_executed": len(results),
        "stages_done": sum(1 for item in results if item.status == StageStatus.DONE),
        "stages_paused": sum(
            1 for item in results if item.status == StageStatus.PAUSED
        ),
        "stages_blocked": sum(
            1 for item in results if item.status == StageStatus.BLOCKED_APPROVAL
        ),
        "stages_failed": sum(
            1 for item in results if item.status == StageStatus.FAILED
        ),
        "degraded": any(r.decision == "degraded" for r in results),
        "from_stage": int(from_stage),
        "final_stage": int(results[-1].stage) if results else int(from_stage),
        "final_status": results[-1].status.value if results else "no_stages",
        "generated": _utcnow_iso(),
    }
    return summary


def _write_pipeline_summary(run_dir: Path, summary: dict[str, object]) -> None:
    (run_dir / "pipeline_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )


def _write_checkpoint(
    run_dir: Path, stage: Stage, run_id: str,
    adapters: "AdapterBundle | None" = None,
) -> None:
    """Write checkpoint atomically via temp file + rename to prevent corruption."""
    checkpoint: dict[str, object] = {
        "last_completed_stage": int(stage),
        "last_completed_name": stage.name,
        "run_id": run_id,
        "timestamp": _utcnow_iso(),
    }

    # Embed HITL session data if available
    if adapters is not None:
        hitl_session = getattr(adapters, "hitl", None)
        if hitl_session is not None:
            try:
                checkpoint["hitl"] = hitl_session.hitl_checkpoint_data()
            except Exception:
                pass
    target = run_dir / "checkpoint.json"
    fd, tmp_path = tempfile.mkstemp(dir=run_dir, suffix=".tmp", prefix="checkpoint_")
    os.close(fd)
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(checkpoint, indent=2))
        Path(tmp_path).replace(target)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _write_heartbeat(run_dir: Path, stage: Stage, run_id: str) -> None:
    """Write heartbeat file for sentinel watchdog monitoring."""
    import os

    heartbeat = {
        "pid": os.getpid(),
        "last_stage": int(stage),
        "last_stage_name": stage.name,
        "run_id": run_id,
        "timestamp": _utcnow_iso(),
    }
    (run_dir / "heartbeat.json").write_text(
        json.dumps(heartbeat, indent=2), encoding="utf-8"
    )


def read_checkpoint(run_dir: Path) -> Stage | None:
    """Read checkpoint and return the NEXT stage to execute, or None if no checkpoint."""
    cp_path = run_dir / "checkpoint.json"
    if not cp_path.exists():
        return None
    try:
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        last_num = data.get("last_completed_stage")
        if last_num is None:
            return None
        for i, stage in enumerate(STAGE_SEQUENCE):
            if int(stage) == last_num:
                if i + 1 < len(STAGE_SEQUENCE):
                    return STAGE_SEQUENCE[i + 1]
                return None
        return None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def resume_from_checkpoint(
    run_dir: Path, default_stage: Stage = Stage.TOPIC_INIT
) -> Stage:
    """Resolve the stage to resume from using checkpoint metadata."""
    next_stage = read_checkpoint(run_dir)
    return next_stage if next_stage is not None else default_stage


logger = logging.getLogger(__name__)


def execute_pipeline(
    *,
    run_dir: Path,
    run_id: str,
    config: RCConfig,
    adapters: AdapterBundle,
    from_stage: Stage = Stage.TOPIC_INIT,
    to_stage: Stage | None = None,
    auto_approve_gates: bool = False,
    stop_on_gate: bool = False,
    kb_root: Path | None = None,
    cancel_event: "threading.Event | None" = None,
) -> list[StageResult]:
    """Execute pipeline stages sequentially from *from_stage* to *to_stage* (inclusive)."""

    results: list[StageResult] = []
    started = False
    total_stages = len(STAGE_SEQUENCE)

    # Force the domain detector to honor a deployed profile (if any) so
    # every stage picks the same adapter.  Safe no-op when empty.
    try:
        from researchclaw.domains.detector import set_forced_profile
        forced = getattr(config.project, "profile", "") or ""
        set_forced_profile(forced)
    except Exception:  # noqa: BLE001
        pass

    # ── Integration hooks: EventLog, ExperimentMemory, CostTracker ──
    event_log = None
    try:
        from researchclaw.pipeline.event_log import EventLog, EventType, create_event
        event_log = EventLog(log_dir=run_dir)
        event_log.append(create_event(
            EventType.PIPELINE_START, run_id=run_id,
            stages=total_stages, from_stage=int(from_stage),
        ))
    except Exception:
        logger.debug("Event log initialisation skipped")

    for stage in STAGE_SEQUENCE:
        started = _should_start(stage, from_stage, started)
        if not started:
            continue

        # ── Check for cancellation before each stage ──
        if cancel_event is not None and cancel_event.is_set():
            logger.info("[%s] Pipeline cancelled before stage %s", run_id, stage.name)
            print(f"[{run_id}] Pipeline cancelled by user.")
            break

        stage_num = int(stage)
        prefix = f"[{run_id}] Stage {stage_num:02d}/{total_stages}"
        print(f"{prefix} {stage.name} — running...")

        # ── Event log: stage start ──
        if event_log:
            try:
                event_log.append(create_event(
                    EventType.STAGE_START, run_id=run_id, stage=stage.name,
                ))
            except Exception:
                pass

        t0 = _time.monotonic()

        result = execute_stage(
            stage,
            run_dir=run_dir,
            run_id=run_id,
            config=config,
            adapters=adapters,
            auto_approve_gates=auto_approve_gates,
        )
        elapsed = _time.monotonic() - t0

        # ── Event log: stage end ──
        if event_log:
            try:
                etype = EventType.STAGE_END if result.status == StageStatus.DONE else EventType.STAGE_FAIL
                event_log.append(create_event(
                    etype, run_id=run_id, stage=stage.name,
                    status=result.status.value, elapsed_sec=round(elapsed, 1),
                    error=result.error,
                ))
            except Exception:
                pass

        if result.status == StageStatus.DONE:
            arts = ", ".join(result.artifacts) if result.artifacts else "none"
            if result.decision == "degraded":
                print(
                    f"{prefix} {stage.name} — DEGRADED ({elapsed:.1f}s) "
                    f"— continuing with sanitization → {arts}"
                )
            else:
                print(f"{prefix} {stage.name} — done ({elapsed:.1f}s) → {arts}")
        elif result.status == StageStatus.FAILED:
            err = result.error or "unknown error"
            print(f"{prefix} {stage.name} — FAILED ({elapsed:.1f}s) — {err}")
        elif result.status == StageStatus.BLOCKED_APPROVAL:
            print(f"{prefix} {stage.name} — blocked (awaiting approval)")
        elif result.status == StageStatus.PAUSED:
            err = result.error or "paused"
            print(f"{prefix} {stage.name} -- PAUSED ({elapsed:.1f}s) -- {err}")
        results.append(result)

        if kb_root is not None and result.status == StageStatus.DONE:
            try:
                stage_dir = run_dir / f"stage-{int(stage):02d}"
                write_stage_to_kb(
                    kb_root,
                    stage_id=int(stage),
                    stage_name=stage.name.lower(),
                    run_id=run_id,
                    artifacts=list(result.artifacts),
                    stage_dir=stage_dir,
                    backend=config.knowledge_base.backend,
                    topic=config.research.topic,
                )
            except Exception:  # noqa: BLE001
                pass

        if result.status == StageStatus.DONE:
            _write_checkpoint(run_dir, stage, run_id, adapters=adapters)

        # ── Stop after to_stage if specified ──
        if to_stage is not None and stage == to_stage:
            logger.info("[%s] Reached --to-stage %s, stopping.", run_id, stage.name)
            print(f"[{run_id}] Reached --to-stage {stage.name}, stopping pipeline.")
            break

        # --- Heartbeat for sentinel watchdog ---
        if result.status == StageStatus.DONE:
            _write_heartbeat(run_dir, stage, run_id)

        # --- HITL: Handle abort decision ---
        if result.decision == "abort":
            logger.info("[%s] Pipeline aborted by user at stage %s", run_id, stage.name)
            print(f"[{run_id}] Pipeline aborted by user at {stage.name}")
            break

        if result.status == StageStatus.FAILED:
            break

        if result.status == StageStatus.PAUSED:
            logger.warning(
                "[%s] Pipeline paused at %s: %s",
                run_id,
                stage.name,
                result.error or result.decision,
            )
            break

        # --- HITL: Handle rejected stage (from HITL review) ---
        if result.status == StageStatus.REJECTED:
            logger.info(
                "[%s] Stage %s rejected by reviewer — pipeline stopped",
                run_id, stage.name,
            )
            print(f"[{run_id}] Stage {stage.name} rejected — pipeline stopped")
            break

        if result.status == StageStatus.BLOCKED_APPROVAL and stop_on_gate:
            break

    summary = _build_pipeline_summary(
        run_id=run_id,
        results=results,
        from_stage=from_stage,
        run_dir=run_dir,
    )
    _write_pipeline_summary(run_dir, summary)

    # ── Event log: pipeline end ──
    if event_log:
        try:
            done_count = sum(1 for r in results if r.status == StageStatus.DONE)
            failed_count = sum(1 for r in results if r.status == StageStatus.FAILED)
            event_log.append(create_event(
                EventType.PIPELINE_END, run_id=run_id,
                stages_done=done_count, stages_failed=failed_count,
            ))
        except Exception:
            pass

    # --- Evolution: extract and store lessons ---
    lessons: list[object] = []
    try:
        lessons = extract_lessons(results, run_id=run_id, run_dir=run_dir)
        if lessons:
            store = EvolutionStore(run_dir / "evolution")
            store.append_many(lessons)
            logger.info("Extracted %d lessons from pipeline run", len(lessons))
    except Exception:  # noqa: BLE001
        logger.warning("Evolution lesson extraction failed (non-blocking)")

    # --- MetaClaw bridge: convert high-severity lessons to skills ---
    try:
        _metaclaw_post_pipeline(config, results, lessons, run_id, run_dir)
    except Exception:  # noqa: BLE001
        logger.warning("MetaClaw post-pipeline hook failed (non-blocking)")

    # --- HITL: Finalize session state ---
    try:
        hitl_session = getattr(adapters, "hitl", None)
        if hitl_session is not None:
            has_abort = any(
                r.decision == "abort" for r in results
            )
            has_failure = any(
                r.status == StageStatus.FAILED for r in results
            )
            if has_abort:
                hitl_session.abort()
            elif has_failure:
                hitl_session.abort()
            else:
                hitl_session.complete()
    except Exception:  # noqa: BLE001
        logger.debug("HITL session finalization failed (non-blocking)")

    return results


def _metaclaw_post_pipeline(
    config: RCConfig,
    results: list[StageResult],
    lessons: list[object],
    run_id: str,
    run_dir: Path,
) -> None:
    """MetaClaw bridge: post-pipeline hook.

    1. Convert high-severity lessons into MetaClaw skills.
    2. Record skill effectiveness feedback.
    3. Signal session end to MetaClaw proxy.
    """
    bridge = getattr(config, "metaclaw_bridge", None)
    if not bridge or not getattr(bridge, "enabled", False):
        return

    from researchclaw.llm.client import LLMClient

    # 1. Lesson-to-skill conversion
    l2s = getattr(bridge, "lesson_to_skill", None)
    if l2s and getattr(l2s, "enabled", False) and lessons:
        try:
            from researchclaw.metaclaw_bridge.lesson_to_skill import (
                convert_lessons_to_skills,
            )

            min_sev = getattr(l2s, "min_severity", "warning")
            llm = LLMClient.from_rc_config(config)
            new_skills = convert_lessons_to_skills(
                lessons,
                llm,
                getattr(bridge, "skills_dir", "~/.metaclaw/skills"),
                min_severity=min_sev,
                max_skills=getattr(l2s, "max_skills_per_run", 3),
            )
            if new_skills:
                logger.info(
                    "MetaClaw: generated %d new skills from lessons: %s",
                    len(new_skills),
                    new_skills,
                )
        except Exception:  # noqa: BLE001
            logger.warning("MetaClaw lesson-to-skill conversion failed", exc_info=True)

    # 2. Skill effectiveness feedback
    try:
        from researchclaw.metaclaw_bridge.skill_feedback import (
            SkillFeedbackStore,
            record_stage_skills,
        )
        from researchclaw.metaclaw_bridge.stage_skill_map import get_stage_config

        feedback_store = SkillFeedbackStore(run_dir / "evolution" / "skill_effectiveness.jsonl")
        for result in results:
            stage_num = int(getattr(result, "stage", 0))
            stage_name = {
                1: "topic_init", 2: "problem_decompose", 3: "search_strategy",
                4: "literature_collect", 5: "literature_screen", 6: "knowledge_extract",
                7: "synthesis", 8: "hypothesis_gen",


            }.get(stage_num, "")
            if not stage_name:
                continue

            stage_config = get_stage_config(stage_name)
            active_skills = stage_config.get("skills", [])
            status = str(getattr(result, "status", ""))
            success = "done" in status.lower()

            if active_skills:
                record_stage_skills(
                    feedback_store,
                    stage_name,
                    run_id,
                    success,
                    active_skills,
                )
    except Exception:  # noqa: BLE001
        logger.warning("MetaClaw skill feedback recording failed")

    # 3. Signal session end (fire-and-forget)
    try:
        from researchclaw.metaclaw_bridge.session import MetaClawSession
        import json as _json
        import urllib.request as _urllib_req

        session = MetaClawSession(run_id)
        end_headers = session.end()
        # Send a minimal request to signal session end
        proxy_url = getattr(bridge, "proxy_url", "http://localhost:30000")
        url = f"{proxy_url.rstrip('/')}/v1/chat/completions"
        body = _json.dumps({
            "model": "session-end",
            "messages": [{"role": "user", "content": "session complete"}],
            "max_tokens": 1,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        headers.update(end_headers)
        req = _urllib_req.Request(url, data=body, headers=headers)
        try:
            _urllib_req.urlopen(req, timeout=5)
        except Exception:  # noqa: BLE001
            pass  # Best-effort signal
    except Exception:  # noqa: BLE001
        pass
