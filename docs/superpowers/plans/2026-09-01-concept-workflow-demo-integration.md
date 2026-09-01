# 一键概念方案主流程整合 Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal: 将现有 1.1 → 1.2 → 2.1 → 2.2 能力串成可从一句话或文档一次运行到概念设计推荐基线的稳定 Demo 主流程。

Architecture: 在现有需求工作台、MBSE、固定翼概念设计、方案库和三学科评估服务之上增加四个边界清晰的应用层：需求子句拆分、Requirement→Envelope、历史方案映射、Concept Workflow Orchestrator。Web 只构造请求和呈现 DTO；所有中间结果通过现有 workspace/SQLite 持久化边界保存；优化器继续复用现有布局生成器和 DisciplineAdapter。

Tech Stack: Python 3.11+, dataclasses, canonical JSON/hash, SQLite repository, FastAPI/Jinja/HTMX, deterministic SVG, pytest, existing document/OCR readers, OR-Tools optional dependency.

## Global Constraints

- 只实施 1.1、1.2、2.1、2.2；不实施 3.1、3.2、3.3 的三维 CAD、PMI/GD&T、DFM/DFA。
- 明确数值先由规则抽取；LLM 只能补充语义候选，不能覆盖规则数值或直接生成最终 Requirement。
- 未提供的参数不得伪造；explicit、derived、suggested 必须在运行结果/UI 中可见。
- 保留既有 StructuredRequirement、IndicatorEnvelope、SchemeRecord、DisciplineAdapter、concept run API 和候选评审兼容字段。
- 默认固定翼 Demo 为 5 个初始候选，优化至少新增 2 个候选并执行第二次评估；iteration_records 不能为空。
- 内置低阶评估器保持 development_only/development；provisional_selected 不等于 formal_approved。
- Web 层不编排业务，不直接构造 Envelope、候选或评估结果。
- 所有测试命令使用 RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config。
- 当前工作区已有的 OCR 修改、demo_assets/、参考资料和 release/ 目录不加入本次提交，修改重叠时保留用户内容。

---

## 文件结构

### 新建生产文件

- src/rflp_lite/application/requirement_clause_splitter.py — 一句话/区域文本拆分、单位与比较符标准化。
- src/rflp_lite/application/requirement_to_envelope.py — 已审核 Requirement 到 IndicatorEnvelope 的映射和字段来源。
- src/rflp_lite/application/scheme_import_mapper.py — 统一历史方案字段、保留扩展字段、导入幂等辅助。
- src/rflp_lite/application/intelligent_concept_workflow.py — 主链编排、步骤状态、中间结果和失败隔离。
- src/rflp_lite/resources/examples/concept-design/demo-schemes.json — 至少 5 条带稳定 ID 的固定翼演示方案。
- scripts/seed_demo_schemes.py — 显式初始化工作区 Demo 方案库。
- tests/application/test_requirement_clause_splitter.py
- tests/application/test_requirement_to_envelope.py
- tests/application/test_scheme_import_mapper.py
- tests/application/test_intelligent_concept_workflow.py
- tests/e2e/test_concept_workflow_demo.py

### 重点修改文件

- src/rflp_lite/application/requirement_semantics.py
- src/rflp_lite/application/requirement_details.py
- src/rflp_lite/application/parameter_rules.py
- src/rflp_lite/application/concept_design_service.py
- src/rflp_lite/application/multidisciplinary_optimization.py
- src/rflp_lite/application/concept_acceptance.py
- src/rflp_lite/application/web_facade.py
- src/rflp_lite/application/requirements_flow.py
- src/rflp_lite/interface/web/routes.py
- src/rflp_lite/interface/web/api_v1.py
- src/rflp_lite/interface/web/templates/requirements-input.html
- src/rflp_lite/interface/web/templates/concept-design.html
- src/rflp_lite/interface/web/templates/dashboard.html
- src/rflp_lite/interface/web/static/app.css
- src/rflp_lite/adapters/sqlite_repository.py（只在 workflow/selection 需要新持久化字段时增量修改）
- pyproject.toml
- README.md

### 实施顺序

任务 1–3 完成阶段 A 数据正确性；任务 4–7 完成阶段 B 后端主链；任务 8 完成阶段 C Web；任务 9–10 完成阶段 D 交付稳定性。每个任务结束后运行自己的 focused test，再提交该任务变更；不得把用户已有未跟踪资料加入 git add。

---

### Task 1: 固定翼 Demo 契约和基线测试

Files:
- Create: tests/application/test_demo_contracts.py
- Modify: src/rflp_lite/resources/domain-packs/fixed-wing-v1.json
- Modify: src/rflp_lite/resources/examples/concept-design/fixed-wing-envelope.json

Interfaces:
- Consumes: existing fixed-wing pack, envelope and evaluator profile.
- Produces: stable Demo input contract used by Tasks 2–7.

