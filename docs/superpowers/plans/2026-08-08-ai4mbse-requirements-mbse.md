# AI4MBSE Requirements and MBSE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax.

**Goal:** Deliver the M0-M2 customer-acceptance slice: document ingestion including PDF and scan OCR, reviewable structured requirements with traceability, and editable semantic Use Case, activity, and sequence models.

**Architecture:** The existing local workbench remains the approval, baseline, and audit boundary. New domain objects and application services own semantic engineering data; adapters parse files and invoke local OCR; Web, API, and CLI only orchestrate those services. RFLP remains compatible, while MBSE is stored as an independent semantic revision.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, HTMX, SQLite, pdfplumber, pypdfium2, Pillow, rapidocr, onnxruntime, existing OpenAI-compatible LLM adapter, pytest, Import Linter, jsonschema, and build.

## Global Constraints

- Customer functions 1.1 and 1.2 are hard requirements. Example output and unconnected mocks cannot form acceptance evidence.
- Engineering content stays local or intranet-only unless a project policy explicitly authorizes the selected remote model.
- Rules and LLMs produce candidates only. Every inferred item remains candidate until an individual human accepts it.
- Stable IDs and hashes use canonical_hash. Persisted objects use canonical_json.
- Document input limit is 50 MiB and 500 pages. Parser, OCR, and inference errors preserve valid partial output and record diagnostics.
- Workbench schema version becomes 2. Migration preserves all existing RFLP, scenario, baseline, and project fields.
- Document dependencies are installed only through the documents extra: pdfplumber>=0.11,<1; pypdfium2>=4.30,<5; Pillow>=11,<13; rapidocr>=3.6,<4; onnxruntime>=1.22,<2.
- Current CLI, Web, and API fields remain additive-compatible.
- Run full pytest, Import Linter, profile schema validation, and build after each completed task.

## File Ownership

| File | Responsibility |
|---|---|
| src/rflp_lite/domain/requirements.py | Document regions, structured requirements, trace links, diagnostics |
| src/rflp_lite/domain/mbse.py | Semantic MBSE value objects |
| src/rflp_lite/ports/document_intelligence.py | Parser and OCR interfaces |
| src/rflp_lite/adapters/document_intelligence.py | DOCX/PDF/OCR extraction |
| src/rflp_lite/application/workbench_schema.py | v1 to v2 state migration |
| src/rflp_lite/application/requirement_semantics.py | Engineering language extraction |
| src/rflp_lite/application/requirement_inference.py | Strict LLM implicit-constraint suggestions |
| src/rflp_lite/application/traceability.py | Trace matrix and coverage |
| src/rflp_lite/application/mbse_modeling.py | Use Case, activity, sequence generation and edits |
| src/rflp_lite/application/mbse_exchange.py | MBSE JSON and SysML subset exchange |
| src/rflp_lite/application/mbse_render.py | Semantic SVG views |
| src/rflp_lite/application/acceptance_metrics.py | Precision, recall, provenance metrics |

### Task 1: Create M0 versioned document and requirement contracts

**Files:**

- Create: src/rflp_lite/domain/requirements.py
- Create: src/rflp_lite/application/workbench_schema.py
- Modify: src/rflp_lite/domain/__init__.py
- Modify: src/rflp_lite/application/web_facade.py at requirements()
- Test: tests/domain/test_requirements.py
- Test: tests/application/test_workbench_schema.py

**Interfaces produced:**

- DocumentRegion, StructuredRequirement, TraceLink, Diagnostic.
- empty_document_state() returns all v2 collections.
- migrate_workbench_state(state) accepts a dictionary or None and returns an upgraded dictionary or None.

- [ ] **Step 1: Write failing tests**

~~~python
def test_structured_requirement_has_source_and_stable_id():
    region = DocumentRegion(
        id="region-1", artifact_id="artifact-1", page=2, kind="paragraph",
        locator="page-2/paragraph-3", text="系统支持导入 PDF。",
        bbox=(10.0, 20.0, 100.0, 40.0), confidence=1.0,
    )
    item = StructuredRequirement.from_fields(
        region=region, subject="系统", predicate="支持", statement="导入 PDF",
        source_type="explicit", entities=("PDF",), constraints=(),
    )
    assert item.source_region_id == "region-1"
    assert item.id.startswith("requirement-")
    assert item.status == "candidate"


def test_v1_workbench_upgrade_preserves_existing_data():
    legacy = {"artifact": {"id": "a"}, "spans": [], "claims": [],
              "rflp": {"elements": [], "relations": []}, "scenarios": [{"id": "s"}]}
    state = migrate_workbench_state(legacy)
    assert state["schema_version"] == 2
    assert state["rflp"] == legacy["rflp"]
    assert state["scenarios"] == legacy["scenarios"]
    assert state["structured_requirements"] == []
    assert state["mbse"] is None
~~~

- [ ] **Step 2: Confirm the tests fail before implementation**

Run: .venv/bin/python -m pytest tests/domain/test_requirements.py tests/application/test_workbench_schema.py -q

