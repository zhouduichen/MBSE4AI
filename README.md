# RFLP-Lite

RFLP-Lite 是一个本地、确定性、可审计的 MBSE 研究原型。当前版本先跑通以下最小垂直链路：

`Artifact -> Stakeholder / Concern / Need -> Claim -> R/F/L/P -> Candidate -> Simulation -> Baseline -> Delta -> TaskContract -> Evidence`

开发资料：[当前完成状态](docs/DEVELOPMENT_STATUS.md) · [需求工作台设计](docs/superpowers/specs/2026-08-04-rflp-lite-requirements-workbench-design.md) · [实施计划](docs/superpowers/plans/2026-08-04-rflp-lite-requirements-workbench.md)

## 本地安装

需要 Python 3.11 或更高版本；不需要 Docker、GPU、PostgreSQL 或外部服务。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev,schema,evidence,opt,web,documents]'
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

1. 粘贴需求，或上传 TXT、Markdown、DOCX、PDF、Python、JSON、YAML、TOML；勾选“并入现有工作台”可把多份文档追加到同一工作台并保留已审核项；
2. 点击“规则分析”；
3. 审核 Stakeholder、Concern、Need 和 Requirement 候选，或点击“接受全部可追溯候选”；
4. 点击“生成 RFLP 规划图”；
5. 在“场景描述”中记录参与者、前置条件、步骤、预期结果和故障/异常；
6. 点击“生成执行轨迹”运行结构化场景的本地声明性执行，查看事件、断言和 Evidence；也可下载场景 JSON、执行记录和 SysML-lite 交换 JSON。

“运行中心”继续提供 Heuristic 或 CP-SAT 的完整 Candidate、Simulation、Baseline、Delta、TaskContract 和 Evidence 链路。

### 连接本地 Python 项目

需求建模生成 RFLP 后，进入“项目接入”，把已批准基线（人工批准）与一个本地 Python 项目目录对接：

1. 在“项目接入”页面点击“人工批准基线”；
2. 填写本地项目目录的绝对路径，点击“分析项目”；
3. 查看 ActualModel、基线→实际匹配、MISSING/EXTRA 差异、任务契约与证据；
4. 对项目作出修改后，点击“执行验证”重扫描判定每条任务契约是否已满足（RESOLVED/UNRESOLVED）；
5. 点击“运行项目测试”，选择 pytest/unittest、资源上限、并行度和缓存策略，在超时与隔离沙箱中运行并查看每个 runner 的结果；
6. 下载规范化 JSON：baseline、actual-model、matches、delta、task-contracts、evidence、project。

场景描述和执行记录保存在现有工作台 JSON 中，不新增数据库表；步骤和预期结果按行记录，可选关联 Requirement ID。执行轨迹只处理结构化文本，不执行任意代码，结果明确标记为 `declarative-only`，可通过 `/w/{workspace}/requirements/scenarios.json`、`/w/{workspace}/requirements/scenario-runs.json` 下载。

本地 MVP 还提供 Profile JSON 的 schema 校验/保存、运行记录导出、`sysml-lite/rflp` JSON 和 SysML v2 常用子集文本交换、本地持久化 Job 状态、进程内 Plugin Registry，以及 `/api/v1` JSON API。安装 `.[tracking]` 后可把运行记录真实写入 MLflow；API 当前默认只绑定本机，不包含登录、权限、限流或公网部署能力。

启用真实 MLflow Tracking：

```bash
.venv/bin/pip install -e '.[tracking]'
.venv/bin/rflp mlflow --workspace <workspace> --result-hash <result-hash>
```

扫描只读 `.py`（AST）、OpenAPI JSON 与 JUnit XML；跳过隐藏目录、依赖目录、符号链接与超大文件；不复制、不写入、不上传项目。测试运行支持 allowlist 中的 `pytest` 与 `unittest`，默认 60s 超时并 kill，可配置 POSIX 内存/文件句柄上限、输出上限、结果缓存和多 runner 并行。

CLI 等效操作：

