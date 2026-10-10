import pytest

from researchclaw.pipeline.stages import (
    GATE_ROLLBACK,
    GATE_STAGES,
    NEXT_STAGE,
    PHASE_MAP,
    PREVIOUS_STAGE,
    STAGE_SEQUENCE,
    TRANSITION_MAP,
    Stage,
    StageStatus,
    TransitionEvent,
    TransitionOutcome,
    advance,
    default_rollback_stage,
    gate_required,
)


@pytest.mark.parametrize(
    "index,stage", [(idx, stage) for idx, stage in enumerate(STAGE_SEQUENCE, start=1)]
)
def test_stage_values_follow_sequence_order(index: int, stage: Stage):
    assert int(stage) == index


def test_previous_stage_boundary_values():
    assert PREVIOUS_STAGE[Stage.TOPIC_INIT] is None
    assert PREVIOUS_STAGE[Stage.PROBLEM_DECOMPOSE] is Stage.TOPIC_INIT


def test_phase_map_covers_all_stages_exactly_once():
    flattened = tuple(stage for stages in PHASE_MAP.values() for stage in stages)
    assert set(flattened) == set(Stage)


def test_succeed_event_on_non_gate_stage_transitions_to_done():
    outcome = advance(
        Stage.SEARCH_STRATEGY,
        StageStatus.RUNNING,
        TransitionEvent.SUCCEED,
        hitl_required_stages=(5, 9, 20),
    )

    assert outcome.status is StageStatus.DONE
    assert outcome.next_stage is Stage.LITERATURE_COLLECT
    assert outcome.checkpoint_required is True
    assert outcome.decision == "proceed"


def test_succeed_event_on_gate_stage_transitions_to_blocked_approval():
    outcome = advance(
        Stage.LITERATURE_SCREEN,
        StageStatus.RUNNING,
        TransitionEvent.SUCCEED,
        hitl_required_stages=(5, 20),
    )

    assert outcome.status is StageStatus.BLOCKED_APPROVAL
    assert outcome.next_stage is Stage.LITERATURE_SCREEN
    assert outcome.checkpoint_required is False
    assert outcome.decision == "block"


def test_timeout_event_transitions_to_paused_with_block_decision():
    outcome = advance(
        Stage.LITERATURE_SCREEN,
        StageStatus.BLOCKED_APPROVAL,
        TransitionEvent.TIMEOUT,
    )

    assert outcome.status is StageStatus.PAUSED
    assert outcome.next_stage is Stage.LITERATURE_SCREEN
    assert outcome.checkpoint_required is True
    assert outcome.decision == "block"


def test_invalid_transition_raises_value_error():
    with pytest.raises(ValueError, match="Unsupported transition"):
        _ = advance(Stage.TOPIC_INIT, StageStatus.DONE, TransitionEvent.START)


def test_advance_rejects_unknown_transition_event_string():
    with pytest.raises(ValueError, match="not a valid TransitionEvent"):
        _ = advance(Stage.TOPIC_INIT, StageStatus.PENDING, "unknown")


@pytest.mark.parametrize("stage", tuple(GATE_STAGES))
def test_gate_required_for_gate_stages_with_default_config(stage: Stage):
    assert gate_required(stage, None) is True


@pytest.mark.parametrize("stage", tuple(GATE_STAGES))
def test_gate_required_respects_hitl_stage_subset(stage: Stage):
    required = (5, 20)
    assert gate_required(stage, required) is (int(stage) in required)


@pytest.mark.parametrize("stage", tuple(s for s in Stage if s not in GATE_STAGES))
def test_gate_required_is_false_for_non_gate_stages(stage: Stage):
    assert gate_required(stage, (5, 9, 20)) is False


def test_default_rollback_stage_for_first_stage_returns_self():
    assert default_rollback_stage(Stage.TOPIC_INIT) is Stage.TOPIC_INIT


def test_transition_outcome_field_values_are_exposed():
    outcome = TransitionOutcome(
        stage=Stage.TOPIC_INIT,
        status=StageStatus.RUNNING,
        next_stage=Stage.TOPIC_INIT,
        rollback_stage=Stage.TOPIC_INIT,
        checkpoint_required=True,
        decision="block",
    )

    assert outcome.checkpoint_required is True
    assert outcome.decision == "block"


def test_sequence_and_neighbor_maps_are_consistent_for_all_stages():
    for idx, stage in enumerate(STAGE_SEQUENCE):
        expected_prev = STAGE_SEQUENCE[idx - 1] if idx > 0 else None
        expected_next = (
            STAGE_SEQUENCE[idx + 1] if idx + 1 < len(STAGE_SEQUENCE) else None
        )
        assert PREVIOUS_STAGE[stage] is expected_prev
        assert NEXT_STAGE[stage] is expected_next


def test_transition_map_covers_all_stage_status_values():
    assert set(TRANSITION_MAP.keys()) == set(StageStatus)
    for source_status, targets in TRANSITION_MAP.items():
        assert isinstance(targets, frozenset)
        assert all(target in StageStatus for target in targets)
        if source_status is StageStatus.DONE:
            assert targets == frozenset()


# ── DECISION_ROLLBACK tests ──