Expected: collection failure for the new modules.

- [ ] **Step 3: Implement value objects and migration**

~~~python
@dataclass(frozen=True, slots=True)
class DocumentRegion:
    id: str
    artifact_id: str
    page: int | None
    kind: str
    locator: str
    text: str
    bbox: tuple[float, float, float, float] = ()
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class StructuredRequirement:
    id: str
    source_region_id: str
    subject: str
    predicate: str
    statement: str
    source_type: str
    entities: tuple[str, ...]
    constraints: tuple[tuple[str, str], ...]
    verification_method: str
    confidence: float
    status: str = "candidate"

    @classmethod
    def from_fields(cls, *, region, subject, predicate, statement, source_type,
                    entities, constraints, verification_method="inspection", confidence=1.0):
        parts = (region.id, subject, predicate, statement, source_type, entities, constraints)
        return cls(f"requirement-{canonical_hash(parts)[:12]}", region.id, subject,
                   predicate, statement, source_type, entities, constraints,
                   verification_method, confidence)
~~~

~~~python
_V2_DEFAULTS = {
    "document_pages": [], "document_regions": [], "entities": [],
    "structured_requirements": [], "trace_links": [], "diagnostics": [], "mbse": None,
}


def migrate_workbench_state(state):
    if state is None:
        return None
    result = json.loads(canonical_json(state))
    if int(result.get("schema_version", 1)) > 2:
        raise ValueError("unsupported workbench schema version")
    for key, value in _V2_DEFAULTS.items():
        result.setdefault(key, value)
    result["schema_version"] = 2
    return result
~~~

WebFacade.requirements must call migration immediately after SQLiteRepository.load_workbench() and before any legacy default assignment.

- [ ] **Step 4: Run focused regression**

Run: .venv/bin/python -m pytest tests/domain/test_requirements.py tests/application/test_workbench_schema.py tests/application/test_requirements_workbench.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/rflp_lite/domain/requirements.py src/rflp_lite/domain/__init__.py src/rflp_lite/application/workbench_schema.py src/rflp_lite/application/web_facade.py tests/domain/test_requirements.py tests/application/test_workbench_schema.py
git commit -m "feat: add versioned document requirement contracts"
~~~

### Task 2: Parse DOCX, digital PDF, and scanned PDF locally

**Files:**

- Create: src/rflp_lite/ports/document_intelligence.py
- Create: src/rflp_lite/adapters/document_intelligence.py
- Modify: src/rflp_lite/adapters/readers.py
- Modify: pyproject.toml
- Modify: src/rflp_lite/application/web_facade.py
- Test: tests/adapters/test_document_intelligence.py
- Test: tests/adapters/test_readers.py
- Test: tests/application/test_web_facade.py

**Interfaces produced:**

- DocumentParserPort.parse(filename, content) -> ParsedDocument.
- OcrPort.recognize(image, page) -> text, bounding box, confidence tuples.
- parse_engineering_document(filename, content, ocr=None) -> ParsedDocument.
- Existing read_artifact remains compatible by mapping parsed regions to TextSpan values.

- [ ] **Step 1: Write failing parser tests**

~~~python
class FakeOcr:
    def recognize(self, image, *, page):
        return (("扫描件需求：系统支持导入 PDF", (1.0, 2.0, 80.0, 12.0), 0.96),)


def test_scan_page_uses_local_ocr_when_pdf_has_no_words(scan_pdf_bytes):
    parsed = parse_engineering_document("scan.pdf", scan_pdf_bytes, ocr=FakeOcr())
    assert parsed.regions[0].page == 1
    assert parsed.regions[0].kind == "ocr"
    assert parsed.regions[0].locator == "page-1/ocr-1"


def test_input_type_and_size_limits():
    with pytest.raises(AdapterFailure, match="unsupported artifact type"):
        parse_engineering_document("requirements.exe", b"x")
    with pytest.raises(AdapterFailure, match="50 MiB"):
        parse_engineering_document("requirements.pdf", b"x" * (50 * 1024 * 1024 + 1))
~~~

Use fpdf2 only in the development test dependencies to make a text PDF and image-only PDF at runtime. The fake OCR prevents model downloads in tests.

- [ ] **Step 2: Confirm failure**

Run: .venv/bin/python -m pytest tests/adapters/test_document_intelligence.py -q

Expected: collection failure for document_intelligence.

- [ ] **Step 3: Implement ports, dependencies, and parser behavior**

~~~python
@dataclass(frozen=True, slots=True)
class ParsedDocument:
    artifact: Artifact
    pages: tuple[DocumentPage, ...]
    regions: tuple[DocumentRegion, ...]
    diagnostics: tuple[Diagnostic, ...]


def parse_engineering_document(filename, content, *, ocr=None):
    suffix = Path(filename).suffix.lower()
    if len(content) > 50 * 1024 * 1024:
        raise AdapterFailure("artifact exceeds 50 MiB")
    if suffix == ".pdf":
        return _parse_pdf(filename, content, ocr or RapidOcrAdapter())
    if suffix == ".docx":
        return _parse_docx(filename, content)
    if suffix in {".txt", ".md", ".markdown", ".py", ".json", ".yaml", ".yml", ".toml"}:
        return _parse_utf8_text(filename, content)
    raise AdapterFailure("unsupported artifact type")
