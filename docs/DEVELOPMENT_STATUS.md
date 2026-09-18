# 开发状态

**更新时间：** 2026-09-18
**产品版本：** rflp-lite 0.2.0
**方法论协议：** v2.1

## 已完成

| 能力 | 验收口径 |
|---|---|
| Typed ModelGraph | 统一实体、关系、生命周期、来源、证据和稳定 ID |
| Repository v2 | SQLite 事务、CAS Revision、Run/Step/Patch/Issue 台账、FTS |
| 四阶段方法论 | Operational、Functional、Logical/Physical、Assurance 加 Closure，共 23 个任务 |
| 结构化 Runtime | 离线 RuleRuntime 可运行；OpenAI-compatible Runtime 走 TaskProposal→Compiler→Patch 边界 |
| Gate / Repair | 覆盖率、语义、RFLP、证据、验证门禁；失败写 Issue，修复受 PatchPolicy 局部约束并定向重新 Gate |
| 生命周期闭环 | 单次调用串联四阶段、Global Gate、Closure manifest、冻结 revision 和审计摘要；指定 phase 保留调试入口 |
| 运行可追溯 | active profile/provider/model、TaskSpec/prompt/context/input/output hash、step ledger、lease/heartbeat |
| 方法论智能化重构 | 23 个独立版本化 Prompt、可执行 Validator、谓词感知 Coverage Matrix、局部语义 Repair、Completion/Failure DSL、分层 Context Planner |
| Benchmark 三轨 | Harness deterministic、显式 LLM + same-model bare baseline、Agent robustness faults 分开运行和报告，不共享总分 |
| 资源服务 | Project、Analysis、Model、Evidence、Render、Settings 服务及统一依赖组装 |
| CLI / Web | `ai4mbse` 命令、完整 Analysis 工作流页、Trace 页、连接测试和 JSON/SVG/DOT/SysML-lite 导出 |
| CLI 单次模型选择 | `analyze generate --profile <id>` 可为本次五阶段生成选择已保存 Profile，不修改 active profile；适用于远程 SSH/Tailscale 模型验收 |
| Web 单次模型选择 | Analysis 页面和 `/analysis` API 支持请求级 Profile 选择，显示无密钥摘要并保留 active profile 不变 |
| Web 主流程入口 | `/` 重定向到项目列表；分析页支持需求文本和文档上传；无输入项目禁止运行分析并在页面禁用运行按钮 |
| Web 异步纵向生成 | `POST /projects/{id}/analysis/runs` 立即创建后台 Run 并返回 `202`；`GET /projects/{id}/runs/{run_id}` 复用 Run/Step 台账投影五阶段进度，Analysis 页面轮询并展示当前阶段；单阶段调试入口保持同步兼容 |
| Web 运行配置 | 设置页支持保存模型配置、激活已有配置和连接测试；API Key 不进入页面或公开响应 |
| 文档接入 | TXT、Markdown、DOCX、PDF 解析；扫描 PDF 使用可选 OCR 适配器 |
| 文档证据上下文 | 解析出的每个 Source Region 持久化为 `document_region` Evidence，文档 Requirement 同时保存 source/evidence ID，补丁提交时物化为 ModelGraph 节点并进入五阶段结构化 LLM 上下文 |
| 自动文档到模型纵向入口 | `analyze generate` 与 Web `/analysis` 自动执行 IntakeDraft→CAS→R→F→L→P→V&V；离线规则摄取明确标记 `degraded`/`RULE`，并保留独立人工 Review 入口 |
| Golden E2E | 校园无人配送机器人 fixture 可导入并跑完整阶段；失败与锁定保护可验证 |
| 默认产品纵向生成 | 自然语言或已解析文档 → Requirements → Functional → Logical → Physical → V&V；五阶段写入同一 ModelGraph，并返回阶段结果、追溯摘要和 SysML 文本 |
| 完整 23-task 纵向生命周期 | `analyze run` / 显式 `mode=pipeline` 共享自然语言、文档区域和 ModelGraph 输入；23 个任务逐任务产生真实 typed entities/relations/updates，形成 R→F→L→P→V&V，并在语义任务失败时阻断后续阶段与 Closure |
| 23-task 依赖安全并行 | 配置 Runtime 声明支持并行时，Operational、Functional、Logical/Physical、Assurance 内的独立任务组共享只读快照并发请求；`max_parallel_requests` 统一限制任务级与 Requirement batch 级并发（1–4，远程 Profile 默认 2），结果按固定顺序合并后仍经过 Validator/CAS，离线/未声明并行能力时保持串行 |
| 统一完整生命周期结果投影 | Pipeline Report 从同一份 ModelGraph revision 只读计算 Traceability、Methodology findings/metrics 和 Controller actions；显式 pipeline API、Analysis 工作台和交付物共享 revision/snapshot hash，报告不创建 Run/Patch、不额外调用 LLM |
| 多需求输入保真 | 自然语言句子/列表项和文档独立条目分别形成 Requirement；文档来源保留 Source Region，三条输入需求可形成三条 Function 和三条完整 RFLP/V&V 路径 |
| 23-task 需求作用域 | 多条自然语言 Requirement 在 Function→Logical→Physical→Technical Requirement→V&V 之间保持局部追溯；物理约束不再跨候选污染，FMEA 风险按运行活动聚合以保持任务 Patch 有界 |
| 自然语言工程约束抽取 | 显式功耗、质量、时延、带宽、成本和续航边界规范化为 canonical constraints，保留 constraint provenance，并随 R→F→L→P 进入物理可行性分析；未知值仍要求测量/评审 |
| Physical Technical Requirement 闭环 | 对明确的 `max_*`/`min_*` 约束生成可审查的技术需求，回接来源需求和物理候选，进入独立 V&V、Traceability、SysML 和统一交付包；不伪造测量或可行性结论 |
| Physical→V&V 推理回流证据 | 物理可行性行和 ModelGraph 候选共同保存 Requirement→Function→Logical→Physical 影响链；实测冲突时生成带回流阶段、冲突字段和受影响 ID 的四类 Trade Study 选项，V&V 计划复用同一作用域并显式区分未执行证据 |
| 数据驱动架构综合 | Fallback 根据 Function 的显式依赖、功能流、分区键、共享状态和稳定 ID 形成可解释的 Logical 分区与跨组件交互证据；每个分区生成 Physical 候选，并沿 Requirement→Function→Logical→Physical 传播已有结构化约束 |
| 一等架构推理载荷 | 五阶段和完整 23-task 路径都在同一 ModelGraph 中持久化 LogicalComponent 的分区依据/候选架构/评分/选择状态，以及 PhysicalBlock 的约束传播/测量缺口/冲突/可行性状态/回流选项；同一事实由 Controller、Workbench 和 SysML 往返复用 |
| Methodology Engine v2 架构约束推理 | Logical 候选显式评估时序协调切分和安全隔离违反；结构化候选、Methodology guidance、Controller 复核信号、Workbench、SysML 往返和 Architecture Report 复用同一证据；自然语言安全文本没有明确端点时不被推断为硬约束 |
| LLM 五阶段接入 | 每个纵向阶段通过现有 StructuredModelRuntime 的 TaskProposal → Compiler → Patch 边界执行；测试覆盖五次真实 stage lens 调用 |
| F/L/P 阶段方法论契约 | 每次 vertical LLM 请求显式收到 stage contract（输入/输出/必需类型、允许关系和 reasoning tasks）；ContextBuilder 以完整 ModelGraph 为源，按当前预算只投影 context 可见的逐需求 requirement_worklist，并携带已有 canonical 目标、当前路径、精确缺口和 omitted_requirement_ids；Functional 完成度校验功能流端点/场景覆盖，Logical/Physical 校验可复核架构与可行性推理证据 |
| LLM Controller 决策提案 | 配置的 OpenAI-compatible Profile 可基于有界 ModelGraph/方法论上下文给出只读建议；建议必须引用确定性 Controller 已有动作并通过用户确认后才执行；离线模式保持确定性，真实 Provider 验证仅使用远程 SSH/Tailscale 模型 |
| Controller 工作台按需建议 | Assurance 首屏先渲染确定性下一步动作；LLM 建议通过 `include_llm=true` 按需请求，远程节点不可达时不阻塞工作台，也不调用本机模型 |
| LLM 阶段反馈闭环 | 结构化 LLM 阶段默认保持远程单次 Proposal pass；远程 Requirements 对缺失 Operational 类型做最多四次有界补全，V&V 按每条需求拆分 Verification/Validation Case 并行请求；typed completion bridge 只有显式开启才使用；同一 Step/audit 保留最终 attempt，离线 RuleRuntime 保持每阶段单次 |
| SysML v2 子集往返 | 导出实际 `part/requirement/action/interface/state/verification/validation` 声明及关系元数据；Concern、Hazard、FailureMode 使用可编辑的通用 part 声明并保留类型元数据；可重新读入新项目并继续编辑 |
| 产品验收指标 | 以 R→F→L→P→V&V 完整追溯、SysML 往返和 ModelGraph 编辑为主，不再以 23-task 重复运行次数作为主进度指标 |
| 语义质量口径 | `semantic_invalid` 输出只保存为 candidate、创建 review Issue，不再通过移除 semantic validator 的方式写成 validated |
| 追溯质量口径 | 分开报告 RFLP、Verification、Validation 和端到端闭环；Verification 或 Validation 单独存在均不算端到端完成 |
| 内部推理记录 | 五阶段保留 23-task/架构分析映射，并以 bounded decision records 表达 clustering、constraint propagation、feasibility selection 等决策 |
| Methodology Engine v1 | 对 ModelGraph 实现 Logical 分区质量、Physical 约束冲突/待测量、Verification/Validation 结构完整度和四跳变更影响分析，并接入生成、Review 与 Web 工作台 |
| 定向重新分析 Controller | Review 请求支持影响路径和下一步 task 路由；执行入口按修改实体从受影响阶段向下重跑，复用并更新未受保护的派生对象、保持 canonical ID，并保留独立 Run、Patch、Revision 与 audit |
| Systems Engineering Controller | 将 Methodology findings 路由为缺证据/补输入/重新分析/Trade Study 动作；支持用户选择物理或逻辑架构方案后按影响实体执行定向重分析，并在 Web/API 中显示决策状态 |
| Controller 决策上下文 | Trade Study 选择进入定向重分析的 ContextBundle、上下文哈希和结构化 LLM 请求，后续阶段能够消费用户已确认的方案 |
| 决策驱动架构迭代 | Logical Trade Study 可生成按功能隔离或共享协调器变体并安全弃用旧分区；Physical Trade Study 可生成保留约束/provenance 的替代候选；决策来源写回 ModelGraph，锁定实体不被覆盖，未知测量仍保持待验证 |
| Controller 自动迭代闭环 | 可有界执行安全的局部重分析/证据检索，逐轮刷新 Traceability、Methodology 和 Controller；在 Trade Study、用户输入/证据、无进展或预算耗尽时暂停，并通过 API/Web 工作台暴露 |
| Controller Tool Layer | 证据缺口先调用文档/历史/本地 FTS 检索工具；结果持久化为 Evidence 后再触发受影响阶段重分析，无结果才等待用户补充 |
| MBSE 对象纵向覆盖 | 默认五阶段显式生成 Concern、State、Hazard、FailureMode、VerificationCase 和 ValidationCase；VerificationCase/ValidationCase 统一包含 method、verification_objective、precondition、test_condition、input、stimulus、procedure、expected_result、pass_criteria，方法学报告分别检查风险覆盖、缓解关系、计划完整度和执行证据 |
| 分层 ModelGraph 工作台 | MBSE 模型页按 System Definition、Functional、Logical、Physical、V&V 展示真实实体，并复用 Review/CAS API 支持编辑、接受、拒绝、锁定、解锁和重新分析 |
| Review 后继续生成 | 用户确认实体后可从其下一层继续生成至 V&V；使用独立 continuation Run，锁定实体只读，V&V 返回无下游状态 |
| 统一工程交付包 | 同一 ModelGraph revision 输出 model/evidence/SysML/Requirements/Behavior/RFLP JSON+SVG/Traceability/V&V Plan/Architecture Report；Behavior 固化 Use Case、Operational Scenario、Activity 和 Sequence Diagram Framework；存在对应审计记录时额外输出 `concept-design.json` 与 `detail-design.json`，固化候选布局、学科评估、优化运行、CAD 模型、标注和 DFM/DFA Review；`evidence.json` 固化项目级证据记录与 evidence hash，被模型补丁引用的证据会同步物化为 `Evidence` 节点，提供 JSON、固定成员 ZIP 和 SysML 回读证据 |
| 23-task 纵向追溯回接 | 后置 functional/technical/reverse requirement 自动回接 Function 与 V&V；校园配送 fixture 交付包验证 7/7 需求完整追溯 |
| 已有 SysML 模型输入 | Web Analysis 支持上传 `.sysml`，通过同一解析器导入 ModelGraph；任意非弃用实体组成的局部模型都可作为分析种子，冲突 ID 在写入前拒绝，并可继续生成、编辑和导出 |
| 用户目标与历史项目输入 | `project goal`、Web `/projects/{id}/goal` 和 Analysis 页面可把目标写入 System mission/objectives 及候选 Requirement；Controller Tool Layer 通过只读跨项目 FTS 检索历史项目模型、文档区域和证据，并将命中结果作为当前项目 Evidence 使用 |
| V&V 执行反馈闭环 | `vv record`、Web `/projects/{id}/vv/{case_id}/execute` 和 Assurance 页面接受外部测试/演示的明确结果与证据摘录；输入资料与实际执行结果分别写入 `evidence_ids`/`execution_evidence_ids`，结果回写 V&V Case，并在同一 Revision 物化 `Evidence` 节点及 `describedBy` 关系；失败生成包含 R→F→L→P 影响实体的 Issue，并在 Assurance 页面给出需人工选择的 Trade Study 迭代入口，重复执行保留历史 |
| 工程工具结果闭环 | `vv tool`、`/projects/{id}/tools` 和 `/projects/{id}/vv/{case_id}/tools/{tool_id}/execute` 提供显式注册的工具适配器；内置模型约束检查器把物理可行性分析结果写入 V&V Evidence，缺少测量字段保持 `inconclusive`，失败沿 Controller 进入迭代 |
| 方法论驱动生成上下文 | Methodology Engine 将当前阶段的 findings、指标、架构候选、影响实体和推荐任务以有界 `methodology_guidance` 注入五阶段及 23-task LLM 请求，确定性工程检查从事后验收前移为生成约束 |
| Provider 请求上下文预算 | ContextPlanner 与 Provider 共享模型无关的 token 估算；结构化请求发送前保证 prompt 与 output 不超过 profile 的 context window，结构化 repair 复用同一预算，无法容纳时明确返回 `context_window_exceeded` 而不发送隐式超窗请求 |
| 垂直阶段完成质量 | 五阶段结果逐项报告其内部 23-task 检查；关键关系、架构评价、约束传播、可行性权衡和 V&V 交叉分析缺失时标记 `needs_review`，并保留结构化候选供 Review/Controller 继续处理 |
| 完整结构化五阶段验收 | 确定性结构化模型夹具已通过生产 Runtime→Compiler→Validator→CAS 路径一次性形成 R→F→L→P→V&V；覆盖 payload local_ref canonicalization、完整 V&V scope、SysML round-trip 和可继续编辑 revision |
| 多需求结构化五阶段验收 | 三条独立自然语言 Requirement 已通过生产结构化 Runtime→Compiler→Validator→CAS 路径分别形成 Function，并沿共享或独立的 Logical/Physical 架构保持逐需求 V&V scope、三条完整端到端追溯、SysML round-trip 和继续编辑；该证据仍是离线结构化模型验收，不等同于真实 Provider 稳定性 |
| 大输入 V&V 批处理 | 配置的 OpenAI-compatible Runtime 对 V&V 按配置批大小生成并合并结构化 Patch；独立批次可并行请求，5 条需求形成 10 个 V&V Case、完整追溯、SysML 往返和可编辑 revision；任一批失败不提交部分结果；仍不等同于真实远程 Provider 稳定性 |
| 大输入 RFLP 批处理 | 配置的 OpenAI-compatible Runtime 对 Functional、Logical、Physical 与 V&V 统一支持按 Requirement 分批；同阶段独立批次可并行，批次只携带当前 Requirement、typed targets、System 和一跳关系邻居，全部 Proposal 合并后才进入既有 Validator/CAS 边界，避免大输入只处理上下文前缀或触发 Provider 超窗 |
| 完整纵向 Requirement worklist | 纵向结构化 Runtime 不再静默截断超过 24 条的 Requirement；支持批处理的 Provider 按完整 worklist 分批，所有需求在进入 Compiler/CAS 前均保留逐条覆盖 |
| 逐需求纵向覆盖反馈 | Functional、Logical、Physical、Verification/Validation 阶段逐条解析活动 Requirement 的覆盖链，输出精确缺失 ID；反馈轮只修复当前阶段缺口，并在 Analysis 工作台显示逐条覆盖结论；远程默认不重复调用每个批次 |
| 上下文可见性追溯 | worklist 保留完整图上的 `current` 追溯，同时标注 `available_current` 与 `unavailable_current`；结构化 LLM 只能引用当前 Context 可见的 canonical ID，延后目标进入后续继续分析 |
| 阶段化方法论决策包 | Methodology guidance 按 Requirements、Functional、Logical、Physical、Assurance 筛选对应决策记录，并以 `decision_package` 同时提供给 LLM、Controller 和工作台，避免跨阶段决策污染当前推理 |
| Requirements 质量推理 | Requirements 阶段检查声明、义务、验证方法和工程约束来源，输出逐条质量指标与可执行 finding；只提供推理依据，不自动改写用户需求 |
| Controller 物理冲突回流 | 在同一结构化 ModelGraph 上验证 physical constraint conflict→Trade Study 暂停→用户选择替代候选→仅 Physical/V&V 定向重分析；锁定和 user_modified 实体保持不变 |
| 用户面工程工作台 | 分析、模型和验证与确认页面以需求→功能→逻辑→物理→V&V 的业务语言呈现阶段质量、追溯闭环和下一步动作；任务键、运行台账、模型标识和原始属性收进高级详情，保留既有编辑、权衡和执行入口 |
| 追溯语义闭环 | 同一 canonical scope resolver 校验需求来源、功能、逻辑、物理及 V&V 载荷；技术需求支持来源链与直接物理候选，作用域失配会同时阻断 Assurance 完成检查并生成可回流的工程问题 |
| 统一需求输入边界 | 五阶段生成与 23-task pipeline 共享 `InputPreparationService`→`RequirementsUseCaseService`→CAS；文本/文档可组合输入，重复 statement 复用节点并通过 CAS 合并全部 Source Region/evidence provenance，多条需求保持独立下游追溯 |
| Pipeline 文档直通验收 | `project ingest` 后直接执行 `analyze run` 或 Web `mode=pipeline` 会自动生成 Requirement、Use Case、Operational Scenario、Activity，再完成 23-task 生命周期与追溯；不需要手动应用 IntakeDraft |
| 行为时序投影（1.2） | Behavior API/UI 从 ModelGraph 中的 Operational Scenario/Activity 确定性生成参与者、消息、守卫、分支和 Mermaid Sequence Diagram；保留 scenario/activity ID，编辑源实体后可重新读取，不新增同步图实体或模型调用 |
| 指标包络建议与 MDO 展示（2.1/2.2） | `/concept-design/input` 从根 Requirement 的显式约束生成可编辑 envelope 草案和证据/缺口列表；总体设计页展示每个候选的气动、结构、重量/重心结果以及 Pareto/优化反馈，缺失工程输入保持 `needs_input` |
| 统一追溯投影 | `resolve_requirement_trace` 成为 Generation Summary、Traceability/Coverage/RFLP、`/trace` 和 `traceability.json` 的共同逐需求语义来源；ready-only 目标、V&V scope、缺口、主路径和覆盖率在各入口保持一致，并保留 SysML/ModelGraph 编辑回读 |
| 可执行 V&V 计划闭环 | V&V prompt、结构化 Schema、语义校核、离线/生命周期运行时、Methodology、Assurance 页面和 `vv-plan` 交付物共享九字段计划契约；来源 `evidence_ids` 与实际 `execution_evidence_ids` 分离，计划完整不宣称执行通过 |
| 候选状态与完成度隔离 | 候选实体保留在 Review、架构候选和约束分析上下文中，但只有 validated/accepted/locked 实体参与 Methodology 完成度与覆盖统计；候选 Physical 仍可触发冲突检测和 Trade Study |
| 总体布局候选生成（2.1） | 版本化声明式领域包、JSON/CSV 历史方案导入、加权相似检索、确定性 3–5 套满足硬约束的候选、来源/差异/约束余量、俯视/侧视概念 SVG；可将人工选择候选写入现有 `PhysicalBlock` |
| 设计来源自动回接（2.1/3.1） | 概念布局与 CAD 意图在未显式选取来源时自动读取当前 ModelGraph 的根 Requirement；显式来源保持优先，应用后通过 `satisfiedBy`/来源载荷保留需求→设计对象追溯 |
| 详细设计开发切片（3.1–3.3） | 设计意图与澄清、稳定 ID 的结构选型推荐及用户选择、支架/底座加筋板式与整体块式 profile 到 `add_rib`/`add_fillet` 的参数化操作编译、CAD 操作计划、预览/审批/执行门、远程 FreeCAD headless 实体生成与 FCStd/STEP 回读、几何摘要、共享 2D/3D 标注/基准/GD&T 候选、厂商无关二维图纸 SVG 预览、风险高亮 SVG、DFM/DFA finding、审查状态、审查结果回接 PhysicalBlock/SysML 和审计链；推荐不会自动成为批准事实，壳体/轴/齿轮 profile 仍保留为后续扩展，preview 图纸与规则结果仍是 development evidence，正式制造结论仍需客户标准和规则库 |
| 多学科快速评估（2.2） | 气动、结构、重量/重心三个适配器有界并行执行；保留输入/输出哈希、适配器版本、缓存、失败隔离、代理有效域门禁、帕累托排序和有界优化反馈；每条评估额外固化输入参数、有效域状态、验证数据集、误差/批准诊断，候选摘要记录完成度和失败学科；内置计算器固定标记为 development evidence |

