# AI4MBSE Layout and MDO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver customer acceptance functions 2.1 and 2.2 with switchable domain packs, 3–5 reproducible feasible layout candidates, three-discipline batch evaluation, and traceable optimization feedback.

**Architecture:** Keep the existing Python monolith, SQLite database, versioned API, Web facade, and CLI. Add one declaration-only JSON domain pack, fixed core domain records, deterministic application services, and replaceable discipline adapters; do not add services, queues, vector databases, or a generic rule engine.

**Tech Stack:** Python 3.11+, standard library `json/csv/sqlite3/ast/random/concurrent.futures`, existing canonical hashing, SQLite repository, FastAPI/Jinja2, pytest, Import Linter, and build.

## Global Constraints

- Customer functions 2.1 and 2.2 are hard requirements; mocks and example-only pages do not constitute formal acceptance.
- Fixed-wing is the first domain pack, but platform core types and tables contain no fixed-wing columns.
- A domain pack is declaration-only JSON and cannot contain executable Python, shell, templates, calls, attributes, or subscripts.
- Projects pin `domain_pack_id + domain_pack_version`; switching either creates a new concept revision and invalidates downstream conclusions without deleting evidence.
- Formal candidates number 3–5 and have 100% hard-constraint satisfaction; infeasible exploration records never fill the formal count.
- Same normalized envelope, domain pack version, reference revisions, generator version, and seed produce the same canonical candidate results.
- Formal evaluation requires aerodynamics, structures, and weight/center-of-gravity. Missing any critical discipline produces `partial`, never `passed`.
- Unapproved built-in evaluators produce development evidence only. Formal acceptance requires customer approval of each evaluator source.
- Surrogates produce formal output only inside their registered validity domain and below their registered validation-error threshold.
- Existing requirements, MBSE, RFLP, project bridge, API, CLI, and Web behavior remains additive-compatible.
- No new runtime dependency is required for M3–M4.
- Every task ends with focused tests and a separate commit.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/rflp_lite/domain/concept_design.py` | Fixed core records for packs, schemes, envelopes, candidates, evaluations, and optimization |
| `src/rflp_lite/application/domain_packs.py` | Pack loading, normalization, validation, version identity, and core-field protection |
| `src/rflp_lite/resources/domain-packs/fixed-wing-v1.json` | First declaration-only domain pack |
| `src/rflp_lite/adapters/scheme_sources.py` | JSON, CSV, and read-only SQLite row readers |
| `src/rflp_lite/application/scheme_library.py` | Field mapping, extensions, import diagnostics, and scheme records |
| `src/rflp_lite/application/parameter_rules.py` | Unit normalization, safe arithmetic formulas, constraints, and envelope validation |
| `src/rflp_lite/application/scheme_retrieval.py` | Deterministic weighted normalized similarity |
| `src/rflp_lite/application/layout_generation.py` | Reference-guided deterministic generation and diversity filtering |
| `src/rflp_lite/application/layout_render.py` | Deterministic fixed-wing SVG adapter selected by the pack |
| `src/rflp_lite/ports/discipline.py` | Discipline adapter and evaluation-store protocols |
| `src/rflp_lite/adapters/disciplines.py` | Built-in aerodynamic, structural, and weight/balance evaluators |
| `src/rflp_lite/application/discipline_batch.py` | Cache, bounded concurrency, timeouts, failure isolation, and surrogate gates |
| `src/rflp_lite/application/multidisciplinary_optimization.py` | Objective extraction, Pareto ranking, bounded iteration, and trace records |
| `src/rflp_lite/application/concept_design_service.py` | End-to-end orchestration independent of Web/API/CLI |
| `src/rflp_lite/application/concept_acceptance.py` | Executable 2.1/2.2 acceptance report |
| `src/rflp_lite/adapters/sqlite_repository.py` | JSON-record persistence and evaluation cache |
| `src/rflp_lite/application/web_facade.py` | Workspace transaction boundary for concept design |
| `src/rflp_lite/interface/web/api_v1.py` | Versioned concept-design API |
| `src/rflp_lite/interface/web/routes.py` | Concept-design page actions and downloads |
| `src/rflp_lite/interface/web/templates/concept-design.html` | One-page M3–M4 workflow |
| `src/rflp_lite/interface/web/templates/base.html` | Navigation entry |
| `src/rflp_lite/interface/cli.py` | `concept import/run/export/acceptance` commands |

### Task 1: Add fixed core records and a declaration-only domain pack

**Files:**

- Create: `src/rflp_lite/domain/concept_design.py`
- Create: `src/rflp_lite/application/domain_packs.py`
- Create: `src/rflp_lite/resources/domain-packs/fixed-wing-v1.json`
- Modify: `src/rflp_lite/domain/__init__.py`
- Modify: `pyproject.toml`
- Test: `tests/domain/test_concept_design.py`
- Test: `tests/application/test_domain_packs.py`

**Interfaces:**

- Consumes: `canonical_hash(value)` and `ContractViolation`.
- Produces: `SchemeRecord`, `IndicatorEnvelope`, `ConstraintResult`, `SimilarityMatch`, `LayoutCandidate`, `DisciplineEvaluation`, `OptimizationRun`, `validate_domain_pack(payload)`, and `load_domain_pack(path)`.

- [ ] **Step 1: Write failing domain and pack tests**

```python
from pathlib import Path
import pytest

from rflp_lite.application.domain_packs import load_domain_pack, validate_domain_pack
from rflp_lite.domain.errors import ContractViolation


def test_fixed_wing_pack_is_versioned_and_has_three_disciplines():
    pack = load_domain_pack(Path("src/rflp_lite/resources/domain-packs/fixed-wing-v1.json"))
    assert (pack["id"], pack["version"], pack["id_prefix"]) == ("fixed-wing", 1, "FW")
    assert {item["id"] for item in pack["disciplines"]} == {
        "aerodynamics", "structures", "weight_balance"
    }


def test_pack_rejects_executable_formula_and_core_override():
    payload = {
        "id": "bad", "version": 1, "object_type": "layout", "id_prefix": "B",
        "parameters": [],
        "derived_parameters": [{"name": "x", "formula": "__import__('os').system('id')", "unit": "1"}],
        "constraints": [], "mappings": {"customer_id": {"parameter": "id"}},
        "retrieval": {"features": []}, "generation": {}, "objectives": [], "disciplines": [],
    }
    with pytest.raises(ContractViolation, match="formula|core field"):
        validate_domain_pack(payload)
