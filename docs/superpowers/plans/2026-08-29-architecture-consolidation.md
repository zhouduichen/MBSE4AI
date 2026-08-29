# RFLP-Lite Architecture Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. The current execution proceeds inline with focused checkpoints.

**Goal:** 在保持现有 Web、CLI、成功 API 响应、工作区布局和 SQLite Workbench 数据兼容的前提下，完成 RFLP-Lite 的架构迁移闭环。

**Architecture:** 采用 Characterize → Introduce Boundary → Delegate → Migrate → Remove Legacy 的渐进迁移。新的 Workbench 写入经过 Command、Use Case、Mutation 和 WorkbenchCommitCoordinator，通过 SQLite CAS、Audit、Trace 和 Requirement Ledger 原子提交；旧入口只承担兼容转发。

**Tech Stack:** Python 3.11+, dataclasses, typing.Protocol, SQLite, FastAPI/Jinja/HTMX, Pydantic（仅 Interface）, JSON Schema/jsonschema, pytest, Import Linter, Ruff, Pyright, setuptools build。

## Global Constraints

- SQLite 是唯一运行时持久化真源；不引入 PostgreSQL、Redis、Celery、Kafka、微服务或大型 DI Framework。
- 现有 Web 路由、CLI 命令和参数、成功响应形状、模板语义、工作区布局与旧 Workbench JSON 必须保持兼容。
- 当前工作区已有未提交改动属于用户基线；不得 reset、checkout、clean 或覆盖无关文件。
- 新 Application 代码不得导入 rflp_lite.adapters、访问 sqlite3、调用 subprocess、读取 RFLP_* 环境变量或调用 require_dependencies()。
- 新 Domain Entity 不以 dict[str, object] 作为核心模型；legacy JSON 只存在于 Mapper/兼容边界。
- 新 Workbench 写入必须使用显式 expected_revision；兼容入口可暂时使用 None。
- 结构迁移与 MBSE/LLM 算法行为改变必须分开提交。
- 每个任务结束前运行 focused tests、architecture tests，并检查架构预算不增加。

---

### Task 1: WAVE 0 — 可重复验证环境、行为基线与架构预算

**Files:**
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/pyproject.toml
- Create: /Users/huangjiahao/Downloads/AI4MBSE/scripts/verify_full.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/architecture_budget.json
- Create: /Users/huangjiahao/Downloads/AI4MBSE/pyrightconfig.json
- Create: /Users/huangjiahao/Downloads/AI4MBSE/ruff.toml
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/characterization/test_verification_contract.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/architecture/test_architecture_budget.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/characterization/test_requirements_behavior.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/characterization/test_llm_block_merge_behavior.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/characterization/test_mbse_semantics_behavior.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/characterization/test_jobs_behavior.py

**Interfaces:**
- test-full optional dependency group contains the existing dev/schema/evidence/opt/documents/web/tracking packages plus Ruff and Pyright.
- scripts/verify_full.py runs compileall, pytest, Import Linter, schema validation, Ruff, Pyright, and build in that order.
- architecture_budget.json records require_dependencies_calls, adapter_to_application_edges, module_cycles, dict_str_object_occurrences, raw_request_json_calls, web_facade_methods, and functions_over_150_lines.
- Characterization tests assert stable semantics, not the complete order-sensitive JSON blob.

