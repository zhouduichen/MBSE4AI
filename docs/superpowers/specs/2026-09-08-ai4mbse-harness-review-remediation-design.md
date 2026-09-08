# AI4MBSE Harness Review Remediation Design

**Status:** For user review
**Baseline:** `cb3c6a7` on `codex/web-audit-2026-08-18`
**Authority:** `AI4MBSE_Harness_项目检查与修改建议_v1.0.docx`
**Product version:** `rflp-lite 0.1.0`
**Methodology protocol:** `v2.0`

## Goal

把当前确定性的 RFLP vertical slice 连接成真正可执行、可追溯、可恢复的 AI4MBSE Harness：Active LLM 按 TaskSpec 逐任务工作，经 Context、Evidence、Schema、Semantic 和 PatchPolicy 约束后写入 ModelGraph，由 Phase Gate、定向 Repair、下一阶段和 Closure 形成完整闭环；无模型配置时继续提供明确的 Offline Rule Mode。

本次用户要求是“按照检查建议全部实施”。文档中的 P0、P1、P2 均纳入范围；文档中“不建议现在做”的 Concept/MDO 扩展、额外实体类型、复杂多 Agent 和更多模型厂商不纳入本次范围。

## Success Criteria

1. 激活的模型 profile 是 Analysis 实际使用的 runtime，并被固化到 Run 和 Step。
2. 一次 `run_pipeline(project_id)` 能按 Operational → Functional → Logical/Physical → Assurance → Closure 推进，Phase Gate 失败时执行有上限的定向 Repair 并重新 Gate。
3. TaskSpec 的 prompt、schema、validators、max_attempts、failure_routes 和 completion_condition 都参与任务执行。
4. 当前任务的 ContextBuilder 能从 ModelGraph 推导 KnowledgeGap，经过有界 Retrieval 获取 Evidence，并把去重后的相关 evidence bundle 传给模型。
5. Gate 从对象存在性检查升级为覆盖矩阵和链路检查，输出结构化 Issue。
6. Repair 重跑最小根因任务，不再直接生成 `missing_xxx` 通用占位符；修复后自动 Re-gate。
7. Patch 在 Domain Validation 之外通过 Task 级 PatchPolicy，限制可写实体、字段、关系谓词和实体范围。
8. Requirement、Scenario、VerificationCase、PhysicalBlock 等关键实体拥有 kind-specific payload 校验。
9. 任意 applied patch 可沿 Run → Step → Patch → Revision 反查模型、输入输出 hash、任务和图前后 hash。
10. 相同图 revision 切换模型或提示词会生成不同 Run，并支持显式 `new_run/force_run`。
11. Closure 只有在 Global Gate 通过后才冻结 accepted revision，并生成 manifest、Gate 快照、导出清单和验收摘要。
12. 最小 wheel 安装不依赖额外安装 `schema` 即可完成 project create；README、Web UI 和交付包与实际行为一致。

## Architecture

### Runtime selection

`V2Services` 不再长期持有一个固定 `self.runtime`。它保存 `RuntimeProvider` 或 `RuntimeFactory`，每次新 Run 在 `AnalysisService`/`LifecycleOrchestrator` 创建时读取 `SettingsService.active_config()`：

- 有 active config：构造 `openai_compatible_runtime(config)`，并使用配置中的 provider、model 和 profile id。
- 无 active config：构造 `RuleRuntime`，Run 和 Analysis 页面明确显示 `Offline Rule Mode`。
- 允许测试注入 `TaskRuntime`，但注入 runtime 的 provider/model 元数据也必须进入 Run/Step ledger。

RuntimeFactory 只负责把配置转换成 TaskRuntime；它不负责 prompt、schema、patch 或 gate。模型调用失败由 TaskExecutor 按 TaskSpec 的重试策略处理，不能静默回退到 RuleRuntime。

### Task execution contract

新增或拆分以下职责：

- `PromptRegistry`：通过 `prompt_template_id` 返回包含方法论目标、输入定义、输出语义、禁止事项和示例的任务提示。
- `SchemaRegistry`：通过 `output_schema_id` 返回外层 operations schema 和每个 EntityKind 的 payload/field_patch schema。
- `ValidatorRegistry`：按 `task.validators` 运行 schema、identity、reference、relation、lifecycle、requirement-quality 和 semantic validators。
- `TaskExecutor`：完成 Context 获取、prompt 编译、runtime 调用、响应解析、校验、PatchPolicy 检查、Patch 应用、completion_condition 判断和 Step 记录。
- `RetryPolicy`：根据 `max_attempts` 区分格式修复、模型重试和最终 degraded/failed 结果。

`WorkflowRunner` 保留为单 Phase 调试入口，但不再直接拼装统一 system prompt 或绕过 TaskSpec。任务成功的定义不是“runtime 返回 completed”，而是满足 `completion_condition` 或明确产生合法的 no-change 结果。

### Context and Retrieval

