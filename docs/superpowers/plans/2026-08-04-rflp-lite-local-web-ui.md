# RFLP-Lite Local Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a polished, local-only Web UI that runs the existing RFLP-Lite vertical slice and exposes every real Artifact-to-Evidence result while presenting undeveloped capabilities as honest placeholders.

**Architecture:** Add a FastAPI/Jinja2/HTMX interface adapter over focused workspace and run-catalog application services. Keep SQLite and normalized run JSON as sources of truth, keep `run_demo` as the only pipeline orchestrator, and make all Web mutation flow through application services rather than templates, routes, or direct SQL.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, Jinja2, python-multipart, HTMX 2.0.10 vendored from the official project, local CSS, SQLite, pytest, FastAPI TestClient.

## Global Constraints

- Default deployment is macOS localhost, single user, listening on `127.0.0.1`; no Docker, GPU, external database, login, permissions, or cloud dependency.
- Keep the Python runtime floor at `>=3.11` and keep Web packages in a separate `web` optional dependency group.
- Do not add Node.js, a front-end build chain, a CDN reference, WebSocket, SSE, or a background job queue.
- The Web UI may create and select workspaces only beneath repository-local `workspaces/`; reject absolute names, separators, `..`, and path traversal.
- Keep arbitrary external workspace paths available through the CLI only.
- Web routes and templates must never execute SQL or modify Baseline records directly.
- Current pipeline runs are synchronous and call `run_demo`; HTMX supplies disabled/loading feedback but must not display fabricated percentage progress.
- Every number, state, hash, trace, and download shown as real must come from SQLite or normalized run JSON.
- A failed Web run must preserve the existing Baseline hash and return a stable, user-readable error without a raw traceback.
- The visual system is the approved dark engineering cockpit: ink-green navigation, mint success/action, muted blue information, amber planned status, red failure only, and light reading panels for dense text and JSON.
- All undeveloped capabilities remain disabled catalog entries with purpose, dependencies, expected inputs/outputs, and enablement criteria.
- Preserve CLI behavior, deterministic hashes, the existing 19 tests, and all three Import Linter contracts.
- The supplied upstream repository is `https://github.com/zhouduichen/MBSE4AI`; do not add a remote or push without a separate explicit action.

---

## File Structure

Create or modify these focused units:

- `src/rflp_lite/application/workspaces.py`: workspace initialization, name validation, root containment, and managed-workspace listing.
- `src/rflp_lite/application/run_catalog.py`: safe discovery/loading of normalized run bundles and registered downloads.
- `src/rflp_lite/application/web_facade.py`: Web-facing use cases combining workspace, catalog, audit, and `run_demo` without HTTP dependencies.
- `src/rflp_lite/application/demo.py`: export Artifact, TextSpan, and Decision JSON in addition to existing outputs.
- `src/rflp_lite/interface/web/app.py`: FastAPI application factory, exception mapping, static/template configuration.
- `src/rflp_lite/interface/web/routes.py`: HTTP input parsing, route definitions, redirects, HTMX responses.
- `src/rflp_lite/interface/web/presenters.py`: deterministic ViewModel creation and display-only formatting.
- `src/rflp_lite/interface/web/templates/*.html`: base shell, page templates, and HTMX fragments.
- `src/rflp_lite/interface/web/static/app.css`: complete cockpit visual system and responsive/accessibility states.
- `src/rflp_lite/interface/web/static/vendor/htmx.min.js`: pinned official HTMX 2.0.10 distribution.
- `src/rflp_lite/interface/web/static/vendor/HTMX-LICENSE.txt`: upstream Zero-Clause BSD license.
- `tests/application/test_workspaces.py`: safe workspace lifecycle tests.
- `tests/application/test_run_catalog.py`: normalized output catalog and download confinement tests.
- `tests/application/test_web_facade.py`: dashboard, run, failure, and Baseline protection tests.
- `tests/interface/web/test_app.py`: application factory, page, error, static asset, and security tests.
- `tests/interface/web/test_pages.py`: end-to-end TestClient coverage for navigation and real content.
- `tests/interface/test_cli.py`: optional Web command dispatch and missing-extra behavior.
- `README.md`: install, start, use, validate, and current capability boundary.
- `docs/verification/local-web-ui-2026-08-04.md`: exact verification environment, commands, results, and screenshots checked.

---

### Task 1: Safe Managed Workspaces

**Files:**
- Create: `src/rflp_lite/application/workspaces.py`
- Modify: `src/rflp_lite/interface/cli.py`
- Create: `tests/application/test_workspaces.py`
- Modify: `tests/e2e/test_cli_demo.py`

**Interfaces:**
- Consumes: `Profile()`, `validate_json(value, schema_path)`, `canonical_json(value)`, and `PROJECT_ROOT`.
- Produces: `WorkspaceRef`, `initialize_workspace(path: Path) -> WorkspaceRef`, `managed_workspace(root: Path, name: str) -> Path`, `create_managed_workspace(root: Path, name: str) -> WorkspaceRef`, and `list_managed_workspaces(root: Path) -> tuple[WorkspaceRef, ...]`.

- [ ] **Step 1: Write failing validation and lifecycle tests**