- [ ] Step 1: Add a verification-contract test asserting that scripts/verify_full.py mentions compileall, pytest, lint-imports, check-jsonschema, ruff, pyright, and build.
- [ ] Step 2: Run .venv/bin/python -m pytest tests/characterization/test_verification_contract.py -q; expect failure because the script does not exist.
- [ ] Step 3: Add test-full to pyproject.toml with all currently separated test extras plus ruff and pyright. Implement verify_full.py with subprocess.run(..., check=True) and the seven gates in the Interfaces section.
- [ ] Step 4: Set Ruff rules E4,E7,E9,F,I,UP,B,S; set Pyright basic mode for src and exclude .venv, build, dist; generate architecture_budget.json with an AST scanner and measured current values.
- [ ] Step 5: Add characterization fixtures for Requirements review/delete/restore, all strict LLM blocks, MBSE semantic IDs/relations/gaps, and Job status/recovery.
- [ ] Step 6: Run .venv/bin/python -m pytest tests/characterization tests/architecture/test_dependency_boundaries.py -q and .venv/bin/python scripts/verify_full.py. Record any unavailable dependency explicitly.
- [ ] Step 7: Commit only the explicitly changed files with `git add pyproject.toml scripts/verify_full.py architecture_budget.json pyrightconfig.json ruff.toml tests/characterization/test_verification_contract.py tests/architecture/test_architecture_budget.py`, inspect `git diff --cached`, then run `git commit -m "build: establish architecture consolidation quality gates"`. Never stage a directory containing pre-existing user changes.

### Task 2: WAVE 1 — 测试环境隔离与 Adapter 循环清理

**Files:**
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/test_executor.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/test_execution_config.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/mlflow_tracking.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/run_catalog.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/readers.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/document_intelligence.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/ports/tracking.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/documents/__init__.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/documents/txt_reader.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/documents/markdown_reader.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/documents/docx_reader.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/documents/pdf_reader.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/documents/ocr.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/README.md
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/docs/DEVELOPMENT_STATUS.md
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/tests/architecture/test_dependency_boundaries.py
- Test: /Users/huangjiahao/Downloads/AI4MBSE/tests/adapters/test_test_executor.py
- Test: /Users/huangjiahao/Downloads/AI4MBSE/tests/adapters/test_mlflow_tracking.py
- Test: /Users/huangjiahao/Downloads/AI4MBSE/tests/adapters/test_readers.py
- Test: /Users/huangjiahao/Downloads/AI4MBSE/tests/adapters/test_document_intelligence.py

**Interfaces:**
- Add build_test_environment(run_root, project_dir, allowed=None) -> dict[str, str].
- Child tests see only PATH, PYTHONPATH, HOME, TMPDIR, LANG, PYTHONDONTWRITEBYTECODE, and explicit runner variables; cwd remains the project directory.
- Stable TrackingRecord lives in ports/tracking.py or Domain; no Adapter imports Application.
- Document intelligence imports public readers under adapters.documents; no cross-adapter private helper import remains.

- [ ] Step 1: Add a failing test that sets RFLP_LLM_API_KEY=SECRET_SENTINEL, runs a temporary project test that prints its environment, and asserts the sentinel is absent. Add an AST assertion that no adapter imports rflp_lite.application.
- [ ] Step 2: Run .venv/bin/python -m pytest tests/adapters/test_test_executor.py -k secret tests/architecture/test_dependency_boundaries.py -q; expect failure on inherited secrets or the MLflow reverse import.
- [ ] Step 3: Create per-run home, tmp, and output directories; construct the allowlist; retain fixed argv, shell=False, timeout, output cap, and resource limits.
- [ ] Step 4: Move RunRecord semantics to the stable Port/Domain type with a compatibility re-export if needed. Extract public TXT, Markdown, DOCX, PDF, and OCR readers; make readers.py delegate to them; remove _read_docx cross-module access.
- [ ] Step 5: Update README and DEVELOPMENT_STATUS to say 受资源约束的本地测试运行器. Run .venv/bin/python -m pytest tests/adapters/test_test_executor.py tests/adapters/test_runners.py tests/adapters/test_mlflow_tracking.py tests/adapters/test_readers.py tests/adapters/test_document_intelligence.py tests/architecture/test_dependency_boundaries.py -q and .venv/bin/lint-imports.
- [ ] Step 6: Stage only the exact files changed by this task, inspect `git diff --cached`, then run `git commit -m "security: isolate test runner and close adapter cycles"`; do not stage whole `src/rflp_lite/adapters` or `tests/adapters` directories because they contain pre-existing user changes.

