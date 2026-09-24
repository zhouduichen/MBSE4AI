# MBSE4AI v0.3.2 Fair Evaluation 验收状态

更新时间：2026-09-24 15:56 CST
审计提交：`5427733`（run13 证据追加待提交）
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
| 12 | GitHub CI 真实 PASS | VERIFIED | push/PR `CI / quality` 对当前分支最新提交 `c841b33` 均成功：[push run 35967820606](https://github.com/zhouduichen/MBSE4AI/actions/runs/35967820606)、[PR run 35967826427](https://github.com/zhouduichen/MBSE4AI/actions/runs/35967826427)；此前 `38c62c5`、`a28694b`、`6807bd2`、`ba7002a`、`9e16650`、`3a143fb`、`7c44f33`、`e5814d9`、`ea3d9fe` 与 `2a16329` 的对应 checks 也保持成功 |
| 13 | main 要求 CI / quality | VERIFIED | GitHub API 当前返回 `strict=true`、required context=`CI / quality`、required approvals=1、`enforce_admins=true` |
| 14 | Integration schedule 不空跑 | CONTRACT VERIFIED; SCHEDULE PENDING | `.github/workflows/integration.yml` 已包含周六 schedule、无条件 contract job、外部 prerequisite readiness，以及 remote A–E 的分层 timeout：默认 per-case `2700s`、per-call budget `4096`，可由 `AI4MBSE_LLM_CASE_TIMEOUT_SECONDS` / `AI4MBSE_LLM_BENCHMARK_TOKEN_BUDGET` 覆盖并在 summary 记录；但该 workflow 尚无配置外部目标的 scheduled event 权威 run evidence。当前 GitHub repository 仍无 Actions variables/secrets；若 schedule 没有任何外部目标，readiness 会明确失败而不是绿灯空跑 |
| 15 | Remote LLM/FreeCAD/GPU 真实 workflow | NOT YET PROVEN | GitHub 当前 self-hosted runners=0、Actions variables=0、secrets=0。Jiayu-intern 曾验证 managed vLLM `/v1/models` 与真实 chat completion/usage 可用；此前三次真实比较均被远端资源切换中断：`/tmp/ai4mbse-v032-ae-natural-20260923-run1-results` 只完成 A repeat 1，`/tmp/ai4mbse-v032-ae-natural-20260924-run2-results` 留下 A/B 输入与部分 C/D/E blocked 结果，`/tmp/ai4mbse-v032-ae-natural-vertical-20260924-run3-results` 已按正确 `--path vertical` 发出真实请求但仍在 00:31:37 被回收。随后 run4 在 A-repeat-03 期间再次被回收；run5（`/tmp/ai4mbse-v032-ae-natural-vertical-20260924-run5-results`，报告 `/tmp/ai4mbse-v032-ae-natural-vertical-20260924-run5-reports`）确认了同一根因：01:09:05 `/v1/models` 与真实请求可用，01:11:45 远端 supervisor 启动下一个 worker handoff，launcher 按策略停止 vLLM，A/B/C/D 记录 `ConnectionResetError`，E 仅留下 `completed_with_warnings`，comparison 为 FAIL。run6 在 campaign 终态后的短窗口启动成功，但 01:25:07 supervisor 又启动 candidate 3 F1 并触发同样的 vLLM 回收；`/tmp/ai4mbse-v032-ae-natural-vertical-20260924-run6-results` 只有 C/D 三 repeats 与 E 三失败 repeats，A/B/C/D/E comparison 仍为 FAIL。run7/8 则在远端 vLLM 健康时暴露了本地 SSH tunnel 生命周期问题：远端 `/v1/models` 正常但本地 `18000` 消失，runner 记录 `URLError`；run9 使用自动重连 tunnel 后确认前两次真实 POST 成功，但约 5 分钟后新的 detached supervisor（PID `1716998`，`--max-rounds 6`）启动 candidate 6 handoff，仍按策略停止 vLLM，run10 因同一 handoff 中止。run11 已在服务器本机直连窗口内完整走过 A–E 目录，但 comparison 明确为 `FAIL`：A 3/3 completed；B 3/3 blocked at 900s；C 为 2 blocked + 1 failed；D/E 各 3 failed。远端当前 vLLM 已退出，GPU 被 `student_campaign_supervisor` 占用，因此不能把 run11 或任何部分目录/fallback 结果计为 A–E PASS |

## 最新远端 run11（部分完成，不能替代完整 A–E）

run11 利用 campaign 结束后的 vLLM 空闲窗口，在 `Jiayu-intern` 服务器本机直接运行，避免 SSH tunnel 生命周期影响：

```text
endpoint: http://127.0.0.1:8000/v1
model: qwen3.5-controller
profile: jiayuinter-vllm-v032-remote
command: --compare-a-e --path vertical --case CASE-01 --repeats 3
comparison-mode: natural
benchmark-token-budget: 4096
benchmark PID: 2409113
vLLM PID: 2171645
results: /tmp/ai4mbse-v032-ae-natural-vertical-20260924-run11-results
reports: /tmp/ai4mbse-v032-ae-natural-vertical-20260924-run11-reports
```

截至本次审计，run11 已终止并生成 `a_to_e_comparison.json` / `a_to_e_comparison.md` / `reproducibility_manifest.json`，但 comparison `status=FAIL`。A `Bare one-shot` 已完成 3/3 repeats；三份 A metadata 均记录 `execution_status=completed`、`call_count=1`、`total_tokens=4269`，wall latency 分别为 324995、322673、323395 ms。A 三份及 B 三份的实际 `input.json` 均为 1549 bytes、SHA-256 `70e5f128a4cecdfce30fec9a05340c0e18431c93055870d30d7fbd05b6540669`。B `Bare staged` 的 repeat 1/2/3 均记录 `status=blocked`、`exception_type=TimeoutError`、`timeout_seconds=900`；C 为两个 blocked 和一个 failed，D/E 三 repeats 均 failed。comparison 仍证明共同 `evaluation_spec`、ExternalEvaluator、ModelGraph normalizer 与 ground-truth isolation 的契约边界，但因执行不完整，`same_model_provider`、`same_input`、`same_task_spec`、telemetry invariants 等 overall checks 均未通过。run11 的失败原因已确认是外层 case timeout/远端资源窗口，不是允许 fallback 后的伪 PASS；第 15 项以及 A–E 的整体结论仍保持 NOT YET PROVEN。

## 最新远端 run12（GPU handoff 中断，不能替代完整 A–E）

```text
endpoint: http://127.0.0.1:8000/v1
model: qwen3.5-controller
profile: jiayuinter-vllm-v032-remote
command: --compare-a-e --path vertical --case CASE-01 --repeats 3 --timeout 2700 --benchmark-token-budget 4096
benchmark PID: 2519279
initial vLLM PID: 2515503
results: /tmp/ai4mbse-v032-ae-natural-vertical-20260924-run12-results
reports: /tmp/ai4mbse-v032-ae-natural-vertical-20260924-run12-reports
```

run12 的 outer case timeout 已足够，但约 2.5 分钟后远端 launcher 记录 `owned vLLM child did not exit after 20s; force reaping process tree` 与 `vLLM exited rc=137; returning to GPU queue`。随后所有场景都 fail-closed：A/B 为 transport failure，C/D 每个 repeat 有 4 个 failed calls，E 每个 repeat 有 33 个 failed calls，token usage 为 0，comparison `status=FAIL`。该结果证明下一次实验必须把“vLLM 已监听”与“GPU handoff lease 已稳定释放”作为两个独立前置条件。

## 最新远端 run13（A repeat03 输出截断，不能替代完整 A–E）

```text
endpoint: http://127.0.0.1:8000/v1
model: qwen3.5-controller
profile: jiayuinter-vllm-v032-remote
command: --compare-a-e --path vertical --case CASE-01 --repeats 3 --timeout 2700 --benchmark-token-budget 4096
benchmark PID: 2550996
vLLM PID: 2546523
results: /tmp/ai4mbse-v032-ae-natural-vertical-20260924-run13-results
reports: /tmp/ai4mbse-v032-ae-natural-vertical-20260924-run13-reports
```

run13 在 F3 campaign lease 释放后启动，vLLM 端口稳定且 A/repeat01、02 均完成真实调用：两次均 `call_count=1`、`failed_call_count=0`、token usage 可用，total tokens 分别为 4313 与 4269，wall latency 分别为 327280 与 317593 ms；三次输入均使用相同的 input hash `e5ab4f5b3c6b719491c716a7fdb0e3613ecd4e28c672665acb1891d02a87de10` 与 artifact SHA-256 `70e5f128a4cecdfce30fec9a05340c0e18431c93055870d30d7fbd05b6540669`。A/repeat03 在 `execution.json` 记录 `elapsed_seconds=720.99805`、`exception_type=StructuredOutputFailure`、`exception=LLM response is not valid JSON after one repair: provider output was truncated`，因此没有完整 graph/telemetry；comparison 不能通过 `execution_complete`、真实 calls 和后续 A–E invariants。run13 随后自然进入 B，当前仍在运行；该失败是 4096 per-call output cap 的真实边界证据，不应被 fallback 或写死 coverage 掩盖。下一次垂直比较必须提高同一个 A–E cap（并同步 profile 的 `max_output_tokens`，例如验证 8192），仍需让所有场景共享该 cap 后重新完成至少 3 repeats。

## 当前结论

v0.3.2 的实验边界、隔离规则、per-call/total 预算公平性、统计、统一 Coverage 语义和 CI 机制已经进入可审计状态；run11 已进一步证明服务器本机直连 vLLM 可以连续完成 A 的真实 repeats，同时证明当前 `--timeout 900` 不足以完成 B 的 staged 路径；run12 则证明仅提高 outer timeout 仍不足以避开 GPU handoff；run13 又证明 4096 per-call cap 会在 one-shot full RFLP+V&V 上触发真实 provider output truncation。Integration workflow 已修复为显式分层 timeout，但完整目标尚未完成。第 14 项还需要默认分支上的 scheduled run，第 15 项还需要配置真实 Remote LLM profile、FreeCAD runner/credentials 和 GPU runner，并取得完整 A–E 的质量/成本结果；下一次正式 run 必须等待 vLLM 重新监听并确认 handoff lease 稳定释放，使用同步提高后的统一 A–E cap（例如 8192）、outer case timeout `2700s` 和独立 output root，取得完整 comparison PASS。

本地离线测试、contract job、skip 状态和 SSH 可达性检查都不能替代第 15 项的 GitHub integration evidence。