```python
from pathlib import Path

import pytest

from rflp_lite.application.workspaces import (
    create_managed_workspace,
    list_managed_workspaces,
    managed_workspace,
)
from rflp_lite.domain.errors import ContractViolation


def test_managed_workspace_create_and_list(tmp_path: Path) -> None:
    created = create_managed_workspace(tmp_path / "workspaces", "demo-01")
    assert created.name == "demo-01"
    assert created.path == (tmp_path / "workspaces" / "demo-01").resolve()
    assert created.profile_path.is_file()
    assert list_managed_workspaces(tmp_path / "workspaces") == (created,)


@pytest.mark.parametrize("name", ("../escape", "/tmp/escape", "a/b", "a\\b", "", "."))
def test_managed_workspace_rejects_unsafe_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(ContractViolation):
        managed_workspace(tmp_path / "workspaces", name)


def test_create_does_not_overwrite_existing_profile(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    created = create_managed_workspace(root, "demo")
    original = created.profile_path.read_text(encoding="utf-8")
    with pytest.raises(ContractViolation, match="already exists"):
        create_managed_workspace(root, "demo")
    assert created.profile_path.read_text(encoding="utf-8") == original
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `.venv/bin/python -m pytest tests/application/test_workspaces.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'rflp_lite.application.workspaces'`.

- [ ] **Step 3: Implement the workspace service and reuse it from CLI init**

```python
@dataclass(frozen=True, slots=True)
class WorkspaceRef:
    name: str
    path: Path
    profile_path: Path
    initialized: bool


_WORKSPACE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


def initialize_workspace(path: Path) -> WorkspaceRef:
    workspace = path.resolve()
    profile_path = workspace / "profile.json"
    if profile_path.exists():
        raise ContractViolation(f"workspace already exists: {workspace.name}")
    workspace.mkdir(parents=True, exist_ok=True)
    profile = Profile()
    validate_json(profile.as_dict(), PROJECT_ROOT / "schemas" / "profile.schema.json")
    profile_path.write_text(canonical_json(profile.as_dict()) + "\n", encoding="utf-8")
    return WorkspaceRef(workspace.name, workspace, profile_path, True)


def managed_workspace(root: Path, name: str) -> Path:
    if not _WORKSPACE_NAME.fullmatch(name):
        raise ContractViolation("workspace name must use 1-64 letters, digits, dot, underscore, or hyphen")
    resolved_root = root.resolve()
    candidate = (resolved_root / name).resolve()
    if candidate.parent != resolved_root:
        raise ContractViolation("workspace path escapes the managed root")
    return candidate


def create_managed_workspace(root: Path, name: str) -> WorkspaceRef:
    return initialize_workspace(managed_workspace(root, name))


def list_managed_workspaces(root: Path) -> tuple[WorkspaceRef, ...]:
    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        return ()
    values = (
        WorkspaceRef(path.name, path.resolve(), path.resolve() / "profile.json", True)
        for path in resolved_root.iterdir()
        if path.is_dir() and (path / "profile.json").is_file()
    )
    return tuple(sorted(values, key=lambda item: item.name))
```

Move CLI profile creation to `initialize_workspace(args.workspace)` and keep the existing canonical JSON response shape.

- [ ] **Step 4: Verify service and CLI regression tests**

Run: `.venv/bin/python -m pytest tests/application/test_workspaces.py tests/e2e/test_cli_demo.py -v`

Expected: all tests pass, including CLI initialization at arbitrary external paths.

- [ ] **Step 5: Commit the independent workspace boundary**

```bash
git add src/rflp_lite/application/workspaces.py src/rflp_lite/interface/cli.py tests/application/test_workspaces.py tests/e2e/test_cli_demo.py
git commit -m "feat: add safe managed workspaces"
```

---

### Task 2: Normalized Run Catalog and Registered Downloads

**Files:**
- Modify: `src/rflp_lite/application/demo.py`
- Create: `src/rflp_lite/application/run_catalog.py`
- Modify: `tests/application/test_demo_workflow.py`
- Create: `tests/application/test_run_catalog.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the `.rflp/runs/<result_hash>/` directory written by `run_demo` and `canonical_json`.
- Produces: `RUN_OUTPUTS`, `RunRecord`, `list_runs(workspace: Path) -> tuple[RunRecord, ...]`, `load_run(workspace: Path, result_hash: str) -> RunRecord`, and `registered_output(record: RunRecord, filename: str) -> Path`.

- [ ] **Step 1: Write failing catalog and expanded-output tests**

```python
def test_demo_exports_complete_web_read_model(tmp_path: Path) -> None:
    result = run_demo(tmp_path, Profile())
    run_dir = Path(result.manifest_path).parent
    assert {path.name for path in run_dir.iterdir()} == {
        "artifacts.json", "spans.json", "claims.json", "rflp.json",
        "candidates.json", "decision.json", "simulation.json", "baseline.json",
        "delta.json", "task-contracts.json", "evidence.json", "run-manifest.json",
    }


def test_catalog_loads_latest_run_and_confines_downloads(tmp_path: Path) -> None:
    result = run_demo(tmp_path, Profile())
    records = list_runs(tmp_path)
    assert records[0].result_hash == result.result_hash
    assert load_run(tmp_path, result.result_hash) == records[0]
    assert registered_output(records[0], "evidence.json").is_file()
    with pytest.raises(ContractViolation):
        registered_output(records[0], "../../profile.json")
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `.venv/bin/python -m pytest tests/application/test_demo_workflow.py tests/application/test_run_catalog.py -v`

Expected: import failure for `run_catalog` and missing `artifacts.json`, `spans.json`, and `decision.json` assertions.

- [ ] **Step 3: Export the missing domain results and implement the catalog**

Add these three entries to `run_demo` outputs:

```python
outputs = {
    "artifacts.json": (artifact,),
    "spans.json": spans,
    "claims.json": claims,
    "rflp.json": {"elements": elements, "relations": relations},
    "candidates.json": candidates,
    "decision.json": decision,
    "simulation.json": selected_simulation,
    "baseline.json": baseline,
    "delta.json": delta,
    "task-contracts.json": task_contracts,
    "evidence.json": evidence,
    "run-manifest.json": manifest,
}
```

Implement the catalog with a strict hash and filename allowlist:

```python
RUN_OUTPUTS = (
    "artifacts.json", "spans.json", "claims.json", "rflp.json",
    "candidates.json", "decision.json", "simulation.json", "baseline.json",
    "delta.json", "task-contracts.json", "evidence.json", "run-manifest.json",
)
_RESULT_HASH = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class RunRecord:
    result_hash: str
    run_dir: Path
    manifest: dict[str, object]
    outputs: dict[str, object]
    modified_ns: int