### Task 3: WAVE 2A — SQLite Migration、Workbench Snapshot 与 CAS

**Files:**
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/persistence/__init__.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/persistence/migrations.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/sqlite_repository.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/ports/repositories.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/domain/errors.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/workbench/__init__.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/workbench/snapshot.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/workbench/mutation.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/workbench/commit.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/workbench/queries.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/adapters/test_sqlite_migrations.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/adapters/test_sqlite_repository_cas.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/application/workbench/test_snapshot.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/application/workbench/test_commit_coordinator.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/application/workbench/test_concurrency.py

**Interfaces:**
- MigrationRunner(path).upgrade(connection) creates schema_migrations, applies migrations in BEGIN IMMEDIATE, verifies invariants, and rolls back failures.
- SQLiteRepository.save_workbench(value, event="workbench.saved", *, expected_revision=None) preserves legacy calls and enforces CAS when a value is supplied.
- SQLiteRepository.load_snapshot(workspace) -> WorkbenchSnapshot | None returns a read-only view.
- WorkbenchCommitCoordinator.commit(mutation, *, expected_revision, expected_content_revision, event) is the only new Workbench write entry point.

- [ ] Step 1: Add tests for fresh/repeated migration, rollback injection, old payload without content_revision, stale revision conflict, concurrent first insert, C1 stale human write, and C2 Audit/Trace/Ledger rollback.
- [ ] Step 2: Run .venv/bin/python -m pytest tests/adapters/test_sqlite_migrations.py tests/adapters/test_sqlite_repository_cas.py tests/application/workbench -q; expect failure because the new contracts do not exist.
- [ ] Step 3: Add schema_migrations; add explicit revision/content_revision columns to workbench; backfill from legacy payload; retain workbench_revisions; conditional-update workbench by expected revision and raise ConcurrentModificationError on zero rows.
- [ ] Step 4: Implement immutable Snapshot and Coordinator. Copy state before mutation; run normalization, staleness checks, Trace refresh, Ledger update, Audit, and CAS save in one transaction. Do not auto-increment content_revision in this task.
- [ ] Step 5: Run .venv/bin/python -m pytest tests/adapters/test_sqlite_repository.py tests/adapters/test_sqlite_repository_concept.py tests/adapters/test_sqlite_migrations.py tests/adapters/test_sqlite_repository_cas.py tests/application/workbench -q; old save_workbench(state) calls must remain valid.
- [ ] Step 6: Stage only the exact migration, repository, error, workbench, and test files changed by this task, inspect `git diff --cached`, then run `git commit -m "refactor: add workbench snapshot migrations and cas"`; never stage an entire source or test directory.

### Task 4: WAVE 2B — Human Mutation Pipeline 与 Explicit DI

**Files:**
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/use_cases/review_requirement.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/use_cases/manage_analysis_entity.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/use_cases/requirements_analysis.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/scenarios.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/requirements_workbench.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/project_bridge.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/compile.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/ingest.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/demo.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/concept_acceptance.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse_render.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/dependencies.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/bootstrap/container.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/bootstrap/infrastructure.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/bootstrap/application.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/ports/repositories.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/contracts/test_repository_contract.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/bootstrap/test_container_wiring.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/tests/architecture/test_dependency_boundaries.py

**Interfaces:**
- Human Commands describe intent and revision, never full state.
- Requirements, entity management, scenario changes, and project mutations save through WorkbenchCommitCoordinator.
- Narrow Protocols cover Workbench, Ledger, Trace, Audit, Evidence, Concept, Run, and Job capability groups.
- Bootstrap owns concrete construction; Use Cases receive focused dependency bundles.

