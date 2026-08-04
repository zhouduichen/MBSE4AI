# RFLP-Lite Local Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build and locally install a deterministic RFLP-Lite CLI that runs Artifact through Evidence as one reproducible vertical slice.

**Architecture:** A Python modular monolith keeps domain objects and invariants free of third-party dependencies, coordinates use cases in `application`, and isolates SQLite, OpenAPI, JUnit, and OR-Tools behind typed ports. A fixed VersionedContentService fixture and seed 42 produce canonical JSON artifacts whose hashes can be compared across runs.

**Tech Stack:** Python 3.11+, standard-library dataclasses/sqlite3/json/hashlib/argparse, pytest, Hypothesis, Import Linter, jsonschema/check-jsonschema, Prance, junitparser, OR-Tools CP-SAT.

## Global Constraints

- The supported Python floor is exactly `>=3.11`; the verified local interpreter is Python 3.12.13 on macOS arm64.
- No Docker, GPU, PostgreSQL, Neo4j, external service, or long-running web process is required.
- Domain modules import only the Python standard library and other domain modules.
- SQLite is the transaction source of truth; JSON is used for contracts, fixtures, manifests, and exports.
- External components may produce proposals or evidence but may never mutate an approved Baseline directly.
- All deterministic runs use seed `42`, canonical JSON (`sort_keys=True`, compact separators), and SHA-256 hashes.
- The first installed extras are `dev,schema,evidence,opt`; heavy research components remain absent.
- A failed adapter or invalid contract must leave the approved Baseline hash unchanged.
- Existing Word, PDF, and PowerPoint research files remain unmodified and untracked.

---

### Task 1: Package Skeleton and CLI Contract

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `src/rflp_lite/__init__.py`
- Create: `src/rflp_lite/__main__.py`
- Create: `src/rflp_lite/interface/__init__.py`
- Create: `src/rflp_lite/interface/cli.py`
- Test: `tests/interface/test_cli.py`

**Interfaces:**
- Consumes: none.
- Produces: `rflp_lite.interface.cli.main(argv: Sequence[str] | None = None) -> int` and the `rflp` console command.

- [x] **Step 1: Write the failing CLI test**

```python
from rflp_lite.interface.cli import main


def test_version_command(capsys):
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == "rflp-lite 0.1.0"
```

- [x] **Step 2: Run the test to verify the package is absent**

Run: `python -m pytest tests/interface/test_cli.py::test_version_command -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'rflp_lite'`.

- [x] **Step 3: Add package metadata and the minimal CLI**

```toml
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "rflp-lite"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8.3", "hypothesis>=6.112", "import-linter>=2.1", "check-jsonschema>=0.30"]
schema = ["jsonschema>=4.23"]
evidence = ["prance>=23.6.21", "junitparser>=3.2"]
opt = ["ortools>=9.11"]

[project.scripts]
rflp = "rflp_lite.interface.cli:entrypoint"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

```python
# src/rflp_lite/interface/cli.py
from __future__ import annotations

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rflp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("version")
    args = parser.parse_args(argv)
    if args.command == "version":
        print("rflp-lite 0.1.0")
        return 0
    return 2


def entrypoint() -> None:
    raise SystemExit(main())
```

`src/rflp_lite/__main__.py` calls `entrypoint()`, `src/rflp_lite/__init__.py` exposes `__version__ = "0.1.0"`, package `__init__.py` files are empty, and `.gitignore` contains `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/`, and `.rflp/`.

- [x] **Step 4: Install the editable package and pass the test**

Run: `python -m pip install -e '.[dev,schema,evidence,opt]' && python -m pytest tests/interface/test_cli.py -v`

Expected: installation succeeds and `1 passed` is reported.

- [x] **Step 5: Commit the skeleton**

```bash
git add .gitignore pyproject.toml src/rflp_lite tests/interface/test_cli.py
git commit -m "build: scaffold RFLP-Lite package and CLI"
```

### Task 2: Canonical Domain Model and Immutable Baseline

**Files:**
- Create: `src/rflp_lite/domain/__init__.py`
- Create: `src/rflp_lite/domain/models.py`
- Create: `src/rflp_lite/domain/canonical.py`
- Create: `src/rflp_lite/domain/baseline.py`
- Create: `src/rflp_lite/domain/errors.py`
- Test: `tests/domain/test_baseline.py`
- Test: `tests/domain/test_canonical.py`

**Interfaces:**
- Consumes: Python standard library only.
- Produces: immutable dataclasses `Artifact`, `TextSpan`, `Claim`, `ModelElement`, `Relation`, `Candidate`, `SimulationRun`, `Baseline`, `Delta`, `TaskContract`, `Evidence`; `canonical_hash(value: object) -> str`; `approve_baseline(elements, relations) -> Baseline`.

- [x] **Step 1: Write failing canonicalization and immutability tests**

```python
from dataclasses import FrozenInstanceError

