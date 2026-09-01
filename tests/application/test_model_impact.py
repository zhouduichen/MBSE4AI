from rflp_lite.application.model_impact import impact_for_change


def test_requirement_change_reaches_only_linked_models():
    state = {
        "trace_links": [{"id": "trace-1", "source_id": "req-1", "target_id": "use-case-1"}],
        "mbse": {"trace_links": [{"id": "trace-2", "source_id": "req-2", "target_id": "use-case-2"}]},
    }
    impact = impact_for_change(state, {"req-1"})
    assert "use-case-1" in impact.entity_ids
    assert "use-case-2" not in impact.entity_ids
