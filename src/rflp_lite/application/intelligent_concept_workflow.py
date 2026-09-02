"""Orchestrate the requirements-to-concept-design demonstration workflow.

The orchestrator deliberately composes the existing document, workbench,
MBSE, envelope, retrieval, generation, evaluation, and optimization services.
It adds only the workflow boundary and a durable, resumable run record.
"""

from __future__ import annotations

import json
from html import escape
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable

from rflp_lite.application.concept_llm_enrichment import enrich_concept_input
from rflp_lite.application.concept_design_service import run_concept_design
from rflp_lite.application.dependencies import ApplicationDependencies, configured_dependencies
from rflp_lite.application.domain_packs import load_domain_pack, validate_domain_pack
from rflp_lite.application.discipline_batch import validate_evaluator_profile
from rflp_lite.application.mbse_modeling import generate_mbse_revision
from rflp_lite.application.requirement_clause_splitter import RequirementClauseSplitter
from rflp_lite.application.requirement_to_envelope import build_envelope_from_requirements
from rflp_lite.application.requirements_workbench import (
    accept_initial_workbench,
    accept_traceable,
    analyze_artifact,
    generate_model,
)
from rflp_lite.application.resources import resource_path
from rflp_lite.application.scheme_import_mapper import map_scheme_rows
from rflp_lite.application.scheme_retrieval import find_similar_schemes
from rflp_lite.application.traceability import refresh_traceability
from rflp_lite.application.workspaces import managed_workspace
from rflp_lite.domain.canonical import canonical_hash, canonical_json, to_primitive
from rflp_lite.domain.concept_design import SchemeRecord
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.repositories import WorkbenchRepositoryPort


@dataclass(frozen=True, slots=True)
class ConceptWorkflowRequest:
    workspace_name: str
    text: str = ""
    filename: str = "requirements.txt"
    document_bytes: bytes | None = None
    pack: object = "auto"
    evaluator_profile: object = "development-v1"
    seed: int = 42
    demo_mode: bool = True


@dataclass(frozen=True, slots=True)
class ConceptWorkflowResult:
    run_id: str
    workspace_name: str
    status: str
    steps: tuple[dict[str, object], ...]
    clause_analysis: Mapping[str, object] = field(default_factory=dict)
    mbse: Mapping[str, object] = field(default_factory=dict)
    envelope: Mapping[str, object] = field(default_factory=dict)
    envelope_field_provenance: tuple[dict[str, object], ...] = ()
    retrieval: Mapping[str, object] = field(default_factory=dict)
    generation: Mapping[str, object] = field(default_factory=dict)
    evaluation: Mapping[str, object] = field(default_factory=dict)
    optimization: Mapping[str, object] = field(default_factory=dict)
    candidates: tuple[dict[str, object], ...] = ()
    recommendation: Mapping[str, object] = field(default_factory=dict)
    concept_run: Mapping[str, object] = field(default_factory=dict)
    formal_status: str = "development"
    input_hash: str = ""
    result_hash: str = ""
    diagnostics: tuple[str, ...] = ()
    request: Mapping[str, object] = field(default_factory=dict)
    domain_pack: Mapping[str, object] = field(default_factory=dict)
    baseline: Mapping[str, object] = field(default_factory=dict)
    concept_proposal: Mapping[str, object] = field(default_factory=dict)
    llm_analysis: Mapping[str, object] = field(default_factory=dict)
    enrichment: Mapping[str, object] = field(default_factory=dict)
    execution_mode: str = "professional"

    @property
    def id(self) -> str:
        return self.run_id

    def to_payload(self) -> dict[str, object]:
        payload = json.loads(canonical_json(self))
        payload["id"] = self.run_id
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "ConceptWorkflowResult":
        return cls(
            run_id=str(payload.get("run_id", payload.get("id", ""))),
            workspace_name=str(payload.get("workspace_name", "")),
            status=str(payload.get("status", "")),
            steps=tuple(dict(item) for item in payload.get("steps", ()) if isinstance(item, Mapping)),
            clause_analysis=dict(payload.get("clause_analysis", {})) if isinstance(payload.get("clause_analysis"), Mapping) else {},
            mbse=dict(payload.get("mbse", {})) if isinstance(payload.get("mbse"), Mapping) else {},
            envelope=dict(payload.get("envelope", {})) if isinstance(payload.get("envelope"), Mapping) else {},
            envelope_field_provenance=tuple(dict(item) for item in payload.get("envelope_field_provenance", ()) if isinstance(item, Mapping)),
            retrieval=dict(payload.get("retrieval", {})) if isinstance(payload.get("retrieval"), Mapping) else {},
            generation=dict(payload.get("generation", {})) if isinstance(payload.get("generation"), Mapping) else {},
            evaluation=dict(payload.get("evaluation", {})) if isinstance(payload.get("evaluation"), Mapping) else {},
            optimization=dict(payload.get("optimization", {})) if isinstance(payload.get("optimization"), Mapping) else {},
            candidates=tuple(dict(item) for item in payload.get("candidates", ()) if isinstance(item, Mapping)),
            recommendation=dict(payload.get("recommendation", {})) if isinstance(payload.get("recommendation"), Mapping) else {},
            concept_run=dict(payload.get("concept_run", {})) if isinstance(payload.get("concept_run"), Mapping) else {},
            formal_status=str(payload.get("formal_status", "development")),
            input_hash=str(payload.get("input_hash", "")),
            result_hash=str(payload.get("result_hash", "")),
            diagnostics=tuple(str(item) for item in payload.get("diagnostics", ())),
            request=dict(payload.get("request", {})) if isinstance(payload.get("request"), Mapping) else {},
            domain_pack=dict(payload.get("domain_pack", {})) if isinstance(payload.get("domain_pack"), Mapping) else {},
            baseline=dict(payload.get("baseline", {})) if isinstance(payload.get("baseline"), Mapping) else {},
            concept_proposal=dict(payload.get("concept_proposal", {})) if isinstance(payload.get("concept_proposal"), Mapping) else {},
            llm_analysis=dict(payload.get("llm_analysis", {})) if isinstance(payload.get("llm_analysis"), Mapping) else {},
            enrichment=dict(payload.get("enrichment", {})) if isinstance(payload.get("enrichment"), Mapping) else {},
            execution_mode=str(payload.get("execution_mode", "professional")),
        )