- [ ] Step 1: Write failing tests for the required input contract.

    @pytest.fixture
    def fixed_wing_pack():
        return load_domain_pack(resource_path("domain-packs/fixed-wing-v1.json"))

    def test_demo_pack_declares_five_candidate_generation_and_three_disciplines():
        pack = load_domain_pack(resource_path("domain-packs/fixed-wing-v1.json"))
        assert pack["generation"]["candidate_count_min"] == 3
        assert pack["generation"]["candidate_count_max"] == 5
        assert {item["id"] for item in pack["disciplines"]} == {
            "aerodynamics", "structures", "weight_balance"
        }

    def test_demo_envelope_has_explicit_source_requirement_ids():
        payload = json.loads(resource_path(
            "examples/concept-design/fixed-wing-envelope.json"
        ).read_text(encoding="utf-8"))
        assert payload["source_requirement_ids"]
        assert payload["bounds"]["span_m"] == {"minimum": 11, "maximum": 16}

- [ ] Step 2: Run the focused tests and record the current contract.

Run:

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_demo_contracts.py -q

Expected: existing generation/disciplines pass; any missing source or Demo metadata is a focused failure to fix in this task.

- [ ] Step 3: Add only additive Demo metadata.

Keep every existing parameter name and discipline adapter. Add a semantic_mappings object to the Demo pack for mtow_kg, span_m, range_km, payload_kg, and cruise_speed_kmh. If the existing evaluator still requires mass_kg/cruise_speed_mps, map only where the pack explicitly declares the interpretation and conversion. Do not silently map an absent range_km to another parameter.

- [ ] Step 4: Run the contract and existing concept tests.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_demo_contracts.py tests/application/test_concept_design_service.py tests/application/test_layout_generation.py -q

Expected: PASS.

- [ ] Step 5: Commit.

    git add tests/application/test_demo_contracts.py src/rflp_lite/resources/domain-packs/fixed-wing-v1.json src/rflp_lite/resources/examples/concept-design/fixed-wing-envelope.json
    git commit -m "test: define concept workflow demo contract"

### Task 2: 一句话子句拆分和数值规范化

Files:
- Create: src/rflp_lite/application/requirement_clause_splitter.py
- Create: tests/application/test_requirement_clause_splitter.py
- Modify: src/rflp_lite/application/requirement_semantics.py
- Modify: src/rflp_lite/application/requirement_details.py

Interfaces:
- Consumes: str or Sequence[DocumentRegion].
- Produces: RequirementClause, NormalizedMetric, ClauseAnalysis, and Requirement-compatible payloads with stable source IDs.

- [ ] Step 1: Write the failing mixed-constraint tests.

    DEMO_TEXT = (
        "设计一型中程侦察无人机，最大起飞重量不超过500kg，"
        "航程不低于800km，翼展不超过12m，任务载荷不低于50kg，"
        "通信中断30秒后自动返航"
    )

    def test_splitter_extracts_five_numeric_constraints_and_behavior():
        analysis = RequirementClauseSplitter().analyze(DEMO_TEXT)
        metrics = {
            metric.name: (metric.operator, metric.value, metric.unit)
            for clause in analysis.clauses
            for metric in clause.normalized_metrics
        }
        assert metrics["最大起飞重量"] == ("<=", 500.0, "kg")
        assert metrics["航程"] == (">=", 800.0, "km")
        assert metrics["翼展"] == ("<=", 12.0, "m")
        assert metrics["任务载荷"] == (">=", 50.0, "kg")
        assert metrics["通信中断"] == ("==", 30.0, "s")
        assert any("自动返航" in clause.text for clause in analysis.clauses)

    def test_splitter_is_stable_for_repeated_input():
        splitter = RequirementClauseSplitter()
        assert splitter.analyze(DEMO_TEXT) == splitter.analyze(DEMO_TEXT)

    def test_operator_aliases_are_normalized():
        result = RequirementClauseSplitter().analyze(
            "质量不得大于2kg，航程至少10km，速度不高于100km/h"
        )
        assert [(m.operator, m.value, m.unit)
                for c in result.clauses for m in c.normalized_metrics] == [
            ("<=", 2.0, "kg"), (">=", 10.0, "km"), ("<=", 100.0, "km/h")
        ]

- [ ] Step 2: Run the focused tests to verify the new module is absent.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_requirement_clause_splitter.py -q

Expected: FAIL with import or missing-interface errors.

- [ ] Step 3: Implement deterministic clause and metric records.

    _OPERATOR_ALIASES = {
        "不超过": "<=", "不得大于": "<=", "不高于": "<=", "≤": "<=", "<=": "<=",
        "不低于": ">=", "不少于": ">=", "至少": ">=", "以上": ">=", "≥": ">=", ">=": ">=",
    }
    _UNIT_ALIASES = {"千克": "kg", "公斤": "kg", "米": "m", "公里": "km", "秒": "s"}

    @dataclass(frozen=True, slots=True)
    class NormalizedMetric:
        name: str
        value: float
        unit: str
        operator: str
        source_text: str

    @dataclass(frozen=True, slots=True)
    class RequirementClause:
        id: str
        source_region_id: str
        ordinal: int
        text: str
        kind: str
        normalized_metrics: tuple[NormalizedMetric, ...]

    @dataclass(frozen=True, slots=True)
    class ClauseAnalysis:
        clauses: tuple[RequirementClause, ...]
        requirements: tuple[dict[str, object], ...]
        attributes: tuple[dict[str, object], ...]
        constraints: tuple[dict[str, object], ...]

