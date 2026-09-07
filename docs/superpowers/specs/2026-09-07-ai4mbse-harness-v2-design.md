# AI4MBSE Harness v2.0 代码级轻量化重构设计

**日期：** 2026-09-07  
**依据：** `AI4MBSE_Harness_代码级轻量化重构施工方案_v2.0.docx`  
**适用仓库：** 当前 `rflp_lite` 源码

## 目标

保留当前项目已经验证的 SQLite、结构化模型调用、JSON Schema 校验与 Repair、Job lease/heartbeat/retry、文档解析、Evidence/Traceability、渲染器和本地 Web 底盘，删除偏离 AI4MBSE Domain Harness 目标的历史产品链，建立一条以 Methodology State Machine 和 Typed Model Graph 为核心的正式路径。

重构后的产品遵循以下原则：

- 先删后建；新路径接管职责后立即删除旧路径，不保留长期双轨。
- Model Graph 是唯一模型真源；图、矩阵、SysML 是视图或导出。
- AI 只能输出经过校验的 Patch，不得整体覆盖模型。
- 4 个 Phase 加 1 个 Closure，通过 `TaskSpec` 数据化细分任务，不建立大量 Agent 类。
- 本地 SQLite 是事务真源；不引入 Neo4j、PostgreSQL 或 Redis。
- Web Search 是可选证据来源；外部检索失败不阻塞主流程。
- 本次保留 `rflp_lite` 包名，最终纯重命名单独进行，降低迁移风险。

## 范围与删除边界

### 保留并重用的底盘

保留文档输入与 source region、结构化模型端口、现有 OpenAI-compatible/Ollama 适配、SQLite 事务能力、Job lease/heartbeat/retry、Evidence 基础、内置 SVG 和可选 Graphviz/PlantUML，以及 FastAPI/Jinja/HTMX 基础。

### 从 Core 删除或迁出

以下能力不再属于 AI4MBSE Core 正式路径：

- Concept/MDO/Layout 全链路，包括 scheme、discipline、parameter rule 和布局资源；未来需要时以插件或 extra 恢复。
- Project Bridge、代码扫描和 Test Runner；第一阶段只保留 `VerificationCase`、`ValidationCase` 模型，不执行用户项目代码。
- 旧 Candidate/Simulation/Baseline/Delta/TaskContract/Demo 垂直链。
- MLflow Core 集成；Acceptance Gold/Harness/Metrics 迁到顶层 `evals/`。
- 独立 Discovery、Review、Workbench 聚合状态机、Enrichment 第二编排器。
- Legacy Builder、旧 architecture block、专用 block merge/reconcile 和 `WebFacade`。

删除以 feature cluster 为单位，并以 import graph、测试和迁移门禁为条件；不在未迁移调用者前直接删除公共能力。

## 目标架构

包内目标边界如下：

```text
interface ───────→ application ───────→ methodology ───────→ domain
    │                    │                    │                 │
    └──────────────→ diagrams              runtime          typed model
                         │                    │                 │
                         └──────────────→ ports ←────── repository
                                             │
                                         adapters/bootstrap
```

### `domain`

只定义 MBSE 语义和值对象：`EntityMeta`、EntityKind、Status、Lifecycle、Requirement、Scenario、Function、LogicalComponent、PhysicalBlock、Interface、Behavior、Hazard、FailureMode、VerificationCase、ValidationCase、Relation、ModelGraph、Revision、Patch。禁止依赖 SQLite、FastAPI 或 LLM。

### `methodology`

定义 `Phase`、`TaskSpec`、`WorkflowRunner`、`ContextBuilder`、Coverage、Validators、Gates、GapAnalysis、RollbackRouter 和 Patch Repair。它决定方法论顺序，但不直接写数据库或渲染图。

### `runtime`

定义 `TaskExecutionRequest` 和 `RuntimePort`，把 Methodology 请求转换为当前 `GenerationRequest`。现有模型提供商继续作为适配器；外部 DeepSeek/Codex Harness 只可作为可替换 Runtime Adapter。

### `repository`

定义 ModelRepository 和 RunRepository 的端口/SQLite 实现。Repository 负责事务、revision、CAS、锁定语义、运行账本和一次性 v1→v2 导入，不判断 MBSE 完整性。

### `application`

只保留 ProjectService、AnalysisService、ModelService、EvidenceService、RenderService、SettingsService。业务编排不得回到一个大 Facade 或 Workbench。

