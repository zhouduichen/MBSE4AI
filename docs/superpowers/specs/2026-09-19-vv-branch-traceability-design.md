# V&V 分支追溯与定向迭代设计

**状态：** 设计待审查

**日期：** 2026-09-19

## 目标

补齐默认 R→F→L→P→V&V 产品链中“Activity 分支 → Verification/Validation → Evidence → 失败反馈 → 定向重分析”的可交付闭环，使每条有效 Requirement 都能从行为模型追溯到结构化 V&V 场景，并在失败后沿影响路径回到最小必要的下游阶段。

本切片只使用现有 ModelGraph、CAS Patch、Methodology Engine 和 Systems Engineering Controller；离线验收不启动服务器、LLM、SSH 或 FreeCAD。

## 当前基础与缺口

现有垂直 Runtime 已生成 Use Case、Activity、五类分支文本、VerificationCase、ValidationCase 和完整 V&V 计划字段；`VvExecutionService` 已能把显式执行结果写成 Evidence，失败结果已能生成 Issue 和影响实体列表。现有 Controller 已能基于 finding 提供 `reanalyze`、`trade_study` 或 evidence 动作。

缺口是分支与 V&V 之间仍主要通过 `covered_branches` 文本数组表达：

- 没有每个分支的独立、可执行场景对象；
- 覆盖率无法区分“列出分支名称”和“该分支具备刺激、预期结果、通过准则”；
- Assurance 页面和交付包不能直接展示每个分支的执行计划；
- 失败反馈虽然存在，但产品结果没有把分支场景覆盖与影响路径作为一个可读的闭环结果呈现。

## 设计选择

### 1. 复用现有实体，不新增元模型类型

继续使用 `VerificationCase` 与 `ValidationCase`。在两个实体的 payload 中增加同构字段 `branch_scenarios`，避免引入新的实体类型、关系端点和 SysML 解析规则。

每个元素采用如下 JSON 结构：

```json
{
  "id": "verification-<case-id>-failure",
  "branch_type": "failure",
  "branch_label": "任务失败后重试",
  "activity_id": "activity-...",
  "requirement_ids": ["requirement-..."],
  "stimulus": "注入任务失败事件",
  "procedure": "执行失败处理并观察重试或人工接管路径",
  "expected_result": "系统沿失败分支恢复或安全转入人工接管",
  "pass_criteria": "失败分支行为、状态转移和结果均可记录",
  "status": "planned"
}
```

`branch_type` 的允许值固定为 `normal`、`failure`、`alternative`、`boundary`、`exception`。若输入 Activity 没有可解析的分支，系统保留已有默认分支，但必须在诊断中标记为规则补全，不把它伪装成 LLM 推断。

### 2. 由 Activity 作为唯一分支来源

在 Assurance 阶段从当前 ContextBundle 中的 Activity 读取：

- Activity ID；
- `branches` 中的分支文本；
- `branch_types` / `branch_map` 中的类型映射；
- Activity 的 `requirement_ids` 和 `use_case_ids`。

规范化分支文本后，为每个 Requirement 的 VerificationCase 和 ValidationCase 分别生成场景。场景引用同一 Activity ID 和 Requirement ID，不复制新的行为实体，也不改变现有 `verifiedBy` / `validatedBy` 关系。

### 3. 覆盖计算从文本存在性升级为结构化完整性

Methodology/Assurance 投影新增确定性指标：

- `branch_scenario_total`：计划中的分支场景数；
- `branch_scenario_complete`：具备刺激、步骤、预期结果和通过准则的场景数；
- `activity_branch_coverage`：每类要求分支均有完整场景时的覆盖率；
- `branch_execution_coverage`：已有执行 Evidence 的场景比例，仅作为执行进度，不等同于通过率。

没有执行证据的场景状态为 `planned`；有 Evidence 后状态取 `passed`、`failed`、`blocked` 或 `inconclusive`。任何缺字段场景进入 `needs_review`，不能被计入完整覆盖。V&V 执行请求接受可选 `scenario_id`：传入时必须引用同一 Case 的已有分支场景，并只更新该场景的状态、执行证据和最后结果；未传入时保留现有 Case 级执行语义，兼容历史调用。

### 4. 失败反馈复用现有 Controller，并显式呈现影响路径

`VvExecutionService.record_result` 保持现有证据写入、Issue 创建和 CAS 语义，并在传入 `scenario_id` 时把结果同步到对应 `branch_scenarios` 元素。失败、阻塞或不确定结果继续由 Methodology Engine 计算影响路径，Controller 返回最小下游动作：