Use canonical_hash((source_region_id, ordinal, normalized_text))[:12] for clause IDs. Preserve original text and stable ordinal. Do not invoke an LLM in this module.

- [ ] Step 4: Bridge splitter output into the existing semantics/detail pipeline.

Create temporary DocumentRegion values for each clause, call extract_requirement_candidates(), then run extract_explicit_details() against the original region text. Extend the detail regexes only to cover 不得大于、不高于、至少、以上、km、km/h、s; leave existing output keys and review statuses unchanged.

- [ ] Step 5: Run focused and regression tests.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_requirement_clause_splitter.py tests/application/test_requirement_semantics.py tests/application/test_requirement_details.py tests/application/test_requirements_workbench.py -q

Expected: all PASS.

- [ ] Step 6: Commit.

    git add src/rflp_lite/application/requirement_clause_splitter.py src/rflp_lite/application/requirement_semantics.py src/rflp_lite/application/requirement_details.py tests/application/test_requirement_clause_splitter.py
    git commit -m "feat: split natural language requirements deterministically"

### Task 3: Requirement → Envelope 桥

Files:
- Create: src/rflp_lite/application/requirement_to_envelope.py
- Create: tests/application/test_requirement_to_envelope.py
- Modify: src/rflp_lite/application/parameter_rules.py

Interfaces:
- Consumes: reviewed requirement/attribute/constraint dictionaries, a validated domain pack, and optional historical schemes.
- Produces: RequirementEnvelopeResult containing an IndicatorEnvelope, field provenance, and diagnostics.

- [ ] Step 1: Write failing mapping tests.

    @pytest.fixture
    def fixed_wing_pack():
        return load_domain_pack(resource_path("domain-packs/fixed-wing-v1.json"))

    def test_build_envelope_maps_explicit_bounds_and_source_ids(fixed_wing_pack):
        result = build_envelope_from_requirements(
            fixed_wing_pack,
            [
                {"id": "REQ-MASS", "status": "accepted", "statement": "最大起飞重量不超过500kg"},
                {"id": "REQ-SPAN", "status": "accepted", "statement": "翼展不超过12m"},
                {"id": "REQ-PAYLOAD", "status": "accepted", "statement": "任务载荷不低于50kg"},
            ],
        )
        assert set(result.envelope.source_requirement_ids) == {
            "REQ-MASS", "REQ-SPAN", "REQ-PAYLOAD"
        }
        span_bound = next(item[1:] for item in result.envelope.bounds if item[0] == "span_m")
        assert span_bound == (0.0, 12.0)
        assert {item.source_kind for item in result.field_provenance} == {"explicit"}

    def test_cruise_speed_converts_kmh_to_pack_mps(fixed_wing_pack):
        result = build_envelope_from_requirements(
            fixed_wing_pack,
            [{"id": "REQ-SPEED", "status": "accepted", "statement": "巡航速度不低于72km/h"}],
        )
        speed_bound = next(item[1:] for item in result.envelope.bounds if item[0] == "cruise_speed_mps")
        assert speed_bound[0] == pytest.approx(20.0)

    def test_missing_range_parameter_is_diagnostic_not_silent_mapping(fixed_wing_pack):
        result = build_envelope_from_requirements(
            fixed_wing_pack,
            [{"id": "REQ-RANGE", "status": "accepted", "statement": "航程不低于800km"}],
        )
        assert not any(name == "range_km" for name, _ in result.envelope.parameters)
        assert any("range_km" in item for item in result.diagnostics)

- [ ] Step 2: Run the focused tests and verify they fail.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_requirement_to_envelope.py -q

Expected: FAIL because the bridge module does not exist.

- [ ] Step 3: Implement field normalization and provenance.

Use a mapping table of semantic aliases to pack parameters. For each accepted requirement, parse its explicit detail or normalized metric payload, convert units with the existing parameter-rule conversion path, and produce:

    @dataclass(frozen=True, slots=True)
    class EnvelopeFieldProvenance:
        parameter: str
        source_kind: str
        requirement_ids: tuple[str, ...]
        note: str

    @dataclass(frozen=True, slots=True)
    class RequirementEnvelopeResult:
        envelope: IndicatorEnvelope
        field_provenance: tuple[EnvelopeFieldProvenance, ...]
        diagnostics: tuple[str, ...]

Use create_indicator_envelope() for final validation. Keep provenance separate from the core IndicatorEnvelope so old payloads remain readable.

- [ ] Step 4: Add derived/suggested handling.

Call only declared safe formulas for derived values. For suggested, select the deterministic median/reference value from history or pack defaults, mark it in provenance, and never add it to a hard user bound. A missing required pack parameter produces a diagnostic and leaves the parameter absent.

- [ ] Step 5: Run focused and parameter-rule regression tests.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_requirement_to_envelope.py tests/application/test_parameter_rules.py tests/application/test_scheme_retrieval.py tests/application/test_layout_generation.py -q

Expected: all PASS.