def load_run(workspace: Path, result_hash: str) -> RunRecord:
    if not _RESULT_HASH.fullmatch(result_hash):
        raise ContractViolation("invalid result hash")
    run_dir = (workspace.resolve() / ".rflp" / "runs" / result_hash).resolve()
    manifest_path = run_dir / "run-manifest.json"
    if not manifest_path.is_file():
        raise ContractViolation(f"run not found: {result_hash}")
    outputs = {
        name: json.loads((run_dir / name).read_text(encoding="utf-8"))
        for name in RUN_OUTPUTS
        if (run_dir / name).is_file()
    }
    manifest = outputs["run-manifest.json"]
    if manifest["result_hash"] != result_hash:
        raise ContractViolation("run manifest hash does not match its directory")
    return RunRecord(result_hash, run_dir, manifest, outputs, manifest_path.stat().st_mtime_ns)
```

Sort `list_runs` by `(modified_ns, result_hash)` descending. `registered_output` must accept only names in `RUN_OUTPUTS`, require an existing regular file, and verify `path.parent == record.run_dir`.

- [ ] **Step 4: Run catalog, workflow, reproducibility, and schema tests**

Run: `.venv/bin/python -m pytest tests/application/test_demo_workflow.py tests/application/test_run_catalog.py tests/e2e/test_cli_demo.py tests/governance/test_validation.py -v`

Expected: all tests pass; existing result and Baseline hashes remain deterministic across workspaces.

- [ ] **Step 5: Update the README output list and commit**

Document all 12 run files, then run `git diff --check`.

```bash
git add src/rflp_lite/application/demo.py src/rflp_lite/application/run_catalog.py tests/application/test_demo_workflow.py tests/application/test_run_catalog.py README.md
git commit -m "feat: expose complete run catalog"
```

---

### Task 3: Web Facade, Optional Dependencies, and Application Shell

**Files:**
- Modify: `pyproject.toml`
- Create: `src/rflp_lite/application/web_facade.py`
- Create: `src/rflp_lite/interface/web/__init__.py`
- Create: `src/rflp_lite/interface/web/app.py`
- Create: `src/rflp_lite/interface/web/routes.py`
- Create: `src/rflp_lite/interface/web/presenters.py`
- Create: `src/rflp_lite/interface/web/templates/base.html`
- Create: `src/rflp_lite/interface/web/templates/error.html`
- Create: `src/rflp_lite/interface/web/templates/dashboard.html`
- Create: `src/rflp_lite/interface/web/static/app.css`
- Create: `src/rflp_lite/interface/web/static/vendor/htmx.min.js`
- Create: `src/rflp_lite/interface/web/static/vendor/HTMX-LICENSE.txt`
- Create: `tests/application/test_web_facade.py`
- Create: `tests/interface/web/test_app.py`

**Interfaces:**
- Consumes: Task 1 workspace functions, Task 2 catalog functions, `SQLiteRepository.audit_events`, and `run_demo`.
- Produces: `WebFacade(workspace_root: Path, fixture_root: Path | None = None)`, `create_app(workspace_root: Path | None = None, fixture_root: Path | None = None) -> FastAPI`, and `build_dashboard_view(workspace: WorkspaceRef, workspaces: tuple[WorkspaceRef, ...], latest: RunRecord | None, audit: tuple[dict[str, object], ...]) -> dict[str, object]`.

- [ ] **Step 1: Add failing facade and application-factory tests**

```python
def test_empty_dashboard_is_honest(tmp_path: Path) -> None:
    facade = WebFacade(tmp_path / "workspaces")
    view = facade.dashboard(None)
    assert view["workspace"] is None
    assert view["latest_run"] is None
    assert view["counts"] == {}


