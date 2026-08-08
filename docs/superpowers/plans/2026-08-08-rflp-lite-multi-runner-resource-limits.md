# RFLP-Lite Multi-Runner Resource Limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the fixed pytest sandbox into a lightweight, decoupled execution layer with built-in pytest/unittest runners, POSIX resource limits, deterministic caching, and bounded parallel execution while preserving the current CLI/Web behavior.

**Architecture:** Keep `project_bridge.py` as the application orchestrator and split execution concerns into small adapter modules: runner command construction, resource policy, cache persistence, and process execution. `RunnerResult` is the only adapter-to-application result boundary; the application aggregates runner Evidence and continues to reuse the existing Delta/TaskContract calculation. CLI and Web translate user input into the same typed execution options.

**Tech Stack:** Python 3.11+ standard library (`subprocess`, `resource`, `concurrent.futures`, `tempfile`, `json`, `hashlib`, `os`), existing `junitparser`, FastAPI/Jinja, pytest.

## Global Constraints

- Runner names are restricted to `pytest` and `unittest`; no shell strings, `shell=True`, or user-provided executable paths.
- Default runner remains `pytest`; default timeout remains 60 seconds and default output cap remains 5 MiB.
- POSIX-only hard memory/file-descriptor limits must be reported as unsupported on other platforms.
- Cache keys include the eligible project file contents, runner name, and normalized resource limits.
- Cache hits must not change `execution.hash`; `cache_hit` and temporary paths are observational metadata only.
- Tests remain independent Evidence and must not change R/F matching or TaskContract semantics.
- Existing calls such as `run_project_tests(project, timeout=120)` and `execute_tests_state(state, source, timeout)` remain valid.
- Do not modify or stage the unrelated user-owned PPTX/DOCX/PDF files.

---

### Task 1: Add typed runner and resource configuration

**Files:**
- Create: `src/rflp_lite/adapters/test_execution_config.py`
- Create: `tests/adapters/test_execution_config.py`

**Interfaces:**
- Produces `ResourceLimits`, `DEFAULT_RESOURCE_LIMITS`, `validate_runner_names`, `validate_jobs`, `build_limits`, and `normalized_limits`.
- `ResourceLimits` fields are `timeout_seconds: int`, `memory_bytes: int | None`, `max_open_files: int | None`, and `max_output_bytes: int`.

- [ ] **Step 1: Write failing validation tests**

```python
def test_build_limits_uses_safe_defaults():
    limits = build_limits()
    assert limits.timeout_seconds == 60
    assert limits.memory_bytes == 1024 * 1024 * 1024
    assert limits.max_open_files == 1024
    assert limits.max_output_bytes == 5 * 1024 * 1024


def test_invalid_limits_and_runner_names_are_rejected():
    with pytest.raises(ContractViolation):
        build_limits(timeout_seconds=0)
    with pytest.raises(ContractViolation):
        build_limits(memory_mib=63)
    with pytest.raises(ContractViolation):
        validate_runner_names(("shell",))
    with pytest.raises(ContractViolation):
        validate_jobs(0)
```

Run: `.venv/bin/pytest tests/adapters/test_execution_config.py -q`  
Expected: FAIL because the module and functions do not exist.

- [ ] **Step 2: Implement pure configuration validation**

Implement constants, a frozen `ResourceLimits` dataclass, and these rules:

```python
def build_limits(
    *,
    timeout_seconds: int = 60,
    memory_mib: int | None = 1024,
    max_open_files: int | None = 1024,
    output_mib: int = 5,
) -> ResourceLimits:
    # timeout: 1..3600; memory: None or >=64 MiB; nofile: None or >=16;
    # output: 8 KiB..64 MiB, otherwise raise ContractViolation.
```

Normalize runners by preserving first occurrence, rejecting duplicates after normalization, and allowing only `pytest` and `unittest`. Normalize `None` memory/nofile to JSON `null`.

- [ ] **Step 3: Run focused tests**

Run: `.venv/bin/pytest tests/adapters/test_execution_config.py -q`  
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/rflp_lite/adapters/test_execution_config.py tests/adapters/test_execution_config.py
git commit -m "feat: add typed test execution limits"
```

### Task 2: Isolate runner command construction and unittest parsing

**Files:**
- Create: `src/rflp_lite/adapters/test_runners.py`
- Modify: `src/rflp_lite/adapters/evidence_readers.py`
- Create: `tests/adapters/test_runners.py`
- Modify: `tests/adapters/test_evidence_readers.py`

**Interfaces:**
- Produces `RunnerSpec`, `runner_spec(name, junit_path)`, and `parse_runner_evidence(name, stdout_path, junit_path)`.
- `RunnerSpec.argv` is a tuple of strings and `RunnerSpec.output_kind` is either `"junit"` or `"unittest-verbose"`.

- [ ] **Step 1: Write failing runner and parser tests**

```python
def test_unittest_runner_uses_current_interpreter():
    spec = runner_spec("unittest", Path("/tmp/junit.xml"))
    assert spec.argv[:3] == (sys.executable, "-m", "unittest")
    assert spec.output_kind == "unittest-verbose"