- [ ] Step 6: Commit.

    git add src/rflp_lite/application/requirement_to_envelope.py src/rflp_lite/application/parameter_rules.py tests/application/test_requirement_to_envelope.py
    git commit -m "feat: bridge reviewed requirements to design envelopes"

### Task 4: 正式 Demo 方案数据与幂等 Seed

Files:
- Create: src/rflp_lite/application/scheme_import_mapper.py
- Create: src/rflp_lite/resources/examples/concept-design/demo-schemes.json
- Create: scripts/seed_demo_schemes.py
- Create: tests/application/test_scheme_import_mapper.py
- Modify: src/rflp_lite/application/scheme_library.py
- Modify: src/rflp_lite/application/web_facade.py
- Modify: src/rflp_lite/interface/web/routes.py
- Modify: src/rflp_lite/interface/web/api_v1.py

Interfaces:
- Consumes: normalized scheme rows and existing SchemeRecord repository methods.
- Produces: map_demo_scheme_rows(), seed_demo_schemes(), scheme count/filter queries, and an idempotent Web/API action.

- [ ] Step 1: Write mapper and idempotence tests.

    @pytest.fixture
    def fixed_wing_pack():
        return load_domain_pack(resource_path("domain-packs/fixed-wing-v1.json"))

    def test_mapper_preserves_identity_and_unknown_fields(fixed_wing_pack):
        rows = [{
            "scheme_id": "C-HIST-01", "name": "基准布局", "task_type": "中程侦察",
            "empty_mass_kg": 540, "payload_kg": 180, "span_m": 13,
            "wing_area_m2": 24, "fuselage_length_m": 9,
            "cruise_speed_kmh": 234, "customer_note": "baseline",
        }]
        result = map_demo_scheme_rows(fixed_wing_pack, rows, source="demo")
        record = result.records[0]
        assert record.id == "C-HIST-01"
        assert dict(record.parameters)["mass_kg"] == 540.0
        assert dict(record.parameters)["cruise_speed_mps"] == pytest.approx(65.0)
        assert dict(record.extensions)["name"] == "基准布局"
        assert dict(record.extensions)["task_type"] == "中程侦察"

    def test_seed_is_idempotent(temp_workspace):
        first = seed_demo_schemes(temp_workspace)
        second = seed_demo_schemes(temp_workspace)
        assert first["accepted"] >= 5
        assert second["inserted"] == 0
        assert second["skipped"] >= 5

- [ ] Step 2: Run tests to capture the current missing behavior.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_scheme_import_mapper.py -q

Expected: FAIL on the new mapper/seed interfaces.

- [ ] Step 3: Build the canonical demo dataset.

Create at least five rows with scheme_id, name, task_type, span_m, wing_area_m2, fuselage_length_m, mtow_kg, empty_mass_kg, payload_kg, range_km, and cruise_speed_kmh. Use real values from the existing historical fixtures where available; leave unavailable values empty. Make one or two rows visibly dominated by mass/span/range trade-offs. Do not add invented customer claims to the dataset.

- [ ] Step 4: Implement the mapper without adding customer-specific SchemeRecord fields.

Use existing pack mappings for evaluator parameters. Store display-only identity fields and unmapped values in SchemeRecord.extensions. Prefer a validated source scheme_id; otherwise retain the existing deterministic generated ID behavior. Return accepted/rejected/skipped diagnostics rather than raising for one malformed row.

- [ ] Step 5: Add CLI/script and Web/API initialization.

The script must accept --workspace, --pack, and --data, and print JSON. The Web action must call the same service, show “已初始化/已存在，无需重复写入”, and expose a scheme count plus task type/weight/range filters. Add API endpoints:

    POST /api/v1/workspaces/{workspace_name}/schemes/seed-demo
    GET  /api/v1/workspaces/{workspace_name}/schemes

- [ ] Step 6: Run focused scheme and repository tests.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_scheme_import_mapper.py tests/application/test_scheme_library.py tests/application/test_scheme_retrieval.py tests/adapters/test_sqlite_repository_concept.py tests/interface -q

Expected: all PASS.

- [ ] Step 7: Commit.

    git add src/rflp_lite/application/scheme_import_mapper.py src/rflp_lite/resources/examples/concept-design/demo-schemes.json scripts/seed_demo_schemes.py src/rflp_lite/application/scheme_library.py src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/api_v1.py tests/application/test_scheme_import_mapper.py
    git commit -m "feat: seed an idempotent concept scheme demo library"

### Task 5: Concept Workflow Orchestrator 与步骤状态

Files:
- Create: src/rflp_lite/application/intelligent_concept_workflow.py
- Create: tests/application/test_intelligent_concept_workflow.py
- Modify: src/rflp_lite/application/web_facade.py
- Modify: src/rflp_lite/adapters/sqlite_repository.py
- Modify: src/rflp_lite/ports/repositories.py

Interfaces:
- Consumes: Tasks 2–4 outputs, existing requirements/MBSE/concept services, evaluator registry and repository.
- Produces: ConceptWorkflowRequest, ConceptWorkflowResult, step state records, run()/resume(), and WebFacade.run_intelligent_concept_workflow().