def test_app_serves_local_assets_and_empty_dashboard(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    response = client.get("/")
    assert response.status_code == 200
    assert "RFLP-Lite" in response.text
    assert "尚无工作区" in response.text
    css = client.get("/static/app.css")
    assert css.status_code == 200
    assert "--color-accent" in css.text
    htmx = client.get("/static/vendor/htmx.min.js")
    assert htmx.status_code == 200
```

- [ ] **Step 2: Run focused tests and verify missing Web modules**

Run: `.venv/bin/python -m pytest tests/application/test_web_facade.py tests/interface/web/test_app.py -v`

Expected: collection fails because `web_facade` and `interface.web` do not exist.

- [ ] **Step 3: Add Web extras and package data**

```toml
[project.optional-dependencies]
web = [
  "fastapi>=0.116,<1",
  "uvicorn>=0.35,<1",
  "jinja2>=3.1,<4",
  "python-multipart>=0.0.20,<1",
  "httpx>=0.28,<1",
]

[tool.setuptools.package-data]
"rflp_lite.interface.web" = [
  "templates/*.html",
  "static/*.css",
  "static/vendor/*.js",
  "static/vendor/*.txt",
]
```

Install locally with `.venv/bin/python -m pip install -e '.[dev,schema,evidence,opt,web]'`.

- [ ] **Step 4: Vendor and verify official HTMX 2.0.10**

```bash
curl -fsSL https://raw.githubusercontent.com/bigskysoftware/htmx/v2.0.10/dist/htmx.min.js -o src/rflp_lite/interface/web/static/vendor/htmx.min.js
printf '71ea67185bfa8c98c39d31717c6fce5d852370fcdfd129db4543774d3145c0de  src/rflp_lite/interface/web/static/vendor/htmx.min.js\n' | shasum -a 256 -c -
curl -fsSL https://raw.githubusercontent.com/bigskysoftware/htmx/v2.0.10/LICENSE -o src/rflp_lite/interface/web/static/vendor/HTMX-LICENSE.txt
```

Expected checksum output: `src/rflp_lite/interface/web/static/vendor/htmx.min.js: OK`.

- [ ] **Step 5: Implement the HTTP-free Facade and deterministic presenter**

```python
class WebFacade:
    def __init__(self, workspace_root: Path, fixture_root: Path | None = None):
        self.workspace_root = workspace_root.resolve()
        self.fixture_root = fixture_root

    def workspaces(self) -> tuple[WorkspaceRef, ...]:
        return list_managed_workspaces(self.workspace_root)

    def workspace(self, name: str) -> WorkspaceRef:
        path = managed_workspace(self.workspace_root, name)
        profile_path = path / "profile.json"
        if not profile_path.is_file():
            raise ContractViolation(f"workspace not found: {name}")
        return WorkspaceRef(name, path, profile_path, True)

    def audit(self, workspace_name: str) -> tuple[dict[str, object], ...]:
        workspace = self.workspace(workspace_name)
        database = workspace.path / ".rflp" / "model.db"
        if not database.is_file():
            return ()
        repository = SQLiteRepository(database)
        try:
            return repository.audit_events()
        finally:
            repository.close()

    def dashboard(self, workspace_name: str | None) -> dict[str, object]:
        if workspace_name is None:
            workspaces = self.workspaces()
            if not workspaces:
                return {"workspace": None, "workspaces": (), "latest_run": None, "counts": {}, "audit": ()}
            workspace_name = workspaces[0].name
        workspace = self.workspace(workspace_name)
        runs = list_runs(workspace.path)
        latest = runs[0] if runs else None
        return build_dashboard_view(workspace, self.workspaces(), latest, self.audit(workspace_name))
```

Implement the presenter with exact real-output keys:

```python
def build_dashboard_view(
    workspace: WorkspaceRef,
    workspaces: tuple[WorkspaceRef, ...],
    latest: RunRecord | None,
    audit: tuple[dict[str, object], ...],
) -> dict[str, object]:
    if latest is None:
        return {"workspace": workspace, "workspaces": workspaces, "latest_run": None, "counts": {}, "audit": audit}
    outputs = latest.outputs
    elements = outputs["rflp.json"]["elements"]
    counts = {
        "claims": len(outputs["claims.json"]),
        "R": sum(item["layer"] == "R" for item in elements),
        "F": sum(item["layer"] == "F" for item in elements),
        "L": sum(item["layer"] == "L" for item in elements),
        "P": sum(item["layer"] == "P" for item in elements),
        "candidates": len(outputs["candidates.json"]),
        "tasks": len(outputs["task-contracts.json"]),
        "evidence": len(outputs["evidence.json"]),
    }
    return {"workspace": workspace, "workspaces": workspaces, "latest_run": latest, "counts": counts, "audit": audit}
```

Presenter functions shorten hashes only for display while retaining full hash fields for links and downloads.

- [ ] **Step 6: Implement the application factory and base shell**

```python
def create_app(
    workspace_root: Path | None = None,
    fixture_root: Path | None = None,
) -> FastAPI:
    package_dir = Path(__file__).resolve().parent
    root = (workspace_root or PROJECT_ROOT / "workspaces").resolve()
    facade = WebFacade(root, fixture_root)
    app = FastAPI(title="RFLP-Lite Local Console", docs_url=None, redoc_url=None)
    app.state.facade = facade
    app.mount("/static", StaticFiles(directory=package_dir / "static"), name="static")
    app.include_router(router)
    register_exception_handlers(app)
    return app
```

Add the empty/latest root dashboard route:

```python
@router.get("/")
def dashboard(request: Request) -> Response:
    context = request.app.state.facade.dashboard(None)
    return templates.TemplateResponse(request, "dashboard.html", context)
```

`base.html` must include skip navigation, fixed sidebar, current workspace label, local-only badge, `{% block content %}`, and only `/static/vendor/htmx.min.js`. `error.html` must show a stable message and recovery link, never `repr(exc)` or a traceback.

- [ ] **Step 7: Add the cockpit token system and make focused tests pass**

```css
:root {
  --color-canvas: #0d1517;
  --color-panel: #121d20;
  --color-reading: #f3f7f5;
  --color-text: #dce8e4;
  --color-text-dark: #16211e;
  --color-muted: #7f9790;
  --color-accent: #70e1bc;
  --color-info: #78aef2;
  --color-planned: #e8b86d;
  --color-danger: #ef7d76;
  --radius-panel: 14px;
  --shadow-panel: 0 20px 60px rgba(0, 0, 0, .22);
}

:focus-visible { outline: 3px solid var(--color-info); outline-offset: 3px; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; } }
```

Run: `.venv/bin/python -m pytest tests/application/test_web_facade.py tests/interface/web/test_app.py -v`

Expected: all focused tests pass.

- [ ] **Step 8: Verify packaging and architecture, then commit**

Run: `.venv/bin/python -m build && .venv/bin/lint-imports`

Expected: sdist/wheel build successfully and all three contracts are kept.

```bash
git add pyproject.toml src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web tests/application/test_web_facade.py tests/interface/web/test_app.py
git commit -m "feat: add local web application shell"
```

---

### Task 4: Workspace Creation, Run Center, and Real Dashboard

**Files:**
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/presenters.py`
- Modify: `src/rflp_lite/interface/web/templates/dashboard.html`
- Create: `src/rflp_lite/interface/web/templates/run-center.html`
- Create: `src/rflp_lite/interface/web/templates/run-detail.html`
- Create: `src/rflp_lite/interface/web/templates/_run-error.html`
- Modify: `src/rflp_lite/interface/web/static/app.css`
- Modify: `tests/application/test_web_facade.py`
- Create: `tests/interface/web/test_pages.py`

