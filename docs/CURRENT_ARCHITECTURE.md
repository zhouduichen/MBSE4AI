# 当前架构

## 产品主链路

```text
自然语言 / 文档 → Requirements → Functional → Logical → Physical → V&V
              → Typed ModelGraph → SysML v2 subset / 可编辑模型
```

项目目标通过 `ProjectContextService` 进入同一条链：写入 System 的 mission/objectives，并以候选 Requirement 保留来源和后续 RFLP/V&V 追溯；既有 SysML 直接导入 ModelGraph，其他 managed project 则只作为 Controller 的历史检索来源。

这是一个本地模块化单体：Python 3.11、SQLite、FastAPI/Jinja/HTMX，以及可选的 OpenAI-compatible Runtime。产品版本是 `0.2.0`，方法论协议是 `v2.1`。每个项目使用独立工作区和数据库，正式模型和证据仍按项目隔离；Controller 可对其他 managed project 的 FTS 做只读历史检索，命中内容以 Evidence 回写当前项目。`WorkflowRunner` 同时支持完整 23-task 生命周期和单阶段调试；五阶段生成器仍是默认的快速产品入口。

P→V&V 使用同一条可复核的作用域：物理候选和可行性矩阵记录 Requirement→Function→LogicalComponent→PhysicalBlock 的 canonical IDs；出现实测约束冲突时，四类 Trade Study 选项携带冲突字段、受影响 ID 和回流任务/阶段，仍由用户决定是否重新分析。V&V Case 复用这组下游 IDs，并以 `evidence_ids`/`execution_evidence_ids` 把输入资料、计划完整度和实际执行证据分开表示。

输入边界会把需求中的显式功耗、质量、时延、带宽、成本和续航比较式规范化为 canonical `constraints`，并保留 `constraint_provenance`。这些字段沿 Requirement→Function→Logical→Physical 传播；物理值未知时仍进入 `needs_measurement`，只有实测值违反 `max_`/`min_` 边界才报告 `physical_constraint_conflict`。P 层对明确的 `max_*`/`min_*` 约束创建 `level=technical` Technical Requirement，以 `derivedFrom` 回接来源需求、以 `satisfiedBy` 连接物理候选；该技术需求复用来源需求的 RFLP 路径并拥有独立 V&V，未声明约束的需求不会额外拆分。

## 分层与依赖

```text
interface → application → methodology → domain
                         ↘ ports → runtime / repository
bootstrap → application + adapters
adapters → ports + domain
```

- `domain/`：Typed Entity、Relation、ModelGraph、Patch、Requirement 和稳定 ID；不依赖外层。
- `methodology/`：五个产品级 `VerticalStage` 合约和阶段 Prompt；纯 ModelGraph `MethodologyEngine` 负责 Logical 分区/State 信号、Physical 约束/可行性、V&V 计划与证据分层、Hazard/FailureMode 覆盖和四跳 Impact Analysis；23 个细粒度 TaskSpec、四个 Phase、Context/Retrieval、Schema/Validator/Retry、PatchPolicy、谓词感知 Gate/Coverage Matrix、局部 Repair 和 LifecycleOrchestrator 驱动显式的完整 23-task 生命周期，也保留单阶段调试能力。
- `application/`：Project、ProjectContext、ModelGeneration、Analysis、Model、Evidence、V&V Execution、Engineering Tools、Render、EngineeringDeliverable、Settings、Tool Layer 服务；`ProjectContextService` 把用户目标写为 System intent 和候选 Requirement。`ModelGenerationService` 负责五阶段纵向编排、追溯摘要和 Controller 动作执行。`VvExecutionService` 接收用户或外部工具提供的明确 V&V outcome 和证据摘录，通过 CAS 回写 Case 的执行记录，并在同一 Revision 物化稳定 ID 的 `Evidence` 节点和 Case→Evidence `describedBy` 关系；失败时生成可追溯 Issue 和 Controller 迭代入口。`EngineeringToolService` 只执行组合根登记的适配器，将工具输出统一送入 V&V；内置 `model.constraint_check` 读取 Architecture Synthesis 的物理可行性矩阵，不能伪造测量。`EngineeringDeliverableService` 从单一 ModelGraph revision 组合 Requirements、RFLP、Traceability、V&V Plan、Architecture Report、SysML 和 manifest，并可导出固定成员顺序的 ZIP。`EngineeringToolLayer` 将文档/历史/本地 FTS 证据检索封装为受限工具；工具只采集，应用服务统一持久化 Evidence，待被 Case 使用的执行证据同时进入 ModelGraph。
- `repository/`：SQLite ModelRepository v2，保存 Graph、文档 Source Region 对应的 `document_region` Evidence、Run、Step、Patch、Revision、Issue、Closure 和 FTS，并提供 lease/heartbeat。
- `runtime/`：RuntimeFactory、结构化模型端口、OpenAI-compatible 适配和离线 RuleRuntime；每次运行动态解析 active profile。远程 Profile 未提供预算时使用 8192 token 上下文窗口和 4096 token 结构化输出预算，显式配置优先。
- `adapters/`：文档解析、OCR 和模型/文档技术实现；由 `bootstrap/container.py` 组装。
- `interface/`：`ai4mbse` CLI、FastAPI Resource API 和五个资源页面；默认 Analysis 操作调用 `ModelGenerationService`，`mode=pipeline`/`analyze run` 调用真实 23-task 生命周期，`phase` 仍可显式单阶段调试。
- Web 页面使用独立的展示适配层把 VerticalStage、Completion、Methodology 和 Controller 的机器字段转换为用户可读的工程阶段、质量结论和下一步动作；原始任务/实体标识、运行台账和 payload 只在高级详情或稳定 data 属性中保留，不改变 API、ModelGraph 或执行边界。
- `tests/mbse_benchmark/tracks/`：Harness deterministic、显式 LLM/bare baseline、Agent robustness 三轨基准；各轨独立记录 runtime/profile/provider/model、方法论和哈希元数据。

