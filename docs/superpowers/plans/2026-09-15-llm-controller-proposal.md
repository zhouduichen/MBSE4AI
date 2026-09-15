# LLM Controller 决策提案 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use inline execution in this session, task-by-task with the checkpoints below. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Add an optional remote-LLM Controller proposal layer that recommends a valid existing engineering action without mutating ModelGraph, then lets the user confirm through the existing Controller/CAS/reanalysis flow.

**Architecture:** Keep SystemsEngineeringController.plan() as the deterministic action catalog and execution authority. Add LLMController as a read-only recommendation service using the existing GenerativeModel.complete_json(GenerationRequest) port; it receives bounded graph/methodology/action context, returns only existing action_id/option_id references, and is validated before being attached to ControllerPlan. RuntimeFactory constructs one OpenAI-compatible model for both stage generation and Controller proposals; offline RuleRuntime has no proposal model and remains deterministic.

**Tech Stack:** Python 3.11+, dataclasses, existing OpenAI-compatible adapter, JSON Schema, MethodologyEngine, ModelGraph, FastAPI/Jinja, pytest, Ruff, import-linter.

## Global Constraints

- Do not call 127.0.0.1:11434 or start any local model.
- Use the existing GenerativeModel.complete_json(GenerationRequest) provider port; do not add a direct HTTP client or a second provider implementation.
- ControllerAction remains the only executable action catalog; LLM output can reference IDs but cannot introduce action kinds, task IDs, stages, entity IDs, Patch operations, or revisions.
- LLMController is read-only: it never writes ModelGraph, Repository, Run, Patch, Evidence, or Review state.
- A missing, unavailable, malformed, or semantically invalid remote proposal falls back to the deterministic Controller plan and cannot fail an otherwise successful model-generation run.
- A user must explicitly submit the existing action_id and, for a Trade Study, option_id before any reanalysis or model mutation occurs.
- Keep iterate_controller deterministic; it must not use the LLM proposal as an automatic execution command.
- Bound Controller context and response diagnostics; never expose API keys or unbounded raw provider output.
- Preserve offline RuleRuntime, existing five-stage R→F→L→P→V&V behavior, SysML round-trip, CAS, locked-entity protection, and current API fields.

---

## File Map

| File | Responsibility in this slice |
|---|---|
| src/rflp_lite/methodology/controller.py | Add immutable ControllerProposal and attach it optionally to ControllerPlan; keep deterministic action selection unchanged. |
| src/rflp_lite/methodology/llm_controller.py | Build bounded Controller context, call the existing model port, validate references, and return a safe proposal/fallback. |
| src/rflp_lite/runtime/factory.py | Expose the provider model used by configured structured runtime as an optional Controller model; keep offline selections empty. |
| src/rflp_lite/adapters/openai_compatible_model.py | Mark the adapter as eligible for Controller proposal requests. |
| src/rflp_lite/bootstrap/v2.py | Inject the optional LLMController into ModelGenerationService. |
| src/rflp_lite/application/model_generation.py | Attach proposals to user-visible plans/results while keeping execution and automatic iteration deterministic. |
| src/rflp_lite/interface/web/resource_pages.py | Decorate proposal status and business-language labels for templates. |
| src/rflp_lite/interface/web/templates/analysis.html and assurance.html | Display the optional AI recommendation without exposing internal contracts. |
| tests/methodology/test_llm_controller.py | Contract, bounded-context, reference-validation, fallback, and read-only tests. |
| tests/runtime/test_factory.py | Verify one configured provider model is exposed and offline selection remains empty. |
| tests/application/test_model_generation.py | Verify generation/controller query can include a proposal and proposal failure does not mutate or fail the graph. |
| tests/interface/web/test_vertical_generation_api.py and test_analysis_workflow.py | Verify API and HTML presentation; existing action execution remains user-confirmed. |
| docs/DEVELOPMENT_STATUS.md | Record the new proposal layer and remote-provider boundary. |

## Task 1: Define the proposal contract and write failing unit tests

**Files:**

- Create: tests/methodology/test_llm_controller.py
- Modify: src/rflp_lite/methodology/controller.py

**Interfaces:**

- ControllerProposal.as_dict() -> Mapping[str, object]
- ControllerPlan.proposal: ControllerProposal | None
- LLMController.propose(graph, report, plan) -> ControllerProposal (implemented in Task 2)