~~~

For PDF, open bytes with pdfplumber, call page.extract_words(), group words by rounded top, and create paragraph regions with page-relative boxes. If no words are returned, render using pypdfium2 at scale 2 and call OcrPort.recognize. Raise AdapterFailure with message document dependencies are missing; install with: pip install -e '.[documents]' when imports are unavailable. Reject page count above 500. Record requirements.document_parsed including page, region, and diagnostic counts.

- [ ] **Step 4: Run parser and regression tests**

Run: .venv/bin/python -m pytest tests/adapters/test_document_intelligence.py tests/adapters/test_readers.py tests/application/test_web_facade.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add pyproject.toml src/rflp_lite/ports/document_intelligence.py src/rflp_lite/adapters/document_intelligence.py src/rflp_lite/adapters/readers.py src/rflp_lite/application/web_facade.py tests/adapters/test_document_intelligence.py tests/adapters/test_readers.py tests/application/test_web_facade.py
git commit -m "feat: parse PDF documents with local OCR fallback"
~~~

### Task 3: Extract structured customer-domain requirements

**Files:**

- Create: src/rflp_lite/application/requirement_semantics.py
- Create: src/rflp_lite/resources/domain/ai4mbse-glossary.json
- Modify: src/rflp_lite/application/resources.py
- Modify: src/rflp_lite/application/requirements_workbench.py
- Test: tests/application/test_requirement_semantics.py
- Test: tests/application/test_requirements_workbench.py

**Interfaces produced:**

- extract_requirement_candidates(document) -> tuple of StructuredRequirement.
- requirement_payload(candidate, producer) -> JSON-safe dictionary.
- Bulk acceptance permits only explicit candidates produced by rule or user.

- [ ] **Step 1: Write failing acceptance-sentence tests**

~~~python
def test_customer_wording_extracts_entities_and_candidate_count(parsed_customer_document):
    candidates = extract_requirement_candidates(parsed_customer_document)
    by_statement = {item.statement: item for item in candidates}
    support = by_statement["导入作战纲要、技战术指标文档（Word/PDF）"]
    assert support.subject == "系统"
    assert support.predicate == "支持"
    assert set(support.entities) >= {"作战纲要", "技战术指标文档", "Word", "PDF"}
    layouts = next(item for item in candidates if "总体布局草图" in item.statement)
    assert ("candidate_count_min", "3") in layouts.constraints
    assert ("candidate_count_max", "5") in layouts.constraints


def test_inferred_requirement_is_not_bulk_accepted():
    state = analyze_artifact("requirements.txt", "系统应满足隐含工艺约束。".encode())
    state["structured_requirements"] = [{
        "id": "requirement-inferred", "source_type": "inferred",
        "producer": "llm", "status": "candidate",
    }]
    assert accept_traceable(state)["structured_requirements"][0]["status"] == "candidate"
~~~

- [ ] **Step 2: Confirm failure**

Run: .venv/bin/python -m pytest tests/application/test_requirement_semantics.py tests/application/test_requirements_workbench.py -q

Expected: collection failure for requirement_semantics.

- [ ] **Step 3: Implement glossary-driven extraction and acceptance gate**

Create this resource:

~~~json
{
  "version": 1,
  "roles": {"设计师": "engineering", "总体设计师": "engineering", "仿真工程师": "engineering", "审查员": "regulator"},
  "entities": ["作战纲要", "技战术指标文档", "总体布局", "气动", "结构", "标准件", "材料库", "三维模型", "二维工程图", "形位公差", "可制造性", "可装配性", "Word", "PDF"],
  "verbs": ["必须", "应当", "应", "不得", "支持", "具备", "能够", "自动", "生成", "调用", "推荐"],
  "units": ["mm", "m", "kg", "N", "Pa", "°", "%", "套"]
}
~~~

~~~python
_LEADING_VERB = re.compile(r"^(支持|具备|能够|自动|生成|调用|推荐)(?P<object>.+?)[。.!！?？]$")
_OBLIGATION = re.compile(r"^(?P<subject>.+?)(必须|应当|应|不得)(?P<object>.+?)[。.!！?？]$")
_COUNT_RANGE = re.compile(r"(?P<low>\d+)\s*(?:~|～|至|-|—)\s*(?P<high>\d+)\s*套")


def _constraints(text):
    match = _COUNT_RANGE.search(text)
    return () if match is None else (
        ("candidate_count_min", match.group("low")),
        ("candidate_count_max", match.group("high")),
    )


def _statement(text):
    matched = _OBLIGATION.match(text)
    if matched is not None:
        return matched.group("subject").strip(), "应", matched.group("object").strip()
    matched = _LEADING_VERB.match(text)
    if matched is not None:
        return "系统", text[:matched.start("object")].strip(), matched.group("object").strip()
    return "系统", "描述", text.rstrip("。.!！?？")
