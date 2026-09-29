# MBSE4AI v0.3.2 Fair Evaluation 验收状态

更新时间：2026-09-29 19:45 CST
审计提交：待本次文档提交生成
PR：[zhouduichen/MBSE4AI#2](https://github.com/zhouduichen/MBSE4AI/pull/2)

本文严格区分“代码契约已经验证”和“真实外部实验已经产生证据”。前者不能替代后者。

| # | 验收项 | 当前状态 | 权威证据 / 边界 |
|---:|---|---|---|
| 1 | A–E 实际输入 byte/hash 一致 | VERIFIED; OVERALL FAIL-CLOSED | run16 input artifact audit 为 `15/15 exact`；run25 进一步审计 `75/75 exact`，各 case artifact 均保留 SHA-256；输入边界本身已通过，整体 comparison 仍因执行不完整 FAIL |
| 2 | Ground truth 仅 ExternalEvaluator 可访问 | VERIFIED | run16 与 run25 均记录 `ground_truth_isolated=true`、`same_evaluator=true`、`same_evaluation_spec=true`；run25 的 75 个 artifact 均记录 evaluator guard evidence |
| 3 | A/B 无法声明 Accepted/User authority | VERIFIED | run16 的 A/B authority claims 被 ExternalEvaluator 记录（A=18、B=53），没有被模型声明直接采信；A/B 的 release/technical closure 均未通过 |
| 4 | Semantic 与 Governance metrics 分离 | VERIFIED | run16 同时生成 semantic projection 与 governance authority/Technical Closure/Release Closure 分支；D/E 的 Technical Closure mean pass=1、Release Closure mean pass=0 |
| 5 | C/D/E 正交 Ablation | VERIFIED; OVERALL FAIL | run16 metadata 记录 C=`verifier=false, gate=true, repair=true, CAS=true`，D=`verifier=true, gate=true, repair=false, CAS=true`，E 全开；controls 已可审计，但 execution 不完整，整体仍 fail-closed |
| 6 | verifier/gate/repair/CAS 开关可审计 | VERIFIED | run16 A–E 均生成独立 control 字段；E 的 provider fail-fast 不能被补推成成功，但不影响 controls 审计 |
| 7 | total token usage | REAL EVIDENCE; OVERALL FAIL-CLOSED | run16 A–E 均有真实 telemetry：A/B/C/D/E mean total tokens 分别为 `4269 / 32760 / 92520 / 127952.33 / 340293`；整体仍因 execution incomplete 保持 invariant FAIL |
| 8 | model call count | REAL EVIDENCE; OVERALL FAIL-CLOSED | run16 A/B/C/D/E mean calls=`1 / 5 / 11.33 / 18 / 42.33`；E 的 calls 也已记录，但 comparison 仍因失败重复保持整体 fail-closed |
| 9 | latency/cost | LATENCY REAL; COST UNAVAILABLE | run16 A–E wall latency mean 约 `321s / 1186s / 664s / 1135s / 2872s`；cost status=`unavailable`，没有伪造价格或成本 |
| 10 | natural 与 budget-matched | NATURAL REAL; BUDGET CONTRACT ONLY | run14 使用 natural mode、共同 per-call cap=8192 且 A–E profile 同步；budget-matched 仍只有契约验证，不能用 natural run 代替 |
| 11 | 3–5 repeats 与统计 | VERIFIED; FAIL-CLOSED | run16 A–E 均有 3 个 repeat 目录并生成 mean/std/CI95；D 为 1 completed+2 failed，E 为 3 failed，故整体 execution complete 仍为 false |
| 12 | GitHub CI 真实 PASS | VERIFIED | push/PR `CI / quality` 对 `9848b3d` 成功（push run `36560353612`、PR run `36560359569`）；此前桥接 workflow checks 也成功 |
| 13 | main 要求 CI / quality | VERIFIED | GitHub API 当前返回 `strict=true`、required context=`CI / quality`、required approvals=1、`enforce_admins=true` |
| 14 | Integration schedule 不空跑 | CONFIGURED; SCHEDULE EVIDENCE PENDING | `.github/workflows/integration.yml` 已包含周六 schedule、无条件 contract job、外部 prerequisite readiness、串行 concurrency，以及通过 remote-bridge runner 执行的 LLM/FreeCAD/GPU jobs；仓库已配置 LLM profile、8192 token budget、SSH bridge、FreeCAD/GPU 开关。尚无 scheduled event 的权威 run evidence；若外部目标不可用，readiness 会明确失败而不是绿灯空跑 |
| 15 | Remote LLM/FreeCAD/GPU 真实 workflow | PARTIAL; A–E TERMINAL FAIL | GitHub run `36524219363` 已真实 PASS FreeCAD 与 GPU acceptance（SSH 到 `Jiayu-intern`，FreeCAD 1.1.3/NVIDIA L40）；run `36524710210` 与 run25 `36540494618` 均真实进入远程 A–E，但均 fail-closed，run25 已保留 75 个 repeat artifact 和 terminal `status.json`。真实远程 workflow 已可执行，但尚无完整 A–E PASS，不能宣称 Harness 收益 |

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

## 最新远端 run16（利用 vLLM 空闲窗口，修复后真实收口但 FAIL）

run16 在修复后的 checkout 上运行，使用服务器本机 `127.0.0.1:8000`，避免 SSH tunnel 生命周期影响：

```text
endpoint: http://127.0.0.1:8000/v1
model: qwen3.5-controller
profile: jiayuinter-vllm-v032-remote-8192
command: --compare-a-e --path vertical --case CASE-01 --repeats 3 --timeout 5400 --benchmark-token-budget 8192 --comparison-mode natural
results: /tmp/ai4mbse-v032-ae-natural-vertical-20260926-run16-results
reports: /tmp/ai4mbse-v032-ae-natural-vertical-20260926-run16-reports
source fix: 00a78db (empty vertical requirement enum regression test passed)
```

这次实验验证了应采用的运行权衡：等待 vLLM 处于空闲且 Controller lease 稳定时启动，不长期强占 GPU，也不在 scheduler handoff 期间重启服务。vLLM 在 `03:48:52` 重新选择 GPU group 0 后，直到本轮收尾没有新的 `campaign holds`/`vLLM exited` 记录；收尾时 `num_requests_running=0`，vLLM `error/abort/repetition` counters 均为 0。也就是说，本轮的失败是实验执行/模型调用长尾证据，不是把 vLLM 重启后得到的伪结果。

run16 comparison 为 `status=FAIL`、`execution_complete=false`，但共同实验边界已经通过：`ground_truth_isolated=true`、`same_input=true`、`same_model_provider=true`、`same_evaluator=true`、`same_normalizer=true`、`same_evaluation_spec=true`、`same_task_spec=true`、`same_temperature=true`；输入 artifact audit 为 `15/15 exact`，共同 artifact SHA-256=`70e5f128a4cecdfce30fec9a05340c0e18431c93055870d30d7fbd05b6540669`，input hash=`e5ab4f5b3c6b719491c716a7fdb0e3613ecd4e28c672665acb1891d02a87de10`。

三次重复的聚合证据如下。所有 scenario 都使用同一个 `qwen3.5-controller`、同一个 ExternalEvaluator/normalizer 和同一个 8192 per-call cap：

| Scenario | Controls | 执行状态 | mean calls | mean total tokens | mean wall latency | semantic / governance 结果 |
|---|---|---|---:|---:|---:|---|
| A Bare one-shot | 全部 false | 3/3 completed | 1.00 | 4,269 | 321s | `RFLP=0`, `trace=0`, authority=18 |
| B Bare staged | 全部 false | 3/3 completed | 5.00 | 32,760 | 1,186s | `RFLP=0`, `trace=0`, authority=53 |
| C Harness−Verifier | verifier=false，其余 gate/repair/CAS=true | 3/3 completed（run_status failed） | 11.33 | 92,520 | 664s | `RFLP=0`, Technical/Release Closure=`0/0` |
| D Harness−Repair | verifier/gate/CAS=true，repair=false | 1 completed + 2 provider fail-fast | 18.00 | 127,952.33 | 1,135s | `RFLP=1`, `trace=0`, Technical/Release=`1/0` |
| E Full Harness | 全部 true | 3 provider fail-fast | 42.33 | 340,293 | 2,872s | `RFLP=1`, `trace=0`, Technical/Release=`1/0` |

本轮 comparison 的 invariant failures 仅保留为 `execution_complete`、`real_calls_observed`、`token_usage_observed` 和 `cost_observed`；后两项在实现中对不完整 A–E 仍 fail-closed，cost 仍不可用。不能据此宣称 Full Harness 已经带来收益，但可以确认：稳定空闲窗口显著提高了真实证据完整度，8192 cap 消除了 run14 期间观测到的 empty-enum schema 500，剩余主要问题转为 E 的长尾 provider fail-fast、总耗时和远程 runner/调度证据。后续应按 repeat 独立可恢复、空闲窗口运行、失败原样保留的方式继续，而不是延长 GPU 强占或把失败样本改写为 PASS。

## 既往 GitHub Integration 证据

2026-09-23 的 `workflow_dispatch` run [35861617609](https://github.com/zhouduichen/MBSE4AI/actions/runs/35861617609) 中，`integration contract` 与 `external prerequisite readiness` 成功；但 `remote LLM A–E comparison`、`GPU acceptance`、`FreeCAD acceptance` 三个 job 均为 `skipped`。因此该 run 只能证明离线 contract 与 prerequisite gate 的行为，不能证明真实远程 LLM、GPU 或 FreeCAD 已在 GitHub runner 上执行。

当前仓库已配置 remote-bridge runner 与外部目标 secrets；既往 run `35861617609` 仍只能证明离线 contract/readiness 与 skipped external jobs，不能替代真实远程 LLM、GPU 或 FreeCAD PASS。

## GitHub remote-bridge readiness 与真实外部验收（2026-09-29）

提交 `7080da3` 将 Integration workflow 改为 remote-bridge 架构；`48e16b7` 修复了 readiness job 使用默认 `GITHUB_TOKEN` 查询 runner API 导致的 403；`0bef823` 改用 runner-local Python 3.12，修复了 FreeCAD job 在 self-hosted Mac 上写 `/Users/runner` 失败；`490ab24` 将 loopback vLLM profile 明确视为 local/no-auth；`86f2666` 确保 benchmark 失败时仍上传远端原始报告。GitHub self-hosted Mac runner 通过专用 SSH key 和 jump-box 访问 `Jiayu-intern`，真实执行目标是服务器上的 vLLM、NVIDIA L40 和 FreeCAD 1.1.3。

- run [36524219363](https://github.com/zhouduichen/MBSE4AI/actions/runs/36524219363)：contract/readiness PASS；FreeCAD acceptance PASS；GPU acceptance PASS；本次 LLM 按 dispatch 参数跳过。
- run [36524446367](https://github.com/zhouduichen/MBSE4AI/actions/runs/36524446367)：vLLM 当时在线并完成 SSH/profile bootstrap，但 profile 被判定为 remote 且无 API key，A–E 未开始。
- run [36524710210](https://github.com/zhouduichen/MBSE4AI/actions/runs/36524710210)：loopback profile 修复后真正进入 A–E；远端报告显示各 scenario fail-closed，服务器日志记录 `13:04:24 vLLM exited rc=0`，随后 worker lease 占用 `[0,1,2,3]`。这是调度 handoff 中断证据，不是成功的 A–E 质量证据。

在本次观察中，`127.0.0.1:8000/v1/models` 曾在 13:04 CST 返回 `qwen3.5-controller`，但 worker handoff 很快取得全部四张 GPU；随后 13:15–13:23 的只读监控也未观察到连续稳定窗口。因而“端口可访问”不是充分条件；下一次 A–E 必须同时满足 endpoint healthy、Controller lease 稳定、worker lease 不覆盖 Controller GPU，并在该窗口内启动完整重复实验。

## GitHub run23：前台 runner 取消，远端 campaign 仍保留部分证据

GitHub run [36528400246](https://github.com/zhouduichen/MBSE4AI/actions/runs/36528400246) 使用 `bbd4bf4` 的稳定 lease 前置检查。contract/readiness 均通过，远端 vLLM 连续 6 次采样满足前置条件，随后真实 A–E 已开始；但 GitHub runner 在 benchmark 前台步骤运行约 1798 秒后收到外部取消信号（不是 benchmark 自己的 PASS/FAIL），SSH 子进程被 SIGINT/SIGTERM 收回，GitHub 侧没有完整实验 artifact。

取消后保留下来的远端快照位于本机临时证据目录 `/tmp/ai4mbse-evidence-final-36528400246.zPGBz0`，包含 558 个文件。快照仍能证明 75 个 A–E repeat 输入 artifact 全部存在且 byte/hash 一致，`ground_truth_isolated=true`、ExternalEvaluator 与 normalizer 配置一致；但执行不完整，不能作为 A–E 质量结论：A 只有 1 个 repeat 完成，B 无完整 telemetry，C/D/E 被 provider failure 或 scheduler handoff 打断，comparison 的 `execution_complete=false`。

远端随后在 14:33 CST 记录 vLLM EngineCore 被停止并返回 HTTP 500；14:35 CST 的只读状态显示 Controller handoff hold、release 和 worker GPU lease 同时出现。该证据确认“端口曾监听”仍不等于完整运行窗口，且不能通过重启 vLLM 或删除 scheduler marker 来修复实验结论。

为适配这个运行权衡，当前工作树新增 detached campaign wrapper 与独立 collector：提交 job 只在稳定 lease 后写入不可变 manifest 并启动远端 campaign；readiness 允许并行 worker lease，但会检查 Controller 与 worker 的 `allocated_gpus` 没有重叠；collector 读取原子 status，只有 `completed + exit_code=0 + comparison PASS + execution_complete=true + 无 invariant failures` 才上传为 PASS 证据。`running`、`interrupted`、scheduler-preempted 和 failed campaign 会被保留并明确标记为非 PASS。该改动在 CI 通过并完成一次 terminal collector 收集前，不计入第 15 项的完整 A–E 证据。

## GitHub run24：空闲窗口已确认，但 readiness 误判 worker lease

run [36535264100](https://github.com/zhouduichen/MBSE4AI/actions/runs/36535264100) 在 `41fbadb` 上手动触发。只读核验当时已确认 vLLM 监听 `127.0.0.1:8000`，Controller lease 为 GPU0，worker lease 为 GPU1–3，且利用率接近 0；但旧 readiness 条件错误地要求 worker lease 文件不存在，因此提交 job 一直等待，A–E 没有启动。确认窗口随后结束后，该 run 被取消，scheduler 接管全部 GPU 并停止 vLLM。

这不是 A–E 实验结果，也不应计入 remote LLM 成功或失败样本。提交 `3fe74db` 已把条件改为检查 Controller 与 worker 的 GPU 集合不重叠，同时继续拒绝 handoff hold；因此当前实际权衡是“允许并行且不冲突的 worker lease，避开 overlap/handoff 窗口”，而不是要求服务器完全没有 worker 活动。

## GitHub run25：稳定空闲窗口提交了真实 detached campaign，但 comparison FAIL

GitHub run [36540494618](https://github.com/zhouduichen/MBSE4AI/actions/runs/36540494618) 使用 `ff9b7d3` 的 Controller lease readiness。该 run 在远端连续收到 6 次 `READY:controller_gpus=[0],worker_gpus=[]` 后，于 `2026-09-29 16:52:19 CST` 启动 detached campaign；campaign 于 `17:22:39 CST` 以 `exit_code=1` 终止。GitHub job 本身 PASS 仅表示 manifest 已提交，不能表示 A–E 实验 PASS。

远端原始证据位于：

```text
/data/models/harness4h3-v27-code/evidence/student-campaign/
  ai4mbse-campaigns/github-36540494618/{status.json,manifest.json,
  benchmark.stderr.log,reports/llm/jiayuinter-vllm-v032-remote-8192/}
```

`status.json` 的终态为 `state=failed`、`evidence_ready=false`、`error="benchmark exited with code 1"`；comparison report 为 `status=FAIL`，fail-closed invariant 包括 `execution_complete`、`real_calls_observed`、`token_usage_observed`、`latency_observed`、`cost_observed` 以及 model/input/task-spec/ablation 一致性检查。

这次 command 覆盖 5 个 case、每个 3 repeats，共 75 个输入 artifact。`input_artifact_audit` 为 `all_present=true`、`all_exact=true`、`checked_count=75`，说明落盘的 benchmark 输入没有发生 byte/hash 漏洞；`ground_truth_isolated=true`、`same_evaluator=true`、`same_normalizer=true`、`same_evaluation_spec=true` 也成立。但由于大量 repeat 在 provider 调用阶段失败，comparison 的整体 `same_input`、`same_task_spec`、`same_temperature`、real-call/token/latency/cost invariants 仍为 false，不能把 artifact audit 单独提升为完整 A–E 结论。

| Scenario | Controls | completed / 15 repeats | telemetry 结果 | 结论 |
|---|---|---:|---|---|
| A Bare one-shot | verifier/gate/repair/CAS=false | 1/15 | 完成 repeat：2 calls、15,582 tokens、1,150.719s；其余失败 | 不完整 |
| B Bare staged | 预期全部 false，但无成功 metadata | 0/15 | telemetry unavailable | 不完整 |
| C Harness−Verifier | verifier=false，其余 true | 0/15 | mean 2 failed calls、0 tokens | 不完整 |
| D Harness−Repair | repair=false，其余 true | 0/15 | mean 2 failed calls、0 tokens | 不完整 |
| E Full Harness | verifier/gate/repair/CAS=true | 0/15 | mean 39.8 failed calls、0 tokens | 不完整 |

因此 run25 是一次真实可访问 runner、真实 vLLM、真实模型调用边界的 terminal failure evidence；它进一步证明“稳定 lease + 端口健康”可以让 campaign 启动，但不能保证长尾 A–E 完整执行。该结果不能宣称 Harness 收益，也不能将失败调用的 `0 tokens` 当成有效质量/成本比较。

当前 collector workflow 尚未进入默认分支，GitHub 对 `.github/workflows/integration-remote-collector.yml` 的手动 dispatch 返回 `404 workflow not found on the default branch`；因此 run25 的 terminal 失败证据已在远端保留，但尚无对应的 GitHub collector artifact。该缺口必须在将 collector 纳入默认分支后补齐，不能用提交 job 的 PASS 替代。

## 本机 direct campaign：manifest 已准备，空闲窗口不足

为验证“利用 vLLM 空闲窗口、但不强占 scheduler GPU”的运行权衡，在
`Jiayu-intern` 本机准备了与 GitHub submission 相同的 `7c90147` A–E
manifest：

```text
campaign: direct-20260929-1924
manifest: /data/models/harness4h3-v27-code/evidence/student-campaign/ai4mbse-campaigns/direct-20260929-1924/manifest.json
manifest_sha256: 12c445babdbe9ef24fa72668f7742b1bf617201d0539a244a7b40d0fb97083e6
command: --compare-a-e --path vertical --repeats 3 --timeout 5400 --benchmark-token-budget 8192 --comparison-mode natural
```

本次 manifest 初始化曾因远端 Python 进程启动后才设置 `PYTHONPATH` 而中断，
已修正并重新生成；当前目录没有 `status.json`、benchmark wrapper 或结果文件，
因此这不是一个实验 repeat，也不计入 A–E 结果。一次性 readiness waiter
（仅轮询 endpoint/lease，不写 scheduler marker）记录了：vLLM 在
`19:42:02`、`19:42:22`、`19:42:42` 连续 READY，随后在 `19:43:02` 回到
`WAIT:vllm-endpoint-unavailable`；六次 READY 门槛未达到，campaign 没有启动。

这次观察支持保守的运行策略：短暂的 `:8000` 健康或少量 READY 样本不足以
证明 A–E 可完成；降低稳定性门槛只会得到被 handoff 打断的 partial evidence，
不能替代完整的 `execution_complete=true` comparison。watcher 继续等待下一
个足够长的空闲窗口，失败或中断仍保持 fail-closed。

## 当前结论

v0.3.2 的实验边界、隔离规则、per-call/total 预算公平性、统计、统一 Coverage 语义和 CI 机制已经进入可审计状态；run16 证明在 vLLM 空闲且 Controller lease 稳定的窗口内，修复后的服务器本机可以真实跑完 A–E 的三次调度并生成完整 telemetry，但 comparison 仍因 D/E provider fail-fast、execution incomplete、cost unavailable 以及 Release Closure 结果为 `FAIL`，不能冒充 Harness 收益已被证明。空 enum schema bug 已在 `00a78db` 修复并通过 CI；run15/run16 共同说明真正的运行策略是“等待稳定空闲窗口、按 repeat 可恢复、失败原样保留”，而不是长期强占 GPU 或仅检查 `:8000`。当前 GitHub bridge 已通过 runner/SSH/FreeCAD/GPU 真实验收，A–E 仍需在下一次稳定 vLLM lease 窗口完成；第 14 项仍需要 scheduled event 的权威 run，第 15 项仍需要真实 remote LLM 的完整 A–E 质量/成本证据。

本地离线测试、contract job、skip 状态和 SSH 可达性检查都不能替代第 15 项的 GitHub integration evidence。
