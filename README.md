# RFLP-Lite

RFLP-Lite 是一个本地、确定性、可审计的 MBSE 研究原型。当前版本先跑通以下最小垂直链路：

`Artifact -> Stakeholder / Concern / Need -> Claim -> R/F/L/P -> Candidate -> Simulation -> Baseline -> Delta -> TaskContract -> Evidence`

开发资料：[当前完成状态](docs/DEVELOPMENT_STATUS.md) · [需求工作台设计](docs/superpowers/specs/2026-08-04-rflp-lite-requirements-workbench-design.md) · [实施计划](docs/superpowers/plans/2026-08-04-rflp-lite-requirements-workbench.md)

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

浏览器打开 `http://127.0.0.1:8000`。首次使用时在页面创建工作区，然后进入“需求建模”：

1. 粘贴需求，或上传 TXT、Markdown、DOCX、Python、JSON、YAML、TOML；
2. 点击“规则分析”；
3. 审核 Stakeholder、Concern、Need 和 Requirement 候选，或点击“接受全部可追溯候选”；
4. 点击“生成 RFLP 规划图”；
5. 查看来源链和 R/F/L/P 覆盖率，并下载确定性 JSON/SVG。

“运行中心”继续提供 Heuristic 或 CP-SAT 的完整 Candidate、Simulation、Baseline、Delta、TaskContract 和 Evidence 链路。

可选 AI 分析使用 OpenAI-compatible API，只产生待审核候选：

```bash
export RFLP_LLM_BASE_URL=http://127.0.0.1:11434/v1
export RFLP_LLM_MODEL=your-model
export RFLP_LLM_API_KEY=local-key
```

不设置这些环境变量时，规则分析和人工审核仍可完整运行。

Web UI 只管理仓库下 `workspaces/` 中的工作区，默认只监听本机地址。按 `Ctrl+C` 停止服务；SQLite 和已完成产物会保留。

## 验证

```bash
.venv/bin/python -m pytest -v
.venv/bin/lint-imports
.venv/bin/check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json
```

同一 fixture、Profile 和 seed 的重复运行应产生相同的 `result_hash` 与 `baseline_hash`。Adapter 失败会回滚当前事务，并记录 `run.failed` 审计事件，不会修改已有 Baseline。

## 当前边界

当前已提供最小 OpenAI-compatible LLM 候选接口，但尚未提供模型管理、流式对话或专用 Ollama/llama.cpp 运行时。Docling、MLflow、SysML v2 编辑、向量模型、登录权限和远程插件运行时仍未启用；“能力中心”只展示这些扩展的启用条件，不生成伪造结果。
