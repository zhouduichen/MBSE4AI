# RFLP-Lite 测试执行沙箱实施计划

**日期：** 2026-08-06
**设计：** `docs/superpowers/specs/2026-08-06-rflp-lite-test-execution-design.md`

## 任务清单

- [x] `adapters/test_executor.py`：`TestRun` + `run_project_tests`（固定 pytest 命令、强制超时、临时目录隔离、`_normalize_junit` 归一化确定性）；
- [x] `application/project_bridge.py`：提取 `_build_execution` 共享重算；新增 `execute_tests_state`（跑测试 → 回填 JUnit Evidence → 重算执行状态）；
- [x] `application/web_facade.py`：`test_workspace_project`（事务 + save_evidence + 审计 `project.tested`）；
- [x] `interface/web/routes.py`：`POST /w/{ws}/project/test`；
- [x] `templates/project-bridge.html`：运行测试按钮 + test_run 摘要块；
- [x] `interface/cli.py`：`rflp project test --workspace --source [--timeout]`；
- [x] 测试：adapter（通过/失败/超时/缺 pytest/目录缺失/归一化确定性）、app（缺前置/跑测试/确定性）、web（422 与按钮+test_run）、cli（成功与失败退出码）；
- [x] `pytest` 全量通过（99）；`lint-imports` 3 contracts kept；`python -m build` 成功；
- [x] 写 `docs/verification/2026-08-06-test-execution.md`；更新 `DEVELOPMENT_STATUS.md` 与 `README.md`。

## 约束提醒

- 命令固定为 `pytest --junitxml <临时>`,无命令注入面；子进程强制超时并 kill；
- 产物全部写入临时目录，结束后清理；归一化 JUnit 保证相同测试结果字节级确定；
- 测试结果作为独立客观 Evidence，不改变 R/F 匹配与契约 RESOLVED/UNRESOLVED。