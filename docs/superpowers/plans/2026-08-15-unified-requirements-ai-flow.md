# Unified Requirements AI Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make “提交并分析” run the structured AI discovery pipeline and populate the existing requirements, stakeholder, scenario, RFLP, and MBSE modules in one pass.

**Architecture:** Keep the existing discovery and bridge services as internal application components, but invoke them from the normal requirements submission flow. Configure structured DeepSeek calls with JSON mode and disabled thinking, auto-accept generated discovery candidates according to the agreed product rule, and preserve deterministic results plus diagnostics when the model fails.

**Tech Stack:** Python 3.12, FastAPI, SQLite workbench state, OpenAI-compatible HTTP API, pytest.

## Global Constraints

- LLM request defaults and fallback timeouts remain 300 seconds.
- Structured model calls must return JSON objects and must not depend on `reasoning_content` as the primary answer.
- One user-facing submission flow owns the analysis; the standalone discovery navigation entry is hidden.
- Generated candidates are accepted automatically by the current product rule, while model failures remain visible as diagnostics.

---

### Task 1: Make structured LLM responses compatible

**Files:**
- Modify: `src/rflp_lite/adapters/llm_client.py`
- Modify: `src/rflp_lite/adapters/openai_compatible_model.py`
- Modify: `src/rflp_lite/application/intelligence/expansion.py`
- Test: `tests/adapters/test_llm_client.py`
- Test: `tests/adapters/test_openai_compatible_model.py`

- [ ] Add request-body support for configured `response_format` and `thinking` options, with text-content extraction that tolerates empty content and JSON code fences.
- [ ] Configure discovery calls for JSON mode and disabled DeepSeek thinking; cap each lens at six concise items and allow 5000 output tokens.
- [ ] Add tests for response options, `reasoning_content` fallback, fenced JSON, and valid structured output.

### Task 2: Orchestrate automatic requirements completion

**Files:**
- Modify: `src/rflp_lite/application/intelligence/service.py`
- Modify: `src/rflp_lite/application/intelligence/bridge.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Test: `tests/interface/web/test_requirements.py`
- Test: `tests/interface/web/test_discovery.py`

- [ ] Add an application-level auto-completion method that drafts discovery, accepts candidates, bridges them into the existing workbench collections, generates scenarios, RFLP/baseline, and MBSE when the available data satisfies each generator.
- [ ] Preserve the rule-analysis state and append a diagnostic when structured model generation fails.
- [ ] Invoke that method from the normal requirements submission endpoint and redirect to the requirements hub.
- [ ] Keep legacy discovery API routes callable for compatibility but remove the standalone discovery link from primary navigation.

### Task 3: Align the user-facing pages and regression coverage

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/base.html`
- Modify: `src/rflp_lite/interface/web/templates/requirements-input.html`
- Modify: `src/rflp_lite/interface/web/templates/requirements-hub.html`
- Test: `tests/interface/web/test_pages.py`

- [ ] Replace “规则分析已完成” with automatic-analysis status and show counts/diagnostics for the populated modules.
- [ ] Remove the standalone “智能补全与架构发现” navigation item and expose the populated modules through the existing requirements navigation.
- [ ] Verify a submission with a fake structured model populates stakeholders, concerns, needs, scenarios, structured requirements, RFLP, and MBSE without a second button.

### Task 4: Run verification

- [ ] Run focused adapter and requirements workflow tests.
- [ ] Run the complete pytest suite with an isolated configuration directory so no real LLM request is sent by tests.
- [ ] Confirm the live Profile still reports `timeout_seconds=300` and document the restart requirement for the modified server process.
