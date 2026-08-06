# RFLP-Lite 任务契约执行实施计划

**日期：** 2026-08-05
**设计：** `docs/superpowers/specs/2026-08-05-rflp-lite-contract-execution-design.md`

## 任务清单

- [x] `application/project_bridge.py`：`verify_contracts_state` + `VerifyResult`（重扫 → 重算 Delta → 逐条契约 RESOLVED/UNRESOLVED）；
- [x] `application/web_facade.py`：`verify_workspace_project`（事务 + save_evidence + 审计 `project.executed`）；
- [x] `interface/web/routes.py`：`POST /w/{ws}/project/verify`；
- [x] `templates/project-bridge.html`：执行验证表单 + 执行结果面板；`app.css` 增加 `resolved`/`unresolved` badge；
- [x] `interface/cli.py`：`rflp project verify --workspace --source`；
- [x] 测试：app（缺前置、实现后全部 RESOLVED、确定性、失效）、web（422 与面板）、cli（成功与失败退出码）；
- [x] `pytest` 全量通过；`lint-imports` 3 contracts kept；`python -m build` 成功；
- [x] 写 `docs/verification/2026-08-05-contract-execution.md`；更新 `DEVELOPMENT_STATUS.md` 与 `README.md`。

## 约束提醒

- 只读重扫，不执行用户代码/子进程，保持确定性；
- 复用 `Analyze` 的扫描上限与失效语义；基线不改则不复写 `baseline` 表；
- 所有 id/哈希来自 `canonical_hash`，状态排序确定。