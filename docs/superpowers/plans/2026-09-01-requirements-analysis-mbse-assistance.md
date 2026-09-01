# Requirements Analysis and MBSE Assistance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete customer requirements 1.1 and 1.2 as an auditable Word/PDF-to-structured-requirements-to-Use-Case vertical slice while preserving the current RFLP-Lite interaction flow.

**Architecture:** Extend the existing document-intelligence, block-analysis, workbench, traceability, scenario, and MBSE services through narrow domain objects and ports. Keep the current project pages, submit-and-analyze action, review cards, scenario cards, MBSE view switcher, CAS persistence, and block retry behavior; add richer data and editing behind those interfaces.

**Tech Stack:** Python 3.11+, dataclasses, SQLite, FastAPI, Jinja2, pdfplumber, pypdfium2, RapidOCR, strict JSON Schema, pytest, Hypothesis.

## Global Constraints

- Scope is limited to customer functions 1.1 and 1.2; do not add concept-design, CAE, CAD, PMI/GD&T, or DFM/DFA work.
- Do not introduce a wizard or reorder navigation. Preserve the existing project → requirements input → review/scenarios → MBSE design flow.
- Existing URLs, CLI commands, compatible API response fields, and workbench migration must remain valid.
- AI results remain candidates. Inferred constraints must always have `bulk_approvable=false` and require individual review.
- Every accepted requirement, attribute, constraint, scenario recommendation, and MBSE trace must retain valid source evidence.
- Historical requirements and combat scenarios must come from versioned JSON, CSV, or read-only SQLite datasets; do not hardcode customer scenarios in Python.
- One failed analysis block must not overwrite successful blocks. Preserve block-level retry, strict schema validation, CAS commits, and audit records.
- Base installation remains dependency-light. Optional vector retrieval may sit behind a port but is not part of this plan.
- Run tests with `RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config` so saved desktop LLM settings cannot leak into deterministic tests.

---

## File Structure

### New production files

- `src/rflp_lite/domain/requirement_details.py` — reviewed attribute and constraint contracts.
- `src/rflp_lite/domain/knowledge.py` — versioned historical-requirement and combat-scenario records and matches.
- `src/rflp_lite/ports/knowledge_datasets.py` — read-only dataset and retrieval protocols.
- `src/rflp_lite/adapters/knowledge_sources.py` — JSON/CSV/read-only SQLite dataset readers.
- `src/rflp_lite/application/requirement_details.py` — deterministic extraction, normalization, and compatibility projections.
- `src/rflp_lite/application/knowledge_library.py` — dataset row validation and record construction.
- `src/rflp_lite/application/knowledge_retrieval.py` — deterministic explainable ranking.
- `src/rflp_lite/application/model_impact.py` — stale-set calculation and targeted invalidation.
- `src/rflp_lite/application/use_case_modeling.py` — one semantic source for Use Case, activity, and sequence drafts.

### New test files

- `tests/domain/test_requirement_details.py`
- `tests/domain/test_knowledge.py`
- `tests/adapters/test_knowledge_sources.py`
- `tests/application/test_requirement_details.py`
- `tests/application/test_knowledge_library.py`
- `tests/application/test_knowledge_retrieval.py`
- `tests/application/test_model_impact.py`
- `tests/application/test_use_case_modeling.py`
- `tests/e2e/test_customer_requirements_11_12.py`

### Existing files with focused changes

- `src/rflp_lite/application/acceptance_metrics.py`
- `src/rflp_lite/application/acceptance_harness.py`
- `src/rflp_lite/application/workbench_schema.py`
- `src/rflp_lite/adapters/documents/docx_reader.py`
- `src/rflp_lite/adapters/document_intelligence.py`
- `src/rflp_lite/application/requirement_semantics.py`
- `src/rflp_lite/application/requirement_inference.py`
- `src/rflp_lite/application/intelligence/analysis_blocks.py`
- `src/rflp_lite/application/intelligence/block_schemas.py`
- `src/rflp_lite/application/intelligence/dto.py`
- `src/rflp_lite/application/intelligence/merge/registry.py`
- `src/rflp_lite/application/traceability.py`
- `src/rflp_lite/application/scenarios.py`
- `src/rflp_lite/application/mbse_modeling.py`
- `src/rflp_lite/application/mbse/legacy_builder.py`
- `src/rflp_lite/application/web_facade.py`
- `src/rflp_lite/bootstrap/container.py`
- `src/rflp_lite/interface/cli.py`
- `src/rflp_lite/interface/web/api_v1.py`
- `src/rflp_lite/interface/web/routes.py`
- `src/rflp_lite/interface/web/presenters.py`
- `src/rflp_lite/interface/web/templates/requirements-input.html`
- `src/rflp_lite/interface/web/templates/requirements-review.html`
- `src/rflp_lite/interface/web/templates/requirements-scenarios.html`
- `src/rflp_lite/interface/web/templates/mbse-diagrams.html`

---

### Task 1: Make Customer Acceptance Honest

**Files:**
- Modify: `src/rflp_lite/application/acceptance_metrics.py`
- Modify: `src/rflp_lite/application/acceptance_harness.py`
- Modify: `tests/application/test_acceptance_harness.py`
- Create: `src/rflp_lite/resources/examples/customer-acceptance/acceptance-v2.json`

**Interfaces:**
- Consumes: extracted requirement dictionaries and a versioned gold JSON object.
- Produces: `formal_acceptance_status(metrics: dict[str, object] | None) -> str` and reports containing `smoke_status` and `formal_status`.

- [ ] **Step 1: Write failing formal-status tests**

```python
def test_gold_mismatch_cannot_formally_pass(tmp_path):
    gold = tmp_path / "gold.json"
    gold.write_text('{"version":2,"requirements":[{"statement":"完全不同","source_text":"完全不同"}]}', encoding="utf-8")
    report = run_customer_acceptance("requirements.txt", "支持导入 PDF。".encode(), gold)
    assert report["smoke_status"] == "passed"
    assert report["formal_status"] == "failed"
    assert report["extraction_metrics"]["recall"] == 0.0


def test_without_gold_is_smoke_only():
    report = run_customer_acceptance("requirements.txt", "支持导入 PDF。".encode())
    assert report["smoke_status"] == "passed"
    assert report["formal_status"] == "not_evaluated"
```

- [ ] **Step 2: Run the tests and verify the old false-positive behavior**

Run:

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_acceptance_harness.py -v
```

Expected: both new tests fail because the current harness exposes only `status` and ignores extraction metrics when deciding pass/fail.

- [ ] **Step 3: Implement versioned formal thresholds**

```python
FORMAL_THRESHOLDS = {
    "requirement_precision": 0.90,
    "requirement_recall": 0.90,
    "detail_micro_f1": 0.85,
    "provenance_complete": 100,
}


def formal_acceptance_status(metrics: dict[str, object] | None) -> str:
    if metrics is None:
        return "not_evaluated"
    passed = (
        float(metrics.get("precision", 0.0)) >= FORMAL_THRESHOLDS["requirement_precision"]
        and float(metrics.get("recall", 0.0)) >= FORMAL_THRESHOLDS["requirement_recall"]
        and int(metrics.get("provenance_complete", 0)) == FORMAL_THRESHOLDS["provenance_complete"]
    )
    return "passed" if passed else "failed"
