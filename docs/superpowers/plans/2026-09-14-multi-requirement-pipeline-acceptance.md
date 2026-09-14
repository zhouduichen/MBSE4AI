# 多需求完整生命周期验收施工计划

> **施工说明：** 本计划用于当前任务的逐步执行；每一步完成后立即运行对应检查。

## 目标

把“完整 23-task 生命周期对多条自然语言需求分别形成 R→F→L→P→V&V 闭环”固定为产品级回归证据，避免仅凭单需求总数判断纵向完成度。

## 实施步骤

### 1. 新增多需求离线 E2E 验收

**文件：** `tests/e2e/test_legacy_pipeline.py`

- 使用 `RuleRuntime` 和临时工作区，不启动本机或远程模型。
- 输入三条独立自然语言需求，其中一条包含显式功耗约束。
- 运行完整 `WorkflowRunner` 23-task 生命周期。
- 断言 23 个任务完成、每条输入需求各自拥有完整 R→F→L→P→Verification/Validation 路径。
- 断言功耗约束产生 Technical Requirement，并且不会把三条需求合并成一条追溯。

### 2. 执行验证

```bash
./.venv/bin/python -m pytest -q tests/e2e/test_legacy_pipeline.py -k multi_requirement
./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/lint-imports
git diff --check
```

### 3. 提交交付

- 检查仅包含本次验收测试和计划文件。
- 创建独立提交并推送当前 GitHub 分支。
- 汇报测试结果、提交号和远程同步状态。

## 完成标准

- 多需求完整生命周期测试通过。
- 全量测试与既有静态质量门禁通过。
- Git 工作树干净，提交已推送到当前远程分支。
