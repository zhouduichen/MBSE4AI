# AI4MBSE Professional Domain-Neutral MBSE Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有基本交互逻辑的前提下，交付隔离可靠、需求可编辑可删除、一次分析自动生成完整 MBSE 语义模型与专业多视图、默认不依赖领域包且可配置常见领域包的 AI4MBSE 工作流。

**Architecture:** 沿用现有 WebFacade、SQLite revision、LLM bridge 和 SVG 输出链路，新增“项目作用域校验 → 一次性领域中立分析 → 版本化 MBSE 语义模型 → 视图编译 → 可选专业引擎渲染 → fallback”的垂直切片。Graphviz、PlantUML 和矩阵渲染均作为适配器，不引入微服务、独立数据库或强制用户配置。

**Tech Stack:** Python 3、SQLite、现有 Web API/HTML/CSS、确定性 SVG、Graphviz DOT、PlantUML、pytest；外部绘图引擎可选，未安装或执行失败时使用内置 SVG fallback。

## Global Constraints

- 所有读取、写入、删除、渲染和 LLM 分析都必须绑定当前 workspace/project scope，禁止跨项目复用 requirements、analysis、diagram cache 或 revision。
- 默认分析配置为 domain pack disabled；没有领域包也必须自动生成通用的利益相关方、场景、需求、功能、逻辑、物理和追踪关系。
- 一次用户提交只触发一次主分析请求；后续派生视图使用同一份已保存的语义模型，不重复调用 LLM。
- 常见领域包只作为可选增强配置，保存 pack id/version 与 provenance；窄领域暂不提供。
- 用户输入界面、提交入口、自动生成场景的现有使用方式保持不变；新增配置只放在可选的高级入口。
- 用户手工编辑、确认、删除后的结果不能被重渲染或重新分析静默覆盖；重新分析必须产生新的 revision 或显式替换操作。
- LLM 只负责语义分析和关系建议，不输出布局坐标、SVG、HTML 或引擎私有语法。
- 图表布局由视图类型决定，不能所有图共用一种布局；树、流程、交互网络、序列图和矩阵分别使用适合的布局。
- 图表引擎是可选运行能力，所有引擎都必须有超时、格式白名单、失败可解释和 deterministic fallback。
- 保留现有 legacy MBSE projection 与接口兼容层，避免破坏已有客户端和测试。
- 保护工作区中用户已有未提交修改；只提交本计划涉及且经过检查的文件，不提交 .superpowers、缓存、临时渲染产物或密钥。
- 每个阶段都必须先增加失败测试，再实现最小改动，并运行对应的 focused tests。

## Task 1: Enforce project scope and requirement lifecycle

**Files:**
- Modify src/rflp_lite/application/project_scope.py
- Modify src/rflp_lite/application/workbench_schema.py
- Modify src/rflp_lite/application/web_facade.py
- Modify src/rflp_lite/application/requirements_workbench.py
- Modify src/rflp_lite/adapters/sqlite_repository.py
- Modify src/rflp_lite/interface/web/routes.py
- Modify src/rflp_lite/interface/web/api.py
- Modify requirement/workspace templates and static scripts only where existing delete/edit controls are wired
- Add or extend tests/application/test_project_scope.py
- Add or extend tests/application/test_requirements_workbench.py
- Add or extend tests/adapters/test_sqlite_repository.py
- Add or extend tests/interface/web/test_requirement_lifecycle.py

**Interfaces and invariants:**
- bind_project_scope(workspace_name, project_id, ...)
- validate_project_scope(workspace_name, project_id, resource_project_id)
- validate_project_references(project_id, state)
- remove_requirement(project_id, requirement_id, actor, reason)
- _save_requirements(..., project_id=...)
- Delete must create a revision/tombstone or equivalent audit record and must not delete another project’s object.
- A requirement not present in the active revision must not reappear from stale analysis or stale render cache.

