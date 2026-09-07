# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

MBSE 研究与工程实践者(系统工程师、研究团队),在本地跑 RFLP 流水线、查看需求模型与验证结果。界面语言为中文。

## Product Purpose

RFLP-Lite 是一个本地、确定性、可审计的 AI4MBSE Domain Harness:跑通 Project → Documents/Evidence → Operational → Functional → Logical/Physical → Assurance → ModelGraph → Gate/Repair → View/Export 的完整生命周期链路,让每个方法论任务到证据的每一步都有迹可查。

## Positioning

本地优先的确定性 MBSE 工具链:不依赖 Docker、GPU、外部服务,LLM 只是可选辅助;每个运行结果是可复现的哈希对照物(结果目录按 run hash 归档),而非黑箱输出。

## Operating Context

- 本地命令行 + Web 控制台(uvicorn 服务),工作区目录在磁盘上,SQLite 为事务真源;
- 用户创建项目后,经过文档/证据接入、四阶段方法论、Gate 检查和局部修复，进入模型查看与导出;
- 5 个一级页面:Projects、Analysis、MBSE Model、Evidence & Issues、Settings;
- 页面交互依赖 htmx 局部刷新,无前端构建步骤。

## Capabilities and Constraints

- Python 3.11+,零前端构建(单 CSS + Jinja 模板 + htmx);
- AI4MBSE Core 不包含 Concept/MDO、Project Bridge/Test Runner、旧 Simulation/Baseline/TaskContract 或 MLflow；这些能力只能作为独立插件/研究 extra 恢复;
- ModelGraph 是模型唯一真源，AI 只能通过 Validate 后的 Patch 写入；图、矩阵和 SysML 都是 View/Export;
- Web Search 为 optional，外部证据缺失不终止 Workflow。

## Brand Commitments

- 产品名 RFLP-Lite,LOCAL CONSOLE/LOCAL WORKSPACE 定位;
- 本地优先、确定性、可审计的信任基调;
- 中文界面。

## Evidence on Hand

examples/ 下有演示工作区与样例;docs/ 有状态文档与设计文档。

## Product Principles

1. 本地优先:一切可离线运行,结果可复现。
2. 确定性:运行结果按哈希归档,差异可见。
3. 可审计:基线、契约、证据是显式对象。
4. LLM 是助手,不是口径:发现与补全结果进入人工确认流。
5. 研究原型务实演进:先垂直打通,再横向扩展。

## Accessibility & Inclusion

界面默认中文;键盘可达、语义化标签已在本轮视觉重做范围内保持。
