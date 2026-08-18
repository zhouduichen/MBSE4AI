# AI4MBSE RFLP-Lite 下一阶段完整落实设计

**日期：** 2026-08-18  
**依据：** `AI4MBSE_RFLP-Lite_当前版本复审与下一阶段执行规划_v2.1.docx`  
**范围：** 按文档 Phase 2A → 2B → 3A → 3B → 5 → 4 → 6 → 7 依次完成全部执行项。

## 目标

把当前“Application / Interface 不再直接 import adapters”的架构地基继续收敛为可验证的业务边界：Use Case 采用显式窄依赖注入；LLM 输出必须经过严格结构、类型、语义和来源校验后才可合并；MBSE 正式模型只保留有证据的实体与关系；本地 Job 在重启后可恢复、可幂等重试；Web/CLI 通过同一 Use Case 完成闭环；所有关键约束进入自动化质量门禁。

## 不变约束

- 保留现有 CLI 命令、Web 路由、模板入口、工作区目录和 `.rflp` 存储布局。
- 继续采用本地模块化单体，不引入 Celery、Redis、消息队列或远程数据库。
- `bootstrap/container.py` 是唯一允许组合 Application 与 Adapter 的位置。
- Application 和 Interface 不得直接 import `rflp_lite.adapters`。
- 新代码不得调用 `require_dependencies()`；旧调用仅作为有明确迁移路径的兼容壳保留。
- 单个分析 Block 失败不得回滚已经成功合并的 Block；只允许重试失败、降级或中断 Block。
- 不可信或未通过语义验证的 LLM 内容不得写入 Workbench 正式状态。

## 总体架构

```text
Interface / CLI
      ↓
Application Use Case / Query Service
      ↓  (显式窄依赖 dataclass)
Ports
      ↓
Composition Root 注入 Adapters
```

LLM 分析统一经过以下边界：

```text
GenerativeModelPort
  → provider-native structured output
  → strict JSON parse
  → block-specific JSON Schema
  → one bounded repair
  → typed DTO
  → semantic + provenance validation
  → deterministic normalization
  → ValidatedBlockResult
  → transactional merge
```

## 组件设计

### 1. Use Case 与依赖边界

在 `application/use_cases/` 增加以下入口：

- `review_requirement.py`：需求接受、编辑、驳回、审查历史和派生 stale 计算。
- `generate_rflp.py`：从已接受需求生成 RFLP 草稿或新的派生 revision。
- `generate_mbse.py`：从 RFLP/Workbench 生成带 provenance 的 MBSE 语义模型。
- `analyze_project.py`：项目扫描、实际模型、基线匹配和差异计算。
- `run_project_tests.py`：测试执行和 Evidence 生成，不改变需求或匹配语义。
- `record_evidence.py`：将测试、扫描、仿真和人工证据统一记录。

每个入口拥有自己的 frozen dependency dataclass，只声明实际需要的 Port。例如 `ReviewRequirementDeps` 只包含 `WorkbenchRepositoryPort`、审查策略和 stale policy；`RunEnrichmentBlockDeps` 只包含 `GenerativeModel`、Workbench Repository、Job Repository 和 `AnalysisSemanticValidator`。WebFacade 保留现有公开方法，但只做参数适配和 Use Case 转发。

### 2. Strict Analysis Contract

在 `application/intelligence/` 增加：

- `block_schemas.py`：六个独立 block schema、版本号、字段长度/枚举/数组限制和 `additionalProperties=false`。
- `validated_result.py`：六类 typed DTO、`ValidatedBlockResult`、结构化诊断和 provenance。
- `semantic_validator.py`：来源区域、workspace、input hash、重复 ID、关系端点和关系方向校验。

六个 Block 为 `system_scope`、`stakeholders`、`concerns_needs`、`requirements`、`scenarios`、`architecture`。Schema 只接受明确字段；`architecture.relations` 使用独立关系 Schema 和端点类型矩阵。`merge_block_result` 的参数改为 `ValidatedBlockResult`，原始 `dict` 不可直接进入业务合并逻辑。

### 3. MBSE 语义真实性

