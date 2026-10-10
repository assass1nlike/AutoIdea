# pyright: reportPrivateUsage=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnusedCallResult=false, reportAttributeAccessIssue=false, reportUnknownLambdaType=false
from __future__ import annotations

import json
import re
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from researchclaw.adapters import AdapterBundle
from researchclaw.config import RCConfig
from researchclaw.pipeline import executor as rc_executor
from researchclaw.pipeline.stages import Stage, StageStatus


class FakeLLMClient:
    def __init__(self, response_text: str = "mock response"):
        self.response_text: str = response_text
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]], **kwargs: object):
        _ = kwargs
        self.calls.append(messages)
        from researchclaw.llm.client import LLMResponse

        return LLMResponse(content=self.response_text, model="fake-model")


class FakeLLMClientWithConfig(FakeLLMClient):
    def __init__(self, response_text: str = "mock response"):
        super().__init__(response_text=response_text)
        self.config: SimpleNamespace = SimpleNamespace(
            base_url="http://fake", api_key="fake-key"
        )


@pytest.fixture()
def rc_config(tmp_path: Path) -> RCConfig:
    data = {
        "project": {"name": "rc-test", "mode": "docs-first"},
        "research": {
            "topic": "test-driven science",
            "domains": ["ml", "systems"],
            "daily_paper_count": 2,
            "quality_threshold": 8.2,
        },
        "runtime": {"timezone": "UTC"},
        "notifications": {
            "channel": "local",
            "on_stage_start": True,
            "on_stage_fail": False,
            "on_gate_required": True,
        },
        "knowledge_base": {"backend": "markdown", "root": str(tmp_path / "kb")},
        "openclaw_bridge": {"use_memory": True, "use_message": True},
        "llm": {
            "provider": "openai-compatible",
            "base_url": "http://localhost:1234/v1",
            "api_key_env": "RC_TEST_KEY",
            "api_key": "inline-test-key",
            "primary_model": "fake-model",
            "fallback_models": [],
        },
        "security": {"hitl_required_stages": [5, 9, 20]},
        "experiment": {"mode": "sandbox"},
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


def _write_prior_artifact(
    run_dir: Path, stage_num: int, filename: str, content: str
) -> None:
    stage_dir = run_dir / f"stage-{stage_num:02d}"
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / filename).write_text(content, encoding="utf-8")


def test_every_stage_member_has_matching_executor() -> None:
    executor_map = getattr(rc_executor, "EXECUTOR_MAP", rc_executor._STAGE_EXECUTORS)
    assert set(executor_map.keys()) == set(Stage)


def test_stage_result_dataclass_fields() -> None:
    result = rc_executor.StageResult(
        stage=Stage.TOPIC_INIT, status=StageStatus.DONE, artifacts=("goal.md",)
    )
    assert result.stage == Stage.TOPIC_INIT
    assert result.status == StageStatus.DONE
    assert result.artifacts == ("goal.md",)
    assert result.error is None
    assert result.decision == "proceed"
    assert result.evidence_refs == ()


def test_utcnow_iso_returns_valid_iso_timestamp() -> None:
    ts = rc_executor._utcnow_iso()
    assert ts.endswith("+00:00")
    assert "T" in ts


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("before\n```yaml\na: 1\n```\nafter", "a: 1"),
        ("```yml\nkey: value\n```", "key: value"),
        ("```\nplain: true\n```", "plain: true"),
        ("  x: y  ", "x: y"),
    ],
)
def test_extract_yaml_block_variants(text: str, expected: str) -> None:
    assert rc_executor._extract_yaml_block(text) == expected


@pytest.mark.parametrize(
    ("payload", "default", "expected"),
    [
        ('{"ok": true}', {"fallback": True}, {"ok": True}),
        ("[1, 2, 3]", {"fallback": True}, [1, 2, 3]),
        ("not-json", {"fallback": True}, {"fallback": True}),
    ],
)
def test_safe_json_loads_valid_and_invalid(payload: str, default, expected) -> None:
    assert rc_executor._safe_json_loads(payload, default) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a/b", "a_b"),
        ("a\\b", "a_b"),
        ("../secret", "__secret"),
        ("name with spaces!.md", "name_with_spaces_.md"),
        ("", "unnamed"),
    ],
)
def test_safe_filename_sanitization(raw: str, expected: str) -> None:
    assert rc_executor._safe_filename(raw) == expected


def test_safe_filename_truncates_to_100_chars() -> None:
    raw = "x" * 120
    cleaned = rc_executor._safe_filename(raw)
    assert len(cleaned) == 100
    assert cleaned == "x" * 100


def test_read_prior_artifact_finds_newest_file(run_dir: Path) -> None:
    _write_prior_artifact(run_dir, 1, "goal.md", "old")
    _write_prior_artifact(run_dir, 3, "goal.md", "new")
    found = rc_executor._read_prior_artifact(run_dir, "goal.md")
    assert found == "new"


def test_read_prior_artifact_finds_directory_path(run_dir: Path) -> None:
    cards_dir = run_dir / "stage-06" / "cards"
    cards_dir.mkdir(parents=True)
    (cards_dir / "card-1.json").write_text("{}", encoding="utf-8")
    found = rc_executor._read_prior_artifact(run_dir, "cards/")
    assert found == str(cards_dir)


def test_read_prior_artifact_returns_none_when_not_found(run_dir: Path) -> None:
    assert rc_executor._read_prior_artifact(run_dir, "missing.md") is None


