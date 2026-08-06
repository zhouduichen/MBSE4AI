# 测试执行沙箱验证记录

**日期：** 2026-08-06
**设计：** `docs/superpowers/specs/2026-08-06-rflp-lite-test-execution-design.md`

## 结论

测试执行沙箱已实现并通过全部验证：**99 passed**（前一版 85 + 新增 14），Import Linter 3 contracts kept / 0 broken，`python -m build` 成功。

## 验证内容

### 单元：适配器（`tests/adapters/test_test_executor.py`）

- 含通过测试的最小 pytest 项目：`returncode=0`、junit 产生、未超时；
- 归一化后 junit 无 `time`/`timestamp`/`hostname`/`id` 属性；
- 失败测试仍写 junit（`returncode != 0`）；
- 同一项目两次运行归一化 junit 字节一致（确定性）；
- 睡眠测试 + 1s 超时 → `timed_out=True`；
- 目录不存在 → `ContractViolation`；pytest 不可启动 → `AdapterFailure`。

### 单元：应用层（`tests/application/test_project_bridge.py`）

- 未批准基线 / 无任务契约时 `execute_tests_state` 抛 `ContractViolation`；
- 对含通过测试项目执行：`test_run` 记录 `returncode=0`、`tests_passed=1`、`junit_evidence=1`，`verify.evidence` 含 `test-case` 证据；
- 重复执行 `execution` 字节一致。

### 端到端（CLI 真实运行）

需求“The service shall record an audit event for every restore.” + 项目含实现与一过一败测试：

- `approve` → 基线批准；
- `analyze` → `matched=2`、`extra=2`、`missing=0`、`tasks=2`；
- `test` → `returncode=1`、`tests_passed=1`、`tests_failed=1`、`timed_out=false`——如实报告真实测试结果，不伪造。

### Web / CLI

- `POST /w/{ws}/project/test`：未分析项目返回 422；分析后执行返回 303，页面显示“运行项目测试”按钮与 test_run 摘要（退出码/超时/通过/失败/测试证据）；
- `rflp project test --workspace --source [--timeout]`：成功输出规范化 JSON；无基线退出码 1。

## 复现命令

```bash
.venv/bin/pytest -q
.venv/bin/lint-imports
.venv/bin/python -m build
.venv/bin/rflp project test --workspace <path> --source <dir> [--timeout 60]
```

## 边界

沙箱只运行固定 `pytest` 命令并回填 JUnit 证据；测试结果作为独立客观 Evidence 呈现，不改变实现符号层面的 R/F 匹配与契约 RESOLVED/UNRESOLVED。多运行器配置、资源上限、结果缓存与并行执行留作下一步。