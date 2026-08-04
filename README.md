# RFLP-Lite

RFLP-Lite 是一个本地、确定性、可审计的 MBSE 研究原型。当前版本先跑通以下最小垂直链路：

`Artifact -> TextSpan -> Claim -> R/F/L/P -> Candidate -> Simulation -> Baseline -> Delta -> TaskContract -> Evidence`

## 本地安装

需要 Python 3.11 或更高版本；不需要 Docker、GPU、PostgreSQL 或外部服务。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev,schema,evidence,opt,web]'
```

安装的首批开源组件包括 Import Linter、jsonschema/check-jsonschema、Hypothesis、Prance、junitparser 和 OR-Tools CP-SAT。它们都位于领域内核之外。

## 跑通完整链路

确定性启发式求解器：

```bash
.venv/bin/rflp init .local-demo-heuristic
.venv/bin/rflp demo --workspace .local-demo-heuristic --seed 42 --solver heuristic
```

OR-Tools CP-SAT 第二实现：

```bash
.venv/bin/rflp init .local-demo-cp-sat
.venv/bin/rflp demo --workspace .local-demo-cp-sat --seed 42 --solver cp-sat
```

CLI 在标准输出返回一行规范化 JSON。完整结果位于工作目录的 `.rflp/runs/<result_hash>/`，包括：

- `artifacts.json`
- `spans.json`
- `claims.json`
- `rflp.json`
- `candidates.json`
- `decision.json`
- `simulation.json`
- `baseline.json`
- `delta.json`
- `task-contracts.json`
- `evidence.json`
- `run-manifest.json`

SQLite 事务真源位于 `<workspace>/.rflp/model.db`。

## 启动本地 Web UI

```bash
.venv/bin/rflp web --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。首次使用时在页面创建工作区，然后进入“运行中心”，选择 Heuristic 或 CP-SAT，保持 Seed 为 `42` 并启动完整链路。完成后可以沿左侧导航查看工件与声明、RFLP 模型、候选与权衡、仿真、Baseline/Delta、TaskContract、Evidence/Audit，并下载规范化 JSON。

Web UI 只管理仓库下 `workspaces/` 中的工作区，默认只监听本机地址。按 `Ctrl+C` 停止服务；SQLite 和已完成产物会保留。

## 验证

```bash
.venv/bin/python -m pytest -v
.venv/bin/lint-imports
.venv/bin/check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json
```

同一 fixture、Profile 和 seed 的重复运行应产生相同的 `result_hash` 与 `baseline_hash`。Adapter 失败会回滚当前事务，并记录 `run.failed` 审计事件，不会修改已有 Baseline。

## 当前边界

当前未启用 LLM、Ollama/llama.cpp、Docling、MLflow、SysML v2 编辑、向量模型、登录权限或远程插件运行时。Web UI 的“能力中心”会展示这些规划项及启用条件，但按钮保持禁用，不生成伪造结果。这些能力后续只能通过 Port/Profile 和可选依赖加入，不改变领域内核和 Baseline 更新规则。
