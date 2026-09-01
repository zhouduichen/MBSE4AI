# 1.x/2.x Customer Acceptance Tree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the reduced customer acceptance sample with a complete atomic 1.1/1.2/2.1/2.2 requirement tree and make the executable Gold v3 report prove coverage without claiming 3.x.

**Architecture:** Keep the existing source-anchor matcher and formal gates. Extend the immutable Gold contract with optional tree metadata, derive a deterministic tree summary in the acceptance harness, and keep concept acceptance as the separate 2.1/2.2 evidence path. No new UI flow or external solver is introduced.

**Tech Stack:** Python 3.11+, dataclasses, JSON, pytest, existing CLI/Web acceptance reports.

## Global Constraints

- Only customer functions 1.1, 1.2, 2.1 and 2.2 are in scope; 3.1, 3.2 and 3.3 remain unimplemented.
- Existing v1/v2 Gold callers and minimal v3 test payloads remain readable.
- Formal gates remain precision/recall >= 0.90, detail micro-F1 >= 0.85 when details are supplied, and provenance 100%.
- Source-region IDs remain run-local provenance evidence, never cross-run identities.
- Built-in 2.2 evaluators remain `development_only`.

## File Structure

- Modify `src/rflp_lite/application/acceptance_gold.py`: validate and freeze tree metadata.
- Modify `src/rflp_lite/application/acceptance_harness.py`: produce a deterministic acceptance-tree summary and enforce tree completeness.
- Modify `src/rflp_lite/resources/examples/customer-acceptance/customer-requirements.txt`: atomic 1.1/1.2/2.1/2.2 source corpus only.
- Modify `src/rflp_lite/resources/examples/customer-acceptance/requirements-gold-v3.json`: complete atomic Gold with details and evidence.
- Add `tests/application/test_customer_acceptance_tree.py`: contract and end-to-end regression tests.
- Modify `README.md` and `docs/DEVELOPMENT_STATUS.md`: document the new acceptance scope and realistic document corpus plan.

### Task 1: Extend Gold v3 with tree metadata

**Files:**
- Modify: `src/rflp_lite/application/acceptance_gold.py`
- Test: `tests/application/test_customer_acceptance_tree.py`

**Interfaces:**
- `GoldRequirement` gains `parent_key`, `level`, `area`, `acceptance_method`, and `evidence` with compatibility defaults.
- `GoldContract` gains `tree: tuple[dict[str, object], ...]`.
- `validate_gold_payload()` validates tree child references and returns immutable metadata.

- [ ] **Step 1: Add failing tree validation tests**

```python
def test_gold_tree_rejects_unknown_child_and_duplicate_child():
    with pytest.raises(ContractViolation):
        validate_gold_payload({
            "version": 3,
            "corpus_mode": "complete",
            "details_mode": "complete",
            "tree": [{"key": "1.1", "children": ["REQ-MISSING"]}],
            "requirements": [{
                "key": "REQ-1",
                "statement": "支持导入 Word",
                "source_anchor": "支持导入 Word",
                "details": [],
            }],
        })
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_customer_acceptance_tree.py::test_gold_tree_rejects_unknown_child_and_duplicate_child -q`

Expected: FAIL because tree metadata is not yet part of the Gold contract.

- [ ] **Step 3: Implement backward-compatible tree parsing**

Add optional dataclass fields after the existing required fields. Parse `tree` as a list of objects with non-empty `key`, `title`, and unique `children`; require every child to be a known Gold key, require each child to occur once, and require each child’s `parent_key` to equal its tree parent when supplied. Default absent tree metadata to `()` and absent item metadata to `parent_key=""`, `level=1`, `area=""`, `acceptance_method="document"`, `evidence=()`.

- [ ] **Step 4: Run all Gold tests**

Run: `RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_acceptance_gold.py tests/application/test_customer_acceptance_tree.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/application/acceptance_gold.py tests/application/test_customer_acceptance_tree.py
git commit -m "feat: add atomic acceptance tree contract"
```

### Task 2: Replace the reduced source corpus and Gold

**Files:**
- Modify: `src/rflp_lite/resources/examples/customer-acceptance/customer-requirements.txt`
- Modify: `src/rflp_lite/resources/examples/customer-acceptance/requirements-gold-v3.json`
- Test: `tests/application/test_customer_acceptance_tree.py`

**Interfaces:**
- The source corpus contains one atomic statement per line and no 3.x text.
- The Gold contains the same 29 stable child keys grouped under four tree parents.

- [ ] **Step 1: Add corpus assertions**

