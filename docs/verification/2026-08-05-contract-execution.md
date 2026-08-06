# 任务契约执行验证记录

**日期：** 2026-08-05
**设计：** `docs/superpowers/specs/2026-08-05-rflp-lite-contract-execution-design.md`

## 结论

任务契约执行（确定性重验证循环）已实现并通过全部验证：**85 passed**（前一版 76 + 新增 9），Import Linter 3 contracts kept / 0 broken，`python -m build` 成功。

## 验证内容

### 单元：应用层（`tests/application/test_project_bridge.py`）

- 未批准基线时 `verify_contracts_state` 抛 `ContractViolation("请先批准基线")`；
- 已批准但无任务契约时抛 `ContractViolation("请先在项目接入中分析项目并生成任务契约")`；
- 单条英文义务、初始未实现 → 2 条 MISSING 契约（目标 `req-*`/`fn-*`），验证全部 `UNRESOLVED`；往项目补 `restore_historical_version` 后验证 → 全部 `RESOLVED`、`missing=0`、`extra=0`；
- 确定性：重复验证 `execution` 字节一致、`statuses`/`hash` 一致；
- 失效语义：重新生成 RFLP 后 `execution` 随 `project` 一并清空。

### 端到端（真实流程）

对 `examples/versioned-content-service` 与混合中英文需求：批准基线 → 分析（4 matched / 4 MISSING / 5 EXTRA）→ 验证，页面显示“任务契约执行验证”面板与逐条 `RESOLVED`/`UNRESOLVED` badge。

### Web / CLI

- `POST /w/{ws}/project/verify`：无基线返回 422；分析后返回 303 并渲染执行面板；
- `rflp project verify --workspace --source`：成功输出规范化 JSON（status ok / actual_model_id / resolved / unresolved / missing / extra）；无基线退出码 1。

## 复现命令

```bash
.venv/bin/pytest -q
.venv/bin/lint-imports
.venv/bin/python -m build
.venv/bin/rflp project verify --workspace <path> --source <dir>
```

## 边界

“执行”是有意的**确定性重验证**：只重扫项目目录并重算与已批准基线的差异，不运行任何用户代码或子进程。真正运行测试命令需要一个带超时与隔离的独立执行器，留作下一步。