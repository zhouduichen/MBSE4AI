# 开发状态

**更新时间：** 2026-09-08
**产品版本：** rflp-lite 0.1.0
**方法论协议：** v2.0

## 已完成

| 能力 | 验收口径 |
|---|---|
| Typed ModelGraph | 统一实体、关系、生命周期、来源、证据和稳定 ID |
| Repository v2 | SQLite 事务、CAS Revision、Run/Step/Patch/Issue 台账、FTS |
| 四阶段方法论 | Operational、Functional、Logical/Physical、Assurance 加 Closure，共 23 个任务 |
| 结构化 Runtime | 离线 RuleRuntime 可运行；OpenAI-compatible Runtime 走严格 JSON 契约 |
| Gate / Repair | 覆盖率、语义、RFLP、证据、验证门禁；失败写 Issue，修复受 PatchPolicy 局部约束并定向重新 Gate |
| 生命周期闭环 | 单次调用串联四阶段、Global Gate、Closure manifest、冻结 revision 和审计摘要；指定 phase 保留调试入口 |
| 运行可追溯 | active profile/provider/model、TaskSpec/prompt/context/input/output hash、step ledger、lease/heartbeat |
| 资源服务 | Project、Analysis、Model、Evidence、Render、Settings 服务及统一依赖组装 |
| CLI / Web | `ai4mbse` 命令、完整 Analysis 工作流页、Trace 页、连接测试和 JSON/SVG/DOT/SysML-lite 导出 |
| 文档接入 | TXT、Markdown、DOCX、PDF 解析；扫描 PDF 使用可选 OCR 适配器 |
| Golden E2E | 校园无人配送机器人 fixture 可导入并跑完整阶段；失败与锁定保护可验证 |

## 当前验收命令

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall -q src
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/lint-imports
```

## 明确边界

本版本聚焦可复现的需求到模型垂直链路。旧版智能发现、Concept/MDO、Project Bridge、测试执行沙箱、仿真、旧 Baseline/TaskContract/Job 和 MLflow 已退出 Core；复杂文档版面、多人权限、CAD/真实工程仿真留作后续独立能力。