```

Update `run_customer_acceptance()` so `smoke_status` is based on executable checks, `formal_status` is based on gold metrics, and the legacy `status` field aliases `formal_status` when gold is present and `smoke_status` otherwise.

- [ ] **Step 4: Add a v2 gold contract with source text instead of unstable generated IDs**

```json
{
  "version": 2,
  "thresholds": {
    "requirement_precision": 0.9,
    "requirement_recall": 0.9,
    "detail_micro_f1": 0.85,
    "provenance_complete": 100
  },
  "requirements": [
    {
      "statement": "导入作战纲要、技战术指标文档（Word/PDF）",
      "source_text": "支持导入作战纲要、技战术指标文档（Word/PDF）"
    }
  ]
}
```

- [ ] **Step 5: Run focused tests and commit**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_acceptance_harness.py tests/application/test_acceptance_metrics.py -v
git add src/rflp_lite/application/acceptance_metrics.py src/rflp_lite/application/acceptance_harness.py tests/application/test_acceptance_harness.py src/rflp_lite/resources/examples/customer-acceptance/acceptance-v2.json
git commit -m "fix: enforce formal customer acceptance thresholds"
```

Expected: focused tests pass; a zero-score gold comparison has `formal_status=failed`.

---

### Task 2: Add Requirement Detail Contracts and Workbench v4 Migration

**Files:**
- Create: `src/rflp_lite/domain/requirement_details.py`
- Modify: `src/rflp_lite/domain/requirements.py`
- Modify: `src/rflp_lite/application/workbench_schema.py`
- Create: `tests/domain/test_requirement_details.py`
- Modify: `tests/application/test_workbench_schema.py`

**Interfaces:**
- Produces: `RequirementAttribute`, `RequirementConstraint`, and multi-region provenance on `StructuredRequirement`.
- Persists: `requirement_attributes`, `requirement_constraints`, `knowledge_datasets`, `retrieval_suggestions`, and `stale_entities` in schema v4.

- [ ] **Step 1: Write failing domain invariant tests**

```python
def test_attribute_and_constraint_require_sources():
    with pytest.raises(ValueError, match="source_region_ids"):
        RequirementAttribute.from_fields(
            requirement_id="req-1", name="速度", value="120", unit="km/h", source_region_ids=()
        )
    constraint = RequirementConstraint.from_fields(
        requirement_ids=("req-1",),
        constraint_type="performance",
        expression="速度 >= 120 km/h",
        explicitness="explicit",
        source_region_ids=("region-1",),
    )
    assert constraint.status == "candidate"
    assert constraint.source_region_ids == ("region-1",)
```

- [ ] **Step 2: Run the domain and migration tests to verify failure**

```bash
.venv/bin/python -m pytest tests/domain/test_requirement_details.py tests/application/test_workbench_schema.py -v
```

Expected: import failure for `requirement_details` and schema version mismatch.

- [ ] **Step 3: Implement frozen detail records**

```python
@dataclass(frozen=True, slots=True)
class RequirementAttribute:
    id: str
    requirement_id: str
    name: str
    value: str
    unit: str
    minimum: str
    maximum: str
    enum_values: tuple[str, ...]
    source_region_ids: tuple[str, ...]
    confidence: float
    status: str = "candidate"
    producer: str = "rule"

    @classmethod
    def from_fields(cls, *, requirement_id: str, name: str, value: str = "", unit: str = "",
                    minimum: str = "", maximum: str = "", enum_values: tuple[str, ...] = (),
                    source_region_ids: tuple[str, ...], confidence: float = 1.0,
                    status: str = "candidate", producer: str = "rule") -> "RequirementAttribute":
        if not source_region_ids:
            raise ValueError("source_region_ids is required")
        identity = (requirement_id, name, value, unit, minimum, maximum, enum_values, source_region_ids)
        return cls(f"attribute-{canonical_hash(identity)[:12]}", requirement_id, name.strip(), value.strip(),
                   unit.strip(), minimum.strip(), maximum.strip(), tuple(enum_values), tuple(source_region_ids),
                   max(0.0, min(1.0, confidence)), status, producer)
```

Add the constraint record in the same file:

```python
@dataclass(frozen=True, slots=True)
class RequirementConstraint:
    id: str
    requirement_ids: tuple[str, ...]
    constraint_type: str
    expression: str
    explicitness: str
    source_region_ids: tuple[str, ...]
    rationale: str
    verification_method: str
    confidence: float
    status: str = "candidate"
    producer: str = "rule"

    @classmethod
    def from_fields(cls, *, requirement_ids: tuple[str, ...], constraint_type: str,
                    expression: str, explicitness: str, source_region_ids: tuple[str, ...],
                    rationale: str = "", verification_method: str = "review",
                    confidence: float = 1.0, status: str = "candidate",
                    producer: str = "rule") -> "RequirementConstraint":
        if not requirement_ids:
            raise ValueError("requirement_ids is required")
        if not source_region_ids:
            raise ValueError("source_region_ids is required")
        if explicitness not in {"explicit", "inferred"}:
            raise ValueError("explicitness must be explicit or inferred")
        identity = (tuple(sorted(requirement_ids)), constraint_type, expression,
                    explicitness, tuple(source_region_ids))
        return cls(
            f"constraint-{canonical_hash(identity)[:12]}", tuple(sorted(requirement_ids)),
            constraint_type.strip(), expression.strip(), explicitness,
            tuple(source_region_ids), rationale.strip(), verification_method.strip() or "review",
            max(0.0, min(1.0, confidence)), status, producer,
        )
```

- [ ] **Step 4: Migrate workbench state to v4 without destroying old projections**

```python
WORKBENCH_SCHEMA_VERSION = 4

_V4_DEFAULTS = {
    "requirement_attributes": [],
    "requirement_constraints": [],
    "knowledge_datasets": {},
    "retrieval_suggestions": [],
    "stale_entities": [],
}

_WORKBENCH_DEFAULTS = {**_V2_DEFAULTS, **_V4_DEFAULTS, "discovery": _DISCOVERY_DEFAULTS}
```

Extend `StructuredRequirement` with `additional_source_region_ids: tuple[str, ...] = ()`; make its `source_region_ids` property return the stable de-duplicated union of the primary and additional IDs.

- [ ] **Step 5: Run tests and commit**

```bash
.venv/bin/python -m pytest tests/domain/test_requirements.py tests/domain/test_requirement_details.py tests/application/test_workbench_schema.py tests/adapters/test_sqlite_migrations.py -v
git add src/rflp_lite/domain/requirements.py src/rflp_lite/domain/requirement_details.py src/rflp_lite/application/workbench_schema.py tests/domain/test_requirement_details.py tests/application/test_workbench_schema.py
git commit -m "feat: add reviewed requirement detail contracts"
```

Expected: old workbench fixtures migrate to schema v4 with empty new collections; old requirement payloads remain readable.

---

### Task 3: Preserve DOCX/PDF Layout Evidence

**Files:**
- Modify: `src/rflp_lite/adapters/documents/docx_reader.py`
- Modify: `src/rflp_lite/adapters/document_intelligence.py`
- Modify: `src/rflp_lite/domain/requirements.py`
- Modify: `tests/adapters/test_document_intelligence.py`

**Interfaces:**
- Produces: page-aware `DocumentRegion` records with `heading_path`, `table_id`, `row_index`, `column_index`, and diagnostics.
- Preserves: `read_docx_text(content) -> str` as a compatibility projection.

