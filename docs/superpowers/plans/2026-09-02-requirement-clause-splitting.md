# 需求文档保守切分 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让需求切分器保留逗号、分号和连接词连接的完整语义句，只按句末标点和换行切分，同时继续抽取整句中的全部指标。

**Architecture:** 保持现有 `RequirementClauseSplitter` 和数据结构不变，仅替换 `_parts()` 的边界规则。 `_metrics()` 继续作用于完整子句，因此多个指标仍能生成多个规范化指标、属性和约束。

**Tech Stack:** Python 3、标准库 `re`、pytest、现有 `rflp_lite` 应用层模型。

## Global Constraints

- 不引入 LLM 或新的 NLP 依赖。
- 不改动 `RequirementClause`、`NormalizedMetric`、`ClauseAnalysis` 的公开结构。
- 逗号、分号和 `并且/此外/以及/and/also/while/when` 不作为切分边界。
- `。`、`！`、`？`、`!`、`?` 和换行作为切分边界。
- ASCII 句号不拆分小数，例如 `0.032`；句末 ASCII 句号应正常切分。
- 保留原始子句内容（仅去除边界两侧空白），保持 ID 和顺序稳定。

---

### Task 1: Add regression tests for conservative boundaries

**Files:**
- Modify: `tests/application/test_requirement_clause_splitter.py`

**Interfaces:**
- Consumes: `RequirementClauseSplitter.split()` and `RequirementClause.normalized_metrics`.
- Produces: failing tests that define one complete clause for comma/semicolon-connected text and hard-boundary splitting for multiple sentences.

- [x] **Step 1: Replace the over-splitting expectations with complete-sentence assertions**

Use the existing mixed Chinese requirement text and assert the result has one clause, retains the behavior text, and contains all five metrics:

```python
clauses = RequirementClauseSplitter().split(text)

assert len(clauses) == 1
assert clauses[0].text == text.removesuffix("。")
assert "通信中断 30 秒后自动返航" in clauses[0].text
assert [metric.name for metric in clauses[0].normalized_metrics] == [
    "最大起飞重量", "任务载荷", "翼展", "巡航速度", "通信中断",
]
```

Keep the existing operator and unit assertions, adapting them to the metrics from the single clause.

- [x] **Step 2: Add hard-boundary and decimal regression tests**

Add a test with two sentences and one newline-separated sentence:

```python
def test_split_uses_sentence_boundaries_without_breaking_decimal_values() -> None:
    text = "系统应满足截面模量等于 0.032 m3，许用应力等于 205000000 Pa。\n通信中断 30 秒后自动返航！"

    clauses = RequirementClauseSplitter().split(text)

    assert [item.text for item in clauses] == [
        "系统应满足截面模量等于 0.032 m3，许用应力等于 205000000 Pa",
        "通信中断 30 秒后自动返航",
    ]
    assert [metric.value for metric in clauses[0].normalized_metrics] == [0.032, 205000000.0]
```

- [x] **Step 3: Run the focused tests to verify they fail**

Run:

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_requirement_clause_splitter.py -q
```

Expected: FAIL because the current implementation splits on commas and returns multiple clauses.

### Task 2: Implement hard-boundary splitting

**Files:**
- Modify: `src/rflp_lite/application/requirement_clause_splitter.py:29-31,160-168`

**Interfaces:**
- Consumes: one string from a `DocumentRegion.text` value.
- Produces: `_parts(text) -> tuple[str, ...]` containing only non-empty, trimmed sentence segments; all public splitter methods remain unchanged.

- [x] **Step 1: Replace the split and connector patterns**

Replace the current comma/semicolon/connector patterns with one hard-boundary pattern:

```python
_SENTENCE_BOUNDARY_PATTERN = re.compile(r"[。!！?？\n]+|\.(?=\s|$)")
```

The lookahead makes an ASCII period a boundary only before whitespace or end-of-text, while `0.032` remains intact.

- [x] **Step 2: Simplify `_parts()` to split only on hard boundaries**

```python
def _parts(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in _SENTENCE_BOUNDARY_PATTERN.split(text) if part.strip())
```

Remove `_SPLIT_PATTERN`, `_CONNECTOR_PATTERN`, and their unused connector loop. Do not alter metric extraction, classification, ID generation, or analysis behavior.

- [x] **Step 3: Run the focused tests to verify they pass**

Run:

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_requirement_clause_splitter.py -q
```

Expected: PASS for all splitter tests, including stable IDs and analyzed requirements.

### Task 3: Run targeted regression verification

**Files:**
- No additional files.

- [x] **Step 1: Run the related requirement and workflow tests**

Run:

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_requirement_semantics.py tests/application/test_requirement_details.py tests/application/test_requirements_workbench.py tests/application/test_intelligent_concept_workflow.py tests/e2e/test_concept_workflow_demo.py -q
```

Expected: PASS; no public data contract or workflow route changes are required.

- [x] **Step 2: Inspect the final diff and worktree**

Run:

```bash
git diff --check
git diff -- src/rflp_lite/application/requirement_clause_splitter.py tests/application/test_requirement_clause_splitter.py
git status --short
```

Expected: only the splitter and its focused test are changed by implementation; existing unrelated user changes remain untouched.

- [x] **Step 3: Commit the implementation**

```bash
git add src/rflp_lite/application/requirement_clause_splitter.py tests/application/test_requirement_clause_splitter.py
git commit -m "fix: preserve complete requirement sentences"
```