```

- [ ] **Step 2: Run tests and confirm collection failure**

Run: `.venv/bin/pytest -q tests/domain/test_concept_design.py tests/application/test_domain_packs.py`
Expected: FAIL because the modules do not exist.

- [ ] **Step 3: Implement immutable records**

```python
from __future__ import annotations


@dataclass(frozen=True, slots=True)
class SchemeRecord:
    id: str
    object_type: str
    schema_version: int
    domain_pack_id: str
    domain_pack_version: int
    revision: int
    status: str
    source: str
    parameters: tuple[tuple[str, object], ...]
    extensions: tuple[tuple[str, object], ...]
    content_hash: str


@dataclass(frozen=True, slots=True)
class LayoutCandidate:
    id: str
    envelope_id: str
    domain_pack_id: str
    domain_pack_version: int
    reference_ids: tuple[str, ...]
    similarity_matches: tuple[SimilarityMatch, ...]
    parameters: tuple[tuple[str, object], ...]
    parameter_sources: tuple[tuple[str, str], ...]
    geometry: tuple[tuple[str, object], ...]
    svg: str
    constraints: tuple[ConstraintResult, ...]
    feasible: bool
    infeasible_reasons: tuple[str, ...]
    status: str
    generator_version: str
    seed: int
    input_hash: str
    result_hash: str
```

Define the other records explicitly; these field names are the cross-task contract:

```python
@dataclass(frozen=True, slots=True)
class IndicatorEnvelope:
    id: str
    object_type: str
    schema_version: int
    domain_pack_id: str
    domain_pack_version: int
    revision: int
    status: str
    source_requirement_ids: tuple[str, ...]
    parameters: tuple[tuple[str, object], ...]
    bounds: tuple[tuple[str, float, float], ...]
    input_hash: str


@dataclass(frozen=True, slots=True)
class ConstraintResult:
    id: str
    candidate_id: str
    constraint_id: str
    severity: str
    actual: float
    operator: str
    limit: float
    margin: float
    passed: bool
    message: str


@dataclass(frozen=True, slots=True)
class SimilarityMatch:
    scheme_id: str
    similarity: float
    feature_differences: tuple[tuple[str, float], ...]
    missing_features: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DisciplineEvaluation:
    id: str
    candidate_id: str
    discipline: str
    adapter_id: str
    adapter_version: str
    source_kind: str
    input_hash: str
    output_hash: str
    metrics: tuple[tuple[str, object], ...]
    status: str
    evidence_status: str
    validity: tuple[tuple[str, object], ...]
    diagnostics: tuple[str, ...]
    log_ref: str


@dataclass(frozen=True, slots=True)
class OptimizationRun:
    id: str
    envelope_id: str
    domain_pack_id: str
    domain_pack_version: int
    candidate_ids: tuple[str, ...]
    evaluation_ids: tuple[str, ...]
    iteration_records: tuple[tuple[str, object], ...]
    front_candidate_ids: tuple[str, ...]
    seed: int
    stop_reason: str
    input_hash: str
    result_hash: str
    status: str
    evidence_status: str
```

Add `from_payload` helpers only where they remove repeated tuple conversion; do not add factories or inheritance.

- [ ] **Step 4: Implement pack validation**

```python
_REQUIRED = {
    "id", "version", "object_type", "id_prefix", "parameters",
    "derived_parameters", "constraints", "mappings", "retrieval",
    "generation", "objectives", "disciplines",
}
_ALLOWED = _REQUIRED | {"schema_version", "display_name", "description"}
_CORE_FIELDS = {
    "id", "object_type", "schema_version", "domain_pack_id",
    "domain_pack_version", "revision", "status", "source", "content_hash",
    "input_hash", "result_hash", "evidence_status", "formal_status",
    "generator_version", "seed", "parameters", "extensions",
}