### `diagrams` 与 `interface`

Diagrams 由 ModelGraph 编译 `ViewSpec` 并调用 Renderer。Web/API/CLI 以项目、运行、模型、证据、问题、修复、导出为资源组织，不再为每种实体复制一套路由。

## Typed Metamodel v0.2

所有正式对象组合通用 `EntityMeta`：

```text
EntityMeta
├─ id: str
├─ kind: EntityKind
├─ name: str
├─ status: candidate | validated | accepted | deprecated | locked
├─ producer: user | llm | rule | import
├─ confidence: float | None
├─ source_ids: tuple[str, ...]
├─ evidence_ids: tuple[str, ...]
├─ lifecycle_ids: tuple[str, ...]
├─ created_revision: int
└─ updated_revision: int
```

`Requirement` 统一表达 stakeholder/system/functional/technical level，支持 functional、performance、interface、safety、security、environmental、maintenance、constraint、verification type，并保留 subject、condition、obligation、rationale、metric 和 verification_method。无证据的性能数字必须保留 `TBD` 或 `ParameterGap`，禁止 LLM 编造。

`ScenarioHypothesis` 只用于需求发现，保留 goal、trigger、preconditions、environment、正常/替代/异常/故障/降级/恢复路径、stakeholders 和 evidence。`OperationalScenario` 是正式 CESAM 黑盒场景，关联 UseCase、actors、外部 exchanges、messages/steps、pre/postcondition 和 exception path，不包含内部组件。

Relation 由白名单和端点类型约束控制，第一版至少支持：`hasConcern`、`participatesIn`、`occursIn`、`derivedFrom`、`refines`、`decomposes`、`describedBy`、`satisfiedBy`、`allocatedTo`、`realizedBy`、`exchangesWith`、`connectedTo`、`verifiedBy`、`validatedBy`、`causes`、`mitigatedBy`、`supportedBy`。例如 Requirement→satisfiedBy→Function 合法，PhysicalBlock→satisfiedBy→Stakeholder 非法。

## Methodology Workflow

工作流固定为四个 Phase 和 Closure：

1. Operational：SystemDefinition → StakeholderAnalysis → StakeholderRequirements → LifecycleAnalysis → ScenarioExploration → UseCaseAnalysis → OperationalScenario → ActivityAnalysis → SystemRequirementDerivation，输出 O-Gate。
2. Functional：FunctionIdentification → FunctionalDecomposition → FunctionalInteraction → FunctionalScenario → FunctionalRequirement，输出 F-Gate。
3. Logical/Physical：LogicalAnalysis → PhysicalCandidates → Allocation/Trade-off → TechnicalRequirement，输出 P-Gate。
4. Assurance：Interface/Sequence/State → FMEA/STPA/Hazard → Verification/Validation → ReverseFeasibility → GlobalCrossAnalysis，输出 Global Gate。
5. Closure：冻结当前 revision，生成可审计 run manifest 和导出视图。

每个任务使用数据化 `TaskSpec`：`id`、`phase`、`input_kinds`、`output_kinds`、`context_query`、`prompt_template_id`、`output_schema_id`、`tools`、`validators`、`max_attempts`、`failure_routes`、`completion_condition`。`WorkflowRunner` 统一负责 run/resume/degraded/repair/rollback。

ContextBuilder 只返回任务直接需要的 Model Graph 邻域和 Evidence。StakeholderAnalysis 不读取 Logical/Physical 候选，ScenarioExploration 不读取完整物理架构，PhysicalCandidates 不读取无关项目全部上下文，SemanticCritic 只读取 issue 邻域 ±2 hop 和相关 Evidence。

## Gate、验证与修复

验证分层如下：

- SchemaValidator：JSON 结构、枚举、必填字段、additionalProperties。
- IdentityValidator：稳定 ID、唯一性、重复候选。
- ReferenceValidator：实体和来源引用存在。
- RelationValidator：谓词白名单及端点类型。
- LifecycleValidator：阶段/转换连通性、entry/exit、孤岛。
- RequirementQuality：原子性、无歧义、可验证性、模糊词、单位和指标。
- CoverageValidator：Stakeholder×Lifecycle、Lifecycle×ScenarioType、Requirement×Verification 等矩阵。
- OperationalGate、FunctionalGate、RFLPGate、VerificationValidator、EvidenceValidator 和 SemanticCritic。

