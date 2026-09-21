# AI4MBSE MBSE Benchmark

这是针对当前 AI4MBSE Harness 的真实应用链路验收测试。它不把 `expected/` 当作系统输出，而是把五个案例导入独立工作区，调用真实的 `ProjectService`、`AnalysisService`、`WorkflowRunner` 和 SQLite `ModelGraph`，然后验证真实产物。

## 执行

使用离线确定性 Runtime：

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py --repeats 3 --timeout 60
```

运行单个案例：

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py --case CASE-05 --repeats 3
```

测试基础设施自身：

```bash
./.venv/bin/python -m pytest tests/mbse_benchmark -q
./.venv/bin/ruff check tests/mbse_benchmark
```

## 案例与状态

- `CASE-01`：宿舍智能门锁。
- `CASE-02`：校园自动售货机。
- `CASE-03`：校园无人配送车完整生命周期。
- `CASE-04`：园区巡检无人机约束与安全。
- `CASE-05`：故意注入 32 kg 重量和 5 h 续航冲突。

结果状态含义：

- `PASS`：观察到的真实结果满足该检查。
- `FAIL`：观察到真实结果，但不满足检查。
- `NOT_IMPLEMENTED`：当前产品模型没有对应能力，不能伪造通过。
- `BLOCKED`：执行超时或无法产生可验证产物。

CASE-05 的 P0 检查必须观察到产品产物明确发现：`32 kg > 20 kg` 和 `1000 Wh / 200 W = 5 h < 12 h`。测试 harness 可以计算已知约束，但只有真实 issues、diagnostics 或模型失败信号出现时才计为检测通过。

## 产物

每次案例运行保存到 `results/case_xx/repeat_nn/`，包括输入、运行摘要、Run Ledger、ModelGraph、Issues、Audit 和执行状态。正式报告位于：

```text
reports/benchmark_report.md
reports/metrics.json
reports/failures.json
reports/traceability_report.md
```

Coverage 使用三态语义：非空范围为 `PASS`/`FAIL`，空范围为 `N/A`，序列化为 `status: "not_applicable"`、`coverage: null`，不能把零需求当成 100%。

## 入口

Track A 是常规 CI 使用的确定性 Harness：

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py --track harness --repeats 3
```

Track B 必须显式指定 LLM profile。A–E 对照会对同一输入使用同一 provider/model、同一个 ModelGraph normalizer 和同一个 external evaluator：

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py --track llm --profile <profile-id> --compare-a-e --case CASE-01
```

五个场景的含义是：A Bare one-shot，B Bare staged，C Harness without verifier，D Harness without repair，E Full Harness。A/B 的模型输入只包含 system brief、stakeholders、lifecycle 和 scenarios，不包含 `expected/` 内容；缺少显式 profile 时 A/B 会失败，而不会构造 ground-truth graph。

每次场景保存 `metadata.json`，包括 scenario、model、provider、prompt/task-spec/input hash、temperature、token usage、latency、graph hash 以及 verifier/repair/CAS 开关。比较报告位于 `reports/llm/<profile-id>/a_to_e_comparison.{json,md}`。

Track C 使用临时 SQLite ModelRepository 和真实 WorkflowRunner lease/CAS 边界注入故障，经过 Gate/外部 Verifier 检测、最小修复和重跑后，单独报告检测、定位、修复和回归指标：

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py --track robustness
```

每条运行都记录 track、runtime/profile/provider/model、prompt/task-spec/input hash、commit、case 和 repeat；真实远程 LLM、FreeCAD 和 GPU 测试不进入普通 CI，而由 `.github/workflows/integration.yml` 手动或 nightly 触发。