```python
def test_customer_corpus_is_atomic_and_excludes_3x():
    text = Path("src/rflp_lite/resources/examples/customer-acceptance/customer-requirements.txt").read_text(encoding="utf-8")
    assert "3.1" not in text and "3.2" not in text and "3.3" not in text
    assert len([line for line in text.splitlines() if line.strip()]) == 29
```

- [ ] **Step 2: Rewrite the corpus and Gold**

Use exact source lines as statements/anchors. Include numeric details for the `3~5` candidate constraint and explicit evidence fields for each atomic record. Keep the Gold threshold and MBSE expectations unchanged.

- [ ] **Step 3: Run the CLI acceptance command**

Run:

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/rflp acceptance --requirements src/rflp_lite/resources/examples/customer-acceptance/customer-requirements.txt --gold src/rflp_lite/resources/examples/customer-acceptance/requirements-gold-v3.json
```

Expected: JSON reports `formal_status=passed`, `matched=29`, `precision=1.0`, `recall=1.0`, and no 3.x key.

- [ ] **Step 4: Commit**

```bash
git add src/rflp_lite/resources/examples/customer-acceptance/customer-requirements.txt src/rflp_lite/resources/examples/customer-acceptance/requirements-gold-v3.json tests/application/test_customer_acceptance_tree.py
git commit -m "test: make customer acceptance corpus atomic"
```

### Task 3: Add acceptance-tree report and gates

**Files:**
- Modify: `src/rflp_lite/application/acceptance_harness.py`
- Test: `tests/application/test_customer_acceptance_tree.py`

**Interfaces:**
- Add `build_acceptance_tree(contract, metrics) -> tuple[dict[str, object], ...]`.
- `run_customer_acceptance()` adds `acceptance_tree` and fails formal status when a declared child is missing or an undeclared actual Gold key is present.

- [ ] **Step 1: Add failing report assertions**

```python
def test_acceptance_report_summarizes_four_parent_nodes():
    report = run_customer_acceptance(...)
    tree = {item["key"]: item for item in report["acceptance_tree"]}
    assert set(tree) == {"1.1", "1.2", "2.1", "2.2"}
    assert all(item["missing"] == [] for item in tree.values())
```

- [ ] **Step 2: Implement deterministic summary**

Use `metrics["requirement_matches"]` to collect matched Gold keys, `metrics["unmatched_expected"]` for missing keys, and `metrics["unmatched_actual"]` for extras. For each tree node return `key`, `title`, `expected`, `matched`, `missing`, `extra`, `status`; use `status="passed"` only when missing and extra are empty.

- [ ] **Step 3: Enforce declared tree coverage**

When a Gold contract declares a tree, append `acceptance_tree_incomplete` to `formal_failures` if any parent status is not passed. Keep smoke behavior unchanged.

- [ ] **Step 4: Run focused and full tests**

Run: `RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_customer_acceptance_tree.py tests/application/test_acceptance_harness.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/application/acceptance_harness.py tests/application/test_customer_acceptance_tree.py
git commit -m "feat: report atomic acceptance tree coverage"
```

### Task 4: Document corpus and delivery boundary

**Files:**
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Add: `docs/verification/2026-09-01-customer-acceptance-tree.md`

**Interfaces:** None.

- [ ] **Step 1: Document the four-function tree and evidence matrix**

State that the shipped Gold is atomic and only covers 1.1/1.2/2.1/2.2; list the planned DOCX table, digital PDF, scanned PDF and complex-indicator corpus variants as verification inputs.

- [ ] **Step 2: Record a reproducible verification command and output fields**

Document the acceptance CLI command, expected `formal_status=passed`, `acceptance_tree` parent keys, and the separate concept command’s `formal_status=development_only`.

- [ ] **Step 3: Run documentation scans**

Run: `rg -n "3\.1|3\.2|3\.3|formal_status|acceptance_tree" README.md docs/DEVELOPMENT_STATUS.md docs/verification/2026-09-01-customer-acceptance-tree.md`

Expected: every 3.x reference says not implemented and every 2.2 reference distinguishes software orchestration from engineering validation.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/DEVELOPMENT_STATUS.md docs/verification/2026-09-01-customer-acceptance-tree.md
git commit -m "docs: define atomic customer acceptance delivery"
```

### Task 5: Final verification

- [ ] **Step 1: Run full test suite**

Run: `RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Run compile and architecture checks**

Run: `python3 -m compileall -q src tests && .venv/bin/python -m pytest tests/architecture -q`

Expected: compile succeeds and all architecture tests pass.

- [ ] **Step 3: Run both acceptance commands**

Run the requirements and concept commands from Tasks 2 and 4. Expected: requirements formal pass; concept software pass with `formal_status=development_only`.

- [ ] **Step 4: Check the diff**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intended source/docs/test changes are tracked.