- [ ] **Step 1: Add failing DOCX table and mixed-PDF tests**

```python
def test_docx_table_cells_keep_row_and_column(docx_with_table):
    parsed = parse_engineering_document("指标.docx", docx_with_table)
    cells = [item for item in parsed.regions if item.kind == "table_cell"]
    assert [(item.row_index, item.column_index) for item in cells] == [(1, 1), (1, 2)]
    assert all(item.table_id for item in cells)


def test_pdf_page_with_sparse_text_still_uses_ocr(fake_mixed_pdf, fake_ocr):
    parsed = LocalDocumentParser(ocr=fake_ocr).parse("mixed.pdf", fake_mixed_pdf)
    assert any(item.kind == "ocr" for item in parsed.regions)
    assert any(item.code == "pdf_page_hybrid_ocr" for item in parsed.diagnostics)
```

- [ ] **Step 2: Run the adapter tests and verify the fields are missing**

```bash
.venv/bin/python -m pytest tests/adapters/test_document_intelligence.py -v
```

Expected: new assertions fail because DOCX tables are flattened and pages with any extracted words skip OCR.

- [ ] **Step 3: Add structured DOCX blocks and retain the text compatibility function**

```python
@dataclass(frozen=True, slots=True)
class DocxBlock:
    kind: str
    locator: str
    text: str
    heading_path: tuple[str, ...] = ()
    table_id: str = ""
    row_index: int | None = None
    column_index: int | None = None


def read_docx_blocks(content: bytes) -> tuple[DocxBlock, ...]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise AdapterFailure("invalid DOCX document") from exc
    body = root.find(f"{_WORD_NAMESPACE}body")
    if body is None:
        return ()
    heading_path: list[str] = []
    blocks: list[DocxBlock] = []
    paragraph_index = 0
    table_index = 0
    for child in body:
        if child.tag == f"{_WORD_NAMESPACE}p":
            paragraph_index += 1
            text = "".join(node.text or "" for node in child.iter(f"{_WORD_NAMESPACE}t")).strip()
            if not text:
                continue
            style = child.find(f"{_WORD_NAMESPACE}pPr/{_WORD_NAMESPACE}pStyle")
            style_id = style.get(f"{_WORD_NAMESPACE}val", "") if style is not None else ""
            match = re.fullmatch(r"(?:Heading|标题)([1-9])", style_id, re.IGNORECASE)
            if match:
                level = int(match.group(1))
                heading_path[level - 1:] = [text]
            blocks.append(DocxBlock("heading" if match else "paragraph", f"paragraph-{paragraph_index}", text, tuple(heading_path)))
            continue
        if child.tag != f"{_WORD_NAMESPACE}tbl":
            continue
        table_index += 1
        table_id = f"table-{table_index}"
        for row_index, row in enumerate(child.findall(f"{_WORD_NAMESPACE}tr"), 1):
            for column_index, cell in enumerate(row.findall(f"{_WORD_NAMESPACE}tc"), 1):
                text = " ".join(
                    "".join(node.text or "" for node in paragraph.iter(f"{_WORD_NAMESPACE}t")).strip()
                    for paragraph in cell.iter(f"{_WORD_NAMESPACE}p")
                ).strip()
                if text:
                    blocks.append(DocxBlock("table_cell", f"{table_id}/r{row_index}/c{column_index}", text,
                                            tuple(heading_path), table_id, row_index, column_index))
    return tuple(blocks)


def read_docx_text(content: bytes) -> str:
    return "\n".join(block.text for block in read_docx_blocks(content))
```

Import `dataclass` and `re`, and delete the old duplicate traversal after `read_docx_text()` delegates to `read_docx_blocks()`.

- [ ] **Step 4: Add deterministic hybrid-OCR policy and diagnostics**

```python
def _needs_hybrid_ocr(words: list[dict[str, object]], width: float, height: float) -> bool:
    characters = sum(len(str(item.get("text", ""))) for item in words)
    page_area = max(width * height, 1.0)
    return characters < 24 or characters / page_area < 0.00008
```

Run OCR when there are no words or `_needs_hybrid_ocr()` is true; de-duplicate OCR and text regions by normalized text plus overlapping bounding boxes. Emit `Diagnostic(code="pdf_page_hybrid_ocr", scope="document", source_id=artifact.id)`.

- [ ] **Step 5: Run tests and commit**

```bash
.venv/bin/python -m pytest tests/adapters/test_document_intelligence.py tests/application/test_requirements_workbench.py -v
git add src/rflp_lite/adapters/documents/docx_reader.py src/rflp_lite/adapters/document_intelligence.py src/rflp_lite/domain/requirements.py tests/adapters/test_document_intelligence.py
git commit -m "feat: preserve engineering document layout evidence"
```

Expected: DOCX cell positions and hybrid PDF diagnostics are deterministic; existing document uploads still pass.

---

### Task 4: Extract Explicit Attributes and Constraints

**Files:**
- Create: `src/rflp_lite/application/requirement_details.py`
- Modify: `src/rflp_lite/application/requirement_semantics.py`
- Modify: `src/rflp_lite/application/intelligence/analysis_blocks.py`
- Modify: `src/rflp_lite/application/intelligence/block_schemas.py`
- Modify: `src/rflp_lite/application/intelligence/dto.py`
- Modify: `src/rflp_lite/application/intelligence/merge/registry.py`
- Create: `tests/application/test_requirement_details.py`
- Modify: `tests/contracts/test_analysis_block_contract.py`

**Interfaces:**
- Produces: `extract_explicit_details(requirements, regions) -> tuple[attributes, constraints]`.
- Adds analysis block: `requirement_details` with strict item kinds `attribute` and `constraint`.

- [ ] **Step 1: Write failing deterministic extraction tests**

```python
def test_extracts_range_unit_and_prohibition():
    requirement = {"id": "req-1", "statement": "系统巡航速度应不低于120 km/h，且不得超过160 km/h", "source_region_ids": ["region-1"]}
    attributes, constraints = extract_explicit_details((requirement,), {"region-1": requirement["statement"]})
    assert any(item.name == "巡航速度" and item.unit == "km/h" for item in attributes)
    assert {item.expression for item in constraints} == {
        "巡航速度 >= 120 km/h",
        "巡航速度 <= 160 km/h",
    }
    assert all(item.explicitness == "explicit" for item in constraints)
```

- [ ] **Step 2: Run the focused tests and verify no detail service exists**

```bash
.venv/bin/python -m pytest tests/application/test_requirement_details.py tests/contracts/test_analysis_block_contract.py -v
```

Expected: import failure and missing `requirement_details` block.

- [ ] **Step 3: Implement conservative rule extraction**

