# 当前架构

## 产品主链路

```text
自然语言 / 文档 → Requirements → Functional → Logical → Physical → V&V
               → Typed ModelGraph → SysML v2 subset / 可编辑模型
```

这是一个本地模块化单体：Python 3.11、SQLite、FastAPI/Jinja/HTMX，以及可选的 OpenAI-compatible Runtime。产品版本是 `0.2.0`，方法论协议是 `v2.1`。每个项目使用独立工作区和数据库，项目之间不共享模型或证据。旧 23-task WorkflowRunner 仍存在，但只承担兼容和单阶段调试职责。

## 分层与依赖

```text
interface → application → methodology → domain
                         ↘ ports → runtime / repository
bootstrap → application + adapters
adapters → ports + domain
```

- `domain/`：Typed Entity、Relation、ModelGraph、Patch、Requirement 和稳定 ID；不依赖外层。
- `methodology/`：五个产品级 `VerticalStage` 合约和阶段 Prompt；纯 ModelGraph `MethodologyEngine` 负责 Logical 分区/State 信号、Physical 约束/可行性、V&V 计划与证据分层、Hazard/FailureMode 覆盖和四跳 Impact Analysis；23 个细粒度 TaskSpec、四个 Phase、Context/Retrieval、Schema/Validator/Retry、PatchPolicy、谓词感知 Gate/Coverage Matrix、局部 Repair 和 LifecycleOrchestrator 保留为兼容/调试能力。
- `application/`：Project、ModelGeneration、Analysis、Model、Evidence、Render、EngineeringDeliverable、Settings、Tool Layer 服务；`ModelGenerationService` 负责五阶段纵向编排、追溯摘要和 Controller 动作执行。`EngineeringDeliverableService` 从单一 ModelGraph revision 组合 Requirements、RFLP、Traceability、V&V Plan、Architecture Report、SysML 和 manifest，并可导出固定成员顺序的 ZIP。`EngineeringToolLayer` 将文档/历史/本地 FTS 证据检索封装为受限工具；工具只采集，应用服务统一持久化 Evidence，不能直接写 ModelGraph。
- `repository/`：SQLite ModelRepository v2，保存 Graph、文档 Source Region 对应的 `document_region` Evidence、Run、Step、Patch、Revision、Issue、Closure 和 FTS，并提供 lease/heartbeat。
- `runtime/`：RuntimeFactory、结构化模型端口、OpenAI-compatible 适配和离线 RuleRuntime；每次运行动态解析 active profile。
- `adapters/`：文档解析、OCR 和模型/文档技术实现；由 `bootstrap/container.py` 组装。
- `interface/`：`ai4mbse` CLI、FastAPI Resource API 和五个资源页面；默认 Analysis 操作调用 `ModelGenerationService`，旧 `pipeline/phase` 仍可显式调用。
- `tests/mbse_benchmark/tracks/`：Harness deterministic、显式 LLM/bare baseline、Agent robustness 三轨基准；各轨独立记录 runtime/profile/provider/model、方法论和哈希元数据。

## 写入与恢复规则

AI 或规则 Runtime 只返回结构化 TaskExecutionResponse。WorkflowRunner 将响应转换为局部 Patch，经实体字段、RelationPredicate、端点类型、状态、锁定标记和 expected revision 校验后提交。CAS 失败返回并发修改错误；`locked` 或 `user_modified` 的实体不能被自动覆盖。

每次运行拥有稳定 `run_id`、methodology/task spec/prompt version、profile/provider/model、input/context/output hash、步骤状态和诊断。纵向生成运行按 Requirements → Functional → Logical → Physical → V&V 顺序提交阶段 Patch，并计算每条 Requirement 的 RFLP、Verification、Validation 和端到端追溯。生成的 LLM 实体只有通过语义校验才进入可编辑的 `validated` 状态；语义失败实体保留为 `candidate`，写入 `semantic_invalid` Issue，人工可通过既有 Review/Edit/Lock 入口接管。每个阶段还返回有界的 decision records，记录内部方法论步骤、结论和依据实体。旧 WorkflowRunner 的 Gate、Repair、Closure 状态机不驱动默认产品路径。

