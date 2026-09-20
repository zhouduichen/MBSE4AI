# R 阶段窄批次闭合 Implementation Plan

> **For agentic workers:** Execute this plan inline task-by-task with a focused test after each task.

**Goal:** 将 `vertical.requirements` 从一次宽 JSON 改为可合并的 R 骨架批次与单 Requirement 闭合批次，并在不改变最终 CAS 边界的前提下继续进入 F→L→P→V&V。

**Architecture:** `StructuredModelRuntime` 先为共享 R 类型创建顺序骨架 slice，将其 Patch 投影到临时 `ModelGraph` working context；再为每个已有 Requirement 创建只允许更新/关系的闭合 slice。所有临时 Patch 通过现有 Compiler、端点校验和 merge operation key 合并，最后仅生成一个以原始 revision 为 expected revision 的 Patch。Prompt、Schema 和测试同步修正 Use Case→Activity 的 `decomposes` 契约。

**Tech Stack:** Python 3.11+, dataclasses, immutable `ModelGraph`/`apply_patch`, JSON Schema, existing `TaskProposal` compiler, pytest, Ruff.

## Global Constraints

- 不启用 `vertical_completion_bridge`，不启动本地模型。
- 不改变 ModelGraph、SysML v2 子集或 CAS 的公开语义。
- 不使用无限续写或截断 JSON 拼接伪造完整响应。
- R slice 失败时不写部分 CAS，F/L/P/V&V 不得被标记为完成。
- 每个 R slice 必须记录 `slice_kind`、index/count、目标 Requirement IDs、hash、finish reason 和 usage。

---

### Task 1: 建立 R slice 规划与契约测试

**Files:**
- Modify: `src/rflp_lite/runtime/structured_model.py`
- Test: `tests/runtime/test_task_execution.py`
- Test: `tests/runtime/test_vertical_rule_runtime.py`

**Interfaces:**
- Produce `_r_stage_slices(request, payload) -> tuple[Mapping[str, object], ...]` in `structured_model.py`.
- Produce `_r_slice_contract(contract, payload) -> Mapping[str, object]` for per-slice JSON Schema narrowing.
- Preserve `_requirement_batches` behavior for Functional/Logical/Physical/V&V.

- [ ] **Step 1: Write failing tests for deterministic slice planning**

Add tests using the existing `ContextBundle`/`TaskExecutionRequest` fixtures. Assert that a graph with five Requirements and no R behavior types produces, in order, `r_backbone_operational`, `r_backbone_behavior`, then five `r_requirement` payloads; each closure payload contains exactly one `requirement_id` and a stable `slice_index`/`slice_count`.

```python
def test_r_stage_slices_backbone_then_one_requirement_closure_per_requirement():
    payloads = _r_stage_slices(requirements_request(), base_payload)
    assert [p["r_slice"]["slice_kind"] for p in payloads] == [
        "r_backbone_operational", "r_backbone_behavior",
        "r_requirement", "r_requirement", "r_requirement",
        "r_requirement", "r_requirement",
    ]
    assert all(
        len(p["r_slice"].get("requirement_ids", ())) == 1
        for p in payloads[2:]
    )
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
./.venv/bin/pytest -q tests/runtime/test_task_execution.py -k r_stage_slices
```

Expected: FAIL because the R slice planner does not exist.

- [ ] **Step 3: Implement the pure planner and contract narrowing**

Add constants for the two shared groups and implement deterministic planning. The planner must derive missing kinds from active context, include a compact requirement index in the backbone payload, and never put a Requirement entity into a backbone `allowed_kinds`. Closure payloads must carry only one canonical Requirement ID and its current missing fields.

```python
_R_BACKBONE_GROUPS = (
    ("r_backbone_operational", ("system", "stakeholder", "concern", "lifecycle_stage", "lifecycle_transition")),
    ("r_backbone_behavior", ("scenario_hypothesis", "use_case", "operational_scenario", "activity")),
)

def _r_stage_slices(request, payload):
    worklist = tuple(item for item in payload.get("requirement_worklist", ()) if isinstance(item, Mapping))
    present = {entity.kind.value for entity in request.context_bundle.entities}
    missing = set(_R_R_KINDS) - present
    result = []
    for kind, group in _R_BACKBONE_GROUPS:
        allowed = tuple(item for item in group if item in missing)
        if allowed:
            result.append(_r_backbone_payload(payload, kind, allowed, worklist))
    for item in worklist:
        result.append(_r_requirement_payload(payload, item))
    return tuple(_renumber_r_slices(result)) or (payload,)
```

`_r_slice_contract` must set `entities.items.kind` to the slice `allowed_kinds`; for a closure slice set `entities.maxItems=0`, constrain `updates` to its one Requirement ID, and keep only the R predicates required for `derivedFrom` and `decomposes`.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```bash
./.venv/bin/pytest -q tests/runtime/test_task_execution.py -k r_stage_slices
./.venv/bin/pytest -q tests/runtime/test_vertical_rule_runtime.py -k requirement
```

