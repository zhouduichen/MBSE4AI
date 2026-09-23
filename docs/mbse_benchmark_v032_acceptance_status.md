# MBSE4AI v0.3.2 Fair Evaluation 验收状态

更新时间：2026-09-24
审计提交：`7db0922`
PR：[zhouduichen/MBSE4AI#2](https://github.com/zhouduichen/MBSE4AI/pull/2)

本文严格区分“代码契约已经验证”和“真实外部实验已经产生证据”。前者不能替代后者。

| # | 验收项 | 当前状态 | 权威证据 / 边界 |
|---:|---|---|---|
| 1 | A–E 实际输入 byte/hash 一致 | CONTRACT VERIFIED | `BenchmarkInputEnvelope`、`_persisted_input_audit`、A–E comparison invariant；每个 repeat 在 worker 启动前落盘 `input.json`，同时记录 canonical payload hash 与实际 artifact SHA-256/byte length；真实 LLM run 仍待外部 profile |
| 2 | Ground truth 仅 ExternalEvaluator 可访问 | CONTRACT VERIFIED | `ExternalEvaluator.from_expected_dir()` 是唯一加载 `EvaluationSpec` 的入口；A/B 与 C/D/E provider 调用前都经过 evaluator 派生的 value-free request guard，metadata 还要求 `ground_truth_payload_transmitted=false` 与 `guard_enforced=true`；真实 LLM run 仍待外部 profile |
| 3 | A/B 无法声明 Accepted/User authority | CONTRACT VERIFIED | `ModelGraphNormalizer` 强制 `CANDIDATE/LLM` 并记录 authority audit |
| 4 | Semantic 与 Governance metrics 分离 | CONTRACT VERIFIED | `ExternalEvaluator.semantic_projection()` 将所有活跃生命周期状态统一为 `VALIDATED` 后再评估语义指标；原始状态、authority claims 与 Technical/Release Closure 保留在 governance metrics 分支 |
| 5 | C/D/E 正交 Ablation | CONTRACT VERIFIED | `validate_ablation_contracts()` 与 scenario contract tests；D 在 runtime 中实际关闭 feedback、operational completion 和 completion bridge，C/E 显式开启 repair 路径 |
| 6 | verifier/gate/repair/CAS 开关可审计 | CONTRACT VERIFIED | comparison metadata/report 四个独立 control 字段 |
| 7 | total token usage | CONTRACT + FAIL-CLOSED | adapter transport telemetry；缺 usage 时 token evidence 不可用，budget-matched 直接失败 |
| 8 | model call count | CONTRACT VERIFIED | transport-boundary `GenerationCallEvent` 聚合，包括 repair calls |
| 9 | latency/cost | CONTRACT + FAIL-CLOSED | provider/wall latency 与 pricing telemetry；profile 保留显式 `0` 价格，缺价格仍为 unavailable，不伪造成本 |
| 10 | natural 与 budget-matched | CONTRACT VERIFIED | 两种 comparison mode；A–E 先统一 effective per-call output cap，并将 lifecycle/vertical batch 与 singleton fallback 都绑定到该 cap，记录 `call_output_token_budget`；公平性比较使用共同 benchmark task-spec hash，同时保留 Harness runtime task-spec hash；natural mode 对总预算明确标记 `not_applicable`，只有 budget-matched 跨调用共享 total cap 并检查 `budget_within_cap`；缺失 temperature 或 per-call cap 时 comparison fail-closed |
| 11 | 3–5 repeats 与统计 | CONTRACT VERIFIED | comparison 至少 3 repeats，JSON/报告记录 mean/std/CI95 与 Quality-Cost；Markdown 另有显式 Repeat statistics 表；主表的 Calls/Tokens/Latency/Cost 明确使用 repeat mean |
| 12 | GitHub CI 真实 PASS | VERIFIED | push/PR `CI / quality` 对当前分支最新提交 `7db0922` 均成功：[push run 35883836014](https://github.com/zhouduichen/MBSE4AI/actions/runs/35883836014)、[PR run 35883843077](https://github.com/zhouduichen/MBSE4AI/actions/runs/35883843077) |
| 13 | main 要求 CI / quality | VERIFIED | GitHub API 当前返回 `strict=true`、required context=`CI / quality`、required approvals=1、`enforce_admins=true` |
| 14 | Integration schedule 不空跑 | CONTRACT VERIFIED; SCHEDULE PENDING | `.github/workflows/integration.yml` 已包含周六 schedule、无条件 contract job 和外部 prerequisite readiness；但该 workflow 尚未进入默认分支，因此尚无 scheduled event 的权威 run evidence。当前 GitHub repository 仍无 Actions variables/secrets；若 schedule 没有任何外部目标，readiness 会明确失败而不是绿灯空跑 |
| 15 | Remote LLM/FreeCAD/GPU 真实 workflow | NOT YET PROVEN | GitHub 当前 self-hosted runners=0、Actions variables=0、secrets=0。Jiayu-intern 曾验证 managed vLLM `/v1/models` 与真实 chat completion/usage 可用；本次真实比较目录为 `/tmp/ai4mbse-v032-ae-natural-20260923-run1-results`，只完成 A repeat 1 的真实 one-shot，B 尚未取得完整 repeat，C/D/E 结果在 vLLM 被 scheduler 回收后记录为 blocked，比较进程因 `execution_complete`、`real_calls_observed`、`token_usage_observed` 等 invariant fail-closed 退出。远端证据明确显示 `controller-handoff-hold.state=worker_handoff`、worker lease `[0,1,2,3]`，以及 `campaign holds Controller lane for worker handoff; stopping owned vLLM child`；因此不能把该目录或 fallback 结果计为 A–E PASS |

## 当前结论

v0.3.2 的实验边界、隔离规则、per-call/total 预算公平性、统计、统一 Coverage 语义和 CI 机制已经进入可审计状态；但完整目标尚未完成。第 14 项还需要默认分支上的 scheduled run，第 15 项还需要配置真实 Remote LLM profile、FreeCAD runner/credentials 和 GPU runner，并为 vLLM 申请不被 GPU queue 中途回收的完整实验租约；之后才能取得可发表的 A–E 质量/成本结果。

本地离线测试、contract job、skip 状态和 SSH 可达性检查都不能替代第 15 项的 GitHub integration evidence。