def test_write_stage_meta_writes_expected_json(run_dir: Path) -> None:
    stage_dir = run_dir / "stage-01"
    stage_dir.mkdir()
    result = rc_executor.StageResult(
        stage=Stage.TOPIC_INIT,
        status=StageStatus.DONE,
        artifacts=("goal.md",),
        decision="proceed",
        evidence_refs=("stage-01/goal.md",),
    )
    rc_executor._write_stage_meta(stage_dir, Stage.TOPIC_INIT, "run-abc", result)
    payload = cast(
        dict[str, Any],
        json.loads((stage_dir / "decision.json").read_text(encoding="utf-8")),
    )
    assert payload["stage_id"] == "01-topic_init"
    assert payload["run_id"] == "run-abc"
    assert payload["status"] == "done"
    assert payload["decision"] == "proceed"
    assert payload["output_artifacts"] == ["goal.md"]
    assert payload["evidence_refs"] == ["stage-01/goal.md"]
    assert payload["next_stage"] == 2
    assert re.match(r"\d{4}-\d{2}-\d{2}T", payload["ts"])


def test_write_stage_meta_keeps_paused_stage_as_next_stage(run_dir: Path) -> None:
    stage_dir = run_dir / "stage-02"
    stage_dir.mkdir()
    result = rc_executor.StageResult(
        stage=Stage.PROBLEM_DECOMPOSE,
        status=StageStatus.PAUSED,
        artifacts=("refinement_log.json",),
        decision="resume",
        error="ACP prompt timed out after 1800s",
        evidence_refs=("stage-02/refinement_log.json",),
    )
    rc_executor._write_stage_meta(
        stage_dir, Stage.PROBLEM_DECOMPOSE, "run-paused", result
    )
    payload = cast(
        dict[str, Any],
        json.loads((stage_dir / "decision.json").read_text(encoding="utf-8")),
    )
    assert payload["status"] == "paused"
    assert payload["decision"] == "resume"
    assert payload["next_stage"] == int(Stage.PROBLEM_DECOMPOSE)


