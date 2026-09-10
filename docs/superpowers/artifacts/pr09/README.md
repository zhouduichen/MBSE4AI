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

结果包含 `json_parse_rate`、`schema_pass_rate`、`proposal_compile_rate`、`domain_validation_rate`、`first_pass_success_rate` 和 `structural_retry_rate`，以及每个样本的 prompt/schema metadata、诊断与 retry ledger。

`run-07efa6e07f0a6b14` 的回归 manifest 位于 `tests/contract_conformance/fixtures/`。旧数据库保留原状；如果旧运行没有完整 raw response，manifest 不会虚构内容。