_STEP_DEFINITIONS = (
    ("1.1", "requirements_completed", "需求拆解"),
    ("1.2", "mbse_completed", "MBSE 语义模型"),
    ("2.1", "envelope_completed", "指标包络"),
    ("2.1.retrieval", "retrieval_completed", "历史方案检索"),
    ("2.1.generation", "generation_completed", "初始候选生成"),
    ("2.1.evaluation", "evaluation_completed", "多学科评估"),
    ("2.2", "optimization_completed", "优化与 Pareto 推荐"),
)


def _step(identifier: str, key: str, label: str, status: str = "pending", *, diagnostics: Sequence[str] = ()) -> dict[str, object]:
    return {
        "id": identifier,
        "key": key,
        "name": key.removesuffix("_completed"),
        "label": label,
        "status": status,
        "started_at": None,
        "completed_at": None,
        "input_hash": "",
        "result_ref": "",
        "diagnostics": tuple(diagnostics),
    }


def _resolve_pack(value: object) -> dict[str, object] | None:
    if value is None or (isinstance(value, str) and value.strip().casefold() in {"", "auto"}):
        return None
    if isinstance(value, Mapping):
        return validate_domain_pack(dict(value))
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation("domain pack must be an object or packaged alias")
    identifier = value.strip()
    if "/" in identifier or "\\" in identifier:
        return load_domain_pack(Path(identifier))
    aliases = {"fixed-wing": "fixed-wing-v1.json", "fixed-wing-v1": "fixed-wing-v1.json"}
    filename = aliases.get(identifier, identifier if identifier.endswith(".json") else f"{identifier}.json")
    return load_domain_pack(resource_path(f"domain-packs/{filename}"))


