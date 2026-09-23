# Vertical Model Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox ( - [ ] ) syntax for tracking.

**Goal:** Make the default product path accept natural-language requirements and generate a complete, editable R→F→L→P→V&V ModelGraph with a round-trippable SysML v2 subset.

**Architecture:** Add a five-stage product orchestrator beside the existing 23-task WorkflowRunner. Each stage reuses the existing TaskRuntime, structured-output boundary, proposal compiler, repository CAS, and graph relations, but uses a small stage contract and records semantic warnings instead of blocking on every non-fatal gap. Route the Web default action to this orchestrator while preserving explicit mode=pipeline and mode=phase compatibility paths.

**Tech Stack:** Python 3.11, dataclasses, JSON Schema, existing TaskRuntime/OpenAI-compatible runtime, SQLite ModelRepository, FastAPI/Jinja/HTMX, pytest.

## Global Constraints

- Python 3.11+ and the existing package dependencies remain unchanged.
- ModelGraph remains the only model source of truth; generated writes go through Patch and ModelRepository.append_patch.
- Generated entities use Producer.LLM and remain editable/unlocked; accepted and locked remain human-review states.
- Existing mode=pipeline and mode=phase behavior and current tests remain compatible.
- Offline RuleRuntime is allowed for deterministic development tests but is never reported as live LLM acceptance.
- Do not add a provider SDK, frontend build system, database, or full SysML parser dependency.

---

### Task 1: Extend the structured proposal envelope with stage review metadata

**Files:**
- Modify: src/rflp_lite/methodology/contracts.py, TaskExecutionResponse
- Modify: src/rflp_lite/methodology/proposal_compiler.py, TaskProposal and proposal_schema
- Modify: src/rflp_lite/runtime/structured_model.py
- Test: tests/methodology/test_proposal_compiler.py
- Test: tests/runtime/test_task_execution.py

**Interfaces:**
- Consumes: existing TaskExecutionResponse, TaskProposal, and compile_task_proposal.
- Produces: TaskProposal.assumptions, TaskProposal.open_questions, and matching TaskExecutionResponse fields.

- [ ] Step 1: Add a failing compiler test using a proposal with assumptions=[“配送区域已经定义”] and open_questions=[“是否需要人工接管”]. Assert that parse_task_proposal returns both tuples.
- [ ] Step 2: Run ./.venv/bin/python -m pytest tests/methodology/test_proposal_compiler.py tests/runtime/test_task_execution.py -q. Expected: FAIL because the fields do not exist.
- [ ] Step 3: Add defaulted tuple fields after TaskProposal.reason and TaskExecutionResponse.usage. Add optional JSON Schema properties:
  assumptions: {"type": "array", "items": {"type": "string"}}
  open_questions: {"type": "array", "items": {"type": "string"}}
  Parse them with the existing _strings helper; keep them optional for all old fixtures.
- [ ] Step 4: In StructuredModelRuntime.execute, call parse_task_proposal before compile_task_proposal and pass proposal.assumptions and proposal.open_questions into the returned TaskExecutionResponse.
- [ ] Step 5: Run the focused tests again. Expected: PASS without changing old proposal validation.
- [ ] Step 6: Commit with git add src/rflp_lite/methodology/contracts.py src/rflp_lite/methodology/proposal_compiler.py src/rflp_lite/runtime/structured_model.py tests/methodology/test_proposal_compiler.py tests/runtime/test_task_execution.py && git commit -m "feat: preserve stage assumptions and open questions"

### Task 2: Define five product-stage contracts and prompts

**Files:**
- Create: src/rflp_lite/methodology/vertical_generation.py
- Create: src/rflp_lite/resources/prompts/vertical/requirements.v1.md
- Create: src/rflp_lite/resources/prompts/vertical/functional.v1.md
- Create: src/rflp_lite/resources/prompts/vertical/logical.v1.md
- Create: src/rflp_lite/resources/prompts/vertical/physical.v1.md
- Create: src/rflp_lite/resources/prompts/vertical/verification_validation.v1.md
- Modify: pyproject.toml package-data
- Test: tests/methodology/test_vertical_generation.py

**Interfaces:**
- Consumes: TaskSpec, ContextQuery, PatchPolicy, EntityKind, RelationPredicate, and output_contract.
- Produces: VerticalStage, vertical_stage_specs(), stage_task(stage), and stage_required_kinds(stage).

