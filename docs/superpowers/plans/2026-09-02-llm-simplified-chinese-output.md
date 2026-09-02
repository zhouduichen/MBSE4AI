# LLM 简体中文输出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让所有业务 LLM 请求在输入中文、英文或混合资料时，均要求以简体中文返回自然语言结果，同时保持协议字段、追溯标识和英文原始证据兼容。

**Architecture:** 在 `generative_model` 端口层定义唯一的中文输出指令和拼接函数；`OpenAICompatibleModel` 在发送首次 JSON 请求及修复请求前统一注入该指令，因此现有各业务提示词无需重复修改。旧的可注入 completion 路径在其任务提示中复用同一指令，连接探活请求继续保留 `OK` 语义。

**Tech Stack:** Python 3.12、OpenAI-compatible/Ollama Chat API、pytest、现有 JSON Schema 校验。

## Global Constraints

- 所有自然语言输出字段必须使用简体中文；输入资料可以是中文、英文或混合语言。
- JSON 字段名、内部 ID、来源区域 ID、哈希值、固定枚举值、型号、标准编号、单位和必要专有名词保持原样。
- 用户输入的英文原文、文件名、来源定位和历史证据不得被改写。
- 首次结构化请求和 JSON 修复请求都必须带有中文输出指令。
- 不增加独立机器翻译服务，不改变现有 JSON Schema、合并、追溯和 LLM 连接流程。
- LLM 连接测试继续使用 `OK` 探活语义，不把探活结果视为业务内容。
- 只修改本计划涉及的源代码、测试和计划文件；保留已有 OCR、测试和资料文件改动。

---

## 文件与职责

- Modify: `src/rflp_lite/ports/generative_model.py` — 定义共享中文输出指令和纯函数拼接入口。
- Modify: `src/rflp_lite/adapters/openai_compatible_model.py` — 在首次请求和 JSON 修复请求发送前注入共享指令。
- Modify: `src/rflp_lite/application/requirement_inference.py` — 为旧的可注入 completion 请求补充共享中文指令。
- Test: `tests/adapters/test_openai_compatible_model.py` — 验证首次请求与修复请求的 system prompt。
- Test: `tests/application/test_requirement_inference.py` — 验证旧 completion 路径传入的任务提示包含中文约束。

## Task 1: 建立共享中文输出提示并覆盖结构化适配器

**Files:**
- Modify: `src/rflp_lite/ports/generative_model.py`
- Modify: `src/rflp_lite/adapters/openai_compatible_model.py`
- Test: `tests/adapters/test_openai_compatible_model.py`

**Interfaces:**
- Produces `SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION: str` and `add_simplified_chinese_instruction(prompt: str) -> str` from `rflp_lite.ports.generative_model`.
- `OpenAICompatibleModel.complete_json(request)` keeps the existing signature and response contract; only outgoing system message content changes.

- [ ] **Step 1: Write failing tests for initial and repair prompts**

In `tests/adapters/test_openai_compatible_model.py`, import `SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION` and extend the first adapter test to capture the sent messages:

```python
from rflp_lite.ports.generative_model import (
    GenerationRequest,
    SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION,
)


def test_adapter_adds_simplified_chinese_instruction_to_initial_prompt():
    calls = []

    def complete(_config, messages, *, max_tokens=None):
        calls.append(messages)
        return '{"items":[]}'

    OpenAICompatibleModel({"model": "local"}, complete=complete).complete_json(request())

    assert SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION in calls[0][0]["content"]
    assert "只返回 JSON" in calls[0][0]["content"]


def test_adapter_adds_simplified_chinese_instruction_to_repair_prompt():
    calls = []
    answers = iter(("not-json", '{"items":[]}'))

    def complete(_config, messages, *, max_tokens=None):
        calls.append(messages)
        return next(answers)

    OpenAICompatibleModel({"model": "local"}, complete=complete).complete_json(request())

    assert SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION in calls[1][0]["content"]
    assert "重新生成完整的 JSON 分析结果" in calls[1][0]["content"]
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
pytest -q tests/adapters/test_openai_compatible_model.py -k "simplified_chinese or repair_prompt"
```

Expected: FAIL because the current adapter forwards the caller's system prompt unchanged and the repair prompt does not contain the shared instruction.

- [ ] **Step 3: Add the shared instruction and pure prompt helper**

In `src/rflp_lite/ports/generative_model.py`, add this constant and function before `GenerationRequest`:

```python
SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION = (
    "面向中国用户输出。无论输入资料使用何种语言，所有自然语言输出字段必须使用简体中文；"
    "不得因为输入是英文而用英文回答。保留 JSON 字段名、ID、固定枚举值、型号、标准编号、"
    "单位和必要专有名词原样。"
)


def add_simplified_chinese_instruction(prompt: str) -> str:
    """Prefix one LLM prompt with the product's natural-language output rule."""

    return f"{SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION}\n{str(prompt).strip()}"
```

- [ ] **Step 4: Inject the helper into both adapter requests**

