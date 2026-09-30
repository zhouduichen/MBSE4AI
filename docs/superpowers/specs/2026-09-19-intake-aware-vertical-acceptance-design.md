# Intake-aware 结构化 LLM 纵向主链设计

## 背景

当前项目已经有两条可工作的路径：离线 `RequirementsUseCaseService` 会生成需求与行为框架，结构化 Runtime 测试则会驱动五个 R→F→L→P→V&V 阶段。但 `InputPreparationService` 会根据模型能力选择路径；现有多数结构化阶段测试使用只支持阶段 lens 的测试模型，因此没有证明“同一个具备需求摄取能力的结构化模型”能够从输入开始驱动完整产品链。

这不是远程模型联调。本切片使用进程内确定性 fake provider，模拟真实 `OpenAICompatibleModel` 的两个能力：`requirements.use_case` intake 和五个 `vertical.*` 阶段请求。

## 目标

补充一条可重复的离线证据链：

```text
文档 Source Region
  → RequirementsUseCaseService / requirements.use_case
  → Requirement + Use Case + Operational Scenario + Activity
  → vertical.requirements
  → vertical.functional
  → vertical.logical
  → vertical.physical
  → vertical.verification_validation
  → ModelGraph / Traceability / SysML / Engineering Deliverable
```

验收必须证明：

1. `InputPreparationService` 选择 `structured_intake`，而不是 legacy input adapter。
2. intake 请求真的携带文档区域和 `requirements_use_case_draft.v1` schema，并保留 provider/model 元数据。
3. 同一个 fake provider 随后收到五个 vertical stage 请求，最终每条 Requirement 都有完整 R→F→L→P→Verification/Validation 追溯。
4. 需求、行为、完整模型、SysML 往返和交付包来自同一 revision-bound ModelGraph。

## 设计

### 1. Intake-aware provider fixture

在现有结构化模型测试中增加一个小型 provider double，显式声明 `supports_requirements_intake = True`。当 lens 为 `requirements.use_case` 时返回符合现有 draft schema 的结构化 payload，并引用测试文档的真实 source region；其他 lens 委托现有完整五阶段 proposal fixture。这样不会复制生产编排逻辑，也不会放宽 schema 或验证器。

### 2. 文档输入

测试通过现有 repository document/source-region API 写入一个文档区域，再调用 `ModelGenerationService.generate(..., document_ids=(...))`。不直接调用独立 draft/apply API，确保产品入口会自行完成 intake、CAS 写入和下游生成。

### 3. 证据与交付验证

测试读取最终 ModelGraph，检查 typed entity kinds、source refs、完整 traceability、provider audit metadata；然后调用既有 `graph_to_sysml`/`sysml_to_graph` 和 `EngineeringDeliverableService`，验证实体/关系及 manifest snapshot 与同一图一致。测试不宣称远程模型质量，不执行网络请求、SSH、FreeCAD 或本地模型。

## 失败边界

- intake payload 不符合 schema：服务必须降级并保留诊断；该测试 fixture 不应触发降级。
- provider 不声明 intake 能力：保留现有 legacy compatibility test，不改变其行为。
- 任一阶段缺少闭环：测试失败，不用实体数量或 placeholder 代替追溯证据。
- SysML 或交付包 revision/hash 不一致：测试失败。

## 非目标

- 不启动远程或本地 LLM。
- 不改变现有 F/L/P 任务契约、并行策略、retry 或 completion bridge。
- 不把 fake provider 的成功当作真实模型质量或领域工程结论。
- 不增加新的 UI、数据库表或外部依赖。

## 验收命令

```bash
./.venv/bin/pytest -q tests/application/test_model_generation.py::test_intake_aware_structured_provider_generates_complete_document_model
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview ./.venv/bin/python scripts/verify_full.py
```