## 历史 Harness 验收边界

| 检查项 | 当前状态 |
|---|---|
| Model connectivity | PASS |
| Native Ollama invocation | PASS |
| Structured MBSE contract | PASS（60/60 provider success；58/60 structural/schema/compile/domain pass） |
| Full 23-task LLM lifecycle | SCRIPTED STRUCTURED ACCEPTED；已用脚本化 StructuredModelRuntime 验证 23 个 TaskSpec→Compiler→Validator→Workflow 调用顺序；真实 Provider 多轮稳定性仍 NOT ACCEPTED |

PR09 的 conformance runner 位于 `tests/contract_conformance/`，默认使用离线 fixture；真实 Ollama 测试必须显式设置 `RFLP_RUN_LIVE_LLM=1`。最终 3 Task × 20 结果为：provider/JSON/schema/compile/domain 均 58/60，2 次 structural retry 未恢复。该结果仅说明结构化边界已有基础覆盖，不能替代新的五阶段产品链验收。

最终 live artifact：`docs/superpowers/artifacts/pr09/contract-conformance-1789049206566817000.json`。五阶段主验收位于 `tests/e2e/test_vertical_model_generation.py`；完整 23-task 主验收位于 `tests/e2e/test_legacy_pipeline.py`、`tests/runtime/test_lifecycle_rule_runtime.py` 和 `tests/application/test_sysml_v2.py`。脚本模型验收不等同于真实 Provider 稳定性。