- [ ] **Step 1: Add tests for immutable proposal serialization.**

    def test_controller_plan_serializes_optional_llm_proposal():
        proposal = ControllerProposal(
            "proposed",
            "controller-action-1",
            "trade-option-1",
            "先比较替代架构，再重新验证受影响需求。",
            ("功耗实测值仍需确认",),
            ("是否允许更换计算平台",),
            (),
            "input-hash",
            "output-hash",
            "openai-compatible",
            "remote-model",
        )
        plan = ControllerPlan(
            "needs_action",
            "推进模型",
            actions=(ControllerAction(
                "controller-action-1", "trade_study", "allocation_tradeoff",
                "physical", "P0", ("physical-1",), "物理冲突",
                ({"id": "trade-option-1", "option": "替代候选"},),
            ),),
            proposal=proposal,
        )

        payload = plan.as_dict()

        assert payload["llm_proposal"]["status"] == "proposed"
        assert payload["llm_proposal"]["action_id"] == "controller-action-1"
        assert payload["llm_proposal"]["option_id"] == "trade-option-1"
        assert payload["actions"][0]["id"] == "controller-action-1"

- [ ] **Step 2: Add LLM Controller tests with a recording model double.**

The test double returns a GenerationResponse whose payload contains the action and option IDs from the bounded request. Assert the request lens is controller.proposal, the payload contains only bounded context, methodology, and controller_plan sections, and the graph revision is unchanged. Add cases for:

For the transport case, the fake raises TransportFailure("remote unavailable", code="network_error", provider_id="remote", model_id="model"); assert proposal.status == "fallback", the diagnostic contains network_error, and no raw response larger than the bounded excerpt is returned. The five concrete test names are test_llm_controller_accepts_only_ids_from_deterministic_plan, test_llm_controller_rejects_unknown_action_without_mutation, test_llm_controller_rejects_unknown_trade_option_without_mutation, test_llm_controller_returns_fallback_on_transport_failure, and test_llm_controller_skips_provider_when_unconfigured_or_no_action.

- [ ] **Step 3: Run the new tests and confirm they fail for missing behavior.**

Run:

    ./.venv/bin/python -m pytest -q tests/methodology/test_llm_controller.py -x

Expected: collection or assertion failure because ControllerProposal and LLMController do not yet exist; existing test files remain untouched.

- [ ] **Step 4: Add the value object and plan overlay.**

Add the following shape to controller.py, preserving all existing positional constructor behavior by putting proposal last:

    @dataclass(frozen=True, slots=True)
    class ControllerProposal:
        status: str
        action_id: str | None
        option_id: str | None
        rationale: str = ""
        assumptions: tuple[str, ...] = ()
        open_questions: tuple[str, ...] = ()
        diagnostics: tuple[str, ...] = ()
        input_hash: str = ""
        output_hash: str = ""
        provider_id: str = ""
        model_id: str = ""

        def as_dict(self) -> Mapping[str, object]:
            return {
                "status": self.status,
                "action_id": self.action_id,
                "option_id": self.option_id,
                "rationale": self.rationale,
                "assumptions": list(self.assumptions),
                "open_questions": list(self.open_questions),
                "diagnostics": list(self.diagnostics),
                "input_hash": self.input_hash,
                "output_hash": self.output_hash,
                "provider_id": self.provider_id,
                "model_id": self.model_id,
            }

Extend ControllerPlan with proposal: ControllerProposal | None = None and add "llm_proposal": self.proposal.as_dict() if self.proposal else None in as_dict(). Do not change action sorting, deduplication, or next_action.

- [ ] **Step 5: Run the contract test.**

Run:

    ./.venv/bin/python -m pytest -q tests/methodology/test_llm_controller.py::test_controller_plan_serializes_optional_llm_proposal

Expected: PASS.

## Task 2: Implement the bounded remote LLM Controller service

**Files:**

- Create: src/rflp_lite/methodology/llm_controller.py
- Test: tests/methodology/test_llm_controller.py

**Interfaces:**

- Consumes ModelGraph, MethodologyReport, ControllerPlan, and optional GenerativeModel.
- Produces only ControllerProposal; it never produces a Patch or executes an action.

- [ ] **Step 1: Add the proposal schema and bounded context helpers.**

