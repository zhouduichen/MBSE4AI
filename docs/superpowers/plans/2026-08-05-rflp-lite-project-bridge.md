# RFLP-Lite Python 项目接入实施计划

**日期：** 2026-08-05
**设计：** `docs/superpowers/specs/2026-08-05-rflp-lite-project-bridge-design.md`

## 任务清单

### T1 领域与适配器

- [x] `domain/models.py`：新增 `ActualElement`、`ActualModel` 冻结数据类；
- [x] `adapters/project_scanner.py`：确定性目录扫描（排序遍历、跳过规则、深度/数量/大小上限），Python AST / OpenAPI / JUnit 解析，返回 `ActualModel` 与摘要；
- [x] 单元测试 `tests/adapters/test_project_scanner.py`。

### T2 应用层

- [x] `application/project_bridge.py`：`reconstruct_rflp`、`approve_workbench_baseline`、`analyze_project_state`、`evidence_from_actual`、`BridgeArtifacts`；
- [x] `application/diff.py`：新增 `compare_baseline_with_actual`（不改 `calculate_delta`）；
- [x] `application/requirements_workbench.py`：`review_item`、`accept_traceable`、`generate_model` 失效时一并清空 `baseline`、`project`；
- [x] 单元测试 `tests/application/test_project_bridge.py`（含对 `examples/versioned-content-service` 的全链路与确定性）。

### T3 Web 与 CLI

- [x] `application/web_facade.py`：`approve_requirements_baseline`、`analyze_workspace_project`（事务 + 审计 + baselines/evidence/tasks 持久化）；
- [x] `interface/web/routes.py`：`/w/{ws}/project`、`/approve-baseline`、`/analyze`、`/download/{filename}` 白名单；
- [x] `templates/project-bridge.html` 页面；`templates/base.html` 导航增加“项目接入”；
- [x] `interface/cli.py`：`rflp project approve|analyze`；
- [x] Web/CLI 路由与命令测试。

### T4 验证与文档

- [x] `pytest` 全量通过；`lint-imports` 3 contracts kept；`python -m build` 成功；
- [x] 用 TestClient 走一遍 批准→分析→下载 完整流程；
- [x] 写 `docs/verification/2026-08-05-project-bridge.md`；
- [x] 更新 `docs/DEVELOPMENT_STATUS.md` 与 `README.md`。

## 约束提醒

- 不改 `application/demo.py` 与 `calculate_delta` 的既有行为；
- 不新增第三方依赖；扫描只用标准库（junitparser 沿用可选依赖用法）；
- 所有集合排序、所有 id 用 `canonical_hash`，保证字节级确定性；
- 基线批准必须是人工显式动作，LLM 代码路径不得接入；
- import-linter 契约：application 不得依赖 interface；adapters 只依赖 ports/domain。
