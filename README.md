# AI4MBSE Harness

AI4MBSE Harness v2.0 是一个本地优先、可复现、可审计的 MBSE 方法论执行器。核心链路为：

```text
Project → Documents / Evidence → Operational → Functional
        → Logical / Physical → Assurance → Closure
        → Typed ModelGraph → Gate / Repair → View / Export
```

ModelGraph 是模型唯一真源。任务运行只能通过经过契约、类型、关系和门禁校验的局部 Patch 修改模型；SQLite 保存项目、文档区域、证据、运行、步骤、Patch、Revision 和 Issue。

## 安装

需要 Python 3.11+：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,web,documents]'
```

不安装远程模型也可以完整运行离线规则 Runtime。OpenAI-compatible 模型是可选的，配置由 `model-profile` 管理。

## 最短路径

使用仓库中的 Golden fixture 创建项目并运行分析：

```bash
.venv/bin/ai4mbse --workspace-root .local-workspaces project create campus-demo
.venv/bin/ai4mbse --workspace-root .local-workspaces project ingest campus-demo tests/e2e/fixtures/campus_delivery_robot.json
.venv/bin/ai4mbse --workspace-root .local-workspaces analyze run campus-demo --phase operational
.venv/bin/ai4mbse --workspace-root .local-workspaces model export campus-demo --format json
```

CLI 的主要命令：

```text
project create|ingest
analyze run|status
model export
issue list
repair run
model-profile list|save|activate
```

## Web

```bash
.venv/bin/uvicorn rflp_lite.interface.web.app:create_app --factory --host 127.0.0.1 --port 8000
```

页面收敛为 Projects、Analysis、MBSE Model、Evidence & Issues、Settings；API 资源以 `/projects` 为根，提供项目、分析运行、模型、实体 CAS 编辑、证据、Issue、Repair 和 Export。

## 开发与验收

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall -q src
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/lint-imports
```

设计说明、施工计划和当前状态：

- [当前架构](docs/CURRENT_ARCHITECTURE.md)
- [开发状态](docs/DEVELOPMENT_STATUS.md)
- [v2.0 设计规格](docs/superpowers/specs/2026-09-07-ai4mbse-harness-v2-design.md)
- [v2.0 实施计划](docs/superpowers/plans/2026-09-07-ai4mbse-harness-v2-implementation.md)

## 边界

Core 不包含旧版智能发现、Concept/MDO、Project Bridge、测试执行沙箱、仿真、旧 Baseline/TaskContract/Job 体系或 MLflow 适配器。它们不再作为隐式依赖存在；如未来需要，应以独立插件或独立研究包接入。