import pytest

from rflp_lite.domain.baseline import approve_baseline
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.models import ModelElement


def test_baseline_is_immutable_and_hash_is_reproducible():
    element = ModelElement("req-1", "requirement", "Restore a version", "approved")
    first = approve_baseline((element,), ())
    second = approve_baseline((element,), ())
    assert first.hash == second.hash == canonical_hash(first.payload)
    with pytest.raises(FrozenInstanceError):
        first.hash = "changed"
```

- [x] **Step 2: Run the tests and confirm missing domain modules**

Run: `python -m pytest tests/domain -v`

Expected: collection FAILS because `rflp_lite.domain` does not exist.

- [x] **Step 3: Implement frozen domain dataclasses and canonical hashing**

All dataclasses use `@dataclass(frozen=True, slots=True)`. IDs, kinds, statuses, references, and numeric values are primitive immutable fields; collections are tuples. `canonical.py` recursively converts dataclasses, tuples, and mappings to JSON-safe values and hashes this exact encoding:

```python
json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
```

`approve_baseline()` accepts only `ModelElement.status == "approved"`, sorts elements and relations by ID, builds a tuple payload, and raises `InvariantViolation` for drafts or duplicate IDs.

- [x] **Step 4: Pass examples and Hypothesis properties**

Add a Hypothesis property generating short Unicode names and asserting two equivalent `ModelElement` instances have the same hash. Run: `python -m pytest tests/domain -v`.

Expected: all domain tests PASS.

- [x] **Step 5: Commit the domain kernel**

```bash
git add src/rflp_lite/domain tests/domain
git commit -m "feat: add canonical domain model and immutable baselines"
```

### Task 3: Ports, Profile, Schemas, and SQLite Repository

**Files:**
- Create: `src/rflp_lite/ports/__init__.py`
- Create: `src/rflp_lite/ports/contracts.py`
- Create: `src/rflp_lite/governance/__init__.py`
- Create: `src/rflp_lite/governance/profile.py`
- Create: `src/rflp_lite/governance/validation.py`
- Create: `src/rflp_lite/adapters/__init__.py`
- Create: `src/rflp_lite/adapters/sqlite_repository.py`
- Create: `schemas/profile.schema.json`
- Create: `schemas/run-manifest.schema.json`
- Create: `examples/profile.json`
- Create: `.importlinter`
- Test: `tests/adapters/test_sqlite_repository.py`
- Test: `tests/governance/test_validation.py`

**Interfaces:**
- Consumes: domain dataclasses and errors.
- Produces: `RepositoryPort` Protocol, `Profile(name, solver, seed, candidate_limit, timeout_seconds)`, `validate_json(instance, schema_path)`, and `SQLiteRepository` transaction methods.

- [x] **Step 1: Write failing repository rollback and schema tests**

```python
def test_transaction_rolls_back_without_changing_baseline(tmp_path):
    repo = SQLiteRepository(tmp_path / "model.db")
    baseline = repo.save_baseline(approved_baseline())
    before = repo.latest_baseline().hash
    with pytest.raises(RuntimeError):
        with repo.transaction():
            repo.record_audit("adapter.started", {"name": "broken"})
            raise RuntimeError("boom")
    assert repo.latest_baseline().hash == before == baseline.hash