```python
_BOUND = re.compile(
    r"(?P<name>[\u4e00-\u9fffA-Za-z_]{2,24}).{0,6}?(?P<op>不低于|不少于|不超过|不得超过|>=|<=|≥|≤)\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>km/h|m/s|mm|m|kg|N|Pa|%|°)?"
)

_OPERATORS = {"不低于": ">=", "不少于": ">=", "≥": ">=", "不超过": "<=", "不得超过": "<=", "≤": "<=", ">=": ">=", "<=": "<="}


def extract_explicit_details(requirements, regions):
    attributes, constraints = [], []
    for requirement in requirements:
        source_ids = tuple(requirement.get("source_region_ids") or (requirement.get("source_region_id"),))
        text = " ".join(str(regions.get(source_id, "")) for source_id in source_ids)
        for match in _BOUND.finditer(text):
            name, value, unit = match.group("name"), match.group("value"), match.group("unit") or ""
            attributes.append(RequirementAttribute.from_fields(requirement_id=str(requirement["id"]), name=name,
                              value=value, unit=unit, source_region_ids=source_ids))
            constraints.append(RequirementConstraint.from_fields(requirement_ids=(str(requirement["id"]),),
                               constraint_type="performance", expression=f"{name} {_OPERATORS[match.group('op')]} {value} {unit}".strip(),
                               explicitness="explicit", source_region_ids=source_ids))
    return tuple(attributes), tuple(constraints)
```

- [ ] **Step 4: Add the strict AI detail block and merger**

Add `_REQUIREMENT_DETAIL` as a `oneOf` schema for `attribute` and `constraint`. Add `RequirementAttributeItem` and `RequirementConstraintItem` DTOs. Register `requirement_details` after `requirements` in `_BLOCK_SPECS`, and merge normalized payloads into `requirement_attributes` and `requirement_constraints` without changing accepted user fields.

```python
_BLOCK_SPECS = (
    ("system_scope", 4, 500, "system_scope：明确系统边界、任务目标、运行环境和未知前提。"),
    ("stakeholders", 12, 1200, "stakeholders：识别与系统目标、使用、运营、监管、供应和环境有关的利益相关方。"),
    ("concerns_needs", 18, 1400, "concerns_needs：为已识别利益相关方补充关注点和可追溯需要，不生成架构。"),
    ("requirements", 16, 1600, "requirements：把明确目标和需要转成短小、可验证、可追溯的需求。"),
    ("requirement_details", 32, 1800, "requirement_details：补充已识别需求的属性和显式约束；不得生成隐含约束。"),
    ("scenarios", 10, 1400, "scenarios：生成正常、边界、故障、恢复和误操作场景，不生成架构。"),
    ("architecture", 18, 1600, "architecture：基于已接受需求给出功能、逻辑组件、物理组件、接口和可追溯关系。"),
)
```

- [ ] **Step 5: Run tests and commit**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_requirement_details.py tests/contracts/test_analysis_block_contract.py tests/application/intelligence/test_enrichment_jobs.py -v
git add src/rflp_lite/application/requirement_details.py src/rflp_lite/application/requirement_semantics.py src/rflp_lite/application/intelligence/analysis_blocks.py src/rflp_lite/application/intelligence/block_schemas.py src/rflp_lite/application/intelligence/dto.py src/rflp_lite/application/intelligence/merge/registry.py tests/application/test_requirement_details.py tests/contracts/test_analysis_block_contract.py
git commit -m "feat: extract requirement attributes and explicit constraints"
```

Expected: detail block is schema-bounded, source-valid, retryable, and does not overwrite accepted details.

---

### Task 5: Make Implicit Constraints a First-Class Review Block

**Files:**
- Modify: `src/rflp_lite/application/requirement_inference.py`
- Modify: `src/rflp_lite/application/intelligence/analysis_blocks.py`
- Modify: `src/rflp_lite/application/intelligence/block_schemas.py`
- Modify: `src/rflp_lite/application/intelligence/dto.py`
- Modify: `src/rflp_lite/application/intelligence/merge/registry.py`
- Modify: `src/rflp_lite/application/review_queue.py`
- Modify: `tests/application/test_requirement_inference.py`
- Modify: `tests/application/intelligence/test_enrichment_jobs.py`

**Interfaces:**
- Adds analysis block: `implicit_constraints`.
- Produces only `RequirementConstraint(explicitness="inferred", status="candidate")` with valid requirement and region references.

- [ ] **Step 1: Write failing review-gate tests**

```python
def test_implicit_constraint_never_becomes_bulk_approvable(fake_model):
    result = suggest_implicit_requirements(_regions(), {}, model=fake_model)
    payload = inferred_requirement_payloads(_regions(), {}, model=fake_model)[0]
    assert result[0].status == "candidate"
    assert payload["bulk_approvable"] is False


def test_implicit_constraint_rejects_unknown_requirement_id():
    with pytest.raises(AdapterFailure, match="requirement_id"):
        merge_implicit_constraint_fixture(requirement_ids=["missing"], source_region_ids=["region-1"])
```

- [ ] **Step 2: Run tests and confirm the current path stores inferred requirements instead of detail objects**

```bash
.venv/bin/python -m pytest tests/application/test_requirement_inference.py tests/application/intelligence/test_enrichment_jobs.py -v
```

Expected: unknown requirement validation and `requirement_constraints` assertions fail.

- [ ] **Step 3: Define the implicit constraint schema and typed DTO**

```python
@dataclass(frozen=True, slots=True)
class ImplicitConstraintItem:
    id: str
    requirement_ids: tuple[str, ...]
    constraint_type: str
    expression: str
    rationale: str
    verification_method: str
    source_region_ids: tuple[str, ...]
    confidence: float
```

The schema requires every field above, at least one requirement ID, at least one source region ID, and `additionalProperties=false`.

- [ ] **Step 4: Merge only valid candidate constraints and add review-queue entries**

```python
def merge_implicit_constraints(state, items):
    known_requirements = {str(item["id"]) for item in state.get("structured_requirements", ())}
    known_regions = {str(item["id"]) for item in state.get("document_regions", ())}
    result = clone_state(state)
    for item in items:
        if not set(item.requirement_ids) <= known_requirements:
            raise ContractViolation("implicit constraint references unknown requirement_id")
        if not set(item.source_region_ids) <= known_regions:
            raise ContractViolation("implicit constraint references unknown source_region_id")
        payload = constraint_payload(item, explicitness="inferred", status="candidate", bulk_approvable=False)
        result["requirement_constraints"].append(payload)
        result["review_queue"].append({"group": "requirement_constraints", "item_id": payload["id"], "reason": "implicit_constraint"})
    return result
```

- [ ] **Step 5: Run tests and commit**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_requirement_inference.py tests/application/intelligence/test_enrichment_jobs.py tests/application/test_review_queue.py -v
git add src/rflp_lite/application/requirement_inference.py src/rflp_lite/application/intelligence/analysis_blocks.py src/rflp_lite/application/intelligence/block_schemas.py src/rflp_lite/application/intelligence/dto.py src/rflp_lite/application/intelligence/merge/registry.py src/rflp_lite/application/review_queue.py tests/application/test_requirement_inference.py tests/application/intelligence/test_enrichment_jobs.py
git commit -m "feat: review implicit constraints as isolated candidates"
```

Expected: inferred constraints are individually reviewable and cannot be batch accepted.

---

### Task 6: Add Versioned Requirement-History and Combat-Scenario Sources

**Files:**
- Create: `src/rflp_lite/domain/knowledge.py`
- Create: `src/rflp_lite/ports/knowledge_datasets.py`
- Create: `src/rflp_lite/adapters/knowledge_sources.py`
- Create: `src/rflp_lite/application/knowledge_library.py`
- Modify: `src/rflp_lite/application/dependencies.py`
- Modify: `src/rflp_lite/bootstrap/container.py`
- Create: `tests/domain/test_knowledge.py`
- Create: `tests/adapters/test_knowledge_sources.py`
- Create: `tests/application/test_knowledge_library.py`