Methodology Engine v1 的边界是确定性反馈；Systems Engineering Controller v1 已将这些反馈转成有限动作，并允许用户比较候选方案后提交 Trade Study 决策。Review 后可显式继续生成下游：系统从已接受实体的下一层运行到 V&V，锁定实体作为只读锚点，V&V 不创建空的后续运行。当前 Controller 仍不替用户无审查地改写工程事实或选择方案；V&V 已支持外部结果/证据接入和失败反馈，工程工具已有注册式结果端口和内置模型约束分析器，详细设计已接通远程 FreeCAD 实体适配器，但真实测试执行沙箱、仿真适配和更完整 CAD/PMI 工具连接仍需按客户环境接入。

## 当前验收命令

全量测试使用临时空 LLM 配置并强制离线 CAD，避免读取开发机上的活动 Profile：

```bash
./.venv/bin/python -m pytest -q tests/e2e/test_local_product_acceptance.py
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview ./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/lint-imports
# Optional remote FreeCAD check; intentionally not run in the local-only phase.
# AI4MBSE_CAD_BACKEND=freecad-remote ./.venv/bin/pytest -q tests/integration/test_freecad_remote.py
```

## 明确边界

本版本已将 2.1/2.2 的概念布局与多学科快速评估切片接回 Core，并将 3.1–3.3 接到远程 FreeCAD 真实几何链。默认 preview 不触碰本机模型；设置 `AI4MBSE_CAD_BACKEND=freecad-remote` 后使用 `Jiayu-intern` 上的独立 FreeCAD 环境，输出 FCStd/STEP 并回读验证。固定翼评估器、GD&T 标准映射和 DFM/DFA 规则仍是开发证据；正式工程结论仍需客户批准的真实标准、规则库和验证合格适配器。

Track B 需要显式配置 profile，不能在无密钥 CI 中默认运行：

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py --track llm --profile <profile-id>
```

要验收产品五阶段纵向链（而不是兼容性的 23-task `WorkflowRunner`），显式选择
`--path vertical`：

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py \
  --track llm --profile windows-5080-ollama --path vertical \
  --case CASE-04 --repeats 1 --timeout 1800 --baseline bare
```

该命令要求显式 LLM profile；不会回退到本机模型。默认 `--path lifecycle`
仍保留旧的 23-task benchmark 入口。
