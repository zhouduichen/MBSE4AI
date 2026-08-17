# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

MBSE 研究与工程实践者(系统工程师、研究团队),在本地跑 RFLP 流水线、查看需求模型与验证结果。界面语言为中文。

## Product Purpose

RFLP-Lite 是一个本地、确定性、可审计的 MBSE 研究原型:跑通 Artifact → Stakeholder/Concern/Need → Claim → R/F/L/P → Candidate → Simulation → Baseline → Delta → TaskContract → Evidence 的完整垂直链路,让需求到证据的每一步都有迹可查。

## Positioning

本地优先的确定性 MBSE 工具链:不依赖 Docker、GPU、外部服务,LLM 只是可选辅助;每个运行结果是可复现的哈希对照物(结果目录按 run hash 归档),而非黑箱输出。

## Operating Context

- 本地命令行 + Web 控制台(uvicorn 服务),工作区目录在磁盘上,SQLite 为事务真源;
- 用户创建工作区后,经过需求建模各页面进行输入、检查、补全、规划,再进入概念设计、项目验证、治理;
- 20+ 个页面模块:需求规划子页簇、概念设计、候选与权衡、仿真、基线与差异、任务契约、证据审计、LLM 设置;
- 页面交互依赖 htmx 局部刷新,无前端构建步骤。

## Capabilities and Constraints

- Python 3.11+,零前端构建(单 CSS + Jinja 模板 + htmx);
- 确定性启发式求解器与 OR-Tools CP-SAT 双实现;
- 功能冻结:本次为纯视觉重做,功能、路由、数据模型一律不动;
- "能力中心"为规划中占位。

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