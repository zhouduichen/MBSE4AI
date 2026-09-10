# Structured Output Boundary Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将真实 LLM 的输出收敛为严格的 `TaskProposal`，由 Harness 确定性编译为 canonical Patch，并隔离 structural/compiler failure 与 MBSE semantic repair。

**Architecture:** 保留现有 `GenerativeModel → StructuredModelRuntime → TaskExecutor → WorkflowRunner` 链路，在 runtime 与领域 Patch 之间增加纯函数式 Proposal Compiler。`OpenAICompatibleModel` 负责 JSON decode、canonical schema 校验和有限 structural retry；TaskExecutor/WorkflowRunner 负责传播失败阶段并阻止结构失败进入语义修复；独立 conformance runner 复用同一 schema/compiler/validator 链路。

**Tech Stack:** Python 3、dataclasses、jsonschema、现有 SQLite ModelGraph/RunRepository、pytest、Ollama native `/api/chat`。

## Global Constraints

- 继续使用 provider `ollama`、model `qwen3.5:9b-q8_0` 做 PR09 live 压力测试。
- Ollama 请求必须通过 `format` 传入 TaskProposal JSON Schema，并保持 `stream=false`、`think=false`、`temperature=0`。
- 默认 structural retry 最多 1 次；不得因为 structural/compiler failure 再触发一次完整 Task retry 或 `LifecycleOrchestrator.repair()`。
- Patch ID、project_id、expected_revision、operation discriminant、producer、默认 status 和实体 ID 必须由 Harness 生成。
- 旧的 `operations` Patch envelope 不得作为 LLM 输入协议继续兼容。
- 保留 `run-07efa6e07f0a6b14` 对应数据库，不删除、不改写。
- 不修改 Track A 分数，不扩展 Simulation/MDO/Agent 架构。
- 不触碰现有 `tests/mbse_benchmark/` 未提交用户改动，也不将其加入 PR09 commit。

---

### Task 1: Define TaskProposal schema and deterministic compiler

**Files:**
- Create: `src/rflp_lite/methodology/proposal_compiler.py`
- Modify: `src/rflp_lite/methodology/tasks.py:output_contract`
- Test: `tests/methodology/test_proposal_compiler.py`

**Interfaces:**
- Consumes: `TaskExecutionRequest`, `ContextBundle`, `PatchPolicy`, `EntityKind`, `Entity`, `RelationPredicate`。
- Produces: `TaskProposal`、`task_proposal_schema(task)`、`compile_task_proposal(request, payload) -> Patch | None`。

- [ ] **Step 1: Write failing protocol and compiler tests**

```python
def test_proposal_compiles_without_model_owned_patch_fields():
    request = make_request(output_kinds=(EntityKind.REQUIREMENT,))
    proposal = {
        "entities": [{
            "local_ref": "e1", "kind": "requirement", "name": "系统应完成投递",
            "payload": {"obligation": "shall"}, "confidence": 0.9,
            "source_ids": [], "evidence_ids": [], "lifecycle_ids": [],
        }],
        "relations": [], "updates": [], "deprecations": [], "reason": "提取需求",
    }
    patch = compile_task_proposal(request, proposal)
    assert patch is not None
    assert patch.project_id == request.context_bundle.project_id
    assert patch.expected_revision == request.context_bundle.revision
    assert isinstance(patch.operations[0], AddEntity)
    assert patch.operations[0].entity.meta.producer is Producer.LLM
    assert patch.operations[0].entity.meta.status is EntityStatus.CANDIDATE


def test_old_patch_envelope_is_not_a_task_proposal():
    request = make_request(output_kinds=(EntityKind.REQUIREMENT,))
    with pytest.raises(ContractViolation, match="proposal"):
        compile_task_proposal(request, {"operations": [{"op": "ADD", "kind": "requirement"}]})


def test_unknown_proposal_ref_is_rejected_before_patch_creation():
    request = make_request(output_kinds=(EntityKind.REQUIREMENT,))
    payload = valid_proposal(relations=[{
        "source_ref": "missing", "predicate": "satisfiedBy",
        "target_ref": "missing-too", "evidence_ids": [],
    }])
    with pytest.raises(ContractViolation, match="reference"):
        compile_task_proposal(request, payload)
```

- [ ] **Step 2: Run the focused tests and verify the old operation contract fails**

Run: `./.venv/bin/pytest tests/methodology/test_proposal_compiler.py -q`

Expected: FAIL because the module and proposal compiler do not yet exist.

- [ ] **Step 3: Implement typed proposal parsing and compiler**

Implement these exact dataclasses and function:

