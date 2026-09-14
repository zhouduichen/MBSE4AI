# 完整生命周期结果投影设计

**状态：** 已确认设计，待实现
**日期：** 2026-09-14

## 目标

让默认的完整 23-task 生命周期成为真正的产品闭环：一次分析结束后，API、Web 工作台和交付物都从同一份 ModelGraph revision 读取并展示：

```text
自然语言 / 文档
    → 23-task WorkflowRunner
    → Typed ModelGraph
    → Traceability + Methodology + Controller
    → Web 工作台 / API / 交付包
```

本设计不新增 LLM 调用，不改变 ModelGraph、Patch、CAS、锁定实体或五阶段兼容入口的语义。

## 当前缺口

`WorkflowRunner` 已能逐任务执行完整生命周期并将结果写入 ModelGraph，但 `AnalysisService.run_pipeline()` 只返回运行摘要。`POST /projects/{id}/analysis` 的 pipeline 响应因此缺少逐需求追溯、Methodology Engine findings/metrics/decisions 和 Controller actions；页面刷新后也只能看到阶段状态和任务台账，不能直接看到架构候选、物理可行性、冲突和下一步工程动作。

这使“生成完整 MBSE 模型”虽然已经生成了图，却没有把模型推理结果交付给用户。

## 方案与选择

### 方案 A：在 Resource API 中直接拼装

API 在 pipeline 返回后直接读取 ModelGraph，调用 `MethodologyEngine`、`SystemsEngineeringController` 和追溯函数。

优点是改动少；缺点是 API 变成业务编排入口，Web 页面刷新还要重新复制同一段逻辑，容易形成两个结果语义。

### 方案 B：应用层 Pipeline Report（推荐）

增加只读的应用层 `PipelineReportService`，负责从指定项目的当前 ModelGraph 构造统一结果：

```text
PipelineReport
├── revision
├── snapshot_hash
├── traceability
├── methodology
└── controller
```

`AnalysisService` 暴露 `pipeline_report(project_id)`；pipeline 运行响应在 `run` 中附加该报告，Web 页面在读取历史运行或刷新页面时也通过同一服务重算。报告只读、确定性、绑定当前 revision，不写 Patch、不创建 Run、不调用 LLM。

### 方案 C：把结果塞进 WorkflowRunner.RunSummary

扩展 `RunSummary` 保存所有应用展示数据。

这会让方法论执行层依赖应用层追溯投影，扩大跨层耦合，并使单阶段运行与完整 pipeline 的责任边界变得模糊，因此不选用。

## 详细设计

### PipelineReportService

新增应用层只读服务，依赖 `ModelRepository`、`MethodologyEngine` 和 `SystemsEngineeringController`：

1. 读取项目当前 ModelGraph 一次。
2. 调用 `build_traceability_summary(graph)`，生成逐需求 RFLP、Verification、Validation 和端到端闭环统计。
3. 调用 `MethodologyEngine.analyze(graph)`，生成 findings、metrics、decisions、impact paths 和 recommended tasks。
4. 使用同一份 report 调用 `SystemsEngineeringController.plan(graph, report)`。
5. 返回包含 `revision` 和 `snapshot_hash` 的 JSON-compatible `PipelineReport`。

报告计算失败时由调用方明确暴露为内部错误，不降级成伪造的“已完成”报告；它不会改变已经写入的 ModelGraph。

### API

`_invoke_pipeline()` 在 `WorkflowRunner` 完成后调用 `AnalysisService.pipeline_report()`，将以下字段附加到 pipeline `run`：

```json
{
  "traceability": {},
  "methodology": {},
  "controller": {},
  "report_revision": 12,
  "report_snapshot_hash": "..."
}
```

`deliverable.revision`、`report_revision` 和当前 ModelGraph revision 必须一致；`report_snapshot_hash` 必须等于交付包的 `snapshot_hash`。`mode=generate` 的既有响应结构保持兼容。

### Web 工作台

历史 pipeline 运行在 `build_analysis_view()` 中通过 `pipeline_report()` 补齐报告，再复用既有的展示适配器 `_decorate_methodology()` 和 `_decorate_controller()`。页面不展示 TaskSpec、Patch、CAS 或内部任务键。

主结果区域按运行模式显示：

- pipeline：完整生命周期结果、追溯指标、架构候选、物理可行性、问题和下一步工程动作；
- generate：保留现有五阶段结果和阶段反馈详情。

两个模式都链接到同一份 ModelGraph、Traceability 页面和交付包，不在页面生成第二份模型。

### 数据流与一致性

```text
POST /analysis
       │
       ├─ run_pipeline()
       │     └─ WorkflowRunner 写 ModelGraph revision N
       │
       ├─ pipeline_report()
       │     └─ 读取 revision N，计算 Trace/Methodology/Controller
       │
       └─ deliverables.build()
             └─ 读取 revision N，生成交付包
```

报告是当前图的确定性投影，而不是持久化事实。Run、Patch、Revision 和 audit 仍由现有工作流负责；报告中所有 ID 必须来自同一份 ModelGraph。

## 验收标准

1. `POST /projects/{id}/analysis` 未指定 `mode` 时返回 `mode=pipeline`，并同时返回 `traceability`、`methodology`、`controller`、报告 revision/hash 和 deliverable。
2. 使用离线规则 Runtime 的单需求输入能完成 23 个任务；报告中的 revision/hash 与 ModelGraph 和交付包完全一致。
3. 配置 StructuredModelRuntime 时，报告不会额外触发模型调用；23-task 调用顺序仍只由 WorkflowRunner 控制。
4. Web 页面在 pipeline 运行后显示“工程检查”、逻辑架构候选、物理可行性矩阵和下一步工程动作；刷新页面后仍能显示这些内容。
5. `mode=generate` 的五阶段 API、页面测试、Controller 操作和交付包测试保持通过。
6. 报告生成不创建新的 revision、Patch 或 Run；锁定实体不会被报告计算修改。

## 非目标

- 本阶段不增加真实 Provider 稳定性轮次。
- 本阶段不自动替用户选择 Trade Study 方案。
- 本阶段不接入仿真、CAD 或真实测试执行沙箱。
- 本阶段不改变已有 Methodology Engine 的工程规则，只把结果接入完整生命周期产品入口。
