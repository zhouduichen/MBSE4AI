# 当前架构

## 产品主链路

```text
Project → Documents / Evidence → Operational → Functional
        → Logical / Physical → Assurance → Closure
        → Typed ModelGraph → Gate / Repair → View / Export
```

这是一个本地模块化单体：Python 3.11、SQLite、FastAPI/Jinja/HTMX，以及可选的 OpenAI-compatible Runtime。产品版本是 `0.2.0`，方法论协议是 `v2.1`。每个项目使用独立工作区和数据库，项目之间不共享模型或证据。

## 分层与依赖

```text
interface → application → methodology → domain
                         ↘ ports → runtime / repository
bootstrap → application + adapters
adapters → ports + domain
```

- `domain/`：Typed Entity、Relation、ModelGraph、Patch、Requirement 和稳定 ID；不依赖外层。
- `methodology/`：23 个 TaskSpec、版本化任务专属 Prompt、四个 Phase、Context/Retrieval、Schema/Validator/Retry、PatchPolicy、谓词感知 Gate/Coverage Matrix、局部 Repair 和 LifecycleOrchestrator。
- `application/`：Project、Analysis、Model、Evidence、Render、Settings 服务；只接收协议和工厂。
- `repository/`：SQLite ModelRepository v2，保存 Graph、Evidence、Run、Step、Patch、Revision、Issue、Closure 和 FTS，并提供 lease/heartbeat。
- `runtime/`：RuntimeFactory、结构化模型端口、OpenAI-compatible 适配和离线 RuleRuntime；每次运行动态解析 active profile。
- `adapters/`：文档解析、OCR 和模型/文档技术实现；由 `bootstrap/container.py` 组装。
- `interface/`：`ai4mbse` CLI、FastAPI Resource API 和五个资源页面。
- `tests/mbse_benchmark/tracks/`：Harness deterministic、显式 LLM/bare baseline、Agent robustness 三轨基准；各轨独立记录 runtime/profile/provider/model、方法论和哈希元数据。

## 写入与恢复规则

AI 或规则 Runtime 只返回结构化 TaskExecutionResponse。WorkflowRunner 将响应转换为局部 Patch，经实体字段、RelationPredicate、端点类型、状态、锁定标记和 expected revision 校验后提交。CAS 失败返回并发修改错误；`locked` 或 `user_modified` 的实体不能被自动覆盖。

每次运行拥有稳定 `run_id`、methodology/task spec/prompt version、profile/provider/model、input/context/output hash、步骤状态和诊断。恢复运行跳过已完成步骤；Gate 失败会写入 Issue，Repair 只能应用小范围本地 Patch，并重新执行最小任务和 Gate。一次未指定 phase 的运行按 Operational → Functional → Logical/Physical → Assurance → Global Gate → Closure 执行；指定 phase 仍可用于单阶段调试。

## 对外资源

| 资源 | 入口 |
|---|---|
| 项目 / 文档 | `POST /projects`、`POST /projects/{id}/documents` |
| 分析运行 | `POST /projects/{id}/analysis`、`GET /projects/{id}/analysis`、`GET /projects/{id}/runs/{run_id}` |
| 模型 | `GET /projects/{id}/model`、`GET /projects/{id}/entities` |
| 人工编辑 | `PATCH /projects/{id}/entities/{entity_id}` |
| 视图 / 导出 | `GET /projects/{id}/views/{view_id}`、`POST /projects/{id}/export` |
| 证据 / Issue | `GET /projects/{id}/evidence`、`GET /projects/{id}/issues`、`POST /projects/{id}/repair` |
| Trace / 配置 | `GET /projects/{id}/trace`、`/model-profiles`、`POST /model-profiles/test` |

## 质量门禁

仓库以 Golden fixture、领域/仓储/方法论/Runtime/API/E2E 测试、`compileall`、Import Linter 和架构预算作为验收基线。旧版智能发现、Concept/MDO、Project Bridge、测试执行、仿真、旧 Job/Baseline/TaskContract 和 MLflow 不属于 Core，已从主包和主测试集移除。
