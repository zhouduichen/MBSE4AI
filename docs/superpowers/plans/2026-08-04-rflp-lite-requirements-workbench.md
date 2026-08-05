# RFLP-Lite Requirements Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one local Web page that turns user-provided requirements and engineering text into reviewed Stakeholder/Concern/Need/Claim data and a deterministic dynamic RFLP SVG.

**Architecture:** Reuse the existing FastAPI/Jinja/SQLite stack and generic domain models. Store the mutable workbench as one canonical JSON document in the existing SQLite database, keep extraction and planning deterministic, and make the optional OpenAI-compatible call a manual fallback that can only add pending candidates.

**Tech Stack:** Python 3.11+ standard library, existing FastAPI/Jinja/SQLite, pytest.

**Status:** Completed and verified on 2026-08-05. See `docs/DEVELOPMENT_STATUS.md`.

## Global Constraints

- Add no runtime dependency.
- LLM calls are manual and optional; no API key is persisted or rendered.
- Unreviewed inferred stakeholders cannot enter the generated model.
- RFLP SVG output is byte-stable for identical accepted input.
- Reuse `Artifact`, `TextSpan`, `Claim`, `ModelElement`, `Relation`, `SQLiteRepository`, and current Web templates.
- Keep one workbench page and ordinary HTML POST/redirect flows.

---

### Task 1: Deterministic intake, review state, planning, and SVG

**Files:**
- Modify: `src/rflp_lite/adapters/readers.py`
- Modify: `src/rflp_lite/adapters/sqlite_repository.py`
- Modify: `src/rflp_lite/application/synthesize.py`
- Create: `src/rflp_lite/application/requirements_workbench.py`
- Create: `tests/application/test_requirements_workbench.py`

**Interfaces:**
- Consumes: uploaded filename/bytes and the existing canonical hash/JSON helpers.
- Produces: `analyze_artifact(filename: str, content: bytes) -> dict[str, object]`, `review_item(state, group, item_id, status, value) -> dict`, `accept_traceable(state) -> dict`, `generate_model(state) -> dict`, `add_llm_suggestions(state) -> dict`, and `render_rflp_svg(elements, relations) -> str`.

- [x] **Step 1: Write the failing core test**

```python
def test_reviewed_stakeholders_generate_stable_dynamic_rflp(tmp_path):
    source = """管理员必须恢复历史版本。\n审计人员必须查看恢复记录。\n普通用户只能查看自己的内容。""".encode()
    state = analyze_artifact("requirements.txt", source)
    assert {item["name"] for item in state["stakeholders"]} >= {"管理员", "审计人员", "普通用户"}
    state = accept_traceable(state)
    state = generate_model(state)
    assert {item["layer"] for item in state["rflp"]["elements"]} == {"R", "F", "L", "P"}
    assert state["coverage"] == {"R-F": 100, "F-L": 100, "L-P": 100}
    assert state["svg"] == generate_model(state)["svg"]
```

- [x] **Step 2: Run the core test and verify failure**

Run: `pytest tests/application/test_requirements_workbench.py -q`

Expected: FAIL because `requirements_workbench` does not exist.

- [x] **Step 3: Add generic artifact parsing and bilingual claim extraction**

Implement in `readers.py`:

```python
def read_artifact(filename: str, content: bytes) -> tuple[Artifact, tuple[TextSpan, ...]]:
    if len(content) > 5 * 1024 * 1024:
        raise AdapterFailure("artifact exceeds 5 MiB")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".txt", ".md", ".markdown", ".docx", ".py", ".json", ".yaml", ".yml", ".toml"}:
        raise AdapterFailure("unsupported artifact type")
    text = _read_docx(content) if suffix == ".docx" else content.decode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    artifact = Artifact(f"artifact-{digest[:12]}", suffix.lstrip("."), Path(filename).name, digest)
    paragraphs = tuple(line.strip(" -*\t") for line in text.splitlines() if line.strip(" -*\t"))
    spans = tuple(TextSpan(f"span-{canonical_hash((artifact.id, i, line))[:12]}", artifact.id, f"paragraph-{i}", line) for i, line in enumerate(paragraphs, 1))
    return artifact, spans
```

For `.py`, call `ast.parse(text)` and add class/function/test names as spans before returning. Extend `_OBLIGATION` to accept `MUST NOT|MUST|SHALL|SHOULD|必须|应当|不得|禁止|需要|可以` while preserving existing English behavior.

- [x] **Step 4: Make existing RFLP synthesis dynamic**

Replace the fixed three-item synthesis with content-hash IDs and one R/F/L chain per claim. Reuse physical nodes named `Web/API`, `SQLite Repository`, and `Python Service`; create only the physical nodes actually referenced. Every R has one `satisfiedBy`, every F one `allocatedTo`, and every L one `realizedBy`.

- [x] **Step 5: Implement one canonical workbench document**

Add a `workbench` SQLite table and these concrete methods:

```python
def save_workbench(self, value: dict[str, object]) -> None:
    self._connection.execute("INSERT OR REPLACE INTO workbench(id, payload) VALUES ('current', ?)", (canonical_json(value),))

def load_workbench(self) -> dict[str, object] | None:
    row = self._connection.execute("SELECT payload FROM workbench WHERE id = 'current'").fetchone()
    return json.loads(row[0]) if row else None
```