The module must expose LLMController and use this provider request shape:

    _PROPOSAL_SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "required": ["action_id", "option_id", "rationale", "assumptions", "open_questions"],
        "properties": {
            "action_id": {"type": ["string", "null"], "maxLength": 128},
            "option_id": {"type": ["string", "null"], "maxLength": 128},
            "rationale": {"type": "string", "maxLength": 800},
            "assumptions": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 200}},
            "open_questions": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 200}},
        },
    }

    class LLMController:
        def __init__(self, model: GenerativeModel | None, *, max_tokens: int = 768):
            self.model = model
            self.max_tokens = max(256, min(int(max_tokens), 1200))

        def propose(self, graph, report, plan) -> ControllerProposal:
            if self.model is None:
                return ControllerProposal("not_configured", None, None)
            if not plan.actions:
                return ControllerProposal("not_needed", None, None)
            context = _bounded_controller_context(graph, report, plan)
            request = GenerationRequest(
                "controller.proposal",
                _CONTROLLER_SYSTEM_PROMPT,
                context,
                _PROPOSAL_SCHEMA,
                self.max_tokens,
            )
            try:
                response = self.model.complete_json(request)
                action_id, option_id, rationale, assumptions, open_questions = _validate_proposal(response.payload, plan)
            except Exception as exc:
                code = str(getattr(exc, "code", "provider_error"))[:64]
                return ControllerProposal(
                    "fallback", None, None,
                    diagnostics=(f"controller_proposal_{code}",),
                    input_hash=canonical_hash(context),
                    provider_id=str(getattr(exc, "provider_id", ""))[:128],
                    model_id=str(getattr(exc, "model_id", ""))[:128],
                )
            return ControllerProposal(
                "proposed", action_id, option_id, rationale, assumptions, open_questions,
                input_hash=canonical_hash(context),
                output_hash=response.output_hash,
                provider_id=response.provider_id,
                model_id=response.model_id,
            )

bounded_controller_context must include at most 48 active entity summaries, 96 relations, 12 findings, 24 impact-path entries, 8 actions, and 8 options per action. Entity summaries may contain only ID, kind, name, status, statement, constraints, and architecture/feasibility status fields. Include graph.revision and graph.snapshot_hash so the recommendation is revision-bound.

- [ ] **Step 2: Implement provider call, strict response validation, and safe fallback.**

Validate provider data even when a fake model bypasses adapter JSON Schema:

    def _validate_proposal(payload, plan):
        if not isinstance(payload, Mapping):
            raise ContractViolation("controller proposal must be an object")
        action_id = str(payload.get("action_id") or "").strip()
        action = next((item for item in plan.actions if item.id == action_id), None)
        if action is None:
            raise ContractViolation("controller proposal references an unknown action")
        option_id = str(payload.get("option_id") or "").strip()
        if action.kind == "trade_study":
            option = next((item for item in action.options if str(item.get("id")) == option_id), None)
            if option is None:
                raise ContractViolation("controller proposal references an unknown trade option")
        elif option_id:
            raise ContractViolation("non-trade controller proposal cannot contain option_id")
        return action_id, option_id or None, _bounded_text(payload.get("rationale")), _bounded_texts(payload.get("assumptions")), _bounded_texts(payload.get("open_questions"))

On success return proposed with response hashes/provider/model. On any TransportFailure, AdapterFailure, StructuredOutputFailure, ContractViolation, or JSON/schema error return fallback with controller_proposal_<code> diagnostic, request hash, and bounded response evidence. Do not re-raise and do not call a second local fallback model.

- [ ] **Step 3: Run all Controller unit tests.**

Run:

    ./.venv/bin/python -m pytest -q tests/methodology/test_llm_controller.py
    ./.venv/bin/ruff check src/rflp_lite/methodology/controller.py src/rflp_lite/methodology/llm_controller.py tests/methodology/test_llm_controller.py

Expected: PASS and no lint errors.

## Task 3: Wire one configured provider model into application plans

**Files:**

- Modify: src/rflp_lite/adapters/openai_compatible_model.py
- Modify: src/rflp_lite/runtime/factory.py
- Modify: src/rflp_lite/bootstrap/v2.py
- Modify: src/rflp_lite/application/model_generation.py
- Modify: tests/runtime/test_factory.py
- Modify: tests/application/test_model_generation.py

**Interfaces:**

