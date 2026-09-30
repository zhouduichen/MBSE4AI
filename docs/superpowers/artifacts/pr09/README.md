# PR09 Contract Conformance Artifacts

该目录保存 Structured Output Boundary 的逐样本 conformance 结果。

运行本地 fixture smoke test：

```bash
./.venv/bin/python -m tests.contract_conformance.runner --repetitions 1
```

运行真实 Ollama `qwen3.5:9b-q8_0` 的 3 Task × 20 次测试：

```bash
RFLP_RUN_LIVE_LLM=1 ./.venv/bin/python -m tests.contract_conformance.runner --repetitions 20 --live
```

结果包含 `provider_success_rate`、`json_parse_rate`、`schema_pass_rate`、`proposal_compile_rate`、`domain_validation_rate`、`first_pass_success_rate`、`structural_retry_rate`、`retry_recovery_rate`、`semantic_rejection_rate`、`blocked_count`、`mean_output_tokens`、`mean_latency_ms`，以及 `status_counts`、`failure_stage_counts`、`finish_reason_counts` 和每个样本的 prompt/schema metadata、诊断与 retry ledger。

Runner 会在每个样本开始/结束时打印进度，并将 partial report checkpoint 到结果文件；Ollama live benchmark 默认把单请求 timeout 收紧为 60 秒，可用 `PR09_LIVE_TIMEOUT_SECONDS` 调整。Ollama structural repair 请求复用 provider-level `format` 约束，不再把完整 schema 再塞进 repair prompt。

`run-07efa6e07f0a6b14` 的回归 manifest 位于 `tests/contract_conformance/fixtures/`。旧数据库保留原状；如果旧运行没有完整 raw response，manifest 不会虚构内容。