- [ ] Step 1: Write the failure-isolation and ordering tests.

    def test_workflow_runs_in_fixed_order_and_keeps_intermediate_results(fake_services):
        result = ConceptWorkflowOrchestrator(fake_services).run(
            ConceptWorkflowRequest(workspace_name="demo", text=DEMO_TEXT, seed=42)
        )
        assert [step.key for step in result.steps] == [
            "requirements", "mbse", "envelope", "retrieval",
            "generation", "evaluation", "optimization",
        ]
        assert result.steps[-1].status == "completed"
        assert result.requirements
        assert result.envelope is not None
        assert result.recommendation["candidate_id"]

    def test_optimization_failure_preserves_first_generation(fake_services):
        fake_services.fail_at = "optimization"
        result = ConceptWorkflowOrchestrator(fake_services).run(
            ConceptWorkflowRequest(workspace_name="demo", text=DEMO_TEXT)
        )
        assert result.steps[-1].status == "failed"
        assert result.candidates
        assert result.evaluations
        assert "optimization" in result.steps[-1].diagnostics[0]

- [ ] Step 2: Run focused tests to verify the orchestrator is absent.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_intelligent_concept_workflow.py -q

Expected: FAIL with missing module/interface errors.

- [ ] Step 3: Implement immutable request, step and result DTOs.

Use these exact public shapes:

    WORKFLOW_STEPS = (
        "requirements", "mbse", "envelope", "retrieval",
        "generation", "evaluation", "optimization",
    )

    @dataclass(frozen=True, slots=True)
    class ConceptWorkflowRequest:
        workspace_name: str
        text: str = ""
        filename: str = "requirements.txt"
        document_bytes: bytes | None = None
        pack: Mapping[str, object] | str = "fixed-wing-v1"
        evaluator_profile: Mapping[str, object] | str = "development-v1"
        seed: int = 42
        demo_mode: bool = True

    @dataclass(frozen=True, slots=True)
    class WorkflowStep:
        key: str
        status: str
        input_hash: str
        result_ref: str
        diagnostics: tuple[str, ...] = ()
        started_at: str = ""
        completed_at: str = ""

    @dataclass(frozen=True, slots=True)
    class ConceptWorkflowResult:
        id: str
        status: str
        steps: tuple[WorkflowStep, ...]
        requirements: tuple[dict[str, object], ...]
        mbse: dict[str, object] | None
        envelope: dict[str, object] | None
        envelope_provenance: tuple[dict[str, object], ...]
        matches: tuple[dict[str, object], ...]
        candidates: tuple[dict[str, object], ...]
        evaluations: tuple[dict[str, object], ...]
        optimization: dict[str, object] | None
        initial_candidate_ids: tuple[str, ...]
        recommendation: dict[str, object] | None
        input_hash: str
        result_hash: str

Each step stores key, status, input_hash, result_ref, diagnostics, started_at, and completed_at. Persist the full JSON-safe result after each completed step.

- [ ] Step 4: Connect existing services in the fixed order.

Use existing analyze_artifact/merge_artifact, generate_mbse_revision, build_envelope_from_requirements, find_similar_schemes, generate_layout_candidates, evaluate_candidates, and run_optimization. Resolve packaged pack/profile aliases at the facade boundary. Do not copy their algorithms into the orchestrator.

- [ ] Step 5: Add persistence and resume behavior.

Add only the repository methods needed to save/load workflow payloads and query the latest workflow for a workspace. Keep transaction boundaries short. resume() must load the last successful intermediate state and restart at the first non-completed step; it must not rerun completed steps unless the input hash changed.

- [ ] Step 6: Run workflow, facade and repository tests.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_intelligent_concept_workflow.py tests/application/test_demo_workflow.py tests/application/test_web_facade.py tests/adapters/test_sqlite_repository_concept.py -q

Expected: all PASS.

- [ ] Step 7: Commit.

    git add src/rflp_lite/application/intelligent_concept_workflow.py tests/application/test_intelligent_concept_workflow.py src/rflp_lite/application/web_facade.py src/rflp_lite/adapters/sqlite_repository.py src/rflp_lite/ports/repositories.py
    git commit -m "feat: orchestrate the concept design workflow"

### Task 6: 真正的一轮优化与概念验收门禁

Files:
- Modify: src/rflp_lite/application/concept_design_service.py
- Modify: src/rflp_lite/application/multidisciplinary_optimization.py
- Modify: src/rflp_lite/application/concept_acceptance.py
- Create: tests/application/test_concept_optimization_loop.py

Interfaces:
- Consumes: existing candidate generator, evaluator batch and optimizer.
- Produces: initial + second-generation candidates, populated iteration records, final Pareto and stricter acceptance diagnostics. The public acceptance helper is evaluate_concept_acceptance(run: ConceptRunResult | ConceptWorkflowResult) -> dict[str, object].