```

The profile schema test validates `{"name":"research","solver":"cp-sat","seed":42,"candidate_limit":3,"timeout_seconds":5}` and rejects a negative timeout.

- [x] **Step 2: Run focused tests and verify failure**

Run: `python -m pytest tests/adapters/test_sqlite_repository.py tests/governance/test_validation.py -v`

Expected: FAIL because ports, schemas, and repository are absent.

- [x] **Step 3: Implement contracts, schema validation, and owned tables**

`RepositoryPort` defines `save_artifacts`, `save_claims`, `save_elements`, `save_candidates`, `save_simulation`, `save_baseline`, `save_tasks`, `save_evidence`, `latest_baseline`, and `record_audit`. `SQLiteRepository` creates explicit tables for those aggregate types, stores canonical JSON payloads, uses `BEGIN IMMEDIATE`/commit/rollback, and never exposes its connection outside the adapter.

`validate_json()` imports `jsonschema` lazily and reports a stable `ContractViolation` containing the schema filename and JSON path. The two schemas set `additionalProperties: false` and require every field described in their corresponding dataclass.

- [x] **Step 4: Add architecture contracts and pass gates**

`.importlinter` defines separate contracts for `interface -> application -> ports -> domain` and `adapters -> ports -> domain`, plus a forbidden contract preventing `rflp_lite.domain` from importing adapters, governance, interface, application, or third-party packages.

Run: `python -m pytest tests/adapters tests/governance -v && lint-imports && check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json`.

Expected: tests, import contracts, and schema validation PASS.

- [x] **Step 5: Commit governance and persistence**

```bash
git add .importlinter schemas examples/profile.json src/rflp_lite/ports src/rflp_lite/governance src/rflp_lite/adapters/sqlite_repository.py tests/adapters tests/governance
git commit -m "feat: add governed ports and SQLite repository"
```

### Task 4: Artifact Readers and Deterministic Claim Compilation

**Files:**
- Create: `src/rflp_lite/adapters/readers.py`
- Create: `src/rflp_lite/adapters/evidence_readers.py`
- Create: `src/rflp_lite/application/__init__.py`
- Create: `src/rflp_lite/application/ingest.py`
- Create: `src/rflp_lite/application/compile.py`
- Create: `examples/versioned-content-service/requirements.md`
- Create: `examples/versioned-content-service/openapi.json`
- Create: `examples/versioned-content-service/junit.xml`
- Test: `tests/application/test_ingest_compile.py`
- Test: `tests/adapters/test_evidence_readers.py`

**Interfaces:**
- Consumes: `Artifact`, `TextSpan`, `Claim`, RepositoryPort.
- Produces: `read_markdown(path) -> tuple[Artifact, tuple[TextSpan, ...]]`, `RuleClaimExtractor.extract(spans) -> tuple[Claim, ...]`, `read_openapi(path) -> tuple[Evidence, ...]`, and `read_junit(path) -> tuple[Evidence, ...]`.

- [x] **Step 1: Write failing fixture tests**

The Markdown fixture contains exactly three normative statements: save a content version, restore a historical version, and record an audit event. The test asserts three spans and three claims with stable source references. OpenAPI contains `/versions` GET and POST; JUnit contains one passing `test_restore_version` case. Evidence tests assert vendor objects are converted to internal `Evidence` dataclasses.

- [x] **Step 2: Verify tests fail before adapters exist**

Run: `python -m pytest tests/application/test_ingest_compile.py tests/adapters/test_evidence_readers.py -v`

Expected: FAIL with missing reader and compiler modules.

- [x] **Step 3: Implement structure-preserving readers**

Markdown spans are split by headings and list items rather than tokens. `RuleClaimExtractor` recognizes `MUST`, `SHALL`, and Chinese obligation markers, emits one subject/predicate/object claim per statement, and never creates approved model elements. Prance is invoked only inside `read_openapi`; junitparser is invoked only inside `read_junit`; both adapters attach artifact SHA-256 and source location.

- [x] **Step 4: Pass reader and contract tests**

Run: `python -m pytest tests/application/test_ingest_compile.py tests/adapters/test_evidence_readers.py -v`.

Expected: all fixture tests PASS and exactly three Claims plus OpenAPI/JUnit Evidence are returned.

- [x] **Step 5: Commit ingestion and evidence adapters**

```bash
git add examples src/rflp_lite/application src/rflp_lite/adapters/readers.py src/rflp_lite/adapters/evidence_readers.py tests/application tests/adapters
git commit -m "feat: ingest structured artifacts and evidence"
```

### Task 5: RFLP Synthesis, Dual Solvers, and Deterministic Simulation

**Files:**
- Create: `src/rflp_lite/application/synthesize.py`
- Create: `src/rflp_lite/adapters/solvers.py`
- Create: `src/rflp_lite/simulation/__init__.py`
- Create: `src/rflp_lite/simulation/engine.py`
- Test: `tests/contracts/test_solver_contract.py`
- Test: `tests/simulation/test_engine.py`

**Interfaces:**
- Consumes: Claims and Profile.
- Produces: `synthesize_rflp(claims) -> tuple[tuple[ModelElement, ...], tuple[Relation, ...]]`, `HeuristicSolver.solve(elements, profile) -> tuple[Candidate, ...]`, `CpSatSolver.solve(elements, profile) -> tuple[Candidate, ...]`, and `simulate(candidate, seed) -> SimulationRun`.

- [x] **Step 1: Write shared solver and event-order tests**

```python
@pytest.mark.parametrize("factory", [HeuristicSolver, CpSatSolver])
def test_solver_contract(factory, rflp_elements, profile):
    candidates = factory().solve(rflp_elements, profile)
    assert 2 <= len(candidates) <= profile.candidate_limit
    assert [c.id for c in candidates] == sorted(c.id for c in candidates)
    assert all(c.score >= 0 for c in candidates)