**Interfaces:**
- Consumes: `create_managed_workspace`, `run_demo`, `Profile`, and `RunRecord`.
- Produces: `WebFacade.create_workspace(name: str) -> WorkspaceRef`, `WebFacade.runs(workspace_name: str) -> tuple[RunRecord, ...]`, `WebFacade.execute(workspace_name: str, solver: str, seed: int) -> RunRecord`, and Run Center routes.

- [ ] **Step 1: Write failing create/run/HTMX tests**

```python
def test_web_creates_workspace_and_runs_real_pipeline(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    created = client.post("/workspaces", data={"name": "demo"}, follow_redirects=False)
    assert created.status_code == 303
    assert created.headers["location"] == "/w/demo"

    run = client.post(
        "/w/demo/runs",
        data={"solver": "heuristic", "seed": "42"},
        headers={"HX-Request": "true"},
    )
    assert run.status_code == 204
    assert run.headers["HX-Redirect"].startswith("/w/demo/runs/")
    detail = client.get(run.headers["HX-Redirect"])
    assert "Artifact → TextSpan → Claim" in detail.text
    assert "passed" in detail.text.lower()


def test_run_form_rejects_invalid_seed_without_starting(tmp_path: Path) -> None:
    client = seeded_client(tmp_path, workspace="demo")
    response = client.post(
        "/w/demo/runs",
        data={"solver": "heuristic", "seed": "-1"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422
    assert "Seed 必须是非负整数" in response.text
    assert not (tmp_path / "workspaces" / "demo" / ".rflp").exists()
```

- [ ] **Step 2: Run the page tests and verify missing routes**

Run: `.venv/bin/python -m pytest tests/interface/web/test_pages.py -v`

Expected: POST requests return 404 or 405.

- [ ] **Step 3: Implement Facade mutation methods with validated defaults**

```python
def create_workspace(self, name: str) -> WorkspaceRef:
    return create_managed_workspace(self.workspace_root, name)


def runs(self, workspace_name: str) -> tuple[RunRecord, ...]:
    return list_runs(self.workspace(workspace_name).path)


def execute(self, workspace_name: str, solver: str, seed: int) -> RunRecord:
    workspace = self.workspace(workspace_name)
    profile = Profile(solver=solver, seed=seed, candidate_limit=3, timeout_seconds=5)
    result = run_demo(workspace.path, profile, fixture_root=self.fixture_root)
    return load_run(workspace.path, result.result_hash)
```

Do not expose candidate limit or timeout fields in the template.

- [ ] **Step 4: Implement POST/Redirect/GET and HTMX redirect behavior**

```python
@router.post("/workspaces")
def create_workspace(request: Request, name: Annotated[str, Form()]) -> Response:
    workspace = request.app.state.facade.create_workspace(name.strip())
    return RedirectResponse(url=f"/w/{workspace.name}", status_code=303)


@router.post("/w/{workspace_name}/runs")
def start_run(
    request: Request,
    workspace_name: str,
    solver: Annotated[str, Form()],
    seed: Annotated[str, Form()],
) -> Response:
    try:
        parsed_seed = int(seed)
        if parsed_seed < 0:
            raise ValueError
    except ValueError:
        return render_run_error(request, "Seed 必须是非负整数", status_code=422)
    try:
        record = request.app.state.facade.execute(workspace_name, solver, parsed_seed)
    except (ContractViolation, RflpError, OSError) as exc:
        return render_run_error(request, exc, status_code=422)
    location = f"/w/{workspace_name}/runs/{record.result_hash}"
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=204, headers={"HX-Redirect": location})
    return RedirectResponse(location, status_code=303)
```

Add the dashboard, history, and detail GET routes with exact destinations:

```python
@router.get("/w/{workspace_name}")
def workspace_dashboard(request: Request, workspace_name: str) -> Response:
    context = request.app.state.facade.dashboard(workspace_name)
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/w/{workspace_name}/runs")
def run_center(request: Request, workspace_name: str) -> Response:
    facade: WebFacade = request.app.state.facade
    context = {"workspace": facade.workspace(workspace_name), "runs": facade.runs(workspace_name)}
    return templates.TemplateResponse(request, "run-center.html", context)


@router.get("/w/{workspace_name}/runs/{result_hash}")
def run_detail(request: Request, workspace_name: str, result_hash: str) -> Response:
    facade: WebFacade = request.app.state.facade
    workspace = facade.workspace(workspace_name)
    record = load_run(workspace.path, result_hash)
    return templates.TemplateResponse(request, "run-detail.html", run_detail_context(workspace, record))
```

The run form uses `hx-disabled-elt="find button"`, `hx-indicator="#run-indicator"`, and targets `_run-error.html`; its loading copy is “正在执行完整链路，请保持页面打开”，without a percentage.

- [ ] **Step 5: Render honest dashboard and run detail data**

Dashboard cards must derive Claim, R/F/L/P, Candidate, TaskContract, and Evidence counts from `RunRecord.outputs`; the chain status comes from `run-manifest.json`; the selected candidate comes from `decision.json`; the full Baseline hash is present in a copyable code element.

```python
def run_detail_context(workspace: WorkspaceRef, record: RunRecord) -> dict[str, object]:
    return {
        "workspace": workspace,
        "run": record,
        "manifest": record.outputs["run-manifest.json"],
        "decision": record.outputs["decision.json"],
        "simulation": record.outputs["simulation.json"],
        "baseline": record.outputs["baseline.json"],
        "files": tuple(name for name in RUN_OUTPUTS if name in record.outputs),
    }
```

- [ ] **Step 6: Verify both Solver paths and failure protection**

Run: `.venv/bin/python -m pytest tests/application/test_web_facade.py tests/interface/web/test_pages.py tests/application/test_failure_protection.py -v`