`ContextBuilder` 先依据 `TaskSpec.context_query` 选择 ModelGraph 邻域，再生成结构化 `KnowledgeGap` 查询。`RetrievalEngine` 按 User Documents > Historical Projects > Local FTS > optional Web 顺序获取候选来源。`EvidenceExtractor`/`EvidenceRanker` 去重并限制数量，只将当前 Task 相关的 `evidence_id`、excerpt 和 locator 放入 `ContextBundle.evidence` 与 `TaskExecutionRequest.evidence_bundle`。

检索停止条件改为连续两轮新增有效证据或实体低于阈值；每个 Task 有明确的最大查询数、最大 evidence 数和 token budget，防止上下文无界增长。保存 Evidence 仍通过现有 EvidenceService/Repository，TaskExecutor 只消费经过筛选的证据。

### Lifecycle orchestration

新增 `LifecycleOrchestrator.run_pipeline(project_id, *, run_id=None, force_run=False)`，执行如下状态机：

```text
Project/Documents
  -> Context + Evidence
  -> Operational tasks -> O-Gate
  -> Functional tasks -> F-Gate
  -> Logical/Physical tasks -> P-Gate
  -> Assurance tasks -> Global-Gate
  -> ClosureService
```

每个 Phase 的 Gate 通过后才进入下一 Phase。Gate 失败时，将结构化 Issue 交给 `RepairRouter`：按 `root_cause` 找到最早的最小根因 Task，补充检索/证据，局部重跑并重新 Gate。自动 Repair 有最大轮数；超过上限时 Run 进入 `degraded` 或 `needs_review` 语义并保留人工处理入口。单 Phase `run()`、`resume()` 和显式 `repair()` 继续支持诊断和局部操作。

### Gate and Repair

Gate 统一输出：`gate_id`、`passed`、Issue 列表和 rollback phase。每个 Issue 至少包含 `code`、`severity`、`root_cause`、`entity_ids`、`suggested_task`、`rollback_phase` 和 `evidence_gap`。

- Operational Gate：检查 Stakeholder × Concern、Stakeholder × Lifecycle、Lifecycle × Scenario Type，以及 UseCase → Scenario → Activity → System Requirement 覆盖链。
- Functional Gate：每个 accepted system requirement 至少有 Function 覆盖，并检查 Function 分解、输入输出和交互。
- P-Gate：每个 accepted requirement 必须有 Requirement → Function → Logical → Physical 路径；Physical 候选必须带 trade-off 依据。
- Global Gate：可验证 Requirement 必须有 VerificationCase，UseCase/OperationalScenario 必须有 ValidationCase，Hazard 必须有 Mitigation 和 Verification 链。

`RepairRouter` 不直接按 Issue 创建 `missing_xxx` 实体。它选择最早根因 Task，补证据后调用 TaskExecutor，只允许局部 Patch，自动应用后立即 Re-gate，并把旧 Issue 标记为 resolved 或 superseded。

### Patch policy and typed payloads

每个 TaskSpec 增加或派生 `PatchPolicy`：

- `writable_kinds`
- `writable_fields`
- `allowed_predicates`
- `allowed_entity_scope`

`patch_from_response()` 负责解析和基础契约检查；`TaskExecutor`/ModelService 在 apply 前同时执行 Task Policy Validation 和 Domain Validation。UPDATE/DEPRECATE 必须确认目标实体在允许范围内；RELATE 必须同时验证 predicate 和 source/target scope。

为关键 EntityKind 建立正式 payload codec/schema，优先覆盖 Requirement、Scenario/OperationalScenario、VerificationCase/ValidationCase 和 PhysicalBlock。ADD.payload 与 UPDATE.field_patch 使用 kind-specific schema 校验，禁止只靠 `{"type":"object"}` 放行语义缺失字段。

### Audit, reproducibility and revision semantics

RunIdentity 至少包括 project、phase、graph revision、methodology version、task spec version、prompt version、model profile 和 context/input hash；需要时用 `force_run/new_run` 生成新的实验 Run。相同图 revision 但不同模型/提示词不得复用已完成 Run。

Run、Step、Patch、Revision 之间建立完整元数据链：

- Run：methodology/task spec/prompt version、model profile、provider、model、input/context hash、graph before hash、status、lease/heartbeat/retry。
- Step：task id、attempt、provider/model、input/output hash、duration、repaired、graph before/after hash、patch id、diagnostics。
- Patch/Revision：run id、task execution metadata、graph before/after hash。

`apply_patch()` 统一使用 `next_revision = graph.revision + 1`：新增实体的 `created_revision`、更新/弃用实体的 `updated_revision` 都以实际产生的新 revision 为准。任何 CAS 失败都不能留下半写入的审计记录。

RunPort 实现本地单进程仍可用的 claim、heartbeat、interrupt、retry 语义；lease 过期、主动中断和可重试错误必须能恢复到可继续的 Run 状态，不重复应用已经成功的 Patch。

### Closure

