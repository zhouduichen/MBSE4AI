# RFLP-Lite 本地最小垂直链路设计

**日期：** 2026-08-04  
**状态：** 已确认设计方向，待书面规格审核  
**目标环境：** macOS 本机、Python 3.11+、无需 Docker/GPU/外部数据库

## 1. 目标

先交付一个可以在当前文件夹中安装、运行和重复验证的 RFLP-Lite 研究原型。单条演示命令必须跑通以下闭环：

`Artifact -> TextSpan -> Claim -> R/F/L/P -> Candidate -> Simulation -> Baseline -> Delta -> TaskContract -> Evidence`

首轮目标是证明架构边界、数据流、错误保护和可重复运行均成立，而不是追求完整功能、图形界面或大模型效果。

## 2. 方案选择

采用“最小垂直链路 + 分阶段开源 Adapter”方案：

- 自建轻量 RFLP-Lite 领域内核和应用编排，不复制外部项目的数据模型。
- 开源项目通过 Python 依赖和受控 Adapter 接入，不批量克隆或 vendor 上游源码。
- 第一轮使用确定性规则抽取、启发式候选生成和内置仿真，确保离线可运行。
- 同时接入 OR-Tools CP-SAT 作为 Solver 的第二真实实现，验证 Port 可替换性。
- OpenAPI 和 JUnit 证据分别由 Prance、junitparser 解析，再转换为内部 DTO。
- LLM、复杂文档解析、实验平台和图形化 SysML 工具均保留扩展位置，但不阻塞首轮闭环。

没有选择“直接拼装多个上游仓库”，因为其领域模型、运行方式和依赖边界不一致，难以形成稳定的单一事务真源。没有选择“一次安装完整研究栈”，因为 Docling、sentence-transformers、MLflow、SysON 等组件会显著扩大首轮故障面，却不增加最小闭环的可验证性。

## 3. 架构

系统采用模块化单体和 Ports/Adapters：

- `domain`：标准库实现的领域对象、关系、不变量、Baseline 和 Evidence 规则。
- `application`：接入、编译、RFLP 构建、候选、决策、仿真、差异和任务生成用例。
- `ports`：Repository、ClaimExtractor、Solver、Analyzer 和 Exporter 的稳定 Protocol。
- `adapters`：SQLite、JSON、Python AST、Prance、junitparser、启发式 Solver 和 CP-SAT Solver。
- `simulation`：确定性事件队列、状态/资源更新、约束检查、轨迹和 Evidence 生成。
- `governance`：Profile、JSON Schema、架构依赖门禁、运行清单和审计记录。
- `interface`：本地 CLI；静态报告只输出 JSON/Markdown，暂不建设 Web UI。

领域层不依赖数据库、HTTP、LLM、Pydantic 或第三方解析器。第三方库返回的数据必须先在 Adapter 中转换为内部 DTO，之后才能进入应用层。

## 4. 数据与事务真源

SQLite 是本地事务真源，JSON 用于契约、配置、演示输入和导出。数据库至少保存：

- Artifact、TextSpan、Claim、ModelElement、Relation；
- Candidate、Decision、SimulationCase、SimulationRun；
- Baseline、BaselineMember、ChangeRequest；
- TaskContract、VerificationCase、Evidence、AuditEvent。

Baseline 采用追加式版本：外部解析器、Solver 或仿真失败时不得修改已批准 Baseline。每次运行记录输入哈希、Profile、seed、组件版本、结果哈希和失败信息。

## 5. 首轮演示数据流

参考项目使用文档建议的 `VersionedContentService`：保存内容版本、恢复历史版本、记录审计事件并提供查询接口。

1. `rflp init demo-project` 初始化目录、SQLite 和默认 Profile。
2. `rflp demo --seed 42` 接入示例 Markdown、OpenAPI JSON 和 JUnit XML。
3. 结构化 Reader 创建 Artifact 与 TextSpan。
4. RuleClaimExtractor 生成原子 Claim；Schema 与领域不变量拒绝非法输出。
5. 应用服务构建最小 R/F/L/P 元素与正式关系。
6. HeuristicSolver 生成 2-3 个架构候选；CpSatSolverAdapter 对相同输入执行第二实现。
7. 确定性仿真运行状态转换、资源约束和一个故障注入场景。
8. 决策服务根据固定权重产生 Decision 和 Baseline proposal，经本地显式批准步骤形成 Baseline。
9. Python AST、OpenAPI 和 JUnit 解析形成 ActualModel/Evidence，与 Baseline 求差。
10. Delta 生成带读写集合、不变量和验收证据要求的 TaskContract DAG。
11. CLI 输出 run manifest、候选、轨迹、Baseline、Delta、TaskContract 和 Evidence 摘要。