def test_parse_unittest_verbose_output_is_stable(tmp_path: Path):
    output = tmp_path / "stdout.log"
    output.write_text(
        "test_b (pkg.Case.test_b) ... FAIL\n"
        "test_a (pkg.Case.test_a) ... ok\n"
        "\nRan 2 tests in 0.001s\n\nFAILED (failures=1)\n",
        encoding="utf-8",
    )
    evidence = read_unittest_output(output)
    assert [item.status for item in evidence] == ["passed", "failed"]
    assert [item.target_id for item in evidence] == [
        "verification-pkg.Case.test_a",
        "verification-pkg.Case.test_b",
    ]
```

Run: `.venv/bin/pytest tests/adapters/test_runners.py tests/adapters/test_evidence_readers.py -q`  
Expected: FAIL because the runner module and unittest reader do not exist.

- [ ] **Step 2: Implement the two allowlisted runner specs**

`pytest` resolves `shutil.which("pytest")` and falls back to `(sys.executable, "-m", "pytest")`; it appends `--junitxml` and the temporary XML path. `unittest` always uses `(sys.executable, "-m", "unittest", "discover", "-v")`. Unknown names raise `ContractViolation`.

- [ ] **Step 3: Implement deterministic unittest Evidence parsing**

Add `read_unittest_output(path)` using one anchored regular expression for verbose result lines. Derive `artifact_hash` from the normalized matching lines, use `kind="test-case"`, `source="unittest#<test-id>"`, `target_id="verification-<test-id>"`, and details containing `runner="unittest"`. Sort by test id. Ignore summary/timing lines and retain unparsed status through the executor diagnostics.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/pytest tests/adapters/test_runners.py tests/adapters/test_evidence_readers.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/adapters/test_runners.py src/rflp_lite/adapters/evidence_readers.py tests/adapters/test_runners.py tests/adapters/test_evidence_readers.py
git commit -m "feat: add allowlisted test runners"
```

### Task 3: Add POSIX resource policy and refactor process execution

**Files:**
- Create: `src/rflp_lite/adapters/test_limits.py`
- Modify: `src/rflp_lite/adapters/test_executor.py`
- Modify: `tests/adapters/test_test_executor.py`

**Interfaces:**
- `make_preexec_fn(limits) -> Callable[[], None] | None` applies `RLIMIT_AS`, `RLIMIT_NOFILE`, and `RLIMIT_CPU` where available.
- `resource_report(limits) -> dict[str, object]` returns deterministic `requested`, sorted `applied`, and sorted `unsupported` fields.
- `RunnerResult` carries `runner`, `command`, process outcome, optional paths, parsed Evidence, diagnostics, resource report, and `cache_hit`.

- [ ] **Step 1: Extend tests before implementation**

Add tests that monkeypatch `resource` availability and verify `resource_report` distinguishes applied and unsupported limits. Add a subprocess test with a small output cap and preserve the current timeout/cleanup assertions.

Run: `.venv/bin/pytest tests/adapters/test_test_executor.py -q`  
Expected: FAIL for the new resource/report assertions while current tests continue to pass.

- [ ] **Step 2: Extract resource setup from the executor**

Keep all platform branching in `test_limits.py`. `make_preexec_fn` must never raise for an unavailable optional limit; it records availability through `resource_report`. Use the existing wall-clock kill path for all platforms.

- [ ] **Step 3: Refactor one-run execution**

Keep `run_project_tests(project_dir, timeout=60, *, runner="pytest", limits=None, cache_dir=None)` as the compatibility entry point. Resolve the runner spec, create a temporary directory, start with `shell=False`, pump bounded stdout/stderr, apply the pre-exec hook, normalize/parse output, and return `RunnerResult`. Do not delete the temp directory in the adapter; the caller owns cleanup.

- [ ] **Step 4: Run adapter regression tests**

Run: `.venv/bin/pytest tests/adapters/test_test_executor.py tests/adapters/test_execution_config.py tests/adapters/test_runners.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/adapters/test_limits.py src/rflp_lite/adapters/test_executor.py tests/adapters/test_test_executor.py
git commit -m "feat: enforce test process resource limits"
```

### Task 4: Add deterministic project fingerprint and cache

