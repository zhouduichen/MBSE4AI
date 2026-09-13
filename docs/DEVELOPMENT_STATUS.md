# 开发状态

**更新时间：** 2026-09-13
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
| 默认产品纵向生成 | 自然语言或已解析文档 → Requirements → Functional → Logical → Physical → V&V；五阶段写入同一 ModelGraph，并返回阶段结果、追溯摘要和 SysML 文本 |
| LLM 五阶段接入 | 每个纵向阶段通过现有 StructuredModelRuntime 的 TaskProposal → Compiler → Patch 边界执行；测试覆盖五次真实 stage lens 调用 |
| SysML v2 子集往返 | 导出实际 `part/requirement/action/interface/verification/validation` 声明及关系元数据；可重新读入新项目并继续编辑 |
| 产品验收指标 | 以 R→F→L→P→V&V 完整追溯、SysML 往返和 ModelGraph 编辑为主，不再以 23-task 重复运行次数作为主进度指标 |

## 历史 Harness 验收边界

| 检查项 | 当前状态 |
|---|---|
| Model connectivity | PASS |
| Native Ollama invocation | PASS |
| Structured MBSE contract | PASS（60/60 provider success；58/60 structural/schema/compile/domain pass） |
| Full 23-task LLM lifecycle | NOT ACCEPTED；该入口保留为兼容/调试路径，不是默认产品生成路径 |

PR09 的 conformance runner 位于 `tests/contract_conformance/`，默认使用离线 fixture；真实 Ollama 测试必须显式设置 `RFLP_RUN_LIVE_LLM=1`。最终 3 Task × 20 结果为：provider/JSON/schema/compile/domain 均 58/60，2 次 structural retry 未恢复。该结果仅说明结构化边界已有基础覆盖，不能替代新的五阶段产品链验收。

最终 live artifact：`docs/superpowers/artifacts/pr09/contract-conformance-1789049206566817000.json`。新的主验收位于 `tests/e2e/test_vertical_model_generation.py`、`tests/application/test_model_generation.py` 和 `tests/interface/test_cli_v2.py`。

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
