# MBSE4AI v0.3.2 Fair Evaluation 验收状态

更新时间：2026-09-25 05:40 CST
审计提交：`00a78db`
PR：[zhouduichen/MBSE4AI#2](https://github.com/zhouduichen/MBSE4AI/pull/2)

本文严格区分“代码契约已经验证”和“真实外部实验已经产生证据”。前者不能替代后者。

| # | 验收项 | 当前状态 | 权威证据 / 边界 |
|---:|---|---|---|
| 1 | A–E 实际输入 byte/hash 一致 | REAL EVIDENCE; FAIL-CLOSED | run14 的 input artifact audit 为 `15/15 exact`，共同 artifact SHA-256=`70e5f128a4cecdfce30fec9a05340c0e18431c93055870d30d7fbd05b6540669`、input hash=`e5ab4f5b3c6b719491c716a7fdb0e3613ecd4e28c672665acb1891d02a87de10`；但 E 超时后 comparison 对整体 `same_input` fail-closed |
| 2 | Ground truth 仅 ExternalEvaluator 可访问 | REAL EVIDENCE | run14 comparison=`ground_truth_isolated=true`、`same_evaluator=true`、`same_evaluation_spec=true`；15 个输入 artifact 均记录 guard evidence |
| 3 | A/B 无法声明 Accepted/User authority | REAL EVIDENCE | run14 的 A/B authority claims 被 ExternalEvaluator 记录（A mean 18、B mean 49.67），没有被模型声明直接采信；A/B 的 release/technical closure 均未通过 |
| 4 | Semantic 与 Governance metrics 分离 | REAL EVIDENCE | run14 同时生成 semantic projection 与 governance authority/Technical Closure/Release Closure 分支；D 的 Technical Closure mean pass=1、Release Closure mean pass=0 |
| 5 | C/D/E 正交 Ablation | REAL EVIDENCE; OVERALL FAIL | run14 metadata 记录 C=`verifier=false, gate=true, repair=true, CAS=true`，D=`verifier=true, gate=true, repair=false, CAS=true`；E 因三次 timeout 没有完整 controls，整体 `ablation_contract_valid=false` |
| 6 | verifier/gate/repair/CAS 开关可审计 | REAL EVIDENCE; E INCOMPLETE | A–D 的每个 repeat 均写入四个独立 control 字段；E 三次只留下 timeout/blocked metadata，不能补推开关 |
| 7 | total token usage | REAL EVIDENCE; E INCOMPLETE | A/B/C/D 记录真实 input/output/total tokens；A mean 4269、B mean 31459.67、C mean 233908、D mean 82929；E 无 token usage，整体 `token_usage_observed=false` |
| 8 | model call count | REAL EVIDENCE; E INCOMPLETE | A mean 1、B mean 5、C mean 32.67、D mean 11；E 无完整 call telemetry，整体 `real_calls_observed=false` |
| 9 | latency/cost | LATENCY REAL; COST UNAVAILABLE | A–D 记录 wall/provider latency；run14 cost status 全部 `unavailable`，没有伪造价格或成本，整体 cost invariant 保持 FAIL |
| 10 | natural 与 budget-matched | NATURAL REAL; BUDGET CONTRACT ONLY | run14 使用 natural mode、共同 per-call cap=8192 且 A–E profile 同步；budget-matched 仍只有契约验证，不能用 natural run 代替 |
| 11 | 3–5 repeats 与统计 | REAL 3 REPEATS; FAIL-CLOSED | A–E 均有 3 个 repeat 目录；A–D 生成 mean/std/CI95，E 三次均 `TimeoutError`/`blocked`，故整体 execution complete 仍为 false |
| 12 | GitHub CI 真实 PASS | VERIFIED | push/PR `CI / quality` 对提交 `00a78db` 均成功：[push run 36042188263](https://github.com/zhouduichen/MBSE4AI/actions/runs/36042188263)、[PR run 36042183423](https://github.com/zhouduichen/MBSE4AI/actions/runs/36042183423)；此前提交的 checks 也保持成功 |
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

## run13 中间态记录（最终状态见下方“run13 最终收口与 run14 状态更新”）

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

## run13 最终收口与 run14 状态更新

run13 已完整收口，但 `a_to_e_comparison.json` 的整体 `status=FAIL`，不能替代 A–E PASS。共同 input artifact audit 为 `15/15 exact`，并且 `ground_truth_isolated=true`、`same_evaluator=true`、`same_normalizer=true`；整体 `execution_complete=false`，因为多个真实 repeat 未成功完成。

- A：repeat01/02 分别为 `327.281s / 4313 tokens` 与 `317.594s / 4269 tokens`；repeat03 在 `720.998s` 触发 `StructuredOutputFailure`，provider 输出在一次 repair 后仍被截断。
- B：3/3 完成，耗时约 `1183.935s`、`1187.243s`、`1180.083s`，每次 5 calls、`32760 tokens`。
- C：repeat01 完成（`252.919s`、6 calls、`50227 tokens`）；repeat02 有 1 个 failed call 并 fail-fast；repeat03 完成（`601.135s`、6 calls、`55972 tokens`）。
- D：repeat01 完成（`1270.895s`、21 calls、`170190 tokens`）；repeat02/03 各有 1 个 failed call。
- E：repeat01 在 `2363.099s` 发生 `ProviderCallFailure`（39 calls、1 failed call）；repeat02 在 `2700.067s` 记录 `TimeoutError`/`blocked`；repeat03 完成（`2687.420s`、41 calls、`341558 tokens`、71 entities、142 relations、`completed_with_warnings`）。E3 的 Technical Closure 通过、Release Closure 失败（23 个下游 fact 仍为 `VALIDATED`），`trace_accuracy=0.0`、`end_to_end_traceability=0.0`。

run13 因此证明了服务器本机可以运行同模型、同输入、同 evaluator 的真实 A–E 管线，也暴露了 4096 cap 下的 JSON 截断、provider fail-fast 和 2700s tail latency；所有这些失败均按原始 execution metadata 保留，没有 fallback 或写死 coverage。

## 最新远端 run14（8192 cap，完整收口但 FAIL）

```text
endpoint: http://127.0.0.1:8000/v1
model: qwen3.5-controller
profile: jiayuinter-vllm-v032-remote-8192
command: --compare-a-e --path vertical --case CASE-01 --repeats 3 --timeout 2700 --benchmark-token-budget 8192 --comparison-mode natural
results: /tmp/ai4mbse-v032-ae-natural-vertical-20260924-run14-results
reports: /tmp/ai4mbse-v032-ae-natural-vertical-20260924-run14-reports
```

run14 已完整生成 `a_to_e_comparison.json`、`a_to_e_comparison.md` 与 `reproducibility_manifest.json`，但 comparison `status=FAIL`、`execution_complete=false`。输入 artifact audit 为 `15/15 exact`，`ground_truth_isolated=true`、`same_evaluator=true`、`same_normalizer=true`、`same_evaluation_spec=true`；整体 comparison 对 incomplete execution fail-closed，因此 `same_input`、`same_model_provider`、`same_task_spec`、real calls、token usage、latency、cost 等 overall invariant 仍不能宣称通过。

- A：3/3 completed，mean `1 call / 4269 tokens / 325259 ms`，三次 graph hash 一致；verifier/gate/repair/CAS 均为 false。
- B：3/3 completed，mean `5 calls / 31459.67 tokens / 1117519 ms`，三次均在 8192 cap 内；verifier/gate/repair/CAS 均为 false。
- C：`verifier=false, gate=true, repair=true, CAS=true`；repeat01 为 35 calls、8 failed provider calls、1883.258s 并 fail-fast；repeat02 无失败、22 calls、178997 tokens；repeat03 为 41 calls、1 failed call、2536.575s 并 fail-fast。
- D：`verifier=true, gate=true, repair=false, CAS=true`；repeat01 为 21 calls、1 failed call，repeat02/03 均 6 calls、约 51.4k tokens、约 278s；Technical Closure 通过，但 Release Closure 因下游 `VALIDATED` facts 未达到 `ACCEPTED/LOCKED` 失败。
- E：三次均 `TimeoutError`/`blocked`，每次约 `2700s`，没有完整 graph/telemetry，不能补推 full-Harness 的质量或成本收益。

run14 使用的是修复提交 `00a78db` 之前的远端 checkout。C1 期间 vLLM 日志明确记录 xgrammar `enum array must not be empty` 并返回 HTTP 500；本地提交 `00a78db` 已修复完整 R 阶段生成空 enum 的 schema bug，并通过 targeted tests/CI，下一次真实 A–E 必须在该修复提交上重新执行。该 run 的原始失败、timeout、token 和 latency evidence 均保留，不用 fallback 或写死 coverage 掩盖。

## run15（修复 checkout，但被外部 GPU handoff 中断）

run15 使用独立 `/tmp/ai4mbse-v032-remote-run15` checkout，并替换为 `00a78db` 中已验证的 `executor.py`；启动命令与 run14 相同但 per-case timeout 提高到 `5400s`。A1 开始真实生成且 vLLM 日志未再出现空 enum 500，但约 4 分钟后 Controller scheduler 记录：`campaign holds Controller lane for worker handoff; stopping owned vLLM child`，随后 vLLM `PID 3337166` 被停止并在 `rc=137` 后回收 GPU。run15 的 A1/A2/A3 分别以 `URLError`（约 `299s`、`2s`、`2s`）失败，benchmark 按比较 invariant fail-closed 退出；没有产生可用于 A–E 质量结论的完整 comparison。该 run 证明下一次真实重跑的必要前置条件不是单纯 `:8000` 可访问，而是整个 Controller GPU lease 在 A–E 完整时段内稳定，不能把 scheduler handoff 期间的部分结果计为 PASS。

## 最新 GitHub Integration 证据（run 35861617609）

2026-09-23 的 `workflow_dispatch` run [35861617609](https://github.com/zhouduichen/MBSE4AI/actions/runs/35861617609) 中，`integration contract` 与 `external prerequisite readiness` 成功；但 `remote LLM A–E comparison`、`GPU acceptance`、`FreeCAD acceptance` 三个 job 均为 `skipped`。因此该 run 只能证明离线 contract 与 prerequisite gate 的行为，不能证明真实远程 LLM、GPU 或 FreeCAD 已在 GitHub runner 上执行。

当前仓库仍没有 self-hosted runner、Actions variables 或 secrets。远端服务器本机的 vLLM 实验与 GitHub integration evidence 必须分开记录；不能用 workflow overall success 或 skipped job 替代外部验收 PASS。

## 当前结论

v0.3.2 的实验边界、隔离规则、per-call/total 预算公平性、统计、统一 Coverage 语义和 CI 机制已经进入可审计状态；run14 证明服务器本机可以在同模型、同输入、同 evaluator 下真实走完 A–E 调度，但 comparison 因 C 的 provider schema 失败、E 的 2700s tail timeout、cost unavailable 以及 Release Closure 结果为 `FAIL`，不能冒充 Harness 收益已被证明。空 enum schema bug 已在 `00a78db` 修复并通过 CI；run15 又证明仅等待 `:8000` 空闲不足以保证实验，外部 GPU handoff 会在中途回收 vLLM，下一次必须取得稳定 Controller lease 或可审计的 scheduler hold 后再重跑 A–E。Integration workflow 已修复为显式分层 timeout，但完整目标尚未完成；第 14 项还需要默认分支上的 scheduled run，第 15 项还需要配置真实 Remote LLM profile、FreeCAD runner/credentials 和 GPU runner，并取得完整 A–E 的质量/成本结果。

本地离线测试、contract job、skip 状态和 SSH 可达性检查都不能替代第 15 项的 GitHub integration evidence。