`ClosureService` 的前置条件是 Global Gate 通过。它冻结 accepted revision，生成 `manifest.json` 和 Gate 快照，记录 graph hash、methodology、profile、provider/model 和输入输出摘要，写入 closure revision，并生成可选 JSON、SysML、SVG 或 trace matrix 导出清单。Closure 失败必须保留明确诊断，不能仅创建一个 completed Run。

### Web workflow

Analysis 页作为全生命周期工作台，显示：Project、Current Revision、Active Model、Run Status、Global Gate；Operational → Functional → Logical/Physical → Assurance → Closure 的状态轴；当前 Task 的输入上下文、Evidence 数量、模型、attempt、Patch 和 Validation；Gate 覆盖矩阵与 Issue；Repair 的 root cause、rollback task、自动修复轮次和人工动作。

Model 页提供 Requirement → Function → Logical → Physical → Verification 的点击式 trace。Settings 页提供连接测试和“本次分析实际使用的 provider/model”状态。JSON 端点保留为调试入口，不能替代主工作流界面。无模型配置时页面明确显示 Offline Rule Mode。

### Delivery and documentation consistency

- `jsonschema>=4.23` 放入基础 dependencies；README 的 editable、wheel 和 offline 安装路径一致。
- 明确产品版本 `0.1.0` 与方法论协议 `v2.0` 的关系。
- 为 `docs/superpowers` 建立 current/superseded/archived 索引；历史计划和设计保留但不再作为当前架构依据。
- 不参与当前 v2 路由的旧模板和 `.impeccable/review` 截图归档或标注。
- localhost 单用户边界保持不变；若未来监听非 127.0.0.1，必须在新增范围中先补鉴权、CSRF 和文件路径安全。

## Data Flow

```text
Active Profile
    -> RuntimeFactory
    -> LifecycleOrchestrator
    -> TaskSpec
    -> ContextBuilder -> KnowledgeGap -> RetrievalEngine -> EvidenceBundle
    -> PromptRegistry + SchemaRegistry
    -> TaskRuntime
    -> ValidatorRegistry + PatchPolicy + Domain Validation
    -> Patch/CAS -> ModelGraph Revision
    -> Step Ledger and Run Audit
    -> Phase Gate
       PASS -> next Phase
       FAIL -> Issue -> RepairRouter -> targeted Task -> Re-Gate
    -> Global Gate -> ClosureService -> manifest/export/snapshot
```

## Error Handling

- 配置错误、输出格式错误、schema 错误和 Task Policy 越权都作为结构化 Step diagnostics 记录；按 `max_attempts` 重试后进入 degraded/failed，不静默成功。
- 模型不可用时保留错误来源和 attempt；只有启动时没有 active profile 才允许使用 RuleRuntime fallback。
- Retrieval 无结果时记录 evidence gap，允许 Task 产生候选或 no-change，但 Gate/CompletionCondition 决定是否可继续。
- Gate 失败必须持久化 Issue；Repair 失败不删除原 Issue，不覆盖原 revision。
- CAS 冲突重新加载最新图并按 Run 状态决定 resume 或人工审阅，禁止强制覆盖并发修改。
- Closure 前任一 Gate 未通过都不能冻结 accepted revision。
- 已有旧 SQLite 数据库继续通过兼容迁移打开；迁移失败返回可读错误并保留原数据库。

## Testing and Acceptance

实现采用测试先行，每个 PR 完成后运行对应单元/集成测试，并在最终阶段执行全量测试、compileall、Ruff、import-linter、架构预算和 wheel smoke。

必须覆盖以下验收场景：

- 激活 Fake LLM 后 Analysis 确实调用它，不调用 RuleRuntime。
- 单次 pipeline 完成四个 Phase、Gate 和 Closure。
- 删除 lifecycle/verification 后，Gate 能定位根因、触发定向 Repair、重跑并 Re-gate。
- 文档中的唯一事实出现在 TaskExecutionRequest.evidence_bundle。
- stakeholder_analysis 不能 UPDATE/DEPRECATE PhysicalBlock。
- 不完整 Requirement payload 在 Patch 前被拒绝。
- applied Patch 可完整反查 run/task/provider/model/input/output hash。
- 切换 model profile 或 prompt version 产生独立 Run。
- 新增、更新、弃用实体的 revision metadata 与实际图 revision 一致。
- 最小 wheel 安装后可直接 project create 和基础 analyze。
- Run claim/heartbeat/interrupt/retry 不重复应用已成功 Patch。
- Web 页面能展示 Phase 状态、Evidence、Gate Issue、Repair 和实际模型来源；静态资源在 wheel 安装后仍可加载。

## Implementation Boundaries

保留现有 domain、repository、ModelGraph、Patch/CAS、文档解析、Runtime Adapter、TaskSpec 名称和测试体系。新增能力通过 application/methodology 组合层接入，避免把 Web 逻辑下沉到 domain，也避免让 Adapter 直接依赖 application。现有单 Phase API 和 RuleRuntime 用于兼容、离线和调试；全生命周期入口是产品主路径。
