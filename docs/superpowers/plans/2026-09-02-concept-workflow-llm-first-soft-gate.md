# LLM-First Concept Workflow Soft-Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the concept workflow LLM-first and soft-gated: every non-empty natural-language requirement produces a useful provisional concept/MBSE result, while professional domain packs, historical schemes, deterministic rules, evaluation, and optimization enrich the result when available.

**Architecture:** Keep the existing deterministic requirement and MBSE pipeline as the durable state backbone. Add one concept-level LLM enrichment adapter before envelope construction. The adapter produces a domain-neutral concept proposal and typed parameter suggestions with explicit provenance. Explicit user/rule values remain authoritative; matching professional packs and history are optional enhancers. The workflow chooses a pack only when explicitly selected or when the LLM/rule context gives a defensible match. Missing information becomes provisional state and diagnostics, not a 2.1 failure.

**Tech Stack:** Python 3.11+, dataclasses, existing `GenerativeModel`/`GenerationRequest` ports, existing `WebFacade`, FastAPI/HTML routes, pytest, Ruff.

## Global Constraints

- Preserve all user changes already present in `src/rflp_lite/adapters/documents/ocr.py`, `tests/adapters/test_document_intelligence.py`, and untracked demo/release assets.
- Do not change the 3.x workflow.
- Do not remove or weaken professional-pack hard validation for explicitly illegal values or violated hard constraints.
- Explicit numeric requirements override LLM suggestions, historical values, and pack defaults.
- History lookup and demo seeding must never be required for output. If there is no history, continue with the LLM and/or pack fallback.
- Empty input may be rejected; infrastructure/LLM failure must be represented as a diagnostic fallback, not as a missing-requirement gate.
- Keep existing strict `build_envelope_from_requirements(...)` behavior for callers that do not opt into provisional mode.

---

## Task 1: Add the concept-level LLM enrichment contract

**Files:**

- Create `src/rflp_lite/application/concept_llm_enrichment.py`.
- Modify `src/rflp_lite/application/intelligence/project_analysis.py`.
- Create `tests/application/test_concept_llm_enrichment.py`.
- Preserve existing `tests/application/intelligence/test_project_analysis.py` assertions.

- [ ] **1.1 Write the failing adapter tests first.**

Use the existing `GenerationResponse` fixture pattern and a model whose `complete_json()` returns the current project-analysis fields plus:

```python
{
    "concept_proposal": {
        "summary": "城市巡检智能飞行器概念",
        "alternatives": ["固定翼长航时", "多旋翼低速悬停"],
        "rationale": ["输入强调城市巡检", "任务细节仍需补充"],
        "assumptions": ["暂未指定续航和载荷"],
        "parameter_suggestions": [
            {"name": "cruise_speed_mps", "value": 28, "unit": "m/s", "reason": "巡检初始估计"}
        ],
    },
    "system": {"name": "城市巡检飞行器", "domain": "uncrewed aerial vehicle"},
    "stakeholders": [], "concerns": [], "needs": [], "requirements": [],
    "scenarios": [], "architecture": {}, "open_questions": ["续航时间"],
}
```

Assert that `enrich_concept_input(...)`:

- calls the configured model once;
- returns `status == "completed"`;
- preserves a domain-neutral analysis under `state["llm_analysis"]`;
- returns stable `concept_proposal` and `parameter_suggestions` entries with `producer == "llm"`, `candidate_type == "suggested"`, and source/input provenance;
- returns a non-failing diagnostic result when the provider is absent or raises, without inventing a fixed-wing concept.

- [ ] **1.2 Extend the existing project-analysis response schema without changing required fields.**

In `project_analysis.py`, add optional `concept_proposal` fields to `_RESPONSE_SCHEMA` and update `_SYSTEM_PROMPT` to request:

- a domain-neutral system/requirements/scenario/RFLP analysis;
- a concept proposal for broad design intent;
- suggested parameters only when reasonable, always marked inferred/suggested;
- assumptions and open questions instead of pretending missing facts are verified.

Do not add these fields to `required`, so old providers and all existing project-analysis tests remain valid. Normalize the optional object in `apply_project_analysis()` into `state["concept_enrichment"]` with stable IDs and provenance fields.

- [ ] **1.3 Implement the adapter.**

Define:

```python
@dataclass(frozen=True, slots=True)
class ConceptLLMResult:
    state: dict[str, object]
    concept_proposal: dict[str, object]
    parameter_suggestions: tuple[dict[str, object], ...]
    status: str
    diagnostics: tuple[str, ...]
    provider_id: str = ""
    model_id: str = ""


def enrich_concept_input(
    state: dict[str, object],
    *,
    active_config: Mapping[str, object] | None,
    model_factory: Callable[[dict[str, object]], GenerativeModel | None],
) -> ConceptLLMResult:
    ...
```