- [ ] Step 1: Add Repository Contract tests against fake and SQLite implementations for load/save, rollback, CAS, Audit, Ledger, and Trace; assert locator count never exceeds budget.
- [ ] Step 2: Run .venv/bin/python -m pytest tests/contracts/test_repository_contract.py tests/bootstrap/test_container_wiring.py tests/architecture/test_dependency_boundaries.py -q; expect failure on missing narrow Protocols and remaining locator calls.
- [ ] Step 3: Migrate Review Requirement first: load latest Snapshot in the Use Case, apply the existing policy to a copy, and commit with the old event name. Keep facade wrappers and response shapes.
- [ ] Step 4: Migrate requirement edit/delete/restore, stakeholder, concern/need, and scenario create/edit/review/delete one group at a time. Preserve content revision increments temporarily and remove direct new-path save_workbench calls.
- [ ] Step 5: After all human mutations use the Coordinator, increment content_revision exactly once for HUMAN_CONTENT; remove migrated business-level increments and add C1/C2/CAS tests.
- [ ] Step 6: Split repository Protocols, construct infrastructure/application in bootstrap, migrate remaining locator callers, and delete repository_method only after grep finds no callers. Remove the global registry after its public compatibility callers are gone.
- [ ] Step 7: Run .venv/bin/python -m pytest tests/contracts/test_repository_contract.py tests/bootstrap/test_container_wiring.py tests/application/workbench tests/application/use_cases tests/application/test_entity_deletion.py tests/application/test_scenarios.py tests/interface/web/test_pages.py tests/interface/web/test_api_v1.py -q and the architecture tests. Expected: all mutation flows pass and the locator budget decreases.
- [ ] Step 8: Stage only the exact files changed by this task, inspect `git diff --cached`, then run `git commit -m "refactor: route human mutations through explicit application dependencies"`; never stage whole application, bootstrap, or test directories.

### Task 5: WAVE 3 — Requirements、Typed LLM 与 Enrichment Pipeline

**Files:**
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/requirements/__init__.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/requirements/ingestion.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/requirements/review.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/requirements/stakeholders.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/requirements/concerns_needs.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/requirements/scenarios.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/requirements/generation.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/intelligence/dto.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/intelligence/merge/registry.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/intelligence/merge/system_scope.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/intelligence/merge/stakeholders.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/intelligence/merge/concerns_needs.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/intelligence/merge/requirements.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/intelligence/merge/scenarios.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/intelligence/merge/architecture.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/intelligence/enrichment_coordinator.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/intelligence/analysis_blocks.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/intelligence/validated_result.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/intelligence/enrichment_jobs.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/requirements_workbench.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/application/intelligence/test_typed_block_dto.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/application/intelligence/test_merge_registry.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/application/intelligence/test_enrichment_coordinator.py

**Interfaces:**
- Frozen Block Item DTOs include StakeholderItem, RequirementItem, ScenarioItem, ArchitectureEntityItem, and ArchitectureRelationItem.
- merge_block_result(snapshot, result) dispatches through MERGERS and returns a Mutation/Command result without persistence.
- EnrichmentCoordinator composes SnapshotGuard, BatchPlanner, BlockExecutor, BlockCommitter, ProgressReporter, and Finalizer.
- requirements_workbench.py becomes delegate/re-export only, targeting under 100 lines.