## 写入与恢复规则

AI 或规则 Runtime 只返回结构化 TaskExecutionResponse。WorkflowRunner 将响应转换为局部 Patch，经实体字段、RelationPredicate、端点类型、状态、锁定标记和 expected revision 校验后提交。CAS 失败返回并发修改错误；`locked` 或 `user_modified` 的实体不能被自动覆盖。

每次运行拥有稳定 `run_id`、methodology/task spec/prompt version、profile/provider/model、input/context/output hash、步骤状态和诊断。五阶段生成和完整 23-task 生命周期都按 Requirements → Functional → Logical → Physical → V&V 顺序写入同一份 ModelGraph；输入适配器按句子/列表项建立独立 Requirement，并为每个文档来源保留各自的 `document_region` source/evidence id；文档 Requirement 同时引用该 evidence id，补丁提交时由仓储将已有证据记录物化为同一 revision 的 `Evidence` 节点，随后计算每条 Requirement 的 RFLP、Verification、Validation 和端到端追溯。ContextBuilder 和五阶段生成器会把 Methodology Engine 的有界 `methodology_guidance`（当前阶段 findings、关键指标、架构候选、影响实体和推荐任务）放入下一次结构化 LLM 请求，使确定性工程判断参与生成而不只是事后验收。没有远程模型时，23-task 离线 Runtime 和五阶段 fallback 都从 Function 的职责、显式分区键、共享状态和稳定 ID 形成逻辑分区，为每个分区生成 Physical candidate，并复制已有结构化约束；有 canonical 工程约束时，P 层同时生成技术需求并把物理候选作为直接约束对象；未知 SWaP-C 仍标记为 `needs_measurement`。生成的 LLM 实体只有通过语义校验才进入可编辑的 `validated` 状态；语义失败实体保留为 `candidate`，写入 `semantic_invalid` Issue，人工可通过既有 Review/Edit/Lock 入口接管。每个任务/阶段还返回有界的 decision records，记录方法论步骤、结论和依据实体。LifecycleOrchestrator 会在任一任务语义失败时阻断后续阶段和 Closure，防止任务台账完成掩盖模型未完成。

五阶段完成后，`MethodologyEngine` 只读当前 ModelGraph 并输出 findings、metrics、decisions、impact paths 和 recommended tasks；生成结果与 `review.reanalysis.requested` audit 共用同一报告格式。默认链在 R/F/L/P/V&V 中分别落下 System、Stakeholder、Lifecycle stage/transition、Scenario、Concern、State、Hazard、FailureMode、VerificationCase 和 ValidationCase 等可编辑对象；V&V 计划字段与执行 evidence 分开统计。默认 fallback 的 Function 会保留输入需求驱动的 decomposition，Physical candidate 会保留结构化 trade study 与选择依据。`VvExecutionService` 只接受明确的 `passed`/`failed`/`blocked`/`inconclusive` 结果和调用方提供的 claim/excerpt，不把计划生成当成执行。失败结果写回 Case、Evidence 和 Issue；`MethodologyEngine` 会报告 `verification_execution_failed`/`validation_execution_failed`，其 finding 和 Issue 实体集合包含驱动 Requirement 及 R→F→L→P 下游实体，并保留 impact paths。对真实 `failed` 结果，Controller 在 Assurance 页面提出功能重构、架构替换、需求调整或修订验证条件等 Trade Study 选项；用户选定后才沿影响链调用定向重分析，不自动盲目重跑。`architecture_synthesis` 是其中的可复用纯分析结果：Logical 候选由功能流、共享状态、显式依赖和当前分配形成，逐项记录 partitions、cross-component exchanges、shared-state cuts、coupling/cohesion 和评分；Physical feasibility matrix 记录每个候选的 requirement lineage、propagated constraints、conflicts、missing measurement fields 和 status。未知的物理 SWaP-C 值会被标记为 `needs_measurement`，约束冲突会被标记为 `physical_constraint_conflict`，不会直接提升为可行。`SystemsEngineeringController` 将这些反馈收敛为有限的下一步动作：缺证据时暂停等待输入，物理冲突或未评审逻辑分区时提出 Trade Study 选项，并在用户选定后按影响实体调用定向重分析。选定的决策会进入后续 `ContextBundle`、context hash 和结构化 LLM 请求，保证它不只是审计文字而是下一轮推理的输入。它不绕过 Review/CAS，也不替用户无审查地改变工程决策。