```python
@dataclass(frozen=True, slots=True)
class TaskProposal:
    entities: tuple[ProposalEntity, ...]
    relations: tuple[ProposalRelation, ...]
    updates: tuple[ProposalUpdate, ...]
    deprecations: tuple[ProposalDeprecation, ...]
    reason: str

def compile_task_proposal(
    request: TaskExecutionRequest,
    payload: Mapping[str, object],
) -> Patch | None:
    """Validate one TaskProposal and compile it into a canonical Patch."""
```

The parser must require top-level `entities`, `relations`, `updates`, `deprecations`, `reason`; reject a top-level `operations`; validate proposal `kind` against `EntityKind` and the Task output/policy scope; validate payloads using `x-payload-schemas`; generate new entities with `make_entity(..., status=EntityStatus.CANDIDATE, producer=Producer.LLM, revision=request.context_bundle.revision)`; map proposal refs to generated IDs; resolve existing context IDs; then create `Patch.create(...)` using the request project/task/revision.

Relations must use `RelationPredicate`, `PatchPolicy.allowed_predicates`, and context/new IDs. Updates and deprecations must target context entities and only policy-writable fields/kinds. Compiler metadata must ignore any unrecognized model-owned Patch fields.

- [ ] **Step 4: Replace `output_contract()` with the proposal schema**

Keep the existing payload schemas and policy metadata, but make the provider-facing schema equivalent to:

```python
{
    "type": "object",
    "additionalProperties": False,
    "required": ["entities", "relations", "updates", "deprecations", "reason"],
    "properties": {
        "entities": {"type": "array", "items": entity_schema, "maxItems": 32},
        "relations": {"type": "array", "items": relation_schema, "maxItems": 32},
        "updates": {"type": "array", "items": update_schema, "maxItems": 32},
        "deprecations": {"type": "array", "items": deprecation_schema, "maxItems": 32},
        "reason": {"type": "string", "maxLength": 300},
    },
    "schema_id": task.output_schema_id,
    "output_kinds": [kind.value for kind in task.output_kinds],
    "x-payload-schemas": payload_schemas,
}
```

Entity `name` remains required; `kind` is required only when a Task allows multiple output kinds and is compiler-injected for singleton output tasks. `op`, `patch_id`, `project_id`, `status`, `producer`, `revision`, `source_id`, and `target_id` operation fields are absent from the LLM schema.

- [ ] **Step 5: Run compiler tests and commit**

Run: `./.venv/bin/pytest tests/methodology/test_proposal_compiler.py -q`

Expected: PASS.

```bash
git add src/rflp_lite/methodology/proposal_compiler.py src/rflp_lite/methodology/tasks.py tests/methodology/test_proposal_compiler.py
git commit -m "feat(pr09): add task proposal compiler"
```

### Task 2: Route runtime through proposal compilation and classify failures

**Files:**
- Modify: `src/rflp_lite/methodology/contracts.py:TaskExecutionResponse`
- Modify: `src/rflp_lite/runtime/structured_model.py:StructuredModelRuntime.execute`
- Modify: `src/rflp_lite/methodology/executor.py:TaskExecutor.execute`
- Modify: `src/rflp_lite/domain/errors.py`
- Modify: `tests/runtime/test_task_execution.py`
- Modify: `tests/runtime/test_task_specific_prompts.py`

**Interfaces:**
- Consumes: `compile_task_proposal()` and `GenerationResponse`。
- Produces: `FailureStage` enum with `STRUCTURAL`, `COMPILER`, `SEMANTIC`; `TaskExecutionResponse.failure_stage` defaulting to `None`。

- [ ] **Step 1: Write failing runtime tests**

```python
def test_structured_runtime_compiles_proposal_not_operations():
    model = FakeModel({
        "entities": [{"local_ref": "e1", "kind": "function", "name": "执行投递", "payload": {}}],
        "relations": [], "updates": [], "deprecations": [], "reason": "识别功能",
    })
    response = StructuredModelRuntime(model).execute(make_function_request())
    assert response.status is StepStatus.COMPLETED
    assert isinstance(response.patch.operations[0], AddEntity)


def test_compiler_failure_is_not_reported_as_semantic_repair():
    model = FakeModel({"entities": [], "relations": [{
        "source_ref": "unknown", "predicate": "satisfiedBy",
        "target_ref": "unknown2", "evidence_ids": [],
    }], "updates": [], "deprecations": [], "reason": "关系"})
    response = TaskExecutor(StructuredModelRuntime(model)).execute(function_task(), context)
    assert response.status is StepStatus.DEGRADED
    assert response.failure_stage is FailureStage.COMPILER
    assert "repair" not in " ".join(response.diagnostics).casefold()
```