Reuse `build_project_analysis_request()` and `apply_project_analysis()` rather than duplicating provider protocol code. Normalize the active config the same way as `WebFacade._project_analysis_model()` (JSON response format and provider-specific reasoning switches). Catch model construction/completion/normalization failures, retain the incoming state, and return `status == "fallback"` with actionable diagnostics.

- [ ] **1.4 Run focused tests and commit.**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/pytest -q \
  tests/application/intelligence/test_project_analysis.py \
  tests/application/test_concept_llm_enrichment.py
```

Commit: `feat: add llm concept enrichment contract`.

## Task 2: Make envelope construction support typed LLM suggestions and provisional values

**Files:**

- Modify `src/rflp_lite/application/requirement_to_envelope.py`.
- Modify/add tests in `tests/application/test_requirement_to_envelope.py` (or the repository’s existing envelope test file).

- [ ] **2.1 Add failing tests for precedence and provisional behavior.**

Cover a fixed-wing pack with:

1. an explicit `cruise_speed_mps` requirement and a conflicting LLM suggestion: explicit value wins and provenance remains explicit;
2. no history and incomplete requirements with valid LLM suggestions: the result has an envelope and `provisional == True`/candidate status;
3. no LLM suggestion for a required field: a declared pack default or safe midpoint of a declared min/max is used with `source_kind == "suggested_default"`;
4. an invalid/out-of-range LLM value: it is ignored and added to diagnostics;
5. existing strict calls without `provisional=True`: missing required fields still return `envelope is None`.

- [ ] **2.2 Extend the function with opt-in parameters.**

Use this signature while preserving positional compatibility:

```python
def build_envelope_from_requirements(
    pack: Mapping[str, object],
    requirements: Sequence[Mapping[str, object]],
    *,
    attributes: Sequence[Mapping[str, object]] = (),
    constraints: Sequence[Mapping[str, object]] = (),
    history: Sequence[SchemeRecord | Mapping[str, object]] = (),
    llm_suggestions: Sequence[Mapping[str, object]] = (),
    provisional: bool = False,
) -> RequirementEnvelopeResult:
    ...
```

Merge valid LLM suggestions after explicit/derived values and before history/defaults. Record them as `source_kind == "suggested_llm"`, with producer/model/input provenance. For `provisional=True`, fill unresolved required values only from a pack default or a declared numeric range midpoint, record `source_kind == "suggested_default"`, and return a candidate/provisional envelope instead of `None`. Never bypass range, type, unit, or hard-constraint validation. Keep the existing missing-field failure path when provisional mode is false.

- [ ] **2.3 Run focused envelope tests and commit.**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/pytest -q \
  tests/application/test_requirement_to_envelope.py \
  tests/application/test_concept_llm_enrichment.py
```

Commit: `feat: support provisional llm envelope suggestions`.

## Task 3: Integrate LLM-first soft gates into the orchestrator

**Files:**

- Modify `src/rflp_lite/application/intelligent_concept_workflow.py`.
- Modify `src/rflp_lite/application/dependencies.py` only if a typed dependency alias is needed.
- Modify `tests/application/test_intelligent_concept_workflow.py`.
- Add/extend tests for the existing fixed-wing and no-pack paths.

- [ ] **3.1 Write failing workflow tests.**

Add cases for:

- `ConceptWorkflowRequest(workspace_name="...", text="我想做一个适合城市巡检的智能飞行器。", pack="auto")` with a fixture LLM: status is not failed, an LLM concept proposal is persisted, MBSE draft exists, and missing formal values are diagnostics/provisional state;
- the same broad input with no LLM config and no history: status is not failed and contains a deterministic temporary draft/fallback diagnostics;
- an explicit `pack="fixed-wing-v1"` with LLM suggestions but no history: the full professional candidate/evaluation path still runs when values can be completed;
- explicit numeric input conflicting with an LLM suggestion: explicit input remains in the resulting envelope;
- non-aviation generic input with `pack="auto"`: no fixed-wing physics is fabricated, while concept/MBSE output is still returned.

- [ ] **3.2 Add LLM provider injection and request/result fields.**

Extend `ConceptWorkflowOrchestrator.__init__` with:

```python
llm_config_provider: Callable[[], Mapping[str, object] | None] | None = None
```

Change the default request pack to `"auto"` (accept `None` as equivalent). Extend `ConceptWorkflowResult` and `from_payload()` with `concept_proposal`, `llm_analysis`, `enrichment`, and a clear provisional/execution mode field, keeping old payloads loadable through defaults.

- [ ] **3.3 Insert enrichment before envelope construction.**

After document/rule analysis and before `build_envelope_from_requirements()`:

1. call `enrich_concept_input()` with the current state and injected config/model factory;
2. merge its structured requirements/attributes without replacing explicit rule values;
3. resolve a pack: explicit pack first; otherwise use a defensible LLM/rule domain hint for a known pack; otherwise leave the professional pack unset;
4. if a pack exists, call `build_envelope_from_requirements(..., llm_suggestions=..., provisional=True)`;
5. if no pack exists, preserve the LLM concept/MBSE draft, mark professional steps as provisional/skipped with diagnostics, and do not run fixed-wing evaluation/optimization;
6. remove the current unconditional `ContractViolation` on an incomplete envelope. Keep exceptions for empty content, malformed persisted state, and illegal values/hard-constraint violations.

History retrieval remains additive. `_ensure_history()` may retain explicit demo seeding for the demo fixed-wing path, but the orchestrator must run correctly with an empty history and must not report history absence as a failure.

- [ ] **3.4 Preserve the existing complete fixed-wing flow and run focused tests.**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/pytest -q \
  tests/application/test_intelligent_concept_workflow.py \
  tests/application/test_scheme_import_mapper.py \
  tests/e2e/test_concept_workflow_demo.py
```

Commit: `feat: integrate llm-first soft-gated concept workflow`.

## Task 4: Connect the WebFacade, API, routes, and concept page

**Files:**

- Modify `src/rflp_lite/application/web_facade.py`.
- Modify `src/rflp_lite/interface/web/api_v1.py`.
- Modify `src/rflp_lite/interface/web/routes.py`.
- Modify `src/rflp_lite/interface/web/templates/concept-design.html`.
- Modify relevant interface tests under `tests/interface/` and `tests/e2e/`.

- [ ] **4.1 Write failing interface tests.**

Verify that a concept-workflow API request with only a non-empty `text` and no `pack` returns HTTP success with:

- non-failed workflow status;
- `concept_proposal`/`enrichment` fields (or explicit fallback diagnostics when LLM is unavailable);
- a provisional status when formal pack fields are not available;
- no forced `fixed-wing-v1` in the request payload for generic text.

Keep explicit fixed-wing API requests backward compatible and preserve existing response fields.

- [ ] **4.2 Wire the active LLM profile into the orchestrator.**

Construct the orchestrator with `llm_config_provider=lambda: self.llm.active_config()` and expose the existing model factory through the enrichment adapter. Make omitted pack values resolve to `"auto"`; explicit pack selection remains authoritative.

- [ ] **4.3 Update API/routes/template presentation.**

Use `auto` as the omitted/default pack in API and HTML routes. Add a compact concept proposal panel showing summary, alternatives, assumptions, open questions, and provenance. Show diagnostics/history absence as informational. Render professional envelope/evaluation/optimization panels only when those sections exist; keep the existing fixed-wing candidate UI unchanged for full runs.

- [ ] **4.4 Run interface tests and commit.**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/pytest -q \
  tests/interface/test_auto_requirements.py \
  tests/e2e/test_concept_workflow_demo.py \
  tests/interface
```

Commit: `feat: expose llm-first concept results in web flow`.

## Task 5: Document behavior and perform full verification

**Files:**

- Modify `README.md` with a short concept-workflow note: any non-empty requirement yields a provisional concept; configure an LLM for richer proposals; professional packs/history are optional enhancers; explicit values and hard validation remain authoritative.
- Keep `docs/superpowers/specs/2026-09-02-concept-workflow-soft-gates-design.md` as the design source of truth.

- [ ] **5.1 Add/adjust regression assertions for status and provenance.**

Ensure `ConceptWorkflowResult.to_payload()`/`from_payload()` round-trip old and new payloads, and that every generated field can be traced to explicit, derived, history, pack default, LLM suggestion, or provisional fallback source.

- [ ] **5.2 Run the full suite and static checks.**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/pytest -q
git diff --check
ruff check src tests scripts
```

If Ruff reports the already-known untouched `model_impact.py`/`traceability.py` E702 findings, record them as pre-existing and do not broaden this change to unrelated files. Fix only failures introduced by this implementation.

- [ ] **5.3 Manually smoke-test the exact user scenario.**

Run the workflow with:

```text
我想做一个适合城市巡检的智能飞行器。
```

Confirm that it returns a concept proposal and MBSE draft even with no history; with an active LLM, confirm that the proposal is LLM-produced and that any formal pack/evaluation is visibly provisional unless enough typed values are available.

- [ ] **5.4 Commit documentation and verification adjustments.**

Commit: `docs: explain llm-first concept workflow behavior`.

## Self-review checklist

- [ ] Search the plan for `TODO`, `TBD`, placeholder ellipses, or unspecified “later” work; none remain.
- [ ] Confirm every implementation task names exact files, callable interfaces, precedence rules, tests, and a commit boundary.
- [ ] Confirm the plan does not require staging or modifying the user’s unrelated OCR/test/assets changes.
- [ ] Confirm any non-empty input has a success/provisional path when LLM, history, and pack are all absent.
- [ ] Confirm strict validation remains active for illegal explicit/derived/LLM values and hard constraints.
- [ ] Confirm the plan satisfies the approved LLM-first design and does not turn professional packs into a hidden prerequisite.