def validate_domain_pack(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ContractViolation("domain pack must be an object")
    keys = set(payload)
    if not _REQUIRED <= keys or keys - _ALLOWED:
        raise ContractViolation("domain pack fields are invalid")
    if any(item["parameter"] in _CORE_FIELDS for item in payload["mappings"].values()):
        raise ContractViolation("domain pack cannot override a core field")
    # Validate unique parameter/constraint/discipline IDs and formula syntax.
    return json.loads(canonical_json(payload))
```

Use `ast.parse(formula, mode="eval")` during validation and accept only numeric constants, parameter names, `+ - * / **`, and unary `+/-` nodes. Validate exact allowlists for every nested parameter, mapping, constraint, objective, generation, retrieval, and discipline object; reject unknown keys such as `formal_approved`. Cap parameters at 500, mappings at 1,000, constraints at 500, disciplines at 20, generation attempts at 10,000, and configured timeout at 3,600 seconds.

- [ ] **Step 5: Create the fixed-wing pack**

Define parameters required by the three transparent evaluators:

```text
mass_kg, payload_kg, wing_area_m2, span_m, fuselage_length_m,
cruise_speed_mps, air_density_kg_m3, cd0, oswald_efficiency,
load_factor, section_modulus_m3, allowable_stress_pa, cg_x_m
```

Use these development bounds/defaults; they are fixture assumptions, not customer-certified engineering limits:

| Parameter | Unit | Required | Minimum | Maximum | Default |
|---|---:|---:|---:|---:|---:|
| `mass_kg` | kg | yes | 100 | 2,000 | — |
| `payload_kg` | kg | yes | 0 | 1,000 | — |
| `wing_area_m2` | m² | yes | 5 | 100 | — |
| `span_m` | m | yes | 5 | 30 | — |
| `fuselage_length_m` | m | yes | 3 | 20 | — |
| `cruise_speed_mps` | m/s | yes | 30 | 150 | — |
| `air_density_kg_m3` | kg/m³ | no | 0.5 | 1.5 | 1.225 |
| `cd0` | 1 | no | 0.01 | 0.08 | 0.025 |
| `oswald_efficiency` | 1 | no | 0.5 | 0.95 | 0.8 |
| `load_factor` | 1 | no | 1 | 9 | 3.5 |
| `section_modulus_m3` | m³ | yes | 0.0001 | 0.1 | — |
| `allowable_stress_pa` | Pa | yes | 10,000,000 | 1,000,000,000 | — |
| `cg_x_m` | m | yes | 0 | 20 | — |

Declare derived parameters `total_mass_kg = mass_kg + payload_kg`, `aspect_ratio = span_m ** 2 / wing_area_m2`, and `cg_fraction = cg_x_m / fuselage_length_m`. Add hard constraints `4 <= aspect_ratio <= 14` and `0.15 <= cg_fraction <= 0.45`; envelope-specific bounds remain additional hard constraints. Include source aliases for the English names plus `空机质量→mass_kg`, `任务载荷→payload_kg`, `机翼面积→wing_area_m2`, `翼展→span_m`, `机身长度→fuselage_length_m`, and `巡航速度→cruise_speed_mps`.

Set generation to `candidate_count_min=3`, `candidate_count_max=5`, `max_attempts=200`, `minimum_distance=0.08`, and `seed=42`. Configure objectives `aerodynamics.lift_to_drag=maximize`, `structures.stress_margin=maximize`, and `weight_balance.total_mass_kg=minimize`.

- [ ] **Step 6: Run tests and architecture checks**

Run: `.venv/bin/pytest -q tests/domain/test_concept_design.py tests/application/test_domain_packs.py && .venv/bin/lint-imports`
Expected: PASS; 3 import contracts kept.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/rflp_lite/domain/concept_design.py src/rflp_lite/domain/__init__.py src/rflp_lite/application/domain_packs.py src/rflp_lite/resources/domain-packs/fixed-wing-v1.json tests/domain/test_concept_design.py tests/application/test_domain_packs.py
git commit -m "feat: add versioned concept design domain packs"
```

### Task 2: Import JSON, CSV, and read-only SQLite historical schemes

**Files:**

- Create: `src/rflp_lite/adapters/scheme_sources.py`
- Create: `src/rflp_lite/application/scheme_library.py`
- Modify: `src/rflp_lite/adapters/sqlite_repository.py`
- Test: `tests/adapters/test_scheme_sources.py`
- Test: `tests/application/test_scheme_library.py`
- Test: `tests/adapters/test_sqlite_repository.py`

**Interfaces:**

- Consumes: validated pack dictionaries and `SchemeRecord`.
- Produces: `read_scheme_rows(filename, content)`, `read_sqlite_scheme_rows(path, table)`, `import_scheme_rows(pack, rows, source)`, `SchemeImportResult`, and SQLite save/load methods.

`SchemeImportResult` is the exact batch boundary:

```python
@dataclass(frozen=True, slots=True)
class SchemeImportResult:
    records: tuple[SchemeRecord, ...]
    rejected: tuple[dict[str, object], ...]
```

- [ ] **Step 1: Write failing source-reader tests**

```python
def test_csv_and_json_readers_return_row_objects():
    csv_rows = read_scheme_rows("schemes.csv", b"name,mass_kg\nA,120\n")
    json_rows = read_scheme_rows("schemes.json", b'[{"name":"B","mass_kg":130}]')
    assert csv_rows == ({"name": "A", "mass_kg": "120"},)
    assert json_rows == ({"mass_kg": 130, "name": "B"},)


def test_sqlite_reader_rejects_unsafe_table_name(tmp_path):
    with pytest.raises(AdapterFailure, match="table"):
        read_sqlite_scheme_rows(tmp_path / "source.db", "schemes; DROP TABLE schemes")
```

- [ ] **Step 2: Write failing mapping tests**

```python
def test_import_maps_aliases_and_preserves_unknown_fields(pack):
    batch = import_scheme_rows(
        pack,
        ({"方案名称": "A", "空机质量": "120", "客户备注": "baseline"},),
        "customer.csv:2",
    )
    record = batch.records[0]
    assert dict(record.parameters)["mass_kg"] == 120.0
    assert dict(record.extensions)["客户备注"] == "baseline"
    assert record.id.startswith("FW-S-")
    assert batch.rejected == ()


def test_invalid_rows_are_isolated_without_losing_valid_rows(pack):
    batch = import_scheme_rows(pack, ({"mass_kg": "bad"}, {"mass_kg": "120"}), "x.csv")
    assert len(batch.records) == 1
    assert batch.rejected[0]["row"] == 1


def test_same_pack_id_and_version_cannot_change_content(repository, pack):
    repository.save_domain_pack(pack)
    changed = {**pack, "id_prefix": "ALT"}
    with pytest.raises(ContractViolation, match="version"):
        repository.save_domain_pack(changed)
```

- [ ] **Step 3: Implement standard-library readers**

Use `csv.DictReader`, `json.loads`, and read-only SQLite URI mode:

```python
connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
```

Allow only table names matching `^[A-Za-z_][A-Za-z0-9_]{0,63}$`. Reject empty files, non-array JSON, non-object rows, more than 50,000 rows, and files over 50 MiB.

- [ ] **Step 4: Implement field mapping and revision identity**

Each mapping is keyed by customer source field and contains `parameter`, optional `source_unit`, optional `scale`, optional `default`, and `null_policy`. Resolve it from `pack["mappings"]`, parse declared `number/string/boolean` types, place unknown keys in `extensions`, and build IDs as:

```python
identity = (pack["id"], pack["version"], source, row_number, parameters)
record_id = f"{pack['id_prefix']}-S-{canonical_hash(identity)[:12]}"
```

Rejected records are dictionaries with `row`, `source`, `code`, and `message`; they are never persisted as schemes.

- [ ] **Step 5: Add SQLite payload tables and methods**

Add `domain_packs`, `scheme_records`, `indicator_envelopes`, `layout_candidates`, `discipline_evaluations`, and `optimization_runs` to `_TABLES`. Add explicit methods using existing `_save_payloads` and a shared `_load_payloads(table)`:

```python
def save_scheme_records(self, values: tuple[dict[str, object], ...]) -> None: ...
def scheme_records(self) -> tuple[dict[str, object], ...]: ...
def save_layout_candidates(self, values: tuple[dict[str, object], ...]) -> None: ...
def save_discipline_evaluations(self, values: tuple[dict[str, object], ...]) -> None: ...
```

`save_domain_pack` stores the canonical content hash and rejects a different hash for an existing `(id, version)`. Therefore mapping, field, unit, constraint, adapter, or ID-prefix changes require incrementing the pack version; old records remain reproducible.

- [ ] **Step 6: Run focused tests**

Run: `.venv/bin/pytest -q tests/adapters/test_scheme_sources.py tests/application/test_scheme_library.py tests/adapters/test_sqlite_repository.py`
Expected: PASS, including transaction rollback.

- [ ] **Step 7: Commit**

```bash
git add src/rflp_lite/adapters/scheme_sources.py src/rflp_lite/application/scheme_library.py src/rflp_lite/adapters/sqlite_repository.py tests/adapters/test_scheme_sources.py tests/application/test_scheme_library.py tests/adapters/test_sqlite_repository.py
git commit -m "feat: import versioned historical scheme data"
```

### Task 3: Normalize units, derive parameters, and enforce constraints

**Files:**

- Create: `src/rflp_lite/application/parameter_rules.py`
- Test: `tests/application/test_parameter_rules.py`

**Interfaces:**

- Consumes: validated packs and raw envelope dictionaries.
- Produces: `normalize_parameters(pack, values)`, `evaluate_formula(formula, values)`, `evaluate_constraints(pack, values, candidate_id)`, and `create_indicator_envelope(pack, payload, source_requirement_ids)`.

- [ ] **Step 1: Write failing safety and unit tests**

```python
def test_unit_normalization_and_safe_formula():
    values = normalize_parameters(pack, {"span_m": {"value": 1200, "unit": "mm"}})
    assert values["span_m"] == 1.2
    assert evaluate_formula("span_m ** 2 / wing_area_m2", {"span_m": 10.0, "wing_area_m2": 20.0}) == 5.0


@pytest.mark.parametrize("formula", ["open('x')", "x.__class__", "x[0]"])
def test_formula_rejects_execution_features(formula):
    with pytest.raises(ContractViolation, match="formula"):
        evaluate_formula(formula, {"x": 1})
```

- [ ] **Step 2: Write failing constraint tests**

```python
def test_hard_constraint_reports_value_limit_margin_and_status(pack):
    results = evaluate_constraints(pack, {"mass_kg": 900.0, "max_mass_kg": 1000.0}, "candidate-1")
    result = next(item for item in results if item.constraint_id == "max-mass")
    assert (result.actual, result.limit, result.margin, result.passed) == (900.0, 1000.0, 100.0, True)


def test_conflicting_envelope_is_rejected(pack):
    with pytest.raises(ContractViolation, match="minimum.*maximum"):
        create_indicator_envelope(pack, {"mass_kg": {"minimum": 1000, "maximum": 900}}, ())
```

- [ ] **Step 3: Implement the arithmetic allowlist**

Walk the parsed AST recursively. Accept `Expression`, `BinOp`, `UnaryOp`, `Name`, numeric `Constant`, `Add`, `Sub`, `Mult`, `Div`, `Pow`, `UAdd`, and `USub`; reject all other node classes before evaluation. Cap formulas at 64 AST nodes, exponent magnitude at 8, and require every intermediate/final numeric result to be finite. Evaluate recursively without calling Python `eval`.

- [ ] **Step 4: Implement the minimal unit table**

Support exact conversions used by the first pack:

```python
_UNIT_SCALE = {
    ("mm", "m"): 0.001, ("cm", "m"): 0.01,
    ("g", "kg"): 0.001, ("kPa", "Pa"): 1000.0,
    ("km/h", "m/s"): 1 / 3.6,
}
```

Equal units use scale `1`. Unknown pairs raise `ContractViolation("unsupported unit conversion: ...")`.

- [ ] **Step 5: Implement envelope and constraints**

Support operators `==`, `!=`, `<`, `<=`, `>`, `>=`. Resolve right-hand operands from either `{"value": ...}` or `{"parameter": "..."}`. A hard constraint with a missing operand fails validation; a soft constraint records a failed result but does not make the candidate infeasible.

- [ ] **Step 6: Run tests and commit**

Run: `.venv/bin/pytest -q tests/application/test_parameter_rules.py`
Expected: PASS.

```bash
git add src/rflp_lite/application/parameter_rules.py tests/application/test_parameter_rules.py
git commit -m "feat: validate concept parameters and constraints"
```

### Task 4: Retrieve similar historical schemes with explanations

**Files:**

- Create: `src/rflp_lite/application/scheme_retrieval.py`
- Test: `tests/application/test_scheme_retrieval.py`

**Interfaces:**

- Consumes: pack retrieval features, `IndicatorEnvelope`, and `SchemeRecord` values.
- Produces: `find_similar_schemes(pack, envelope, schemes, limit=5) -> tuple[SimilarityMatch, ...]`.

- [ ] **Step 1: Write failing ranking and explanation tests**

```python
def test_similarity_is_deterministic_and_explained(pack, envelope, schemes):
    first = find_similar_schemes(pack, envelope, schemes, limit=3)
    second = find_similar_schemes(pack, envelope, tuple(reversed(schemes)), limit=3)
    assert first == second
    assert first[0].scheme_id == "scheme-nearest"
    assert dict(first[0].feature_differences)["mass_kg"] == pytest.approx(0.02)
    assert 0.0 <= first[0].similarity <= 1.0
```

- [ ] **Step 2: Implement weighted normalized distance**

For numeric features use `abs(actual-target)/(maximum-minimum)`, capped at `1`. For enums use `0` or `1`. Ignore no feature silently: a missing feature contributes distance `1` and its name is added to `SimilarityMatch.missing_features`.

Sort by `(-similarity, scheme_id)` so input row order cannot alter results.

- [ ] **Step 3: Run tests and commit**

Run: `.venv/bin/pytest -q tests/application/test_scheme_retrieval.py`
Expected: PASS.

```bash
git add src/rflp_lite/application/scheme_retrieval.py tests/application/test_scheme_retrieval.py
git commit -m "feat: retrieve explainable similar schemes"
```

### Task 5: Generate 3–5 feasible, diverse candidates and SVG sketches

**Files:**

- Create: `src/rflp_lite/application/layout_generation.py`
- Create: `src/rflp_lite/application/layout_render.py`
- Create: `src/rflp_lite/resources/examples/concept-design/fixed-wing-schemes.json`
- Create: `src/rflp_lite/resources/examples/concept-design/fixed-wing-envelope.json`
- Modify: `pyproject.toml`
- Test: `tests/application/test_layout_generation.py`
- Test: `tests/application/test_layout_render.py`

**Interfaces:**

- Consumes: normalized envelope, similarity matches, scheme records, and parameter rules.
- Produces: `generate_layout_candidates(pack, envelope, schemes, matches, seed=None)`, `candidate_distance(pack, left, right)`, and `render_layout_svg(pack, candidate)`.

- [ ] **Step 1: Write the hard acceptance test**

```python
def test_generator_returns_three_to_five_feasible_diverse_candidates(pack, envelope, schemes):
    matches = find_similar_schemes(pack, envelope, schemes)
    candidates = generate_layout_candidates(pack, envelope, schemes, matches)
    assert 3 <= len(candidates) <= 5
    assert all(item.feasible and item.status == "feasible" for item in candidates)
    assert all(all(result.passed for result in item.constraints if result.severity == "hard") for item in candidates)
    for index, left in enumerate(candidates):
        for right in candidates[index + 1:]:
            assert candidate_distance(pack, left, right) >= 0.08
```

- [ ] **Step 2: Write determinism and insufficient-feasibility tests**

```python
def test_same_inputs_and_seed_have_same_result_hashes(pack, envelope, schemes):
    args = (pack, envelope, schemes, find_similar_schemes(pack, envelope, schemes))
    assert [x.result_hash for x in generate_layout_candidates(*args, seed=42)] == [
        x.result_hash for x in generate_layout_candidates(*args, seed=42)
    ]


def test_generator_does_not_fill_shortfall_with_infeasible_items(pack, impossible_envelope, schemes):
    result = generate_layout_candidates(pack, impossible_envelope, schemes, (), seed=42)
    assert result == ()
```

- [ ] **Step 3: Implement reference-guided bounded generation**

Use `random.Random(seed)` only. Copy fixed envelope values, fill missing values from the selected reference, perturb configurable numeric and enum parameters, derive formulas, evaluate constraints, and keep only feasible candidates separated by `minimum_distance`. Stop at `candidate_count_max` or `max_attempts`.

Candidate hashes include normalized envelope, pack ID/version, reference revisions, generator version `layout-generator-v1`, and seed. Candidate IDs use `f"{pack['id_prefix']}-C-{result_hash[:12]}"`; changing the declared prefix and incrementing the pack version therefore changes display IDs without changing database columns or core code.

- [ ] **Step 4: Implement deterministic fixed-wing SVG**

Dispatch only the allowlisted renderer name `fixed-wing-svg-v1`. Build top and side views from `span_m`, `wing_area_m2`, and `fuselage_length_m`; calculate chord as `wing_area_m2/span_m`. Escape labels and use a fixed view box. Unknown renderers raise `ContractViolation`.

- [ ] **Step 5: Run focused and acceptance tests**

Run: `.venv/bin/pytest -q tests/application/test_layout_generation.py tests/application/test_layout_render.py`
Expected: PASS with 3–5 candidates and byte-identical repeated SVG.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/rflp_lite/application/layout_generation.py src/rflp_lite/application/layout_render.py src/rflp_lite/resources/examples/concept-design/fixed-wing-schemes.json src/rflp_lite/resources/examples/concept-design/fixed-wing-envelope.json tests/application/test_layout_generation.py tests/application/test_layout_render.py
git commit -m "feat: generate feasible layout candidates"
```

### Task 6: Add three transparent discipline adapters

**Files:**

- Create: `src/rflp_lite/ports/discipline.py`
- Create: `src/rflp_lite/adapters/disciplines.py`
- Test: `tests/adapters/test_disciplines.py`

**Interfaces:**

- Consumes: `LayoutCandidate` and discipline config dictionaries.
- Produces: `DisciplineAdapter`, `EvaluationStorePort`, `discipline_registry()`, `AerodynamicsAdapter`, `StructuresAdapter`, and `WeightBalanceAdapter`.

```python
class DisciplineAdapter(Protocol):
    id: str
    version: str
    source_kind: str

    def evaluate(
        self, candidate: LayoutCandidate, profile: dict[str, object]
    ) -> DisciplineEvaluation: ...


class EvaluationStorePort(Protocol):
    def load_discipline_evaluation(
        self, cache_key: str
    ) -> DisciplineEvaluation | None: ...

    def save_discipline_evaluation(
        self, cache_key: str, value: DisciplineEvaluation
    ) -> None: ...
```

The profile supplies `timeout_seconds`. Registered subprocess adapters must call `subprocess.run(..., timeout=timeout_seconds, shell=False)` and convert `TimeoutExpired` to a timeout evaluation; in-process adapters are limited to trusted built-ins and surrogate wrappers.

- [ ] **Step 1: Write failing adapter-contract tests**

```python
@pytest.mark.parametrize("adapter_id", [
    "builtin.aerodynamics.v1", "builtin.structures.v1", "builtin.weight-balance.v1"
])
def test_builtin_adapter_returns_versioned_metrics(adapter_id, candidate):
    result = discipline_registry()[adapter_id].evaluate(candidate, {})
    assert result.status == "succeeded"
    assert result.adapter_id == adapter_id
    assert result.source_kind == "analytical"
    assert result.input_hash and result.output_hash
```

- [ ] **Step 2: Implement weight/balance formulas**

```text
total_mass_kg = mass_kg + payload_kg
cg_fraction = cg_x_m / fuselage_length_m
```

Return metrics `weight_balance.total_mass_kg` and `weight_balance.cg_fraction`.

- [ ] **Step 3: Implement aerodynamic formulas**

```text
aspect_ratio = span_m² / wing_area_m2
dynamic_pressure = 0.5 × air_density_kg_m3 × cruise_speed_mps²
cl = total_mass_kg × 9.80665 / (dynamic_pressure × wing_area_m2)
cd = cd0 + cl² / (π × oswald_efficiency × aspect_ratio)
lift_to_drag = cl / cd
```

Return `aerodynamics.aspect_ratio`, `aerodynamics.cl`, `aerodynamics.cd`, and `aerodynamics.lift_to_drag`.

- [ ] **Step 4: Implement structural formulas**

```text
root_bending_moment_nm = load_factor × total_mass_kg × 9.80665 × span_m / 4
stress_pa = root_bending_moment_nm / section_modulus_m3
stress_margin = allowable_stress_pa / stress_pa - 1
```

Return the three namespaced metrics. Missing, non-numeric, zero, or negative required inputs return a failed evaluation with a precise diagnostic; they do not raise past the adapter boundary.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/pytest -q tests/adapters/test_disciplines.py && .venv/bin/lint-imports`
Expected: PASS; application code depends only on the port, not this adapter module.

```bash
git add src/rflp_lite/ports/discipline.py src/rflp_lite/adapters/disciplines.py tests/adapters/test_disciplines.py
git commit -m "feat: add transparent multidisciplinary evaluators"
```

### Task 7: Batch evaluations with cache, timeout, isolation, and surrogate gates

**Files:**

- Create: `src/rflp_lite/application/discipline_batch.py`
- Modify: `src/rflp_lite/adapters/sqlite_repository.py`
- Test: `tests/application/test_discipline_batch.py`
- Test: `tests/adapters/test_sqlite_repository.py`

**Interfaces:**

- Consumes: candidates, pack discipline profiles, a separately supplied evaluator-approval profile, a `dict[str, DisciplineAdapter]`, and `EvaluationStorePort`.
- Produces: `validate_evaluator_profile(payload)`, `evaluate_candidates(candidates, pack, evaluator_profile, registry, store, max_workers=3) -> EvaluationBatch`, and `surrogate_is_valid(profile, parameters)`.

```python
@dataclass(frozen=True, slots=True)
class EvaluationBatch:
    evaluations: tuple[DisciplineEvaluation, ...]
    candidate_status: dict[str, str]
    candidate_formal_status: dict[str, str]
    cache_hits: int
```

- [ ] **Step 1: Write failure-isolation and cache tests**

```python
def test_one_adapter_failure_does_not_cancel_other_tasks(candidate, pack, evaluator_profile, store):
    registry = {**working_registry(), "builtin.structures.v1": FailingAdapter()}
    batch = evaluate_candidates((candidate,), pack, evaluator_profile, registry, store, max_workers=3)
    by_discipline = {item.discipline: item for item in batch.evaluations}
    assert by_discipline["structures"].status == "failed"
    assert by_discipline["aerodynamics"].status == "succeeded"
    assert batch.candidate_status[candidate.id] == "partial"


def test_second_identical_batch_uses_cache(candidate, pack, evaluator_profile, counting_registry, store):
    evaluate_candidates((candidate,), pack, evaluator_profile, counting_registry, store)
    second = evaluate_candidates((candidate,), pack, evaluator_profile, counting_registry, store)
    assert all(item.status == "cached" for item in second.evaluations)
    assert sum(adapter.calls for adapter in counting_registry.values()) == 3


def test_domain_pack_cannot_self_approve_formal_evidence(pack):
    pack["disciplines"][0]["formal_approved"] = True
    with pytest.raises(ContractViolation, match="formal_approved"):
        validate_domain_pack(pack)


def test_adapter_timeout_is_isolated(candidate, pack, evaluator_profile, store):
    registry = {**working_registry(), "builtin.structures.v1": TimeoutAdapter()}
    batch = evaluate_candidates((candidate,), pack, evaluator_profile, registry, store)
    structure = next(x for x in batch.evaluations if x.discipline == "structures")
    assert structure.status == "timeout"
    assert batch.candidate_status[candidate.id] == "partial"
```

- [ ] **Step 2: Write surrogate-gate tests**

```python
def test_surrogate_outside_domain_uses_fallback(candidate, pack, evaluator_profile, store):
    pack["disciplines"][0].update({
        "adapter": "surrogate.aero.v1",
        "validity_domain": {"mass_kg": {"minimum": 100, "maximum": 200}},
        "validation_error": 0.03,
        "maximum_error": 0.05,
        "fallback_adapter": "builtin.aerodynamics.v1",
    })
    result = evaluate_candidates(
        (candidate,), pack, evaluator_profile, registry_with_surrogate(), store
    )
    aero = next(item for item in result.evaluations if item.discipline == "aerodynamics")
    assert aero.adapter_id == "builtin.aerodynamics.v1"


def test_surrogate_over_error_threshold_cannot_be_formal(profile):
    profile.update({"validation_error": 0.08, "maximum_error": 0.05})
    assert surrogate_is_valid(profile, {"mass_kg": 150.0}) is False
```

- [ ] **Step 3: Implement deterministic cache keys and bounded concurrency**

```python
cache_key = canonical_hash({
    "candidate": candidate.result_hash,
    "discipline": discipline["id"],
    "adapter": adapter.id,
    "adapter_version": adapter.version,
    "profile": discipline,
    "approval_profile_id": evaluator_profile["id"],
    "approval_profile_version": evaluator_profile["version"],
})
```

Use `ThreadPoolExecutor(max_workers=min(max_workers, 8))`. Submit independent candidate/discipline tasks, convert exceptions to failed evaluations, and gather in sorted `(candidate_id, discipline)` order. Reject `max_workers < 1`.

- [ ] **Step 4: Enforce formal-result source policy outside the domain pack**

The domain pack selects adapters but cannot approve them. Load approval from a separate evaluator profile with `id`, `version`, and `approvals[adapter_id] = {adapter_version, approved_for_formal, basis, approved_by, approved_at}`. `candidate_status` is numerical completeness (`complete|partial`); `candidate_formal_status` is the independent evidence gate (`passed|development|partial`). An unapproved source remains numerically available for development optimization but cannot become formally passed. Reject attempts to place `formal_approved` inside a domain pack so changing business fields cannot bypass the evidence gate.

- [ ] **Step 5: Persist cache entries**

Implement `load_discipline_evaluation(cache_key)` and save each evaluation under both its ID and cache key metadata. Cache only complete `succeeded` results; never cache `failed`, `timeout`, or partial output.

- [ ] **Step 6: Run tests and commit**

Run: `.venv/bin/pytest -q tests/application/test_discipline_batch.py tests/adapters/test_sqlite_repository.py`
Expected: PASS.

```bash
git add src/rflp_lite/application/discipline_batch.py src/rflp_lite/adapters/sqlite_repository.py tests/application/test_discipline_batch.py tests/adapters/test_sqlite_repository.py
git commit -m "feat: batch multidisciplinary evaluations safely"
```

### Task 8: Add Pareto ranking and bounded optimization feedback

**Files:**

- Create: `src/rflp_lite/application/multidisciplinary_optimization.py`
- Test: `tests/application/test_multidisciplinary_optimization.py`

**Interfaces:**

- Consumes: feasible candidates, complete evaluations, objective definitions, and the existing generator/evaluator callables.
- Produces: `objective_vector(candidate_id, evaluations, objectives)`, `pareto_front(vectors, objectives)`, `rank_evaluated_candidates(candidates, evaluations, objectives)`, and `run_optimization(pack, evaluator_profile, initial_candidates, initial_evaluations, generate, evaluate, iterations, evaluation_budget, base_seed) -> OptimizationResult`.

```python
@dataclass(frozen=True, slots=True)
class OptimizationResult:
    run: OptimizationRun
    candidates: tuple[LayoutCandidate, ...]
    evaluations: tuple[DisciplineEvaluation, ...]
```

- [ ] **Step 1: Write failing Pareto tests**

```python
def test_pareto_front_keeps_non_dominated_candidates():
    vectors = {"a": (12.0, 100.0), "b": (10.0, 90.0), "c": (11.0, 120.0)}
    objectives = (("maximize", "lift_to_drag"), ("minimize", "mass"))
    assert pareto_front(vectors, objectives) == ("a", "b")


def test_partial_candidate_is_not_ranked(candidates, evaluations, pack):
    ranked = rank_evaluated_candidates(candidates, evaluations, pack["objectives"])
    assert "candidate-partial" not in {item["candidate_id"] for item in ranked}
```

- [ ] **Step 2: Implement objective extraction and dominance**

Raise `ContractViolation` when an objective metric is absent from a supposedly passed candidate. Convert minimize metrics by comparison direction rather than negating stored evidence. Sort ties by candidate ID.

Rank numerically complete development evidence so the workflow remains usable before customer approval, but copy its evidence status into the optimization record; never relabel it as formal.

- [ ] **Step 3: Implement bounded iteration**

`run_optimization` accepts `iterations` in `1..10` and `evaluation_budget` in `3..500`. Each iteration generates around the current front with seed `base_seed + iteration`, evaluates through Task 7, and stops on budget, iteration count, or two consecutive iterations with no new front hash.

Return an `OptimizationResult` containing immutable tuples of all candidate/evaluation objects plus one `OptimizationRun` with iteration records and final front IDs.

- [ ] **Step 4: Run tests and commit**

Run: `.venv/bin/pytest -q tests/application/test_multidisciplinary_optimization.py`
Expected: PASS, including deterministic front order and stop reason.

```bash
git add src/rflp_lite/application/multidisciplinary_optimization.py tests/application/test_multidisciplinary_optimization.py
git commit -m "feat: rank and optimize multidisciplinary layouts"
```

### Task 9: Orchestrate and persist the complete M3–M4 run

**Files:**

- Create: `src/rflp_lite/application/concept_design_service.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/adapters/sqlite_repository.py`
- Test: `tests/application/test_concept_design_service.py`
- Test: `tests/application/test_web_facade.py`

**Interfaces:**

- Consumes: all Task 1–8 services and repository methods.
- Produces: `run_concept_design(pack, evaluator_profile, envelope_payload, schemes, registry, store, optimize=True) -> ConceptRunResult` and facade methods `import_concept_schemes`, `run_concept_design`, `concept_run`, and `review_layout_candidate`.

```python
@dataclass(frozen=True, slots=True)
class ConceptRunResult:
    id: str
    envelope: IndicatorEnvelope
    matches: tuple[SimilarityMatch, ...]
    candidates: tuple[LayoutCandidate, ...]
    evaluations: tuple[DisciplineEvaluation, ...]
    optimization: OptimizationRun
    trace_links: tuple[tuple[str, str, str], ...]
    status: str
    formal_status: str
    input_hash: str
    result_hash: str
```

- [ ] **Step 1: Write the end-to-end application test**

```python
def test_concept_run_links_envelope_candidates_evaluations_and_optimization(
    pack, evaluator_profile, envelope_payload, schemes, registry, store
):
    result = run_concept_design(
        pack, evaluator_profile, envelope_payload, schemes, registry, store, optimize=True
    )
    assert 3 <= len(result.candidates) <= 5
    assert len(result.evaluations) == len(result.candidates) * 3
    assert result.optimization.front_candidate_ids
    assert all(item.envelope_id == result.envelope.id for item in result.candidates)
    assert result.trace_links
```

- [ ] **Step 2: Implement the orchestration sequence**

Execute exactly: validate pack → normalize envelope → retrieve schemes → generate candidates → render sketch artifacts → save candidates → evaluate → optimize → save evaluations/run → audit. Build trace links:

```text
requirement refines envelope
scheme influences candidate
candidate evaluatedBy evaluation
evaluation contributesTo optimization
optimization ranks candidate
```

- [ ] **Step 3: Add human review and invalidation**

Only `review_layout_candidate(candidate_id, "accepted"|"rejected")` can approve a passed candidate. Parameter, pack, generator, or evaluator changes create a new run and leave the old run immutable.

- [ ] **Step 4: Add facade transaction boundaries**

The facade opens one repository transaction per state-changing request, stores normalized records, and adds audit events `concept.schemes_imported`, `concept.run_completed`, and `concept.candidate_reviewed`. It returns JSON-safe dictionaries using existing canonical serialization.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/pytest -q tests/application/test_concept_design_service.py tests/application/test_web_facade.py tests/application/test_requirements_workbench.py`
Expected: PASS without changing M0–M2 behavior.

```bash
git add src/rflp_lite/application/concept_design_service.py src/rflp_lite/application/web_facade.py src/rflp_lite/adapters/sqlite_repository.py tests/application/test_concept_design_service.py tests/application/test_web_facade.py
git commit -m "feat: orchestrate concept design runs"
```

### Task 10: Expose API, CLI, and one lightweight Web page

**Files:**

- Modify: `src/rflp_lite/interface/web/api_v1.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Create: `src/rflp_lite/interface/web/templates/concept-design.html`
- Modify: `src/rflp_lite/interface/web/templates/base.html`
- Modify: `src/rflp_lite/interface/cli.py`
- Test: `tests/interface/web/test_api_v1.py`
- Test: `tests/interface/web/test_pages.py`
- Test: `tests/interface/test_cli.py`

**Interfaces:**

- Consumes: Task 9 facade methods.
- Produces: the approved API routes, `/w/{workspace}/concept-design`, and `rflp concept import/run/export`.

- [ ] **Step 1: Write API workflow tests**

```python
def test_api_imports_schemes_and_runs_concept_design(client, workspace):
    imported = client.post(
        f"/api/v1/workspaces/{workspace}/schemes/import",
        json={"pack": "fixed-wing-v1", "filename": "schemes.json", "content": scheme_rows},
    )
    assert imported.status_code == 200
    run = client.post(
        f"/api/v1/workspaces/{workspace}/concept-runs",
        json={
            "pack": "fixed-wing-v1",
            "evaluator_profile": "development-v1",
            "envelope": envelope_payload,
            "optimize": True,
        },
    )
    assert run.status_code == 200
    assert 3 <= len(run.json()["run"]["candidates"]) <= 5
```

- [ ] **Step 2: Add exact API routes**

Implement the seven routes from the approved spec. JSON/CSV uploads are capped before parsing. SQLite imports are local-path operations available only through CLI and restricted to the workspace or an adapter-approved directory; the Web API never accepts an arbitrary server filesystem path. Return existing `_error` shape with status `422` for validation errors and `404` for unknown runs/candidates.

- [ ] **Step 3: Add CLI tests and handlers**

```python
def test_concept_run_cli_emits_acceptance_summary(tmp_path, capsys):
    code = main(["concept", "run", "--workspace", str(workspace),
                 "--pack", str(pack_path),
                 "--evaluator-profile", str(profile_path),
                 "--envelope", str(envelope_path)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["candidate_count"] in {3, 4, 5}
    assert payload["disciplines"] == ["aerodynamics", "structures", "weight_balance"]
```

`concept import` accepts `--pack`, `--data`, and optional `--table`; `concept run` accepts `--workspace`, `--pack`, `--evaluator-profile`, `--envelope`, `--iterations`, and `--evaluation-budget`; `concept export` accepts `--workspace`, `--run-id`, and `--format json|svg`. For SVG export, require `--candidate-id`; JSON exports the complete run.

- [ ] **Step 4: Add one Web page**

Render four sections in `concept-design.html`: pack/data, envelope, candidate cards with SVG/constraints, and evaluation/Pareto results. Reuse existing CSS classes; add no JavaScript dependency. Candidate acceptance uses a standard POST form.

- [ ] **Step 5: Run interface regression**

Run: `.venv/bin/pytest -q tests/interface/web/test_api_v1.py tests/interface/web/test_pages.py tests/interface/test_cli.py`
Expected: PASS; existing requirements and project routes remain green.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/interface/web/api_v1.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/templates/concept-design.html src/rflp_lite/interface/web/templates/base.html src/rflp_lite/interface/cli.py tests/interface/web/test_api_v1.py tests/interface/web/test_pages.py tests/interface/test_cli.py
git commit -m "feat: expose concept design workflow"
```

### Task 11: Add executable acceptance evidence and release checks

**Files:**

- Create: `src/rflp_lite/application/concept_acceptance.py`
- Create: `src/rflp_lite/resources/examples/concept-design/development-evaluator-profile.json`
- Modify: `src/rflp_lite/interface/cli.py`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Test: `tests/application/test_concept_acceptance.py`

**Interfaces:**

- Consumes: `run_concept_design` and packaged fixed-wing fixtures.
- Produces: `run_concept_acceptance(pack_path, schemes_path, envelope_path, evaluator_profile_path) -> dict[str, object]` and `rflp concept acceptance`.

- [ ] **Step 1: Write the acceptance test**

```python
def test_concept_acceptance_proves_21_and_22(pack_path, schemes_path, envelope_path, profile_path):
    report = run_concept_acceptance(pack_path, schemes_path, envelope_path, profile_path)
    assert report["status"] == "passed"
    assert report["formal_status"] == "development_only"
    assert report["checks"]["2.1.candidate_count"] is True
    assert report["checks"]["2.1.hard_constraints"] is True
    assert report["checks"]["2.1.reproducible"] is True
    assert report["checks"]["2.2.three_disciplines"] is True
    assert report["checks"]["2.2.failure_isolation"] is True
    assert report["checks"]["2.2.optimization_trace"] is True
    assert report["checks"]["2.2.approval_gate"] is True
```

- [ ] **Step 2: Implement the report**

Run the same inputs twice and compare candidate/result hashes. Deliberately run a second failure-isolation probe with the structure adapter failing and verify aerodynamic and weight/balance results remain. Also rerun with approval removed and prove that formal status cannot be `passed`. The packaged profile is explicitly development-only; `status="passed"` means the executable software checks passed, while `formal_status` remains `development_only` until the customer supplies an approval profile naming each accepted adapter/version, approval basis, approver, and time.

- [ ] **Step 3: Add the CLI command**

```text
rflp concept acceptance --pack <pack.json> --schemes <schemes.json> --envelope <envelope.json> --evaluator-profile <profile.json>
```

Exit `0` only when all executable checks pass; otherwise print canonical failure JSON and exit `1`. Include `formal_status` separately so a development fixture can never be mistaken for customer approval.

- [ ] **Step 4: Update user and status documentation**

Document domain-pack changes, supported sources, fixed core fields, the exact acceptance command, evaluator-approval gate, and remaining M5–M8 scope. Do not describe built-in analytical evaluators as customer-approved unless the supplied profile says so.

- [ ] **Step 5: Run full release verification**

Run:

```bash
.venv/bin/pytest -q
.venv/bin/lint-imports
.venv/bin/python -m build --wheel --no-isolation
.venv/bin/rflp concept acceptance \
  --pack src/rflp_lite/resources/domain-packs/fixed-wing-v1.json \
  --schemes src/rflp_lite/resources/examples/concept-design/fixed-wing-schemes.json \
  --envelope src/rflp_lite/resources/examples/concept-design/fixed-wing-envelope.json \
  --evaluator-profile src/rflp_lite/resources/examples/concept-design/development-evaluator-profile.json
```

Expected: all tests pass, 3 import contracts are kept, wheel builds, and the acceptance command returns `"status":"passed"`, `"formal_status":"development_only"`, and 3–5 candidates. Repeating the command with a separately supplied, schema-valid customer approval profile may return `"formal_status":"passed"`.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/application/concept_acceptance.py src/rflp_lite/resources/examples/concept-design/development-evaluator-profile.json src/rflp_lite/interface/cli.py README.md docs/DEVELOPMENT_STATUS.md tests/application/test_concept_acceptance.py
git commit -m "feat: add concept design acceptance evidence"
```

## Completion Gate

M3–M4 is complete only when:

- Tasks 1–11 are committed independently.
- The packaged acceptance command passes twice with identical candidate and evaluation hashes.
- Formal candidates number 3–5 and all hard constraints pass.
- Every candidate has parameters, sources, similarity explanations, SVG, seed, versions, and hashes.
- Three critical disciplines have complete structured outputs and evidence-source labels.
- Failure isolation and surrogate validity-domain tests pass.
- Optimization results trace to all contributing evaluations and candidates.
- An unapproved evaluator profile cannot produce a formal `passed` status.
- Full pytest, Import Linter, and wheel build pass.
