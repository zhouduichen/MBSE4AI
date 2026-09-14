# 开发状态

**更新时间：** 2026-09-14
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
| Web 主流程入口 | `/` 重定向到项目列表；分析页支持需求文本和文档上传；无输入项目禁止运行分析并在页面禁用运行按钮 |
| Web 运行配置 | 设置页支持保存模型配置、激活已有配置和连接测试；API Key 不进入页面或公开响应 |
| 文档接入 | TXT、Markdown、DOCX、PDF 解析；扫描 PDF 使用可选 OCR 适配器 |
| 文档证据上下文 | 解析出的每个 Source Region 持久化为 `document_region` Evidence，文档 Requirement 同时保存 source/evidence ID，补丁提交时物化为 ModelGraph 节点并进入五阶段结构化 LLM 上下文 |
| Golden E2E | 校园无人配送机器人 fixture 可导入并跑完整阶段；失败与锁定保护可验证 |
| 默认产品纵向生成 | 自然语言或已解析文档 → Requirements → Functional → Logical → Physical → V&V；五阶段写入同一 ModelGraph，并返回阶段结果、追溯摘要和 SysML 文本 |
| 完整 23-task 纵向生命周期 | `analyze run` / Web `mode=pipeline` 共享自然语言、文档区域和 ModelGraph 输入；23 个任务逐任务产生真实 typed entities/relations/updates，形成 R→F→L→P→V&V，并在语义任务失败时阻断后续阶段与 Closure |
| 多需求输入保真 | 自然语言句子/列表项和文档独立条目分别形成 Requirement；文档来源保留 Source Region，三条输入需求可形成三条 Function 和三条完整 RFLP/V&V 路径 |
| 自然语言工程约束抽取 | 显式功耗、质量、时延、带宽、成本和续航边界规范化为 canonical constraints，保留 constraint provenance，并随 R→F→L→P 进入物理可行性分析；未知值仍要求测量/评审 |
| Physical Technical Requirement 闭环 | 对明确的 `max_*`/`min_*` 约束生成可审查的技术需求，回接来源需求和物理候选，进入独立 V&V、Traceability、SysML 和统一交付包；不伪造测量或可行性结论 |
| Physical→V&V 推理回流证据 | 物理可行性行和 ModelGraph 候选共同保存 Requirement→Function→Logical→Physical 影响链；实测冲突时生成带回流阶段、冲突字段和受影响 ID 的四类 Trade Study 选项，V&V 计划复用同一作用域并显式区分未执行证据 |
| 数据驱动架构综合 | Fallback 根据 Function 的显式依赖、功能流、分区键、共享状态和稳定 ID 形成可解释的 Logical 分区与跨组件交互证据；每个分区生成 Physical 候选，并沿 Requirement→Function→Logical→Physical 传播已有结构化约束 |
| LLM 五阶段接入 | 每个纵向阶段通过现有 StructuredModelRuntime 的 TaskProposal → Compiler → Patch 边界执行；测试覆盖五次真实 stage lens 调用 |
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
| MBSE 对象纵向覆盖 | 默认五阶段显式生成 Concern、State、Hazard、FailureMode、VerificationCase 和 ValidationCase；方法学报告分别检查风险覆盖、缓解关系、V&V 计划字段和执行证据 |
| 分层 ModelGraph 工作台 | MBSE 模型页按 System Definition、Functional、Logical、Physical、V&V 展示真实实体，并复用 Review/CAS API 支持编辑、接受、拒绝、锁定、解锁和重新分析 |
| Review 后继续生成 | 用户确认实体后可从其下一层继续生成至 V&V；使用独立 continuation Run，锁定实体只读，V&V 返回无下游状态 |
| 统一工程交付包 | 同一 ModelGraph revision 输出 model/evidence/SysML/RFLP JSON+SVG/Requirements/Traceability/V&V Plan/Architecture Report；`evidence.json` 固化项目级证据记录与 evidence hash，被模型补丁引用的证据会同步物化为 `Evidence` 节点，提供 JSON、固定成员 ZIP 和 SysML 回读证据 |
| 23-task 纵向追溯回接 | 后置 functional/technical/reverse requirement 自动回接 Function 与 V&V；校园配送 fixture 交付包验证 7/7 需求完整追溯 |
| 已有 SysML 模型输入 | Web Analysis 支持上传 `.sysml`，通过同一解析器导入 ModelGraph；任意非弃用实体组成的局部模型都可作为分析种子，冲突 ID 在写入前拒绝，并可继续生成、编辑和导出 |
| 用户目标与历史项目输入 | `project goal`、Web `/projects/{id}/goal` 和 Analysis 页面可把目标写入 System mission/objectives 及候选 Requirement；Controller Tool Layer 通过只读跨项目 FTS 检索历史项目模型、文档区域和证据，并将命中结果作为当前项目 Evidence 使用 |
| V&V 执行反馈闭环 | `vv record`、Web `/projects/{id}/vv/{case_id}/execute` 和 Assurance 页面接受外部测试/演示的明确结果与证据摘录；输入资料与实际执行结果分别写入 `evidence_ids`/`execution_evidence_ids`，结果回写 V&V Case，并在同一 Revision 物化 `Evidence` 节点及 `describedBy` 关系；失败生成包含 R→F→L→P 影响实体的 Issue，并在 Assurance 页面给出需人工选择的 Trade Study 迭代入口，重复执行保留历史 |
| 工程工具结果闭环 | `vv tool`、`/projects/{id}/tools` 和 `/projects/{id}/vv/{case_id}/tools/{tool_id}/execute` 提供显式注册的工具适配器；内置模型约束检查器把物理可行性分析结果写入 V&V Evidence，缺少测量字段保持 `inconclusive`，失败沿 Controller 进入迭代 |
| 方法论驱动生成上下文 | Methodology Engine 将当前阶段的 findings、指标、架构候选、影响实体和推荐任务以有界 `methodology_guidance` 注入五阶段及 23-task LLM 请求，确定性工程检查从事后验收前移为生成约束 |
| 垂直阶段完成质量 | 五阶段结果逐项报告其内部 23-task 检查；关键关系、架构评价、约束传播、可行性权衡和 V&V 交叉分析缺失时标记 `needs_review`，并保留结构化候选供 Review/Controller 继续处理 |