~~~

analyze_artifact must populate document_pages, document_regions, diagnostics, entities, structured_requirements, and backwards-compatible claims. Rule claims receive producer rule and candidate_type explicit. Change accept_traceable and confirm_requirements so inferred producer llm candidates remain candidate until a review action accepts them.

- [ ] **Step 4: Run semantic and regression tests**

Run: .venv/bin/python -m pytest tests/application/test_requirement_semantics.py tests/application/test_requirements_workbench.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/rflp_lite/application/requirement_semantics.py src/rflp_lite/resources/domain/ai4mbse-glossary.json src/rflp_lite/application/resources.py src/rflp_lite/application/requirements_workbench.py tests/application/test_requirement_semantics.py tests/application/test_requirements_workbench.py
git commit -m "feat: extract structured engineering requirements"
~~~

### Task 4: Add strict implicit-constraint LLM suggestions

**Files:**

- Create: src/rflp_lite/application/requirement_inference.py
- Modify: src/rflp_lite/application/requirements_workbench.py
- Modify: src/rflp_lite/application/web_facade.py
- Modify: src/rflp_lite/interface/web/routes.py
- Modify: src/rflp_lite/interface/web/api_v1.py
- Test: tests/application/test_requirement_inference.py
- Test: tests/interface/web/test_api_v1.py

**Interfaces produced:**

- suggest_implicit_requirements(regions, config, complete) returns StructuredRequirement candidates.
- complete receives config and a JSON prompt, then returns JSON text.
- Every inferred payload has source_type inferred, producer llm, status candidate, and bulk_approvable false.

- [ ] **Step 1: Write failing inference tests**

~~~python
def test_inferred_constraint_requires_known_source(region):
    def complete(_config, _prompt):
        return '[{"source_region_id":"region-1","statement":"关键尺寸应满足工艺能力","entities":["关键尺寸"],"constraints":[["manufacturing","required"]],"verification_method":"analysis","confidence":0.72}]'
    item = suggest_implicit_requirements((region,), {"model": "local"}, complete)[0]
    assert item.source_type == "inferred"
    assert item.status == "candidate"


def test_unknown_llm_source_is_rejected(region):
    def complete(_config, _prompt):
        return '[{"source_region_id":"missing","statement":"约束","entities":[],"constraints":[],"verification_method":"inspection","confidence":0.6}]'
    with pytest.raises(AdapterFailure, match="source_region_id"):
        suggest_implicit_requirements((region,), {"model": "local"}, complete)
~~~

- [ ] **Step 2: Confirm failure**

Run: .venv/bin/python -m pytest tests/application/test_requirement_inference.py -q

Expected: collection failure for requirement_inference.

- [ ] **Step 3: Implement strict schema validation**

~~~python
_REQUIRED = {"source_region_id", "statement", "entities", "constraints", "verification_method", "confidence"}


def suggest_implicit_requirements(regions, config, complete):
    source_ids = {region.id for region in regions}
    prompt = {
        "task": "只提出文本中隐含但未明确写出的工程约束；不得改写原文，不得批准结果。",
        "schema": sorted(_REQUIRED),
        "regions": [{"id": region.id, "text": region.text} for region in regions],
    }
    value = json.loads(complete(config, prompt))
    if not isinstance(value, list):
        raise AdapterFailure("LLM implicit requirement output must be an array")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != _REQUIRED:
            raise AdapterFailure("LLM implicit requirement schema is invalid")
        if item["source_region_id"] not in source_ids:
            raise AdapterFailure("LLM implicit requirement source_region_id is invalid")
        if not 0.0 <= float(item["confidence"]) <= 1.0:
            raise AdapterFailure("LLM implicit requirement confidence is invalid")
        region = next(value for value in regions if value.id == item["source_region_id"])
        result.append(StructuredRequirement.from_fields(
            region=region, subject="系统", predicate="应", statement=str(item["statement"]),
            source_type="inferred", entities=tuple(map(str, item["entities"])),
            constraints=tuple((str(key), str(value)) for key, value in item["constraints"]),
            verification_method=str(item["verification_method"]), confidence=float(item["confidence"]),
        ))
    return tuple(result)
~~~

Expose POST /w/{workspace}/requirements/implicit-constraints and POST /api/v1/workspaces/{workspace}/requirements/implicit-constraints. Return 422 with the existing error shape when no permitted profile is active. Display each result as AI 推断，需逐条确认.

- [ ] **Step 4: Run inference and API tests**

Run: .venv/bin/python -m pytest tests/application/test_requirement_inference.py tests/interface/web/test_api_v1.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/rflp_lite/application/requirement_inference.py src/rflp_lite/application/requirements_workbench.py src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/api_v1.py tests/application/test_requirement_inference.py tests/interface/web/test_api_v1.py
git commit -m "feat: add review-gated implicit constraint suggestions"
~~~

### Task 5: Persist traceability and metrics

**Files:**

