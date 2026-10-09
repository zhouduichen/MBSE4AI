# F 阶段按需求窄批次 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `vertical.functional` 变成按单个 Requirement 生成并统一合并的真实 F 阶段窄批次链。

**Architecture:** 复用现有 `StructuredModelRuntime` 的批次、Compiler、Validator 和 CAS 边界，仅把 Functional 的批次粒度固定为单 Requirement，并加强批次作用域和 F 追溯 Prompt。每个批次独立生成 Function/Flow/Scenario，全部成功后沿现有 `_merge_compiled` 进入一个阶段 Patch。

**Tech Stack:** Python 3.11+, dataclasses, immutable ModelGraph/Patch, JSON Schema, existing TaskProposal compiler, pytest, Ruff.

## Global Constraints

- 不启动本机模型；本轮只使用离线结构化夹具和现有远端 Provider 配置。
- 不改变 ModelGraph、CAS、SysML v2 子集或公开 API 语义。
- Functional 批次失败时不提交部分 Patch，不把 L/P/V&V 标记为完成。
- 每个 Functional 批次只携带一个 canonical Requirement 和当前可见的一跳上下文。
- 不通过截断 JSON、无限续写或 completion bridge 伪造成功。

---

### Task 1: 固定 Functional 单 Requirement 批次

**Files:**
- Modify: `src/rflp_lite/runtime/structured_model.py`
- Modify: `src/rflp_lite/adapters/openai_compatible_model.py`
- Test: `tests/runtime/test_task_execution.py`
- Test: `tests/adapters/test_openai_compatible_model.py`

**Interfaces:**
- Extend `_requirement_batches(request, worklist, model, *, batch_size=...)` behavior so `vertical.functional` uses one Requirement per batch by default.
- Preserve configured `vertical_batch_size` behavior for Logical, Physical and V&V.
- Add a model-level `vertical_functional_batch_size` default of `1` for OpenAI-compatible models, with an explicit test-double override for legacy batching tests.

- [ ] **Step 1: Write the failing test**

Add a Functional-only test with five Requirements and assert the request payloads contain five singleton `requirement_worklist` lists and five `requirement_batch` descriptors. Keep the existing Logical/Physical two-item batch assertion unchanged.

```python
def test_structured_runtime_batches_functional_one_requirement_per_call():
    model = BatchedVerticalModel()
    requirements = tuple(make_entity(EntityKind.REQUIREMENT, f"需求-{i}", {"statement": f"系统应满足需求-{i}"}) for i in range(5))
    request = TaskExecutor(model).request(
        stage_task("functional"),
        ContextBundle("p1", "vertical.functional", 3, requirements),
        "v2.1",
    )

    StructuredModelRuntime(model).execute(request)

    assert [len(call.user_payload["requirement_worklist"]) for call in model.calls] == [1] * 5
    assert [call.user_payload["requirement_batch"]["requirement_ids"] for call in model.calls] == [[item.id] for item in sorted(requirements, key=lambda item: item.id)]
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
./.venv/bin/pytest -q tests/runtime/test_task_execution.py -k functional_one_requirement
```

Expected: FAIL because Functional currently follows the shared two-Requirement batch size.

- [ ] **Step 3: Implement the batch-size split**

In `StructuredModelRuntime.execute`, choose the batch size by task:

```python
batch_size = self.vertical_batch_size
if request.task_id == "vertical.functional":
    batch_size = self.vertical_functional_batch_size
elif request.task_id == _VV_BATCH_TASK:
    batch_size = self.vertical_vv_batch_size
```

Initialize `vertical_functional_batch_size` from the model with a bounded default of `1`. Add the corresponding OpenAI-compatible adapter setting, preserving explicit test overrides. Emit `requirement_batch` metadata even when the Functional count is one so the Prompt always sees its boundary.

- [ ] **Step 4: Run focused runtime and adapter tests**

```bash
./.venv/bin/pytest -q tests/runtime/test_task_execution.py tests/adapters/test_openai_compatible_model.py
```