def test_execute_stage_creates_stage_dir_writes_artifacts_and_meta(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    fake_llm = FakeLLMClientWithConfig("# Goal\n\nMocked goal body")
    monkeypatch.setattr(
        "researchclaw.pipeline.executor.LLMClient.from_rc_config",
        lambda _config: fake_llm,
    )

    result = rc_executor.execute_stage(
        Stage.TOPIC_INIT,
        run_dir=run_dir,
        run_id="run-1",
        config=rc_config,
        adapters=adapters,
        auto_approve_gates=True,
    )

    assert result.status == StageStatus.DONE
    assert "goal.md" in result.artifacts
    assert (run_dir / "stage-01").is_dir()
    goal_text = (run_dir / "stage-01" / "goal.md").read_text(encoding="utf-8")
    # goal.md now starts with a disclaimer blockquote; the original content follows
    assert "# Goal" in goal_text
    assert "unverified draft" in goal_text  # disclaimer is present
    assert len(fake_llm.calls) == 1

    decision = cast(
        dict[str, Any],
        json.loads(
            (run_dir / "stage-01" / "decision.json").read_text(encoding="utf-8")
        ),
    )
    assert decision["run_id"] == "run-1"
    assert decision["status"] == "done"
    assert decision["output_artifacts"] == ["goal.md",]


def test_execute_stage_contract_validation_missing_output_file_marks_failed(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    def bad_executor(
        _stage_dir: Path,
        _run_dir: Path,
        _config: RCConfig,
        _adapters: AdapterBundle,
        *,
        llm: object = None,
    ):
        _ = llm
        return rc_executor.StageResult(
            stage=Stage.TOPIC_INIT, status=StageStatus.DONE, artifacts=("goal.md",)
        )

    monkeypatch.setitem(rc_executor._STAGE_EXECUTORS, Stage.TOPIC_INIT, bad_executor)
    result = rc_executor.execute_stage(
        Stage.TOPIC_INIT,
        run_dir=run_dir,
        run_id="run-2",
        config=rc_config,
        adapters=adapters,
        auto_approve_gates=True,
    )
    assert result.status == StageStatus.FAILED
    assert "Missing or empty output: goal.md" in (result.error or "")


def test_execute_stage_contract_validation_missing_output_directory_marks_failed(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    _write_prior_artifact(run_dir, 5, "shortlist.jsonl", '{"title": "x"}')

    def bad_executor(
        _stage_dir: Path,
        _run_dir: Path,
        _config: RCConfig,
        _adapters: AdapterBundle,
        *,
        llm: object = None,
    ):
        _ = llm
        return rc_executor.StageResult(
            stage=Stage.KNOWLEDGE_EXTRACT,
            status=StageStatus.DONE,
            artifacts=("cards/",),
        )

    monkeypatch.setitem(
        rc_executor._STAGE_EXECUTORS, Stage.KNOWLEDGE_EXTRACT, bad_executor
    )
    result = rc_executor.execute_stage(
        Stage.KNOWLEDGE_EXTRACT,
        run_dir=run_dir,
        run_id="run-3",
        config=rc_config,
        adapters=adapters,
        auto_approve_gates=True,
    )
    assert result.status == StageStatus.FAILED
    assert "Missing output directory: cards/" in (result.error or "")


def test_execute_stage_missing_required_input_returns_failed(
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    result = rc_executor.execute_stage(
        Stage.PROBLEM_DECOMPOSE,
        run_dir=run_dir,
        run_id="run-4",
        config=rc_config,
        adapters=adapters,
        auto_approve_gates=True,
    )
    assert result.status == StageStatus.FAILED
    assert "Missing input: goal.md" in (result.error or "")


def test_execute_stage_gate_behavior_auto_approve_true_keeps_done(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    _write_prior_artifact(run_dir, 4, "candidates.jsonl", '{"title": "paper"}')

    def good_executor(
        stage_dir: Path,
        _run_dir: Path,
        _config: RCConfig,
        _adapters: AdapterBundle,
        *,
        llm: object = None,
        **_kwargs: object,
    ):
        _ = llm
        (stage_dir / "shortlist.jsonl").write_text(
            '{"title": "paper"}\n', encoding="utf-8"
        )
        return rc_executor.StageResult(
            stage=Stage.LITERATURE_SCREEN,
            status=StageStatus.DONE,
            artifacts=("shortlist.jsonl",),
        )

    monkeypatch.setitem(
        rc_executor._STAGE_EXECUTORS, Stage.LITERATURE_SCREEN, good_executor
    )
    result = rc_executor.execute_stage(
        Stage.LITERATURE_SCREEN,
        run_dir=run_dir,
        run_id="run-5",
        config=rc_config,
        adapters=adapters,
        auto_approve_gates=True,
    )
    assert result.status == StageStatus.DONE
    memory_entries = getattr(adapters.memory, "entries", [])
    assert any(
        ns == "gates" and "auto-approved" in content for ns, content in memory_entries
    )


def test_execute_stage_gate_behavior_auto_approve_false_blocks(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    _write_prior_artifact(run_dir, 4, "candidates.jsonl", '{"title": "paper"}')

    def good_executor(
        stage_dir: Path,
        _run_dir: Path,
        _config: RCConfig,
        _adapters: AdapterBundle,
        *,
        llm: object = None,
        **_kwargs: object,
    ):
        _ = llm
        (stage_dir / "shortlist.jsonl").write_text(
            '{"title": "paper"}\n', encoding="utf-8"
        )
        return rc_executor.StageResult(
            stage=Stage.LITERATURE_SCREEN,
            status=StageStatus.DONE,
            artifacts=("shortlist.jsonl",),
        )

    monkeypatch.setitem(
        rc_executor._STAGE_EXECUTORS, Stage.LITERATURE_SCREEN, good_executor
    )
    result = rc_executor.execute_stage(
        Stage.LITERATURE_SCREEN,
        run_dir=run_dir,
        run_id="run-6",
        config=rc_config,
        adapters=adapters,
        auto_approve_gates=False,
    )
    assert result.status == StageStatus.BLOCKED_APPROVAL
    assert result.decision == "block"
    message_calls = getattr(adapters.message, "calls", [])
    assert message_calls
    assert "Approval required" in message_calls[-1][2]


def test_execute_stage_llm_client_creation_error_falls_back_without_crash(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    def boom(_config: RCConfig):
        raise RuntimeError("llm init failed")

    monkeypatch.setattr("researchclaw.pipeline.executor.LLMClient.from_rc_config", boom)
    result = rc_executor.execute_stage(
        Stage.TOPIC_INIT,
        run_dir=run_dir,
        run_id="run-7",
        config=rc_config,
        adapters=adapters,
        auto_approve_gates=True,
    )
    assert result.status == StageStatus.DONE
    assert (run_dir / "stage-01" / "goal.md").exists()


def test_execute_stage_executor_exception_returns_failed(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    rc_config: RCConfig,
    adapters: AdapterBundle,
) -> None:
    def raising_executor(
        _stage_dir: Path,
        _run_dir: Path,
        _config: RCConfig,
        _adapters: AdapterBundle,
        *,
        llm: object = None,
        **_kwargs: object,
    ):
        _ = llm
        raise RuntimeError("stage exploded")

    monkeypatch.setitem(
        rc_executor._STAGE_EXECUTORS, Stage.TOPIC_INIT, raising_executor
    )
    result = rc_executor.execute_stage(
        Stage.TOPIC_INIT,
        run_dir=run_dir,
        run_id="run-8",
        config=rc_config,
        adapters=adapters,
        auto_approve_gates=True,
    )
    assert result.status == StageStatus.FAILED
    assert result.decision == "retry"
    assert "stage exploded" in (result.error or "")


class TestStageHealth:
    def test_stage_health_json_written(self, tmp_path: Path) -> None:
        from researchclaw.pipeline.executor import execute_stage
        from researchclaw.pipeline.stages import Stage

        config = RCConfig.load(
            Path(__file__).parent.parent / "config.researchclaw.example.yaml",
            check_paths=False,
        )
        result = execute_stage(
            Stage.TOPIC_INIT,
            run_dir=tmp_path,
            run_id="test-health",
            config=config,
            adapters=AdapterBundle(),
            auto_approve_gates=True,
        )
        health_path = tmp_path / "stage-01" / "stage_health.json"
        assert result is not None
        assert health_path.exists()

    def test_stage_health_has_required_fields(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock, patch

        from researchclaw.pipeline.executor import execute_stage
        from researchclaw.pipeline.stages import Stage

        config = RCConfig.load(
            Path(__file__).parent.parent / "config.researchclaw.example.yaml",
            check_paths=False,
        )

        with patch("researchclaw.pipeline.executor.LLMClient") as mock_llm_cls:
            mock_client = MagicMock()
            mock_client.chat.return_value = MagicMock(
                content='{"topic": "test", "research_questions": ["q1"]}'
            )
            mock_llm_cls.from_rc_config.return_value = mock_client

            execute_stage(
                Stage.TOPIC_INIT,
                run_dir=tmp_path,
                run_id="test-health-fields",
                config=config,
                adapters=AdapterBundle(),
                auto_approve_gates=True,
            )

        health_path = tmp_path / "stage-01" / "stage_health.json"
        if health_path.exists():
            data = json.loads(health_path.read_text(encoding="utf-8"))
            assert "stage_id" in data
            assert "run_id" in data
            assert "duration_sec" in data
            assert "status" in data
            assert "timestamp" in data
            assert data["duration_sec"] >= 0


    def test_stage_health_duration_positive(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock, patch

        from researchclaw.pipeline.executor import execute_stage
        from researchclaw.pipeline.stages import Stage

        config = RCConfig.load(
            Path(__file__).parent.parent / "config.researchclaw.example.yaml",
            check_paths=False,
        )

        with patch("researchclaw.pipeline.executor.LLMClient") as mock_llm_cls:
            mock_client = MagicMock()
            mock_client.chat.return_value = MagicMock(
                content='{"topic": "test", "sub_problems": []}'
            )
            mock_llm_cls.from_rc_config.return_value = mock_client

            execute_stage(
                Stage.TOPIC_INIT,
                run_dir=tmp_path,
                run_id="test-duration",
                config=config,
                adapters=AdapterBundle(),
                auto_approve_gates=True,
            )

        health_path = tmp_path / "stage-01" / "stage_health.json"
        if health_path.exists():
            data = json.loads(health_path.read_text(encoding="utf-8"))
            assert data["duration_sec"] >= 0

# Contracts import for Stage 13/22 preservation features.
from researchclaw.pipeline.contracts import CONTRACTS


# ── P1-1: Topic keyword extraction tests ──


class TestExtractTopicKeywords:
    def test_basic_extraction(self) -> None:
        keywords = rc_executor._extract_topic_keywords(
            "Agent-based Reinforcement Learning for Automated Scientific Discovery"
        )
        assert "agent-based" in keywords
        assert "reinforcement" in keywords
        assert "learning" in keywords
        assert "automated" in keywords
        assert "scientific" in keywords
        assert "discovery" in keywords
        # Stop words excluded
        # Stop words excluded
        assert "for" not in keywords

    def test_includes_domain_keywords(self) -> None:
        keywords = rc_executor._extract_topic_keywords(
            "Neural network pruning", domains=("ml", "optimization")
        )
        assert "neural" in keywords
        assert "network" in keywords
        assert "pruning" in keywords
        assert "ml" in keywords
        assert "optimization" in keywords

    def test_deduplication(self) -> None:
        keywords = rc_executor._extract_topic_keywords(
            "Learning to learn meta-learning", domains=("learning",)
        )
        assert keywords.count("learning") == 1

    def test_empty_topic(self) -> None:
        keywords = rc_executor._extract_topic_keywords("")
        assert keywords == []


# ── P1-2: Topic constraint block test ──


# ── Multi-perspective debate tests ──


class TestMultiPerspectiveGenerate:
    def test_generates_all_perspectives(self, tmp_path: Path) -> None:
        roles = {
            "role_a": {"system": "You are A.", "user": "Do A for {topic}."},
            "role_b": {"system": "You are B.", "user": "Do B for {topic}."},
        }
        fake_llm = FakeLLMClient("perspective output")
        perspectives_dir = tmp_path / "perspectives"
        result = rc_executor._multi_perspective_generate(
            fake_llm, roles, {"topic": "test"}, perspectives_dir
        )
        assert set(result.keys()) == {"role_a", "role_b"}
        assert (perspectives_dir / "role_a.md").exists()
        assert (perspectives_dir / "role_b.md").exists()
        assert len(fake_llm.calls) == 2

    def test_saves_perspective_content(self, tmp_path: Path) -> None:
        roles = {"critic": {"system": "Be critical.", "user": "Criticize {topic}."}}
        fake_llm = FakeLLMClient("critical analysis here")
        perspectives_dir = tmp_path / "perspectives"
        rc_executor._multi_perspective_generate(
            fake_llm, roles, {"topic": "ml"}, perspectives_dir
        )
        content = (perspectives_dir / "critic.md").read_text()
        assert content == "critical analysis here"

    def test_renders_variables_in_prompts(self, tmp_path: Path) -> None:
        roles = {"r1": {"system": "Sys for {topic}.", "user": "User for {topic}."}}
        fake_llm = FakeLLMClient("ok")
        rc_executor._multi_perspective_generate(
            fake_llm, roles, {"topic": "RL"}, tmp_path / "p"
        )
        call = fake_llm.calls[0]
        assert "RL" in call[0]["content"]


class TestSynthesizePerspectives:
    def test_combines_perspectives(self) -> None:
        fake_llm = FakeLLMClient("synthesized result")
        pm = rc_executor.PromptManager()
        perspectives = {"innovator": "idea A", "contrarian": "idea B"}
        result = rc_executor._synthesize_perspectives(
            fake_llm, perspectives, "hypothesis_synthesize", pm
        )
        assert result == "synthesized result"
        # Check the user prompt contained both perspectives
        call_content = fake_llm.calls[0][0]["content"]
        assert "innovator" in call_content
        assert "contrarian" in call_content


class TestHypothesisGenDebate:
    def test_hypothesis_gen_with_llm_creates_perspectives(
        self, tmp_path: Path, rc_config: RCConfig, adapters: AdapterBundle
    ) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        stage_dir = run_dir / "stage-08"
        stage_dir.mkdir(parents=True)
        _write_prior_artifact(run_dir, 7, "synthesis.md", "# Synthesis\nGap found.")
        fake_llm = FakeLLMClient("## H1\nTest hypothesis")
        result = rc_executor._execute_hypothesis_gen(
            stage_dir, run_dir, rc_config, adapters, llm=fake_llm
        )
        assert result.status == StageStatus.DONE
        assert "hypotheses.md" in result.artifacts
        perspectives_dir = stage_dir / "perspectives"
        assert perspectives_dir.exists()
        # Should have 3 perspective files (innovator, pragmatist, contrarian)
        perspective_files = list(perspectives_dir.glob("*.md"))
        assert len(perspective_files) == 3

    def test_hypothesis_gen_without_llm_no_perspectives(
        self, tmp_path: Path, rc_config: RCConfig, adapters: AdapterBundle
    ) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        stage_dir = run_dir / "stage-08"
        stage_dir.mkdir(parents=True)
        _write_prior_artifact(run_dir, 7, "synthesis.md", "# Synthesis\nGap found.")
        result = rc_executor._execute_hypothesis_gen(
            stage_dir, run_dir, rc_config, adapters, llm=None
        )
        assert result.status == StageStatus.DONE
        assert "hypotheses.md" in result.artifacts
        # No perspectives directory when no LLM
        assert not (stage_dir / "perspectives").exists()


class TestExpandSearchQueries:
    """Tests for _expand_search_queries()."""

    def test_adds_broader_queries(self) -> None:
        queries = ["gradient descent optimization algorithms"]
        topic = "Comparing gradient descent optimization algorithms on benchmark functions"
        result = rc_executor._expand_search_queries(queries, topic)
        assert len(result) > len(queries)

    def test_deduplicates(self) -> None:
        queries = ["gradient descent survey"]
        topic = "gradient descent optimization"
        result = rc_executor._expand_search_queries(queries, topic)
        lowered = [q.lower().strip() for q in result]
        assert len(lowered) == len(set(lowered))

    def test_preserves_original_queries(self) -> None:
        queries = ["query A", "query B"]
        topic = "some research topic about machine learning methods"
        result = rc_executor._expand_search_queries(queries, topic)
        assert result[0] == "query A"
        assert result[1] == "query B"

    def test_adds_survey_benchmark_variants(self) -> None:
        queries = ["deep learning"]
        topic = "deep learning for image classification with limited data"
        result = rc_executor._expand_search_queries(queries, topic)
        has_survey = any("survey" in q.lower() for q in result)
        has_benchmark = any("benchmark" in q.lower() for q in result)
        assert has_survey
        assert has_benchmark


# Stage 4 literature collection regression tests


class TestLiteratureCollectConfiguration:
    """Regression coverage for Stage 4 configuration and fallback behavior."""

    @staticmethod
    def _prepare_stage(run_dir: Path, *, year_min: int = 2021) -> Path:
        _write_prior_artifact(
            run_dir,
            3,
            "queries.json",
            json.dumps(
                {"queries": ["test-driven science"], "year_min": year_min}
            ),
        )
        _write_prior_artifact(
            run_dir,
            3,
            "search_plan.yaml",
            "queries:\n  - test-driven science\n",
        )
        stage_dir = run_dir / "stage-04"
        stage_dir.mkdir(exist_ok=True)
        return stage_dir

    @staticmethod
    def _patch_successful_search(
        monkeypatch: pytest.MonkeyPatch,
        captured: dict[str, object],
    ) -> None:
        from researchclaw.literature.models import Paper

        def fake_search(queries: list[str], **kwargs: object) -> list[Paper]:
            captured["queries"] = queries
            captured.update(kwargs)
            return [
                Paper(
                    paper_id="openalex-W123",
                    title="A Real Literature Search Result",
                    year=2025,
                    url="https://openalex.org/W123",
                    source="openalex",
                )
            ]

        monkeypatch.setattr(
            "researchclaw.literature.search.search_papers_multi_query",
            fake_search,
        )
        monkeypatch.setattr(
            "researchclaw.data.load_seminal_papers",
            lambda _topic: [],
        )

    @staticmethod
    def _read_candidates(stage_dir: Path) -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for line in (stage_dir / "candidates.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]

    @pytest.mark.parametrize(
        (
            "literature_s2_key",
            "llm_s2_key",
            "s2_env_name",
            "s2_env_value",
            "expected_s2_key",
            "literature_openalex_key",
            "openalex_env_name",
            "openalex_env_value",
            "expected_openalex_key",
        ),
        [
            pytest.param(
                "",
                "",
                "S2_API_KEY",
                "s2-env-key",
                "s2-env-key",
                "",
                "OPENALEX_API_KEY",
                "openalex-env-key",
                "openalex-env-key",
                id="default-environment-keys",
            ),
            pytest.param(
                "",
                "",
                "S2_API_KEY",
                "",
                "",
                "",
                "OPENALEX_API_KEY",
                "",
                "",
                id="no-api-keys",
            ),
            pytest.param(
                "",
                "",
                "CUSTOM_S2_KEY",
                "custom-s2-env-key",
                "custom-s2-env-key",
                "",
                "CUSTOM_OPENALEX_KEY",
                "custom-openalex-env-key",
                "custom-openalex-env-key",
                id="custom-environment-names",
            ),
            pytest.param(
                "inline-s2-key",
                "llm-s2-key",
                "S2_API_KEY",
                "s2-env-key",
                "inline-s2-key",
                "inline-openalex-key",
                "OPENALEX_API_KEY",
                "openalex-env-key",
                "inline-openalex-key",
                id="literature-inline-keys-win",
            ),
            pytest.param(
                "",
                "llm-s2-key",
                "S2_API_KEY",
                "s2-env-key",
                "llm-s2-key",
                "",
                "OPENALEX_API_KEY",
                "openalex-env-key",
                "openalex-env-key",
                id="llm-s2-key-wins-over-environment",
            ),
        ],
    )
    def test_resolves_keys_and_passes_all_search_configuration(
        self,
        monkeypatch: pytest.MonkeyPatch,
        rc_config: RCConfig,
        adapters: AdapterBundle,
        run_dir: Path,
        literature_s2_key: str,
        llm_s2_key: str,
        s2_env_name: str,
        s2_env_value: str,
        expected_s2_key: str,
        literature_openalex_key: str,
        openalex_env_name: str,
        openalex_env_value: str,
        expected_openalex_key: str,
    ) -> None:
        from researchclaw.pipeline.stage_impls._literature import (
            _execute_literature_collect,
        )

        stage_dir = self._prepare_stage(run_dir, year_min=2019)
        captured: dict[str, object] = {}
        self._patch_successful_search(monkeypatch, captured)

        for env_name in {
            "S2_API_KEY",
            "OPENALEX_API_KEY",
            s2_env_name,
            openalex_env_name,
        }:
            monkeypatch.delenv(env_name, raising=False)
        if s2_env_value:
            monkeypatch.setenv(s2_env_name, s2_env_value)
        if openalex_env_value:
            monkeypatch.setenv(openalex_env_name, openalex_env_value)

        config = replace(
            rc_config,
            llm=replace(rc_config.llm, s2_api_key=llm_s2_key),
            literature_search=replace(
                rc_config.literature_search,
                sources=("openalex", "arxiv"),
                max_results_per_query=7,
                inter_query_delay_sec=0.25,
                openalex_email="research@example.com",
                openalex_api_key=literature_openalex_key,
                openalex_api_key_env=openalex_env_name,
                s2_api_key=literature_s2_key,
                s2_api_key_env=s2_env_name,
            ),
            web_search=replace(rc_config.web_search, enabled=False),
        )

        result = _execute_literature_collect(
            stage_dir,
            run_dir,
            config,
            adapters,
            llm=None,
        )

        assert result.status == StageStatus.DONE
        assert captured["s2_api_key"] == expected_s2_key
        assert captured["openalex_api_key"] == expected_openalex_key
        assert captured["limit_per_query"] == 7
        assert captured["sources"] == ("openalex", "arxiv")
        assert captured["year_min"] == 2019
        assert captured["openalex_email"] == "research@example.com"
        assert captured["inter_query_delay"] == 0.25
        assert "test-driven science" in cast(list[str], captured["queries"])

        search_meta = json.loads(
            (stage_dir / "search_meta.json").read_text(encoding="utf-8")
        )
        assert search_meta["real_search"] is True
        assert search_meta["year_min"] == 2019
        candidates = self._read_candidates(stage_dir)
        assert candidates[0]["paper_id"] == "openalex-W123"
        assert not any(row.get("is_placeholder") for row in candidates)

    def test_web_search_uses_config_and_writes_context_artifacts(
        self,
        monkeypatch: pytest.MonkeyPatch,
        rc_config: RCConfig,
        adapters: AdapterBundle,
        run_dir: Path,
    ) -> None:
        from researchclaw.pipeline.stage_impls._literature import (
            _execute_literature_collect,
        )

        stage_dir = self._prepare_stage(run_dir)
        captured: dict[str, object] = {}
        self._patch_successful_search(monkeypatch, captured)

        class FakeWebResult:
            scholar_papers: list[object] = []
            web_results: list[object] = [SimpleNamespace(title="Web result")]
            crawled_pages: list[object] = []

            @staticmethod
            def to_context_string(*, max_length: int) -> str:
                captured["web_context_max_length"] = max_length
                return "Verified web search context"

            @staticmethod
            def to_dict() -> dict[str, object]:
                return {
                    "web_results": [{"title": "Web result"}],
                    "web_results_count": 1,
                }

        class FakeWebSearchAgent:
            def __init__(self, **kwargs: object) -> None:
                captured["web_agent_kwargs"] = kwargs

            def search_and_extract(
                self,
                topic: str,
                *,
                search_queries: list[str],
            ) -> FakeWebResult:
                captured["web_topic"] = topic
                captured["web_queries"] = search_queries
                return FakeWebResult()

        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.setenv("CUSTOM_TAVILY_KEY", "tavily-env-key")
        monkeypatch.setattr(
            "researchclaw.web.agent.WebSearchAgent",
            FakeWebSearchAgent,
        )
        config = replace(
            rc_config,
            web_search=replace(
                rc_config.web_search,
                enabled=True,
                tavily_api_key="",
                tavily_api_key_env="CUSTOM_TAVILY_KEY",
                enable_scholar=False,
                enable_crawling=False,
                enable_pdf_extraction=False,
                max_web_results=4,
                max_scholar_results=3,
                max_crawl_urls=2,
            ),
        )

        result = _execute_literature_collect(
            stage_dir,
            run_dir,
            config,
            adapters,
            llm=None,
        )

        assert result.status == StageStatus.DONE
        assert captured["web_agent_kwargs"] == {
            "tavily_api_key": "tavily-env-key",
            "enable_scholar": False,
            "enable_crawling": False,
            "enable_pdf": False,
            "max_web_results": 4,
            "max_scholar_results": 3,
            "max_crawl_urls": 2,
        }
        assert captured["web_topic"] == rc_config.research.topic
        assert captured["web_queries"] == ["test-driven science"]
        assert captured["web_context_max_length"] == 20_000
        assert (stage_dir / "web_context.md").read_text(
            encoding="utf-8"
        ) == "Verified web search context"
        web_metadata = json.loads(
            (stage_dir / "web_search_result.json").read_text(encoding="utf-8")
        )
        assert web_metadata["web_results_count"] == 1
        assert "web_context.md" in result.artifacts
        assert "web_search_result.json" in result.artifacts

    def test_execute_stage_runs_literature_contract_without_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        rc_config: RCConfig,
        adapters: AdapterBundle,
        run_dir: Path,
    ) -> None:
        stage_dir = self._prepare_stage(run_dir)
        captured: dict[str, object] = {}
        self._patch_successful_search(monkeypatch, captured)
        config = replace(
            rc_config,
            web_search=replace(rc_config.web_search, enabled=False),
        )

        result = rc_executor.execute_stage(
            Stage.LITERATURE_COLLECT,
            run_dir=run_dir,
            run_id="stage-4-regression",
            config=config,
            adapters=adapters,
            auto_approve_gates=True,
        )

        assert result.status == StageStatus.DONE
        assert captured["sources"] == config.literature_search.sources
        assert (stage_dir / "candidates.jsonl").exists()
        assert (stage_dir / "references.bib").exists()
        assert (stage_dir / "decision.json").exists()
        assert (stage_dir / "stage_health.json").exists()
        search_meta = json.loads(
            (stage_dir / "search_meta.json").read_text(encoding="utf-8")
        )
        assert search_meta["real_search"] is True
        assert not any(
            row.get("is_placeholder")
            for row in self._read_candidates(stage_dir)
        )

    def test_api_failure_logs_and_uses_placeholder_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        rc_config: RCConfig,
        adapters: AdapterBundle,
        run_dir: Path,
    ) -> None:
        from researchclaw.pipeline.stage_impls._literature import (
            _execute_literature_collect,
        )

        stage_dir = self._prepare_stage(run_dir)

        def failing_search(
            _queries: list[str], **_kwargs: object
        ) -> list[object]:
            raise RuntimeError("simulated literature backend outage")

        monkeypatch.setattr(
            "researchclaw.literature.search.search_papers_multi_query",
            failing_search,
        )
        monkeypatch.setattr(
            "researchclaw.data.load_seminal_papers",
            lambda _topic: [],
        )
        config = replace(
            rc_config,
            web_search=replace(rc_config.web_search, enabled=False),
        )

        result = _execute_literature_collect(
            stage_dir,
            run_dir,
            config,
            adapters,
            llm=None,
        )

        assert result.status == StageStatus.DONE
        assert "falling back to LLM" in caplog.text
        assert "simulated literature backend outage" in caplog.text
        candidates = self._read_candidates(stage_dir)
        assert len(candidates) == 20
        assert all(row.get("is_placeholder") for row in candidates)
        assert not (stage_dir / "references.bib").exists()
        search_meta = json.loads(
            (stage_dir / "search_meta.json").read_text(encoding="utf-8")
        )
        assert search_meta["real_search"] is False
        assert search_meta["bibtex_entries"] == 0


# R4-1: Experiment Budget Guard Tests


# ── R4-2: Data Integrity Enforcement Tests ───────────────────────────


# ── R4-3: Conference-Grade Title Guidelines Tests ────────────────────


# ── R4-4: Conference-Grade Writing Quality Tests ─────────────────────


# ── R5-1 & R5-2: Bug Fixes Tests ────────────────────────────────────


# ── R5-3: NaN/Divergence Fast-Fail Tests ────────────────────────────


# ── R5-4: Experiment Harness Template Tests ──────────────────────────


# ── R5-5: Stdout Truncation Tests ────────────────────────────────────


# ===================================================================
# R6 Tests — Post-E2E Failure Analysis Fixes
# ===================================================================


# ===================================================================
# R7 Tests — Experiment-Paper Quality Alignment
# ===================================================================


# ===================================================================
# R8 Tests — AutoBench Round 1 Fixes
# ===================================================================


# ===================================================================
# R9 Tests — AutoBench Round 2 Fixes
# ===================================================================


# =====================================================================
# _validate_draft_quality tests
# =====================================================================


def _make_prose(word_count: int) -> str:  # noqa: E302
    """Generate flowing prose text of approximately *word_count* words."""
    sentence = (
        "This is a flowing academic prose sentence "
        "that demonstrates our research findings. "
    )
    words_per = len(sentence.split())
    return sentence * (word_count // words_per + 1)


def _make_bullets(word_count: int) -> str:
    """Generate bullet-point text of approximately *word_count* words."""
    line = "- This is a bullet point about a research finding\n"
    words_per = len(line.split())
    return line * (word_count // words_per + 1)


def _make_comparative_prose(word_count: int) -> str:
    """Generate related-work style prose with comparative language."""
    sentence = (
        "Unlike prior work that focuses on simple baselines, "
        "our approach differs by incorporating novel techniques. "
        "In contrast to existing methods, we address key limitations. "
        "However, while previous approaches rely on heuristics, "
        "our method provides theoretical guarantees. "
    )
    words_per = len(sentence.split())
    return sentence * (word_count // words_per + 1)


def _make_results_prose(word_count: int) -> str:
    """Generate results prose with statistical measures."""
    sentence = (
        "Our method achieves 85.3 ± 1.2 accuracy averaged over 5 seeds. "
        "The baseline comparison yields a p-value of 0.003, confirming "
        "statistical significance with 95% confidence interval. "
    )
    words_per = len(sentence.split())
    return sentence * (word_count // words_per + 1)


def _build_draft(**section_overrides: str) -> str:
    """Build a paper draft with default prose sections."""
    defaults = {
        "Abstract": _make_prose(200),
        "Introduction": _make_prose(900),
        "Related Work": _make_comparative_prose(700),
        "Method": _make_prose(1200),
        "Experiments": _make_prose(1000),
        "Results": _make_results_prose(700),
        "Discussion": _make_prose(500),
        "Limitations": _make_prose(250),
        "Conclusion": _make_prose(250),
    }
    defaults.update(section_overrides)
    parts = ["# My Research Title\n"]
    for heading, body in defaults.items():
        parts.append(f"# {heading}\n{body}\n")
    return "\n".join(parts)


# ============================================================
# IMP-21: Stage 6 (knowledge_extract) refuses to run on empty shortlist
# ============================================================


class TestIMP21_KnowledgeExtractEmptyShortlistGate:
    """IMP-21: Stage 6 must short-circuit when Stage 5
    (literature_screen) has produced no shortlist (PAUSED state with
    ``decision="rejected_all"``). Without this gate, Stage 6 spends an
    LLM turn extracting cards from empty input, produces low-quality
    fallback content, and lets downstream stages cascade on garbage.

    We use ``StageStatus.PAUSED`` (not ``BLOCKED_APPROVAL``) because the
    runner halts on PAUSED unconditionally, whereas BLOCKED_APPROVAL only
    halts when ``stop_on_gate=True`` — and ``--auto-approve`` explicitly
    sets ``stop_on_gate=False``, which is the exact scenario this gate
    must prevent the cascade for. Mirrors the existing Stage 5 pattern
    (literature_screen returns PAUSED with ``decision="rejected_all"``).
    """

    def test_returns_paused_when_shortlist_missing(
        self, rc_config: RCConfig, adapters: AdapterBundle, run_dir: Path
    ) -> None:
        """No stage-05*/shortlist.jsonl exists → PAUSED (halts pipeline)."""
        from researchclaw.pipeline.stage_impls._literature import (
            _execute_knowledge_extract,
        )

        stage_dir = run_dir / "stage-06"
        stage_dir.mkdir()

        result = _execute_knowledge_extract(
            stage_dir=stage_dir,
            run_dir=run_dir,
            config=rc_config,
            adapters=adapters,
            llm=None,  # gate must trigger before any LLM call
        )

        assert result.status == StageStatus.PAUSED
        assert result.stage == Stage.KNOWLEDGE_EXTRACT
        assert result.error is not None
        assert "shortlist" in result.error.lower()
        assert result.decision == "upstream_blocked"
        meta_path = stage_dir / "knowledge_meta.json"
        assert meta_path.is_file(), "Gate must write knowledge_meta.json"
        meta = json.loads(meta_path.read_text())
        assert meta["outcome"] == "upstream_empty_shortlist"
        assert meta["shortlist_rows"] == 0

    def test_returns_paused_when_shortlist_empty_string(
        self, rc_config: RCConfig, adapters: AdapterBundle, run_dir: Path
    ) -> None:
        """stage-05/shortlist.jsonl exists but is 0-byte → PAUSED."""
        from researchclaw.pipeline.stage_impls._literature import (
            _execute_knowledge_extract,
        )

        s5_dir = run_dir / "stage-05"
        s5_dir.mkdir()
        (s5_dir / "shortlist.jsonl").write_text("", encoding="utf-8")

        stage_dir = run_dir / "stage-06"
        stage_dir.mkdir()

        result = _execute_knowledge_extract(
            stage_dir=stage_dir,
            run_dir=run_dir,
            config=rc_config,
            adapters=adapters,
            llm=None,
        )

        assert result.status == StageStatus.PAUSED
        assert "stage-06/knowledge_meta.json" in result.evidence_refs

    def test_returns_paused_when_shortlist_only_whitespace(
        self, rc_config: RCConfig, adapters: AdapterBundle, run_dir: Path
    ) -> None:
        """stage-05/shortlist.jsonl is just whitespace → PAUSED."""
        from researchclaw.pipeline.stage_impls._literature import (
            _execute_knowledge_extract,
        )

        s5_dir = run_dir / "stage-05"
        s5_dir.mkdir()
        (s5_dir / "shortlist.jsonl").write_text("\n\n  \n", encoding="utf-8")

        stage_dir = run_dir / "stage-06"
        stage_dir.mkdir()

        result = _execute_knowledge_extract(
            stage_dir=stage_dir,
            run_dir=run_dir,
            config=rc_config,
            adapters=adapters,
            llm=None,
        )

        assert result.status == StageStatus.PAUSED

    def test_proceeds_when_shortlist_has_at_least_one_row(
        self, rc_config: RCConfig, adapters: AdapterBundle, run_dir: Path
    ) -> None:
        """stage-05/shortlist.jsonl has >=1 valid row → gate passes,
        stage proceeds (but exits early since llm=None and no real
        cards can be generated, so we just assert it didn't BLOCK)."""
        from researchclaw.pipeline.stage_impls._literature import (
            _execute_knowledge_extract,
        )

        s5_dir = run_dir / "stage-05"
        s5_dir.mkdir()
        (s5_dir / "shortlist.jsonl").write_text(
            json.dumps(
                {
                    "paper_id": "oalex-W123",
                    "title": "A Real Paper About Label Noise",
                    "abstract": "We study symmetric noise on MNIST.",
                    "year": 2024,
                    "cite_key": "doe2024noise",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        stage_dir = run_dir / "stage-06"
        stage_dir.mkdir()

        result = _execute_knowledge_extract(
            stage_dir=stage_dir,
            run_dir=run_dir,
            config=rc_config,
            adapters=adapters,
            llm=None,  # no LLM, but gate must not trigger
        )

        # Gate did NOT trigger — stage proceeded past the check.
        # Without an LLM, the stage falls back to a template-card path,
        # which is its existing behaviour (not gated by IMP-21).
        assert result.status != StageStatus.PAUSED
        assert result.stage == Stage.KNOWLEDGE_EXTRACT