## 历史 Harness 验收边界

| 检查项 | 当前状态 |
|---|---|
| Model connectivity | PASS |
| Native Ollama invocation | PASS |
| Structured MBSE contract | PASS（60/60 provider success；58/60 structural/schema/compile/domain pass） |
| Full 23-task LLM lifecycle | SCRIPTED STRUCTURED ACCEPTED；已用脚本化 StructuredModelRuntime 验证 23 个 TaskSpec→Compiler→Validator→Workflow 调用顺序；真实 Provider 多轮稳定性仍 NOT ACCEPTED |

PR09 的 conformance runner 位于 `tests/contract_conformance/`，默认使用离线 fixture；真实 Ollama 测试必须显式设置 `RFLP_RUN_LIVE_LLM=1`。最终 3 Task × 20 结果为：provider/JSON/schema/compile/domain 均 58/60，2 次 structural retry 未恢复。该结果仅说明结构化边界已有基础覆盖，不能替代新的五阶段产品链验收。

最终 live artifact：`docs/superpowers/artifacts/pr09/contract-conformance-1789049206566817000.json`。五阶段主验收位于 `tests/e2e/test_vertical_model_generation.py`；完整 23-task 主验收位于 `tests/e2e/test_legacy_pipeline.py`、`tests/runtime/test_lifecycle_rule_runtime.py` 和 `tests/application/test_sysml_v2.py`。脚本模型验收不等同于真实 Provider 稳定性。

Methodology Engine v1 的边界是确定性反馈；Systems Engineering Controller v1 已将这些反馈转成有限动作，并允许用户比较候选方案后提交 Trade Study 决策。Review 后可显式继续生成下游：系统从已接受实体的下一层运行到 V&V，锁定实体作为只读锚点，V&V 不创建空的后续运行。当前 Controller 仍不替用户无审查地改写工程事实或选择方案；V&V 已支持外部结果/证据接入和失败反馈，工程工具已有注册式结果端口和内置模型约束分析器，但真实测试执行沙箱、仿真适配和 CAD/真实工程工具连接仍需接入经批准的具体适配器。

## 当前验收命令

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/lint-imports
```

## 明确边界

本版本聚焦可复现的需求到模型垂直链路。旧版智能发现、Concept/MDO、Project Bridge、测试执行沙箱、仿真、旧 Baseline/TaskContract/Job 和 MLflow 已退出 Core；当前 Core 只提供受限的工程工具注册与结果接入端口，复杂文档版面、多人权限、CAD/真实工程仿真仍需后续独立适配器。

Track B 需要显式配置 profile，不能在无密钥 CI 中默认运行：

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py --track llm --profile <profile-id>
```
