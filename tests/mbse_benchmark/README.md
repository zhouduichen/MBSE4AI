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

当前验收基线使用 `RuleRuntime`，不读取用户的激活 LLM 配置；因此结果可离线重复。若要评估外部 LLM，应单独运行并保留 provider/model/配置记录，不得覆盖这份确定性基线。

## 三轨入口

Track A 是常规 CI 使用的确定性 Harness：

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py --track harness --repeats 3
```

Track B 必须显式指定 LLM profile；它会把 Harness + 同一模型与裸 LLM（同输入、无 workflow/gate/repair）分开记录：

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py --track llm --profile <profile-id> --case CASE-01
```

Track C 使用离线故障目录，单独报告检测、定位、修复和回归指标：

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py --track robustness
```

每条 Track 的报告都记录 track、runtime/profile/provider/model、methodology version、prompt/task-spec hash、commit、case 和 repeat；Track A 与 Track B 不共享总分。