**Steps:**
- [ ] Add failing tests for cross-project reads, cross-project writes, cross-project deletes, unknown requirement ids, and deletion followed by reload.
- [ ] Fix scope binding at every WebFacade and repository entry point, including analysis state, diagram state and revision state.
- [ ] Fix revision-number allocation and transaction boundaries; remove any accidentally concatenated SQL statements in sqlite_repository.py.
- [ ] Implement requirement deletion with explicit project validation, revision persistence, audit metadata and idempotent not-found behavior.
- [ ] Ensure editing a requirement updates the selected project revision and keeps derived provenance/trace links consistent.
- [ ] Keep existing routes and UI interaction shape; only expose the corrected delete/edit behavior through current controls.
- [ ] Run focused tests and git diff --check.
- [ ] Commit this slice as fix: enforce project isolation and requirement lifecycle.

## Task 2: Make automatic analysis domain-neutral by default

**Files:**
- Modify src/rflp_lite/application/intelligence/project_analysis.py
- Modify src/rflp_lite/application/intelligence/service.py
- Modify src/rflp_lite/application/intelligence/bridge.py
- Modify src/rflp_lite/application/web_facade.py
- Modify src/rflp_lite/application/llm_profiles.py
- Modify src/rflp_lite/interface/web/routes.py
- Modify src/rflp_lite/interface/web/api.py
- Modify src/rflp_lite/interface/web/templates/requirements-input.html
- Modify src/rflp_lite/interface/web/templates/project-management.html
- Extend tests/application/intelligence/test_project_analysis.py
- Extend tests/interface/web/test_auto_requirements.py
- Add tests/interface/web/test_analysis_config.py

**Interfaces and invariants:**
- normalize_analysis_config(config) -> AnalysisConfig
- WebFacade.analysis_config(project_id) -> AnalysisConfig
- WebFacade.save_analysis_config(project_id, config) -> AnalysisConfig
- build_project_analysis_request(state, config=None)
- apply_project_analysis(project_id, response, source=...)
- mark_llm_waiting(project_id, request_id, ...)
- Default config must serialize as enabled: false, domain_pack_id: null, domain_pack_version: null.
- A valid response must be normalized into environment, stakeholder hierarchy, concern/need/requirement categories, lifecycle, use cases, operational scenarios, functional analysis, logical/physical architecture, allocations, technical requirements and traceability relations.
- Missing optional sections get deterministic derived content; invalid required structure gets a visible error and never silently generates a partial successful model.

**Steps:**
- [ ] Add failing tests proving a normal project with no domain pack still creates complete analysis sections and scenarios.
- [ ] Add a test proving one submission invokes the model once and all views are rendered from the stored result.
- [ ] Add configuration normalization and persistence with optional pack id/version and provenance, without adding a required user step.
- [ ] Remove hard-coded default pack selection from the normal path; retain explicit common-domain pack registration as an advanced configuration path.
- [ ] Normalize LLM output into a domain-neutral canonical response, including stable ids and source/producer metadata.
- [ ] Keep the existing automatic scenario generation path and improve only its domain-pack dependency and completeness guarantees.
- [ ] Add user-visible waiting, failure and retry metadata without changing the main submit interaction.
- [ ] Run focused tests and verify no default response contains a fixed-domain example.

## Task 3: Introduce a versioned MBSE semantic model

**Files:**
- Add src/rflp_lite/application/mbse_semantics.py
- Modify src/rflp_lite/domain/mbse.py
- Modify src/rflp_lite/application/mbse_modeling.py
- Modify src/rflp_lite/application/mbse_exchange.py
- Modify src/rflp_lite/application/workbench_schema.py
- Modify src/rflp_lite/application/traceability.py
- Add tests/application/test_mbse_semantics.py
- Extend tests/application/test_mbse_modeling.py
- Extend tests/application/test_mbse_exchange.py
- Extend tests/application/test_traceability.py