**Interfaces:**
- Produces: `read_knowledge_rows(filename, content)`, `read_sqlite_knowledge_rows(path, table)`, `import_requirement_history(rows, dataset)`, and `import_combat_scenarios(rows, dataset)`.
- Adds ports: `RequirementHistoryRepositoryPort` and `CombatScenarioRepositoryPort` with read-only `records()` methods.

- [ ] **Step 1: Write failing JSON/CSV/SQLite contract tests**

```python
def test_requirement_history_json_is_versioned():
    rows = read_knowledge_rows("history.json", b'[{"id":"h-1","statement":"系统应记录状态"}]')
    records = import_requirement_history(rows, dataset_id="history", dataset_version="2026.1")
    assert records[0].dataset_id == "history"
    assert records[0].dataset_version == "2026.1"


def test_sqlite_reader_is_read_only(tmp_path):
    database = build_dataset_db(tmp_path)
    rows = read_sqlite_knowledge_rows(database, "combat_scenarios")
    assert rows[0]["id"] == "scenario-1"
    assert not database.with_suffix(".db-journal").exists()
```

- [ ] **Step 2: Run tests and verify missing ports and adapters**

```bash
.venv/bin/python -m pytest tests/domain/test_knowledge.py tests/adapters/test_knowledge_sources.py tests/application/test_knowledge_library.py -v
```

Expected: import failures for the new modules.

- [ ] **Step 3: Implement immutable records and matches**

```python
@dataclass(frozen=True, slots=True)
class RequirementHistoryRecord:
    id: str
    dataset_id: str
    dataset_version: str
    statement: str
    subject: str
    predicate: str
    attributes: tuple[tuple[str, str], ...]
    constraints: tuple[str, ...]
    trace_links: tuple[tuple[str, str, str], ...]
    applicability: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CombatScenarioRecord:
    id: str
    dataset_id: str
    dataset_version: str
    title: str
    mission: str
    actors: tuple[str, ...]
    preconditions: tuple[str, ...]
    steps: tuple[str, ...]
    alternate_steps: tuple[str, ...]
    failure_steps: tuple[str, ...]
    recovery_steps: tuple[str, ...]
    applicability: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RequirementMatch:
    record_id: str
    dataset_id: str
    dataset_version: str
    score: float
    matched_terms: tuple[str, ...]
    matched_numeric_features: tuple[tuple[float, str], ...]


@dataclass(frozen=True, slots=True)
class ScenarioMatch:
    record_id: str
    dataset_id: str
    dataset_version: str
    score: float
    matched_terms: tuple[str, ...]
    covered_requirement_ids: tuple[str, ...]
```

- [ ] **Step 4: Reuse the safe tabular-source rules and wire dependency factories**

`knowledge_sources.py` must use the same 50 MiB, 50,000-row, UTF-8, strict table-name, and SQLite `mode=ro` rules as `scheme_sources.py`. Add `knowledge_reader` and `sqlite_knowledge_reader` callables to `ApplicationDependencies` and the composition root.

```python
class RequirementHistoryRepositoryPort(Protocol):
    def dataset_id(self) -> str:
        pass

    def dataset_version(self) -> str:
        pass

    def records(self) -> tuple[RequirementHistoryRecord, ...]:
        pass
```

- [ ] **Step 5: Run tests and commit**

```bash
.venv/bin/python -m pytest tests/domain/test_knowledge.py tests/adapters/test_knowledge_sources.py tests/application/test_knowledge_library.py tests/architecture/test_dependency_boundaries.py -v
git add src/rflp_lite/domain/knowledge.py src/rflp_lite/ports/knowledge_datasets.py src/rflp_lite/adapters/knowledge_sources.py src/rflp_lite/application/knowledge_library.py src/rflp_lite/application/dependencies.py src/rflp_lite/bootstrap/container.py tests/domain/test_knowledge.py tests/adapters/test_knowledge_sources.py tests/application/test_knowledge_library.py
git commit -m "feat: add versioned requirements and scenario datasets"
```

Expected: all three source formats produce identical record contracts; no source file is modified.

---

### Task 7: Implement Explainable Dataset Retrieval

**Files:**
- Create: `src/rflp_lite/application/knowledge_retrieval.py`
- Modify: `src/rflp_lite/ports/knowledge_datasets.py`
- Create: `tests/application/test_knowledge_retrieval.py`

**Interfaces:**
- Produces: `retrieve_requirements(query, records, limit=5)` and `retrieve_scenarios(requirements, records, limit=5)`.
- Returns stable match objects containing score, matched terms, matched numeric features, and dataset identity.

- [ ] **Step 1: Write failing ranking and determinism tests**

```python
def test_requirement_retrieval_ranks_same_object_and_unit_first():
    matches = retrieve_requirements(
        {"statement": "系统巡航速度不低于120 km/h", "attributes": [("巡航速度", "120 km/h")]},
        history_records(),
        limit=2,
    )
    assert matches[0].record_id == "history-speed"
    assert "巡航速度" in matches[0].matched_terms


def test_scenario_ties_are_broken_by_record_id():
    first = retrieve_scenarios(accepted_requirements(), reversed(scenario_records()), limit=5)
    second = retrieve_scenarios(accepted_requirements(), scenario_records(), limit=5)
    assert first == second
```

- [ ] **Step 2: Run tests and verify retrieval is absent**

```bash
.venv/bin/python -m pytest tests/application/test_knowledge_retrieval.py -v
```

Expected: import failure for `knowledge_retrieval`.

- [ ] **Step 3: Implement standard-library token and numeric normalization**

```python
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]*|[\u4e00-\u9fff]{2,}")
_NUMBER_UNIT = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>km/h|m/s|mm|m|kg|N|Pa|%|°)?")


def normalized_features(text: str) -> tuple[frozenset[str], tuple[tuple[float, str], ...]]:
    terms = frozenset(match.group(0).casefold() for match in _TOKEN.finditer(text))
    numbers = tuple((float(match.group("value")), (match.group("unit") or "").casefold()) for match in _NUMBER_UNIT.finditer(text))
    return terms, numbers
```

- [ ] **Step 4: Implement weighted scoring and port protocols**

```python
def _score(query_terms, query_numbers, record_terms, record_numbers):
    term_score = len(query_terms & record_terms) / max(len(query_terms), 1)
    numeric_score = sum(1 for item in query_numbers if item in record_numbers) / max(len(query_numbers), 1)
    return round(0.75 * term_score + 0.25 * numeric_score, 8)
```

Sort by `(-score, record_id)`. Add these concrete protocols:

```python
class RequirementRetrieverPort(Protocol):
    def retrieve(self, query: Mapping[str, object], records: Iterable[RequirementHistoryRecord],
                 limit: int = 5) -> tuple[RequirementMatch, ...]:
        pass


class ScenarioRetrieverPort(Protocol):
    def retrieve(self, requirements: Iterable[Mapping[str, object]], records: Iterable[CombatScenarioRecord],
                 limit: int = 5) -> tuple[ScenarioMatch, ...]:
        pass
```

- [ ] **Step 5: Run tests and commit**

```bash
.venv/bin/python -m pytest tests/application/test_knowledge_retrieval.py -v
git add src/rflp_lite/application/knowledge_retrieval.py src/rflp_lite/ports/knowledge_datasets.py tests/application/test_knowledge_retrieval.py
git commit -m "feat: rank historical requirements and combat scenarios"
```