```bash
.venv/bin/rflp project approve --workspace <workspace>
.venv/bin/rflp project analyze --workspace <workspace> --source <project-dir>
.venv/bin/rflp project verify --workspace <workspace> --source <project-dir>
.venv/bin/rflp project test --workspace <workspace> --source <project-dir> [--timeout 60] [--runner pytest|unittest] [--jobs 2]
.venv/bin/rflp workbench build --workspace <workspace> --requirements <file>
.venv/bin/rflp acceptance --requirements <file> [--gold <requirements-gold.json>]
.venv/bin/rflp mbse generate --workspace <workspace>
.venv/bin/rflp mbse export --workspace <workspace> --format json|sysml|svg
.venv/bin/rflp assess --workspace <workspace> --requirements <file> --source <project-dir> [--timeout 60]
.venv/bin/rflp profile show --workspace <workspace>
.venv/bin/rflp profile validate --profile <profile.json>
.venv/bin/rflp profile save --workspace <workspace> --profile <profile.json>
.venv/bin/rflp scenario execute --workspace <workspace> --scenario-id <scenario-id>
.venv/bin/rflp run export --workspace <workspace> --result-hash <result-hash>
.venv/bin/rflp sysml export --workspace <workspace> > rflp-model.sysml
.venv/bin/rflp sysml import --workspace <workspace> --file rflp-model.sysml
.venv/bin/rflp mlflow --workspace <workspace> --result-hash <result-hash>
```

`assess` 一步完成 需求工作台 → 批准基线 → 分析项目 → 运行测试 并输出汇总，适合脚本/CI 断言。`workbench build` 接受多个 `--requirements` 文件完成多文档合并。需求接入支持 DOCX 表格行（每行按 “ID | 义务句” 合并为一条 span）。

测试命令还支持 `--memory-mib`、`--max-open-files`、`--output-mib` 和 `--no-cache`。多个 `--runner` 配合 `--jobs 2` 可并行运行 pytest/unittest；测试结果仍作为独立客观 Evidence，不改变 R/F 匹配。

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

### 客户验收功能（1.1—1.2）

当前实现已覆盖需求分析与论证阶段的客户验收切片：TXT/Markdown/DOCX/数字 PDF/扫描 PDF 统一解析，保留页码、区域坐标、来源哈希和诊断；按客户工程语言抽取实体、能力、对象、数量范围和指标约束，生成可审查的 MBSE 结构化需求候选；持久化 `derivedFrom / representedBy / satisfiedBy / refines` 追溯链和覆盖率；已接受的明确需求生成 Use Case、活动图、时序图语义模型，并支持版本校验、逐条编辑、JSON/SysML 子集/SVG 导出。LLM 只生成 `inferred` 候选，批量确认不会批准隐含约束。

```bash
.venv/bin/rflp acceptance --requirements src/rflp_lite/resources/examples/customer-acceptance/customer-requirements.txt
.venv/bin/rflp mbse generate --workspace <workspace>
.venv/bin/rflp mbse export --workspace <workspace> --format json
```

文档依赖通过 `.[documents]` 安装；未安装时 PDF/OCR 返回明确的本地依赖诊断，不影响 TXT/DOCX 规则链路。

当前已提供最小 OpenAI-compatible LLM 候选接口，但尚未提供模型管理、流式对话或专用 Ollama/llama.cpp 运行时。场景执行目前是安全的声明性轨迹，不连接真实系统，也不生成仿真通过结论。项目接入扫描只读 `.py` / OpenAPI JSON / JUnit XML，匹配按分词交集进行（中英文义务句之间无法用关键词对齐，会如实标为 MISSING）。“执行验证”是确定性重扫描——只读重算与已批准基线的差异并判定任务契约是否满足。测试结果作为独立客观 Evidence 呈现，不改变契约状态；运行器仅允许 pytest/unittest，POSIX 资源限制在平台不支持时会明确报告。SysML v2 常用子集文本桥接、MLflow 可选真实 Tracking、Profile、Job、API 和进程内插件已提供本地 MVP；完整 SysML v2 语义、Docling、LLM/Ollama 生命周期、登录权限和远程插件运行时仍未配置，能力中心会区分“局部可用”和“未配置”。