**Interfaces and invariants:**
- MBSE_SEMANTIC_MODEL_VERSION = 2
- build_mbse_semantic_model(analysis, revision, provenance) -> dict
- validate_mbse_semantic_model(model) -> list[ValidationIssue]
- legacy_mbse_projection(model) -> dict
- mbse_entity_index(model) -> dict[str, Entity]
- generate_mbse_revision(project_id, analysis_id, source_revision_id) -> MBSERevision
- Top-level sections must include operational, functional, logical, physical and technical requirements.
- Every entity has stable id, kind, name, status, source and producer metadata.
- Relations have stable id, kind, source id, target id and optional evidence/confidence.
- Unknown relation endpoints and duplicate ids are rejected before rendering.
- needs_analysis is explicit and distinct from empty content.
- Legacy actors/use_cases/activities/lifelines/messages/trace_links remain available through projection.

**Steps:**
- [ ] Write contract tests for complete models, incomplete models, duplicate ids, unknown endpoints, unsupported relation kinds and legacy projection.
- [ ] Define the versioned schema and normalization helpers without embedding any layout coordinate.
- [ ] Build operational content: environment, stakeholders, stakeholder hierarchy, concerns, needs, use cases, lifecycle and operational scenarios.
- [ ] Build functional content: function decomposition, external/internal flows, functional scenarios and requirement satisfaction links.
- [ ] Build logical/physical content: logical decomposition, logical interactions, physical build blocks, physical interactions and allocation relations.
- [ ] Build technical requirements, categories and full cross-level traceability.
- [ ] Connect the existing confirmation/edit flow to semantic entities and ensure modifications create a new revision.
- [ ] Keep old MBSE APIs working by projecting the new model to the legacy shape.
- [ ] Run focused tests and add round-trip exchange coverage.

## Task 4: Add a view registry and professional diagram compilers

**Files:**
- Add src/rflp_lite/application/mbse_views.py
- Add src/rflp_lite/application/mbse_graphviz.py
- Add src/rflp_lite/application/mbse_plantuml.py
- Add src/rflp_lite/application/mbse_matrix.py
- Modify src/rflp_lite/application/mbse_render.py
- Add tests/application/test_mbse_views.py
- Add tests/application/test_mbse_graphviz.py
- Add tests/application/test_mbse_plantuml.py
- Add tests/application/test_mbse_matrix.py
- Extend tests/application/test_mbse_render.py

**Interfaces:**
- MBSE_VIEW_DEFINITIONS
- list_mbse_views(model) -> list[MBSEViewDefinition]
- compile_mbse_view(model, view_id, options=None) -> CompiledView
- compile_graphviz_view(model, view_id, options=None) -> str
- compile_plantuml_view(model, view_id, options=None) -> str
- render_matrix_view(model, view_id, options=None) -> str
- render_mbse_svg(model, view_id, options=None) -> str

**Required view ids and layouts:**
- environment: radial or layered external-system exchange layout.
- stakeholder_hierarchy: top-down hierarchy with concern/need annotations.
- requirements_tree: top-down categorized requirement tree.
- lifecycle: left-to-right phase/state flow with transition labels.
- use_case_tree: top-down use-case decomposition.
- operational_scenario: sequence layout with actors, systems and messages.
- function_tree: top-down function decomposition with external/internal flow edges.
- function_interaction: left-to-right directed interaction network.
- functional_scenario: activity/swimlane layout with guard and outcome labels.
- logical_tree: top-down logical decomposition.
- logical_interaction: left-to-right ports/flow layout.
- allocation_matrix: row/column allocation table with traceability markers.
- physical_interaction: architecture graph with typed interfaces and direction.
- technical_requirements: categorized requirement tree.
- traceability_matrix: source-target relation matrix with relation-kind legend.
- rflp: overview flow from requirement through function, logical and physical levels.

**Steps:**
- [ ] Add failing registry tests for all view ids, view-specific layout policy, empty and needs-analysis states, and legacy view aliases.
- [ ] Implement a semantic-to-DOT compiler with escaped labels, stable ordering, clusters, legends, typed edges and per-view rank direction. Use top-down for decomposition trees, left-to-right for flows and overview, and clusters for boundaries.
- [ ] Implement PlantUML sequence compilation for operational scenarios and activity/swimlane compilation for functional scenarios, preserving message, guard and actor semantics.
- [ ] Implement matrix rendering for allocation and traceability views with row/column labels, relation markers, legend and overflow handling.
- [ ] Replace list-style MBSE SVG cards with professional compiled diagrams while retaining the existing fallback path and download behavior.
- [ ] Add deterministic snapshot or structural assertions for nodes, edges, labels and layout directives rather than brittle pixel-only tests.
- [ ] Run focused rendering tests and confirm no raw LLM response or unescaped user text is emitted into diagram source.