- RuntimeSelection.controller_model: GenerativeModel | None.
- Add a keyword-only parameter llm_controller: LLMController | None = None after the existing controller parameter.
- Private application helper _controller_plan(graph, report, *, include_llm: bool = True) -> ControllerPlan.

- [ ] **Step 1: Add the adapter capability marker and factory field.**

Add supports_controller_proposals = True to OpenAICompatibleModel. Add an optional controller_model field at the end of RuntimeSelection. When a configured openai_compatible_runtime(runtime_config) returns a StructuredModelRuntime, expose its .model only when the model has supports_controller_proposals is True; otherwise use None. For RuleRuntime and injected deterministic runtimes use None unless the runtime explicitly exposes an eligible model.

The configured path must create one provider model inside openai_compatible_runtime; do not instantiate a second OpenAICompatibleModel for the Controller. Add:

    def test_runtime_factory_exposes_same_configured_model_to_controller():
        selection = RuntimeFactory().select({
            "id": "remote-model", "provider": "openai-compatible", "kind": "remote",
            "base_url": "https://example.invalid/v1", "model": "engineering-model",
            "enabled": True,
        })
        assert selection.controller_model is selection.runtime.model

    def test_runtime_factory_offline_selection_has_no_controller_model():
        selection = RuntimeFactory().select(None)
        assert selection.controller_model is None

- [ ] **Step 2: Inject the service at the composition root.**

In V2Services.generation, construct LLMController(selection.controller_model) and pass it to ModelGenerationService. Keep V2Services.analysis and legacy WorkflowRunner behavior unchanged. Direct application callers continue to work because the new constructor argument defaults to None.

- [ ] **Step 3: Attach proposals only to user-visible plan projections.**

Add this helper to ModelGenerationService:

    def _controller_plan(self, graph, report, *, include_llm=True):
        plan = self.controller.plan(graph, report)
        if include_llm and self.llm_controller is not None:
            return replace(plan, proposal=self.llm_controller.propose(graph, report, plan))
        return plan

Use it for the final plan returned by generate, reanalyze, continue_generation, and controller_plan. In execute_controller_action, always use self.controller.plan(...) without the proposal so submitted IDs are checked against the current deterministic catalog. In iterate_controller, use the deterministic plan for every loop decision and attach at most one proposal to the final read-only response.

If LLMController.propose returns fallback, the surrounding generation result remains completed/completed_with_warnings according to its existing traceability and methodology logic; the fallback status is visible only in controller.llm_proposal and the bounded audit payload.

- [ ] **Step 4: Add application tests for read-only and non-blocking behavior.**

Use a fake proposal model that selects plan.actions[0].id from the request payload. Assert:

    plan = generation.controller_plan("robot")
    assert plan["llm_proposal"]["status"] == "proposed"
    assert repository.load_graph("robot").revision == revision_before

    failed_result = service_with_failing_proposal.generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    assert failed_result.status in {"completed", "completed_with_warnings"}
    assert failed_result.controller.proposal.status == "fallback"

Also assert iterate_controller(max_iterations=1) still executes controller.next_action, not an arbitrary action ID returned by the fake LLM.

- [ ] **Step 5: Run the application wiring tests.**

Run:

    ./.venv/bin/python -m pytest -q tests/runtime/test_factory.py tests/methodology/test_llm_controller.py tests/application/test_model_generation.py -x

Expected: PASS; no test may make a network request.

## Task 4: Expose the proposal in API and Web business language

**Files:**

- Modify: src/rflp_lite/interface/web/resource_pages.py
- Modify: src/rflp_lite/interface/web/templates/analysis.html
- Modify: src/rflp_lite/interface/web/templates/assurance.html
- Modify: tests/interface/web/test_vertical_generation_api.py
- Modify: tests/interface/web/test_analysis_workflow.py

**Interfaces:**

- Existing GET /projects/{project_id}/controller returns controller.llm_proposal through ControllerPlan.as_dict().
- Existing POST /projects/{project_id}/controller/execute remains the only execution endpoint and keeps action_id, option_id, and expected_revision semantics.

- [ ] **Step 1: Decorate proposal fields without changing the API contract.**

