# AI4MBSE MBSE Benchmark 自动验收测试设计

## 目标

在不修改生产逻辑以制造通过结果的前提下，对当前 RFLP-Lite / AI4MBSE Harness 通过真实应用链路执行 CASE-01～CASE-05 和 T1～T20，保存真实模型与运行产物，输出可复现的指标、失败根因、追溯报告和最终 ACCEPTED / REJECTED 决策。

## 范围与原则

- 测试范围覆盖当前仓库真实的 `V2Services → AnalysisService → WorkflowRunner → ModelGraph/SQLite` 链路。
- 默认使用仓库已有的 `RuleRuntime` 作为离线运行时；不连接外部 LLM，避免网络、密钥和随机输出破坏回归稳定性。
- 测试只新增 benchmark fixture、runner、validator 和报告；生产缺陷只记录，不为通过测试而修复。
- `expected/` 只保存语义覆盖参考、已知约束和 CASE-05 冲突，不保存冒充系统输出的黄金模型。
- 每个案例使用独立临时工作区。CASE-05 的物理设计由 fault-injection harness 按案例输入注入 ModelGraph，再调用真实 Assurance / Verification 链路。
- 每个案例至少运行 3 次；超时、运行异常、未实现能力分别标记为 `BLOCKED`、`FAIL`、`NOT_IMPLEMENTED`。

## 测试架构

### Cases 与准备器

`tests/mbse_benchmark/cases/` 保存五个输入案例；`expected/` 保存每个案例的 stakeholder、lifecycle、scenario、异常条件、数值约束和 P0 期望。准备器只负责创建项目、导入输入以及 CASE-05 的通用物理注入，不写入预期结果。

### Runner

`tests/mbse_benchmark/runners/` 提供单案例运行器和总 benchmark runner。运行器调用 `build_v2_services()`、`ProjectService`、`AnalysisService` 和 `ModelService`，将原始运行摘要、模型导出、issues、audit 和诊断保存到 `results/case_xx/`。运行阶段设置明确超时，避免配置错误或修复循环阻塞整个验收。

### Validators

`tests/mbse_benchmark/validators/` 提供确定性检查：

- schema / ID / relation endpoint / reference validity；
- stakeholder 与 lifecycle 语义覆盖；
- scenario 类型与异常条件召回；
- requirement 清晰性、原子性、可验证性、来源与不支持假设；
- Scenario → Requirement → Use Case → Activity 的关系和语义一致性；
- Function → Logical → Physical RFLP 链；
- Verification Case 字段、Requirement 连接和测试类型覆盖；
- 数值质量、物理质量、runtime / mass / power / energy 冲突；
- upstream、end-to-end trace、orphan、iteration、change impact 和 3 次回归稳定性。

缺失对应产品能力时 validator 返回 `NOT_IMPLEMENTED`，而不是将缺失结果当作 PASS。

## 执行流

1. 记录 git commit、branch、Python、配置和测试时间。
2. 对每个案例创建新工作区并导入原始输入。
3. 运行完整生命周期；必要时按真实阶段分别运行，以定位阻塞位置。
4. 导出真实 ModelGraph、Run Ledger、Issues、Audit 和阶段结果。
5. 执行 T1～T20 validator，计算指标和 P0 hard gates。
6. CASE-05 检查 `32 kg > 20 kg` 与 `1000 Wh / 200 W = 5 h < 12 h`，并检查错误的 SATISFIED 判定。
7. 同一案例重复三次，比较结构、关键语义覆盖、关系和指标稳定性。
8. 生成 benchmark、failure 和 traceability 报告。

## 判定

综合评分按任务书的 100 分制计算。最终只有同时满足 `score >= 80` 和全部 P0 通过时才为 `ACCEPTED`；否则为 `REJECTED`。若完整能力尚未实现，同时报告 current capability score 与 full target capability score。

## 产物

```text
tests/mbse_benchmark/results/case_01/...
tests/mbse_benchmark/results/case_05/...
tests/mbse_benchmark/reports/benchmark_report.md
tests/mbse_benchmark/reports/metrics.json
tests/mbse_benchmark/reports/failures.json
tests/mbse_benchmark/reports/traceability_report.md
```
