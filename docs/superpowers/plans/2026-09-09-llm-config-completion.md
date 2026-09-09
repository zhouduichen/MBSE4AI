# LLM 配置闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** Complete local LLM configuration for OpenAI-compatible and Ollama providers, including real connectivity checks, profile lifecycle controls, and runtime-visible diagnostics.

**Architecture:** Extend the existing LLMProfileService as the source of normalized profile data and key storage, keep provider-specific HTTP behavior in adapters/llm_client.py, and let RuntimeFactory consume the active normalized config on every analysis start. FastAPI routes expose profile CRUD/test operations while the settings template renders provider presets and test feedback without rendering credentials.

**Tech Stack:** Python 3.11+, FastAPI, urllib, Keyring/session fallback, Jinja2/vanilla JavaScript, pytest/TestClient.

## Global Constraints

- Support provider values openai-compatible and ollama.
- Preserve existing profile JSON and infer provider for old profiles without rewriting secrets.
- Keep API keys out of JSON config, HTML, API responses, and error bodies.
- Keep the default local-only bind at 127.0.0.1 and introduce no external service.
- Preserve existing workspaces, analysis behavior, CLI commands, and architecture budgets.

---

### Task 1: Provider-aware profile normalization and lifecycle

**Files:** Modify src/rflp_lite/application/llm_profiles.py and src/rflp_lite/application/settings_service.py. Test tests/application/test_llm_profiles.py.

**Produces:** normalize_profile returns provider; presets returns public provider presets; delete removes a profile and repairs active_id; SettingsService.delete_profile delegates deletion.

- [ ] Write tests for old-profile provider inference, provider validation, presets, deleting active/inactive profiles, and preserving an existing key when an edit form leaves Key blank.
- [ ] Run .venv/bin/python -m pytest tests/application/test_llm_profiles.py -q and confirm the new assertions fail.
- [ ] Add provider normalization: explicit openai/openai-compatible/openai_chat maps to openai-compatible; explicit ollama/ollama-native or a URL containing 11434/ollama maps to ollama; other valid profiles default to openai-compatible. Reject other values.
- [ ] Add public presets and delete behavior. Deleting the active profile selects the first remaining profile or sets active_id to None. Never write API keys to JSON.
- [ ] Run the focused tests and confirm they pass.
- [ ] Commit only this task with message feat: normalize provider-aware LLM profiles.

### Task 2: Real provider connectivity checks

**Files:** Modify src/rflp_lite/adapters/llm_client.py and src/rflp_lite/interface/web/resource_api.py. Test tests/adapters/test_llm_client.py and tests/interface/web/test_settings_runtime_status.py.

**Produces:** test_connection sends a minimal completion through the selected provider and maps failures to safe connection statuses.

- [ ] Add mock HTTP tests for OpenAI-compatible /chat/completions, native Ollama /api/chat, success, 401/403, unreachable, timeout, invalid JSON, and empty responses.
- [ ] Run .venv/bin/python -m pytest tests/adapters/test_llm_client.py -q and confirm the new tests fail.
- [ ] Dispatch by provider while preserving existing native Ollama behavior. OpenAI-compatible uses Bearer Key when present; Ollama sends stream=false and think=false. Missing remote Key returns not_configured without a network request.
- [ ] Map errors to connected, authentication_failed, unreachable, invalid_response, or not_configured. Do not return response bodies or credentials.
- [ ] Run adapter and settings tests and confirm they pass.
- [ ] Commit this task with message feat: validate real LLM provider connectivity.

### Task 3: Profile presets and CRUD/test API

**Files:** Modify src/rflp_lite/interface/web/resource_api.py and src/rflp_lite/application/settings_service.py. Test tests/interface/web/test_settings_runtime_status.py.

**Produces:** GET /model-profiles/presets and DELETE /model-profiles/{profile_id}; existing save/test/activate routes remain compatible and secret-free.

- [ ] Add TestClient tests for presets, delete active/inactive profiles, active-id repair, and secret-free responses.
- [ ] Run the focused Web tests and confirm the new routes fail with 404.
- [ ] Add routes delegating to SettingsService and use the existing 422 error mapping.
- [ ] Run focused Web tests and confirm they pass.
- [ ] Commit this task with message feat: expose LLM profile presets and deletion.

### Task 4: Settings UI and runtime visibility

**Files:** Modify src/rflp_lite/interface/web/templates/settings.html, src/rflp_lite/interface/web/resource_pages.py, and src/rflp_lite/interface/web/static/app.css. Test tests/interface/web/test_app.py and tests/interface/web/test_settings_runtime_status.py.

**Produces:** provider selector, preset controls, edit fields, real test feedback, activate/delete controls, and active runtime profile/provider/model labels.

- [ ] Add failing page assertions for provider, presets, delete, test result, and runtime labels.
- [ ] Run the focused page tests and confirm the controls are absent.
- [ ] Render provider and preset controls; preset selection fills provider, URL, and model without sending a Key. Save uses blank-Key preservation. Test feedback displays status and safe message. Delete uses a confirmation and reloads after success.
- [ ] Run page/API tests and confirm they pass.
- [ ] Commit this task with message feat: complete LLM settings workflow UI.

### Task 5: Active profile selection and safe analysis diagnostics

**Files:** Modify src/rflp_lite/runtime/factory.py and src/rflp_lite/methodology/workflow.py. Test tests/runtime/test_factory.py, creating it if absent, and tests/interface/web/test_analysis_workflow.py.

**Produces:** disabled active profiles are rejected clearly; a new run records selected profile/provider/model; LLM failures remain degraded with safe diagnostics; no active profile still uses offline RuleRuntime.

- [ ] Add tests for disabled-profile rejection, active-profile selection after activation, and degraded diagnostics without credentials or provider response bodies.
- [ ] Run focused runtime/analysis tests and confirm the new assertions fail.
- [ ] Implement the checks and diagnostics without changing the offline fallback.
- [ ] Run focused tests and confirm they pass.
- [ ] Commit this task with message feat: record and validate active LLM runtime.

### Task 6: Full verification and browser acceptance

**Files:** Modify docs/DEVELOPMENT_STATUS.md. Test the existing suite.

- [ ] Run pytest, compileall, Ruff, lint-imports, and architecture metrics.
- [ ] Inspect the live local settings UI: presets, save, test feedback, activate, delete, and active runtime summary. Use an isolated test config and do not overwrite existing profiles or delete existing projects.
- [ ] Update the status document with provider-aware configuration and explicit offline/remote boundaries.
- [ ] Commit documentation and verification with message test: verify completed LLM configuration workflow.