`mbse_semantics.py` 不再从需求自动创建正式 Function、LogicalComponent、PhysicalBlock，也不再使用 `index % len(...)` 生成分配关系。缺失层级通过 `needs-analysis` gap 记录，gap 不是满足关系的端点。只有用户确认、确定性有证据规则或已经通过严格契约和语义验证的 LLM 结果才能形成正式 `satisfiedBy`、`allocatedTo`、`realizedBy`、`interfacesWith`、`flowsTo` 或 `verifiedBy`。

未知关系类型产生 Diagnostic 并被拒绝，不转换为 `relatedTo`。技术需求只在输入含有技术参数、验证义务或明确领域规则时生成；不能机械把每条需求复制成“验证：...”。

### 4. 可恢复 Job

`JobService` 继续使用原子 JSON 文件，但记录增加 `attempt`、`lease_id`、`lease_expires_at`、`heartbeat_at`、`last_error`、`block_states` 和 `idempotency_key`。提交、状态转移、heartbeat、完成和重试都通过 Job Port。启动时扫描 `running` 任务：有效 lease 仍由本进程持有的任务继续；没有有效 lease 的任务转为 `interrupted`。重试只重新执行非 `succeeded` Block，并根据幂等键避免重复写入。

### 5. 交互闭环

状态呈现集中在 presenter/helper 层完成内部 ID 到中文名的映射。需求输入页将领域包和模型策略放入高级设置；分析进度显示中文 Block 名、错误诊断、单块重试；需求检查显示 source/producer/confidence 和 stale 下游范围；RFLP/MBSE 对 gap 使用明确的缺口样式；视图切换只读取已保存语义模型，不触发 LLM；项目验证在前置条件不满足时禁用动作并说明缺项。

## 数据流与失败处理

1. 输入或编辑创建新的 `input_hash` / revision。
2. Job 为每个 Block 建立独立状态。
3. Model 只通过 `GenerativeModel.complete_json()` 调用。
4. 结构错误最多进行一次定向 repair；再次失败标记当前 Block `failed`。
5. 结构正确但语义/来源错误的结果直接拒绝并记录 Diagnostic，不进入 Workbench。
6. 合法结果转换为 `ValidatedBlockResult`，在单个事务中写入新的 revision。
7. 已成功 Block 保持可用；失败 Block 可以按幂等键单独重试。
8. 进程重启后未持有有效 lease 的 `running` Job 变为 `interrupted`，UI 明确提示可恢复。

## 分阶段验收

### Phase 2A / 2B

- 新 Use Case 只使用显式构造注入，不调用 `require_dependencies()`。
- WebFacade 兼容入口的行为保持不变，路由不再承载业务规则。
- 架构 AST 测试能够定位新增的全局依赖获取和 Interface→Adapter 依赖。

### Phase 3A / 3B

- Application 中不再存在业务层 raw `chat_completion` 旁路。
- 六个 Block 的额外字段、缺字段、错误类型、非法枚举、无效来源和非法关系端点均拒绝写入。
- repair 最多一次；`ValidatedBlockResult` 是唯一合并入口。

### Phase 5

- 无架构证据时只显示 gap，不生成正式满足、分配或实现关系。
- 未知关系类型产生 Diagnostic 并不进入正式模型。
- 视图和导出仍能处理带 gap 的合法模型。

### Phase 4

- `running` → `interrupted` 的启动恢复可测试。
- 成功 Block 不重复执行；失败/降级/中断 Block 可按幂等键重试。
- 重启不丢失已保存的成功结果。

### Phase 6 / 7

- 两个 workspace 的跨项目 ID 被拒绝。
- 视图切换不产生新的 LLM 请求。
- Graphviz/PlantUML 不可用时 fallback 正常。
- 测试结果只生成 Evidence，不改变 Requirement/Function 语义。
- 全量 pytest、Import Linter、compileall、schema 检查和 E2E 门禁通过。

## 实施策略

采用增量垂直切片，而不是一次性重写大文件。每个阶段按“先测试、最小实现、局部迁移、全量验证”的顺序完成；每一阶段结束后保留兼容壳并更新架构文档，确保后续阶段可以独立回退或继续推进。

