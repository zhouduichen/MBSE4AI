# L 阶段按 Function 窄批次 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 将 `vertical.logical` 默认切成单 Requirement 请求，并验证 Function→Logical→Interface/State 的完整追溯。

**Architecture:** 复用 `StructuredModelRuntime` 的 worklist、context scoping、Proposal Compiler 和合并 Patch。仅增加 Logical 独立 batch size 与 L-specific prompt；OpenAI-compatible adapter 默认值为 1，显式配置仍可覆盖。

**Tech Stack:** Python 3.11+, pytest, existing structured Proposal compiler.

## Global Constraints

- 不启动本机模型；只使用离线结构化夹具验证。
- 不重写 ModelGraph、CAS、状态机、UI 或 SysML exporter。
- 所有批次完成后才合并为一个 Logical Patch。

---

### Task 1: 固定 Logical singleton 批次

**Files:**
- Modify: `src/rflp_lite/runtime/structured_model.py`
- Modify: `src/rflp_lite/adapters/openai_compatible_model.py`
- Test: `tests/runtime/test_task_execution.py`
- Test: `tests/adapters/test_openai_compatible_model.py`

- [ ] 在 runtime 选择 `vertical.logical` 的专用 batch size，默认 1。
- [ ] 保持其他阶段的既有 batch 行为和显式 override。
- [ ] 为五需求 Logical 请求增加 singleton 断言并更新期望诊断。

### Task 2: 收紧 L 提示词和追溯

**Files:**
- Modify: `src/rflp_lite/runtime/structured_model.py`
- Modify: `src/rflp_lite/resources/prompts/vertical/logical.v1.md`
- Test: `tests/runtime/test_task_specific_prompts.py`

- [ ] 在 batch instruction 中注入当前唯一 Requirement ID。
- [ ] 要求 `function_id`、`connected_component_ids`、`owner_id` 只引用当前切片。
- [ ] 验证 prompt 同时保留“不要机械一功能一组件”的架构指导。

### Task 3: 验证三需求端到端 L 合并

**Files:**
- Modify: `tests/application/test_model_generation.py`

- [ ] 记录三需求夹具的 Logical worklists，断言每批一个 Requirement。
- [ ] 断言三条 Function→LogicalComponent 分配和每个切片的 Interface/State 归属。
- [ ] 运行 focused、full local gate、ruff/diff 检查后提交并推送。
