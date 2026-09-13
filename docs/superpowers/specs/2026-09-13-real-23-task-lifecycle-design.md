# 真实 23-task 端到端生命周期设计

## 目标

把现有 23-task `WorkflowRunner` 从“fixture/兼容入口”提升为真实产品能力：用户输入自然语言或文档后，系统依次执行 23 个方法论任务，每个任务都基于当前 ModelGraph 上下文产生有意义的实体、关系或可审查更新，最终形成完整的

```text
Operational → Requirement → Functional → Logical/Physical → Assurance
```

并提供可验证的 Requirement→Function→Logical→Physical→Verification/Validation 追溯、SysML 往返和可编辑结果。

本设计是完整 AI4MBSE 目标中的下一项纵向子项目，不宣称一次完成所有后续仿真、真实工程工具执行或论文 benchmark 能力。

## 当前证据与问题

默认五阶段 `ModelGenerationService` 已能从自然语言生成可编辑 ModelGraph；但旧生命周期仍由 `WorkflowRunner` 按 23 个 TaskSpec 调度，`RuleRuntime` 对多数任务只生成通用候选或 no-op。一次单需求离线运行虽然返回 `completed`，但 phase 仍出现 `degraded`，结果缺少 State 和 FailureMode，说明“任务台账完成”不等于“方法论对象和关系完成”。

此外，Web `mode=pipeline` 目前只接受已有图或文档输入，不能像默认五阶段入口一样直接消费 `requirement_text`。因此真实 23-task 验收必须同时覆盖输入接入和任务语义，而不是把五阶段结果重新标记成 23 个任务。

## 设计原则

1. `Typed ModelGraph` 仍是唯一真源；SysML、报告和页面都是投影。
2. 保留现有 `WorkflowRunner`、`TaskSpec`、`TaskExecutor`、`StructuredModelRuntime`、PatchPolicy、CAS、Run/Step/Patch/Issue 台账，不新建第二套持久化或失败状态机。
3. 23 个任务必须真实执行。每个任务至少满足下列一项：新增该任务负责的实体、建立该任务负责的类型化关系、或对既有实体执行可审查的字段更新；纯 no-op 只允许在重复运行且目标已经存在时出现。
4. 离线 Runtime 只使用输入和当前图中已有事实；无法证明的工程数值保留为空并生成 open question，不伪造测量或可行性。
5. 配置 LLM 时，每个 TaskSpec 仍单独经过结构化输出、编译、验证和 CAS；新增逻辑只改善输入和离线语义，不绕过 LLM 边界。
6. 用户只看到 Project、Documents、Model、Traceability、Review/Issues 和生成动作；23-task、Patch 和 CAS 继续隐藏在 Web/API 实现中。

## 方案选择

### 方案 A：只把五阶段结果映射为 23-task 台账

实现成本最低，但任务并未真正执行，无法证明任务级上下文、关系和方法论推理，拒绝。

### 方案 B：继续依赖 Golden fixture 作为 23-task 输入

可以维持旧 benchmark，但不能证明自然语言/文档驱动的产品闭环，且会继续掩盖缺失的 F/L/P 语义，拒绝。

### 方案 C：保留 WorkflowRunner，补齐任务语义 Runtime 和真实输入入口

推荐方案。它直接复用现有编排、结构化 LLM 和审计边界，只增加一个按任务分派的离线语义层和一个公共输入适配点。这样离线运行可以先得到可重复的完整链，配置 LLM 时仍能逐任务替换为模型输出，并且两条路径共享同一套 ModelGraph、Gate、Trace 和交付投影。

## 架构

```text
User text / Document / Existing SysML
                 │
                 ▼
        RequirementInputService
                 │
                 ▼
             ModelGraph
                 │
                 ▼
        WorkflowRunner (23 tasks)
                 │
     ┌───────────┴───────────┐
     ▼                       ▼
LifecycleTaskRuleRuntime  StructuredModelRuntime
     │                       │
     └───────────┬───────────┘
                 ▼
       TaskExecutionResponse
                 │
      Validator → Patch → CAS
                 │
                 ▼
             ModelGraph
                 │
        Gate / Trace / V&V
                 │
        SysML / Reports / UI
```

### 输入适配

新增应用层 `RequirementInputService`，提供：