Expected: retrieval is deterministic, explainable, dependency-free, and bounded to the requested limit.

---

### Task 8: Integrate Retrieval into the Existing Analysis Job

**Files:**
- Modify: `src/rflp_lite/application/intelligence/analysis_coordinator.py`
- Modify: `src/rflp_lite/application/intelligence/enrichment_jobs.py`
- Modify: `src/rflp_lite/application/intelligence/analysis_blocks.py`
- Modify: `src/rflp_lite/application/use_cases/requirements_analysis.py`
- Modify: `src/rflp_lite/application/workbench_schema.py`
- Modify: `tests/application/intelligence/test_analysis_coordinator.py`
- Modify: `tests/application/intelligence/test_enrichment_jobs.py`

**Interfaces:**
- Consumes: configured dataset repositories and retriever ports.
- Produces: `retrieval_suggestions` plus local block statuses `requirement_history` and `scenario_retrieval`.

- [ ] **Step 1: Write failing partial-failure and provenance tests**

```python
def test_dataset_failure_does_not_erase_requirement_block(coordinator, accepted_requirement_state):
    coordinator.requirement_history = BrokenHistoryRepository()
    result = coordinator.run_local_retrieval(accepted_requirement_state)
    assert result["structured_requirements"] == accepted_requirement_state["structured_requirements"]
    assert result["auto_analysis"]["blocks"]["requirement_history"]["status"] == "failed"


def test_retrieval_suggestion_records_dataset_version(coordinator, accepted_requirement_state):
    result = coordinator.run_local_retrieval(accepted_requirement_state)
    suggestion = result["retrieval_suggestions"][0]
    assert suggestion["dataset_id"] == "history"
    assert suggestion["dataset_version"] == "2026.1"
```

- [ ] **Step 2: Run coordinator tests and verify local blocks are missing**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/intelligence/test_analysis_coordinator.py tests/application/intelligence/test_enrichment_jobs.py -v
```

Expected: missing `run_local_retrieval` and block status assertions fail.

- [ ] **Step 3: Add local block result records without routing them through the LLM**

```python
LOCAL_ANALYSIS_BLOCKS = ("requirement_history", "scenario_retrieval")


def retrieval_suggestion(match, kind: str) -> dict[str, object]:
    return {
        "id": f"suggestion-{canonical_hash((kind, match.dataset_id, match.dataset_version, match.record_id))[:12]}",
        "kind": kind,
        "record_id": match.record_id,
        "dataset_id": match.dataset_id,
        "dataset_version": match.dataset_version,
        "score": match.score,
        "matched_terms": list(match.matched_terms),
        "status": "candidate",
    }
```

- [ ] **Step 4: Execute retrieval after accepted requirement merge and persist through CAS**

The coordinator loads datasets from project analysis configuration, runs history retrieval first and scenario retrieval second, writes only `retrieval_suggestions` and block diagnostics, and commits with the same `snapshot_content_revision` and input hash checks used by LLM blocks.

```python
if self._accepted_requirements(state):
    state = self._run_requirement_history(state)
    state = self._run_scenario_retrieval(state)
```

- [ ] **Step 5: Run tests and commit**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/intelligence/test_analysis_coordinator.py tests/application/intelligence/test_enrichment_jobs.py tests/application/test_requirements_analysis_service.py -v
git add src/rflp_lite/application/intelligence/analysis_coordinator.py src/rflp_lite/application/intelligence/enrichment_jobs.py src/rflp_lite/application/intelligence/analysis_blocks.py src/rflp_lite/application/use_cases/requirements_analysis.py src/rflp_lite/application/workbench_schema.py tests/application/intelligence/test_analysis_coordinator.py tests/application/intelligence/test_enrichment_jobs.py
git commit -m "feat: integrate dataset retrieval with analysis jobs"
```

Expected: dataset failures are isolated; suggestions carry dataset provenance and never auto-accept.

---

### Task 9: Expand the Traceability Matrix

**Files:**
- Modify: `src/rflp_lite/application/traceability.py`
- Modify: `src/rflp_lite/application/mbse_matrix.py`
- Modify: `src/rflp_lite/application/mbse_views.py`
- Modify: `tests/application/test_traceability.py`
- Modify: `tests/application/test_mbse_views.py`

**Interfaces:**
- Consumes: accepted requirements, attributes, constraints, retrieval suggestions, Use Cases, activities, and messages.
- Produces: stable rows for `derivedFrom`, `representedBy`, `constrainedBy`, `similarTo`, and `refines` plus coverage and orphan diagnostics.

- [ ] **Step 1: Write failing multi-layer trace tests**

```python
def test_trace_matrix_covers_details_and_mbse_elements():
    matrix = build_trace_matrix(state_with_requirement_details_and_mbse())
    triples = {(item["source_id"], item["predicate"], item["target_id"]) for item in matrix}
    assert ("req-1", "representedBy", "attribute-1") in triples
    assert ("req-1", "constrainedBy", "constraint-1") in triples
    assert ("history-1", "similarTo", "req-1") in triples
    assert ("req-1", "refines", "use-case-1") in triples
    assert trace_coverage(matrix, total=1)["source_complete"] == 100
```

- [ ] **Step 2: Run trace tests and verify missing predicates**

```bash
.venv/bin/python -m pytest tests/application/test_traceability.py tests/application/test_mbse_views.py -v
```

Expected: detail and historical-requirement rows are absent.

- [ ] **Step 3: Build rows only from accepted, source-valid objects**

```python
for attribute in state.get("requirement_attributes", ()):
    if attribute.get("status") == "accepted":
        rows.append(_row(str(attribute["requirement_id"]), "representedBy", str(attribute["id"]), "accepted", str(attribute.get("producer", "rule"))))

for constraint in state.get("requirement_constraints", ()):
    if constraint.get("status") == "accepted":
        for requirement_id in constraint.get("requirement_ids", ()):
            rows.append(_row(str(requirement_id), "constrainedBy", str(constraint["id"]), "accepted", str(constraint.get("producer", "rule"))))
```

Add accepted retrieval suggestions as `historical_record_id similarTo requirement_id`. Do not emit formal rows for candidate or stale details.

- [ ] **Step 4: Extend matrix predicates and orphan diagnostics**

Add `constrainedBy` and `similarTo` to the matrix allowlist. Return `trace_diagnostics` from `refresh_traceability()` for accepted requirements with no valid source, Use Cases with no requirement, and messages with no requirement.

```python
result["trace_diagnostics"] = trace_diagnostics(result, matrix)
```

- [ ] **Step 5: Run tests and commit**

```bash
.venv/bin/python -m pytest tests/application/test_traceability.py tests/application/test_mbse_views.py tests/application/test_mbse_render.py -v
git add src/rflp_lite/application/traceability.py src/rflp_lite/application/mbse_matrix.py src/rflp_lite/application/mbse_views.py tests/application/test_traceability.py tests/application/test_mbse_views.py
git commit -m "feat: trace requirements through details and MBSE views"
```

Expected: the trace matrix renders all five required relation families and identifies orphans.

---

### Task 10: Generate Scenario-Based Use Case, Activity, and Sequence Drafts