**Files:**
- Create: `src/rflp_lite/adapters/test_cache.py`
- Create: `tests/adapters/test_test_cache.py`
- Modify: `src/rflp_lite/adapters/test_executor.py`

**Interfaces:**
- `project_fingerprint(project_dir: Path) -> str` hashes eligible relative paths and bytes using the same hidden/symlink/size/limit policy as the scanner.
- `cache_key(project_dir, runner, limits) -> str` returns `canonical_hash` of the project fingerprint, runner, and normalized limits.
- `load_cached_result(cache_dir, key, runner) -> RunnerResult | None` validates version and returns `None` for missing/corrupt records.
- `save_cached_result(cache_dir, key, result) -> None` writes JSON through a temporary file and `os.replace`.

- [ ] **Step 1: Write cache tests**

```python
def test_cache_hit_requires_same_project_and_limits(tmp_path: Path):
    project = _make_project(tmp_path)
    first_key = cache_key(project, "pytest", build_limits())
    (project / "test_ok.py").write_text("def test_changed():\n    assert True\n", encoding="utf-8")
    second_key = cache_key(project, "pytest", build_limits())
    assert first_key != second_key


def test_corrupt_cache_is_ignored(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "abc.json").write_text("not-json", encoding="utf-8")
    assert load_cached_result(cache_dir, "abc", "pytest") is None
```

Run: `.venv/bin/pytest tests/adapters/test_test_cache.py -q`  
Expected: FAIL because the cache module does not exist.

- [ ] **Step 2: Implement fingerprint and atomic JSON persistence**

Use sorted relative POSIX paths, file bytes, scanner-compatible skips, and a cache format version constant. Serialize Evidence using `asdict`; reconstruct `Evidence` values on load. Do not cache timeout or launch failures. Keep stdout/stderr as bounded diagnostic text, never full unbounded output.

- [ ] **Step 3: Add cache lookup to one-run execution**

When `cache_dir` is supplied, compute the key before starting the process. On valid hit return a result with path fields `None` and `cache_hit=True`; on a normal completed run save the normalized result. Make cache metadata observable but exclude `cache_hit` from execution hashing at the application boundary.

- [ ] **Step 4: Run cache and executor tests**

Run: `.venv/bin/pytest tests/adapters/test_test_cache.py tests/adapters/test_test_executor.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/adapters/test_cache.py src/rflp_lite/adapters/test_executor.py tests/adapters/test_test_cache.py
git commit -m "feat: cache deterministic test results"
```

### Task 5: Add bounded runner matrix and application aggregation

**Files:**
- Modify: `src/rflp_lite/adapters/test_executor.py`
- Modify: `src/rflp_lite/application/project_bridge.py`
- Modify: `tests/application/test_project_bridge.py`
- Create: `tests/application/test_test_matrix.py`

**Interfaces:**
- `run_project_test_matrix(project_dir, runners=("pytest",), limits=None, cache_dir=None, jobs=1) -> tuple[RunnerResult, ...]`.
- `execute_tests_state(state, project_dir, timeout=60, *, runners=("pytest",), limits=None, cache_dir=None, jobs=1) -> tuple[dict, VerifyResult]`.

- [ ] **Step 1: Add matrix and aggregation tests**

Cover two selected runners with `jobs=2`, one failing runner, duplicate runner rejection, cache hit metadata, and a repeated execution whose `canonical_json(execution_without_observation_metadata)` is equal. Keep existing calls without keyword arguments unchanged.

- [ ] **Step 2: Implement bounded matrix execution**

Validate all runner names and jobs before starting any child. Use `ThreadPoolExecutor(max_workers=min(jobs, len(runners)))` only when more than one runner is selected; sort returned results by runner name. Clean each non-cache temp directory in a `finally` block after parsing.

- [ ] **Step 3: Update application state**

Add a small aggregation helper in `project_bridge.py` that converts results into the existing singular fields for one runner and adds `runners`, `runner`, `jobs`, `cache_hit`, `resource_limits`, and per-run diagnostics for multiple runners. Feed the merged Evidence into `_build_execution`. Compute the execution hash from a copy with `cache_hit`, paths, and diagnostic tails removed.

- [ ] **Step 4: Run application tests**

Run: `.venv/bin/pytest tests/application/test_project_bridge.py tests/application/test_test_matrix.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/adapters/test_executor.py src/rflp_lite/application/project_bridge.py tests/application/test_project_bridge.py tests/application/test_test_matrix.py
git commit -m "feat: aggregate bounded test runner matrix"
```

### Task 6: Wire CLI and assess options

**Files:**
- Modify: `src/rflp_lite/interface/cli.py`
- Modify: `tests/interface/test_cli.py`
- Modify: `README.md`