```python
ensure_text_requirements(project_id: str, text: str) -> tuple[str, ...]
ensure_document_requirements(project_id: str, document_ids: tuple[str, ...]) -> tuple[str, ...]
```

它复用现有 `split_requirement_statements` 和 `extract_requirement_constraints`，以稳定的 `statement` 去重，保留用户来源和文档 `document_region` source id。已有 Requirement、已有 SysML 实体或已有文档不会因重复调用被复制。

`POST /projects/{id}/analysis` 的 `mode=pipeline` 在运行前调用该服务；`mode=generate` 继续使用现有 `ModelGenerationService`，两个入口共享输入语义但不共享运行台账。CLI 的 `analyze run` 增加可选文本/输入文件入口，仍调用同一应用服务。

### 任务语义 Runtime

新增 `runtime/lifecycle_rule.py`，由小型 `LifecycleTaskRuleRuntime` 负责 23 个任务的确定性离线操作。`RuleRuntime` 只做兼容分派：`vertical.*` 继续交给 `VerticalRuleRuntime`，23-task ID 交给新的生命周期 Runtime，其他历史任务保留现有行为。

生命周期 Runtime 使用一个局部 `TaskGraphBuilder`：

- `find(kind, name)`：在上下文和本次响应中按类型/名称查找，支持幂等重跑；
- `add(kind, name, payload)`：新增 `Producer.RULE` 的 `VALIDATED` 实体；
- `relate(source, predicate, target)`：按 `(source, predicate, target)` 去重；
- `update(entity, payload)`：只更新未锁定且未 `user_modified` 的既有实体；
- `response()`：无新增操作时仅在目标已经存在的重复执行中返回 `offline:lifecycle-idempotent`。

该 Builder 不直接写仓库，所有结果仍由 `WorkflowRunner` 的验证和 `append_patch` 提交。

## 23 个任务的语义契约

| 顺序 | TaskSpec | 最小真实产物 |
|---:|---|---|
| 1 | `system_definition` | 一个具有 mission、boundary、objectives 的 System；已有 System 只补缺失字段 |
| 2 | `stakeholder_analysis` | Stakeholder、Concern，以及 Stakeholder→Concern `HAS_CONCERN` |
| 3 | `stakeholder_requirements` | stakeholder/concern 派生的 Requirement 与 `DERIVED_FROM` |
| 4 | `lifecycle_analysis` | LifecycleStage；多个阶段之间可建立有序 transition payload/关系 |
| 5 | `scenario_exploration` | ScenarioHypothesis，带 actor、trigger、outcome 和来源关系 |
| 6 | `use_case_analysis` | UseCase，连接 ScenarioHypothesis 与 Stakeholder |
| 7 | `operational_scenario` | OperationalScenario，连接 UseCase、参与者和步骤 |
| 8 | `activity_analysis` | Activity，连接 OperationalScenario 和 LifecycleStage |
| 9 | `system_requirement_derivation` | 可验证系统 Requirement，连接 Activity/Scenario，并保留约束 provenance |
| 10 | `function_identification` | 每个活跃系统需求至少一个 Function，并建立 Requirement→Function `SATISFIED_BY` |
| 11 | `functional_decomposition` | Function 的 decomposition metadata；必要时新增子 Function 和 `DECOMPOSES` |
| 12 | `functional_interaction` | FunctionalFlow 以及 Function→Flow `EXCHANGES_WITH` |
| 13 | `functional_scenario` | FunctionalScenario，连接 Function 和执行步骤 |
| 14 | `functional_requirement` | 功能 Requirement 或现有 Requirement 的功能属性更新，并保留来源 |
| 15 | `logical_analysis` | LogicalComponent，并将 Function 通过 `ALLOCATED_TO` 分配 |
| 16 | `physical_candidates` | PhysicalBlock，连接 LogicalComponent 并复制明确约束 |
| 17 | `allocation_tradeoff` | 至少一个物理候选选择/替代记录；不填充虚假 SWaP-C |
| 18 | `technical_requirement` | 显式约束对应的 technical Requirement，连接来源需求和 PhysicalBlock |
| 19 | `interface_sequence_state` | Interface、State，并用 `CONNECTED_TO`/`DECOMPOSES` 表达结构 |
| 20 | `fmea_stpa_hazard` | Hazard、FailureMode、`CAUSES` 和 `MITIGATED_BY` |
| 21 | `verification_validation` | 每个 Requirement 独立 VerificationCase、ValidationCase 及对应关系 |
| 22 | `reverse_feasibility` | 对物理冲突/待测量问题形成可追溯的反向 Requirement 或 Issue 线索 |
| 23 | `global_cross_analysis` | 补齐缺失跨阶段关系并返回全链 Gate/Trace 检查结果 |