def test_simulation_is_reproducible(candidate):
    assert simulate(candidate, 42) == simulate(candidate, 42)
    assert [e.sequence for e in simulate(candidate, 42).events] == [0, 1, 2, 3]
```

- [x] **Step 2: Run tests and verify the solver boundary is missing**

Run: `python -m pytest tests/contracts/test_solver_contract.py tests/simulation/test_engine.py -v`

Expected: FAIL because synthesis, solvers, and simulation are absent.

- [x] **Step 3: Implement R/F/L/P synthesis and both solvers**

The synthesizer maps the three claims to approved Requirement and Function elements, three named logical patterns (`modular-monolith`, `ports-adapters`, `event-split`), and physical SQLite/JSON configurations with explicit `satisfiedBy`, `allocatedTo`, and `realizedBy` relations. Heuristic scores are fixed integer sums. CP-SAT uses integer variables, one state-owner constraint, candidate/time limits, one worker, and `random_seed=profile.seed`; its results are normalized to the same Candidate DTO and ordering.

- [x] **Step 4: Implement and test the bounded event engine**

The engine uses `heapq` and events ordered by `(time, priority, sequence)`. The fixed scenario performs create, retrieve, restore, and audit actions, checks latency/capacity assertions, injects one recoverable storage failure, and returns trace events, metrics, pass/fail, and canonical hash without calling Python `eval`.

Run: `python -m pytest tests/contracts/test_solver_contract.py tests/simulation/test_engine.py -v`.

Expected: both Solver implementations pass the same contract and simulation tests PASS.

- [x] **Step 5: Commit synthesis and simulation**

```bash
git add src/rflp_lite/application/synthesize.py src/rflp_lite/adapters/solvers.py src/rflp_lite/simulation tests/contracts tests/simulation
git commit -m "feat: add replaceable solvers and deterministic simulation"
```

### Task 6: Baseline Decision, Delta, Task Contract, and Evidence Workflow

**Files:**
- Create: `src/rflp_lite/application/decide.py`
- Create: `src/rflp_lite/application/diff.py`
- Create: `src/rflp_lite/application/tasks.py`
- Create: `src/rflp_lite/application/demo.py`
- Create: `src/rflp_lite/governance/run_manifest.py`
- Test: `tests/application/test_demo_workflow.py`
- Test: `tests/application/test_failure_protection.py`

**Interfaces:**
- Consumes: repository, readers, compiler, synthesizer, SolverPort, simulation, profile.
- Produces: `run_demo(workspace: Path, profile: Profile) -> DemoResult`, containing artifact IDs, claims, RFLP elements, candidates, selected decision, simulation, Baseline, Delta, TaskContract DAG, Evidence, manifest path, and result hash.

- [x] **Step 1: Write the failing complete-chain test**

```python
def test_demo_runs_complete_chain(tmp_path, default_profile):
    result = run_demo(tmp_path, default_profile)
    assert len(result.claims) == 3
    assert len(result.candidates) >= 2
    assert result.baseline.status == "approved"
    assert result.simulation.passed
    assert result.delta.items
    assert result.task_contracts
    assert result.evidence
    assert result.manifest_path.is_file()
