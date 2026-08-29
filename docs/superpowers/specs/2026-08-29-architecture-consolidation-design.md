# RFLP-Lite Architecture Consolidation 设计

**日期：** 2026-08-29  
**状态：** 设计已获批准，进入实施计划阶段  
**适用范围：** 当前 RFLP-Lite 代码库  
**架构形态：** Local-first Modular Monolith

## 1. 目标与边界

本次工作完成现有新旧架构的迁移闭环，不重写产品，不引入微服务或新的基础设施边界。外部兼容约束为：现有 Web 路由、CLI 命令和参数、成功响应形状、模板语义、工作区目录布局、既有 SQLite Workbench 数据和历史修订记录继续可用。

允许改变内部 Python 模块、Domain 类型、Port 接口和 Application 组织方式。当前工作区已有未提交改动属于用户改造基线，实施过程必须保留，不得覆盖或回退。

非目标：微服务、PostgreSQL、Redis、Celery、Kafka、全量 ORM、Event Sourcing、前端框架重写、复杂 DI Framework、真实不可信代码安全沙箱，以及与结构迁移无关的 MBSE/LLM 算法调整。

## 2. 目标架构

```text
Interface: FastAPI / Jinja / HTMX / CLI
        ↓ Command / Query DTO
Application: Requirements / Intelligence / System Model /
             Verification / Concept / Workspace / Integration
        ↓ Mutation / Query / Narrow Port
Workbench Kernel: Snapshot / CAS / Commit / Audit / Trace / Ledger
        ↓
Domain + Ports: typed entities, rules, contracts
        ↓
Adapters: SQLite / LLM / Documents / Diagrams / Tests / MLflow
```

Bootstrap 是唯一 Composition Root，负责构建 Infrastructure、窄依赖、Use Case、Query 和 Interface 所需的 Application API。`AppServices` 只能存在于 Bootstrap/Interface 组装边界，不能作为 Application 内部的万能依赖。

业务边界及所有权如下：

| 边界 | 核心职责 |
|---|---|
| Workspace | 工作区定位、创建、隔离和元信息 |
| Requirements | Stakeholder、Concern、Need、Requirement、Scenario 的生命周期和人工修改 |
| Intelligence | Block 分析、Schema、语义校验、Coverage、Reconciliation |
| System Model | RFLP、MBSE、Sequence、View Projection |
| Verification | 项目扫描、Baseline、Delta、Task、Evidence、Test orchestration |
| Concept Design | Scheme、Layout、Discipline、Optimization |
| Integration | LLM Profile、MLflow、Plugin、Interchange |
| Workbench Kernel | Snapshot、版本、CAS、事务、Audit、Trace、Requirement Ledger |

业务子系统决定“改什么”，Workbench Kernel 决定“如何安全、原子地提交”。

## 3. Workbench Mutation Kernel

新增 `application/workbench/`，包含 `snapshot.py`、`mutation.py`、`commit.py` 和 `queries.py`。

初期不强制全量类型化 Workbench，使用兼容快照承载历史 JSON：

```python
@dataclass(frozen=True, slots=True)
class WorkbenchSnapshot:
    workspace: str
    revision: int
    content_revision: int
    input_hash: str
    state: Mapping[str, object]
```

Snapshot 对调用方按只读语义使用；Mutation 必须生成独立 working copy 或 typed aggregate，禁止调用方在事务外修改并保存快照。

统一写入协议为：

```text
Command
  ↓
Use Case
  ↓
Mutation
  ↓
WorkbenchCommitCoordinator
  ↓
Repository transaction + CAS
```

`WorkbenchCommitCoordinator` 只负责：读取 Snapshot、检查版本、执行 Mutation、统一 normalize/staleness/trace、更新 Requirement Ledger、写 Audit、CAS 保存并提交事务。实体生成规则仍由 Requirements、Intelligence 或 System Model 模块负责，Coordinator 不得演化成新的业务 God Service。