Update task-specific prompt assertions from `operations/reason` to `entities/relations/updates/deprecations/reason`, while preserving prompt hash determinism.

- [ ] **Step 2: Run focused runtime tests and verify failure**

Run: `./.venv/bin/pytest tests/runtime/test_task_execution.py tests/runtime/test_task_specific_prompts.py -q`

Expected: FAIL because the runtime still calls `patch_from_response()` and no failure stage exists.

- [ ] **Step 3: Add failure classification and change runtime adapter**

Add:

```python
class FailureStage(StrEnum):
    STRUCTURAL = "structural"
    COMPILER = "compiler"
    SEMANTIC = "semantic"
```

Add `failure_stage: FailureStage | None = None` as the final field of `TaskExecutionResponse` to preserve existing positional constructors. Add `StructuredOutputFailure(AdapterFailure)` and `ProposalCompileFailure(ContractViolation)` with `stage`, `code`, `raw_response`, `schema_hash`, and `retry_count` attributes.

`StructuredModelRuntime.execute()` must send the proposal schema, call `compile_task_proposal()`, convert compiler exceptions into `ProposalCompileFailure(stage=FailureStage.COMPILER)`, and return a completed response only with a compiled Patch. The system prompt must say “仅返回 TaskProposal JSON 对象” and list the five top-level fields.

`TaskExecutor.execute()` must copy failure stage from runtime responses and classify caught `StructuredOutputFailure` as structural and `ProposalCompileFailure`/`ContractViolation` from the compiler as compiler. If the caught stage is structural or compiler, return degraded immediately instead of consuming another task-level retry. Preserve provider/model and input/output hashes.

- [ ] **Step 4: Run runtime tests and commit**

Run: `./.venv/bin/pytest tests/runtime/test_task_execution.py tests/runtime/test_task_specific_prompts.py tests/methodology/test_prompt_contracts.py -q`

Expected: PASS.

```bash
git add src/rflp_lite/domain/errors.py src/rflp_lite/methodology/contracts.py src/rflp_lite/methodology/executor.py src/rflp_lite/runtime/structured_model.py tests/runtime/test_task_execution.py tests/runtime/test_task_specific_prompts.py
git commit -m "feat(pr09): route runtime through task proposals"
```

### Task 3: Harden adapter structural retry and preserve failure evidence

**Files:**
- Modify: `src/rflp_lite/adapters/openai_compatible_model.py`
- Modify: `src/rflp_lite/ports/generative_model.py`
- Modify: `src/rflp_lite/methodology/executor.py`
- Test: `tests/adapters/test_openai_compatible_model.py`

**Interfaces:**
- Consumes: `GenerationRequest.response_schema` containing TaskProposal schema。
- Produces: one bounded structural retry, `StructuredOutputFailure` diagnostics with raw response and schema hash。

- [ ] **Step 1: Add adapter tests for provider schema and bounded retry**

```python
def test_ollama_receives_task_proposal_schema_as_format():
    calls = []
    def complete(config, messages, *, max_tokens=None):
        calls.append((config, messages, max_tokens))
        return '{"entities": [], "relations": [], "updates": [], "deprecations": [], "reason": "无变化"}'
    OpenAICompatibleModel(ollama_config(), complete=complete).complete_json(proposal_request())
    assert calls[0][0]["json_schema"]["required"] == ["entities", "relations", "updates", "deprecations", "reason"]


def test_invalid_structured_output_exposes_raw_response_and_one_retry():
    calls = []
    def complete(config, messages, *, max_tokens=None):
        calls.append(messages)
        return "not-json" if len(calls) == 1 else "still-not-json"
    with pytest.raises(StructuredOutputFailure) as error:
        OpenAICompatibleModel(ollama_config(), complete=complete).complete_json(proposal_request())
    assert len(calls) == 2
    assert error.value.stage is FailureStage.STRUCTURAL
    assert error.value.raw_response == "still-not-json"
    assert error.value.retry_count == 1
```

- [ ] **Step 2: Run adapter tests and verify the new exception test fails**

Run: `./.venv/bin/pytest tests/adapters/test_openai_compatible_model.py -q`

Expected: the existing adapter tests show the old generic exception/repair behavior; the new evidence assertions fail.

- [ ] **Step 3: Preserve raw response and classify parse/schema failures**

Keep `_ollama_transport_schema()` and native `format` behavior. In `complete_json()`, preserve the first and retry raw outputs; after the single retry fails, raise `StructuredOutputFailure` with `stage=structural`, `code` set to `json_decode`, `schema_validation`, or `truncated`, `raw_response` set to the failed retry output truncated to 12000 characters, `schema_hash=canonical_hash(request.response_schema)`, and `retry_count=1`. Provider/network failures remain `AdapterFailure` and are not mislabeled as structural.