## Task 5: Add optional professional diagram engine adapters

**Files:**
- Add src/rflp_lite/ports/diagram_engine.py
- Add src/rflp_lite/adapters/graphviz_engine.py
- Add src/rflp_lite/adapters/plantuml_engine.py
- Add src/rflp_lite/adapters/matrix_engine.py
- Modify src/rflp_lite/application/mbse_render.py
- Modify src/rflp_lite/application/mbse_views.py
- Modify README.md
- Add tests/adapters/test_diagram_engines.py
- Extend tests/application/test_mbse_render.py

**Interfaces and behavior:**
- DiagramEngine protocol with engine_id, status(), and render(source, output_format, timeout_seconds).
- GraphvizEngine supports DOT input and SVG/PNG output when dot or a configured runtime is available.
- PlantUMLEngine supports sequence/activity source and SVG/PNG output when the configured PlantUML command is available.
- MatrixEngine is always available through the built-in deterministic renderer.
- select_diagram_engine(view_id, requested_engine=None).
- Supported output formats are an explicit allowlist; subprocesses use argument arrays, no shell, bounded timeout and captured stderr.
- Optional configuration uses AI4MBSE_GRAPHVIZ_DOT and AI4MBSE_PLANTUML_CMD or application configuration; no required setup for end users.
- Engine failure returns fallback metadata and a useful diagnostic, not a blank diagram or unhandled exception.

**Steps:**
- [ ] Add fake-runner tests for successful render, unavailable engine, timeout, invalid format, malformed source and stderr diagnostics.
- [ ] Implement engine selection and capability reporting.
- [ ] Implement Graphviz and PlantUML adapters with no mandatory runtime dependency.
- [ ] Keep MatrixEngine and built-in SVG rendering available in the base installation.
- [ ] Optionally add a Node/WASM Graphviz hook only behind capability detection; do not make it a required runtime.
- [ ] Document the optional engine path as an installation enhancement, not a user workflow prerequisite.
- [ ] Run adapter tests in an environment with no external binaries and verify fallback success.

## Task 6: Expose all views without changing the main interaction

**Files:**
- Modify src/rflp_lite/application/web_facade.py
- Modify src/rflp_lite/interface/web/routes.py
- Modify src/rflp_lite/interface/web/api.py
- Modify src/rflp_lite/interface/web/templates/mbse-diagrams.html
- Modify src/rflp_lite/interface/web/templates/requirements-input.html
- Modify src/rflp_lite/interface/web/templates/graph.html
- Modify src/rflp_lite/interface/web/templates/overview.html
- Modify src/rflp_lite/interface/web/static/app.css
- Add or extend tests/interface/web/test_mbse_views.py
- Extend existing route/API tests

**Interfaces and compatibility:**
- WebFacade.mbse_views(project_id, revision_id=None) -> list[dict]
- WebFacade.render_requirements_mbse_view(project_id, view_id, engine=None, format=svg) -> RenderedView
- Keep existing render_requirements_mbse(...) -> str behavior as a compatibility wrapper where existing clients expect raw SVG.
- Add read-only view discovery endpoint: GET /api/v1/workspaces/{workspace}/requirements/mbse/views.
- Add view rendering endpoint: GET /api/v1/workspaces/{workspace}/requirements/mbse/views/{view_id}.
- Keep the current MBSE page, submit path, automatic scenario generation and download controls.
- Advanced domain-pack configuration is optional and hidden/collapsed by default.