```python
class MutationKind(StrEnum):
    HUMAN_CONTENT = "human_content"
    GENERATED_CONTENT = "generated_content"
    DERIVED_MODEL = "derived_model"
    METADATA = "metadata"

@dataclass(frozen=True, slots=True)
class MutationResult:
    state: dict[str, object]
    changed_ids: tuple[str, ...] = ()
    invalidated_sections: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    mutation_kind: MutationKind = MutationKind.HUMAN_CONTENT
```

第一阶段只统一 transaction、save、Audit、Trace 和 Ledger，不接管 `content_revision` 的自动递增，避免与遗留 `advance_content_revision()` 双重递增。全部人工 Mutation 迁入后，才把 `content_revision` 的所有权移入 Kernel 并删除旧增量逻辑。

## 4. Revision、CAS 与 Job 新鲜度

`revision` 表示每次成功持久化的 Workbench 版本；`content_revision` 表示用户可编辑的工程语义版本。

- 用户编辑、审核、删除、恢复、输入变更：递增两者。
- LLM Block 自动合并、派生 RFLP/MBSE、Job heartbeat/progress：只递增 `revision`。
- 新写 Use Case 必须携带 `expected_revision`。
- 兼容入口可以暂时省略 expected revision，但不得被新代码调用。
- CAS 使用 `UPDATE ... WHERE id='current' AND revision=?`，更新数量不是 1 时抛出 `ConcurrentModificationError`。
- 初次创建以 `expected_revision=0` 保护并发初始化。
- 首版采用严格 CAS，不做隐式 rebase。

LLM Job 同时保存 `snapshot_revision`、`snapshot_content_revision` 和 `input_hash`。每个 Block 提交时使用最新 Workbench revision 做 CAS，但必须确认当前 `content_revision` 仍等于 Job 快照；用户编辑后，后续 Block 标记为 `SUPERSEDED`，不再合并。

Command 只描述意图，不接收前端携带的完整旧状态：

```python
@dataclass(frozen=True, slots=True)
class ReviewRequirementCommand:
    workspace: str
    requirement_id: str
    decision: ReviewDecision
    comment: str | None
    expected_revision: int
```

## 5. 依赖注入与 Repository

最终删除 `_DEFAULT_DEPENDENCIES`、`require_dependencies()` 和 `configure_default_dependencies()`。迁移期间使用 `architecture_budget.json` 记录遗留数量，当前基线约为 25，后续只能下降。

新 Application Use Case 只接收窄 Port/Policy。先拆 Protocol，再拆 SQLite 实现；过渡期一个 `SQLiteRepository` 可以实现多个窄 Protocol：

```text
WorkbenchRepositoryPort
RequirementLedgerPort
TraceRepositoryPort
AuditRepositoryPort
EvidenceRepositoryPort
ConceptRepositoryPort
RunRepositoryPort
JobRepositoryPort
```

删除 `repository_method()` 字符串反射 escape hatch。新代码禁止 Application 导入 Adapter、读取 `RFLP_*` 环境变量、访问 `sqlite3` 或调用 `subprocess`。

## 6. SQLite Migration 与 Job

SQLite 是唯一运行时持久化真源。新增版本化 `schema_migrations`，Migration 在 `BEGIN IMMEDIATE` 内执行、验证并记录版本；失败回滚。需要重建表或转换不可逆格式时，在迁移前创建不覆盖既有备份的 `model.db.bak` 或带时间戳备份。

Workbench 现有 JSON 快照继续可读，Mapper 对缺失字段填充兼容默认、保留未知扩展字段，写回使用 canonical schema。

Job 运行时迁移为 SQLite `jobs` 与 `job_blocks`：

```text
jobs: id, kind, workspace, status, idempotency_key,
      snapshot_revision, snapshot_content_revision, input_hash,
      attempt, lease_id, lease_expires_at, heartbeat_at,
      payload, result, last_error, created_at, updated_at

job_blocks: job_id, block_id, status, attempt, input_hash,
            output_hash, started_at, finished_at, diagnostics
```

