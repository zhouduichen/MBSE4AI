# AI4MBSE Harness v2.0 Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 按 AI4MBSE Harness 代码级轻量化重构施工方案 v2.0，将当前多路径 RFLP-Lite 原型收敛为单一 AI4MBSE Domain Harness。

**Architecture:** 在现有 rflp_lite 包内采用绞杀式迁移，保留成熟底盘，依次建立 Typed Model Graph、Repository v2、4 Phase Workflow、Gate/Repair、Retrieval 和窄 Application Services。每个新路径接管后立即删除对应旧路径，最终只保留一个 Model Truth、一个 Orchestrator 和一个主工作台。

**Tech Stack:** Python 3.11+, dataclasses/typing, SQLite/FTS5, FastAPI/Jinja2/HTMX, existing OpenAI-compatible/Ollama runtime, JSON Schema, pytest/Hypothesis, ruff, pyright, import-linter, setuptools build。

## Global Constraints

- 保留 rflp_lite 包名，v2.0 稳定后再做纯包名重命名。
- 不引入 Neo4j、PostgreSQL、Redis 或重复的 schema framework。
- ModelGraph 是唯一模型真源；图、矩阵、SysML 只从 ModelGraph 投影或导出。
- AI 只能通过 ADD/UPDATE/RELATE/DEPRECATE Patch 修改模型，Patch 必须先 Validate 再 Apply。
- 4 Phase + Closure 通过数据化 TaskSpec 实现，不创建大量 Agent class。
- 外部 Web Search optional；失败只能生成 ExternalEvidenceGap，不得终止 Workflow。
- locked 或 user-modified Entity 禁止 automatic patch overwrite。
- 当前未提交修改仅限 OCR、workspace 中文名、两个 Web 模板及对应测试；不得覆盖、重置或纳入无关删除。
- 每个任务完成独立测试和提交；删除功能时同步删除其测试、资源、extra 和路由。

## File Map

### Create

