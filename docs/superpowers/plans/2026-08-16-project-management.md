# 项目管理与需求删除实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** 将现有 workspace 管理改造成多项目卡片入口，支持展开项目查看需求，并安全删除当前需求、清理派生模型、保留审计历史。

**Architecture:** 复用现有 workspace 作为项目实体，新增项目管理首页视图，不改变 workspace 目录结构。需求删除由纯 workbench 变换负责当前数据清理，由 WebFacade 负责剩余需求模型重建和事务审计；项目卡片只读取现有 workspace 与 requirement ledger。

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, SQLite, 原生 details/summary, pytest。

## Global Constraints

- 不新增 Project 表、第二套项目 ID 或新的数据库迁移。
- 删除需求时不删除项目目录、profile、原始输入文件、运行记录和审计事件。
- 删除后的 requirement ledger 使用 \`deleted\` 状态，不能重新进入当前需求集合。
- 自动生成的场景、RFLP、MBSE、baseline 不能继续引用已删除 Requirement。
- 手动场景保留，只移除已删除 Requirement ID 的关联。
- 项目卡片默认折叠，使用原生 HTML，不增加 JavaScript 依赖。
- 所有写入通过现有 SQLite 事务完成，失败时整体回滚。

---

### Task 1: Add failing domain and repository tests

**Files:**
- Modify: \`tests/application/test_requirements_workbench.py\`
- Modify: \`tests/adapters/test_sqlite_repository.py\`
- Modify: \`tests/application/test_web_facade.py\`

**Interfaces:**
- Consumes: \`empty_workbench\`, \`build_scenario\`, \`SQLiteRepository\`, and \`WebFacade\`.
- Produces: deletion transformation, ledger tombstone, and project summary contracts.

- [x] **Step 1: Define pure deletion tests**

Use a fixture with two claims, linked structured requirements, one automatic scenario per claim, one manual scenario linked to both, non-empty RFLP/MBSE/baseline, and review queue entries. Assert deleting one claim removes its structured requirement and automatic scenario, keeps the manual scenario while removing only the deleted ID, clears derived model fields, and keeps the other claim.

- [x] **Step 2: Define last-requirement and invalid-ID tests**

Assert deleting the only claim leaves an empty current workbench and no automatic scenarios, while an unknown ID raises \`ContractViolation\` without changing state.

- [x] **Step 3: Define ledger tombstone tests**

Save one requirement record, mark it deleted, reload it, and assert \`status == "deleted"\`, preserved \`first_sequence\`, updated \`last_sequence\`, and a final history item whose event is \`requirements.deleted\`.

- [x] **Step 4: Run focused tests and confirm failure**

\`\`\`bash
RFLP_CONFIG_DIR=/tmp/rflp-lite-test-config-20260816-empty ./.venv/bin/python -m pytest -q tests/application/test_requirements_workbench.py tests/adapters/test_sqlite_repository.py tests/application/test_web_facade.py -k "delete or project"
\`\`\`

Expected: failure because the deletion transformation, repository tombstone method, and project summary interface do not exist.

---

### Task 2: Implement safe requirement deletion and ledger tombstones

**Files:**
- Modify: \`src/rflp_lite/application/requirements_workbench.py\`
- Modify: \`src/rflp_lite/adapters/sqlite_repository.py\`
- Modify: \`src/rflp_lite/application/web_facade.py\`

**Interfaces:**
- Produces \`remove_requirement(state, requirement_id) -> tuple[dict[str, object], dict[str, object]]\`.
- Produces \`SQLiteRepository.mark_requirement_deleted(requirement_ids, sequence, event)\`.
- Produces \`WebFacade.delete_requirement(workspace_name, requirement_id) -> dict[str, object]\`.

- [x] **Step 1: Add the pure workbench transformation**

Implement:

\`\`\`python
def remove_requirement(
    state: dict[str, object], requirement_id: str
) -> tuple[dict[str, object], dict[str, object]]:
    """Remove one current claim and return state plus deletion metadata."""
\`\`\`

Clone the state, validate the current claim, remove its linked structured requirement and review/change-set entries, and identify orphaned span/region IDs. Remove only system/domain-pack/LLM candidates whose source is orphaned. Remove automatic scenarios generated from the requirement and filter the ID from manual scenarios. Remove runs for deleted scenarios. Clear \`rflp\`, \`draft\`, \`draft_graph\`, \`svg\`, \`mbse\`, \`baseline\`, \`trace_links\`, \`trace_coverage\`, \`traceability\`, \`project\`, and \`auto_analysis\`. If no claims remain, clear current spans, document regions, entities, system context, and automatic discovery output while retaining artifact metadata.

Return removed claim IDs, structured requirement IDs, orphaned source IDs, and scenario IDs in metadata.

- [x] **Step 2: Add the SQLite ledger tombstone**

For each existing ledger row, append a bounded deletion history item, set SQL and payload status to \`deleted\`, preserve \`first_sequence\`, and update \`last_sequence\` and \`updated_at\`. Ignore unknown IDs after facade validation.

- [x] **Step 3: Extend the save boundary**

Add \`deleted_requirement_ids: tuple[str, ...] = ()\` to \`_save_requirements\`. After the primary audit event and current records are saved, call \`mark_requirement_deleted\` with the same sequence.

- [x] **Step 4: Implement the facade use case**

Call \`remove_requirement\`. When claims remain, run \`confirm_requirements\`, \`generate_model\`, \`approve_workbench_baseline\`, \`generate_mbse_revision\`, and \`generate_scenario_matrix\` with the default pack. When no claims remain, leave derived fields cleared. Save with event \`requirements.deleted\`, deletion metadata, and the deleted ID tuple.

- [x] **Step 5: Run domain and facade tests**

\`\`\`bash
RFLP_CONFIG_DIR=/tmp/rflp-lite-test-config-20260816-empty ./.venv/bin/python -m pytest -q tests/application/test_requirements_workbench.py tests/adapters/test_sqlite_repository.py tests/application/test_web_facade.py -k "delete or project"
\`\`\`

Expected: pass.

---

### Task 3: Add project summaries and the project-management page

**Files:**
- Modify: \`src/rflp_lite/application/web_facade.py\`
- Modify: \`src/rflp_lite/interface/web/routes.py\`
- Create: \`src/rflp_lite/interface/web/templates/project-management.html\`
- Modify: \`src/rflp_lite/interface/web/templates/base.html\`
- Test: \`tests/interface/web/test_pages.py\`

**Interfaces:**
- Produces \`WebFacade.project_summaries() -> tuple[dict[str, object], ...]\`.
- Root \`GET /\` renders the project-management template.
- Project-specific \`GET /w/{workspace_name}\` remains the existing dashboard.

- [x] **Step 1: Build deterministic project summaries**

Iterate \`self.workspaces()\` by name. For each workspace collect its ref, current requirement items, requirement counts, latest run, and model label (\`正式模型\`, \`草稿\`, or \`未生成\`). Expose only current requirements to the project card; the detailed ledger remains in the workbench.

- [x] **Step 2: Change only the root route**

Pass \`projects=facade.project_summaries()\` to the new template. Empty roots show the existing create-project form. Keep \`/w/{workspace_name}\` rendering the current single-project dashboard.

- [x] **Step 3: Render collapsed project cards**

Render one \`<details class="project-card">\` without an \`open\` attribute. The summary shows project name, current requirement count, accepted count, model state, and “打开项目”. The body lists current requirements with a project link, stable ID, status, and delete form. Empty projects show “暂无需求” and an input link.

- [x] **Step 4: Update navigation**

Make desktop and mobile “开始项目” links always point to \`/\`; preserve the selected workspace name in the top bar and all module links.

- [x] **Step 5: Add and run page tests**

Create two workspaces with different requirements. Assert \`GET /\` has two collapsed project cards, each card contains only its own requirement, links target the matching project, and an empty workspace has the empty state.

\`\`\`bash
RFLP_CONFIG_DIR=/tmp/rflp-lite-test-config-20260816-empty ./.venv/bin/python -m pytest -q tests/interface/web/test_pages.py
\`\`\`

Expected: pass.

---

### Task 4: Add deletion route and UI coverage

**Files:**
- Modify: \`src/rflp_lite/interface/web/routes.py\`
- Modify: \`src/rflp_lite/application/web_facade.py\`
- Modify: \`src/rflp_lite/interface/web/templates/requirements-overview.html\`
- Modify: \`src/rflp_lite/interface/web/templates/requirements-input.html\`
- Test: \`tests/interface/web/test_pages.py\`
- Test: \`tests/interface/web/test_api_v1.py\`

**Interfaces:**
- Consumes \`WebFacade.delete_requirement\`.
- Produces the HTML delete POST, visible \`已删除\` ledger status, and consistent browser-facing behavior.

- [x] **Step 1: Add the HTML deletion route**

Add \`POST /w/{workspace_name}/requirements/delete\` with form field \`requirement_id\`. Call the facade and redirect to \`/\`; route errors use existing handling. Do not delete workspace or input files.

- [x] **Step 2: Add deleted status presentation**

Add \`"deleted": "已删除"\` to overview labels. Deleted ledger rows show a status badge but no current badge and no delete button. Input and project pages show the empty state after the last current claim is deleted.

- [x] **Step 3: Test the deletion flow**

Submit a requirement, capture its ID, POST the delete route, assert redirect to \`/\`, assert the project card remains, assert the requirement is absent from current items, assert the ledger shows \`已删除\`, and assert audit contains \`requirements.deleted\`. Add a two-requirement case proving only the selected requirement and its generated scenario references are removed.

- [x] **Step 4: Run focused web tests**

\`\`\`bash
RFLP_CONFIG_DIR=/tmp/rflp-lite-test-config-20260816-empty ./.venv/bin/python -m pytest -q tests/interface/web/test_pages.py tests/interface/web/test_api_v1.py
\`\`\`

Expected: pass.

---

### Task 5: Documentation and full verification

**Files:**
- Modify: \`README.md\`
- Modify: \`docs/DEVELOPMENT_STATUS.md\`
- Modify: \`docs/superpowers/plans/2026-08-16-project-management.md\`

**Interfaces:**
- Consumes: completed project summary, card UI, deletion route, ledger tombstone, and tests.
- Produces: documented project hierarchy and verified implementation.

- [x] **Step 1: Document the project hierarchy**

Update the Web UI instructions to state that \`/\` manages multiple projects, each project opens its own requirement workbench, project cards expand to show requirements, and deleting a requirement preserves audit history while clearing derived outputs.

- [x] **Step 2: Run formatting and full tests**

\`\`\`bash
git diff --check
RFLP_CONFIG_DIR=/tmp/rflp-lite-test-config-20260816-empty ./.venv/bin/python -m pytest -q
\`\`\`

Expected: all tests pass with only the known Starlette/httpx deprecation warning.

- [x] **Step 3: Verify the active project set**

Use read-only checks against \`/\` and the active workspace requirements API. Confirm cards are collapsed, the project remains after deletion, and deleted records remain in the ledger.

- [ ] **Step 4: Commit implementation files only**

Stage only files changed for this feature and commit with message \`feat: add project management and requirement deletion\`.