- [ ] Step 1: Add failing tests asserting the order requirements, functional, logical, physical, verification_validation and that the functional task writes only FUNCTION, FUNCTIONAL_FLOW, and FUNCTIONAL_SCENARIO.
- [ ] Step 2: Run ./.venv/bin/python -m pytest tests/methodology/test_vertical_generation.py -q. Expected: FAIL because the module and resources do not exist.
- [ ] Step 3: Implement VerticalStage and immutable stage descriptors. Use these output scopes:
  requirements: SYSTEM, STAKEHOLDER, CONCERN, OPERATIONAL_SCENARIO, ACTIVITY, REQUIREMENT;
  functional: FUNCTION, FUNCTIONAL_FLOW, FUNCTIONAL_SCENARIO;
  logical: LOGICAL_COMPONENT, INTERFACE;
  physical: PHYSICAL_BLOCK, REQUIREMENT;
  verification_validation: VERIFICATION_CASE, VALIDATION_CASE.
  Give each stage only the predicates needed to connect its outputs to the current graph. Construct a TaskSpec with id vertical.<stage>, prompt id vertical.<stage> (resolved from vertical/<stage>.v1.md), schema id vertical.<stage>.v1, validators schema/identity/reference/semantic/patch_policy, max_attempts=2, and a PatchPolicy limited to that stage.