Job 状态唯一为：`queued`、`running`、`succeeded`、`degraded`、`failed`、`interrupted`、`superseded`、`cancelled`；历史 `completed` 只在导入时转换为 `succeeded`。不再同时维护 `blocks` 与 `block_states` 两套运行状态。

Application 只依赖 `JobRepositoryPort` 和 `BackgroundExecutorPort`；线程实现移动到 `ThreadBackgroundExecutor` Adapter。执行语义明确为 at-least-once execution + idempotent semantic commit，不宣称 exactly-once。

旧 `.rflp/jobs.json` 只做一次性导入：解析、归一化、事务写入、重新读取核对数量/ID/状态后改名为 `jobs.legacy.json`。失败时回滚且保持原名，不进行双写。

## 7. Typed LLM、Requirements 与 MBSE

六个 LLM Block 分别定义 Item DTO，例如 `StakeholderItem`、`RequirementItem`、`ScenarioItem`、`ArchitectureEntityItem` 和 `ArchitectureRelationItem`。链路为：

```text
LLM response
  → JSON Schema
  → RawBlockPayload
  → Block DTO Parser
  → Typed DTO
  → Semantic Validator
  → Domain/Application Command
  → Mutation Kernel
```

LLM 不得直接 append 到 Workbench。`merge_block_result()` 改为注册表分发到按 Block 划分的 Merger，入口小于 40 行，Merger 只返回 Mutation/Command，不直接持久化。保留 transport、parse、schema、semantic、repair 的结构化诊断。

`EnrichmentJobRunner` 拆为 `SnapshotGuard`、`BatchPlanner`、`BlockExecutor`、`BlockCommitter`、`ProgressReporter` 和 `EnrichmentFinalizer`；主 Coordinator 小于 100 行，并复用 Mutation Kernel。

Requirements 真实实现按 ingestion、review、stakeholders、concerns_needs、scenarios、generation 迁移；`requirements_workbench.py` 在过渡期只 re-export/delegate，最终小于 100 行或删除，不复制两份业务逻辑。

MBSE 第一阶段只结构重构，不改变算法结果。`build_mbse_semantic_model()` 拆为 operational、requirements、functional、logical、physical、interfaces、relations、gaps builders，并通过 Typed `MbseSemanticModel` 与 legacy Mapper 保持输出兼容。Diagram 统一为：

```text
SemanticModel → ViewProjection → DiagramSpec → DiagramRendererPort
```

View 不知道 Graphviz/PlantUML，Adapter 不导入 View。文档 Reader 提取为独立的 TXT/Markdown/DOCX/PDF/OCR 模块，消除 private helper 循环依赖。

## 8. Interface、错误与安全

Interface 按领域拆分 Routes 和 CLI Handler。Pydantic 只属于 Interface，转换后进入 Application Command/Query；Template 使用 `RequirementsPageView` 等 Query View，不直接访问 Workbench 原始字典。

WebFacade 依次经历：代理新 Use Case → Route 直接使用 Application API → 删除。现有 URL、CLI、成功响应和模板语义保持兼容。旧 HTTP 错误状态映射暂不无版本改变，内部新增错误码和诊断。

错误模型为：

```text
RflpError
├── ValidationError
├── NotFoundError
├── ConflictError
│   └── ConcurrentModificationError
├── CapabilityUnavailableError
├── ExternalServiceError
└── InvariantViolation
```

Domain/Application 只抛语义错误，Interface 决定 HTTP/CLI 展示，Adapter 翻译第三方异常。

Test Executor 使用显式环境白名单：`PATH`、`PYTHONPATH`、隔离的 `HOME`、隔离的 `TMPDIR`、`LANG` 和 `PYTHONDONTWRITEBYTECODE`，另加明确声明的 Runner 变量。不得继承 API Key、Cloud Token、`SSH_AUTH_SOCK` 等 Secret。保留 `shell=False`、timeout、resource limit 和 output cap，产品文档改称“受资源约束的本地测试运行器”，不宣称安全沙箱。

## 9. 架构门禁与测试

架构预算初始扫描记录 global DI、Adapter 反向依赖、模块循环、`dict[str, object]`、raw JSON、Facade 方法数和超长函数；新代码不增加这些指标，核心遗留指标逐波下降。

