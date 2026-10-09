# Multi-Requirement Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve multiple requirement statements from natural-language and document inputs so one generation run produces per-requirement R→F→L→P→V&V traceability.

**Architecture:** Add a small pure statement splitter and make `ModelGenerationService._ensure_input` create one input Patch containing one Requirement per ordered statement, with document region IDs attached to the matching entities. Existing stage Runtime and CAS boundaries remain the only write path.

**Tech Stack:** Python 3.11+, regular expressions, typed ModelGraph, SQLite repository, pytest.

## Global Constraints

- One sentence or list item becomes one Requirement; conjunctions inside a sentence are not split automatically.
- Explicit natural-language input has empty `source_ids`; document-derived requirements carry their Source Region IDs.
- Existing requirements are reused when statement and source provenance match; no duplicate input Patch is created on retry.
- Empty input and existing active-model seed behavior remain unchanged.
- Every generated downstream object still uses existing Runtime validation and CAS Revision.

---

### Task 1: Add and test requirement statement splitting

**Files:**
- Create: `src/rflp_lite/application/requirement_intake.py`
- Test: `tests/application/test_requirement_intake.py`

**Interfaces:**
- Consumes: arbitrary text from user requirements or parsed document regions.
- Produces: `split_requirement_statements(text: str) -> tuple[str, ...]` with stable order, normalized whitespace, and no empty entries.

- [x] **Step 1: Write failing splitter tests**

```python
from rflp_lite.application.requirement_intake import split_requirement_statements


def test_splitter_preserves_order_and_removes_list_prefixes():
    assert split_requirement_statements(
        "1. 系统应自主配送；\n- 系统应支持人工接管。\n系统应在 12.5 h 内完成。"
    ) == (
        "系统应自主配送",
        "系统应支持人工接管",
        "系统应在 12.5 h 内完成",
    )


def test_splitter_handles_english_sentence_boundaries_without_splitting_versions():
    assert split_requirement_statements("The system shall stop safely. The system shall log v2.0.") == (
        "The system shall stop safely",
        "The system shall log v2.0",
    )


def test_splitter_ignores_blank_entries():
    assert split_requirement_statements("；\n  \n系统应可用！") == ("系统应可用",)
```

- [x] **Step 2: Run the splitter tests and verify they fail**

Run: `./.venv/bin/pytest tests/application/test_requirement_intake.py -q`

Expected: FAIL with `ModuleNotFoundError` because the splitter module does not exist.

- [x] **Step 3: Implement the pure splitter**

```python
_SEPARATOR = re.compile(r"(?:\r?\n+|[；;。！？!?]+|(?<=[.!?])\s+(?=[A-Z]))")
_LIST_PREFIX = re.compile(r"^\s*(?:(?:[-*•])\s*|\d+[.)、]\s*|[（(][一二三四五六七八九十\d]+[）)]\s*)")


def split_requirement_statements(text: str) -> tuple[str, ...]:
    values = []
    seen = set()
    for raw in _SEPARATOR.split(str(text or "")):
        value = _LIST_PREFIX.sub("", raw)
        value = " ".join(value.split()).strip()
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return tuple(values)
```

- [x] **Step 4: Run the splitter tests and verify they pass**

Run: `./.venv/bin/pytest tests/application/test_requirement_intake.py -q`

Expected: 3 passed.

- [x] **Step 5: Commit the splitter**

```bash
git add src/rflp_lite/application/requirement_intake.py tests/application/test_requirement_intake.py
git commit -m "feat: split multi-requirement input statements"
```

### Task 2: Create per-statement Requirements in the generation input path

**Files:**
- Modify: `src/rflp_lite/application/model_generation.py:840-880`
- Modify: `tests/application/test_document_generation.py`
- Modify: `tests/e2e/test_vertical_model_generation.py`

**Interfaces:**
- Consumes: `split_requirement_statements`, `repository.list_source_regions`, and existing `AddEntity`/`Patch` input path.
- Produces: one active Requirement per ordered statement, with region provenance and downstream per-requirement generation.