- Create: src/rflp_lite/application/traceability.py
- Create: src/rflp_lite/application/acceptance_metrics.py
- Create: src/rflp_lite/resources/examples/customer-acceptance/requirements-gold.json
- Modify: src/rflp_lite/adapters/sqlite_repository.py
- Modify: src/rflp_lite/application/requirements_workbench.py
- Modify: src/rflp_lite/application/web_facade.py
- Test: tests/application/test_traceability.py
- Test: tests/application/test_acceptance_metrics.py
- Test: tests/adapters/test_sqlite_repository.py

**Interfaces produced:**

- build_trace_matrix(state) -> immutable tuple of rows.
- trace_coverage(matrix) -> source_complete, rflp_complete, mbse_complete, total.
- evaluate_requirement_extraction(actual, expected) -> precision, recall, F1, provenance_complete, unmatched records.

- [ ] **Step 1: Write failing trace and metric tests**

~~~python
def test_trace_matrix_keeps_source_and_rflp_links(reviewed_state):
    matrix = build_trace_matrix(reviewed_state)
    assert {row["predicate"] for row in matrix} >= {"derivedFrom", "satisfiedBy"}
    assert trace_coverage(matrix)["source_complete"] == 100


def test_extraction_metrics_use_statement_and_source_not_generated_id():
    expected = ({"id": "REQ-1", "statement": "导入 PDF", "source_region_id": "region-1"},)
    actual = ({"id": "requirement-1", "statement": "导入 PDF", "source_region_id": "region-1"},)
    report = evaluate_requirement_extraction(actual, expected)
    assert report["precision"] == 1.0
    assert report["recall"] == 1.0
    assert report["provenance_complete"] == 100
~~~

- [ ] **Step 2: Confirm failure**

Run: .venv/bin/python -m pytest tests/application/test_traceability.py tests/application/test_acceptance_metrics.py -q

Expected: collection failure for traceability.

- [ ] **Step 3: Implement trace rows and evidence persistence**

~~~python
def build_trace_matrix(state):
    rows = []
    for requirement in state.get("structured_requirements", ()):
        rows.append({"source_id": requirement["source_region_id"], "predicate": "derivedFrom",
                     "target_id": requirement["id"], "status": requirement["status"]})
        claim = next((item for item in state.get("claims", ())
                      if item.get("structured_requirement_id") == requirement["id"]), None)
        if claim is not None and state.get("rflp"):
            target = next((item for item in state["rflp"]["elements"]
                           if item["layer"] == "R" and ("claim_id", claim["id"]) in item["attributes"]), None)
            if target is not None:
                rows.append({"source_id": requirement["id"], "predicate": "satisfiedBy",
                             "target_id": target["id"], "status": claim["status"]})
    return tuple(sorted(rows, key=lambda row: (row["source_id"], row["predicate"], row["target_id"])))
~~~

Add document_evidence and trace_records tables with id and payload columns. Add save_document_evidence(values) and save_trace_records(values) using _save_many. In _save_requirements, recompute trace_links, save them in the current transaction, and audit requirements.traceability_updated with coverage. Metrics reject records that omit statement or source_region_id.

- [ ] **Step 4: Run trace and persistence regression**

Run: .venv/bin/python -m pytest tests/application/test_traceability.py tests/application/test_acceptance_metrics.py tests/adapters/test_sqlite_repository.py tests/application/test_requirements_workbench.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/rflp_lite/application/traceability.py src/rflp_lite/application/acceptance_metrics.py src/rflp_lite/resources/examples/customer-acceptance/requirements-gold.json src/rflp_lite/adapters/sqlite_repository.py src/rflp_lite/application/requirements_workbench.py src/rflp_lite/application/web_facade.py tests/application/test_traceability.py tests/application/test_acceptance_metrics.py tests/adapters/test_sqlite_repository.py
git commit -m "feat: persist requirement traceability evidence"
~~~

### Task 6: Generate semantic Use Case, activity, and sequence models

**Files:**

- Create: src/rflp_lite/domain/mbse.py
- Create: src/rflp_lite/application/mbse_modeling.py
- Modify: src/rflp_lite/application/requirements_workbench.py
- Test: tests/domain/test_mbse.py
- Test: tests/application/test_mbse_modeling.py

**Interfaces produced:**

- generate_mbse_revision(state) requires accepted structured requirements and returns a copied state with mbse.
- apply_mbse_edit(state, revision, operation) applies only rename or set-status with optimistic concurrency.
- Model collections are actors, use_cases, activities, lifelines, messages, and trace_links.

- [ ] **Step 1: Write failing semantic-model tests**

~~~python
def test_accepted_requirement_generates_all_three_model_views(reviewed_state):
    state = generate_mbse_revision(reviewed_state)
    model = state["mbse"]
    assert model["actors"]
    assert model["use_cases"]
    assert model["activities"]
    assert model["messages"]
    assert model["trace_links"]


def test_mbse_edit_requires_current_revision(reviewed_state):
    state = generate_mbse_revision(reviewed_state)
    operation = {"kind": "rename", "id": state["mbse"]["use_cases"][0]["id"], "name": "新名称"}
    with pytest.raises(ContractViolation, match="revision"):
        apply_mbse_edit(state, "wrong", operation)