Extend _decorate_controller with a bounded view:

    proposal = _mapping(controller.get("llm_proposal"))
    if proposal:
        value["llm_proposal"] = {
            **proposal,
            "status_label": {
                "proposed": "AI 建议",
                "fallback": "确定性 Controller",
                "not_configured": "未配置模型",
                "not_needed": "暂无建议",
            }.get(str(proposal.get("status")), "Controller 建议"),
        }

When reconstructing a historical controller from model_generation.controller_planned audit, include llm_proposal in the allowlisted fields. Never include raw provider messages or credentials.

- [ ] **Step 2: Add a compact proposal block to Analysis and Assurance pages.**

Show the status label, rationale, assumptions, and open questions in Chinese. Do not show provider URLs, schema, TaskSpec, Patch, CAS, raw hashes, or internal action IDs as primary text. Keep existing action buttons and Trade Study option buttons unchanged; the proposal block is informational and has no automatic click handler.

- [ ] **Step 3: Add API and HTML assertions.**

With the existing offline client, assert the controller response still contains actions and next_action, and llm_proposal is either absent or not_configured rather than a fabricated LLM result. With a configured fake proposal container, assert the endpoint exposes status, rationale, and selected IDs, while the page contains the Chinese proposal label and still posts to /controller/execute for confirmation.

- [ ] **Step 4: Run interface tests.**

Run:

    ./.venv/bin/python -m pytest -q tests/interface/web/test_vertical_generation_api.py tests/interface/web/test_analysis_workflow.py tests/interface/web/test_assurance_view.py

Expected: PASS with existing user-confirmation behavior intact.

## Task 5: Update product status and run complete gates

**Files:**

- Modify: docs/DEVELOPMENT_STATUS.md
- Test: all existing suites and the new Controller tests.

- [ ] **Step 1: Record the product capability boundary.**

Add one status row stating that configured OpenAI-compatible profiles can provide a read-only LLM Controller recommendation, the recommendation is checked against deterministic actions, and model mutation still requires user confirmation. State that offline mode remains deterministic and live verification requires the remote SSH/Tailscale model.

- [ ] **Step 2: Run the focused product acceptance command.**

    ./.venv/bin/python -m pytest -q tests/methodology/test_llm_controller.py tests/runtime/test_factory.py tests/application/test_model_generation.py tests/interface/web/test_vertical_generation_api.py tests/interface/web/test_analysis_workflow.py

Expected: PASS.

- [ ] **Step 3: Run all repository gates.**

    ./.venv/bin/python -m pytest -q
    ./.venv/bin/python -m compileall -q src tests scripts
    ./.venv/bin/ruff check src tests scripts
    ./.venv/bin/python scripts/architecture_metrics.py
    ./.venv/bin/lint-imports
    git diff --check

Expected architecture metrics remain within architecture_budget.json, especially dict_str_object_occurrences <= 119, and import-linter reports zero broken contracts.

- [ ] **Step 4: Commit the implementation.**

    git add src/rflp_lite/methodology/controller.py src/rflp_lite/methodology/llm_controller.py src/rflp_lite/runtime/factory.py src/rflp_lite/adapters/openai_compatible_model.py src/rflp_lite/bootstrap/v2.py src/rflp_lite/application/model_generation.py src/rflp_lite/interface/web/resource_pages.py src/rflp_lite/interface/web/templates/analysis.html src/rflp_lite/interface/web/templates/assurance.html tests/methodology/test_llm_controller.py tests/runtime/test_factory.py tests/application/test_model_generation.py tests/interface/web/test_vertical_generation_api.py tests/interface/web/test_analysis_workflow.py tests/interface/web/test_assurance_view.py docs/DEVELOPMENT_STATUS.md
    git commit -m "feat: add bounded LLM controller proposals"

- [ ] **Step 5: Push and perform the remote-only smoke check.**

    git push origin HEAD
    ssh -o BatchMode=yes -o ConnectTimeout=8 -o ConnectionAttempts=1 autoresearch-5080 'hostname && powershell.exe -NoProfile -Command "& ollama.exe list"'

Only if SSH responds, run exactly one configured remote vertical smoke:

    ./.venv/bin/python tests/mbse_benchmark/run_benchmark.py --track llm --profile windows-5080-ollama --path vertical --case CASE-04 --repeats 1 --timeout 900 --baseline bare

If the node is offline, record the timeout and do not substitute a local endpoint or local model. Final status must distinguish deterministic/fixture acceptance from live remote-provider acceptance.