In `src/rflp_lite/adapters/openai_compatible_model.py`, import `add_simplified_chinese_instruction`, then make the two outgoing system messages use it:

```python
"content": add_simplified_chinese_instruction(request.system_prompt),
```

and in `_repair_messages`:

```python
"content": add_simplified_chinese_instruction(
    f"重新生成完整的 JSON 分析结果，最多返回 {max_items} 项；"
    "保留有效内容，修复结构，不要解释，也不要用空数组规避任务。"
),
```

Do not change `GenerationRequest.system_prompt`, the user payload, response schema, hashes, or the direct `chat_completion` connection-test request.

- [ ] **Step 5: Run the adapter tests and verify they pass**

Run:

```bash
pytest -q tests/adapters/test_openai_compatible_model.py
```

Expected: PASS for all adapter tests. The test must still verify that the original request instruction and repair instruction remain present after prefixing.

- [ ] **Step 6: Commit the adapter change**

```bash
git add src/rflp_lite/ports/generative_model.py \
  src/rflp_lite/adapters/openai_compatible_model.py \
  tests/adapters/test_openai_compatible_model.py
git commit -m "feat: require simplified Chinese from structured llm calls"
```

## Task 2: Cover the legacy injectable completion path

**Files:**
- Modify: `src/rflp_lite/application/requirement_inference.py`
- Test: `tests/application/test_requirement_inference.py`

**Interfaces:**
- `suggest_implicit_requirements(..., complete=...)` keeps its current callback signature `complete(config, prompt) -> str`.
- The callback receives the same prompt dictionary as before, with `prompt["task"]` carrying the shared Chinese output instruction plus the existing task text.

- [ ] **Step 1: Write a failing test that captures the legacy prompt**

Add this test to `tests/application/test_requirement_inference.py`:

```python
def test_legacy_completion_prompt_requires_simplified_chinese_output():
    region = DocumentRegion(
        "region-1", "artifact-1", 1, "paragraph", "page-1/paragraph-1", "The system shall import PDF"
    )
    captured = {}

    def complete(_config, prompt):
        captured["prompt"] = prompt
        return '[{"source_region_id":"region-1","statement":"系统应支持导入 PDF","entities":[],"constraints":[],"verification_method":"inspection","confidence":0.6}]'

    suggest_implicit_requirements((region,), {"model": "local"}, complete)

    assert "简体中文" in captured["prompt"]["task"]
    assert "只提出文本中隐含但未明确写出的工程约束" in captured["prompt"]["task"]
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
pytest -q tests/application/test_requirement_inference.py -k "legacy_completion_prompt"
```

Expected: FAIL because the legacy task currently contains only the constraint-generation instruction.

- [ ] **Step 3: Reuse the shared helper in the legacy task**

In `src/rflp_lite/application/requirement_inference.py`, import `add_simplified_chinese_instruction` and replace the task value in `prompt` with:

```python
"task": add_simplified_chinese_instruction(
    "只提出文本中隐含但未明确写出的工程约束；不得改写原文，不得批准结果。"
),
```

Leave source region text, source IDs, schema, validation, and candidate status handling unchanged.

- [ ] **Step 4: Run all requirement inference tests**

Run:

```bash
pytest -q tests/application/test_requirement_inference.py
```

Expected: PASS, including known-source validation and non-bulk-acceptance behavior.

- [ ] **Step 5: Commit the legacy-path change**

```bash
git add src/rflp_lite/application/requirement_inference.py \
  tests/application/test_requirement_inference.py
git commit -m "feat: localize legacy requirement prompts"
```

## Task 3: Run cross-flow regression tests and verify compatibility

**Files:**
- Modify: none.
- Test: existing adapter, requirement, intelligence, concept, and Web/API suites.

**Interfaces:**
- All existing `GenerationRequest` callers continue using their current prompts and schemas; the adapter applies the shared instruction at send time.
- `test_connection` continues returning a preview compatible with `OK`.

- [ ] **Step 1: Run all direct language-boundary tests**

Run:

```bash
pytest -q \
  tests/adapters/test_openai_compatible_model.py \
  tests/adapters/test_llm_client.py \
  tests/application/test_requirement_inference.py \
  tests/application/intelligence/test_project_analysis.py \
  tests/application/intelligence/test_analysis_blocks.py \
  tests/application/test_concept_llm_enrichment.py
```

Expected: PASS. This verifies initial prompts, repair prompts, raw connection testing, English input handling, project analysis, block analysis, and concept enrichment compatibility.

- [ ] **Step 2: Run the complete test suite**

Run:

```bash
pytest -q
```

Expected: PASS with no changes to JSON keys, IDs, enums, source references, or existing degraded-mode behavior.

- [ ] **Step 3: Inspect the final diff and working tree**

Run:

```bash
git diff HEAD~2..HEAD --stat
git status --short
```

Expected: the two feature commits contain only the shared prompt helper, adapter/legacy prompt changes, and their tests; existing user-owned OCR, test, and artifact files remain untouched.