五阶段完成后，`MethodologyEngine` 只读当前 ModelGraph 并输出 findings、metrics、decisions、impact paths 和 recommended tasks；生成结果与 `review.reanalysis.requested` audit 共用同一报告格式。默认链在 R/F/L/P/V&V 中分别落下 Concern、State、Hazard、FailureMode、VerificationCase 和 ValidationCase 等可编辑对象；V&V 计划字段与执行 evidence 分开统计。未知的物理 SWaP-C 值会被标记为 `needs_measurement`，约束冲突会被标记为 `physical_constraint_conflict`，不会直接提升为可行。`SystemsEngineeringController` 将这些反馈收敛为有限的下一步动作：缺证据时暂停等待输入，物理冲突或未评审逻辑分区时提出 Trade Study 选项，并在用户选定后按影响实体调用定向重分析。选定的决策会进入后续 `ContextBundle`、context hash 和结构化 LLM 请求，保证它不只是审计文字而是下一轮推理的输入。它不绕过 Review/CAS，也不替用户无审查地改变工程决策。

模型页提供分层 ModelGraph 工作台，按 System Definition、Functional、Logical、Physical 和 V&V 展示真实实体及其来源、证据、关系和问题计数。实体可在页面内编辑、接受、拒绝、锁定、解锁或请求重新分析；编辑保留实体稳定 ID，通过新的 CAS Revision 记录用户来源，并让锁定实体拒绝后续修改。Requirements 保持独立的需求工作台，避免把需求编辑与下游分层投影混在一起。分析输入门禁以 ModelGraph 为准：任意非 `DEPRECATED` 实体即可作为已有模型种子，空图仍需要需求或可读文档；部分模型生成后的缺层和追溯缺口由 warnings/review findings 表达。

Review 后的显式“继续生成下游”调用 `ModelGenerationService.continue_generation`，按实体所属层路由到下一个 VerticalStage，使用独立的 `vertical_continuation` Run。接受的实体不会被重复改写；锁定实体可作为只读上下文参与 Logical、Physical 或 V&V 推理。续行结束后重新计算 Traceability、Methodology 和 Controller，V&V 是终止层。

`EngineeringDeliverableService` 是只读的交付投影边界。它先加载一次图和 Issue，再生成带统一 revision/hash 的结构化 artifacts；V&V Plan 从 Verification/Validation 行派生，Architecture Report 同时检查 RFLP gaps 和 V&V gaps，因此后置需求未回接时会明确报告 BLOCKED。ZIP 包固定包含 `manifest.json`、`model.json`、`model.sysml`、`requirements.json`、`rflp.json`、`traceability.json`、`vv-plan.json`、`vv-plan.md`、`architecture-report.json` 和 `architecture-report.md`，SysML 仍通过现有 importer 回读到 ModelGraph。

## 对外资源

| 资源 | 入口 |
|---|---|
| 项目 / 文档 | `POST /projects`、`POST /projects/{id}/documents` |
| 分析运行 | `POST /projects/{id}/analysis`（默认五阶段生成；`mode=pipeline/phase` 为兼容入口）、`GET /projects/{id}/controller`、`POST /projects/{id}/controller/execute`（Controller 动作/Trade Study）、`POST /projects/{id}/entities/{entity_id}/reanalyze/execute`（定向重分析）、`POST /projects/{id}/entities/{entity_id}/continue`（Review 后从下一层继续生成）、`GET /projects/{id}/analysis`、`GET /projects/{id}/runs/{run_id}` |
| 模型 | `GET /projects/{id}/model`、`GET /projects/{id}/entities` |
| 人工编辑 | `PATCH /projects/{id}/entities/{entity_id}` |
| 视图 / 导出 | `GET /projects/{id}/views/{view_id}`、`POST /projects/{id}/export`、`GET /projects/{id}/deliverables`、`GET /projects/{id}/deliverables/download`、`POST /projects/{id}/sysml/import`、`POST /projects/{id}/sysml/import/upload` |
| 证据 / Issue | `GET /projects/{id}/evidence`、`GET /projects/{id}/issues`、`POST /projects/{id}/repair`；Controller 证据动作会先调用 Tool Layer 检索 |
| Trace / 配置 | `GET /projects/{id}/trace`、`/model-profiles`、`POST /model-profiles/test` |

## 质量门禁

仓库以 Golden fixture、领域/仓储/方法论/Runtime/API/E2E 测试、`compileall`、Import Linter 和架构预算作为验收基线。旧版智能发现、Concept/MDO、Project Bridge、测试执行、仿真、旧 Job/Baseline/TaskContract 和 MLflow 不属于 Core，已从主包和主测试集移除。