技术需求沿用已完成的 `level=technical` 约定；反向需求不覆盖来源需求，也不把未证实的方案结论写成事实。

## 任务完成与 Gate 语义

旧 TaskSpec 中大量 `minimum_entities=0` 的配置会让“有步骤记录”看起来像“有模型产物”。本子项目为 23-task 增加任务级完成检查：

- 实体型任务要求响应 Patch 或当前图中存在负责类型；
- 关系型任务要求目标谓词和端点类型存在；
- 更新型任务要求字段变化可被审计；
- `functional_gate`、`rflp_gate` 和 `global_gate` 继续以实际图关系计算，不信任 payload 中的 ID 列表；
- 完整生命周期只有当每个阶段 Gate 通过、完整 Requirement 具备 RFLP/V&V 关系且 Closure 写入成功时，才返回 `completed`；否则返回准确的 `degraded`/`blocked`，不能因 Closure 成功掩盖 phase degraded。

重复运行必须不新增相同名称/相同关系；强制新 Run 可以留下新的 Run/Step 记录，但 ModelGraph 不应出现重复语义对象。

## LLM 路径

配置 Profile 后，`WorkflowRunner` 继续为每个 TaskSpec 建 ContextBundle、Prompt 和 output contract，并调用现有 `StructuredModelRuntime`。新的离线语义 Runtime 不改变 LLM schema；测试用一个按 task id 返回最小合法 Proposal 的脚本模型验证 23 次真实调用、TaskSpec 顺序、关系编译和最终图。真实 Provider 的稳定性不作为本子项目的主要门槛；只记录一次可复现的调用证据，避免再次提前进入大规模重复实验。

## 错误与审查

- 空文本、没有可读文档和空 ModelGraph：在输入层返回 `InputRequired`，不启动 23-task Run。
- 结构、引用、PatchPolicy、编译或 CAS 错误：沿现有 fail-closed 路径记录 Step/Issue，并阻断后续任务。
- 语义缺口、未测量物理值和架构权衡：保留候选/Issue/open question，允许后续 Review 或 Controller 继续推进，但不提升为已验证事实。
- 已锁定或用户修改的实体：只能作为上下文锚点，不能被生命周期 Runtime 覆盖。

## 验收

必须有一次不依赖预置实体图的离线自然语言运行，证明：

1. `mode=pipeline` 和 CLI 入口都能从文本建立输入 Requirement；文档输入能复用 `document_region` Evidence。
2. 23 个 TaskSpec 都有实际 Step 记录，且每个任务至少产生实体、关系或更新；没有用五阶段结果伪造任务记录。
3. 结果包含 System、Stakeholder、Lifecycle、Scenario、UseCase、Activity、Requirement、Function、FunctionalFlow、FunctionalScenario、LogicalComponent、Interface、State、PhysicalBlock、Hazard、FailureMode、VerificationCase、ValidationCase。
4. 至少一条 Requirement 形成真实 Requirement→Function→Logical→Physical→Verification/Validation 路径；显式工程约束形成 Technical Requirement 并拥有独立 V&V。
5. 阶段状态、Gate、Traceability 和 Closure 一致；不得出现“总体 completed 但 phase degraded”的成功伪装。
6. 导出 SysML 后重新导入，实体 ID、类型、关键 payload 和关系保持一致；导入图可继续编辑。
7. 配置脚本模型后，23 个 TaskSpec 逐任务经过 Structured Runtime，结果可编译、可写入、可回读。
8. 现有五阶段生成、Controller、SysML、交付包和旧 fixture/兼容测试保持通过。

## 不在本次范围

- 不删除或重写旧 23-task API；
- 不新增数据库表、Provider、状态机或外部仿真执行器；
- 不把一次脚本模型测试包装成真实 Provider 稳定性结论；
- 不声称已完成多轮自主 Trade Study、真实 CAD/仿真或论文级 benchmark。
