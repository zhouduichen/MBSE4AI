# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

MBSE 研究与工程实践者(系统工程师、研究团队),在本地跑 RFLP 流水线、查看需求模型与验证结果。界面语言为中文。

## Product Purpose

RFLP-Lite 是一个由 LLM 驱动、确定性校验、可审计的 AI4MBSE 工程工作台:跑通 Project → Documents/Evidence → Operational → Functional → Logical/Physical → Assurance → ModelGraph → Gate/Repair → View/Export 的完整生命周期链路,让 AI Systems Engineer 能把自然语言、文档和已有模型转成可继续编辑的 MBSE 模型。

## Positioning

LLM-first 的 MBSE 工具链:配置 Profile 后由 LLM 主导需求到模型的纵向生成，确定性 Methodology/Validator/ModelGraph 负责约束、追溯和审计；无模型时保留离线 RuleRuntime 作为开发回归和可复现兜底。每个运行结果都记录实际 profile/provider/model 与哈希对照物，而不是黑箱输出。

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
- LLM 驱动、确定性、可审计的信任基调;
- 中文界面。

## Evidence on Hand

examples/ 下有演示工作区与样例;docs/ 有状态文档与设计文档。

## Product Principles

1. 纵向闭环优先:先完成 R→F→L→P→V&V，再扩展横向基础设施。
2. 确定性:运行结果按哈希归档,差异可见。
3. 可审计:基线、契约、证据是显式对象。
4. LLM 是 Systems Engineering Controller:负责分析、补全和提出方案，工程事实与方案选择经过验证和人工确认流。
5. 研究原型务实演进:先垂直打通,再横向扩展。

## Accessibility & Inclusion

界面默认中文;键盘可达、语义化标签已在本轮视觉重做范围内保持。