- [ ] Step 1: Add typed DTO and merge characterization tests for all six fixtures: enum/tuple/finite-float conversion, source IDs, semantic diagnostics, stable IDs, hashes, merged IDs, and no merger save_workbench calls.
- [ ] Step 2: Implement DTO parsers and Domain Commands while retaining JSON Schema as the external shape gate; perform source, namespace, duplicate, and relation checks.
- [ ] Step 3: Split Merge Registry. Move existing behavior without changing it; keep dispatch under 40 lines; return Mutation/Command with stable idempotent IDs.
- [ ] Step 4: Extract Requirements behavior into ingestion, review, stakeholders, concerns_needs, scenarios, and generation; keep old module as compatibility delegate and do not duplicate implementations.
- [ ] Step 5: Split Enrichment into planning, per-Block execution, progress, commit, and finalization; every validated Block uses the Coordinator and original snapshot content revision.
- [ ] Step 6: Record transport, parse, schema, semantic, repair attempted, repair succeeded, failure stage, and provider request ID while retaining legacy response fields. Run .venv/bin/python -m pytest tests/application/intelligence tests/application/use_cases tests/application/test_requirements_workbench.py tests/application/test_scenarios.py tests/interface/web/test_requirements_enrichment.py -q.
- [ ] Step 7: Stage only the exact Requirements, Intelligence, compatibility, and test files changed by this task, inspect `git diff --cached`, then run `git commit -m "refactor: type llm blocks and split requirements enrichment"`; never stage whole source/test directories.

### Task 6: WAVE 4 — SQLite Job、Lease Recovery 与幂等提交

**Files:**
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/ports/jobs.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/job_state.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/sqlite_job_repository.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/thread_background_executor.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/jobs.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/intelligence/enrichment_jobs.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/adapters/persistence/migrations.py
- Test: /Users/huangjiahao/Downloads/AI4MBSE/tests/adapters/test_sqlite_job_repository.py
- Test: /Users/huangjiahao/Downloads/AI4MBSE/tests/application/test_jobs_migration.py
- Test: /Users/huangjiahao/Downloads/AI4MBSE/tests/application/test_jobs_recovery.py
- Test: /Users/huangjiahao/Downloads/AI4MBSE/tests/application/intelligence/test_enrichment_coordinator.py

**Interfaces:**
- JobStatus is the only status enum: queued, running, succeeded, degraded, failed, interrupted, superseded, cancelled.
- JobRepositoryPort owns durable state; BackgroundExecutorPort.submit(job_id, runner) owns scheduling.
- SQLite jobs and job_blocks own lease, heartbeat, retry, idempotency, diagnostics, and per-block state.
- Runtime semantics are at-least-once execution plus idempotent semantic commit, not exactly-once.

- [ ] Step 1: Add failing tests for schema creation, completed→succeeded, malformed JSON rollback, no rename on failure, repeated startup without duplicate import, expired lease recovery, retry attempt, heartbeat, duplicate active idempotency key, and successful-block preservation.
- [ ] Step 2: Add JobStatus and SQLite jobs/job_blocks migration; store query fields in columns and payload/result/diagnostics in JSON text; use transaction conditions for lease and active idempotency.
- [ ] Step 3: Implement one-time jobs.json import: parse, normalize, insert transactionally, re-read and verify count/IDs/status, then rename to jobs.legacy.json; preserve original on failure.
- [ ] Step 4: Move threading.Thread to ThreadBackgroundExecutor; remove JSON, tempfile, os.replace, and file persistence from Application Job code; keep retry policy in Application.
- [ ] Step 5: Run .venv/bin/python -m pytest tests/adapters/test_sqlite_job_repository.py tests/application/test_jobs.py tests/application/test_jobs_migration.py tests/application/test_jobs_recovery.py tests/application/intelligence/test_enrichment_jobs.py tests/application/intelligence/test_enrichment_coordinator.py tests/e2e/test_cross_workspace_and_partial_failure.py -q.
- [ ] Step 6: Expected: SQLite is the only runtime Job source, completed is never emitted, recovery/retry/idempotency pass, and Application Job code has no persistence IO.
- [ ] Step 7: Stage only the exact Job, migration, Enrichment, and test files changed by this task, inspect `git diff --cached`, then run `git commit -m "refactor: move durable jobs into sqlite"`; never stage whole source/test directories.

### Task 7: WAVE 5 — MBSE Builder、Diagram Projection 与 Repository Session