硬性规则包括：

- `adapters → application = 0`；
- `application → adapters = 0`；
- Application 禁止 `sqlite3`、`subprocess` 和 `RFLP_*` 环境变量；
- 新 Use Case 禁止 `require_dependencies()`；
- Interface 禁止直接访问 Repository；
- Domain 禁止依赖外层；
- 新 Domain Entity 禁止以 `dict[str, object]` 作为核心模型；
- 模块 SCC 不得增加，最终为 0。

测试顺序为 Characterization → 结构迁移 → 行为优化。新增 Requirements、LLM、MBSE、Job、Web Contract、Migration、Repository Contract 和并发测试。关键并发场景包括 stale human write、Job 被人工修改 supersede、相同 idempotency key 的重复提交、过期 lease recovery、CAS 事务回滚。

新增 `test-full` 依赖组和锁定依赖；统一验证命令覆盖 compile、pytest、Import Linter、schema、build、ruff 和 pyright。Pyright 先 basic + error budget，新 typed 模块零错误，核心 Domain/Application 迁移完成后提升 strict。

## 10. 实施波次

```text
WAVE 0  完整验证环境、Characterization、架构预算、Ruff/Pyright 基线
WAVE 1  Test Executor 隔离、Adapter 反向依赖、Document Reader 解环
WAVE 2  Migration、Workbench Snapshot、CAS、CommitCoordinator、Human Mutation
WAVE 3  Requirements/Application、Query View、Typed LLM、Merge Registry、Explicit DI
WAVE 4  Job Domain、SQLite Job、jobs.json 导入、Thread Executor、Enrichment Pipeline
WAVE 5  MBSE Typed Model、Builder、Diagram Projection、窄 Repository Port、Session
WAVE 6  WebFacade 代理化与删除、API DTO、Error Mapper、Router/CLI 拆分
WAVE 7  Typed Requirements/Workbench、兼容层退出、Strict Quality Closure、文档闭环
```

每个波次必须先通过前一波的退出条件。单个 PR 遵循：行为测试、目标边界、移动实现、迁移最小调用方、focused tests、架构测试、完整验证、预算检查、旧路径 grep、文档更新。结构移动与算法行为变化不得放在同一个 PR。

第一实际批次覆盖 WAVE 0、WAVE 1 以及 WAVE 2 的前半段，完成 CommitCoordinator 与 Review Requirement vertical slice 后进行中期架构复审，再继续大规模人工 Mutation 和后续波次。

## 11. 回滚与停止条件

兼容代理未删除前，结构迁移可以回滚调用入口，但不得长期保留双实现。数据库 Migration 必须事务化，破坏性变更前备份；Job 导入验证前不改名 JSON。API 路由和成功 Schema 不变，因此内部回滚不要求前端同步回滚。

如出现以下情况，停止扩大范围并先修复：关键 Characterization 无法解释的输出变化；出现新双实现或万能 Service；架构预算上升；旧 DB fixture migration 失败；关闭 CAS 来绕过测试；大量 `Any`/`cast`/`type: ignore` 掩盖类型问题；结构迁移同时改变 MBSE/LLM 算法结果。

## 12. 最终验收

```text
adapters → application = 0
require_dependencies() = 0
global dependency registry = 0
module cycles = 0
WebFacade = 0
jobs.json runtime dependency = 0
SQLite = 唯一运行时持久化真源
CAS = enforced
LLM = Schema → Typed DTO → Semantic Validator → Command → Mutation
核心 Domain/Application 不以 dict[str, object] 承载实体
所有核心 Workbench 写入经过 CommitCoordinator
完整验证环境一条命令可复现
旧 Web/CLI/SQLite 数据兼容
```

算法函数如确需超过 150 行，必须进入架构预算并附带 Characterization 证据；否则核心业务函数目标小于 150 行，MBSE orchestration 小于 100 行，Enrichment orchestration 小于 100 行，Merge dispatch 小于 40 行。