离线 `VerticalRuleRuntime` 会消费已确认的有限决策字段并把它们落实到 ModelGraph：Logical 的 `dependency_cluster_search`、`one_component_per_function`、`shared_coordinator` 和 `current_dependency_partition` 生成带 `architecture_variant`/`architecture_decision` 的新组件、接口和状态，并只弃用未锁定且未被用户修改的旧层；Physical 的候选替换选项新增 `candidate_variant=alternative`，保留约束传播和 provenance。预算或需求类选项只记录决策和待确认问题，不修改实测值或 Requirement；锁定/用户修改的实体阻塞更新时生成未测量替代项。这样 Controller 选项会形成可比较、可追溯的版本，而不是只写入审计日志。

模型页提供分层 ModelGraph 工作台，按 System Definition、Functional、Logical、Physical 和 V&V 展示真实实体及其来源、证据、关系和问题计数。实体可在页面内编辑、接受、拒绝、锁定、解锁或请求重新分析；编辑保留实体稳定 ID，通过新的 CAS Revision 记录用户来源，并让锁定实体拒绝后续修改。定向重分析沿现有 trace 用 `updates` 复用并刷新未被人工修改或锁定的派生对象，保留人工锚点和必要的待评审差异。Requirements 保持独立的需求工作台，避免把需求编辑与下游分层投影混在一起。分析输入门禁以 ModelGraph 为准：任意非 `DEPRECATED` 实体即可作为已有模型种子，空图仍需要需求或可读文档；若部分模型只有 Activity、Operational Scenario 或 System 上下文，离线/规则纵向 Runtime 会在 Requirements 阶段派生带 `source_context_ids` 和 `derived_from_kind` 的可 Review Requirement，并以 `derivedFrom` 回接来源，再交给后续 F/L/P/V&V；其他缺层和追溯缺口由 warnings/review findings 表达。

Review 后的显式“继续生成下游”调用 `ModelGenerationService.continue_generation`，按实体所属层路由到下一个 VerticalStage，使用独立的 `vertical_continuation` Run。接受的实体不会被重复改写；锁定实体可作为只读上下文参与 Logical、Physical 或 V&V 推理。续行结束后重新计算 Traceability、Methodology 和 Controller，V&V 是终止层。

`ModelGenerationService.iterate_controller` 提供有界的 Controller 迭代：每轮读取最新图、选择最高优先级动作，并复用单动作入口执行 `reanalyze` 或成功的 `collect_evidence`。它记录每轮 revision、Traceability 和 finding 变化；`trade_study`、`collect_input`、证据等待、无进展和预算耗尽分别成为明确停止状态。该迭代不新增模型状态机，也不绕过用户决策、CAS、锁定保护或结构化 LLM 边界。Resource API 的 `/controller/iterate` 和 Analysis 工作台的自动推进按钮使用同一返回结构。

`EngineeringDeliverableService` 是只读的交付投影边界。它先加载一次图和 Issue，再生成带统一 revision/hash 的结构化 artifacts；V&V Plan 从 Verification/Validation 行派生，Architecture Report 同时检查 RFLP gaps 和 V&V gaps，因此后置需求未回接时会明确报告 BLOCKED。ZIP 包固定包含 `manifest.json`、`model.json`、`evidence.json`、`model.sysml`、`requirements.json`、`rflp.json`、`rflp.svg`、`traceability.json`、`vv-plan.json`、`vv-plan.md`、`architecture-report.json` 和 `architecture-report.md`。`rflp.svg` 与 RFLP JSON 来自同一图快照，便于直接查看 R→F→L→P 关系；`evidence.json` 是项目级证据库的确定性快照，含独立 evidence hash；实体、关系或 V&V payload 引用的已有证据会在模型补丁提交时物化为同一 revision 的 `Evidence` 节点，未绑定证据仍作为外部检索上下文保留；`model.json` 同时携带证据记录，实体/关系仍通过稳定 evidence IDs 引用，导出不会隐式创建 ModelGraph Revision。`model.sysml` 使用明确的声明属性表达实体 kind、name、status、来源、修订和 payload，核心关系使用 `satisfy`/`allocate`/`verify`/`validate` 语句；稳定 ID、非核心谓词和完整追溯通过元数据保留，导入器既能读取无注释声明，也能把声明属性编辑回写为 ModelGraph。