**Files:**
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse/builders/context.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse/builders/operational.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse/builders/requirements.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse/builders/functional.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse/builders/logical.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse/builders/physical.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse/builders/interfaces.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse/builders/relations.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse/builders/gaps.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse_semantics.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse_views.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse_graphviz.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse_plantuml.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/mbse_matrix.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/ports/repositories.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/domain/diagram_spec.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/characterization/test_mbse_semantics_behavior.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/application/mbse/test_builder_pipeline.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/tests/architecture/test_dependency_boundaries.py

**Interfaces:**
- Typed MbseSemanticModel contains functions, logical components, physical components, interfaces, relations, and gaps.
- Public build_mbse_semantic_model(state, revision, provenance) remains compatible and delegates to an orchestration-only pipeline.
- SemanticModel → ViewProjection → DiagramSpec → DiagramRendererPort; View does not know Graphviz/PlantUML and adapters do not import View implementation.
- One request/Use Case scope owns one SQLite session/connection and its complete transaction lock.

- [ ] Step 1: Add semantic characterization tests for Function/Logical/Physical IDs, interfaces, relations, Gap IDs, technical requirements, and semantic hash.
- [ ] Step 2: Introduce typed model and legacy Mapper; parse existing state into MbseBuildContext and serialize back without changing IDs, evidence rules, predicates, provenance, or gaps.
- [ ] Step 3: Extract operational, requirement, functional, logical, physical, interface, relation, and gap builders; keep public function compatible and orchestration-only.
- [ ] Step 4: Establish DiagramSpec projection; update renderers to consume it; enforce migrated MBSE/Diagram SCCs reaching zero.
- [ ] Step 5: Narrow Repository Protocols and make transaction locking explicit while allowing the existing SQLite class to implement multiple Protocols temporarily.
- [ ] Step 6: Run .venv/bin/python -m pytest tests/application/test_mbse_semantics.py tests/application/test_mbse_semantic_gaps.py tests/application/test_mbse_modeling.py tests/application/test_mbse_views.py tests/application/test_mbse_render.py tests/application/diagrams tests/application/mbse -q and .venv/bin/python -m pytest tests/architecture/test_dependency_boundaries.py -q. Expected: semantic hashes equal and diagram tests pass.
- [ ] Step 7: Stage only the exact MBSE, Diagram, Port, and test files changed by this task, inspect `git diff --cached`, then run `git commit -m "refactor: split mbse builders and diagram projection"`; never stage whole source/test directories.

### Task 8: WAVE 6–7 — Query View、Interface 收敛、Typed Domain 与最终门禁

**Files:**
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/queries/__init__.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/queries/requirements.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/queries/workspace.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/queries/mbse.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/web_facade.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/interface/web/routes.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/interface/web/api_v1.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/interface/web/presenters.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/interface/cli.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/interface/web/error_mapper.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/interface/cli/requirements.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/interface/cli/mbse.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/interface/cli/project.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/interface/cli/concept.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/interface/cli/discovery.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/interface/cli/profile.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/domain/requirements.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/domain/mbse.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/workbench/snapshot.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/workbench_schema.py
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/docs/CURRENT_ARCHITECTURE.md
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/docs/DEVELOPMENT_STATUS.md
- Modify: /Users/huangjiahao/Downloads/AI4MBSE/architecture_budget.json
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/interface/test_query_views.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/interface/web/test_api_dto_contract.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/interface/test_cli_dispatch.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/characterization/test_workbench_round_trip.py
- Create: /Users/huangjiahao/Downloads/AI4MBSE/tests/architecture/test_no_new_legacy_paths.py

**Interfaces:**
- Query classes return frozen RequirementsPageView, WorkspaceView, and MBSE view models; templates do not consume raw Workbench state on migrated pages.
- Pydantic request models live only under Interface and convert immediately to Application Commands.
- Internal errors are typed; existing route status codes and successful response shapes remain compatible while adding error_code and diagnostics.
- WebFacade delegates, reaches zero callers, and is deleted; cli.main() becomes parser/dispatch/render under 100 lines.
- Requirements/Workbench core sections become typed with tolerant legacy Mappers; unknown extension fields survive round trips.