Expected: PASS with no changes to non-R vertical batching.

- [ ] **Step 5: Commit the planner and tests**

```bash
git add src/rflp_lite/runtime/structured_model.py tests/runtime/test_task_execution.py tests/runtime/test_vertical_rule_runtime.py
git commit -m "test: define R-stage narrow slice planning"
```

### Task 2: Execute R slices through a temporary working graph

**Files:**
- Modify: `src/rflp_lite/runtime/structured_model.py`
- Test: `tests/runtime/test_task_execution.py`

**Interfaces:**
- Add `_execute_r_stage(request, payload, contract) -> tuple[_CompiledProposal, ...]`.
- Add `_working_context(request, graph) -> TaskExecutionRequest`.
- Add `_rebase_patch(patch, expected_revision) -> Patch`.
- Existing `execute()` continues to return one `TaskExecutionResponse` and one final Patch.

- [ ] **Step 1: Write failing tests for temporary projection and one CAS boundary**

Use a fake model that returns one valid backbone proposal and one valid closure proposal. Assert the second request sees the backbone canonical entity ID, the returned final Patch has the original `expected_revision`, and the repository graph is unchanged until the caller applies the response patch.

```python
def test_r_stage_closure_sees_backbone_without_incrementing_repository_revision():
    response = StructuredModelRuntime(FakeRModel()).execute(requirements_request())
    assert response.patch is not None
    assert response.patch.expected_revision == 7
    assert response.patch.operations
    assert fake_model.closure_context_revision == 8
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
./.venv/bin/pytest -q tests/runtime/test_task_execution.py -k backbone_without_incrementing
```

Expected: FAIL because `execute()` currently submits all payloads against the original context and has no working graph.

- [ ] **Step 3: Implement working graph projection**

Import `ModelGraph` and `apply_patch`. For R only, execute backbone payloads sequentially with the narrowed contract. After each compiled Patch, apply a copy with `expected_revision=working_graph.revision` to a temporary `ModelGraph`. Build a new `ContextBundle` from that graph and use `dataclasses.replace` on the request for closure calls. Rebase every compiled Patch to the original request revision before final merge.

```python
def _rebase_patch(patch, expected_revision):
    return Patch(
        patch.id, patch.project_id, patch.task_id, patch.operations,
        patch.reason, expected_revision,
    )
```

The final R merge must call the existing `_merge_operations` semantics, reject conflicting updates, and create one Patch with the original revision. Do not call Repository or CAS from `StructuredModelRuntime`.

- [ ] **Step 4: Add bounded failure behavior**

If a backbone slice raises `StructuredOutputFailure` or `ProposalCompileFailure`, retry once only with the same slice narrowed to one allowed kind. If that fails, propagate the original stage failure; do not run closures or downstream stages. Add diagnostics with `r_slice=<kind>`, `r_slice_index=<n>/<count>`, and `r_slice_failed`.

- [ ] **Step 5: Run focused runtime tests**

```bash
./.venv/bin/pytest -q tests/runtime/test_task_execution.py tests/runtime/test_vertical_rule_runtime.py
```

Expected: PASS; existing F/L/P/V&V batch tests remain green.

- [ ] **Step 6: Commit the working-context implementation**

```bash
git add src/rflp_lite/runtime/structured_model.py tests/runtime/test_task_execution.py tests/runtime/test_vertical_rule_runtime.py
git commit -m "feat: execute R stage through temporary narrow slices"
```

### Task 3: Align R prompt and relation contract

**Files:**
- Modify: `src/rflp_lite/runtime/structured_model.py`
- Modify: `src/rflp_lite/adapters/openai_compatible_model.py`
- Modify: `src/rflp_lite/resources/prompts/vertical/requirements.v1.md`
- Test: `tests/adapters/test_openai_compatible_model.py`
- Test: `tests/runtime/test_task_specific_prompts.py`

**Interfaces:**
- `_requirements_instruction()` and `_batch_instruction()` consume `payload["r_slice"]`.
- `vertical.requirements` continues to use the existing stage contract and allowed predicate enum.

- [ ] **Step 1: Write failing contract/prompt tests**

Assert that the generated R prompt contains `slice_kind`, does not instruct the model to avoid `decomposes`, and explicitly requires `derivedFrom` Requirement→UseCase/Activity and `decomposes` UseCase→Activity. Assert that a closure Schema rejects a new shared entity and accepts the two required relation shapes.

- [ ] **Step 2: Run focused adapter/prompt tests and verify failure**

```bash
./.venv/bin/pytest -q tests/adapters/test_openai_compatible_model.py tests/runtime/test_task_specific_prompts.py -k 'requirements or decomposes or slice'
```