编辑后的影响分析由纯 ModelGraph `TypedImpactPlanner` 计算，并以 revision-bound `ImpactPlan` 同时服务 Resource API、Review 和定向重分析；它不会调用本地模型或改变图，只负责把 typed 关系传播结果交给后续阶段和 Controller。

## 对外资源

| 资源 | 入口 |
|---|---|
| 项目 / 目标 / 文档 | `POST /projects`、`POST /projects/{id}/goal`、`GET /projects/{id}/context`、`POST /projects/{id}/documents` |
| 分析运行 | `POST /projects/{id}/analysis`（默认五阶段生成；`mode=pipeline` 为完整 23-task；`mode=phase` 为单阶段调试；成功响应中的 `run.deliverable` 绑定本次 revision/snapshot 并提供交付包入口）、`GET /projects/{id}/controller`、`POST /projects/{id}/controller/execute`（Controller 动作/Trade Study）、`POST /projects/{id}/controller/iterate`（有界自动推进安全动作）、`POST /projects/{id}/entities/{entity_id}/reanalyze/execute`（定向重分析）、`POST /projects/{id}/entities/{entity_id}/continue`（Review 后从下一层继续生成）、`POST /projects/{id}/vv/{case_id}/execute`（记录真实 V&V 结果并触发失败反馈）、`GET /projects/{id}/tools`、`POST /projects/{id}/vv/{case_id}/tools/{tool_id}/execute`（运行登记工具并统一写入 V&V）、`GET /projects/{id}/analysis`、`GET /projects/{id}/runs/{run_id}` |
| 模型 | `GET /projects/{id}/model`、`GET /projects/{id}/entities`、`GET /projects/{id}/entities/{entity_id}/impact`（Typed Impact Plan） |
| 人工编辑 | `PATCH /projects/{id}/entities/{entity_id}` |
| 视图 / 导出 | `GET /projects/{id}/views/{view_id}`、`POST /projects/{id}/export`、`GET /projects/{id}/deliverables`、`GET /projects/{id}/deliverables/download`、`POST /projects/{id}/sysml/import`、`POST /projects/{id}/sysml/import/upload` |
| 证据 / Issue | `GET /projects/{id}/evidence`、`GET /projects/{id}/issues`、`POST /projects/{id}/repair`；Controller 证据动作会先调用 Tool Layer 检索 |
| Trace / 配置 | `GET /projects/{id}/trace`、`/model-profiles`、`POST /model-profiles/test` |

## 质量门禁

仓库以 Golden fixture、领域/仓储/方法论/Runtime/API/E2E 测试、`compileall`、Import Linter 和架构预算作为验收基线。旧版智能发现、Concept/MDO、Project Bridge、测试执行、仿真、旧 Job/Baseline/TaskContract 和 MLflow 不属于 Core，已从主包和主测试集移除。

## 当前纵向推理增强

五阶段生成现在逐项计算其内部 23-task 完成检查，并把结果同时返回给工作台、写入阶段审计摘要、反馈到下一次 `methodology_guidance`。Logical 阶段读取功能依赖和功能流端点，支持有证据的传递聚类；没有明确边界证据的独立需求仍保持独立组件，同时在组件载荷中记录 flow、cross-component、内聚/耦合和备选分区证据。Physical 和 V&V 阶段对约束传播、可行性权衡和交叉分析字段执行同一套确定性完成检查；缺口会进入 `needs_review`，而不是伪报完整。

追溯闭环另有共享的 `requirement_trace_scope` 规则：它沿需求派生链解析
Function→LogicalComponent→PhysicalBlock，并合并技术需求的直接物理分配；
`vv_scope_matches` 将 Verification/Validation payload 中的作用域与图关系逐项
比较。作用域不一致时，`global_cross_analysis` 不通过，Methodology Engine 记录
`vv_scope_mismatch` 及其受影响的 RFLP/V&V 实体，Controller 复用既有验证与确认
重分析入口。这个检查不改变用户输入或执行证据，只避免陈旧计划被统计为闭环。