Expected: Heuristic and CP-SAT submissions both pass; invalid input returns 422; injected Adapter failure leaves the previous Baseline hash unchanged.

- [ ] **Step 7: Commit the first usable Web workflow**

```bash
git add src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web tests/application/test_web_facade.py tests/interface/web/test_pages.py
git commit -m "feat: run RFLP chain from web console"
```

---

### Task 5: Artifact-to-Evidence Read-Only Pages and Safe Downloads

**Files:**
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/presenters.py`
- Create: `src/rflp_lite/interface/web/templates/artifacts.html`
- Create: `src/rflp_lite/interface/web/templates/rflp-model.html`
- Create: `src/rflp_lite/interface/web/templates/candidates.html`
- Create: `src/rflp_lite/interface/web/templates/simulation.html`
- Create: `src/rflp_lite/interface/web/templates/baselines.html`
- Create: `src/rflp_lite/interface/web/templates/tasks.html`
- Create: `src/rflp_lite/interface/web/templates/evidence.html`
- Modify: `src/rflp_lite/interface/web/static/app.css`
- Modify: `tests/interface/web/test_pages.py`
- Modify: `tests/application/test_run_catalog.py`

**Interfaces:**
- Consumes: `WebFacade.workspace`, `load_run`, and `registered_output`.
- Produces: seven read-only page routes and `GET /w/{workspace}/runs/{result_hash}/downloads/{filename}`.

- [ ] **Step 1: Add failing navigation/content/download security tests**

```python
@pytest.mark.parametrize(
    ("suffix", "expected"),
    (
        ("model/artifacts", "TextSpan"),
        ("model/rflp", "Requirement"),
        ("decision/candidates", "Candidate"),
        ("decision/simulation", "trace_hash"),
        ("governance/baselines", "Baseline"),
        ("governance/tasks", "TaskContract"),
        ("governance/evidence", "Audit"),
    ),
)
def test_real_run_pages(client_with_run, suffix: str, expected: str) -> None:
    client, workspace, result_hash = client_with_run
    response = client.get(f"/w/{workspace}/runs/{result_hash}/{suffix}")
    assert response.status_code == 200
    assert expected in response.text


def test_download_is_allowlisted(client_with_run) -> None:
    client, workspace, result_hash = client_with_run
    good = client.get(f"/w/{workspace}/runs/{result_hash}/downloads/evidence.json")
    assert good.status_code == 200
    assert good.headers["content-type"].startswith("application/json")
    escaped = client.get(f"/w/{workspace}/runs/{result_hash}/downloads/%2E%2E%2Fprofile.json")
    assert escaped.status_code in {400, 404}
```

- [ ] **Step 2: Run the focused tests and verify page 404s**

Run: `.venv/bin/python -m pytest tests/interface/web/test_pages.py::test_real_run_pages tests/interface/web/test_pages.py::test_download_is_allowlisted -v`

Expected: each new page returns 404.

- [ ] **Step 3: Add one shared loader and thin page routes**

```python
def _run_page(request: Request, workspace_name: str, result_hash: str) -> tuple[WorkspaceRef, RunRecord]:
    facade: WebFacade = request.app.state.facade
    workspace = facade.workspace(workspace_name)
    return workspace, load_run(workspace.path, result_hash)