~~~

- [ ] **Step 2: Confirm failure**

Run: .venv/bin/python -m pytest tests/domain/test_mbse.py tests/application/test_mbse_modeling.py -q

Expected: collection failure for rflp_lite.domain.mbse.

- [ ] **Step 3: Implement deterministic generator and edit gate**

~~~python
def generate_mbse_revision(state):
    accepted = [item for item in state.get("structured_requirements", ()) if item.get("status") == "accepted"]
    if not accepted:
        raise ContractViolation("请先接受至少一条结构化需求")
    actors, use_cases, activities, lifelines, messages, links = [], [], [], [], [], []
    for requirement in accepted:
        subject = str(requirement["subject"] or "使用者")
        actor_id = f"actor-{canonical_hash((subject,))[:12]}"
        use_case_id = f"usecase-{canonical_hash((requirement['id'],))[:12]}"
        activity_id = f"activity-{canonical_hash((requirement['id'], 'main'))[:12]}"
        message_id = f"message-{canonical_hash((requirement['id'], 'request'))[:12]}"
        actors.append({"id": actor_id, "name": subject, "status": "candidate", "requirement_ids": [requirement["id"]]})
        use_cases.append({"id": use_case_id, "name": requirement["statement"], "actor_ids": [actor_id], "requirement_ids": [requirement["id"]], "status": "candidate"})
        activities.append({"id": activity_id, "name": requirement["statement"], "kind": "action", "predecessor_ids": [], "requirement_ids": [requirement["id"]], "status": "candidate"})
        lifelines.extend(({"id": f"lifeline-{actor_id}", "name": subject}, {"id": "lifeline-system", "name": "系统"}))
        messages.append({"id": message_id, "name": requirement["statement"], "from_id": f"lifeline-{actor_id}", "to_id": "lifeline-system", "sequence": 1, "requirement_ids": [requirement["id"]], "status": "candidate"})
        links.append({"source_id": requirement["id"], "predicate": "refines", "target_id": use_case_id, "status": "candidate"})
    model = {"format": "ai4mbse/mbse", "version": 1, "actors": _unique(actors), "use_cases": _unique(use_cases),
             "activities": _unique(activities), "lifelines": _unique(lifelines), "messages": _unique(messages),
             "trace_links": sorted(links, key=lambda item: (item["source_id"], item["target_id"]))}
    model["revision"] = canonical_hash(model)
    result = json.loads(canonical_json(state))
    result["mbse"] = model
    return result
~~~

apply_mbse_edit accepts rename and set-status only, finds the ID in exactly one collection, recalculates revision, and invalidates baseline and project.

- [ ] **Step 4: Run semantic and RFLP tests**

Run: .venv/bin/python -m pytest tests/domain/test_mbse.py tests/application/test_mbse_modeling.py tests/application/test_requirements_workbench.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/rflp_lite/domain/mbse.py src/rflp_lite/application/mbse_modeling.py src/rflp_lite/application/requirements_workbench.py tests/domain/test_mbse.py tests/application/test_mbse_modeling.py
git commit -m "feat: generate semantic use case and scenario models"
~~~

### Task 7: Render and exchange semantic MBSE revisions

**Files:**

- Create: src/rflp_lite/application/mbse_render.py
- Create: src/rflp_lite/application/mbse_exchange.py
- Modify: src/rflp_lite/application/sysml_v2.py
- Modify: src/rflp_lite/application/traceability.py
- Test: tests/application/test_mbse_exchange.py
- Test: tests/application/test_mbse_render.py
- Test: tests/application/test_sysml_v2.py

**Interfaces produced:**

- render_use_case_svg(model), render_activity_svg(model), render_sequence_svg(model).
- export_mbse(model) and import_mbse(payload).
- export_mbse_sysml_v2_text(model) and import_mbse_sysml_v2_text(text).

- [ ] **Step 1: Write failing exchange and SVG tests**

~~~python
def test_mbse_exchange_round_trips_and_rejects_bad_hash(mbse_model):
    exported = export_mbse(mbse_model)
    assert import_mbse(exported) == mbse_model
    exported["model_hash"] = "0" * 64
    with pytest.raises(ContractViolation, match="model_hash"):
        import_mbse(exported)


def test_three_views_render_escaped_svg(mbse_model):
    renders = (render_use_case_svg(mbse_model), render_activity_svg(mbse_model), render_sequence_svg(mbse_model))
    assert all(value.startswith("<svg") for value in renders)
    assert "<script" not in "".join(renders)
~~~

- [ ] **Step 2: Confirm failure**

Run: .venv/bin/python -m pytest tests/application/test_mbse_exchange.py tests/application/test_mbse_render.py -q

Expected: collection failure for mbse_exchange.

- [ ] **Step 3: Implement JSON exchange, textual bridge, and rendering**

~~~python
def export_mbse(model):
    normalized = validate_mbse(model)
    return {"format": "ai4mbse/mbse", "version": 1, "model": normalized,
            "model_hash": canonical_hash(normalized)}


