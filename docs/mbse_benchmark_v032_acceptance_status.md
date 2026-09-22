# MBSE4AI v0.3.2 Fair Evaluation 验收状态

更新时间：2026-09-22  
审计提交：`a0fc9dc`
PR：[zhouduichen/MBSE4AI#1](https://github.com/zhouduichen/MBSE4AI/pull/1)

本文严格区分“代码契约已经验证”和“真实外部实验已经产生证据”。前者不能替代后者。

| # | 验收项 | 当前状态 | 权威证据 / 边界 |
|---:|---|---|---|
| 1 | A–E 实际输入 byte/hash 一致 | CONTRACT VERIFIED | `BenchmarkInputEnvelope`、`_persisted_input_audit`、A–E comparison invariant；真实 LLM run 仍待外部 profile |
| 2 | Ground truth 仅 ExternalEvaluator 可访问 | CONTRACT VERIFIED | evaluator-only key rejection（包括 `EvaluationSpec` 的全部顶层键）、evaluation boundary metadata；真实 LLM run 仍待外部 profile |
| 3 | A/B 无法声明 Accepted/User authority | CONTRACT VERIFIED | `ModelGraphNormalizer` 强制 `CANDIDATE/LLM` 并记录 authority audit |
| 4 | Semantic 与 Governance metrics 分离 | CONTRACT VERIFIED | `ExternalEvaluator.semantic_projection()` 与 governance metrics 分支 |
| 5 | C/D/E 正交 Ablation | CONTRACT VERIFIED | `validate_ablation_contracts()` 与 scenario contract tests |
| 6 | verifier/gate/repair/CAS 开关可审计 | CONTRACT VERIFIED | comparison metadata/report 四个独立 control 字段 |
| 7 | total token usage | CONTRACT + FAIL-CLOSED | adapter transport telemetry；缺 usage 时 token evidence 不可用，budget-matched 直接失败 |
| 8 | model call count | CONTRACT VERIFIED | transport-boundary `GenerationCallEvent` 聚合，包括 repair calls |
| 9 | latency/cost | CONTRACT + FAIL-CLOSED | provider/wall latency 与 pricing telemetry；缺价格不伪造成本 |
| 10 | natural 与 budget-matched | CONTRACT VERIFIED | 两种 comparison mode；budget-matched cap 跨调用共享并检查 `budget_within_cap` |
| 11 | 3–5 repeats 与统计 | CONTRACT VERIFIED | comparison 至少 3 repeats，报告 mean/std/CI95 与 Quality-Cost |
| 12 | GitHub CI 真实 PASS | VERIFIED | push/PR `CI / quality` 对 `a0fc9dc` 均成功：[push run](https://github.com/zhouduichen/MBSE4AI/actions/runs/35740185933)、[PR run](https://github.com/zhouduichen/MBSE4AI/actions/runs/35740193666) |
| 13 | main 要求 CI / quality | VERIFIED | branch protection `strict=true`、required context=`CI / quality`、required approvals=1 |
| 14 | Integration schedule 不空跑 | VERIFIED | unconditional `contract` job；最新 contract run 成功：[run 35689707347](https://github.com/zhouduichen/MBSE4AI/actions/runs/35689707347) |
| 15 | Remote LLM/FreeCAD/GPU 真实 workflow | NOT YET PROVEN | GitHub 当前 self-hosted runners=0、Actions variables=0、secrets=0；对应 jobs 必须保持 SKIPPED，不能计为 PASS |

## 当前结论

v0.3.2 的实验边界、隔离规则、预算公平性、统计和 CI 机制已经进入可审计状态；但完整目标尚未完成。只有配置真实 Remote LLM profile、FreeCAD runner/credentials 和 GPU runner 后，才能运行 A–E 并把第 15 项从 `NOT YET PROVEN` 更新为真实 job PASS，同时取得可发表的 A–E 质量/成本结果。

本地离线测试、contract job、skip 状态和 SSH 可达性检查都不能替代第 15 项的 GitHub integration evidence。