Expected: PASS, including existing Logical/Physical/V&V batching tests.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/runtime/structured_model.py src/rflp_lite/adapters/openai_compatible_model.py tests/runtime/test_task_execution.py tests/adapters/test_openai_compatible_model.py
git commit -m "feat: slice functional generation per requirement"
```

### Task 2: Enforce F slice scope and typed traceability

**Files:**
- Modify: `src/rflp_lite/runtime/structured_model.py`
- Modify: `src/rflp_lite/resources/prompts/vertical/functional.v1.md`
- Test: `tests/runtime/test_task_execution.py`
- Test: `tests/runtime/test_task_specific_prompts.py`

**Interfaces:**
- Add Functional batch guidance through the existing `_batch_instruction` path.
- Keep `_scope_batch_payload` as the sole context projection boundary.
- Preserve canonicalization in `_normalize_vertical_payload` and `_infer_vertical_relations`.

- [ ] **Step 1: Write the failing scope/trace test**

Use a model that records the Functional prompt and payload. Assert the prompt contains the exact singleton Requirement ID, forbids other batch IDs, and the resulting Function payload includes only that Requirement in `source_requirement_ids`; assert `satisfiedBy` points from that Requirement to the Function.

- [ ] **Step 2: Run the focused test and verify it fails**

```bash
./.venv/bin/pytest -q tests/runtime/test_task_execution.py tests/runtime/test_task_specific_prompts.py -k 'functional and (batch or scope or trace)'
```

Expected: FAIL because the existing generic batch instruction does not state the Function-specific source/trace contract.

- [ ] **Step 3: Implement the F-specific instruction**

Extend `_batch_instruction` for `vertical.functional` with short, exact rules:

```python
if task_id == "vertical.functional":
    return (
        f"当前只处理一个 canonical Requirement：{requirement_ids[0]}。"
        "只能为该 Requirement 生成行为性的 Function；Function payload.source_requirement_ids "
        "只能包含该 ID。可以生成与本批 Function 端点一致的 FunctionalFlow 和 "
        "FunctionalScenario；必须保留 satisfiedBy 关系，禁止引用其它批次 Requirement。"
    )
```

Update `functional.v1.md` to match the same boundary and to require a short decomposition, typed flow endpoints and scenario function IDs. Do not add a new public schema or a second compiler.

- [ ] **Step 4: Run focused prompt/runtime tests**

```bash
./.venv/bin/pytest -q tests/runtime/test_task_execution.py tests/runtime/test_task_specific_prompts.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/runtime/structured_model.py src/rflp_lite/resources/prompts/vertical/functional.v1.md tests/runtime/test_task_execution.py tests/runtime/test_task_specific_prompts.py
git commit -m "fix: scope functional proposals to one requirement"
```

### Task 3: Verify merged F patch and vertical continuation

**Files:**
- Modify: `tests/application/test_model_generation.py`
- Modify: `tests/e2e/test_vertical_model_generation.py`
- Modify: `src/rflp_lite/application/model_generation.py` only if stage ledger projection loses batch diagnostics

**Interfaces:**
- The existing `ModelGenerationService` remains the public entry point.
- The final Functional StageResult must contain one merged Patch, all singleton attempt evidence, and no partial CAS write on failure.

- [ ] **Step 1: Add a deterministic five-Requirement product test**

Run the existing scripted vertical model with five independent Requirements. Assert five Functional Provider calls, five `satisfiedBy` relations, one Function per Requirement, and downstream Logical/Physical/V&V steps still execute from the merged revision.

- [ ] **Step 2: Add the failure-boundary assertion**

Make one singleton Functional response raise `StructuredOutputFailure`. Assert the generation result has no Functional Patch, the repository revision is unchanged for that stage, and Logical/Physical/V&V remain queued or are not falsely marked completed.

- [ ] **Step 3: Implement only missing ledger projection**

If the public result omits singleton diagnostics, preserve them as existing `TaskExecutionResponse.diagnostics`; do not add a second state machine. If the current projection already keeps them, change no production code.

- [ ] **Step 4: Run targeted application/e2e tests**

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview ./.venv/bin/pytest -q tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py
```

Expected: PASS with real Function/Flow/Scenario objects and downstream stage records.

- [ ] **Step 5: Commit**

```bash
git add src tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py
git commit -m "test: verify functional requirement slices"
```

### Task 4: Run local gates and publish the F milestone

**Files:**
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Generate: `tests/mbse_benchmark/reports/llm/jiayuinter-vllm/*` only if a single remote acceptance is run

- [ ] **Step 1: Run the full local gate**

```bash
RFLP_CONFIG_DIR=/tmp/ai4mbse-local-gate-20260920 AI4MBSE_CAD_BACKEND=preview ./.venv/bin/python -m pytest -q --disable-warnings
./.venv/bin/ruff check src tests scripts
git diff --check
```

Expected: all local tests pass and no local model process starts.

- [ ] **Step 2: Update the development boundary**

Record that local structured F is complete only if the five-Requirement test passes; keep the pure remote Provider status separate and do not claim R→F→L→P→V&V remote completion.

- [ ] **Step 3: Commit and push**

```bash
git add docs src tests
git commit -m "feat: complete functional requirement slice"
git push origin codex/web-audit-2026-08-18
```

## Self-review

- Spec coverage: singleton F batching, typed traceability, merge/failure boundary, local gates and honest remote boundary are each covered by a task.
- No public API or second compiler is introduced.
- Logical, Physical and V&V batch sizes remain unchanged.
- No step relies on an unbounded retry or a local model.