- [ ] Step 1: Write failing optimization-loop tests.

    def test_demo_concept_run_adds_second_generation_candidates(demo_run):
        assert len(demo_run["initial_candidate_ids"]) == 5
        assert len(demo_run["optimization"]["iteration_records"]) >= 1
        generated = {
            item
            for _iteration, record in demo_run["optimization"]["iteration_records"]
            for item in record["candidate_ids"]
        }
        assert 2 <= len(generated) <= 3
        assert generated <= set(demo_run["optimization"]["candidate_ids"])
        assert any(record["parent_ids"]
                   for _iteration, record in demo_run["optimization"]["iteration_records"])

    def test_concept_acceptance_rejects_trace_without_real_iteration():
        result = {**demo_run, "optimization": {
            **demo_run["optimization"], "iteration_records": ()
        }}
        report = evaluate_concept_acceptance(result)
        assert report["2.2.optimization_iteration"] is False
        assert report["status"] == "failed"

- [ ] Step 2: Run tests to capture the current no-op optimization.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_concept_optimization_loop.py tests/application/test_multidisciplinary_optimization.py tests/application/test_concept_acceptance.py -q

Expected: iteration-count assertions fail because the current concept service sets the optimization budget to the initial evaluation count and returns only the first generation.

- [ ] Step 3: Make generation Parent-aware and budget a second evaluation batch.

Pass selected Pareto/ranked Parent candidates into the generator. Generate exactly 2 or 3 candidates in Demo mode using deterministic seed offsets and parameter perturbations around Parent values. Set evaluation budget to at least len(initial_evaluations) + 3 * len(pack["disciplines"]); retain all generated candidates/evaluations in the concept result.

- [ ] Step 4: Record optimization provenance.

Store each iteration as:

    (
        "1",
        {
            "parent_ids": ("FW-C-...",),
            "candidate_ids": ("FW-C-...", "FW-C-..."),
            "front_ids": ("FW-C-...",),
            "generation_index": 1,
        },
    )

Add a candidate source entry that points to the Parent candidate ID. Keep deterministic hash inputs unchanged for unchanged inputs/seeds.

- [ ] Step 5: Harden concept acceptance.

Require both a non-empty iteration and at least one generated candidate whose source Parent is in the previous candidate set. Keep formal evaluator approval checks independent and unchanged. A development-only run may pass software orchestration acceptance but must report formal_status = "development".

- [ ] Step 6: Run concept regression and acceptance tests.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_concept_optimization_loop.py tests/application/test_multidisciplinary_optimization.py tests/application/test_concept_acceptance.py tests/application/test_concept_design_service.py -q

Expected: all PASS.

- [ ] Step 7: Commit.

    git add src/rflp_lite/application/concept_design_service.py src/rflp_lite/application/multidisciplinary_optimization.py src/rflp_lite/application/concept_acceptance.py tests/application/test_concept_optimization_loop.py
    git commit -m "feat: run a real second-generation concept optimization"

### Task 7: 推荐基线选择操作

Files:
- Modify: src/rflp_lite/application/concept_design_service.py
- Modify: src/rflp_lite/application/web_facade.py
- Modify: src/rflp_lite/interface/web/routes.py
- Modify: src/rflp_lite/interface/web/api_v1.py
- Create: tests/application/test_concept_baseline_selection.py

Interfaces:
- Consumes: persisted concept run and candidate review repository.
- Produces: select_as_concept_baseline(workspace, run_id, candidate_id, rationale, selected_by) and provisional_selected audit/review state.

- [ ] Step 1: Write the failing selection test.

    def test_select_as_concept_baseline_is_not_formal_approval(concept_workspace):
        selected = select_as_concept_baseline(
            concept_workspace, run_id="FW-RUN-1", candidate_id="FW-C-03",
            rationale="Pareto 前沿且结构裕度更高", selected_by="designer"
        )
        assert selected["decision"] == "provisional_selected"
        assert selected["candidate_id"] == "FW-C-03"
        assert selected["formal_status"] == "development"

- [ ] Step 2: Run the focused test and verify the operation is absent.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_concept_baseline_selection.py -q

Expected: FAIL with missing interface errors.

- [ ] Step 3: Implement the operation and audit record.

Validate that run_id and candidate_id belong to the same concept run. Save a review payload with decision, selected_by, selected_at, rationale, run_id, and input/result hashes. Do not change DisciplineEvaluation.evidence_status or formal_status.

- [ ] Step 4: Add Web/API actions.

    POST /api/v1/workspaces/{workspace_name}/concept-runs/{run_id}/select-baseline
    POST /w/{workspace_name}/concept-design/select-baseline

Return 422 for missing candidate/run and redirect back to the same result page after success.

- [ ] Step 5: Run focused tests and commit.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_concept_baseline_selection.py tests/application/test_web_facade.py tests/interface -q
    git add src/rflp_lite/application/concept_design_service.py src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/api_v1.py tests/application/test_concept_baseline_selection.py
    git commit -m "feat: allow provisional concept baseline selection"

Expected: all PASS.

### Task 8: 一键入口、进度页和工程化结果页

Files:
- Modify: src/rflp_lite/interface/web/routes.py
- Modify: src/rflp_lite/interface/web/api_v1.py
- Modify: src/rflp_lite/application/web_facade.py
- Modify: src/rflp_lite/application/requirements_flow.py
- Modify: src/rflp_lite/interface/web/templates/dashboard.html
- Modify: src/rflp_lite/interface/web/templates/requirements-input.html
- Modify: src/rflp_lite/interface/web/templates/concept-design.html
- Modify: src/rflp_lite/interface/web/static/app.css
- Create: tests/interface/test_concept_workflow_pages.py