格式或 API 错误走 Retry/JSON Repair；方法论缺口先做 GapAnalysis，分类为 stakeholder、lifecycle、scenario、requirement、function、architecture、verification 或 evidence，选择最小回退阶段，生成局部 Patch，Validate 后 Apply，再重跑 Gate。Repair 不等价于 Retry。

Patch 只有四种操作：

```text
ADD(entity)
UPDATE(entity_id, field_patch)
RELATE(source_id, predicate, target_id)
DEPRECATE(entity_id)
```

Patch 采用事务和 CAS 写入；任何 `locked` 或用户修改实体都禁止自动覆盖。

## Repository v2

SQLite v2 表收敛为：

```text
projects(id, name, revision, content_revision, status, settings_json)
documents(id, project_id, kind, path, name, sha256, metadata)
source_regions(id, document_id, page, locator, text, bbox, heading_path)
entities(id, project_id, kind, name, status, lifecycle_hint, producer,
         confidence, payload_json, created_revision, updated_revision)
relations(id, project_id, source_id, predicate, target_id, status,
          evidence_ids, created_revision)
evidence(id, project_id, source_type, source_id, locator, claim, excerpt,
         authority, relevance)
runs(id, project_id, phase, status, lease, heartbeat, attempt,
     methodology_version, model_profile, input_hash, diagnostics)
steps(run_id, task_id, status, attempt, input_hash, output_patch_id, diagnostics)
patches(id, run_id, task_id, operations_json, reason, status)
revisions(id, project_id, sequence, parent_id, reason, snapshot_json,
          snapshot_hash, run_id)
issues(id, project_id, run_id, task_id, code, severity, entity_ids,
       suggested_rollback, status)
audit_events(sequence, project_id, kind, payload)
```

现有 `jobs/job_blocks` 的 lease、heartbeat、idempotency、retry 语义迁移为 `runs/steps`；新写入只走 v2。旧 workspace 由一次性 importer 转换，导入结果必须通过 entity identity、relation、revision 和 locked semantics 验证。

## Evidence 与 Retrieval

第一版采用 Coverage-driven Retrieval：User Documents > Historical Projects > Local FTS5 > optional Web。文档段落与历史项目 Entity/Evidence 文本进入 SQLite FTS5；Query Planner 只根据 `KnowledgeGap` 生成少量结构化检索任务；EvidenceExtractor 把命中材料转成带来源和 locator 的 Evidence，不把整篇文档塞进 Prompt。

Coverage Saturation 在连续两轮新增有效 Evidence/Scenario/Requirement 低于阈值时停止。Web 失败生成 `ExternalEvidenceGap`、降低 confidence，但不终止 Workflow。

## Runtime、Web、API 与 CLI

`TaskExecutionRequest` 包含 task_id、methodology_version、context_bundle、evidence_bundle、output_contract、token_budget、tool_policy，并由 RuntimePort 转换到现有 GenerationRequest。这样不破坏现有模型调用契约，也不把 Methodology 绑定到 DeepSeek/Codex。

正式 API 收敛为：

```text
POST  /projects/{id}/analysis
GET   /projects/{id}/runs/{run_id}
GET   /projects/{id}/model
GET   /projects/{id}/entities?kind=...
PATCH /projects/{id}/entities/{entity_id}
GET   /projects/{id}/views/{view_id}
GET   /projects/{id}/evidence
GET   /projects/{id}/issues
POST  /projects/{id}/repair
POST  /projects/{id}/export
```

一级页面收敛为 Projects、Analysis、MBSE Model、Evidence & Issues、Settings。所有 Scenario、Requirement、Verification View 支持 LifecycleStage filter 和 badge，并提供 Lifecycle Coverage Matrix。

CLI 保留：

```text
ai4mbse project create
ai4mbse project ingest
ai4mbse analyze run
ai4mbse analyze status
ai4mbse model export --format json|sysml
ai4mbse issue list
ai4mbse repair run
ai4mbse model-profile list|save|activate
```

旧 demo、concept、project test、mlflow、discovery、baseline/task 命令随功能簇删除。

## PR 施工顺序与门禁

按文档执行 PR-00～PR-19：