@router.get("/w/{workspace_name}/runs/{result_hash}/model/artifacts")
def artifacts_page(request: Request, workspace_name: str, result_hash: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    context = artifacts_context(workspace, run)
    return templates.TemplateResponse(request, "artifacts.html", context)
```

Add the remaining routes explicitly; every function only loads, presents, and renders:

```python
@router.get("/w/{workspace_name}/runs/{result_hash}/model/rflp")
def rflp_page(request: Request, workspace_name: str, result_hash: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    return templates.TemplateResponse(request, "rflp-model.html", rflp_context(workspace, run))


@router.get("/w/{workspace_name}/runs/{result_hash}/decision/candidates")
def candidates_page(request: Request, workspace_name: str, result_hash: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    return templates.TemplateResponse(request, "candidates.html", candidates_context(workspace, run))


@router.get("/w/{workspace_name}/runs/{result_hash}/decision/simulation")
def simulation_page(request: Request, workspace_name: str, result_hash: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    return templates.TemplateResponse(request, "simulation.html", simulation_context(workspace, run))


@router.get("/w/{workspace_name}/runs/{result_hash}/governance/baselines")
def baselines_page(request: Request, workspace_name: str, result_hash: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    return templates.TemplateResponse(request, "baselines.html", baselines_context(workspace, run))


@router.get("/w/{workspace_name}/runs/{result_hash}/governance/tasks")
def tasks_page(request: Request, workspace_name: str, result_hash: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    return templates.TemplateResponse(request, "tasks.html", tasks_context(workspace, run))


@router.get("/w/{workspace_name}/runs/{result_hash}/governance/evidence")
def evidence_page(request: Request, workspace_name: str, result_hash: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    audit = request.app.state.facade.audit(workspace_name)
    return templates.TemplateResponse(request, "evidence.html", evidence_context(workspace, run, audit))
```

- [ ] **Step 4: Implement deterministic presenters and readable templates**

`artifacts_context` joins TextSpan to Artifact and Claim by IDs without changing the underlying records. `rflp_context` groups elements in the fixed order `requirement`, `function`, `logical`, `physical`. Candidate order is descending score then ID. Simulation events order by `(time, priority, sequence)`. TaskContract cards show dependency, read, write, invariant, and acceptance sections. Evidence groups by kind and includes audit events read through the Facade.

```python
LAYER_ORDER = ("R", "F", "L", "P")


def rflp_context(workspace: WorkspaceRef, record: RunRecord) -> dict[str, object]:
    model = record.outputs["rflp.json"]
    grouped = {
        layer: tuple(item for item in model["elements"] if item["layer"] == layer)
        for layer in LAYER_ORDER
    }
    return {"workspace": workspace, "run": record, "layers": grouped, "relations": model["relations"]}
```

Dense raw text and JSON snippets use `.reading-panel` with dark text on `--color-reading`; tables have visible headers, horizontal overflow, and `<caption class="sr-only">`.

- [ ] **Step 5: Implement registered JSON downloads**

```python
@router.get("/w/{workspace_name}/runs/{result_hash}/downloads/{filename}")
def download_output(request: Request, workspace_name: str, result_hash: str, filename: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    path = registered_output(run, filename)
    return FileResponse(path, media_type="application/json", filename=filename)
```

Map `ContractViolation` from an invalid filename to 404. Do not resolve or open the route parameter before `registered_output` validates it.

- [ ] **Step 6: Run all Web read and security tests**

Run: `.venv/bin/python -m pytest tests/application/test_run_catalog.py tests/interface/web/test_pages.py -v`

Expected: all page routes show real fixture content and traversal requests never return `profile.json` or another non-run file.

- [ ] **Step 7: Commit the full read-only chain**

```bash
git add src/rflp_lite/interface/web tests/interface/web/test_pages.py tests/application/test_run_catalog.py
git commit -m "feat: browse complete RFLP evidence chain"
```

---

### Task 6: Capability Center, Empty/Error States, and Visual Polish

**Files:**
- Modify: `src/rflp_lite/interface/web/presenters.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Create: `src/rflp_lite/interface/web/templates/capabilities.html`
- Modify: `src/rflp_lite/interface/web/templates/base.html`
- Modify: `src/rflp_lite/interface/web/templates/error.html`
- Modify: `src/rflp_lite/interface/web/static/app.css`
- Modify: `tests/interface/web/test_app.py`
- Modify: `tests/interface/web/test_pages.py`

**Interfaces:**
- Consumes: no future subsystem code.
- Produces: immutable `CAPABILITIES`, `/capabilities`, complete empty/error states, keyboard and reduced-motion behavior.

- [ ] **Step 1: Write failing placeholder honesty and accessibility tests**

```python
def test_capability_center_has_disabled_honest_placeholders(client: TestClient) -> None:
    response = client.get("/capabilities")
    assert response.status_code == 200
    for name in ("LLM / Ollama", "Docling", "SysML v2", "MLflow", "登录与权限"):
        assert name in response.text
    assert response.text.count("尚未启用") >= 9
    assert "disabled" in response.text
    assert "模拟结果" not in response.text


def test_every_page_has_skip_link_and_local_mode_label(client: TestClient) -> None:
    response = client.get("/")
    assert 'href="#main-content"' in response.text
    assert 'id="main-content"' in response.text
    assert "仅限本机" in response.text
```

- [ ] **Step 2: Run tests and verify the capability route failure**

Run: `.venv/bin/python -m pytest tests/interface/web/test_app.py tests/interface/web/test_pages.py -v`

Expected: `/capabilities` returns 404 and accessibility assertions fail until the shell is completed.

- [ ] **Step 3: Define the exact capability catalog**

```python
CAPABILITIES = (
    Capability("LLM / Ollama", "planned", "从声明辅助生成模型建议", "Ollama 或兼容 LLM Adapter", "Claim", "候选 ModelElement", "契约、审计与人工批准门禁完成"),
    Capability("Docling", "planned", "解析复杂 PDF/DOCX", "Docling optional adapter", "本地文档", "Artifact/TextSpan", "版面回归与资源上限完成"),
    Capability("SysML v2", "planned", "导入、导出与图形编辑", "SysML v2 repository adapter", "RFLP model", "SysML v2 model", "映射契约和往返测试完成"),
    Capability("MLflow", "planned", "追踪实验与参数", "MLflow adapter", "Run manifest", "Experiment record", "本地存储策略完成"),
    Capability("Profile / Pack 编辑", "planned", "配置已验证运行参数", "Schema-driven editor", "Profile JSON", "validated Profile", "字段级校验和版本迁移完成"),
    Capability("后台任务队列", "planned", "承载长耗时运行", "persistent job repository", "Run request", "Job status", "重启恢复和幂等完成"),
    Capability("对外 Web API", "planned", "为受控客户端提供契约接口", "versioned API adapter", "versioned request", "versioned response", "认证、限流和 OpenAPI 契约完成"),
    Capability("登录与权限", "planned", "支持多人和角色边界", "identity and policy layer", "identity", "authorization decision", "威胁模型和审计完成"),
    Capability("插件与远程运行", "planned", "接入受控外部能力", "signed plugin/runtime protocol", "TaskContract", "Evidence", "隔离、签名和回滚完成"),
)
```

Define the immutable display type before the catalog:

```python
@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    status: str
    purpose: str
    dependency: str
    expected_input: str
    expected_output: str
    enable_when: str
```

The capability page renders every field and uses a native `<button disabled aria-disabled="true">尚未启用</button>`.

- [ ] **Step 4: Finish the approved visual hierarchy and all interaction states**

Implement `.app-shell`, `.sidebar`, `.topbar`, `.metric-grid`, `.pipeline`, `.reading-panel`, `.data-table`, `.status-badge`, `.empty-state`, `.error-banner`, `.capability-grid`, `.htmx-indicator`, `.htmx-request`, responsive navigation, hover, active, focus, disabled, print, and reduced-motion rules. Maintain WCAG-style readable contrast and never encode passed/failed only by color.

```css
.htmx-indicator { display: none; }
.htmx-request .htmx-indicator, .htmx-request.htmx-indicator { display: inline-flex; }
.htmx-request [type="submit"] { opacity: .55; pointer-events: none; }
.reading-panel { background: var(--color-reading); color: var(--color-text-dark); border-radius: var(--radius-panel); }
.data-table-wrap { overflow-x: auto; }
.status-badge::before { content: ""; width: .55rem; height: .55rem; border-radius: 50%; background: currentColor; }
@media (max-width: 760px) { .app-shell { grid-template-columns: 1fr; } .sidebar { position: static; } }
```

- [ ] **Step 5: Verify page semantics, no fake data, and visual token coverage**

Run: `.venv/bin/python -m pytest tests/interface/web/test_app.py tests/interface/web/test_pages.py -v`

Expected: all tests pass; empty workspaces show no numeric metrics; every placeholder is disabled and self-describing.

- [ ] **Step 6: Commit capability boundaries and visual polish**

```bash
git add src/rflp_lite/interface/web tests/interface/web/test_app.py tests/interface/web/test_pages.py
git commit -m "feat: polish engineering cockpit and roadmap"
```

---

### Task 7: CLI Startup, Browser Verification, Documentation, and Full Regression

**Files:**
- Modify: `src/rflp_lite/interface/cli.py`
- Modify: `tests/interface/test_cli.py`
- Modify: `README.md`
- Create: `docs/verification/local-web-ui-2026-08-04.md`

**Interfaces:**
- Consumes: `create_app` and Uvicorn.
- Produces: `rflp web --host 127.0.0.1 --port 8000 --workspace-root workspaces`, verified local usage instructions, and a reproducible verification record.

- [ ] **Step 1: Write failing Web command dispatch tests**

```python
def test_web_command_uses_safe_defaults(monkeypatch) -> None:
    captured = {}

    def fake_serve(host: str, port: int, workspace_root: Path) -> None:
        captured.update(host=host, port=port, workspace_root=workspace_root)

    monkeypatch.setattr("rflp_lite.interface.cli.serve_web", fake_serve)
    assert main(["web"]) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000
    assert captured["workspace_root"].name == "workspaces"


def test_web_command_reports_missing_extra(monkeypatch, capsys) -> None:
    def missing(*args, **kwargs):
        raise ModuleNotFoundError("No module named 'fastapi'")

    monkeypatch.setattr("rflp_lite.interface.cli.serve_web", missing)
    assert main(["web"]) == 1
    assert "pip install -e '.[web]'" in capsys.readouterr().err
```

- [ ] **Step 2: Run CLI tests and verify `web` is not recognized**

Run: `.venv/bin/python -m pytest tests/interface/test_cli.py -v`

Expected: argparse rejects `web` or `serve_web` is missing.

- [ ] **Step 3: Add lazy optional startup without breaking core installs**

```python
def serve_web(host: str, port: int, workspace_root: Path) -> None:
    import uvicorn
    from rflp_lite.interface.web.app import create_app

    uvicorn.run(create_app(workspace_root=workspace_root), host=host, port=port)
```

Add parser arguments with exact defaults:

```python
web_parser = subparsers.add_parser("web", help="start the local Web UI")
web_parser.add_argument("--host", default="127.0.0.1")
web_parser.add_argument("--port", type=int, default=8000)
web_parser.add_argument("--workspace-root", type=Path, default=PROJECT_ROOT / "workspaces")
```

Catch `ModuleNotFoundError` only around the Web branch and print the explicit extras installation command; do not mask unrelated exceptions from a running app.

- [ ] **Step 4: Run complete automated verification**

```bash
.venv/bin/python -m pytest -v
.venv/bin/lint-imports
.venv/bin/check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json
.venv/bin/python -m build
```

Expected: all pytest tests pass, three Import Linter contracts are kept, Profile validation passes, and wheel/sdist include templates, CSS, HTMX, and the HTMX license.

- [ ] **Step 5: Run both real Solver smoke tests in managed workspaces**

```bash
.venv/bin/rflp init workspaces/web-heuristic
.venv/bin/rflp demo --workspace workspaces/web-heuristic --seed 42 --solver heuristic
.venv/bin/rflp init workspaces/web-cp-sat
.venv/bin/rflp demo --workspace workspaces/web-cp-sat --seed 42 --solver cp-sat
```

Expected: both commands return canonical JSON with `"status":"passed"`; record candidate counts, Baseline hashes, result hashes, and manifest paths in the verification document.

- [ ] **Step 6: Start the local server and perform browser verification**

Run: `.venv/bin/rflp web --host 127.0.0.1 --port 8000 --workspace-root workspaces`

In Chromium and Safari/WebKit-equivalent rendering, verify: empty state; workspace creation; Heuristic and CP-SAT run submission; disabled/loading state; dashboard; every Artifact-to-Evidence page; valid JSON download; invalid download 404; capability placeholders; keyboard focus; narrow viewport overflow; no external network requests. Save representative screenshots outside the tracked source tree or reference their local verification paths without committing large binary files.

- [ ] **Step 7: Update usage documentation and verification record**

README must contain these exact first-run commands:

```bash
.venv/bin/python -m pip install -e '.[dev,schema,evidence,opt,web]'
.venv/bin/rflp web --host 127.0.0.1 --port 8000
```

Document `http://127.0.0.1:8000`, `Ctrl+C` shutdown, the `workspaces/` boundary, the current real pages, and the planned-only Capability Center. In `docs/verification/local-web-ui-2026-08-04.md`, record environment, package versions, automated command results, both Solver hashes, browser checks, known limitations, and the fact that no remote push was performed.

- [ ] **Step 8: Commit the verified local Web UI**

```bash
git add src/rflp_lite/interface/cli.py tests/interface/test_cli.py README.md docs/verification/local-web-ui-2026-08-04.md
git commit -m "docs: verify local RFLP web console"
```

- [ ] **Step 9: Inspect final state without pushing**

Run: `git status --short && git log --oneline -10 && git remote -v`

Expected: only the user's pre-existing untracked Word/PDF/PPT research files remain; implementation commits are present; no remote is added and nothing is pushed.