Use `GenerationRequest`/`GenerationResponse` unchanged unless the implementation needs a bounded raw response field; the failure object and TaskExecutor diagnostics are the persistence boundary. Add a helper that serializes failure evidence as one JSON diagnostic string containing `stage`, `code`, `raw_response`, `schema_hash`, `provider_id`, `model_id`, and `retry_count`.

- [ ] **Step 4: Run the complete adapter/runtime regression set and commit**

Run: `./.venv/bin/pytest tests/adapters/test_openai_compatible_model.py tests/runtime/test_task_execution.py -q`

Expected: PASS, including existing fenced JSON, truncation, token cap, and provider-format tests.

```bash
git add src/rflp_lite/adapters/openai_compatible_model.py src/rflp_lite/ports/generative_model.py src/rflp_lite/methodology/executor.py tests/adapters/test_openai_compatible_model.py
git commit -m "feat(pr09): classify and preserve structured output failures"
```

### Task 4: Stop structural/compiler failures from entering workflow repair

**Files:**
- Modify: `src/rflp_lite/methodology/workflow.py:LifecycleOrchestrator.run`
- Modify: `src/rflp_lite/methodology/workflow.py:WorkflowRunner._run_phase`
- Modify: `src/rflp_lite/methodology/repair_strategies.py`
- Modify: `tests/methodology/test_workflow.py`
- Modify: `tests/methodology/repair/test_llm_repair_strategy.py`

**Interfaces:**
- Consumes: `TaskExecutionResponse.failure_stage`。
- Produces: degraded, finite run status for structural/compiler failure; semantic repair only after successful Patch validation。

- [ ] **Step 1: Add workflow isolation tests**

```python
def test_structural_failure_does_not_create_gate_repair_round():
    runtime = FailingRuntime(FailureStage.STRUCTURAL)
    summary = make_runner(runtime).run(project_id, phase=Phase.FUNCTIONAL, force_run=True)
    stored = run_repository.load_run(project_id, summary.run_id)
    assert summary.status is RunStatus.DEGRADED
    assert stored.status == RunStatus.DEGRADED.value
    assert all(step.repair_round == 0 for step in stored.steps)
    assert "repair" not in " ".join(summary.diagnostics).casefold()


def test_semantic_failure_keeps_existing_repair_route():
    summary = run_with_gate_issue_and_valid_patch(
        runtime=runtime,
        project_id=project_id,
        run_repository=run_repository,
    )
    assert summary.status in {RunStatus.REPAIRING, RunStatus.DEGRADED, RunStatus.COMPLETED}
    assert repair_strategy.calls == 1
```

Add a repair-strategy test asserting the repair prompt requests TaskProposal fields and the returned LLM response is compiled through the same compiler.

- [ ] **Step 2: Run workflow tests and verify structural failure currently reaches repair**

Run: `./.venv/bin/pytest tests/methodology/test_workflow.py tests/methodology/repair/test_llm_repair_strategy.py -q`

Expected: the new isolation test fails against the current gate-driven repair loop.

- [ ] **Step 3: Add the early terminal path and update semantic repair prompt**

In `_run_phase`, after a degraded response, inspect `response.failure_stage`. Persist the step as degraded with its diagnostics. If the stage is `STRUCTURAL` or `COMPILER`, set the run status to `DEGRADED` and return the phase summary without evaluating a gate repair route. In the lifecycle orchestrator, do the same before entering `repair()` for a phase whose task summary has a structural/compiler failure.

Leave gate-triggered semantic repair unchanged for completed Patch responses. Update `_repair_prompt()` to require `entities`, `relations`, `updates`, `deprecations`, and `reason`; `LLMRepairStrategy` must use the normal TaskExecutor/runtime boundary and never call `patch_from_response()` directly.

- [ ] **Step 4: Run workflow, repair, and full non-benchmark tests; commit**

Run: `./.venv/bin/pytest tests/methodology tests/runtime -q`

Expected: PASS, with structural/compiler failure tests proving no semantic repair round is recorded.

```bash
git add src/rflp_lite/methodology/workflow.py src/rflp_lite/methodology/repair_strategies.py tests/methodology/test_workflow.py tests/methodology/repair/test_llm_repair_strategy.py
git commit -m "fix(pr09): isolate structural failures from semantic repair"
```

### Task 5: Add conformance runner and preserve the failed-run regression manifest

