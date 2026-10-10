# pyright: reportPrivateUsage=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnusedCallResult=false, reportAttributeAccessIssue=false, reportUnknownLambdaType=false
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from researchclaw.adapters import AdapterBundle
from researchclaw.config import RCConfig
from researchclaw.pipeline import runner as rc_runner
from researchclaw.pipeline.executor import StageResult
from researchclaw.pipeline.stages import STAGE_SEQUENCE, Stage, StageStatus


@pytest.fixture()
def rc_config(tmp_path: Path) -> RCConfig:
    data = {
        "project": {"name": "rc-runner-test", "mode": "docs-first"},
        "research": {"topic": "pipeline testing"},
        "runtime": {"timezone": "UTC"},
        "notifications": {"channel": "local"},
        "knowledge_base": {"backend": "markdown", "root": str(tmp_path / "kb")},
        "openclaw_bridge": {},
        "llm": {
            "provider": "openai-compatible",
            "base_url": "http://localhost:1234/v1",
            "api_key_env": "RC_TEST_KEY",
            "api_key": "inline",
        },
    }
    return RCConfig.from_dict(data, project_root=tmp_path, check_paths=False)


@pytest.fixture()
def adapters() -> AdapterBundle:
    return AdapterBundle()


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    path = tmp_path / "run"
    path.mkdir()
    return path


def _done(stage: Stage, artifacts: tuple[str, ...] = ("out.md",)) -> StageResult:
    return StageResult(stage=stage, status=StageStatus.DONE, artifacts=artifacts)


def _failed(stage: Stage, msg: str = "boom") -> StageResult:
    return StageResult(stage=stage, status=StageStatus.FAILED, artifacts=(), error=msg)


def _paused(stage: Stage, msg: str = "resume needed") -> StageResult:
    return StageResult(
        stage=stage,
        status=StageStatus.PAUSED,
        artifacts=("refinement_log.json",),
        error=msg,
        decision="resume",
    )


def _blocked(stage: Stage) -> StageResult:
    return StageResult(
        stage=stage,
        status=StageStatus.BLOCKED_APPROVAL,
        artifacts=("gate.md",),
        decision="block",
    )