- [ ] Step 1: Add Query View, API, CLI, and legacy round-trip tests for view fields, success keys, CLI options, missing legacy fields, and unknown extension preservation.
- [ ] Step 2: Implement Requirements/Workspace/MBSE Query Views and central typed error mapping for ValidationError, NotFoundError, ConflictError, ConcurrentModificationError, CapabilityUnavailableError, ExternalServiceError, and InvariantViolation.
- [ ] Step 3: Convert raw JSON handlers to Interface-only Pydantic DTOs; keep explicit multipart upload handlers only with a test explaining the boundary.
- [ ] Step 4: Delegate Requirements, System Model, Verification, Workspace, Concept, and Integration calls in groups; reduce WebFacade budget 92 → 60 → 30 → 15 → 0; delete only after grep confirms no callers.
- [ ] Step 5: Split CLI command bodies by domain while retaining command names, arguments, output semantics, and exit codes.
- [ ] Step 6: Type Stakeholder, Concern, Need, Requirement, Scenario, and MBSE sections in small slices; keep old JSON keys and unknown extensions at Mapper boundary.
- [ ] Step 7: Raise migrated packages to Pyright strict, remove obsolete ignores, and lower budget values. Do not hide errors with Any, cast, or type: ignore.
- [ ] Step 8: Run .venv/bin/python scripts/verify_full.py and .venv/bin/python -m pytest tests/architecture tests/contracts tests/characterization tests/e2e -q. Expected: all gates and legacy compatibility tests pass.
- [ ] Step 9: Update CURRENT_ARCHITECTURE and DEVELOPMENT_STATUS to describe final layering, SQLite Job source, runner boundary, Typed LLM path, and remaining public compatibility. Stage only the exact files changed by this task, inspect `git diff --cached`, then run `git commit -m "refactor: close architecture consolidation and remove legacy paths"`; never stage whole source/test directories.

## Checkpoints and rollback

After Tasks 1–4, perform a checkpoint: Coordinator reduces duplicated save logic; strict CAS works with existing Web interactions; Audit/Trace/Ledger are atomic; no ApplicationAPI has become a Service Locator; invocation depth remains Route/CLI → Use Case → Coordinator → Repository.

If a focused test exposes an unexplained semantic change, keep the characterization test, stop the current Wave, and revert only the new delegation/migration commit. Never reset existing user changes. Database migrations roll back transactionally; jobs.json retains its original name until import verification succeeds. Stop if architecture budget rises, a second implementation appears, CAS is disabled to pass tests, or a structural refactor changes MBSE/LLM algorithm output.

## Final acceptance matrix

| Area | Required result |
|---|---|
| Boundaries | adapters → application = 0; application → adapters = 0; Domain has no outer imports |
| DI | require_dependencies() = 0; no global registry; new Use Cases use focused bundles |
| Workbench | all new writes use Command → Mutation → CommitCoordinator → CAS Repository |
| Persistence | versioned migrations; SQLite-only runtime Jobs; old Workbench JSON readable; rollback tested |
| LLM | Schema → Typed DTO → Semantic Validator → Command → Mutation; no direct raw-dict append |
| Jobs | unified statuses; lease/recovery/retry/idempotency; at-least-once + idempotent commit |
| MBSE | typed model; semantic-equivalent builder split; Diagram SCC = 0 |
| Interface | Query Views, Pydantic at boundary only, legacy success compatibility, WebFacade deleted |
| Security | env allowlist, isolated HOME/TMP/output, shell false, resource limits, no sandbox overclaim |
| Quality | compile, pytest, Import Linter, schema, build, Ruff, Pyright in one command |
| Maintainability | core functions <150 lines; MBSE/Enrichment orchestration <100; Merge dispatch <40 |
