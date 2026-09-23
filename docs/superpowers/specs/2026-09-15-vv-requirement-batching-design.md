# V&V Requirement Batching Design

## Goal

让配置的结构化 LLM 在 V&V 阶段处理多需求输入时，按有限的 Requirement 批次生成可执行的 Verification/Validation 计划，再通过现有 ModelGraph 写入边界合并为一份完整、可编辑、可追溯的模型。

## Motivation

当前五阶段产品链把全部 Requirement 放进一次 `vertical.verification_validation` 请求。每条需求至少需要一个 VerificationCase 和一个 ValidationCase，且每个 Case 有九个可执行计划字段；在 8192 context window、2048 output token 的远程模型配置下，五条需求很容易让单次输出被截断。这样会使 R/F/L/P 已经完成，但 V&V 阶段无法闭合，违背“自然语言输入自动形成完整 MBSE 模型”的纵向交付目标。

## Scope and constraints

- 只对配置的 OpenAI-compatible/远程 LLM Runtime 的 `vertical.verification_validation` 启用批处理。
- 每个批次最多包含 2 条正式 Requirement；按 canonical Requirement ID 排序，保证调用顺序稳定。
- 每个批次仍使用原有 `TaskProposal` schema、Proposal Compiler、Validator 和 CAS 写入边界；不引入第二份模型真源。
- 批次输出只允许覆盖该批次的 Requirement 及其已有 RFLP scope；第一批承担跨需求的最小 Hazard/FailureMode 覆盖，后续批次只补本批需求的 V&V。
- 每个批次编译得到的 Patch 在一个结构化 Runtime 响应中合并，最终由既有 `ModelGenerationService` 以一次 CAS Revision 提交；合并前必须去重操作并重新检查原阶段的最大操作数；V&V TaskSpec 未显式设置上限时，遵循现有结构化 schema 的 32-operation contract。
- 三需求结构化离线夹具、离线 RuleRuntime、Requirements/Functional/Logical/Physical 阶段行为保持不变。
- 远程节点不在线时不调用本机模型，也不把离线规则结果当成真实 Provider 验收。

## Design

### Batch selection

`StructuredModelRuntime` 读取垂直请求的 `requirement_worklist`。当任务为 `vertical.verification_validation` 且 worklist 超过 3 条时，切分为连续的 2 条一批；三条及以下维持一次请求，以保持当前小规模路径的调用成本和既有行为。批次请求携带原始 context、evidence、methodology guidance 和一个只包含本批 canonical Requirement ID 的 `requirement_worklist`，并额外携带 `requirement_batch` 元数据（index、count、is_first）。

批次的用户指令明确：只为本批需求产生 V&V Case 和需求更新；不得重复生成其它批次需求的 Case；第一批可以生成一个代表全局异常分支的 Hazard/FailureMode，后续批次不得生成风险对象。这样不会让模型因为完整上下文而重新覆盖所有需求。

### Compile and merge

每批使用独立的 `GenerationRequest` 调用 Provider，并按现有逻辑进行截断检查、一次结构化修复、JSON Schema 校验、TaskProposal 解析和 Proposal Compiler 编译。Compiler 为每批 local_ref 生成 canonical ID，因此不需要在合并阶段重写 payload 内的图引用。

合并规则如下：

1. 按批次顺序合并 `AddEntity`、`Relate`、`UpdateEntity` 和 `Deprecate` 操作。
2. 以完整 operation identity 去重；同一 canonical ID 的重复更新只保留第一次出现的字段，批次之间不应更新同一 Requirement。
3. Hazard/FailureMode 只保留第一批生成的风险对象及其关系；后续批次的重复风险操作被丢弃并记录诊断。
4. 合并后若超过当前 TaskSpec 的 `max_operations`，或 V&V 未设置该策略时超过 32-operation structured-output contract，返回明确的 `batch_operation_limit` 编译失败，不提交部分 Patch。
5. 合并 Patch 的 `expected_revision` 仍是请求开始时的 context revision；ModelGenerationService 继续用一个 CAS Revision 原子写入，失败时沿现有错误路径处理。

响应的 assumptions、open_questions、decision_records 和 diagnostics 按批次顺序合并并去重；`input_hash`、`output_hash` 和 `duration_ms` 反映全部批次，provider/model/finish_reason/usage 保留真实 Provider 元数据，并附加 `batch_count` 与 `batch=i/n` 诊断。

### Completion semantics

阶段完成检查仍在合并 Patch 写入后只执行一次，使用现有逐 Requirement `resolve_vertical_coverage` 和 `evaluate_vertical_stage`。因此只有所有批次都写入并且每条正式 Requirement 的 Verification/Validation scope 都闭合时，阶段才会返回 `completed`；任一批次失败不会留下“部分成功即完成”的状态。

## Error handling

- 任一批次发生 network、结构化、compiler 或 provider context-window 失败，整个 Runtime 响应失败，不返回可提交的部分 Patch。
- 批次编译成功但合并超过操作上限时，返回 `ProposalCompileFailure(code="batch_operation_limit")`，不调用 CAS。
- 某批次返回了其它批次的 V&V 对象时，现有语义/引用校验继续生效；无法证明的跨批关系会使整个响应进入现有 Review/Failure 路径。
- 诊断中记录 batch index/count，便于在 Run/Step/audit 中定位失败批次；不保存凭据。

## Verification

- Adapter 单元测试：五条 Requirement 的 V&V 请求分为 3 批，Provider 调用收到 `[2, 2, 1]` worklist；合并响应只有一份 Patch，操作去重且不超过策略上限。
- Adapter 单元测试：任一批次结构化失败时，不返回部分 Patch；`batch_operation_limit` 不产生 CAS 写入。
- Application 回归：生产 `StructuredModelRuntime`、Compiler、Validator、CAS 路径处理五条需求，生成 10 个 V&V Case，每条需求 `resolve_requirement_trace(...).complete`，阶段和最终结果完成，SysML 往返保留实体/关系，并可继续编辑。
- 全量回归继续运行 pytest、compileall、ruff、architecture metrics、import-linter 和 `git diff --check`。
- 远程验收只在 `autoresearch-5080` 在线时执行一次 CASE-04；节点离线时只报告不可达，不执行本机模型。
