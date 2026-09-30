# Methodology Engine v1 设计

## 目标

把当前五阶段纵向生成从“LLM 返回结构化实体”推进为“ModelGraph 驱动的系统工程推理”。第一版 Methodology Engine 不替换现有 LLM Runtime，而是在每次生成或 Review 重新分析时，对当前图执行确定性的工程分析，输出可追踪的 findings、metrics、decision records、影响实体和下一步任务。

## 产品边界

用户仍然只面对 Project、Requirements、Functional Model、Logical Architecture、Physical Architecture、V&V、Traceability 和 Review/Issues。`TaskSpec`、Patch、CAS 和 23-task catalog 继续作为 Harness 内部实现。

第一版覆盖四类可观察能力：

1. Logical：从 Function、FunctionalFlow、Interface 和 LogicalComponent 构建依赖/分区视图，计算分配覆盖、孤立功能、跨组件交互、内聚/耦合信号，并给出候选分区与架构决策依据。
2. Physical：从 Requirement 约束和 PhysicalBlock payload 提取质量、功耗、算力、内存、时延、带宽、成本、热、可靠性和可用性字段；区分满足、冲突和待测量，不把未知值当作通过。
3. V&V：检查每个 Requirement 的 VerificationCase 和 ValidationCase，检查 method、precondition、input、procedure、expected_result、pass_criteria、evidence 和 Activity 分支覆盖；Verification 与 Validation 永远分开报告。
4. Impact：从被修改实体沿 ModelGraph 的关系做有界双向影响遍历，返回受影响实体、受影响阶段、根因路径和建议的内部 task IDs，供 Review 重新分析使用。

## 方案

新增 `rflp_lite.methodology.engine` 作为纯 ModelGraph 分析边界。它不写仓库、不调用 LLM、不创建 Patch，只消费图和可选的 changed entity IDs，返回不可变报告：

```python
MethodologyEngine.analyze(
    graph: ModelGraph,
    *,
    changed_entity_ids: Sequence[str] = (),
) -> MethodologyReport
```

报告包含：

```python
MethodologyReport(
    findings: tuple[MethodologyFinding, ...],
    metrics: Mapping[str, object],
    decisions: tuple[Mapping[str, object], ...],
    impacted_entity_ids: tuple[str, ...],
    impacted_stages: tuple[str, ...],
    recommended_tasks: tuple[str, ...],
)
```

每个 finding 包含稳定的 `code`、`severity`、`stage`、`entity_ids`、中文 `message` 和 `recommended_actions`。所有实体引用使用 canonical ID；报告只做分析，不提升实体状态。

`ModelGenerationService` 在五阶段完成后调用引擎，把 `methodology` 放进 `GenerateModelResult.as_dict()`，并记录 `model_generation.methodology_analyzed` audit event。生成仍以端到端追溯作为主状态，但当分析发现未知物理约束、结构化 V&V 缺口或架构孤立项时，结果带有 warning 和可见的 review findings。

`ReviewService.request_reanalysis` 调用同一个引擎，不再只根据实体 kind 静态选择 task；它将影响分析中的 `recommended_tasks`、路径和阶段写入请求 audit。`ModelGenerationService.reanalyze` 是显式执行入口，按修改实体类型从受影响阶段向下重跑并复用 CAS/Run/Patch 审计；“创建请求”和“执行生成”仍是两个动作，避免 Review API 意外触发长时间 LLM 调用。

Web 分析页显示四个精简区域：Methodology Findings、Architecture/Physical Metrics、V&V Coverage 和 Impact / Next Tasks。详细实体和原始诊断继续由现有资源页提供。

## 决策与限制

- 逻辑分区第一版使用图连通性、功能分配和 payload 中的 dependency/shared state/timing/safety 字段做信号分析；不声称替代完整优化器。
- 物理约束只接受已有 Requirement/PhysicalBlock payload 中的结构化数值或明确状态。无法提取的数值进入 `needs_measurement`，不会变成 feasible。
- 影响分析最多遍历 4 跳，按 canonical ID 排序，避免循环图或大型历史图导致不可控运行时间。
- 不新增第三方依赖，不把 SysML 作为内部真源，不删除 23-task catalog。
- 现有 `TraceabilitySummary` 兼容字段继续保留；MethodologyReport 作为新报告独立演进。

## 验收标准

- 一个包含 Function → LogicalComponent → PhysicalBlock 的图可以得到逻辑分区和物理可行性报告，而不是只有字符串 decision record。
- 质量/功耗等约束与物理值冲突时得到确定的 `physical_constraint_conflict` finding，未知值时得到 `physical_measurement_required`，两者都不误报为通过。
- Verification 或 Validation 单独存在时，报告分别计数且端到端 coverage 仍为 0；结构化 V&V 缺字段时生成 finding。
- 编辑 Requirement 或 Function 后，影响分析返回上游/下游相关实体、受影响阶段和至少一个具体内部任务。
- 生成 API、Review 重新分析 API 和分析页可读取同一份报告。
- 全量测试、Ruff、compileall、架构预算和 import-linter 通过。