Expected: FAIL on the contradictory prompt text and missing slice-specific guidance.

- [ ] **Step 3: Implement slice-specific instructions**

For backbone slices, describe only the allowed shared kinds and behavior branch payload. For closure slices, forbid entities and scope updates/relations to the one Requirement. Replace the contradictory “不要使用 decomposes” guidance with the exact direction rules from the design spec. Keep all text short enough not to consume the response budget.

- [ ] **Step 4: Run adapter and prompt tests**

```bash
./.venv/bin/pytest -q tests/adapters/test_openai_compatible_model.py tests/runtime/test_task_specific_prompts.py
```

Expected: PASS.

- [ ] **Step 5: Commit contract alignment**

```bash
git add src/rflp_lite/runtime/structured_model.py src/rflp_lite/adapters/openai_compatible_model.py src/rflp_lite/resources/prompts/vertical/requirements.v1.md tests/adapters/test_openai_compatible_model.py tests/runtime/test_task_specific_prompts.py
git commit -m "fix: align R slice relation contract"
```

### Task 4: Verify failure boundary, diagnostics, and product flow

**Files:**
- Modify: `src/rflp_lite/runtime/structured_model.py`
- Test: `tests/application/test_model_generation.py`
- Test: `tests/e2e/test_vertical_model_generation.py`
- Test: `tests/e2e/test_local_product_acceptance.py`

**Interfaces:**
- Diagnostics from `TaskExecutionResponse` remain consumable by existing run ledger/audit writers.
- No public API or UI contract changes.

- [ ] **Step 1: Add failure-boundary test**

Make the second R slice return `finish_reason="length"` and invalid JSON. Assert the response status is failed, `patch is None`, the original graph revision is unchanged, `r_slice_failed` appears in diagnostics, and the vertical workflow reports F/L/P/V&V as queued rather than completed.

- [ ] **Step 2: Add product-flow success test**

Use the existing scripted model to return a backbone plus closures, then assert the product flow has R, F, L, P and V&V stage records, a complete Requirement→UseCase→Activity→Function→LogicalComponent→PhysicalBlock→VerificationCase path, and no duplicate shared R entities.

- [ ] **Step 3: Run targeted application/e2e tests**

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview .venv/bin/pytest -q tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py tests/e2e/test_local_product_acceptance.py
```

Expected: PASS without starting any model process.

- [ ] **Step 4: Commit product-flow verification**

```bash
git add src/rflp_lite/runtime/structured_model.py tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py tests/e2e/test_local_product_acceptance.py
git commit -m "test: verify R slice failure and vertical continuation"
```

### Task 5: Run local gates and one real remote Provider acceptance

**Files:**
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Generate: `tests/mbse_benchmark/reports/llm/jiayuinter-vllm/*`
- Generate: `tests/mbse_benchmark/results/llm/jiayuinter-vllm/case_04/*`

- [ ] **Step 1: Run the local full gate**

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview .venv/bin/python -m pytest -q --disable-warnings
./.venv/bin/ruff check src tests scripts
git diff --check
```

Expected: all tests and Ruff pass; no local model process is started.

- [ ] **Step 2: Start only the remote Provider path**

Use the existing `Jiayu-intern` SSH tunnel to remote vLLM and an isolated profile with `vertical_completion_bridge=false`. Run:

```bash
RFLP_CONFIG_DIR=/tmp/ai4mbse-jiayuinter-profile \
  ./.venv/bin/python tests/mbse_benchmark/run_benchmark.py \
  --track llm --profile jiayuinter-vllm --path vertical \
  --case CASE-04 --repeats 1 --timeout 1800 --baseline bare
```

Expected: R slice audit shows backbone/closure batches; if R completes, F/L/P/V&V have Provider steps. If remote infrastructure fails, preserve the failure evidence and do not enable the bridge.

- [ ] **Step 3: Validate evidence**

Check JSON validity, `execution.json`, `audit.json`, `run_ledger.json`, ModelGraph entity/relation counts, slice diagnostics, final traceability and SysML output. Update `docs/DEVELOPMENT_STATUS.md` with exact score and boundary.

- [ ] **Step 4: Commit and push the implementation/evidence**

```bash
git add src tests docs/DEVELOPMENT_STATUS.md
git commit -m "feat: complete R narrow-batch vertical handoff"
git push origin codex/web-audit-2026-08-18
```

## Self-review

- Spec coverage: R slicing, working context, one CAS boundary, relation alignment, diagnostics, local tests, and remote acceptance each have a task.
- No placeholders or open-ended retries are used; failure behavior is explicit.
- The only new interfaces are `_r_stage_slices`, `_r_slice_contract`, `_execute_r_stage`, `_working_context`, and `_rebase_patch`; all are private runtime helpers and do not change public API types.
- F/L/P/V&V existing batching remains on the current path; the plan only adds the R-specific sequential/closure path.