**Interfaces:**
- `project test` and `assess` accept repeated `--runner` choices, `--jobs`, `--memory-mib`, `--max-open-files`, `--output-mib`, `--no-cache`, and existing `--timeout`.

- [ ] **Step 1: Add CLI parser and end-to-end tests**

Test default pytest compatibility, `--runner unittest`, repeated runners with `--jobs 2`, cache hit on the second call, and invalid values returning the existing JSON error with exit code 1.

- [ ] **Step 2: Implement shared CLI option parsing**

Add one helper that converts parsed argparse values to `build_limits`, normalized runner names, jobs, and workspace cache directory. Use `cache_dir=None` for `--no-cache`. Reuse it in both `project test` and `assess` so option behavior cannot drift.

- [ ] **Step 3: Extend JSON output without removing old keys**

Keep `returncode`, `timed_out`, `tests_passed`, `tests_failed`, `resolved`, and `unresolved`; add `runner`, `runners`, `jobs`, `cache_hit`, and `resource_limits`. Record the existing `project.tested` audit event with only bounded summary fields.

- [ ] **Step 4: Update usage documentation**

Document the new flags, safe runner allowlist, resource-limit platform behavior, cache location, and examples for pytest/unittest. State that tests still do not change R/F matching.

- [ ] **Step 5: Run CLI tests**

Run: `.venv/bin/pytest tests/interface/test_cli.py -q`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/interface/cli.py tests/interface/test_cli.py README.md
git commit -m "feat: expose test execution controls in CLI"
```

### Task 7: Wire lightweight Web controls and presentation

**Files:**
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/templates/project-bridge.html`
- Modify: `tests/interface/web/test_project.py`

**Interfaces:**
- `WebFacade.test_workspace_project(workspace_name, runners=("pytest",), limits=None, jobs=1, use_cache=True) -> dict[str, object]`.
- `POST /w/{workspace}/project/test` accepts only form values matching the allowlist and typed limits.

- [ ] **Step 1: Add Web request tests**

Cover default button behavior, `unittest` selection, invalid runner/limit returning 422, and rendering per-runner status/cache/resource fields.

- [ ] **Step 2: Implement facade and route parsing**

Parse form values with small helpers in `routes.py`, call the same `build_limits` and matrix application path as CLI, and keep the source directory from the analyzed project. Do not allow a form field for executable or shell command.

- [ ] **Step 3: Keep the template compact**

Add a small inline configuration row with runner select, timeout, memory, file descriptors, jobs, and cache checkbox. Render one summary row per runner and preserve the existing singular summary fields for default pytest.

- [ ] **Step 4: Run Web tests**

Run: `.venv/bin/pytest tests/interface/web/test_project.py tests/interface/web/test_pages.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/templates/project-bridge.html tests/interface/web/test_project.py
git commit -m "feat: expose safe test controls in web UI"
```

### Task 8: Documentation, packaging, and full verification

**Files:**
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Create: `docs/verification/2026-08-08-multi-runner-resource-limits.md`
- Modify: `README.md` if verification details need a final adjustment

- [ ] **Step 1: Add verification record**

Record commands, runner results, cache hit behavior, resource limit report, parallel run behavior, and platform limitations without including machine-specific paths or timestamps.

- [ ] **Step 2: Update development status**

Mark multi-runner/resource limits/cache/parallel as completed only for the implemented scope and retain explicit non-goals for arbitrary commands, remote execution, cache GC, and Windows hard limits.

- [ ] **Step 3: Run the complete verification suite**

```bash
.venv/bin/pytest -q
.venv/bin/lint-imports
.venv/bin/python -m build
.venv/bin/check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json
```

Expected: all tests pass, 3 import contracts kept, build succeeds, and the profile validates.

- [ ] **Step 4: Inspect repository state**

Run `git status --short --branch` and verify that only intended source/tests/docs commits are present; do not stage the unrelated user documents.

- [ ] **Step 5: Commit final documentation**

```bash
git add docs/DEVELOPMENT_STATUS.md docs/verification/2026-08-08-multi-runner-resource-limits.md README.md
git commit -m "docs: verify multi-runner execution controls"
```

## Plan Self-Review

- The design requirements map to Tasks 1–5; CLI/Web exposure maps to Tasks 6–7; verification and status updates map to Task 8.
- Runner, limits, cache, and process execution have separate adapter boundaries; application code only aggregates `RunnerResult`.
- Existing single-runner signatures and summary keys are explicitly preserved.
- No task accepts arbitrary shell commands or introduces a third-party runtime dependency.
- Cache-hit observability is excluded from the execution hash, matching the design document.
- All code-changing tasks include focused tests and exact verification commands.