- [ ] Step 4: Write five concise prompts. Each prompt must require the TaskProposal envelope, concrete names, local_ref for new nodes, canonical IDs for existing nodes, no operations DSL, and assumptions/open_questions for uncertainty. Requirements must create a real system, stakeholders, scenario, and requirement; functional must link requirements to functions; logical must allocate functions to logical components; physical must allocate logical components to physical blocks; V&V must provide method and pass_criteria.
- [ ] Step 5: Add vertical/*.md to the existing rflp_lite package-data configuration and run ./.venv/bin/python -m pytest tests/methodology/test_vertical_generation.py tests/runtime/test_task_specific_prompts.py -q. Expected: PASS.
- [ ] Step 6: Commit with git add src/rflp_lite/methodology/vertical_generation.py src/rflp_lite/resources/prompts/vertical pyproject.toml tests/methodology/test_vertical_generation.py && git commit -m "feat: add five-stage product generation contracts"

### Task 3: Implement the product generator and deterministic offline path

**Files:**
- Create: src/rflp_lite/application/model_generation.py
- Modify: src/rflp_lite/runtime/rule_based.py
- Modify: src/rflp_lite/bootstrap/v2.py
- Test: tests/application/test_model_generation.py
- Test: tests/e2e/test_vertical_model_generation.py

**Interfaces:**
- Consumes: ModelRepository, TaskExecutor, vertical_stage_specs(), ContextBundle, Patch, and RuntimeSelection.
- Produces: GenerateModelRequest, StageResult, TraceabilitySummary, GenerateModelResult, and ModelGenerationService.generate().

- [ ] Step 1: Add failing tests. The offline test creates a project, calls services.generation("robot").generate("robot", requirement_text="系统应在校园内自主完成配送并支持人工接管"), and asserts status=completed, actual FUNCTION/LOGICAL_COMPONENT/PHYSICAL_BLOCK/VERIFICATION_CASE/VALIDATION_CASE kinds, complete_count >= 1, and no rule-created name contains 候选 or 待确认. A scripted-runtime test asserts exactly five stage calls and the ordered stage results.
- [ ] Step 2: Run ./.venv/bin/python -m pytest tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py -q. Expected: FAIL because the service and accessor do not exist.
- [ ] Step 3: Add these dataclasses:
  GenerateModelRequest(project_id, requirement_text=None, document_ids=(), run_id=None, force_new=False)
  StageResult(stage, status, revision, entity_count, relation_count, assumptions=(), open_questions=(), diagnostics=())
  TraceabilitySummary(complete_count, partial_count, missing_count, paths=())
  GenerateModelResult(run_id, project_id, status, revision, stage_results, traceability, warnings=(), sysml_text="")
- [ ] Step 4: Implement input seeding. Normalize requirement_text and append one user REQUIREMENT with statement, source=user_input, and verification_method=review unless an identical active requirement exists. Build each ContextBundle from the current graph and stage-specific active entities/relations.
- [ ] Step 5: Implement the five-stage loop. For each stage call TaskExecutor.execute(task, context, methodology_version="v2.1", token_budget=output_budget). A completed response with a patch is persisted by repository.append_patch(project_id, response.patch, graph.revision, run_id=run_id). A semantic gap becomes a warning; transport, structural, compiler, CAS, no-patch, or missing-stage errors return failed. Return completed only if all five stages apply and at least one complete trace path exists; otherwise return completed_with_warnings only when all stages applied but paths are partial.
- [ ] Step 6: Record a Run with phase=vertical_generation and one Step per stage, including selected profile/provider/model. Use the existing repository ledger and never invent a completed live run after a provider transport failure.
- [ ] Step 7: Add VerticalRuleRuntime or a vertical branch in RuleRuntime. It must generate concrete validated nodes and real relations: one function per active requirement, one logical component allocated from each function, one physical block allocated from each logical component, and verification plus validation cases linked to every requirement. It must not create placeholder names.
- [ ] Step 8: Add V2Services.generation(project_id) that selects the same active runtime/profile as analysis(project_id) and returns ModelGenerationService.
- [ ] Step 9: Run ./.venv/bin/python -m pytest tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py tests/e2e/test_campus_delivery_robot.py -q. Expected: PASS.
- [ ] Step 10: Commit with git add src/rflp_lite/application/model_generation.py src/rflp_lite/runtime/rule_based.py src/rflp_lite/bootstrap/v2.py tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py && git commit -m "feat: generate complete model through vertical stages"

### Task 4: Replace the SysML export shell with a deterministic subset and reader

**Files:**
- Create: src/rflp_lite/application/sysml_v2.py
- Modify: src/rflp_lite/application/model_export.py
- Test: tests/application/test_sysml_v2.py

**Interfaces:**
- Consumes: ModelGraph, Entity, Relation, EntityKind, and RelationPredicate.
- Produces: graph_to_sysml(graph), sysml_to_graph(text, project_id), and backwards-compatible graph_sysml(graph).

- [ ] Step 1: Add a failing test that builds a complete graph, exports it, reads it back, and compares all entity IDs, kinds, names, payloads, and (source_id, predicate, target_id) triples.
- [ ] Step 2: Run ./.venv/bin/python -m pytest tests/application/test_sysml_v2.py -q. Expected: FAIL because there is no reader and the old exporter only provides comments.
- [ ] Step 3: Render each entity as a real subset declaration plus one canonical JSON metadata comment. Use part def for system/logical/physical, requirement def for requirement, action def for function, interface def for interface/functional_flow, and part def for remaining kinds. Use JSON metadata to preserve id, kind, name, status, producer, confidence, source/evidence/lifecycle IDs, revisions, and payload.
- [ ] Step 4: Render core relations as satisfy source by target, allocate source to target, verify source by target, or validate source by target. Add one JSON relation metadata comment for every relation so non-core predicates and evidence IDs also round-trip.
- [ ] Step 5: Implement sysml_to_graph without new dependencies. Check the package envelope, parse entity/relation metadata, reject duplicate IDs and missing endpoints, instantiate EntityMeta with the original IDs, create ModelGraph, and call validate_relation for every relation.
- [ ] Step 6: Make graph_sysml return graph_to_sysml and run ./.venv/bin/python -m pytest tests/application/test_sysml_v2.py tests/interface/web/test_resource_api.py -q. Expected: PASS.
- [ ] Step 7: Commit with git add src/rflp_lite/application/sysml_v2.py src/rflp_lite/application/model_export.py tests/application/test_sysml_v2.py && git commit -m "feat: add round-trippable SysML v2 subset"

### Task 5: Route the default Web/API analysis action to vertical generation

**Files:**
- Modify: src/rflp_lite/interface/web/resource_api.py
- Modify: src/rflp_lite/interface/web/templates/analysis.html
- Modify: src/rflp_lite/interface/web/resource_pages.py
- Modify: src/rflp_lite/application/analysis_service.py only if a facade method is needed
- Test: tests/interface/web/test_vertical_generation_api.py
- Modify: tests/interface/web/test_analysis_workflow.py

**Interfaces:**
- Consumes: ModelGenerationService.generate, graph_to_sysml, sysml_to_graph, and existing resource projections.
- Produces: POST /projects/{project_id}/analysis with mode=generate, a default UI action using that mode, and POST /projects/{project_id}/sysml/import.

- [ ] Step 1: Add a failing API test that posts mode=generate and requirement_text, then asserts run.mode=generate, five ordered stage_results, and traceability.complete_count >= 1. Add a failing import test that exports a model and imports its text into a fresh project.
- [ ] Step 2: Run ./.venv/bin/python -m pytest tests/interface/web/test_vertical_generation_api.py -q. Expected: FAIL because dispatch and import route do not exist.
- [ ] Step 3: In run_analysis, dispatch mode in generate/vertical to the generation accessor, pass requirement_text/document_ids/run_id/force_run, serialize with _plain, and leave explicit pipeline/phase branches unchanged. If requirement_text is supplied to an empty project, generation seeds it before input checks.
- [ ] Step 4: Add POST /projects/{project_id}/sysml/import. Read UTF-8 request content, call sysml_to_graph, reject conflicting IDs in a non-empty target, turn imported entities/relations into one sysml.import Patch, append it at the current revision, and return revision plus counts.
- [ ] Step 5: Change the main analysis form to submit mode=generate and label the action 生成完整 MBSE 模型. Render the five stage statuses, counts, traceability summary, assumptions, and open questions above the legacy run ledger. Keep phase buttons under 高级阶段调试 and send mode=phase unchanged.
- [ ] Step 6: Run ./.venv/bin/python -m pytest tests/interface/web/test_vertical_generation_api.py tests/interface/web/test_analysis_workflow.py tests/interface/web/test_resource_api.py -q. Expected: PASS; explicit pipeline and phase tests remain green.
- [ ] Step 7: Commit with git add src/rflp_lite/interface/web/resource_api.py src/rflp_lite/interface/web/templates/analysis.html src/rflp_lite/interface/web/resource_pages.py src/rflp_lite/application/analysis_service.py tests/interface/web/test_vertical_generation_api.py tests/interface/web/test_analysis_workflow.py && git commit -m "feat: route default analysis to complete model generation"

### Task 6: Add product-level acceptance evidence and update documentation

**Files:**
- Create: tests/e2e/fixtures/vertical_delivery_robot_input.txt
- Create: tests/e2e/test_natural_language_to_mbse.py
- Create: tests/application/test_generation_traceability.py
- Modify: README.md
- Modify: docs/DEVELOPMENT_STATUS.md
- Modify: docs/CURRENT_ARCHITECTURE.md

**Interfaces:**
- Consumes: complete generation service, traceability summary, SysML reader/writer.
- Produces: natural-language-starting E2E proof and docs that distinguish product generation from legacy Harness benchmarks.

- [ ] Step 1: Add an E2E test that starts from fixture text, calls ModelGenerationService.generate, exports and re-reads SysML, asserts status=completed, complete_count >= 1, real F/L/P entities, and equal entity/relation counts after round-trip.
- [ ] Step 2: Add traceability assertions for every generated active requirement: non-empty function, logical, physical, and verification/validation targets; no placeholder-only names; user editing creates a new revision while preserving generated IDs.
- [ ] Step 3: Update README short path to project create, analyze generate with text, model export --format sysml, and model import-sysml. Document explicit pipeline/phase as compatibility/research mode and report progress by complete R→F→L→P→V&V paths, editable ModelGraph, and SysML round-trip.
- [ ] Step 4: Run the complete verification suite:
  ./.venv/bin/python -m pytest -q
  ./.venv/bin/python -m compileall -q src
  ./.venv/bin/python scripts/architecture_metrics.py
  ./.venv/bin/lint-imports
  Expected: existing tests and the new natural-language E2E pass with no forbidden dependency direction.
- [ ] Step 5: Commit with git add tests/e2e/fixtures/vertical_delivery_robot_input.txt tests/e2e/test_natural_language_to_mbse.py tests/application/test_generation_traceability.py README.md docs/DEVELOPMENT_STATUS.md docs/CURRENT_ARCHITECTURE.md && git commit -m "test: prove natural language to editable mbse model"

## Self-Review

- Spec coverage: Tasks 1–3 implement the five-stage LLM generation path and warnings; Task 4 implements SysML subset export/read; Task 5 makes generation the default API/UI product path; Task 6 proves the requested product-level acceptance metrics.
- Placeholder scan: no TBD, TODO, implement-later, or undefined file/function references remain. “Expected before the implementation is complete” is test baseline language, not an implementation placeholder.
- Type consistency: ModelGenerationService.generate returns GenerateModelResult; V2Services.generation supplies that service; graph_to_sysml and sysml_to_graph are the stable exchange functions; graph_sysml remains an alias.