```

Failure protection injects a Solver raising `AdapterFailure`, records the current Baseline hash, reruns the workflow, and asserts the hash is unchanged plus one failed audit event exists.

- [x] **Step 2: Run workflow tests and confirm missing orchestration**

Run: `python -m pytest tests/application/test_demo_workflow.py tests/application/test_failure_protection.py -v`

Expected: FAIL because decision, diff, tasks, manifest, and workflow are absent.

- [x] **Step 3: Implement the transactionally protected workflow**

`run_demo()` executes each stage in order, persists aggregate outputs in one owned repository, selects the highest normalized score with ID tie-breaking, approves only after a passing simulation, diffs baseline against AST/OpenAPI/JUnit actual evidence, creates a topologically sorted TaskContract tuple, and writes canonical JSON files beneath `<workspace>/.rflp/runs/<result_hash>/`.

The run manifest contains profile, seed, Python/platform versions, dependency versions, fixture hashes, stage hashes, baseline hash, result hash, and status. Any adapter exception is wrapped as `AdapterFailure`, rolls back the transaction, then records a separate failed audit event without altering the previous approved baseline.

- [x] **Step 4: Pass end-to-end and failure tests**

Run: `python -m pytest tests/application/test_demo_workflow.py tests/application/test_failure_protection.py -v`.

Expected: complete chain PASS; failure test proves identical pre/post Baseline hash.

- [x] **Step 5: Commit the application workflow**

```bash
git add src/rflp_lite/application src/rflp_lite/governance/run_manifest.py tests/application
git commit -m "feat: complete baseline-to-evidence workflow"
```

### Task 7: Local Deployment Command and Release Gates

**Files:**
- Modify: `src/rflp_lite/interface/cli.py`
- Modify: `examples/profile.json`
- Create: `tests/e2e/test_cli_demo.py`
- Create: `README.md`

**Interfaces:**
- Consumes: `run_demo()` and Profile validation.
- Produces: `rflp init PATH`, `rflp demo --workspace PATH --seed 42 --solver heuristic|cp-sat`, and a documented local installation procedure.

- [x] **Step 1: Write the failing CLI end-to-end test**

```python
def test_cli_demo_is_reproducible(tmp_path, capsys):
    first = main(["demo", "--workspace", str(tmp_path / "one"), "--seed", "42"])
    first_output = json.loads(capsys.readouterr().out)
    second = main(["demo", "--workspace", str(tmp_path / "two"), "--seed", "42"])
    second_output = json.loads(capsys.readouterr().out)
    assert first == second == 0
    assert first_output["result_hash"] == second_output["result_hash"]
    assert first_output["baseline_hash"] == second_output["baseline_hash"]
```

- [x] **Step 2: Verify the new command is not yet registered**

Run: `python -m pytest tests/e2e/test_cli_demo.py -v`

Expected: FAIL because `demo` is not a valid CLI command.

- [x] **Step 3: Add CLI commands and operator documentation**

`init` creates the workspace and validates/writes its Profile. `demo` validates arguments, calls `run_demo()`, prints one canonical JSON summary to stdout, prints stable errors to stderr, returns 0 for success and 1 for controlled failures. README documents exact setup, commands, output locations, dependency groups, design boundaries, and cleanup by removing only the chosen demo workspace.

- [x] **Step 4: Run all local release gates**

Run:

```bash
python -m pytest -v
lint-imports
check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json
rflp demo --workspace .local-demo-heuristic --seed 42 --solver heuristic
rflp demo --workspace .local-demo-cp-sat --seed 42 --solver cp-sat
```

Expected: all tests and governance gates PASS; both demo commands return 0, emit at least two candidates, an approved Baseline, SimulationRun, Delta, TaskContract, and Evidence; normalized domain/result hashes are reproducible for repeated runs with the same solver.

- [x] **Step 5: Commit the runnable local deployment**

```bash
git add README.md examples/profile.json src/rflp_lite/interface/cli.py tests/e2e
git commit -m "feat: expose reproducible local RFLP demo"
```

### Task 8: Fresh-Environment Verification and Handoff

**Files:**
- Modify: `README.md`
- Create: `docs/verification/local-demo-2026-08-04.md`

**Interfaces:**
- Consumes: committed package and fixture files.
- Produces: reproducible installation evidence with commands, resolved dependency versions, test counts, output hashes, and known deferred capabilities.

- [x] **Step 1: Create a fresh project-local virtual environment**

Run: `python -m venv .venv && .venv/bin/python -m pip install --upgrade pip && .venv/bin/python -m pip install -e '.[dev,schema,evidence,opt]'`.

Expected: installation succeeds on macOS arm64 without Docker or external services.

- [x] **Step 2: Verify from the fresh environment**

Run: `.venv/bin/python -m pytest -v && .venv/bin/lint-imports && .venv/bin/check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json`.

Expected: every test and gate PASS.

- [x] **Step 3: Run the installed console command twice**

Run `.venv/bin/rflp demo --workspace .local-demo-a --seed 42 --solver heuristic` and `.venv/bin/rflp demo --workspace .local-demo-b --seed 42 --solver heuristic`.

Expected: both commands return 0 and report matching result and Baseline hashes.

- [x] **Step 4: Record verification evidence**

Write `docs/verification/local-demo-2026-08-04.md` with the exact OS/Python values, `pip freeze` subset for selected components, executed commands, test result, both hashes, output paths, and the explicit statement that LLM, Docling, MLflow, SysON, and Web UI remain deferred.

- [x] **Step 5: Commit verification evidence**

```bash
git add README.md docs/verification/local-demo-2026-08-04.md
git commit -m "docs: record local vertical-slice verification"
```
