# 当前架构

## 产品主链路

```text
自然语言 / 文档 → Requirements → Functional → Logical → Physical → V&V
               → Typed ModelGraph → SysML v2 subset / 可编辑模型
```

这是一个本地模块化单体：Python 3.11、SQLite、FastAPI/Jinja/HTMX，以及可选的 OpenAI-compatible Runtime。产品版本是 `0.2.0`，方法论协议是 `v2.1`。每个项目使用独立工作区和数据库，项目之间不共享模型或证据。旧 23-task WorkflowRunner 仍存在，但只承担兼容和单阶段调试职责。

## 分层与依赖

```text
interface → application → methodology → domain
                         ↘ ports → runtime / repository
bootstrap → application + adapters
adapters → ports + domain
```

- `domain/`：Typed Entity、Relation、ModelGraph、Patch、Requirement 和稳定 ID；不依赖外层。
- `methodology/`：五个产品级 `VerticalStage` 合约和阶段 Prompt；23 个细粒度 TaskSpec、四个 Phase、Context/Retrieval、Schema/Validator/Retry、PatchPolicy、谓词感知 Gate/Coverage Matrix、局部 Repair 和 LifecycleOrchestrator 保留为兼容/调试能力。
- `application/`：Project、ModelGeneration、Analysis、Model、Evidence、Render、Settings 服务；`ModelGenerationService` 负责五阶段纵向编排和追溯摘要。
- `repository/`：SQLite ModelRepository v2，保存 Graph、Evidence、Run、Step、Patch、Revision、Issue、Closure 和 FTS，并提供 lease/heartbeat。
- `runtime/`：RuntimeFactory、结构化模型端口、OpenAI-compatible 适配和离线 RuleRuntime；每次运行动态解析 active profile。
- `adapters/`：文档解析、OCR 和模型/文档技术实现；由 `bootstrap/container.py` 组装。
- `interface/`：`ai4mbse` CLI、FastAPI Resource API 和五个资源页面；默认 Analysis 操作调用 `ModelGenerationService`，旧 `pipeline/phase` 仍可显式调用。
- `tests/mbse_benchmark/tracks/`：Harness deterministic、显式 LLM/bare baseline、Agent robustness 三轨基准；各轨独立记录 runtime/profile/provider/model、方法论和哈希元数据。

## 写入与恢复规则

AI 或规则 Runtime 只返回结构化 TaskExecutionResponse。WorkflowRunner 将响应转换为局部 Patch，经实体字段、RelationPredicate、端点类型、状态、锁定标记和 expected revision 校验后提交。CAS 失败返回并发修改错误；`locked` 或 `user_modified` 的实体不能被自动覆盖。

每次运行拥有稳定 `run_id`、methodology/task spec/prompt version、profile/provider/model、input/context/output hash、步骤状态和诊断。纵向生成运行按 Requirements → Functional → Logical → Physical → V&V 顺序提交阶段 Patch，并计算每条 Requirement 的完整/部分/缺失追溯。生成的 LLM 实体进入可编辑的 `validated` 状态，人工仍可通过既有 Review/Edit/Lock 入口接管。旧 WorkflowRunner 的 Gate、Repair、Closure 状态机不驱动默认产品路径。

## 对外资源

| 资源 | 入口 |
|---|---|
| 项目 / 文档 | `POST /projects`、`POST /projects/{id}/documents` |
| 分析运行 | `POST /projects/{id}/analysis`（默认五阶段生成；`mode=pipeline/phase` 为兼容入口）、`GET /projects/{id}/analysis`、`GET /projects/{id}/runs/{run_id}` |
| 模型 | `GET /projects/{id}/model`、`GET /projects/{id}/entities` |
| 人工编辑 | `PATCH /projects/{id}/entities/{entity_id}` |
| 视图 / 导出 | `GET /projects/{id}/views/{view_id}`、`POST /projects/{id}/export`、`POST /projects/{id}/sysml/import` |
| 证据 / Issue | `GET /projects/{id}/evidence`、`GET /projects/{id}/issues`、`POST /projects/{id}/repair` |
| Trace / 配置 | `GET /projects/{id}/trace`、`/model-profiles`、`POST /model-profiles/test` |

## 质量门禁

仓库以 Golden fixture、领域/仓储/方法论/Runtime/API/E2E 测试、`compileall`、Import Linter 和架构预算作为验收基线。旧版智能发现、Concept/MDO、Project Bridge、测试执行、仿真、旧 Job/Baseline/TaskContract 和 MLflow 不属于 Core，已从主包和主测试集移除。