- src/rflp_lite/domain/entities.py — EntityKind、EntityMeta 和通用实体封装。
- src/rflp_lite/domain/lifecycle.py — LifecycleStage/Transition。
- src/rflp_lite/domain/requirements.py — v2 Requirement。
- src/rflp_lite/domain/behavior.py — Scenario、Activity、Function、L/P、Interface、V&V。
- src/rflp_lite/domain/relations.py — Relation predicate 白名单和类型规则。
- src/rflp_lite/domain/model.py — ModelGraph、Revision、Patch 和 CAS 语义。
- src/rflp_lite/methodology/{contracts,tasks,workflow,context,coverage,gates,repair}.py — Workflow 核心。
- src/rflp_lite/methodology/validators/*.py — 确定性和语义 Validators。
- src/rflp_lite/runtime/{port,structured_model,openai_compatible}.py — TaskExecutionRequest 和 RuntimePort。
- src/rflp_lite/repository/{port,sqlite,migrations}.py — v2 repository 端口、SQLite 实现和导入迁移。
- src/rflp_lite/application/{project_service,analysis_service,model_service,evidence_service,render_service,settings_service}.py — 窄 Application Services。
- src/rflp_lite/retrieval/{planner,local_fts,history,web_port,evidence}.py — Coverage-driven Retrieval。
- src/rflp_lite/diagrams/{views,compiler,renderers}.py — ModelGraph → ViewSpec → Renderer。
- src/rflp_lite/evals/ — Acceptance/Evaluation 资产。
- tests/domain/test_metamodel_v2.py、tests/methodology/、tests/repository/、tests/retrieval/、tests/e2e/fixtures/campus_delivery_robot.json — 新路径测试和 Golden fixture。

### Modify

- pyproject.toml、README.md、PRODUCT.md、docs/CURRENT_ARCHITECTURE.md — Core 边界、extra、入口和目录说明。
- src/rflp_lite/domain/__init__.py、src/rflp_lite/ports/{repositories,generative_model,knowledge_datasets,jobs}.py — 公共契约。
- src/rflp_lite/adapters/persistence/migrations.py、src/rflp_lite/adapters/sqlite_repository.py、src/rflp_lite/adapters/sqlite_job_repository.py — v2 schema 和 durable runtime 迁移。
- src/rflp_lite/application/mbse/pipeline.py、src/rflp_lite/application/mbse/builders/*.py、src/rflp_lite/application/intelligence/*.py — 新 Workflow 接管和旧路径拆除。
- src/rflp_lite/interface/cli.py、src/rflp_lite/interface/web/{routes,api_v1,dto,presenters}.py、模板和 bootstrap/container.py — 资源型接口和 composition root。
- architecture_budget.json、pyrightconfig.json、ruff.toml、.importlinter、scripts/architecture_metrics.py — 最终门禁。

### Delete after migration gate

- Concept/MDO/Layout：application/concept_acceptance.py、concept_design_service.py、intelligent_concept_workflow.py、layout_generation.py、layout_render.py、layout_evidence.py、multidisciplinary_optimization.py、parameter_rules.py、requirement_to_envelope.py、scheme_*.py、discipline_batch.py、evaluator_approval.py、domain/concept_design.py、ports/discipline.py、相关 adapters/resources/tests。
- Project Bridge/Test Runner：application/project_bridge.py、adapters/project_scanner.py、adapters/test_executor.py、adapters/test_execution_config.py、adapters/test_cache.py、adapters/test_limits.py、ports/project_analysis.py、ports/test_execution.py、相关 tests。
- Legacy vertical slice：domain/baseline.py、simulation/engine.py、application/synthesize.py、旧 demo 路径、ports/contracts.py、旧 acceptance runtime。
- Legacy orchestration：application/requirements_workbench.py、application/web_facade.py、旧 workbench、旧独立 discovery/review、application/mbse/legacy_builder.py、旧 block merge/reconcile。

## Task 1: PR-00 Baseline Lock

**Files:**
- Create: tests/e2e/fixtures/campus_delivery_robot.json, tests/e2e/test_baseline_fixture.py
- Modify: scripts/verify_full.py, docs/DEVELOPMENT_STATUS.md

**Interfaces:**
- Produces the baseline commands and Golden fixture consumed by every later task.

- [ ] Step 1: Add the deterministic Golden fixture

~~~json
{
  "system": "校园无人配送机器人",
  "stakeholders": ["学生", "运营人员", "校园安全监管方", "维护人员"],
  "lifecycle_stages": ["规划", "部署", "运行", "维护", "退役"],
  "scenarios": ["正常配送", "障碍绕行", "低电量返航", "通信丢失恢复"],
  "requirements": [
    {"id": "req-availability", "statement": "系统应支持校园配送任务", "verification_method": "demonstration"},
    {"id": "req-maintenance", "statement": "系统应支持维护人员进行故障处置", "verification_method": "inspection"}
  ]
}
~~~

- [ ] Step 2: Add the fixture integrity test

~~~python
def test_campus_delivery_robot_fixture_has_lifecycle_and_failure_coverage():
    fixture = json.loads(Path("tests/e2e/fixtures/campus_delivery_robot.json").read_text())
    assert fixture["lifecycle_stages"] == ["规划", "部署", "运行", "维护", "退役"]
    assert "通信丢失恢复" in fixture["scenarios"]
    assert {item["id"] for item in fixture["requirements"]} == {
        "req-availability", "req-maintenance"
    }
~~~

- [ ] Step 3: Record the baseline without changing behavior

Run: .venv/bin/python -m pytest -q && .venv/bin/python -m compileall -q src && .venv/bin/python scripts/architecture_metrics.py

Expected: all current tests pass, compileall exits 0, and metrics are recorded in docs/DEVELOPMENT_STATUS.md.

- [ ] Step 4: Commit only the baseline files

~~~bash
git add tests/e2e/fixtures/campus_delivery_robot.json tests/e2e/test_baseline_fixture.py scripts/verify_full.py docs/DEVELOPMENT_STATUS.md
git commit -m "chore: lock AI4MBSE refactor baseline"
~~~

## Task 2: PR-01 Product Cut

**Files:**
- Modify: PRODUCT.md, README.md, docs/CURRENT_ARCHITECTURE.md, pyproject.toml
- Test: tests/architecture/test_product_boundary.py

- [ ] Step 1: Replace the product chain description with Project → Documents/Evidence → 4 Phase Workflow → ModelGraph → Gate/Repair → View/Export; mark Concept/MDO, Project Bridge/Test Runner, old Simulation/Baseline/TaskContract, and MLflow as external/plugin-only.
- [ ] Step 2: Add this boundary test.

~~~python
def test_product_docs_define_single_model_truth():
    text = Path("PRODUCT.md").read_text(encoding="utf-8")
    assert "ModelGraph" in text
    assert "Concept/MDO" in text
    assert "Model Truth" in text
~~~

- [ ] Step 3: Add ai4mbse = rflp_lite.interface.cli:entrypoint while keeping rflp during the migration window; remove obsolete package-data only after Tasks 3–4 delete those resources.
- [ ] Step 4: Run .venv/bin/python -m pytest tests/architecture/test_product_boundary.py -q and commit the product-boundary files. Expected: PASS.

## Task 3: PR-02 Delete Concept MDO and Layout

**Files:**
- Delete: all Concept/MDO/Layout files in the Delete-after-migration map.
- Modify: bootstrap/container.py, interface/cli.py, interface/web/routes.py, interface/web/api_v1.py, pyproject.toml.
- Delete tests: matching test_concept*, test_layout*, test_scheme*, test_multidisciplinary_optimization.py, test_discipline_batch.py, test_evaluator_approval.py.

- [ ] Step 1: Run rg -n "concept|layout|scheme|discipline|optimizer|ortools|OR-Tools" src tests pyproject.toml and assign every match to deletion or replacement.
- [ ] Step 2: Remove concept/layout route and CLI callers, bootstrap dependencies, opt extra, and concept package-data.
- [ ] Step 3: Use explicit git rm paths from the Delete-after-migration map; do not use a broad wildcard outside those paths.
- [ ] Step 4: Run .venv/bin/python -m pytest -q and rg -n "concept|layout|scheme|discipline|ortools" src/rflp_lite pyproject.toml. Expected: only documentation/plugin boundary text remains and tests pass.
- [ ] Step 5: Commit with git commit -m "refactor: remove concept optimization core".

## Task 4: PR-03/04 Delete Project Bridge, Test Runner, Legacy Demo and Tracking

**Files:**
- Delete: application/project_bridge.py, adapters/project_scanner.py, adapters/test_executor.py, adapters/test_execution_config.py, adapters/test_cache.py, adapters/test_limits.py, ports/project_analysis.py, ports/test_execution.py, simulation/engine.py, domain/baseline.py, application/synthesize.py, ports/contracts.py, adapters/mlflow_tracking.py, ports/tracking.py.
- Modify: domain/models.py, ports/repositories.py, governance/run_manifest.py, pyproject.toml, interface/cli.py, Web routes/API.
- Create: src/rflp_lite/evals/__init__.py, src/rflp_lite/evals/acceptance.py, tests/evals/test_acceptance.py.

- [ ] Step 1: Implement run_acceptance(graph: ModelGraph, fixture: Mapping[str, object]) -> AcceptanceReport; report only contains status, coverage, diagnostics, and traceability.
- [ ] Step 2: Replace run manifest fields with methodology_version, model_profile, runtime, evidence_hash, and per-step hashes.
- [ ] Step 3: Remove project source scanning/test execution/MLflow commands and routes; keep VerificationCase as a typed model.
- [ ] Step 4: Add a test that acceptance has no returncode or project execution result, then run .venv/bin/python -m pytest tests/evals tests/domain -q.
- [ ] Step 5: Commit with git commit -m "refactor: remove bridge runner demo and tracking core".

## Task 5: PR-05 Typed Metamodel v0.2

**Files:**
- Create: domain/entities.py, lifecycle.py, behavior.py, relations.py, model.py.
- Modify: domain/requirements.py, domain/__init__.py, ports/repositories.py.
- Test: tests/domain/test_metamodel_v2.py, tests/domain/test_relations_v2.py.

**Interfaces:**

~~~python
class EntityKind(StrEnum): ...
class EntityStatus(StrEnum): ...
class Producer(StrEnum): ...
@dataclass(frozen=True, slots=True)
class EntityMeta: ...
@dataclass(frozen=True, slots=True)
class Entity: meta: EntityMeta; payload: Mapping[str, object]
@dataclass(frozen=True, slots=True)
class Requirement: ...
@dataclass(frozen=True, slots=True)
class Relation: id: str; source_id: str; predicate: RelationPredicate; target_id: str; evidence_ids: tuple[str, ...]
@dataclass(frozen=True, slots=True)
class ModelGraph: entities: tuple[Entity, ...]; relations: tuple[Relation, ...]; revision: int
~~~

- [ ] Step 1: Write tests for status, stable identity, confidence range, missing metric, and relation endpoint failure.
- [ ] Step 2: Implement frozen dataclasses, stable canonical IDs, non-empty IDs/names, tuples for provenance, and Requirement.parameter_gap == "TBD" when unsupported performance evidence is absent.
- [ ] Step 3: Encode the document predicate whitelist and source-kind → predicate → target-kind matrix in relations.py.
- [ ] Step 4: Run .venv/bin/python -m pytest tests/domain/test_metamodel_v2.py tests/domain/test_relations_v2.py -q. Expected: PASS.
- [ ] Step 5: Commit with git commit -m "feat: add typed MBSE metamodel v2".

## Task 6: PR-06 Repository v2 and SQLite Migration

**Files:**
- Create: repository/__init__.py, port.py, sqlite.py, migrations.py, import_v1.py.
- Modify: adapters/persistence/migrations.py, adapters/sqlite_repository.py, adapters/sqlite_job_repository.py, ports/repositories.py.
- Test: tests/repository/test_sqlite_model_repository.py, test_import_v1.py, test_patch_cas.py.

**Interfaces:**

~~~python
class ModelRepository(Protocol):
    def load_graph(self, project_id: str) -> ModelGraph: ...
    def list_entities(self, project_id: str, kind: EntityKind | None = None) -> tuple[Entity, ...]: ...
    def append_patch(self, project_id: str, patch: Patch, expected_revision: int) -> Revision: ...
    def list_issues(self, project_id: str) -> tuple[Issue, ...]: ...

class RunRepository(Protocol):
    def create_run(self, run: Run) -> None: ...
    def update_step(self, run_id: str, step: Step) -> None: ...
    def load_run(self, project_id: str, run_id: str) -> Run | None: ...
~~~

- [ ] Step 1: Add schema version 2, the 12 target tables, foreign keys, WAL mode, and indexes by project/kind, project/predicate, and revision.
- [ ] Step 2: Test stale-revision rejection and locked-entity update rejection.
- [ ] Step 3: Persist Patch operations, new revision, snapshot hash, audit event, and issues in one transaction; reject the complete transaction on invalid operation.
- [ ] Step 4: Implement one-time v1 importer for workbench/elements/relations/evidence/jobs/job_blocks; emit diagnostics for dropped fields and never write old tables after import.
- [ ] Step 5: Run .venv/bin/python -m pytest tests/repository tests/adapters/test_sqlite_migrations.py -q. Expected: fresh v2 database and old fixture import pass.
- [ ] Step 6: Commit with git commit -m "feat: add v2 model graph repository".

## Task 7: PR-07 Workflow Skeleton

**Files:**
- Create: methodology/__init__.py, contracts.py, tasks.py, workflow.py, context.py, validators/{__init__,schema,identity,reference,relation}.py.
- Create tests/methodology/test_workflow.py and test_context_contract.py.
- Modify: ports/jobs.py and bootstrap/container.py.

**Interfaces:**

~~~python
@dataclass(frozen=True, slots=True)
class TaskSpec:
    id: str; phase: Phase; input_kinds: frozenset[EntityKind]; output_kinds: frozenset[EntityKind]
    context_query: ContextQuery; prompt_template_id: str; output_schema_id: str
    tools: tuple[str, ...]; validators: tuple[str, ...]; max_attempts: int
    failure_routes: tuple[FailureRoute, ...]; completion_condition: CompletionCondition

class WorkflowRunner:
    def run(self, project_id: str, phase: Phase | None = None) -> RunSummary: ...
    def resume(self, project_id: str, run_id: str) -> RunSummary: ...
    def repair(self, project_id: str, issue_id: str) -> RunSummary: ...
~~~

- [ ] Step 1: Test fake-task run/resume/degraded/idempotency/lease recovery.
- [ ] Step 2: Implement states queued, running, degraded, failed, completed, repairing, and cancelled; keep lease/retry durable in SQLite.
- [ ] Step 3: Implement typed ContextBundle and reject queries outside TaskSpec input allowlists.
- [ ] Step 4: Run .venv/bin/python -m pytest tests/methodology -q. Expected: PASS.
- [ ] Step 5: Commit with git commit -m "feat: add methodology workflow runner skeleton".

## Task 8: PR-08 Operational Context

**Files:**
- Create: methodology/stages/operational.py, resources/methodology/operational.json.
- Modify: methodology/tasks.py and application/intelligence/analysis_blocks.py.
- Test: tests/methodology/test_operational_context.py.

- [ ] Step 1: Register SystemDefinition, StakeholderAnalysis, StakeholderRequirements, and LifecycleAnalysis with exact input/output kinds and strict schemas.
- [ ] Step 2: Test that the runner creates LifecycleStage and Stakeholder entities and reports O-Gate.
- [ ] Step 3: Convert document parser output to typed source-region/evidence context; never pass complete legacy state or domain packs to prompts.
- [ ] Step 4: Run .venv/bin/python -m pytest tests/methodology/test_operational_context.py tests/adapters/test_document_intelligence.py -q and commit with git commit -m "feat: implement operational context stages".

## Task 9: PR-09 Operational Scenario Chain

**Files:**
- Modify: methodology/stages/operational.py, methodology/tasks.py, domain/behavior.py.
- Create: tests/methodology/test_operational_scenarios.py.
- Delete after callers migrate: application/scenarios.py, application/use_case_modeling.py, old scenario merge/review modules and matching tests.

- [ ] Step 1: Register ScenarioHypothesis, UseCase, OperationalScenario, Activity, and SystemRequirementDerivation.
- [ ] Step 2: Test that ScenarioHypothesis remains candidate and OperationalScenario contains external actors/exchanges only, with no internal component IDs.
- [ ] Step 3: Derive requirements from Activity details with derivedFrom relations and preserve source/evidence provenance.
- [ ] Step 4: Migrate callers to AnalysisService/WorkflowRunner, delete old scenario/use-case modules when rg finds no imports, run .venv/bin/python -m pytest tests/methodology/test_operational_scenarios.py tests/domain -q, and commit with git commit -m "feat: close operational CESAM workflow".

## Task 10: PR-10 O-Gate Coverage and Recursive Repair

**Files:**
- Create: methodology/coverage.py, gates.py, repair.py, validators/lifecycle.py, validators/coverage.py, validators/operational.py.
- Test: tests/methodology/test_coverage_repair.py and test_operational_gate.py.
- Modify old coverage_audit.py and semantic_validator.py only until imports are migrated.

- [ ] Step 1: Implement CoverageReport for Stakeholder×Lifecycle, Lifecycle×ScenarioType, Scenario×UseCase/Activity, Requirement×Verification, and RFLP coverage.
- [ ] Step 2: Test missing maintenance/failure routes to Phase.OPERATIONAL and produces local operations.
- [ ] Step 3: Implement root-cause classification, minimum rollback selection, local Patch generation, Validate, CAS Apply, and affected-task rerun.
- [ ] Step 4: Test locked repair neighborhood returns human-review issue and writes no update.
- [ ] Step 5: Run .venv/bin/python -m pytest tests/methodology/test_coverage_repair.py tests/methodology/test_operational_gate.py -q and commit with git commit -m "feat: add coverage gates and recursive patch repair".

## Task 11: PR-11 Functional Phase and F-Gate

**Files:**
- Create: methodology/stages/functional.py, methodology/validators/functional.py.
- Modify: domain/behavior.py, methodology/tasks.py, application/mbse/builders/functional.py.
- Test: tests/methodology/test_functional_phase.py.

- [ ] Step 1: Register FunctionIdentification, FunctionalDecomposition, FunctionalInteraction, FunctionalScenario, and FunctionalRequirement; exclude concrete physical candidates from context.
- [ ] Step 2: Test that accepted operational requirements drive the phase and no physical allocation is emitted.
- [ ] Step 3: Add Function/FunctionalFlow/FunctionalScenario through Patch using refines, decomposes, exchangesWith, and satisfiedBy relations.
- [ ] Step 4: Run .venv/bin/python -m pytest tests/methodology/test_functional_phase.py -q and commit with git commit -m "feat: implement functional phase and gate".

## Task 12: PR-12 Logical Physical Phase and P-Gate

**Files:**
- Create: methodology/stages/logical_physical.py, methodology/validators/rflp.py.
- Modify: domain/behavior.py, methodology/tasks.py, application/mbse/builders/{logical,physical,relations}.py.
- Test: tests/methodology/test_logical_physical_phase.py.

- [ ] Step 1: Implement LogicalAnalysis and PhysicalCandidates; allow multiple PhysicalBlock candidates per LogicalComponent.
- [ ] Step 2: Represent trade-off as typed candidate metadata and allocation/realization relations; do not reintroduce OR-Tools.
- [ ] Step 3: Reject P-Gate when accepted requirements do not trace Requirement→Function→LogicalComponent→PhysicalBlock or physical output precedes functional predecessors.
- [ ] Step 4: Run .venv/bin/python -m pytest tests/methodology/test_logical_physical_phase.py -q and commit with git commit -m "feat: implement logical physical phase".

## Task 13: PR-13 Assurance Phase and Global Gate

**Files:**
- Create: methodology/stages/assurance.py, methodology/validators/{verification,evidence,semantic}.py.
- Modify: domain/behavior.py, domain/sequence.py, application/sequence_modeling.py, application/traceability.py.
- Test: tests/methodology/test_assurance_phase.py and test_global_gate.py.

- [ ] Step 1: Register Interface, Sequence, State, Hazard, FailureMode, VerificationCase, and ValidationCase tasks; retain FMEA/STPA as typed hooks only.
- [ ] Step 2: Require VerificationCase or explicit waiver for every accepted Requirement and source locator for every evidence-backed relation.
- [ ] Step 3: Implement reverse feasibility and Global Gate result with issue code, affected IDs, minimum rollback Phase, and local Patch plan.
- [ ] Step 4: Run .venv/bin/python -m pytest tests/methodology/test_assurance_phase.py tests/methodology/test_global_gate.py -q and commit with git commit -m "feat: implement assurance phase and global gate".

## Task 14: PR-14 Remove Architecture Block and Legacy Merge

**Files:**
- Modify: application/intelligence/analysis_blocks.py, block_schemas.py, pack_composition.py.
- Delete after import graph is clear: merge/architecture.py, architecture_reconciler.py, block-specific merge modules, reconciliation.py, review.py, validated_result.py.
- Test: tests/methodology/test_no_architecture_block.py and migrated TaskSpec contract tests.

- [ ] Step 1: Assert the catalog has no architecture task whose outputs cross Function, LogicalComponent, and PhysicalBlock at once.
- [ ] Step 2: Route all task outputs through PatchValidator and ModelRepository CAS; delete block-specific merge dispatch.
- [ ] Step 3: Run .venv/bin/python -m pytest tests/methodology tests/contracts -q and rg -n "architecture_reconciler|merge\.architecture|analysis_blocks" src/rflp_lite tests. Expected: only TaskSpec implementation/tests remain.
- [ ] Step 4: Commit with git commit -m "refactor: replace architecture block with phase tasks".

## Task 15: PR-15 Delete Legacy Builder and Typed Projection

**Files:**
- Modify: application/mbse/pipeline.py, mbse_modeling.py, mbse_semantics.py, mbse_views.py.
- Delete after migration: application/mbse/legacy_builder.py and empty builder projections with no callers.
- Test: tests/application/mbse/test_builder_pipeline.py and tests/architecture/test_no_legacy_builder.py.

- [ ] Step 1: Implement compile_model_view(graph: ModelGraph, view_id: str) -> ViewSpec; it cannot call a legacy builder or consume the old analysis dictionary.
- [ ] Step 2: Add this guard.

~~~python
def test_formal_pipeline_does_not_import_legacy_builder():
    source = Path("src/rflp_lite/application/mbse/pipeline.py").read_text()
    assert "legacy_builder" not in source
~~~

- [ ] Step 3: Migrate view tests to typed graph fixtures and assert IDs and predicates survive RFLP, sequence, matrix, and SysML projections.
- [ ] Step 4: Run .venv/bin/python -m pytest tests/application/mbse tests/architecture/test_no_legacy_builder.py -q and rg -n "legacy_builder|build_legacy_mbse" src tests. Expected: no formal import remains.
- [ ] Step 5: Commit with git commit -m "refactor: compile views directly from model graph".

## Task 16: PR-16 Retrieval v1

**Files:**
- Create: retrieval/{__init__,planner,local_fts,history,web_port,evidence}.py.
- Modify: ports/knowledge_datasets.py, application/knowledge_retrieval.py, application/knowledge_library.py, repository migrations.
- Test: tests/retrieval/test_fts.py, test_planner.py, test_external_optional.py.

**Interfaces:**

~~~python
class RetrievalPlanner(Protocol):
    def plan(self, gap: KnowledgeGap, context: ContextBundle) -> tuple[RetrievalTask, ...]: ...

class EvidenceRetriever(Protocol):
    def search(self, task: RetrievalTask) -> tuple[EvidenceCandidate, ...]: ...
    def extract(self, candidate: EvidenceCandidate) -> Evidence: ...
~~~

- [ ] Step 1: Add project-scoped FTS5 indexes for source region text, entity/payload text, and Evidence claims/excerpts.
- [ ] Step 2: Implement source priority User Documents > Historical Projects > Local FTS > Web and stop after two low-yield rounds.
- [ ] Step 3: Test Web failure returns ExternalEvidenceGap, workflow_blocked == False, and reduced confidence.
- [ ] Step 4: Run .venv/bin/python -m pytest tests/retrieval -q and commit with git commit -m "feat: add coverage driven evidence retrieval".

## Task 17: PR-17 Runtime and Application Services

**Files:**
- Create: runtime/{__init__,port,structured_model,openai_compatible}.py, application/{project_service,analysis_service,model_service,evidence_service,render_service,settings_service}.py.
- Modify: ports/generative_model.py, application/llm_profiles.py, bootstrap/container.py.
- Test: tests/runtime/test_task_execution.py and tests/application/test_services.py.

- [ ] Step 1: Add TaskExecutionRequest with task_id, methodology_version, context_bundle, evidence_bundle, output_contract, token_budget, and tool_policy; RuntimePort.execute returns TaskExecutionResponse.
- [ ] Step 2: Convert internally to existing GenerationRequest and preserve provider/model/input/output hashes and one JSON repair.
- [ ] Step 3: Test service ownership: ProjectService paths, AnalysisService runner invocation, ModelService graph/Patch, EvidenceService retrieval, RenderService ViewCompiler, SettingsService profiles.
- [ ] Step 4: Enforce that services do not import WebFacade, routes, legacy builder, or concrete SQLite outside composition root.
- [ ] Step 5: Run .venv/bin/python -m pytest tests/runtime tests/application/test_services.py -q and commit with git commit -m "feat: isolate runtime and application services".

## Task 18: PR-17/18 Resource API, Five Pages, and WebFacade Removal

**Files:**
- Modify: interface/web/{routes,api_v1,dto,presenters,app}.py, templates, interface/cli.py.
- Delete after caller count is zero: application/web_facade.py, requirements_workbench.py, old workbench modules, discovery routes/API, entity-specific route tests.
- Create/modify: tests/interface/web/test_resource_api.py, tests/interface/test_cli_v2.py, five page templates.

- [ ] Step 1: Implement the ten resource routes from the design spec using service dependencies; entity PATCH requires expected revision and returns 409 on CAS conflict.
- [ ] Step 2: Implement project create/ingest, analyze run/status, model export, issue list, repair run, and model-profile list/save/activate; remove old demo/concept/test/mlflow/discovery/baseline/task parsers.
- [ ] Step 3: Converge pages to Projects, Analysis, MBSE Model, Evidence & Issues, Settings with shared Inspector/Presenter and LifecycleStage filter/badge/matrix.
- [ ] Step 4: Run rg -n "WebFacade|requirements_workbench|discovery_routes|discovery_api" src tests. Expected: only migration checklist text remains.
- [ ] Step 5: Delete old paths, run .venv/bin/python -m pytest tests/interface tests/application/test_services.py -q, and commit with git commit -m "refactor: converge web cli and application paths".

## Task 19: PR-19 Final Cleanup and CI Gates

**Files:**
- Modify: pyproject.toml, architecture_budget.json, pyrightconfig.json, ruff.toml, .importlinter, scripts/architecture_metrics.py, README.md, docs/CURRENT_ARCHITECTURE.md.
- Delete: remaining compatibility modules, obsolete resources, legacy schemas, old tests and migration-only code with zero callers.
- Test: tests/architecture/test_final_budget.py, tests/e2e/test_campus_delivery_robot.py, tests/e2e/test_failure_repair.py.

- [ ] Step 1: Add architectural budget test asserting WebFacade, requirements_workbench, and legacy_builder are absent, exactly one workflow orchestrator exists, and no file exceeds 1000 lines.
- [ ] Step 2: Tighten pyright to domain/methodology/ports/repository/runtime at standard or stronger; add ruff unused/import-order/complexity gates; preserve zero-cycle inward layer contract.
- [ ] Step 3: Run campus delivery robot from ingest through Closure; inject missing maintenance/failure/verification/physical coverage and assert minimum rollback, local Patch, locked guard, revision increment, and unchanged unrelated entities.
- [ ] Step 4: Run the complete matrix:

~~~bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/lint-imports
.venv/bin/ruff check src tests
.venv/bin/pyright
.venv/bin/python -m build
~~~

Expected: all commands exit 0; offline tests do not require Web Search, OR-Tools, MLflow, prance, junitparser, or user project execution.

- [ ] Step 5: Run git diff --check and git status --short, then stage only task-owned files and commit with git commit -m "refactor: complete AI4MBSE Harness v2 cleanup".

## Plan Self-Review

- Scope coverage: PR-00 through PR-19 are mapped to Tasks 1–19; all major document requirements have a task.
- Placeholder scan: no TODO or unassigned implementation step is used as a plan placeholder; TBD is only the required domain value for unsupported performance evidence.
- Type consistency: ModelGraph, Patch, TaskSpec, ContextBundle, TaskExecutionRequest, ModelRepository, RunRepository, RuntimePort, and service boundaries are named consistently.
- Deletion safety: every deletion is gated by import inventory, focused tests, and caller count; no broad destructive command is part of the plan.
- Existing worktree safety: current dirty files and untracked reference assets are explicitly outside automatic staging scope.

