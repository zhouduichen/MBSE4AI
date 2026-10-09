# R 阶段窄批次闭合与 R→F→L→P→V&V 纵向推进设计

## 状态

提案已获用户批准，等待规格审阅后实施。

## 背景与问题证据

最新真实远端 Provider 验收提交为 `44435fc`。远端
`qwen3.5-controller` 已保持在线并返回多次 `200 OK`，但
`vertical.requirements` 仍把 Operational Analysis、行为对象、需求字段和
追溯关系放进一次大 JSON。该响应在 `finish_reason=length` 时被截断，结构化
修复也失败，最终只有 `24 entities / 61 relations`，Functional、Logical、
Physical、V&V 没有启动。

当前 F/L/P/V&V 已有按 Requirement 分批和确定性合并能力；问题集中在 R 阶段
仍然是单个宽请求。继续提高远端 token 上限只能延后同一问题，也不能保证
Use Case、Activity 和 Requirement 追溯关系不会被同一个长响应截断。

## 目标与验收标准

### 目标

把 R 阶段改为可验证的窄批次闭合流程：先生成共享 Operational/Behavior
骨架，再逐个闭合已有 Requirement 的字段和关系；所有批次在内存中编译、合并
和校验，最终仍只经过一次 CAS 写入，然后按现有顺序进入 F→L→P→V&V。

### 验收标准

1. 在不启用 `vertical_completion_bridge`、不启动本地模型的情况下，R 阶段不再
   依赖一个包含全部实体和关系的宽 JSON。
2. 每个 R 子请求都有明确的 `slice_kind`、目标实体/Requirement 范围和
   `context_hash`；响应经过既有 TaskProposal Schema、Compiler 和语义校验。
3. 共享 System、Stakeholder、Concern、Lifecycle、Scenario、Use Case、
   Operational Scenario、Activity 只由骨架批次创建；Requirement 闭合批次只
   更新已有 Requirement 并补关系，不重复创建共享实体。
4. Requirement→Use Case、Requirement→Activity 和 Use Case→Activity 的
   关系能在最终 ModelGraph 中以 canonical ID 表达；Activity 保留 normal、
   failure、alternative、boundary、exception 五类分支。
5. 所有 R 批次成功后，F、L、P、V&V 按既有依赖顺序启动；任意 R 批次失败时
   不产生部分 CAS 写入，也不把下游 queued 误报为完成。
6. 一次真实远端 CASE-04 能在执行证据中显示五个 vertical stage 的状态、
   Provider/model、批次数、合并哈希和最终追溯结果。该验收不要求此切片同时
   解决三次回归稳定性或 23-task 生命周期稳定性。

## 非目标

- 不引入 completion bridge，也不把离线规则运行时当作 Provider 成功。
- 不改变 ModelGraph、SysML v2 子集或现有 CAS 语义。
- 不在本切片中增加新的 UI、审计页面、Benchmark 维度或 Provider 重试策略。
- 不通过无限续写或截断 JSON 拼接来假装结构化响应完整。

## 设计

### 1. R 阶段切片计划

`StructuredModelRuntime` 为 `vertical.requirements` 建立显式的 R 切片计划，
但沿用现有 `TaskExecutionRequest`、TaskProposal、Compiler 和最终 Patch 接口。
切片计划只存在于运行时 payload 和审计中，不成为用户领域实体。

#### 1.1 Operational/Behavior 骨架批次

骨架批次携带压缩后的输入需求索引（canonical Requirement ID、短 statement、
缺口摘要）和当前图上下文，但不要求生成 Requirement 实体。它只允许生成
当前缺失的共享 R 类型：

- System、Stakeholder、Concern；
- LifecycleStage、LifecycleTransition；
- ScenarioHypothesis、UseCase、OperationalScenario、Activity。

若当前上下文已经有某种类型，Schema 将该类型从 `entities` 中排除，模型只能
通过关系或最小更新补缺。骨架批次有两个确定性行为组：基础运营组和行为组；
行为组必须为 Activity 提供五类分支。每组输出保持在 profile 的垂直批次预算
内；组仍过宽时，按缺失 kind 再拆成单 kind 子批次，不进行开放式重试。

#### 1.2 Requirement 闭合批次

骨架 Patch 在内存中编译后，运行时为每个已有 canonical Requirement 建立一
个闭合批次。每个批次只接收一个 Requirement 的 `requirement_id`、当前缺口
和骨架生成的 canonical ID，允许：

- 用 `updates` 补齐 statement、obligation、level、type、verification_method、
  derived_by、rationale 等字段；
- 用 `derivedFrom` 将 Requirement 连接到 Concern、Use Case 和 Activity；
- 用 `decomposes` 将 Use Case 连接到 Activity；
- 写入该 Requirement 所需的最小 assumptions/open_questions。

闭合批次不允许新增共享 R 实体，不允许触碰其它 Requirement。没有现有
Requirement worklist 时，运行时保留现有单请求兼容路径并记录
`r_slice:no_requirement_worklist`；真实产品入口必须先由 1.1 需求摄取产生
Requirement，不能用该兼容路径宣称 R 阶段完成。