**Steps:**
- [ ] Add failing tests for view listing, selected view rendering, engine fallback metadata and project isolation.
- [ ] Wire the semantic model and renderer through WebFacade.
- [ ] Update the MBSE page to show view cards/tabs and per-view download links while retaining current entry point.
- [ ] Show status for complete, needs-analysis, waiting and error states.
- [ ] Preserve the existing requirement input submit flow and auto-generated scenario display.
- [ ] Add optional configuration controls only where they do not add a required step or repeated user input.
- [ ] Run route/API/template tests and a local browser smoke check.

## Task 7: Connect analysis, editing, deleting and rerendering end to end

**Files:**
- Modify src/rflp_lite/application/web_facade.py
- Modify src/rflp_lite/application/requirements_flow.py
- Modify src/rflp_lite/application/synthesize.py
- Modify src/rflp_lite/application/traceability.py
- Modify src/rflp_lite/application/mbse_exchange.py
- Modify relevant web routes/templates only where integration is required
- Add tests/e2e/test_project_mbse_workflow.py
- Extend tests/application/test_synthesize.py
- Extend tests/application/test_requirements_flow.py

**End-to-end acceptance path:**
- [ ] Create two projects with overlapping requirement names and distinct input.
- [ ] Submit analysis in project A; verify stakeholders, scenarios, RFLP and MBSE views are complete for A.
- [ ] Verify project B cannot read or mutate A’s requirements, analysis, revision, or diagram.
- [ ] Edit a requirement in A; verify provenance, affected relations and all relevant views update after a new revision.
- [ ] Delete a requirement in A; verify it is absent from active requirements, semantic entities, traceability and rendered diagrams.
- [ ] Reopen A and verify the saved model and diagrams are deterministic without a second LLM call.
- [ ] Re-run analysis explicitly and verify a new analysis/revision is created, while manual edits are not silently lost.
- [ ] Verify no domain pack is needed for a general non-specialized example and optional common-domain configuration remains available.
- [ ] Verify partial/malformed LLM output produces visible needs-analysis/error state with recovery path.
- [ ] Run the complete end-to-end test file.

## Task 8: Full regression, documentation and final commit

**Files:**
- Modify README.md
- Modify docs/DEVELOPMENT_STATUS.md
- Add or update focused documentation only for delivered interfaces
- Review all implementation files from Tasks 1–7
- Do not include .superpowers, temporary PPT render directories, caches, local secrets or unrelated user artifacts

**Steps:**
- [ ] Run .venv/bin/python -m pytest -q.
- [ ] Run .venv/bin/python -m compileall -q src tests.
- [ ] Run git diff --check.
- [ ] Run a local Web smoke test covering two project scopes, edit/delete, automatic analysis and several view types.
- [ ] Review SQL, subprocess calls, HTML escaping, stable ids, project scope checks, revision behavior and error handling.
- [ ] Search for remaining default fixed-domain pack selection, placeholder diagrams, raw LLM diagram output and unbounded subprocess execution.
- [ ] Update README and development status with default behavior, optional engine setup, supported views and compatibility notes.
- [ ] Inspect git status --short and git diff --stat; stage only reviewed task files and preserve unrelated user changes by confirming they are part of this requested work.
- [ ] Commit the complete implementation as feat: deliver professional domain-neutral mbse workflow.
- [ ] Report test results, commit id and any optional engine capability limitations.

## Self-review checklist

- [ ] Every requirement, analysis, semantic model and diagram access path validates the active project scope.
- [ ] Default analysis works without a domain pack and generates complete common MBSE sections.
- [ ] One user submission produces one analysis call and multiple derived views.
- [ ] Requirement edit and delete are revision-safe and cannot resurrect stale content.
- [ ] RFLP/MBSE views use distinct professional layouts appropriate to their semantics.
- [ ] Graphviz/PlantUML are optional adapters; built-in SVG/matrix fallback works without them.
- [ ] Legacy API and existing basic interaction remain compatible.
- [ ] No placeholder or domain-specific sample content leaks into general projects.
- [ ] No new mandatory user setup, repeated prompt or additional workflow step was introduced.
- [ ] Tests cover both success and failure paths, including two-project isolation.