In `requirements_workbench.py`, use a longest-first role dictionary, source-span IDs, candidate statuses, exact aliases only, and `ponytail:` comments on heuristic grouping. `accept_traceable` accepts explicit stakeholders and their linked concerns/needs/claims but leaves inferred candidates pending. `generate_model` rejects missing accepted claims or broken stakeholder/need provenance.

- [x] **Step 6: Add the optional LLM call**

Read `RFLP_LLM_BASE_URL`, `RFLP_LLM_MODEL`, and `RFLP_LLM_API_KEY`; if any is absent, raise `AdapterFailure("LLM 未配置")`. Use `urllib.request` with a 20-second timeout, parse `choices[0].message.content` as JSON, allow only stakeholder/concern/need/source_span_id fields, and append every result with `candidate_type=inferred`, `producer=llm`, `status=candidate`.

- [x] **Step 7: Run the core tests**

Run: `pytest tests/application/test_requirements_workbench.py tests/application/test_ingest_compile.py tests/application/test_demo_workflow.py -q`

Expected: PASS.

- [x] **Step 8: Commit the core**

```bash
git add src/rflp_lite/adapters/readers.py src/rflp_lite/adapters/sqlite_repository.py src/rflp_lite/application/synthesize.py src/rflp_lite/application/requirements_workbench.py tests/application/test_requirements_workbench.py
git commit -m "feat: add reviewed requirements workbench core"
```

### Task 2: Single-page Web workflow

**Files:**
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/templates/base.html`
- Create: `src/rflp_lite/interface/web/templates/requirements-workbench.html`
- Modify: `src/rflp_lite/interface/web/static/app.css`
- Modify: `tests/interface/web/test_pages.py`

**Interfaces:**
- Consumes: Task 1 workbench functions and `SQLiteRepository.save_workbench/load_workbench`.
- Produces: GET `/w/{workspace}/requirements`; POST endpoints `/analyze`, `/review`, `/accept-traceable`, `/generate`, `/ai`; downloads `/requirements/model.json` and `/requirements/model.svg`.

- [x] **Step 1: Write the failing Web test**

```python
def test_requirements_page_runs_reviewed_rflp_flow(client):
    client.post("/workspaces", data={"name": "demo"})
    analyzed = client.post("/w/demo/requirements/analyze", data={"text": "管理员必须恢复历史版本。\n审计人员必须查看恢复记录。"}, follow_redirects=False)
    assert analyzed.status_code == 303
    client.post("/w/demo/requirements/accept-traceable")
    generated = client.post("/w/demo/requirements/generate", follow_redirects=False)
    assert generated.status_code == 303
    page = client.get("/w/demo/requirements")
    assert "利益相关方" in page.text
    assert "RFLP 规划图" in page.text
    assert "<svg" in page.text
    assert client.get("/w/demo/requirements/model.json").status_code == 200
    assert client.get("/w/demo/requirements/model.svg").status_code == 200
```

- [x] **Step 2: Run the Web test and verify failure**

Run: `pytest tests/interface/web/test_pages.py::test_requirements_page_runs_reviewed_rflp_flow -q`

Expected: FAIL with 404.

- [x] **Step 3: Add facade operations and routes**

`WebFacade` opens `{workspace}/.rflp/model.db`, delegates to the Task 1 functions inside a transaction, saves the returned workbench, and closes the repository. Routes validate the uploaded size/type through the core, use POST/303 redirects, return actionable 422 errors, and send JSON/SVG with explicit media types.

- [x] **Step 4: Build the one-page template**

The page contains: textarea/file form; rule and AI buttons; stakeholder, concern, need, and claim review rows with editable value plus accept/reject buttons; one “接受全部可追溯候选” action; provenance checklist; Generate button; four-layer SVG; coverage cards; JSON/SVG download links. Use existing colors, cards, buttons, labels, focus states, and semantic form labels.

- [x] **Step 5: Add the navigation entry and minimum CSS**

Add “需求建模” under Model whenever a workspace exists. Add only workbench grid, review row, input textarea, source-chain, and SVG overflow styles; reuse every existing component class that fits.

- [x] **Step 6: Run Web and core tests**

Run: `pytest tests/interface/web/test_pages.py tests/application/test_requirements_workbench.py -q`

Expected: PASS.

- [x] **Step 7: Commit the Web workflow**

```bash
git add src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/templates/base.html src/rflp_lite/interface/web/templates/requirements-workbench.html src/rflp_lite/interface/web/static/app.css tests/interface/web/test_pages.py
git commit -m "feat: expose local requirements modeling workflow"
```

### Task 3: Regression and local verification

**Files:**
- Modify only if verification finds a defect in files from Tasks 1-2.

**Interfaces:**
- Consumes: completed workbench and current full test/build checks.
- Produces: a locally verified page and clean regression result.

- [x] **Step 1: Run all tests and import contracts**

Run: `pytest -q && lint-imports`

Expected: all tests and all import contracts pass.

- [x] **Step 2: Build the package**

Run: `python -m build`

Expected: wheel and source distribution build successfully.

- [x] **Step 3: Start and smoke-test the local server**

Run: `rflp serve --host 127.0.0.1 --port 8000`

Verify: create/select a workspace, open “需求建模”, paste the VersionedContentService sample, accept traceable candidates, generate RFLP, inspect stakeholder source chain, and download JSON/SVG.

- [x] **Step 4: Commit verification fixes if any**

```bash
git add src/rflp_lite tests
git commit -m "fix: complete requirements workbench verification"
```
