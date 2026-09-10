# 开发状态

**更新时间：** 2026-09-10
**产品版本：** rflp-lite 0.2.0
**方法论协议：** v2.1

## 已完成

| 能力 | 验收口径 |
|---|---|
| Typed ModelGraph | 统一实体、关系、生命周期、来源、证据和稳定 ID |
| Repository v2 | SQLite 事务、CAS Revision、Run/Step/Patch/Issue 台账、FTS |
| 四阶段方法论 | Operational、Functional、Logical/Physical、Assurance 加 Closure，共 23 个任务 |
| 结构化 Runtime | 离线 RuleRuntime 可运行；OpenAI-compatible Runtime 走 TaskProposal→Compiler→Patch 边界 |
| Gate / Repair | 覆盖率、语义、RFLP、证据、验证门禁；失败写 Issue，修复受 PatchPolicy 局部约束并定向重新 Gate |
| 生命周期闭环 | 单次调用串联四阶段、Global Gate、Closure manifest、冻结 revision 和审计摘要；指定 phase 保留调试入口 |
| 运行可追溯 | active profile/provider/model、TaskSpec/prompt/context/input/output hash、step ledger、lease/heartbeat |
| 方法论智能化重构 | 23 个独立版本化 Prompt、可执行 Validator、谓词感知 Coverage Matrix、局部语义 Repair、Completion/Failure DSL、分层 Context Planner |
| Benchmark 三轨 | Harness deterministic、显式 LLM + same-model bare baseline、Agent robustness faults 分开运行和报告，不共享总分 |
| 资源服务 | Project、Analysis、Model、Evidence、Render、Settings 服务及统一依赖组装 |
| CLI / Web | `ai4mbse` 命令、完整 Analysis 工作流页、Trace 页、连接测试和 JSON/SVG/DOT/SysML-lite 导出 |
| Web 主流程入口 | `/` 重定向到项目列表；分析页支持需求文本和文档上传；无输入项目禁止运行分析并在页面禁用运行按钮 |
| Web 运行配置 | 设置页支持保存模型配置、激活已有配置和连接测试；API Key 不进入页面或公开响应 |
| 文档接入 | TXT、Markdown、DOCX、PDF 解析；扫描 PDF 使用可选 OCR 适配器 |
| Golden E2E | 校园无人配送机器人 fixture 可导入并跑完整阶段；失败与锁定保护可验证 |

## PR09 Structured Output 验收边界

| 检查项 | 当前状态 |
|---|---|
| Model connectivity | PASS |
| Native Ollama invocation | PASS |
| Structured MBSE contract | PASS（60/60 provider success；58/60 structural/schema/compile/domain pass） |
| Full LLM lifecycle | NOT ACCEPTED |

PR09 的 conformance runner 位于 `tests/contract_conformance/`，默认使用离线 fixture；真实 Ollama 测试必须显式设置 `RFLP_RUN_LIVE_LLM=1`。最终 3 Task × 20 结果为：provider/JSON/schema/compile/domain 均 58/60，2 次 structural retry 未恢复；这证明结构化边界达到初始验收线，但仍不把连接成功或局部 conformance 结果等同于完整生命周期成功。

最终 live artifact：`docs/superpowers/artifacts/pr09/contract-conformance-1789049206566817000.json`。本轮未运行 23-task lifecycle；待 structural retry recovery 和完整生命周期继续验收。

## 当前验收命令

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall -q src
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/lint-imports
```

## 明确边界

本版本聚焦可复现的需求到模型垂直链路。旧版智能发现、Concept/MDO、Project Bridge、测试执行沙箱、仿真、旧 Baseline/TaskContract/Job 和 MLflow 已退出 Core；复杂文档版面、多人权限、CAD/真实工程仿真留作后续独立能力。

Track B 需要显式配置 profile，不能在无密钥 CI 中默认运行：

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py --track llm --profile <profile-id>
```