Interfaces:
- Consumes: Task 5 workflow DTOs and Task 7 selection action.
- Produces: visible “智能生成概念方案” entry, seven-step progress, latest-run fallback, scheme library view and human-readable result page.

- [ ] Step 1: Write page contract tests.

    def test_concept_page_without_run_id_uses_latest_workflow(client, seeded_workspace):
        response = client.get("/w/demo/concept-design")
        assert response.status_code == 200
        assert "需求理解" in response.text
        assert "历史方案检索" in response.text

    def test_result_page_contains_numeric_evaluation_and_boundary_notice(client, completed_workflow):
        response = client.get("/w/demo/concept-design")
        assert "development-only" in response.text
        assert "lift_to_drag" in response.text or "L/D" in response.text
        assert "stress_margin" in response.text or "结构裕度" in response.text
        assert "Pareto" in response.text

- [ ] Step 2: Run page tests to capture current UI gaps.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/interface/test_concept_workflow_pages.py tests/application/test_web_facade.py -q

Expected: latest-run/result-content assertions fail against the current minimal concept page.

- [ ] Step 3: Add the visible entry and unified submission.

Put the form on the dashboard or requirements input page with only text, artifact, and submit controls. Route both the visible action and legacy /requirements/run-flow into the same facade/orchestrator. Keep pack/profile defaults server-side.

- [ ] Step 4: Update latest-run fallback and progress rendering.

When run_id is empty, call facade.concept_run(workspace_name, None) and handle the no-run error with the existing empty state. Render exactly these steps:

    ①需求分析 → ②MBSE建模 → ③指标包络 → ④历史方案检索
    → ⑤候选生成 → ⑥多学科评估 → ⑦方案优选

For failed steps show the diagnostic and preserve sections whose result references are available.

- [ ] Step 5: Replace internal JSON-heavy result markup with presenters.

Build small presenter helpers in web_facade.py or a dedicated presenter module for requirements, Top 3 matches, candidate cards, numeric discipline rows, Pareto points, recommendation reason and selection state. Keep raw JSON available only behind a details/download affordance.

- [ ] Step 6: Add the boundary declaration and visual styling.

Use the exact copy:
    当前多学科结果来自 development-only 快速评估器，仅用于概念方案筛选，不作为正式工程验证依据。

Use existing CSS tokens and responsive grid styles. Add no frontend dependency.

- [ ] Step 7: Run Web regression and commit.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/interface/test_concept_workflow_pages.py tests/application/test_web_facade.py tests/application/test_requirements_flow.py tests/application/test_concept_design_service.py -q
    git add src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/api_v1.py src/rflp_lite/application/web_facade.py src/rflp_lite/application/requirements_flow.py src/rflp_lite/interface/web/templates/dashboard.html src/rflp_lite/interface/web/templates/requirements-input.html src/rflp_lite/interface/web/templates/concept-design.html src/rflp_lite/interface/web/static/app.css tests/interface/test_concept_workflow_pages.py
    git commit -m "feat: expose the one-click concept workflow in Web"

Expected: all PASS.

### Task 9: 文档样例、Gold、Demo extra 和 README 收口

Files:
- Create: src/rflp_lite/resources/examples/customer-acceptance/demo-requirements.docx
- Create: src/rflp_lite/resources/examples/customer-acceptance/demo-metrics.pdf
- Create: src/rflp_lite/resources/examples/customer-acceptance/demo-scan.pdf
- Create: src/rflp_lite/resources/examples/customer-acceptance/demo-mixed-constraints.docx
- Create: src/rflp_lite/resources/examples/customer-acceptance/corpus-manifest.json
- Modify: pyproject.toml
- Modify: README.md
- Modify: src/rflp_lite/application/acceptance_gold.py
- Modify: src/rflp_lite/application/acceptance_harness.py
- Create: tests/application/test_demo_corpus.py

Interfaces:
- Consumes: existing document readers, OCR diagnostics, acceptance gold schema.
- Produces: four real short demo documents, complete manifest/Gold entries, installable .[demo] dependency set and documented run command.

- [ ] Step 1: Write corpus and dependency tests.

    def test_demo_corpus_contains_four_readable_files():
        manifest = json.loads(corpus_manifest.read_text(encoding="utf-8"))
        assert len(manifest["documents"]) == 4
        assert all(Path(item["path"]).is_file() for item in manifest["documents"])
        assert {item["kind"] for item in manifest["documents"]} == {
            "docx", "digital_pdf", "scanned_pdf", "mixed_constraints"
        }

    def test_demo_extra_contains_document_web_evidence_and_optimization_dependencies():
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        demo = set(project["project"]["optional-dependencies"]["demo"])
        assert any(item.startswith("fastapi") for item in demo)
        assert any(item.startswith("pdfplumber") for item in demo)
        assert any(item.startswith("ortools") for item in demo)
        assert any(item.startswith("prance") for item in demo)

- [ ] Step 2: Run the focused tests and record missing corpus/dependency behavior.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_demo_corpus.py -q