**Files:**
- Create: `tests/contract_conformance/__init__.py`
- Create: `tests/contract_conformance/runner.py`
- Create: `tests/contract_conformance/test_metrics.py`
- Create: `tests/contract_conformance/fixtures/run-07efa6e07f0a6b14-regression.json`
- Create: `docs/superpowers/artifacts/pr09/README.md`
- Modify: `README.md` only if it has an existing benchmark command section suitable for one PR09 command entry

**Interfaces:**
- Consumes: `task_catalog()`, `TaskExecutor`, `output_contract()`, Proposal Compiler, validators, and a configured runtime。
- Produces: `run_conformance(repetitions: int = 20, live: bool = False) -> dict[str, object]` and JSON output with funnel metrics plus per-sample ledger。

- [ ] **Step 1: Write deterministic metric tests**

```python
def test_metrics_are_computed_from_stage_results():
    samples = [
        SampleResult(json_parsed=True, schema_passed=True, compiled=True, domain_valid=True, structural_retries=0),
        SampleResult(json_parsed=True, schema_passed=False, compiled=False, domain_valid=False, structural_retries=1),
    ]
    metrics = summarize(samples)
    assert metrics == {
        "json_parse_rate": 1.0,
        "schema_pass_rate": 0.5,
        "proposal_compile_rate": 0.5,
        "domain_validation_rate": 0.5,
        "first_pass_success_rate": 0.5,
        "structural_retry_rate": 0.5,
    }
```

- [ ] **Step 2: Run metric tests and verify missing runner symbols**

Run: `./.venv/bin/pytest tests/contract_conformance/test_metrics.py -q`

Expected: FAIL because the runner and metric types do not yet exist.

- [ ] **Step 3: Implement the isolated 3-task runner**

Implement `SampleResult`, `summarize(samples)`, and `run_conformance(repetitions=20, live=False)`. The runner must select exactly `system_definition`, `stakeholder_requirements`, and `function_identification`; use a temporary SQLite project for live mode; call the same model/runtime/schema/compiler/validator path; and write a JSON artifact under `docs/superpowers/artifacts/pr09/` with provider/model, sampling settings, prompt/schema hashes, failure evidence, retry/repair ledger, metrics, and samples. Live execution must require `live=True` or `RFLP_RUN_LIVE_LLM=1`; default pytest must use fake responses and must not call Ollama.

The regression fixture must record `run-07efa6e07f0a6b14`, its DB path, model/provider, known failure messages, and expected post-PR09 isolation behavior. It must not claim raw response content that is absent from the old run record.

- [x] **Step 4: Run unit tests and one explicit local conformance smoke test**

Run:

```bash
./.venv/bin/pytest tests/contract_conformance tests/adapters tests/runtime tests/methodology -q
./.venv/bin/python -m tests.contract_conformance.runner --repetitions 1
```

Expected: all tests PASS; the smoke command writes a JSON result containing the full funnel metric set without contacting Ollama unless `RFLP_RUN_LIVE_LLM=1` is explicitly set.

- [x] **Step 5: Run the live 20×3 contract benchmark and record results**

Run only after Tasks 1–4 pass:

```bash
RFLP_RUN_LIVE_LLM=1 ./.venv/bin/python -m tests.contract_conformance.runner --repetitions 20 --live
```

Result: [`contract-conformance-1789049206566817000.json`](../../artifacts/pr09/contract-conformance-1789049206566817000.json) contains 60 samples and the configured `ollama/qwen3.5:9b-q8_0` metadata. Provider success is 60/60; JSON/schema/compile/domain are 58/60; two structural retries were not recovered. Do not run the 23-task lifecycle in this step.

- [x] **Step 6: Run final regression checks (without committing)**

Run: `./.venv/bin/pytest tests -q`

Expected: PASS without staging or modifying `tests/mbse_benchmark/` user changes.

本次未执行 commit；保留当前工作树，包含用户已有的 benchmark 改动。

## Final acceptance checklist

- [x] `TaskProposal` is the only LLM task output protocol.
- [x] Canonical Patch metadata and operation discriminants are Harness-owned.
- [x] Ollama native request contains the provider-level `format` schema.
- [x] Structural retry is bounded and classified; raw failure evidence is retained with excerpt/hash/size bounds.
- [x] Structural/compiler failure never calls semantic repair and reaches degraded terminal state.
- [x] Three-task, 20-repetition conformance output contains the full funnel metric set.
- [x] `run-07efa6e07f0a6b14` remains available as regression evidence.
- [x] Full 23-task lifecycle remains not accepted until the conformance gate passes.
- [x] Existing PR08/UI files and unrelated benchmark working-tree changes remain untouched.