## 6. 开源组件边界

首轮实际安装：

- 开发与治理：Import Linter、Hypothesis、check-jsonschema；
- Schema：jsonschema；
- 证据接入：Prance、junitparser；
- 优化求解：OR-Tools CP-SAT。

Python 运行时继续以标准库、SQLite 和 JSON 为核心。RapidFuzz、Pydantic、Instructor、httpx、Ollama/llama.cpp、OpenAPI-core 与 python-docx 只保留 optional dependency 分组和能力探测，不作为首轮演示前置。Docling、SimPy、NetworkX、sentence-transformers、MLflow、SysON 与 Pluggy 暂不安装。

## 7. 错误处理与稳定性

- 所有 CLI 错误返回非零退出码，并给出阶段、输入和可恢复建议。
- Adapter 将第三方异常转换为稳定的内部错误类型，禁止供应商异常穿透领域层。
- Solver 设置固定 seed、候选上限和时间上限；超时返回受控失败记录。
- Schema、领域不变量或证据校验失败时，中止当前变更并保持 Baseline 哈希不变。
- 每次演示从固定 fixture 建立独立工作目录，允许重复运行且输出可比较。
- 数据库写入使用事务；失败时回滚并追加审计事件。

## 8. 测试与门禁

测试采用 pytest 和 Hypothesis，至少覆盖：

- 领域对象序列化往返、关系合法性和 Baseline 不可变性；
- Patch 幂等、TaskContract DAG 无环、仿真事件稳定排序；
- ClaimExtractor、Solver、Repository 和 Analyzer 的契约测试；
- Prance、junitparser 和 CP-SAT Adapter 的 fixture 集成测试；
- 外部组件超时、崩溃或非法输出后的 Baseline 哈希保护；
- Import Linter 的分层和禁止依赖契约；
- core-only 安装、完整 extras 安装和 `rflp demo --seed 42` 冒烟测试。

固定 seed 和固定 fixture 下，第二次运行的规范化 JSON 结果及关键哈希必须与第一次一致。

## 9. 本地部署与使用

项目采用 `src/` 布局和 `pyproject.toml`。本地部署流程为：创建项目专用虚拟环境、以 editable 模式安装 core 与 `dev,evidence,opt` extras、执行 Schema/架构/单元测试、初始化演示项目、运行完整 demo。

首轮不启动常驻服务。部署成功意味着 CLI 和 SQLite 数据可以离线工作；将来增加 Ollama 或 API 时仍通过 Port/Profile 选择，不改变核心命令和领域模型。

## 10. 验收标准

以下条件全部满足才算“本地链路已跑通”：

1. 干净虚拟环境可安装，且不需要 Docker、GPU、PostgreSQL 或网络服务。
2. `rflp demo --seed 42` 一次完成完整链路并返回退出码 0。
3. 输出至少包含 1 个已批准 Baseline、2 个 Candidate、1 条仿真轨迹、1 个 DeltaSet、1 个 TaskContract DAG 和对应 Evidence。
4. Heuristic 与 CP-SAT Solver 均通过相同契约测试并可由 Profile 切换。
5. 注入 Adapter 失败后，命令受控失败且 Baseline 哈希不变。
6. 单元、性质、契约、集成、架构和安装冒烟测试全部通过。
7. 同一 fixture、Profile 和 seed 的重复运行产生相同规范化结果和关键哈希。

## 11. 首轮不做

- Web UI、完整 SysML 图形编辑器或在线 SysML v2 仓库；
- LLM 自动批准需求、模型元素或 Baseline；
- PDF/PPTX 高保真解析、向量检索、模型训练和 MLOps 平台；
- 插件市场、远程 Runtime、万能 Hook 总线和多数据库部署；
- 将上游项目源码批量复制到本仓库。