**Files:**
- Create: `src/rflp_lite/application/use_case_modeling.py`
- Modify: `src/rflp_lite/application/scenarios.py`
- Modify: `src/rflp_lite/application/mbse_modeling.py`
- Modify: `src/rflp_lite/application/mbse/legacy_builder.py`
- Modify: `src/rflp_lite/application/sequence_modeling.py`
- Create: `tests/application/test_use_case_modeling.py`
- Modify: `tests/application/test_scenarios.py`
- Modify: `tests/application/test_sequence_modeling.py`

**Interfaces:**
- Produces: `build_use_case_drafts(state) -> tuple[dict[str, object], ...]` and compiles activity/sequence semantics from the same steps.
- Removes: normal-project dependence on `_SCENARIO_MATRIX_ROWS`; keeps legacy compatibility only for explicitly selected legacy packs.

- [ ] **Step 1: Write failing unified-model tests**

```python
def test_use_case_activity_and_sequence_share_steps():
    drafts = build_use_case_drafts(state_with_recommended_scenario())
    draft = drafts[0]
    assert draft["requirement_ids"] == ["req-1"]
    assert draft["main_flow"][0]["message"] == "提交任务"
    model = generate_mbse_revision({**state_with_recommended_scenario(), "use_case_drafts": list(drafts)})["mbse"]
    assert model["activities"][0]["steps"][0] == "提交任务"
    assert model["messages"][0]["name"] == "提交任务"


def test_unrelated_hardcoded_medical_scenarios_are_not_generated():
    state = generate_scenario_matrix(generic_radar_requirement_state())
    assert all("医疗" not in item["title"] for item in state["scenarios"])
```

- [ ] **Step 2: Run tests and verify current divergence and hardcoded rows**

```bash
.venv/bin/python -m pytest tests/application/test_use_case_modeling.py tests/application/test_scenarios.py tests/application/test_sequence_modeling.py -v
```

Expected: missing `build_use_case_drafts`; the hardcoded medical scenario fixture exposes the current risk.

- [ ] **Step 3: Build one canonical flow-step structure**

```python
def flow_step(*, order: int, sender: str, receiver: str, message: str,
              guard: str = "", branch: str = "main", requirement_ids=()) -> dict[str, object]:
    return {
        "id": f"flow-step-{canonical_hash((order, sender, receiver, message, guard, branch, tuple(requirement_ids)))[:12]}",
        "order": order,
        "sender": sender,
        "receiver": receiver,
        "message": message,
        "guard": guard,
        "branch": branch,
        "requirement_ids": sorted(set(str(value) for value in requirement_ids)),
    }
```

`build_use_case_drafts()` uses accepted scenarios and accepted requirements only. It maps scenario `interaction_steps` first and plain `steps` conservatively second.

- [ ] **Step 4: Compile both diagrams from canonical flow and isolate legacy matrices**

`generate_mbse_revision()` stores `use_case_drafts`, then `legacy_builder` and `sequence_modeling` consume canonical steps. Move `_SCENARIO_MATRIX_ROWS` behind an explicit legacy-pack function; normal analysis uses retrieved and LLM-proposed scenarios only.

```python
if state.get("analysis_config", {}).get("domain_pack_id") == "urban-medical-aam-v1":
    return generate_legacy_scenario_matrix(state)
return preserve_manual_and_analyzed_scenarios(state)
```

- [ ] **Step 5: Run tests and commit**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_use_case_modeling.py tests/application/test_scenarios.py tests/application/test_mbse_modeling.py tests/application/test_sequence_modeling.py -v
git add src/rflp_lite/application/use_case_modeling.py src/rflp_lite/application/scenarios.py src/rflp_lite/application/mbse_modeling.py src/rflp_lite/application/mbse/legacy_builder.py src/rflp_lite/application/sequence_modeling.py tests/application/test_use_case_modeling.py tests/application/test_scenarios.py tests/application/test_sequence_modeling.py
git commit -m "feat: compile MBSE drafts from reviewed scenarios"
```

Expected: Use Case, activity, and sequence outputs share one flow model; unrelated fixed scenarios are not injected.

---

### Task 11: Add Structured MBSE Editing and Targeted Invalidation

**Files:**
- Create: `src/rflp_lite/application/model_impact.py`
- Modify: `src/rflp_lite/application/mbse_modeling.py`
- Modify: `src/rflp_lite/application/scenarios.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/interface/web/api_v1.py`
- Create: `tests/application/test_model_impact.py`
- Modify: `tests/application/test_mbse_modeling.py`
- Modify: `tests/interface/web/test_api_v1.py`

**Interfaces:**
- Adds edit operation: `update-fields` with allowlists by MBSE collection.
- Produces: `impact_for_change(state, changed_ids) -> ImpactSet` and `mark_impacted_stale(state, impact) -> state`.

- [ ] **Step 1: Write failing rich-edit and impact tests**

```python
def test_update_message_fields_preserves_unrelated_use_case():
    state = mbse_state_with_two_use_cases()
    revision = state["mbse"]["revision"]
    changed = apply_mbse_edit(state, revision, {
        "kind": "update-fields",
        "id": "message-1",
        "fields": {"name": "发送任务", "guard": "链路可用", "requirement_ids": ["req-1"]},
    })
    assert changed["mbse"]["messages"][0]["guard"] == "链路可用"
    assert changed["mbse"]["use_cases"][1]["status"] == "accepted"


def test_requirement_change_marks_only_linked_models_stale():
    impact = impact_for_change(mbse_state_with_two_use_cases(), {"req-1"})
    assert "use-case-1" in impact.entity_ids
    assert "use-case-2" not in impact.entity_ids
```

- [ ] **Step 2: Run tests and verify only rename/set-status are supported**

```bash
.venv/bin/python -m pytest tests/application/test_model_impact.py tests/application/test_mbse_modeling.py tests/interface/web/test_api_v1.py -v
```

Expected: `update-fields` is rejected and impact service import fails.

- [ ] **Step 3: Implement graph-based impact calculation**

```python
@dataclass(frozen=True, slots=True)
class ImpactSet:
    source_ids: tuple[str, ...]
    entity_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]


def impact_for_change(state: dict[str, object], changed_ids: set[str]) -> ImpactSet:
    relations = tuple(state.get("trace_links", ())) + tuple((state.get("mbse") or {}).get("trace_links", ()))
    frontier, impacted = set(changed_ids), set(changed_ids)
    while frontier:
        current = frontier.pop()
        targets = {str(item["target_id"]) for item in relations if str(item.get("source_id")) == current}
        frontier |= targets - impacted
        impacted |= targets
    relation_ids = tuple(sorted(str(item.get("id", "")) for item in relations if str(item.get("source_id")) in impacted or str(item.get("target_id")) in impacted))
    return ImpactSet(tuple(sorted(changed_ids)), tuple(sorted(impacted - changed_ids)), relation_ids)
