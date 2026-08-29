# RFLP-Lite 架构收敛执行状态

更新时间：2026-08-29

## 已完成

- 建立架构指标、预算和全量隔离验证门禁。
- 将文档、跟踪、测试执行和 Job 能力收敛到端口与适配器边界。
- 为 Workbench 增加 SQLite 迁移、`revision` / `content_revision`、快照、CAS、审计和删除记录能力。
- 将 Job ledger 迁移到 SQLite，支持旧 `jobs.json` 一次性导入、幂等提交、启动恢复、租约心跳、重试和分块状态持久化。
- 增加智能分析快照协调器、分块合并注册表、强类型 DTO、部分失败保留和过期任务隔离。
- 将需求用例、查询视图、MBSE 构建器和 Web DTO / 错误映射拆出稳定边界；保留旧入口作为薄兼容壳。
- 修复 Web 并发分析中的 SQLite 锁等待，并保证快速完成的 Job 不会被旧的排队状态覆盖。

## 当前架构指标

由 `scripts/architecture_metrics.py` 测得：

```text
adapter_to_application_edges: 0
module_cycles: 0
require_dependencies_calls: 0
raw_request_json_calls: 29
functions_over_150_lines: 11
web_facade_methods: 92
dict_str_object_occurrences: 1034
```

## 兼容性说明

- SQLite 中的规范终态为 `succeeded`；需求富化在 Web 查询边界仍返回历史状态名 `completed`，避免旧页面和客户端轮询失效。
- `jobs.json` 只作为迁移输入，成功校验后改名为 `jobs.legacy.json`，运行时不再写回 JSON ledger。
- `configured_dependencies`、旧 `WebFacade` 方法和旧仓储替身仍保留为兼容入口；新的核心用例通过显式依赖和端口工作。

## 验证结果

```text
548 passed
lint-imports: 6 kept, 0 broken
check-jsonschema: passed
ruff: passed
pyright: 0 errors, 1 existing missing-source warning
python -m build --no-isolation: passed
```

全量命令：

```bash
RFLP_VERIFY_TIMEOUT_SECONDS=180 .venv/bin/python scripts/verify_full.py
```