Expected: FAIL before the four files and demo extra are added.

- [ ] Step 3: Create short real documents and Gold anchors.

Create 2–5 page files using the existing document-generation/rendering utilities or a deterministic fixture builder. Include numeric and mixed constraints in the source text, a digital PDF, a scan-like PDF that exercises OCR, and a DOCX with a table. Update the manifest from planned to actual paths, hashes, parser expectations, and Gold anchors. Do not mark documents as complete without checking their bytes exist.

- [ ] Step 4: Add the concrete demo dependency extra.

Copy the current runtime dependencies from schema, evidence, opt, web, and documents into one explicit demo list in pyproject.toml; keep the existing extras unchanged. Update package data if the new files are not already covered.

- [ ] Step 5: Update README with the现场演示 command.

    .venv/bin/python -m pip install -e '.[demo]'
    .venv/bin/rflp init .local-demo
    .venv/bin/rflp web --host 127.0.0.1 --port 8000

Describe the visible one-click form, the seven stages, the development-only boundary, and the provisional baseline distinction.

- [ ] Step 6: Run corpus, acceptance, packaging and commit.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_demo_corpus.py tests/application/test_acceptance_harness.py tests/application/test_acceptance_gold.py -q
    .venv/bin/python -m build --wheel --no-isolation
    git add src/rflp_lite/resources/examples/customer-acceptance pyproject.toml README.md src/rflp_lite/application/acceptance_gold.py src/rflp_lite/application/acceptance_harness.py tests/application/test_demo_corpus.py
    git commit -m "chore: package the concept workflow demo corpus"

Expected: focused tests PASS and wheel build succeeds.

### Task 10: 端到端验收、全回归和交付检查

Files:
- Create: tests/e2e/test_concept_workflow_demo.py
- Modify: scripts/verify_full.py
- Modify: docs/DEVELOPMENT_STATUS.md
- Modify: README.md

Interfaces:
- Consumes: all previous tasks through public facade/API/application interfaces.
- Produces: deterministic full-chain acceptance test and documented delivery status.

- [ ] Step 1: Write the end-to-end test.

    def test_one_click_concept_workflow_reaches_provisional_baseline(tmp_path):
        workspace = create_managed_workspace(tmp_path, "demo")
        seed_demo_schemes(workspace.path)
        first = facade.run_intelligent_concept_workflow(
            "demo", text=DEMO_TEXT, seed=42, demo_mode=True
        )
        assert len(first["requirements"]) >= 5
        assert first["mbse"]
        assert first["envelope"]["source_requirement_ids"]
        assert len(first["matches"]) >= 3
        assert len(first["initial_candidate_ids"]) == 5
        assert len(first["candidates"]) >= 7
        assert len(first["evaluations"]) >= len(first["candidates"]) * 3
        assert first["optimization"]["iteration_records"]
        assert first["recommendation"]["candidate_id"]
        selected = facade.select_as_concept_baseline(
            "demo", first["id"], first["recommendation"]["candidate_id"],
            rationale="Demo recommendation", selected_by="test"
        )
        assert selected["decision"] == "provisional_selected"

- [ ] Step 2: Run the E2E test and fix only integration defects.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/e2e/test_concept_workflow_demo.py -q

Expected: PASS with a fresh temporary workspace; no network or LLM configuration required.

- [ ] Step 3: Add deterministic repeatability and failure-isolation assertions.

Run the same input/seed twice in fresh workspaces and compare workflow/result hashes. Inject an evaluator failure and assert requirements, MBSE, Envelope, first-generation candidates and diagnostics remain available.

- [ ] Step 4: Run the complete project verification suite.

    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest -v
    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m compileall -q src
    RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/lint-imports
    .venv/bin/check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json

Expected: all existing and new tests pass; import-linter and schema validation pass.

- [ ] Step 5: Update delivery status.

Record the implemented 1.1→2.2 workflow, demo command, exact development-only boundary, and explicit 3.x non-goals in docs/DEVELOPMENT_STATUS.md. Do not claim formal evaluator approval.

- [ ] Step 6: Review changed files and commit delivery notes.

    git status --short
    git diff --stat HEAD~1
    git diff --check
    git add tests/e2e/test_concept_workflow_demo.py scripts/verify_full.py docs/DEVELOPMENT_STATUS.md README.md
    git commit -m "test: close the one-click concept workflow acceptance"

Expected: only intended source/tests/docs changes are staged; existing user files remain unstaged.

---

## Plan Self-Review

- Requirement 1 covered by Tasks 1–3 and E2E Task 10.
- Requirement 2 covered by Task 3 and E2E envelope assertions.
- Requirement 3 covered by Task 4 and its idempotence tests.
- Requirement 4 covered by Task 5 and failure-isolation tests.
- Requirement 5 covered by Task 6 and concept acceptance gates.
- Requirement 6–7 covered by Tasks 7–8.
- Requirement 8 covered by Task 7 and formal/development separation tests.
- Requirement 9 covered by Task 9 corpus/Gold work.
- Requirement 10 covered by Tasks 9–10.
- No task implements 3.x.
- No step relies on TODO, TBD, unspecified files, or an undefined neighboring interface.
