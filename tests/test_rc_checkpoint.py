# pyright: reportPrivateUsage=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnusedCallResult=false
"""Tests for checkpoint/resume and content metrics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from researchclaw.pipeline.executor import StageResult
from researchclaw.pipeline.runner import (
    _build_pipeline_summary,
    _write_checkpoint,
    read_checkpoint,
    resume_from_checkpoint,
)
from researchclaw.pipeline.stages import (
    STAGE_SEQUENCE,
    Stage,
    StageStatus,
)


class TestCheckpoint:
    def test_write_checkpoint(self, tmp_path: Path):
        _write_checkpoint(tmp_path, Stage.LITERATURE_COLLECT, "test-run")
        cp = json.loads((tmp_path / "checkpoint.json").read_text())
        assert cp["last_completed_stage"] == 4
        assert cp["last_completed_name"] == "LITERATURE_COLLECT"
        assert cp["run_id"] == "test-run"
        assert "timestamp" in cp

    def test_read_checkpoint_returns_next_stage(self, tmp_path: Path):
        _write_checkpoint(tmp_path, Stage.LITERATURE_COLLECT, "test-run")
        next_stage = read_checkpoint(tmp_path)
        assert next_stage == Stage.LITERATURE_SCREEN

    def test_read_checkpoint_no_file(self, tmp_path: Path):
        assert read_checkpoint(tmp_path) is None


    def test_read_checkpoint_corrupted(self, tmp_path: Path):
        (tmp_path / "checkpoint.json").write_text("not json", encoding="utf-8")
        assert read_checkpoint(tmp_path) is None

    def test_read_checkpoint_invalid_stage(self, tmp_path: Path):
        (tmp_path / "checkpoint.json").write_text(
            json.dumps({"last_completed_stage": 999}), encoding="utf-8"
        )
        assert read_checkpoint(tmp_path) is None

    def test_resume_from_checkpoint_uses_default(self, tmp_path: Path):
        assert resume_from_checkpoint(tmp_path) == Stage.TOPIC_INIT

    def test_resume_from_checkpoint_uses_next_stage(self, tmp_path: Path):
        _write_checkpoint(tmp_path, Stage.SEARCH_STRATEGY, "run-x")
        assert resume_from_checkpoint(tmp_path) == Stage.LITERATURE_COLLECT