def import_mbse(payload):
    if not isinstance(payload, dict) or payload.get("format") != "ai4mbse/mbse" or payload.get("version") != 1:
        raise ContractViolation("unsupported MBSE exchange format or version")
    model = validate_mbse(payload.get("model"))
    if payload.get("model_hash") != canonical_hash(model):
        raise ContractViolation("MBSE model_hash does not match model")
    return model
~~~

validate_mbse requires unique IDs and valid requirement_ids. SVG labels pass through html.escape and rendering uses fixed SVG primitives. Extend sysml_v2.py with package AI4MBSE_MBSE and metadata comments beginning with ai4mbse-mbse-element; keep existing RFLP output byte-compatible.

- [ ] **Step 4: Run exchange and SysML tests**

Run: .venv/bin/python -m pytest tests/application/test_mbse_exchange.py tests/application/test_mbse_render.py tests/application/test_sysml_v2.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/rflp_lite/application/mbse_render.py src/rflp_lite/application/mbse_exchange.py src/rflp_lite/application/sysml_v2.py src/rflp_lite/application/traceability.py tests/application/test_mbse_exchange.py tests/application/test_mbse_render.py tests/application/test_sysml_v2.py
git commit -m "feat: render and exchange semantic MBSE revisions"
~~~

### Task 8: Expose traceability and MBSE through Web, API, and CLI

**Files:**

- Modify: src/rflp_lite/application/web_facade.py
- Modify: src/rflp_lite/interface/web/routes.py
- Modify: src/rflp_lite/interface/web/api_v1.py
- Modify: src/rflp_lite/interface/cli.py
- Modify: src/rflp_lite/interface/web/templates/base.html
- Create: src/rflp_lite/interface/web/templates/requirements-traceability.html
- Create: src/rflp_lite/interface/web/templates/requirements-mbse.html
- Modify: src/rflp_lite/interface/web/static/app.css
- Test: tests/interface/web/test_pages.py
- Test: tests/interface/web/test_api_v1.py
- Test: tests/interface/test_cli.py

**Interfaces produced:**

- Web routes for traceability, MBSE page, generate, edit, and three SVGs.
- API routes for traceability, generate, GET/PUT MBSE JSON, and GET/PUT MBSE SysML text.
- CLI commands workbench trace and workbench mbse with optional workspace-contained export.

- [ ] **Step 1: Write failing UI and API tests**

~~~python
def test_web_generates_and_downloads_semantic_mbse(client):
    client.post("/workspaces", data={"name": "demo"})
    client.post("/w/demo/requirements/analyze", data={"text": "设计师应当生成三维模型。"})
    client.post("/w/demo/requirements/accept-traceable")
    assert client.post("/w/demo/requirements/mbse/generate", follow_redirects=False).status_code == 303
    page = client.get("/w/demo/requirements/mbse")
    assert "Use Case" in page.text and "活动图" in page.text and "时序图" in page.text
    assert client.get("/w/demo/requirements/mbse/use-case.svg").status_code == 200
    assert client.get("/w/demo/requirements/traceability").status_code == 200


def test_api_rejects_stale_mbse_edit(client):
    _workbench(client)
    client.post("/api/v1/workspaces/demo/requirements/run-flow")
    model = client.post("/api/v1/workspaces/demo/requirements/mbse/generate").json()["mbse"]
    response = client.put("/api/v1/workspaces/demo/requirements/mbse", json={
        "revision": "old", "operation": {"kind": "rename", "id": model["use_cases"][0]["id"], "name": "更新"},
    })
    assert response.status_code == 422
~~~

- [ ] **Step 2: Confirm the route tests fail**

Run: .venv/bin/python -m pytest tests/interface/web/test_pages.py tests/interface/web/test_api_v1.py tests/interface/test_cli.py -q

Expected: MBSE route returns 404 and CLI parser rejects trace.

- [ ] **Step 3: Implement facade and transport endpoints**

~~~python
def generate_requirements_mbse(self, workspace_name):
    current = self.requirements(workspace_name)
    if current is None:
        raise ContractViolation("requirements workbench is empty")
    return self._save_requirements(workspace_name, generate_mbse_revision(current), "mbse.generated")


def update_requirements_mbse(self, workspace_name, revision, operation):
    current = self.requirements(workspace_name)
    if current is None:
        raise ContractViolation("requirements workbench is empty")
    return self._save_requirements(workspace_name, apply_mbse_edit(current, revision, operation), "mbse.edited")
~~~

The trace matrix page displays source locator, source text, structured requirement, RFLP link, MBSE link, producer, confidence, and status. The MBSE page uses revision, operation_kind, element_id, name, and status form fields. Add navigation items 追溯矩阵 and MBSE 用例模型.

workbench trace prints one canonical object with trace_links. workbench mbse creates MBSE when absent, persists it, prints canonical JSON, and permits export only inside the resolved workspace.

- [ ] **Step 4: Run UI, API, and CLI tests**