### 2. 合并与写入边界

骨架批次按顺序执行，以便后续行为实体可引用已经编译出的 canonical ID。
Requirement 闭合批次在骨架完成后可按 `max_parallel_requests` 并行执行；其
输入互不重叠，输出在合并前仍需逐批通过 Compiler 和端点校验。

运行时维护一个只存在于本次执行的 working context：

1. 将骨架 Proposal 编译为临时 Patch，并把新增实体/关系投影到 working
   context；不写 Repository、不增加 revision。
2. 用 working context 构造每个 Requirement 闭合请求，禁止闭合请求引用
   不在该上下文中的 ID。
3. 按稳定的计划顺序合并所有 Patch，使用现有 operation key 去重关系和实体，
   对冲突的同一字段保留确定性错误而不是静默覆盖。
4. 对合并结果执行一次完整的 patch policy、semantic validator、stage gate 和
   traceability 校验，全部通过后才进入既有 CAS 写入。

任一切片发生 transport、截断、Schema、Compiler 或语义失败时，整个 R 阶段
不写入部分结果；audit/run ledger 记录失败切片和下游 queued 状态。该失败
状态必须保持真实，不能调用离线桥接器补齐后标记为 Provider 成功。

### 3. 关系契约对齐

现有 vertical R stage contract 已声明 `decomposes`，但 R prompt 的附加指导
仍写着“不要使用 decomposes”，同时又要求 Use Case→Activity。实现时统一为：

- `hasConcern`：System/Stakeholder → Concern；
- `participatesIn`：Stakeholder → OperationalScenario；
- `occursIn`：Activity/OperationalScenario → LifecycleStage；
- `derivedFrom`：Requirement → Concern/UseCase/Activity，以及 OperationalScenario
  → UseCase；
- `decomposes`：UseCase → Activity。

Schema、prompt、semantic validator 和测试必须使用同一组方向；不能只放自由
文本或 payload 数组而不落 canonical relation。

### 4. 提示词与上下文控制

每个 R 请求都追加短的 slice-specific 指令，而不是重复整份全局 Schema：

- 标明 `slice_kind`、`slice_index/count`、允许的 entity kinds 和唯一目标；
- 骨架批次只描述共享 R 对象和行为框架；
- 闭合批次只描述一个 Requirement 的缺口和可引用 ID；
- 复用已有 canonical ID，禁止跨批次复制实体；
- 短字段、短 procedure、短分支文本优先，事实不足写入 open_questions。

Provider 的 `json_schema/json_object` 选择保持现状；本切片不通过关闭结构化
约束来换取“看起来完整”的文本。

### 5. 可观测性

在 execution/audit/run ledger 中为每个 R slice 保存：

- `slice_kind`、index/count、目标 Requirement IDs；
- input/context/schema/output hash；
- provider/model、finish_reason、usage；
- compiled operation count、working-context revision（不等于 Repository revision）；
- merged patch hash 和最终 CAS revision。

报告增加 R slice 数量、失败切片和合并状态，但不改变现有总分定义。

## 测试与验收计划

### 单元与集成测试

- R 切片计划：验证基础运营组、行为组和单 Requirement 闭合组的确定性拆分。
- Context projection：验证骨架临时实体能被闭合批次引用，但未写入 Repository。
- Merge：验证重复共享实体、重复关系、跨 Requirement 越权更新和字段冲突均被
  拒绝或确定性去重。
- Contract：验证 `decomposes` 方向和 Requirement→Use Case/Activity 关系通过，
  其它非法端点失败。
- Failure boundary：模拟任一 slice 截断，确认 CAS revision 不变、下游不启动、
  audit 记录失败 slice。
- Regression：保留现有离线 R→F→L→P→V&V、行为图、SysML 和 FreeCAD 测试。

### 真实 Provider 验收

使用已有 SSH 转发远端 vLLM，禁止本机启动模型：

1. `vertical_completion_bridge=false`；
2. CASE-04，单次运行；
3. 检查 R slices 全部完成，随后 F/L/P/V&V 均有 Provider execution step；
4. 检查 ModelGraph 的 R→F→L→P→V&V 追溯、Activity 五类分支、SysML 导出和
   audit/run ledger；
5. 失败时保留原始证据，不用 bridge 重跑冒充纯 Provider 成功。

## 风险与取舍

- 请求数量会增加，单卡远端总耗时可能上升；这是用可合并的短请求换取完整
  纵向链的明确取舍，`max_parallel_requests` 只用于 Requirement 闭合批次。
- Provider 可能在不同批次给出不同名称；canonical ID 只由骨架批次创建，闭合
  批次不能新增共享实体，降低名称漂移对图的影响。
- 如果远端输出仍截断，失败会更早、更可定位地落在一个 slice；这比当前整段
  R JSON 被截断后无法判断缺口更适合继续迭代。