def _resolve_profile(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return validate_evaluator_profile(dict(value))
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation("evaluator profile must be an object or packaged alias")
    identifier = value.strip()
    if "/" in identifier or "\\" in identifier:
        raise ContractViolation("evaluator profile paths are not allowed")
    aliases = {
        "development-v1": "development-evaluator-profile.json",
        "development-evaluator-profile": "development-evaluator-profile.json",
    }
    filename = aliases.get(identifier, identifier if identifier.endswith(".json") else f"{identifier}.json")
    path = resource_path(f"examples/concept-design/{filename}")
    try:
        return validate_evaluator_profile(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractViolation(f"evaluator profile not found: {identifier}") from exc


def _content(request: ConceptWorkflowRequest) -> tuple[str, bytes]:
    if request.document_bytes is not None:
        return request.filename, bytes(request.document_bytes)
    return request.filename, request.text.strip().encode("utf-8")


def _request_payload(request: ConceptWorkflowRequest, pack: Mapping[str, object] | None, profile: Mapping[str, object], content: bytes) -> dict[str, object]:
    return {
        "workspace_name": request.workspace_name,
        "filename": request.filename,
        "content_sha256": sha256(content).hexdigest(),
        "input_text": request.text if request.document_bytes is None else "",
        "pack": f"{pack['id']}@{pack['version']}" if pack else "auto",
        "evaluator_profile": f"{profile['id']}@{profile['version']}",
        "seed": int(request.seed),
        "demo_mode": bool(request.demo_mode),
    }


def _records_payload(values: object) -> tuple[dict[str, object], ...]:
    return tuple(dict(item) for item in values if isinstance(item, Mapping)) if isinstance(values, (tuple, list)) else ()


def _infer_pack(state: Mapping[str, object]) -> dict[str, object] | None:
    """Select only a known pack whose domain is supported by the input."""

    context = state.get("system_context") if isinstance(state.get("system_context"), Mapping) else {}
    enrichment = state.get("llm_analysis") if isinstance(state.get("llm_analysis"), Mapping) else {}
    regions = state.get("document_regions", ())
    source = " ".join(
        str(item.get("text", ""))
        for item in regions
        if isinstance(item, Mapping)
    )
    signal = " ".join(
        (
            str(context.get("domain", "")),
            str(context.get("mission", "")),
            str(enrichment.get("system", {})),
            source,
        )
    ).casefold()
    aviation_terms = (
        "无人机", "飞行器", "航空", "固定翼", "多旋翼", "无人航空", "uav", "aircraft", "aerial", "drone"
    )
    if any(term in signal for term in aviation_terms):
        return _resolve_pack("fixed-wing-v1")
    return None


def _baseline_scheme(pack: Mapping[str, object], envelope: Mapping[str, object]) -> SchemeRecord:
    parameters = envelope.get("parameters", {})
    parameter_pairs = tuple(sorted(
        (str(name), value)
        for name, value in parameters.items()
    )) if isinstance(parameters, Mapping) else ()
    scheme_hash = canonical_hash({"pack": pack, "parameters": parameter_pairs})
    return SchemeRecord(
        id=f"{pack.get('id_prefix', 'PACK')}-LLM-BASELINE-{scheme_hash[:12]}",
        object_type=str(pack.get("object_type", "layout")),
        schema_version=int(pack.get("schema_version", 1)),
        domain_pack_id=str(pack.get("id", "")),
        domain_pack_version=int(pack.get("version", 1)),
        revision=1,
        status="candidate",
        source="concept-workflow:provisional-baseline",
        parameters=parameter_pairs,
        extensions=(("name", "LLM 临时概念基线"), ("task_type", "provisional concept")),
        content_hash=scheme_hash,
    )


def _mark_provisional(steps: list[dict[str, object]], start: int, message: str) -> None:
    for item in steps[start:]:
        item["status"] = "provisional"
        item["diagnostics"] = (message,)


class ConceptWorkflowOrchestrator:
    """Run and persist the complete local intelligent concept workflow."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        dependencies: ApplicationDependencies | None = None,
        llm_config_provider: Callable[[], Mapping[str, object] | None] | None = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.dependencies = configured_dependencies(dependencies)
        self.llm_config_provider = llm_config_provider

    def _repository(self, workspace_name: str) -> WorkbenchRepositoryPort:
        workspace = managed_workspace(self.workspace_root, workspace_name)
        if not (workspace / "profile.json").is_file():
            raise ContractViolation(f"workspace not found: {workspace_name}")
        return self.dependencies.repository_factory(workspace / ".rflp" / "model.db")

    def _ensure_history(self, repository: WorkbenchRepositoryPort, pack: Mapping[str, object]) -> tuple[dict[str, object], ...]:
        records = repository.scheme_records()
        if records or str(pack.get("id")) != "fixed-wing":
            return records
        data_path = resource_path("examples/concept-design/demo-schemes.json")
        rows = self.dependencies.scheme_reader(data_path.name, data_path.read_bytes())
        mapped = map_scheme_rows(pack, rows, str(data_path), existing_ids={str(item.get("id")) for item in records})
        repository.save_domain_pack(pack)
        repository.save_scheme_records(mapped.records)
        repository.record_audit(
            "concept.schemes_seeded",
            {"source": str(data_path), "accepted": len(mapped.records), "skipped": len(mapped.skipped), "rejected": len(mapped.rejected)},
        )
        return repository.scheme_records()

    def run(self, request: ConceptWorkflowRequest) -> ConceptWorkflowResult:
        pack = _resolve_pack(request.pack)
        run_pack = dict(pack) if pack else {}
        generation = dict(pack.get("generation", {})) if pack and isinstance(pack.get("generation"), Mapping) else {}
        generation["seed"] = int(request.seed)
        run_pack["generation"] = generation
        profile = _resolve_profile(request.evaluator_profile)
        filename, content = _content(request)
        request_payload = _request_payload(request, pack, profile, content)
        input_hash = canonical_hash(request_payload)
        run_id = f"WORKFLOW-{input_hash[:16]}"
        repository = self._repository(request.workspace_name)
        existing = repository.load_workflow_run(run_id)
        if existing is not None:
            repository.close()
            return ConceptWorkflowResult.from_payload(existing)

        steps = [_step(*definition) for definition in _STEP_DEFINITIONS]
        for item in steps:
            item["input_hash"] = input_hash
        state: dict[str, object] = {}
        diagnostics: list[str] = []
        current_index = 0
        concept_payload: dict[str, object] = {}
        analysis = None
        envelope_payload: dict[str, object] = {}
        envelope_provenance: object = ()
        retrieval_payload: dict[str, object] = {}
        try:
            fresh = analyze_artifact(filename, content, dependencies=self.dependencies)
            analysis = RequirementClauseSplitter().analyze(fresh.get("document_regions", ()))
            state = json.loads(canonical_json(fresh))
            state["structured_requirements"] = list(to_primitive(analysis.requirements))
            state["requirement_attributes"] = list(to_primitive(analysis.attributes))
            state["requirement_constraints"] = list(to_primitive(analysis.constraints))
            state["trace_links"] = []
            state["traceability"] = []
            scope = state.get("project_scope") if isinstance(state.get("project_scope"), dict) else {}
            state["project_scope"] = {
                **scope,
                "workspace": request.workspace_name,
                "input_hash": input_hash,
            }
            state = refresh_traceability(state)
            llm_result = enrich_concept_input(
                state,
                active_config=self.llm_config_provider() if self.llm_config_provider else None,
                model_factory=self.dependencies.model_factory,
            )
            state = llm_result.state
            diagnostics.extend(llm_result.diagnostics)
            if pack is None:
                pack = _infer_pack(state)
                run_pack = dict(pack) if pack else {}
                generation = dict(pack.get("generation", {})) if pack and isinstance(pack.get("generation"), Mapping) else {}
                generation["seed"] = int(request.seed)
                if pack:
                    request_payload["pack"] = f"{pack['id']}@{pack['version']}"
            state = accept_initial_workbench(state)
            steps[current_index]["status"] = "completed"
            steps[current_index]["result_ref"] = f"workbench:{input_hash[:12]}"
            steps[current_index]["artifacts"] = {"clause_count": len(analysis.clauses), "requirement_count": len(analysis.requirements)}
            repository.save_workbench(state, event="concept.workflow.requirements_analyzed")

            current_index = 1
            state = accept_traceable(state)
            state = generate_model(state)
            state = generate_mbse_revision(state)
            state = refresh_traceability(state)
            steps[current_index]["status"] = "completed"
            steps[current_index]["result_ref"] = f"mbse:{canonical_hash(state.get('mbse', {}))[:12]}"
            steps[current_index]["artifacts"] = {"mbse_status": (state.get("mbse") or {}).get("status", "candidate")}
            repository.save_workbench(state, event="concept.workflow.mbse_generated")

            current_index = 2
            enrichment = state.get("concept_enrichment") if isinstance(state.get("concept_enrichment"), Mapping) else {}
            llm_suggestions = _records_payload(enrichment.get("parameter_suggestions", ()))
            if pack is None:
                message = "未匹配到适用的专业领域包，已保留 LLM/规则概念与 MBSE 临时草案"
                diagnostics.append(message)
                retrieval_payload = {"matches": [], "top_matches": []}
                _mark_provisional(steps, current_index, message)
            else:
                envelope_result = build_envelope_from_requirements(
                    run_pack,
                    _records_payload(to_primitive(analysis.requirements)),
                    attributes=_records_payload(to_primitive(analysis.attributes)),
                    constraints=_records_payload(to_primitive(analysis.constraints)),
                    history=repository.scheme_records(),
                    llm_suggestions=llm_suggestions,
                    provisional=True,
                )
                diagnostics.extend(envelope_result.diagnostics)
                envelope_provenance = to_primitive(envelope_result.field_provenance)
                if envelope_result.envelope is None:
                    message = "指标包络仍有未解决字段，已保留概念与 MBSE 临时草案"
                    diagnostics.append(message)
                    _mark_provisional(steps, current_index, message)
                else:
                    envelope_payload = _envelope_request(envelope_result.envelope)
                    steps[current_index]["status"] = "completed"
                    steps[current_index]["result_ref"] = f"envelope:{canonical_hash(envelope_payload)[:12]}"
                    steps[current_index]["artifacts"] = {
                        "parameter_count": len(envelope_payload.get("parameters", ())),
                        "diagnostics": envelope_result.diagnostics,
                        "status": envelope_payload.get("status", "candidate"),
                    }
                    repository.save_domain_pack(pack)
                    repository.save_indicator_envelopes((envelope_result.envelope,))

                    current_index = 3
                    existing_schemes = repository.scheme_records()
                    schemes = self._ensure_history(repository, pack) if request.demo_mode else existing_schemes
                    history_seeded = not existing_schemes and bool(schemes)
                    if not schemes:
                        schemes = (_baseline_scheme(run_pack, envelope_payload),)
                        diagnostics.append("没有历史方案，已用当前指标包络创建临时基线供专业算法继续")
                    full_matches = find_similar_schemes(
                        run_pack,
                        envelope_result.envelope,
                        schemes,
                        limit=max(3, len(schemes)),
                    )
                    retrieval_payload = {
                        "matches": _retrieval_rows(full_matches, schemes),
                        "top_matches": _retrieval_rows(full_matches[:3], schemes),
                    }
                    steps[current_index]["status"] = "completed"
                    steps[current_index]["result_ref"] = f"schemes:{len(schemes)}"
                    steps[current_index]["artifacts"] = {
                        "match_source_count": len(schemes),
                        "history_seeded": history_seeded,
                        "temporary_baseline": not bool(existing_schemes),
                    }

                    provisional_defaults = any(
                        isinstance(item, Mapping) and item.get("source_kind") == "suggested_default"
                        for item in envelope_provenance
                    )
                    if provisional_defaults:
                        message = "部分指标使用领域包范围生成临时初值，专业评估与优化等待补充确认"
                        diagnostics.append(message)
                        _mark_provisional(steps, 4, message)
                    else:
                        current_index = 4
                        try:
                            concept = run_concept_design(
                                run_pack,
                                profile,
                                envelope_payload,
                                schemes,
                                self.dependencies.discipline_registry(),
                                repository,
                                optimize=True,
                            )
                        except ContractViolation as exc:
                            message = f"专业候选暂未生成，已保留指标包络和概念草案：{exc}"
                            diagnostics.append(message)
                            _mark_provisional(steps, current_index, message)
                        else:
                            concept_payload = json.loads(canonical_json(concept))
                            optimization_payload = concept_payload.get("optimization", {})
                            iteration_records = optimization_payload.get("iteration_records", ()) if isinstance(optimization_payload, Mapping) else ()
                            steps[current_index]["status"] = "completed"
                            steps[current_index]["result_ref"] = str(concept_payload.get("id", ""))
                            steps[current_index]["artifacts"] = {"candidate_count": len(concept_payload.get("candidates", ())), "initial_candidate_count": len(_initial_ids(optimization_payload))}

                            current_index = 5
                            evaluations = concept_payload.get("evaluations", ())
                            steps[current_index]["status"] = "completed"
                            steps[current_index]["result_ref"] = f"evaluations:{len(evaluations)}"
                            steps[current_index]["artifacts"] = {"evaluation_count": len(evaluations), "numeric_metrics": _numeric_metrics(evaluations)}

                            current_index = 6
                            steps[current_index]["status"] = "completed"
                            steps[current_index]["result_ref"] = str(optimization_payload.get("id", ""))
                            steps[current_index]["artifacts"] = {"iteration_count": len(iteration_records), "front_candidate_ids": optimization_payload.get("front_candidate_ids", ())}
        except Exception as exc:
            diagnostics.append(str(exc))
            if 0 <= current_index < len(steps):
                steps[current_index]["status"] = "failed"
                steps[current_index]["diagnostics"] = tuple(diagnostics)
            result = self._build_result(
                run_id,
                request.workspace_name,
                input_hash,
                steps,
                diagnostics,
                state,
                concept_payload,
                envelope_payload,
                envelope_provenance,
                analysis,
                profile,
                pack,
                request_payload,
                retrieval_payload,
            )
            repository.save_workflow_runs((result.to_payload(),))
            repository.record_audit("concept.workflow_failed", {"run_id": run_id, "diagnostics": diagnostics})
            repository.close()
            return result

        result = self._build_result(
            run_id,
            request.workspace_name,
            input_hash,
            steps,
            diagnostics,
            state,
            concept_payload,
            envelope_payload,
            envelope_provenance,
            analysis,
            profile,
            pack,
            request_payload,
            retrieval_payload,
        )
        repository.save_workflow_runs((result.to_payload(),))
        repository.record_audit("concept.workflow_completed", {"run_id": run_id, "result_hash": result.result_hash})
        repository.close()
        return result

    def _build_result(
        self,
        run_id: str,
        workspace_name: str,
        input_hash: str,
        steps: list[dict[str, object]],
        diagnostics: Sequence[str],
        state: Mapping[str, object],
        concept_payload: Mapping[str, object],
        envelope_payload: Mapping[str, object],
        provenance: object,
        analysis: object,
        profile: Mapping[str, object],
        pack: Mapping[str, object] | None,
        request_payload: Mapping[str, object],
        retrieval_override: Mapping[str, object] | None = None,
    ) -> ConceptWorkflowResult:
        analysis_payload = {
            "clauses": to_primitive(getattr(analysis, "clauses", ())),
            "requirements": to_primitive(getattr(analysis, "requirements", ())),
            "attributes": to_primitive(getattr(analysis, "attributes", ())),
            "constraints": to_primitive(getattr(analysis, "constraints", ())),
        } if analysis else {}
        candidates = _records_payload(concept_payload.get("candidates", ()))
        optimization = dict(concept_payload.get("optimization", {})) if isinstance(concept_payload.get("optimization"), Mapping) else {}
        front_ids = tuple(str(item) for item in optimization.get("front_candidate_ids", ()))
        optimization["pareto_svg"] = _pareto_svg(candidates, concept_payload.get("evaluations", ()), front_ids)
        recommendation = _recommendation(candidates, front_ids, concept_payload.get("evaluations", ()))
        concept_enrichment = state.get("concept_enrichment") if isinstance(state.get("concept_enrichment"), Mapping) else {}
        concept_proposal = concept_enrichment.get("proposal", {}) if isinstance(concept_enrichment.get("proposal"), Mapping) else {}
        llm_analysis = state.get("llm_analysis") if isinstance(state.get("llm_analysis"), Mapping) else {}
        step_statuses = {str(item.get("status")) for item in steps}
        result_status = "failed" if "failed" in step_statuses else "provisional" if "provisional" in step_statuses else "completed"
        core = {
            "run_id": run_id,
            "workspace_name": workspace_name,
            "status": result_status,
            "steps": steps,
            "clause_analysis": analysis_payload,
            "mbse": state.get("mbse", {}) if isinstance(state.get("mbse"), Mapping) else {},
            "envelope": dict(envelope_payload),
            "envelope_field_provenance": provenance if isinstance(provenance, (tuple, list)) else (),
            "retrieval": dict(retrieval_override or {"matches": concept_payload.get("matches", ())}),
            "generation": {
                "initial_candidate_ids": _initial_ids(optimization),
                "candidate_count": len(candidates),
                "layout_manifests": concept_payload.get("layout_manifests", ()),
            },
            "evaluation": {"evaluations": concept_payload.get("evaluations", ())},
            "optimization": optimization,
            "candidates": candidates,
            "recommendation": recommendation,
            "concept_run": dict(concept_payload),
            "formal_status": str(concept_payload.get("formal_status", "development")),
            "input_hash": input_hash,
            "diagnostics": tuple(str(item) for item in diagnostics),
            "request": dict(request_payload),
            "evaluator_profile": dict(profile),
            "domain_pack": {"id": pack.get("id"), "version": pack.get("version")} if pack else {},
            "baseline": {},
            "concept_proposal": concept_proposal,
            "llm_analysis": llm_analysis,
            "enrichment": concept_enrichment,
            "execution_mode": "professional" if concept_payload else "provisional-concept",
        }
        result_hash = canonical_hash(core)
        return ConceptWorkflowResult(
            run_id=run_id,
            workspace_name=workspace_name,
            status=str(core["status"]),
            steps=tuple(dict(item) for item in steps),
            clause_analysis=analysis_payload,
            mbse=core["mbse"],
            envelope=dict(envelope_payload),
            envelope_field_provenance=tuple(dict(item) for item in core["envelope_field_provenance"] if isinstance(item, Mapping)),
            retrieval=core["retrieval"],
            generation=core["generation"],
            evaluation=core["evaluation"],
            optimization=optimization,
            candidates=candidates,
            recommendation=recommendation,
            concept_run=dict(concept_payload),
            formal_status=str(core["formal_status"]),
            input_hash=input_hash,
            result_hash=result_hash,
            diagnostics=tuple(str(item) for item in diagnostics),
            request=dict(request_payload),
            domain_pack=core["domain_pack"],
            baseline={},
            concept_proposal=concept_proposal,
            llm_analysis=dict(llm_analysis),
            enrichment=dict(concept_enrichment),
            execution_mode=str(core["execution_mode"]),
        )

    def resume(self, run_id: str, workspace_name: str | None = None) -> ConceptWorkflowResult:
        repositories = []
        names = (workspace_name,) if workspace_name else tuple(path.name for path in self.workspace_root.iterdir() if path.is_dir())
        try:
            for name in names:
                try:
                    repository = self._repository(name)
                except ContractViolation:
                    continue
                repositories.append(repository)
                payload = repository.load_workflow_run(run_id)
                if payload is not None:
                    return ConceptWorkflowResult.from_payload(payload)
        finally:
            for repository in repositories:
                repository.close()
        raise ContractViolation(f"workflow run not found: {run_id}")

    def latest(self, workspace_name: str) -> ConceptWorkflowResult:
        repository = self._repository(workspace_name)
        try:
            runs = repository.workflow_runs()
        finally:
            repository.close()
        if not runs:
            raise ContractViolation("concept workflow run not found")
        return ConceptWorkflowResult.from_payload(runs[0])

    def select_as_concept_baseline(
        self,
        workspace_name: str,
        run_id: str,
        candidate_id: str,
        *,
        selected_by: str = "user",
        rationale: str = "",
    ) -> dict[str, object]:
        workflow = self.resume(run_id, workspace_name)
        candidate = next((item for item in workflow.candidates if str(item.get("id")) == candidate_id), None)
        if candidate is None:
            raise ContractViolation(f"layout candidate not found: {candidate_id}")
        payload = {
            "id": f"BASELINE-{canonical_hash((run_id, candidate_id, selected_by, rationale))[:16]}",
            "run_id": run_id,
            "candidate_id": candidate_id,
            "decision": "provisional_selected",
            "selected_by": selected_by.strip() or "user",
            "selected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rationale": rationale.strip(),
            "candidate_result_hash": candidate.get("result_hash", ""),
            "formal_status": workflow.formal_status,
            "status": "recorded",
            "input_hash": canonical_hash({"run_id": run_id, "candidate_id": candidate_id}),
        }
        repository = self._repository(workspace_name)
        try:
            with repository.transaction():
                repository.save_candidate_reviews((payload,))
                repository.record_audit("concept.baseline_provisionally_selected", payload)
        finally:
            repository.close()
        updated = workflow.to_payload()
        updated["baseline"] = payload
        repository = self._repository(workspace_name)
        try:
            repository.save_workflow_runs((updated,))
        finally:
            repository.close()
        return json.loads(canonical_json(payload))


def _initial_ids(optimization: object) -> tuple[str, ...]:
    if not isinstance(optimization, Mapping):
        return ()
    records = optimization.get("iteration_records", ())
    if not isinstance(records, (tuple, list)):
        return ()
    for item in records:
        if isinstance(item, (tuple, list)) and len(item) == 2 and isinstance(item[1], Mapping):
            if int(item[1].get("generation_index", 0)) == 0:
                return tuple(str(value) for value in item[1].get("candidate_ids", ()))
    return ()


def _envelope_request(envelope: object) -> dict[str, object]:
    """Convert the immutable envelope record to the service input shape."""

    payload = json.loads(canonical_json(envelope))
    parameters = {
        str(item[0]): item[1]
        for item in payload.get("parameters", ())
        if isinstance(item, (tuple, list)) and len(item) == 2
    }
    bounds = {
        str(item[0]): {"minimum": item[1], "maximum": item[2]}
        for item in payload.get("bounds", ())
        if isinstance(item, (tuple, list)) and len(item) == 3
    }
    return {
        "status": payload.get("status", "approved"),
        "source_requirement_ids": payload.get("source_requirement_ids", ()),
        "parameters": parameters,
        "bounds": bounds,
    }


def _numeric_metrics(evaluations: object) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    if not isinstance(evaluations, (tuple, list)):
        return ()
    for evaluation in evaluations:
        if not isinstance(evaluation, Mapping):
            continue
        metrics = evaluation.get("metrics", ())
        if isinstance(metrics, Mapping):
            result.extend({"candidate_id": evaluation.get("candidate_id"), "discipline": evaluation.get("discipline"), "metric": key, "value": value} for key, value in metrics.items())
        elif isinstance(metrics, (tuple, list)):
            result.extend({"candidate_id": evaluation.get("candidate_id"), "discipline": evaluation.get("discipline"), "metric": item[0], "value": item[1]} for item in metrics if isinstance(item, (tuple, list)) and len(item) == 2)
    return tuple(result)


def _retrieval_rows(matches: object, schemes: object) -> list[dict[str, object]]:
    scheme_by_id = {
        str(item.get("id")): item
        for item in schemes
        if isinstance(item, Mapping) and item.get("id")
    } if isinstance(schemes, (tuple, list)) else {}
    rows: list[dict[str, object]] = []
    for match in matches if isinstance(matches, (tuple, list)) else ():
        if isinstance(match, Mapping):
            row = dict(match)
        elif all(hasattr(match, field) for field in ("scheme_id", "similarity", "feature_differences", "missing_features")):
            row = {
                "scheme_id": getattr(match, "scheme_id"),
                "similarity": getattr(match, "similarity"),
                "feature_differences": getattr(match, "feature_differences"),
                "missing_features": getattr(match, "missing_features"),
            }
        else:
            continue
        scheme = scheme_by_id.get(str(row.get("scheme_id")), {})
        raw_extensions = scheme.get("extensions", ()) if isinstance(scheme, Mapping) else ()
        extension_map = {
            str(item[0]): item[1]
            for item in raw_extensions
            if isinstance(item, (tuple, list)) and len(item) == 2
        }
        row["scheme_name"] = extension_map.get("name", extension_map.get("方案名称", ""))
        row["task_type"] = extension_map.get("task_type", extension_map.get("任务类型", ""))
        row["extensions"] = extension_map
        rows.append(row)
    return rows


def _pareto_svg(
    candidates: Sequence[Mapping[str, object]],
    evaluations: object,
    front_ids: Sequence[str],
) -> str:
    """Render a small deterministic scatter plot for the result page."""

    values: dict[str, float] = {}
    if isinstance(evaluations, (tuple, list)):
        for evaluation in evaluations:
            if not isinstance(evaluation, Mapping):
                continue
            candidate_id = str(evaluation.get("candidate_id", ""))
            metrics = evaluation.get("metrics", ())
            if isinstance(metrics, Mapping):
                pairs = tuple(metrics.items())
            elif isinstance(metrics, (tuple, list)):
                pairs = metrics
            else:
                pairs = ()
            for item in pairs:
                if isinstance(item, (tuple, list)) and len(item) == 2 and isinstance(item[1], (int, float)):
                    values.setdefault(candidate_id, float(item[1]))
                    break
    plotted = [(str(candidate.get("id", "")), values.get(str(candidate.get("id", "")), 0.0)) for candidate in candidates]
    if not plotted:
        return ""
    low = min(value for _identifier, value in plotted)
    high = max(value for _identifier, value in plotted)
    span = high - low or 1.0
    points = []
    for index, (identifier, value) in enumerate(plotted):
        x = 40 + (index * 560 / max(1, len(plotted) - 1))
        y = 160 - ((value - low) / span * 110)
        color = "#18794e" if identifier in front_ids else "#8b95a1"
        points.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}"><title>{escape(identifier)}: {value:.4f}</title></circle>'
        )
    return (
        '<svg class="pareto-plot" viewBox="0 0 640 190" role="img" aria-label="Pareto 前沿散点图">'
        '<line x1="40" y1="160" x2="600" y2="160" stroke="#cfd5dc"/>'
        '<line x1="40" y1="20" x2="40" y2="160" stroke="#cfd5dc"/>'
        + "".join(points)
        + '<text x="48" y="182" fill="#6b7280" font-size="10">候选排序</text>'
        + '<text x="48" y="16" fill="#6b7280" font-size="10">数值指标</text></svg>'
    )


def _recommendation(candidates: Sequence[Mapping[str, object]], front_ids: Sequence[str], evaluations: object) -> dict[str, object]:
    if not candidates:
        return {}
    candidate_id = next((item for item in front_ids if any(str(candidate.get("id")) == item for candidate in candidates)), str(candidates[0].get("id", "")))
    candidate = next(item for item in candidates if str(item.get("id")) == candidate_id)
    return {
        "candidate_id": candidate_id,
        "reason": "位于当前 Pareto 前沿，且保留完整参数、约束和多学科数值证据。",
        "front_rank": list(front_ids).index(candidate_id) + 1 if candidate_id in front_ids else None,
        "feasible": bool(candidate.get("feasible", False)),
        "formal_status": "development",
        "numeric_evidence_count": len(_numeric_metrics(evaluations)),
    }


__all__ = ["ConceptWorkflowOrchestrator", "ConceptWorkflowRequest", "ConceptWorkflowResult"]