Run: .venv/bin/python -m pytest tests/interface/web/test_pages.py tests/interface/web/test_api_v1.py tests/interface/test_cli.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/api_v1.py src/rflp_lite/interface/cli.py src/rflp_lite/interface/web/templates/base.html src/rflp_lite/interface/web/templates/requirements-traceability.html src/rflp_lite/interface/web/templates/requirements-mbse.html src/rflp_lite/interface/web/static/app.css tests/interface/web/test_pages.py tests/interface/web/test_api_v1.py tests/interface/test_cli.py
git commit -m "feat: expose requirements traceability and MBSE workflow"
~~~

### Task 9: Add the customer-acceptance harness and verify the release

**Files:**

- Modify: src/rflp_lite/interface/cli.py
- Modify: README.md
- Modify: docs/DEVELOPMENT_STATUS.md
- Create: docs/verification/2026-08-08-requirements-mbse-acceptance.md
- Test: tests/e2e/test_requirements_mbse_acceptance.py
- Test: tests/interface/test_cli.py

**Interfaces produced:**

- rflp acceptance requirements --workspace path --gold path evaluates structured requirements and returns zero only when precision is at least 0.85, recall is at least 0.90, and provenance completeness is 100.

- [ ] **Step 1: Write the failing end-to-end acceptance test**

~~~python
def test_cli_requirement_acceptance_reports_thresholds(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    assert main(["init", str(workspace)]) == 0
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("系统支持导入 PDF。\n系统应当生成活动图。\n", encoding="utf-8")
    assert main(["workbench", "build", "--workspace", str(workspace), "--requirements", str(requirements)]) == 0
    gold = resource_path("examples/customer-acceptance/requirements-gold.json")
    status = main(["acceptance", "requirements", "--workspace", str(workspace), "--gold", str(gold)])
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert status == 0
    assert report["thresholds"] == {"precision": True, "recall": True, "provenance_complete": True}
    assert report["mbse_revision"]
~~~

- [ ] **Step 2: Confirm failure**

Run: .venv/bin/python -m pytest tests/e2e/test_requirements_mbse_acceptance.py -q

Expected: argparse invalid-choice error for acceptance.

- [ ] **Step 3: Implement command and verification report**

The handler loads SQLite state through migrate_workbench_state, rejects missing workbench with ContractViolation, reads a top-level JSON array from gold, calls evaluate_requirement_extraction, generates and persists MBSE when absent, calculates the three threshold booleans, prints canonical JSON with metrics, diagnostics, trace coverage, and MBSE revision, then returns one when a threshold fails.

Document these exact commands:

~~~bash
.venv/bin/pip install -e '.[dev,schema,evidence,opt,web,documents]'
.venv/bin/python -m pytest -q
.venv/bin/lint-imports
.venv/bin/check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json
.venv/bin/python -m build
.venv/bin/rflp acceptance requirements --workspace <workspace> --gold src/rflp_lite/resources/examples/customer-acceptance/requirements-gold.json
~~~

The verification document records input hashes, metrics, trace coverage, MBSE revision, dependency versions, and OCR/LLM diagnostics. It explicitly states that the public fixture tests the harness and customer acceptance uses a customer-approved, desensitized, versioned golden dataset.

- [ ] **Step 4: Run full release verification**

Run: .venv/bin/python -m pytest -q && .venv/bin/lint-imports && .venv/bin/check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json && .venv/bin/python -m build

Expected: all tests pass, all import contracts are kept, schema validation succeeds, and both sdist and wheel are built.

- [ ] **Step 5: Commit**

~~~bash
git add src/rflp_lite/interface/cli.py README.md docs/DEVELOPMENT_STATUS.md docs/verification/2026-08-08-requirements-mbse-acceptance.md tests/e2e/test_requirements_mbse_acceptance.py tests/interface/test_cli.py
git commit -m "feat: add requirements and MBSE acceptance harness"
~~~

## Plan Self-Review

### Specification coverage

- Function 1.1 is implemented by Tasks 1 through 5: contracts, DOCX/PDF/OCR parsing, domain-language extraction, review-gated implicit constraints, traceability, and metrics.
- Function 1.2 is implemented by Tasks 6 through 8: semantic Use Case/activity/sequence models, edits, rendering, exchange, and user interfaces.
- M0 contracts, migration, persistence, golden-data harness, documentation, and release verification are covered by Tasks 1, 5, and 9.
- Functions 2.1 through 3.3 remain in the approved overall design and require separate plans because they introduce independent repository, solver, CAD, drawing, and DFM/DFA toolchains.

### Consistency checks

- StructuredRequirement is created in Task 1, populated in Tasks 3 and 4, traced in Task 5, consumed in Task 6, and exposed in Tasks 8 and 9.
- migrate_workbench_state is introduced in Task 1 and used by all persistence consumers.
- generate_mbse_revision and apply_mbse_edit are introduced in Task 6, rendered/exported in Task 7, and exposed in Task 8.
- trace_links is initialized in Task 1, recomputed in Task 5, extended with MBSE links in Tasks 6 and 7, and rendered in Task 8.