- [x] **Step 1: Write failing multi-input generation tests**

```python
def test_document_sentences_create_independent_requirements(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    services.projects.ingest_uploaded(
        "robot", "requirements.txt", "系统应自主配送。系统应支持人工接管。".encode()
    )

    services.generation("robot").generate("robot")
    graph = services.model("robot").graph("robot")
    requirements = [item for item in graph.entities if item.kind is EntityKind.REQUIREMENT]

    assert {item.meta.name for item in requirements} == {"系统应自主配送", "系统应支持人工接管"}
    assert all(item.meta.source_ids for item in requirements)


def test_multiple_natural_language_requirements_get_separate_function_paths(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应自主配送；系统应支持人工接管；系统应在断网后安全运行"
    )
    graph = services.model("robot").graph("robot")

    requirements = [item for item in graph.entities if item.kind is EntityKind.REQUIREMENT]
    functions = [item for item in graph.entities if item.kind is EntityKind.FUNCTION]
    assert len(requirements) == 3
    assert len(functions) == 3
    assert result.traceability.complete_count == 3
```

- [x] **Step 2: Run the new generation tests and verify the old single-Requirement behavior fails**

Run: `./.venv/bin/pytest tests/application/test_document_generation.py::test_document_sentences_create_independent_requirements tests/e2e/test_vertical_model_generation.py::test_multiple_natural_language_requirements_get_separate_function_paths -q`

Expected: FAIL because `_ensure_input` currently creates one Requirement containing all statements.

- [x] **Step 3: Build ordered candidates and append one input Patch**

Import `split_requirement_statements`. In `_ensure_input`, build ordered `(statement, source_ids)` candidates from explicit text or each source region. Merge repeated statements by statement while preserving the first-seen order and unioning source IDs. For every candidate, find an existing active Requirement whose statement and `source_ids` match; create only missing entities. Append all new `AddEntity` operations in one `user.requirement_input` Patch at the current revision. If no candidate text exists, preserve the active-model and existing error branches.

- [x] **Step 4: Run the focused generation and regression tests**

Run: `./.venv/bin/pytest tests/application/test_document_generation.py tests/e2e/test_vertical_model_generation.py tests/application/test_model_generation.py -q`

Expected: PASS; single-input tests retain one Requirement and multi-input tests produce independent Function and trace paths.

- [x] **Step 5: Commit the generation integration**

```bash
git add src/rflp_lite/application/model_generation.py tests/application/test_document_generation.py tests/e2e/test_vertical_model_generation.py
git commit -m "feat: preserve per-requirement generation traces"
```

### Task 3: Document and verify the multi-requirement product behavior

**Files:**
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `docs/superpowers/README.md`
- Modify: `docs/superpowers/plans/2026-09-13-multi-requirement-intake.md`

**Interfaces:**
- Consumes: the multi-statement intake and per-requirement trace behavior from Tasks 1–2.
- Produces: user-facing input semantics and a verified pushed branch.

- [x] **Step 1: Document statement boundaries and trace semantics**

State that newline/list/sentence-separated requirements remain separate in ModelGraph, document-derived items retain Source Region evidence, and the five stages report traceability per Requirement.

- [x] **Step 2: Mark the plan complete and scan for placeholders**

Change completed checkboxes to `[x]`. Run:

```bash
rg -n 'TODO|TBD|FIXME|Similar to Task|add appropriate' docs/superpowers/plans/2026-09-13-multi-requirement-intake.md | rg -v 'rg -n'
```

Expected: no output.

- [x] **Step 3: Run complete verification**

Run:

```bash
./.venv/bin/pytest -q
./.venv/bin/python scripts/verify_full.py
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/lint-imports
./.venv/bin/python scripts/architecture_metrics.py
git diff --check
```

Expected: every command exits 0.

- [x] **Step 4: Commit and push**

```bash
git add README.md docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md docs/superpowers/README.md docs/superpowers/plans/2026-09-13-multi-requirement-intake.md
git commit -m "docs: record multi-requirement trace flow"
git push origin codex/web-audit-2026-08-18
```
