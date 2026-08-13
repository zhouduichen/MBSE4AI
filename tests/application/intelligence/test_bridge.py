from rflp_lite.application.intelligence.bridge import bridge_discovery_to_workbench, build_accepted_graph


def item(identifier, element_type, payload, status="accepted"):
    return {"id": identifier, "element_type": element_type, "status": status, "payload": payload, "producer": "llm", "provenance": [{"source_type": "inferred", "source_id": "lens", "rationale": ""}]}


def state():
    return {"artifact": {"id": "artifact-1", "path": "input.txt", "sha256": "hash"}, "document_regions": [{"id": "region-1", "text": "城市医疗飞行汽车"}], "stakeholders": [], "concerns": [], "needs": [], "structured_requirements": [], "scenarios": [], "discovery": {"candidate_sets": [{"lens_id": "test", "items": [item("s1", "stakeholder", {"name": "急救医生", "category": "medical", "goals": ["救治"], "interactions": ["下达任务"]}), item("r1", "requirement", {"name": "低能见度运行", "statement": "系统应在规定低能见度包线内安全运行", "requirement_type": "operational", "verification_method": "test", "source_region_id": "region-1", "relations": [{"predicate": "satisfiedBy", "target_id": "f1"}]}), item("f1", "function", {"name": "感知障碍物", "inputs": ["传感器数据"], "outputs": ["障碍物轨迹"]}), item("draft", "risk", {"name": "未确认风险"}, status="candidate")]}], "accepted_graph": {}, "revision": 7}}


def test_accepted_graph_excludes_unreviewed_items_and_builds_relations():
    graph = build_accepted_graph(state())
    assert {element["id"] for element in graph["elements"]} == {"s1", "r1", "f1"}
    assert graph["relations"] == [{"source_id": "r1", "predicate": "satisfiedBy", "target_id": "f1"}]


def test_bridge_populates_legacy_groups_without_approving_a_baseline():
    result = bridge_discovery_to_workbench(state())
    assert result["stakeholders"][0]["name"] == "急救医生"
    assert result["structured_requirements"][0]["statement"].startswith("系统应")
    assert result.get("baseline") is None
    assert result["discovery"]["accepted_graph"]["graph_hash"]
