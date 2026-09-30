import pytest


def test_canonical_idempotency_hash_is_order_independent():
    from vdagent_chart.runtime import canonical_input_hash

    left = canonical_input_hash({"task_id": "t1", "scope": {"snapshot": "s1", "area": "a1"}})
    right = canonical_input_hash({"scope": {"area": "a1", "snapshot": "s1"}, "task_id": "t1"})

    assert left == right
    assert left.startswith("sha256:")


def test_completed_run_cannot_transition_back_to_running():
    from vdagent_chart.runtime import ChartRunState

    state = ChartRunState.new("sha256:input")
    completed = state.start().complete()

    with pytest.raises(ValueError, match="terminal"):
        completed.start()
