from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rflp_lite.application.dependencies import ApplicationDependencies, require_dependencies
from rflp_lite.application.compile import compile_claims
from rflp_lite.application.decide import select_candidate
from rflp_lite.application.diff import calculate_delta
from rflp_lite.application.ingest import ingest_requirements
from rflp_lite.application.synthesize import synthesize_rflp
from rflp_lite.application.tasks import build_task_contracts
from rflp_lite.application.resources import PROJECT_ROOT, resource_path
from rflp_lite.domain.baseline import approve_baseline
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.domain.models import DemoResult, Evidence
from rflp_lite.governance.profile import Profile
from rflp_lite.governance.run_manifest import build_manifest
from rflp_lite.governance.validation import validate_json
from rflp_lite.simulation.engine import simulate


DEFAULT_FIXTURES = resource_path("examples/versioned-content-service")


def _write_json(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def run_demo(
    workspace: Path,
    profile: Profile,
    fixture_root: Path | None = None,
    solver_override: Any | None = None,
    *,
    dependencies: ApplicationDependencies | None = None,
) -> DemoResult:
    deps = require_dependencies(dependencies)
    fixture_root = fixture_root or DEFAULT_FIXTURES
    model_dir = workspace / ".rflp"
    model_dir.mkdir(parents=True, exist_ok=True)
    repository = deps.repository_factory(model_dir / "model.db")
    try:
        try:
            with repository.transaction():
                repository.record_audit("run.started", profile.as_dict())
                artifact, spans = ingest_requirements(
                    fixture_root / "requirements.md", dependencies=deps
                )
                claims = compile_claims(spans, dependencies=deps)
                elements, relations = synthesize_rflp(claims)
                solver = solver_override or (
                    deps.solver_factory(profile.solver)
                )
                candidates = solver.solve(elements, profile)
                simulations = tuple(simulate(candidate, profile.seed) for candidate in candidates)
                decision = select_candidate(candidates, simulations)
                selected_simulation = next(
                    item for item in simulations if item.candidate_id == decision.candidate_id
                )
                baseline = approve_baseline(elements, relations)
                parsed_evidence = (
                    deps.evidence_readers(fixture_root)
                )
                simulation_evidence = Evidence(
                    id=f"evidence-{selected_simulation.id}",
                    kind="simulation",
                    source=selected_simulation.id,
                    target_id=selected_simulation.candidate_id,
                    status="passed" if selected_simulation.passed else "failed",
                    artifact_hash=selected_simulation.trace_hash,
                    details=selected_simulation.metrics,
                )
                evidence = tuple(sorted(parsed_evidence + (simulation_evidence,), key=lambda item: item.id))
                delta = calculate_delta(baseline, evidence)
                task_contracts = build_task_contracts(delta)

                repository.save_artifacts((artifact,))
                repository.save_spans(spans)
                repository.save_claims(claims)
                repository.save_elements(elements)
                repository.save_relations(relations)
                repository.save_candidates(candidates)
                repository.save_simulation(selected_simulation)
                repository.save_baseline(baseline)
                repository.save_tasks(task_contracts)
                repository.save_evidence(evidence)
                repository.record_audit(
                    "run.completed",
                    {"baseline_hash": baseline.hash, "solver": profile.solver},
                )
        except Exception as exc:
            repository.record_audit(
                "run.failed",
                {"error_type": type(exc).__name__, "message": str(exc)},
            )
            if isinstance(exc, AdapterFailure):
                raise
            raise AdapterFailure(f"demo pipeline failed: {exc}") from exc

        fixture_hashes = {
            path.name: __import__("hashlib").sha256(path.read_bytes()).hexdigest()
            for path in sorted(fixture_root.iterdir())
            if path.is_file()
        }
        stage_hashes = {
            "artifact": canonical_hash(artifact),
            "claims": canonical_hash(claims),
            "rflp": canonical_hash((elements, relations)),
            "candidates": canonical_hash(candidates),
            "simulation": selected_simulation.trace_hash,
            "delta": canonical_hash(delta),
            "tasks": canonical_hash(task_contracts),
            "evidence": canonical_hash(evidence),
        }
        result_hash = canonical_hash(
            (
                profile.as_dict(),
                fixture_hashes,
                stage_hashes,
                baseline.hash,
                decision,
            )
        )
        run_dir = model_dir / "runs" / result_hash
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest = build_manifest(
            profile, fixture_hashes, stage_hashes, baseline.hash, result_hash
        )
        validate_json(manifest, resource_path("schemas/run-manifest.schema.json"))
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
        for filename, value in outputs.items():
            _write_json(run_dir / filename, value)
        return DemoResult(
            artifacts=(artifact,),
            spans=spans,
            claims=claims,
            elements=elements,
            relations=relations,
            candidates=candidates,
            decision=decision,
            simulation=selected_simulation,
            baseline=baseline,
            delta=delta,
            task_contracts=task_contracts,
            evidence=evidence,
            manifest_path=str((run_dir / "run-manifest.json").resolve()),
            result_hash=result_hash,
        )
    finally:
        repository.close()