| PR | 交付 | 合并门禁 |
|---|---|---|
| PR-00 | 冻结基线、关键回归、compileall、架构指标、校园无人配送机器人 Golden fixture | 无功能变化 |
| PR-01 | 收敛 PRODUCT/README 范围 | 产品边界明确 |
| PR-02 | 删除 Concept/MDO/Layout 及关联 Web/CLI/tests/resources/OR-Tools | 核心流程回归 |
| PR-03 | 删除 Project Bridge/Test Runner 及 prance/junitparser | V&V 建模仍可用 |
| PR-04 | 删除旧 Demo/Tracking，Acceptance 迁 evals | extras 收敛 |
| PR-05 | 建立 Typed Metamodel v2 | Entity/Relation 单测通过 |
| PR-06 | 建立 Repository v2 和一次性迁移 | 旧 fixture 可迁移，新写入只走 v2 |
| PR-07 | 建立 WorkflowRunner/TaskSpec/Context/Gate/Repair 骨架 | fake task 可 run/resume/repair |
| PR-08～PR-10 | 迁 Operational、O-Gate、Coverage Repair | 全生命周期与最小回退闭环 |
| PR-11 | 迁 Functional Phase/F-Gate | 黑盒驱动灰盒 |
| PR-12 | 迁 Logical/Physical/P-Gate | R→F→L→P 完整 |
| PR-13 | 迁 Assurance/Global Gate | 可定位回退 |
| PR-14 | 删除 architecture block、专用 merge/reconcile | 不存在一次性 F/L/P 生成 |
| PR-15 | 删除 Legacy Builder 和假 typed projection | 测试不再 import legacy builder |
| PR-16 | FTS5、历史项目、Evidence extraction、optional Web | 离线运行不受 Web 影响 |
| PR-17 | 建立六类 Application Service 并迁 Web/API | WebFacade 调用者为 0 |
| PR-18 | 删除 WebFacade/Workbench，收敛五页面 | 只有一个正式路径 |
| PR-19 | 删除兼容遗留、收紧 pyright/ruff/import-linter/architecture budget | v2.0 门禁全部通过 |

任何删除 PR 必须同步删除已失效测试和资源，并保持主分支可运行；每一步有明确的 Delete-After-Migrate 条件。

## 测试与质量预算

测试分为 Metamodel、Repository、Workflow、Context、Coverage、Validator、Runtime、Traceability、E2E Golden、Failure E2E 和 Eval。校园无人配送机器人 Golden fixture 应跑完整生命周期；Failure E2E 故意漏维护、故障、验证和物理实现，验证最小回退与局部 Patch。

最终验收至少包括：

- `pytest` 通过，删除功能对应测试同步迁出或删除。
- `compileall` 通过。
- import-linter 无循环或越层依赖。
- pyright 从 domain/methodology/ports 逐步扩大到至少 standard 模式。
- ruff 增加未使用、导入排序和复杂度约束。
- `legacy_builder.py`、`requirements_workbench.py`、`web_facade.py` 无正式调用者并删除。
- Domain/Methodology 内 `dict[str, object]` 为 0；全项目收敛到文档目标以内。
- 普通函数大于 150 行为 0，文件大于 1000 行为 0，普通文件优先小于 400 行。
- Workflow Orchestrator 只有一个，Model Truth 只有一个 Model Graph。
- `python -m build` 成功，文档输入、Web、内置渲染和离线 Retrieval 回归通过。

## 风险与回滚

删除按功能簇拆分，每个 PR 绑定 Golden fixture 和主链回归；一次性 v1→v2 importer 保留可审计诊断；迁移失败时拒绝写入并保留原 workspace；运行时失败只影响当前 Run/Step，不能污染已提交 Revision；外部证据失败只生成 Gap；用户锁定实体不会被自动 Patch 覆盖。

回滚使用 Git PR 回退和未改写的旧 workspace 副本，不使用破坏性数据库重置。v2 稳定后再做包名纯重命名，避免把结构迁移与命名迁移绑定在一起。

## 目标目录

```text
src/rflp_lite/
├── domain/          # typed entities, relations, lifecycle, model graph
├── methodology/     # workflow, task specs, contracts, context, gates, repair
├── retrieval/       # planner, local FTS, history, web port, evidence
├── runtime/         # runtime port, structured model, OpenAI-compatible adapter
├── repository/      # repository port, SQLite implementation, migrations
├── application/     # project, analysis, model, evidence, render, settings services
├── diagrams/        # views, compiler, renderers
├── interface/       # CLI and resource-oriented Web/API
├── evals/           # acceptance/evaluation assets
└── bootstrap.py     # composition root
```

现有包名 `rflp_lite` 在 v2.0 内保留；旧路径只在对应迁移窗口中存在，完成门禁后删除。