```

- [ ] **Step 4: Implement collection-specific field allowlists and stale marking**

```python
_EDITABLE_FIELDS = {
    "actors": {"name"},
    "use_cases": {"name", "preconditions", "postconditions", "requirement_ids"},
    "activities": {"name", "steps", "requirement_ids"},
    "messages": {"name", "sort", "guard", "sender_lifeline_id", "receiver_lifeline_id", "requirement_ids"},
}
```

Reject unknown fields and references. Mark only impacted entities and relations `stale`; clear baseline/project for any semantic edit, but do not delete unrelated current MBSE entities.

- [ ] **Step 5: Run tests and commit**

```bash
.venv/bin/python -m pytest tests/application/test_model_impact.py tests/application/test_mbse_modeling.py tests/application/test_scenarios.py tests/interface/web/test_api_v1.py -v
git add src/rflp_lite/application/model_impact.py src/rflp_lite/application/mbse_modeling.py src/rflp_lite/application/scenarios.py src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/api_v1.py tests/application/test_model_impact.py tests/application/test_mbse_modeling.py tests/interface/web/test_api_v1.py
git commit -m "feat: edit MBSE semantics with targeted invalidation"
```

Expected: structured edits are revision-checked, reference-safe, and do not invalidate unrelated model branches.

---

### Task 12: Preserve the Current Web Flow and Close End-to-End Acceptance

**Files:**
- Modify: `src/rflp_lite/interface/web/presenters.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/api_v1.py`
- Modify: `src/rflp_lite/interface/web/templates/requirements-input.html`
- Modify: `src/rflp_lite/interface/web/templates/requirements-review.html`
- Modify: `src/rflp_lite/interface/web/templates/requirements-scenarios.html`
- Modify: `src/rflp_lite/interface/web/templates/mbse-diagrams.html`
- Modify: `src/rflp_lite/interface/cli.py`
- Modify: `src/rflp_lite/application/acceptance_harness.py`
- Modify: `src/rflp_lite/application/acceptance_metrics.py`
- Create: `tests/e2e/test_customer_requirements_11_12.py`
- Modify: `tests/interface/web/test_pages.py`
- Modify: `tests/interface/web/test_api_v1.py`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`

**Interfaces:**
- Preserves: existing page URLs, POST/303 behavior, scenario cards, MBSE view switching, CLI `rflp acceptance`, and compatible JSON fields.
- Adds: detail review forms, dataset provenance, local retrieval block statuses, structured MBSE edit fields, and formal acceptance output.

- [ ] **Step 1: Write failing UI compatibility and E2E tests**

```python
def test_customer_11_12_flow_keeps_existing_routes(client, customer_docx, fake_model, datasets):
    create_workspace(client, "customer")
    response = upload_and_analyze(client, "customer", "requirements.docx", customer_docx)
    assert response.status_code == 303
    review = client.get("/w/customer/requirements/review")
    assert "属性与约束" in review.text
    assert "历史相似需求" in review.text
    scenarios = client.get("/w/customer/requirements/scenarios")
    assert "模板来源" in scenarios.text
    mbse = client.get("/w/customer/requirements/mbse")
    assert "发送方" in mbse.text
    assert "接收方" in mbse.text


def test_formal_cli_fails_when_gold_thresholds_are_not_met(tmp_path, capsys):
    exit_code = main(["acceptance", "--requirements", str(BAD_INPUT), "--gold", str(GOLD_V2)])
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert report["formal_status"] == "failed"
```

- [ ] **Step 2: Run E2E and page tests to capture missing presentation fields**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/e2e/test_customer_requirements_11_12.py tests/interface/web/test_pages.py tests/interface/web/test_api_v1.py -v
```

Expected: new E2E tests fail while all pre-existing route assertions continue to pass.

- [ ] **Step 3: Extend existing cards and forms without adding navigation**

In `requirements-review.html`, render accepted/candidate attributes and constraints inside each requirement card and reuse existing accept/reject/edit actions. In `requirements-scenarios.html`, render dataset title/version, recommendation reason, and structured interaction steps. In `mbse-diagrams.html`, add structured fields to the selected model element form.

```html
<label class="field">发送方<input name="sender" value="{{ selected.sender or '' }}"></label>
<label class="field">接收方<input name="receiver" value="{{ selected.receiver or '' }}"></label>
<label class="field">消息<input name="message" value="{{ selected.name or '' }}" required></label>
<label class="field">条件<input name="guard" value="{{ selected.guard or '' }}"></label>
```

Keep existing page links and POST endpoints. Translate form input into the existing `/requirements/mbse/edit` `update-fields` operation.

- [ ] **Step 4: Add presenter/API fields and complete formal acceptance metrics**

Expose `requirement_attributes`, `requirement_constraints`, `retrieval_suggestions`, `trace_diagnostics`, and structured Use Case data as additive response fields. Extend formal metrics with entity, attribute, and constraint micro-F1 and scenario top-5 recall.

```python
formal_passed = (
    requirement_metrics["precision"] >= 0.90
    and requirement_metrics["recall"] >= 0.90
    and detail_metrics["micro_f1"] >= 0.85
    and provenance_complete == 100
    and scenario_metrics["top_5_hit_rate"] >= 1.0
)
```

Return CLI exit code `0` only for `formal_status=passed` when `--gold` is supplied; preserve smoke exit behavior without `--gold`.

- [ ] **Step 5: Run focused, full, architecture, and schema gates**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/e2e/test_customer_requirements_11_12.py tests/interface/web/test_pages.py tests/interface/web/test_api_v1.py tests/application/test_acceptance_harness.py -v
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest -q
.venv/bin/lint-imports
.venv/bin/python -m compileall -q src tests
.venv/bin/check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json
```

Expected: all 1.1/1.2 E2E assertions pass; the full suite passes; all import contracts are kept; compilation and schema checks succeed.

- [ ] **Step 6: Update capability documentation and commit**

Document exact supported formats, dataset inputs, formal thresholds, AI review gates, and interaction compatibility. Do not mark 2.x or 3.x complete.

```bash
git add src/rflp_lite/interface/web/presenters.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/api_v1.py src/rflp_lite/interface/web/templates/requirements-input.html src/rflp_lite/interface/web/templates/requirements-review.html src/rflp_lite/interface/web/templates/requirements-scenarios.html src/rflp_lite/interface/web/templates/mbse-diagrams.html src/rflp_lite/interface/cli.py src/rflp_lite/application/acceptance_harness.py src/rflp_lite/application/acceptance_metrics.py tests/e2e/test_customer_requirements_11_12.py tests/interface/web/test_pages.py tests/interface/web/test_api_v1.py README.md docs/DEVELOPMENT_STATUS.md
git commit -m "feat: complete requirements and MBSE assistance acceptance"
```

Expected: the final commit closes the customer 1.1/1.2 vertical slice without changing the main user journey.

---

## Final Verification Checklist

- [ ] `rflp acceptance` distinguishes smoke and formal status.
- [ ] A zero precision/recall/F1 gold comparison cannot pass formally.
- [ ] DOCX paragraphs, headings, and table cells retain source evidence.
- [ ] Digital, scanned, and hybrid PDFs retain page, coordinates, and diagnostics.
- [ ] Explicit requirements, entities, attributes, and constraints are separate reviewable objects.
- [ ] Inferred constraints always require individual review.
- [ ] Requirement history and combat scenarios load from versioned JSON, CSV, or read-only SQLite.
- [ ] Retrieval suggestions are deterministic, explainable, and source-versioned.
- [ ] Trace matrices include source, detail, history, Use Case, activity, and sequence relations.
- [ ] Use Case, activity, and sequence models compile from one canonical flow.
- [ ] Structured human edits use CAS revisions and targeted stale propagation.
- [ ] Existing page routes, POST/303 interactions, API fields, and CLI commands remain compatible.
- [ ] Full tests pass with an isolated `RFLP_CONFIG_DIR`.
- [ ] Root reference PPT/PDF/DOCX files remain untracked and are not included in implementation commits.