def test_execute_pipeline_runs_stages_in_sequence(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    seen: list[Stage] = []

    def mock_execute_stage(stage: Stage, **kwargs) -> StageResult:
        _ = kwargs
        seen.append(stage)
        return _done(stage)

    monkeypatch.setattr(rc_runner, "execute_stage", mock_execute_stage)
    results = rc_runner.execute_pipeline(
        run_dir=run_dir,
        run_id="run-seq",
        config=rc_config,
        adapters=adapters,
    )
    assert seen == list(STAGE_SEQUENCE)
    assert all(r.status == StageStatus.DONE for r in results)


def test_execute_pipeline_stops_on_failed_stage(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    fail_stage = Stage.SEARCH_STRATEGY

    def mock_execute_stage(stage: Stage, **kwargs) -> StageResult:
        _ = kwargs
        if stage == fail_stage:
            return _failed(stage, "forced failure")
        return _done(stage)

    monkeypatch.setattr(rc_runner, "execute_stage", mock_execute_stage)
    results = rc_runner.execute_pipeline(
        run_dir=run_dir,
        run_id="run-fail",
        config=rc_config,
        adapters=adapters,
    )
    assert results[-1].stage == fail_stage
    assert results[-1].status == StageStatus.FAILED
    assert len(results) == int(fail_stage)


def test_execute_pipeline_stops_on_gate_when_stop_on_gate_enabled(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    gate_stage = Stage.LITERATURE_SCREEN

    def mock_execute_stage(stage: Stage, **kwargs) -> StageResult:
        _ = kwargs
        if stage == gate_stage:
            return _blocked(stage)
        return _done(stage)

    monkeypatch.setattr(rc_runner, "execute_stage", mock_execute_stage)
    results = rc_runner.execute_pipeline(
        run_dir=run_dir,
        run_id="run-gate-stop",
        config=rc_config,
        adapters=adapters,
        stop_on_gate=True,
    )
    assert results[-1].stage == gate_stage
    assert results[-1].status == StageStatus.BLOCKED_APPROVAL
    assert len(results) == int(gate_stage)


def test_execute_pipeline_continues_after_gate_when_stop_on_gate_disabled(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    gate_stage = Stage.LITERATURE_SCREEN

    def mock_execute_stage(stage: Stage, **kwargs) -> StageResult:
        _ = kwargs
        if stage == gate_stage:
            return _blocked(stage)
        return _done(stage)

    monkeypatch.setattr(rc_runner, "execute_stage", mock_execute_stage)
    results = rc_runner.execute_pipeline(
        run_dir=run_dir,
        run_id="run-gate-continue",
        config=rc_config,
        adapters=adapters,
        stop_on_gate=False,
    )
    assert any(item.status == StageStatus.BLOCKED_APPROVAL for item in results)


def test_execute_pipeline_writes_pipeline_summary_json(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    def mock_execute_stage(stage: Stage, **kwargs) -> StageResult:
        _ = kwargs
        return _done(stage)

    monkeypatch.setattr(rc_runner, "execute_stage", mock_execute_stage)
    rc_runner.execute_pipeline(
        run_dir=run_dir,
        run_id="run-summary",
        config=rc_config,
        adapters=adapters,
    )
    summary_path = run_dir / "pipeline_summary.json"
    assert summary_path.exists()


def test_pipeline_summary_has_expected_fields_and_values(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    def mock_execute_stage(stage: Stage, **kwargs) -> StageResult:
        _ = kwargs
        if stage == Stage.LITERATURE_SCREEN:
            return _blocked(stage)
        if stage == Stage.HYPOTHESIS_GEN:
            return _failed(stage)
        return _done(stage)

    monkeypatch.setattr(rc_runner, "execute_stage", mock_execute_stage)
    results = rc_runner.execute_pipeline(
        run_dir=run_dir,
        run_id="run-summary-fields",
        config=rc_config,
        adapters=adapters,
    )
    summary = cast(
        dict[str, Any],
        json.loads((run_dir / "pipeline_summary.json").read_text(encoding="utf-8")),
    )
    assert summary["run_id"] == "run-summary-fields"
    assert summary["stages_executed"] == len(results)
    assert summary["stages_done"] == sum(
        1 for r in results if r.status == StageStatus.DONE
    )
    assert summary["stages_paused"] == 0
    assert summary["stages_blocked"] == 1
    assert summary["stages_failed"] == 1
    assert summary["from_stage"] == 1
    assert summary["final_stage"] == int(Stage.HYPOTHESIS_GEN)
    assert summary["final_status"] == "failed"
    assert "generated" in summary


def test_execute_pipeline_writes_kb_entries_when_kb_root_provided(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
    tmp_path: Path,
) -> None:
    calls: list[tuple[int, str, str]] = []

    def mock_execute_stage(stage: Stage, **kwargs) -> StageResult:
        _ = kwargs
        stage_dir = run_dir / f"stage-{int(stage):02d}"
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / "out.md").write_text(f"stage {int(stage)}", encoding="utf-8")
        return _done(stage)

    def mock_write_stage_to_kb(
        kb_root: Path,
        stage_id: int,
        stage_name: str,
        run_id: str,
        artifacts: list[str],
        stage_dir: Path,
        **kwargs,
    ):
        _ = kb_root, artifacts, stage_dir, kwargs
        calls.append((stage_id, stage_name, run_id))
        return []

    monkeypatch.setattr(rc_runner, "execute_stage", mock_execute_stage)
    monkeypatch.setattr(rc_runner, "write_stage_to_kb", mock_write_stage_to_kb)

    kb_root = tmp_path / "kb-out"
    results = rc_runner.execute_pipeline(
        run_dir=run_dir,
        run_id="run-kb",
        config=rc_config,
        adapters=adapters,
        kb_root=kb_root,
    )
    assert calls[0] == (1, "topic_init", "run-kb")


def test_execute_pipeline_passes_auto_approve_flag_to_execute_stage(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    received: list[bool] = []

    def mock_execute_stage(stage: Stage, **kwargs) -> StageResult:
        received.append(kwargs["auto_approve_gates"])
        return _done(stage)

    monkeypatch.setattr(rc_runner, "execute_stage", mock_execute_stage)
    rc_runner.execute_pipeline(
        run_dir=run_dir,
        run_id="run-auto-approve",
        config=rc_config,
        adapters=adapters,
        auto_approve_gates=True,
    )
    assert received
    assert all(received)


@pytest.mark.parametrize(
    ("results", "expected_status", "expected_final_stage"),
    [
        ([], "no_stages", int(Stage.TOPIC_INIT)),
        ([_done(Stage.TOPIC_INIT)], "done", int(Stage.TOPIC_INIT)),
        (
            [_done(Stage.TOPIC_INIT), _paused(Stage.PROBLEM_DECOMPOSE)],
            "paused",
            int(Stage.PROBLEM_DECOMPOSE),
        ),
        (
            [_done(Stage.TOPIC_INIT), _failed(Stage.PROBLEM_DECOMPOSE)],
            "failed",
            int(Stage.PROBLEM_DECOMPOSE),
        ),
    ],
)
def test_build_pipeline_summary_core_fields(
    results, expected_status: str, expected_final_stage: int
) -> None:
    summary = rc_runner._build_pipeline_summary(
        run_id="run-core",
        results=results,
        from_stage=Stage.TOPIC_INIT,
    )
    assert summary["run_id"] == "run-core"
    assert summary["final_status"] == expected_status
    assert summary["final_stage"] == expected_final_stage


def test_pipeline_prints_stage_progress(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_results = [
        StageResult(
            stage=Stage.TOPIC_INIT, status=StageStatus.DONE, artifacts=("topic.json",)
        ),
        StageResult(
            stage=Stage.PROBLEM_DECOMPOSE,
            status=StageStatus.DONE,
            artifacts=("tree.json",),
        ),
        StageResult(
            stage=Stage.SEARCH_STRATEGY,
            status=StageStatus.FAILED,
            artifacts=(),
            error="LLM timeout",
        ),
    ]

    call_idx = 0

    def mock_execute_stage(stage: Stage, **kwargs) -> StageResult:
        _ = stage, kwargs
        nonlocal call_idx
        idx = call_idx
        call_idx += 1
        return mock_results[min(idx, len(mock_results) - 1)]

    monkeypatch.setattr(rc_runner, "execute_stage", mock_execute_stage)
    monkeypatch.setattr(rc_runner, "write_stage_to_kb", lambda *args, **kwargs: [])

    _ = rc_runner.execute_pipeline(
        run_dir=run_dir,
        run_id="rc-test-001",
        config=rc_config,
        adapters=adapters,
    )

    captured = capsys.readouterr()
    assert "TOPIC_INIT — running..." in captured.out
    assert "TOPIC_INIT — done" in captured.out
    assert "SEARCH_STRATEGY — FAILED" in captured.out
    assert "LLM timeout" in captured.out


def test_pipeline_prints_elapsed_time(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_result = StageResult(
        stage=Stage.TOPIC_INIT,
        status=StageStatus.DONE,
        artifacts=("topic.json",),
    )
    mock_fail = StageResult(
        stage=Stage.PROBLEM_DECOMPOSE,
        status=StageStatus.FAILED,
        artifacts=(),
        error="test",
    )
    results_iter = iter([mock_result, mock_fail])

    monkeypatch.setattr(
        rc_runner, "execute_stage", lambda *args, **kwargs: next(results_iter)
    )
    monkeypatch.setattr(rc_runner, "write_stage_to_kb", lambda *args, **kwargs: [])

    _ = rc_runner.execute_pipeline(
        run_dir=run_dir,
        run_id="rc-test-002",
        config=rc_config,
        adapters=adapters,
    )

    captured = capsys.readouterr()
    import re

    assert re.search(r"\d+\.\d+s\)", captured.out), (
        f"No elapsed time found in: {captured.out}"
    )


# ── PIVOT/PROCEED/REFINE decision loop tests ──


def _pivot_result(stage: Stage) -> StageResult:
    return StageResult(
        stage=stage, status=StageStatus.DONE, artifacts=("decision.md",), decision="pivot"
    )


def _refine_result(stage: Stage) -> StageResult:
    return StageResult(
        stage=stage, status=StageStatus.DONE, artifacts=("decision.md",), decision="refine"
    )


def test_proceed_decision_does_not_trigger_rollback(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    seen: list[Stage] = []

    def mock_execute_stage(stage: Stage, **kwargs) -> StageResult:
        _ = kwargs
        seen.append(stage)
        return _done(stage)

    monkeypatch.setattr(rc_runner, "execute_stage", mock_execute_stage)
    results = rc_runner.execute_pipeline(
        run_dir=run_dir,
        run_id="run-proceed",
        config=rc_config,
        adapters=adapters,
    )
    # Should be exactly 23 stages, no rollback
    assert not (run_dir / "decision_history.json").exists()


# ── Deliverables packaging tests ──


def _setup_stage_artifacts(run_dir: Path) -> None:
    """Create typical stage-22 and stage-23 output files for testing."""
    s22 = run_dir / "stage-22"
    s22.mkdir(parents=True, exist_ok=True)
    (s22 / "paper_final.md").write_text("# My Paper\nContent here.", encoding="utf-8")
    (s22 / "paper.tex").write_text("\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}", encoding="utf-8")
    (s22 / "references.bib").write_text("@article{smith2024,\n  title={Test}\n}", encoding="utf-8")
    code_dir = s22 / "code"
    code_dir.mkdir()
    (code_dir / "main.py").write_text("print('hello')", encoding="utf-8")
    (code_dir / "requirements.txt").write_text("numpy\n", encoding="utf-8")
    (code_dir / "README.md").write_text("# Code\n", encoding="utf-8")

    s23 = run_dir / "stage-23"
    s23.mkdir(parents=True, exist_ok=True)
    (s23 / "paper_final_verified.md").write_text("# My Paper (verified)\nContent.", encoding="utf-8")
    (s23 / "references_verified.bib").write_text("@article{smith2024,\n  title={Test}\n}", encoding="utf-8")
    (s23 / "verification_report.json").write_text(
        json.dumps({"summary": {"total": 5, "verified": 4}}), encoding="utf-8"
    )


# ── Atomic checkpoint write tests ──


def test_write_checkpoint_uses_atomic_rename(run_dir: Path) -> None:
    """Checkpoint must be written via temp file + rename, not direct write"""
    rc_runner._write_checkpoint(run_dir, Stage.TOPIC_INIT, "run-atomic")
    cp = run_dir / "checkpoint.json"
    assert cp.exists()
    data = json.loads(cp.read_text(encoding="utf-8"))
    assert data["last_completed_stage"] == int(Stage.TOPIC_INIT)
    assert data["run_id"] == "run-atomic"


def test_write_checkpoint_leaves_no_temp_files(run_dir: Path) -> None:
    """Atomic write must clean up temp files on success"""
    rc_runner._write_checkpoint(run_dir, Stage.TOPIC_INIT, "run-clean")
    temps = list(run_dir.glob("*.tmp"))
    assert temps == [], f"Leftover temp files: {temps}"


def test_write_checkpoint_preserves_old_on_write_failure(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the temp-file write fails, the existing checkpoint must survive"""
    import builtins

    rc_runner._write_checkpoint(run_dir, Stage.TOPIC_INIT, "run-ok")

    original_open = builtins.open

    def _exploding_open(path, *args, **kwargs):
        # After os.close(fd), _write_checkpoint opens via path string —
        # intercept temp-file opens (checkpoint_*.tmp)
        if isinstance(path, (str, Path)) and "checkpoint_" in str(path):
            raise OSError("disk full")
        if isinstance(path, int):
            raise OSError("disk full")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _exploding_open)
    with pytest.raises(OSError):
        rc_runner._write_checkpoint(run_dir, Stage.PROBLEM_DECOMPOSE, "run-ok")

    # Original checkpoint must be intact
    data = json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))
    assert data["last_completed_stage"] == int(Stage.TOPIC_INIT)
    # Temp file must be cleaned up
    assert list(run_dir.glob("checkpoint_*.tmp")) == []


def test_write_checkpoint_overwrites_previous(run_dir: Path) -> None:
    """A second checkpoint call must fully replace the first"""
    rc_runner._write_checkpoint(run_dir, Stage.TOPIC_INIT, "run-1")
    rc_runner._write_checkpoint(run_dir, Stage.PROBLEM_DECOMPOSE, "run-1")
    data = json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))
    assert data["last_completed_stage"] == int(Stage.PROBLEM_DECOMPOSE)
    assert data["last_completed_name"] == Stage.PROBLEM_DECOMPOSE.name


def _degraded(stage: Stage) -> StageResult:
    return StageResult(
        stage=stage,
        status=StageStatus.DONE,
        artifacts=("quality_report.json",),
        decision="degraded",
    )


# ---------------------------------------------------------------------------
# BUG-223: _promote_best_stage14 must always write experiment_summary_best.json
# ---------------------------------------------------------------------------

def _make_stage14_summary(run_dir: Path, suffix: str, pm_value: float) -> None:
    """Helper: create a stage-14{suffix}/experiment_summary.json."""
    d = run_dir / f"stage-14{suffix}"
    d.mkdir(parents=True, exist_ok=True)
    data = {
        "metrics_summary": {
            "primary_metric": {"min": pm_value, "max": pm_value, "mean": pm_value, "count": 1}
        },
        "condition_summaries": {"cond_a": {"metrics": {"primary_metric": pm_value}}},
    }
    (d / "experiment_summary.json").write_text(json.dumps(data), encoding="utf-8")


# ============================================================
# IMP-21: Runner-level integration test — Stage 6 gate must halt
# the pipeline under --auto-approve (stop_on_gate=False)
# ============================================================