```text
V&V execution failure
  → Evidence + Issue
  → requirement / function / logical / physical impact paths
  → controller action
  → user decision or safe targeted re-analysis
```

不自动修改锁定实体，不自动选择 Trade Study 方案。用户通过既有 Controller 执行入口确认后，调用现有 `continue_generation` / `reanalyze`，只重跑受影响阶段；执行结果记录 `revision_before`、`revision_after`、所选阶段和 finding 变化。

### 5. 交付与界面

- Assurance API/页面在每条 V&V 行展示分支场景摘要、完整性、执行状态和证据数量；
- 失败执行结果展示影响路径和下一步 Controller 动作；
- ModelGraph payload、SysML v2 子集和 `behavior.json` / `model.json` 通过现有通用序列化自动保留 `branch_scenarios`；
- 交付包额外在 assurance 内容中输出分支覆盖汇总，revision 和 snapshot hash 仍来自同一 ModelGraph；
- 没有真实执行证据时，页面明确显示“计划/待执行”，不显示通过。

## 错误与一致性策略

- 分支类型未知时保留原始文本并归类为 `unknown`，该场景为 `needs_review`，不计入覆盖率；
- 缺少 Activity 时仍生成基本 V&V 计划，但 `branch_scenario_total=0`，Assurance 报告必须给出缺失行为来源 finding；
- 已锁定的 V&V Case、Requirement 或下游实体遵循既有 ConflictError/CAS 规则；
- 重复生成必须按 Case ID、Activity ID、Branch Type 幂等更新，不重复创建场景或 Evidence；
- SysML 导入遇到未知 payload 字段时按现有兼容规则保留，不因新字段丢失整份模型。

## 文件边界

### 修改

- `src/rflp_lite/runtime/rule_based.py`：规范化 Activity 分支并生成两个 V&V Case 的 `branch_scenarios`。
- `src/rflp_lite/methodology/engine.py`：计算分支场景完整性/覆盖率并生成缺口 finding。
- `src/rflp_lite/application/projections/assurance.py`：把分支场景和覆盖摘要投影到 Assurance 视图。
- `src/rflp_lite/interface/web/templates/assurance.html`：展示分支计划、执行状态和失败影响路径。
- `src/rflp_lite/application/vv_execution.py` 与 `src/rflp_lite/interface/web/resource_api.py`：接受并校验 `scenario_id`，将分支级执行证据回写到 Case payload。
- `src/rflp_lite/application/deliverables.py`：在 assurance 交付内容中保留覆盖摘要。

### 测试

- `tests/runtime/test_task_execution.py`：验证规则 Runtime 生成五类结构化分支场景。
- `tests/methodology/test_engine.py`：验证完整性、未知分支和缺失 Activity 的覆盖指标。
- `tests/application/test_vv_execution.py`：验证分支 Evidence、失败 Issue 和定向动作仍遵循 CAS/幂等语义。
- `tests/application/projections/test_assurance_projection.py`：验证页面投影字段。
- `tests/interface/web/test_vertical_generation_api.py`：验证 API 返回分支摘要、影响路径和 Controller 动作。
- `tests/e2e/test_local_product_acceptance.py`：验证 ModelGraph → SysML → 交付包的分支场景往返。

## 验收场景

使用离线 `VerticalRuleRuntime` 输入“系统应支持人工接管”：

1. 生成图后，每个 Requirement 有 Use Case、Activity、VerificationCase、ValidationCase 关系。
2. 两类 V&V Case 均包含五类完整 `branch_scenarios`，覆盖指标为 1.0，执行覆盖仍为 0.0。
3. 对 failure 场景携带 `scenario_id` 记录 failed Evidence 后，场景状态为 failed，相关 Issue 为 open，影响路径至少包含 Requirement、Function、Logical 和 Physical。
4. Controller 返回的动作只指向受影响阶段；用户确认后定向重分析产生新 revision，并且不修改锁定实体。
5. 重新导出并导入 SysML 后，`branch_scenarios`、覆盖摘要和执行状态保持一致。
6. 完整离线验收、Ruff、import-linter 和架构指标全部通过。

## 非目标

- 本切片不运行真实远程 LLM，不评估模型生成质量或稳定性。
- 本切片不启动 FreeCAD，不生成新的真实 FCStd/STEP 几何。
- 本切片不增加并行实验轮次，不重建 Benchmark Harness。
- 本切片不自动判定用户验收通过，不把计划字段当成执行事实。
