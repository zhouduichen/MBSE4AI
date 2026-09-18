# 结构化结构选型推荐设计

## 背景

详细设计入口已经能够从自然语言识别目标零件、尺寸和材料，并生成可审查的 CAD 操作计划。但当前“结构推荐”仍主要是自由文本：推荐没有稳定 ID，用户不能明确选择或拒绝候选，CAD 计划和 PhysicalBlock 也无法说明采用了哪一个结构方案。这使 3.1 结构选型推荐没有形成可追溯的产品闭环。

本切片只解决结构选型决策的结构化表达和追溯，不改变已经完成的审批门禁，也不把推荐伪装成工程批准事实。

## 目标

1. 设计意图草案在目标零件明确时输出结构化 `structure_options`。
2. 每个候选拥有稳定 ID、名称、类别、适用性、推荐理由和 `recommendation` 状态。
3. 用户可以在生成 CAD 计划前选择一个候选，也可以不选择，保留“仅推荐”的状态。
4. 选择结果随 CAD 计划、执行模型和 PhysicalBlock/交付物保存，并可重新读取。
5. 非法候选 ID 被拒绝；推荐不会绕过澄清、审批或审查流程。
6. 离线 fallback 可确定性地产生候选，不启动本机或远程模型。

## 非目标

- 不在本切片中执行真实 FreeCAD、仿真、强度计算或制造工艺验证。
- 不自动把候选提升为 `approved` 工程结论。
- 不建立新的状态机、Provider、仓库或 UI 审计体系。
- 不重新进行多轮 LLM 稳定性实验。

## 方案

### 结构化候选契约

`design-intent-draft.v1` 增加可选的 `structure_options` 数组。每项包含：

- `id`：稳定的候选标识；
- `label`：面向用户的结构名称；
- `category`：结构类别，例如加筋板式、机加工块式、法兰式；
- `applicability`：适用性边界；
- `rationale`：推荐理由；
- `status`：固定为 `recommendation`。

目标零件明确时，确定性解析器按目标类型提供有限候选。LLM 输出经过相同 schema 校验；缺少候选时仍可保持兼容，但产品 fallback 始终输出结构化候选。自由文本 `recommendations` 保留用于兼容和补充说明。

### 决策流

```text
自然语言
  → DesignIntentDraft.structure_options
  → 用户选择候选（或留空）
  → CadExecutionPlan.selected_structure_option_id
  → 审批
  → CadModel 输出
  → PhysicalBlock.design_payload / detail-design.json
```

候选选择只记录设计意图，不直接改变几何操作；几何仍由现有参数化计划和适配器负责。后续实现可以用该 ID 驱动不同结构操作，但本切片先保证决定可见、可追溯和可审查。

### 失败与门禁

- 目标不明确或基础尺寸缺失时，候选可以展示，但计划保持 `needs_clarification`，不可审批执行。
- 选择不存在于草案的候选 ID 时，返回契约错误，不保存计划。
- 不选择候选时，计划明确保存空 ID；这表示尚未作出结构选择，不表示系统已批准默认方案。
- `approval_status` 仍必须经过现有的 `pending → approved` 门禁。

## 验收

- 离线支架输入能得到至少两个结构候选，并保留 `status=recommendation`。
- 选择候选后，计划、模型和 PhysicalBlock 都能重新读取该 ID 及候选清单。
- 非法候选被拒绝，未选择候选不会被自动填充。
- Web 页面显示候选并提交用户选择。
- 既有 CAD、二维图纸、交付物、SysML 和全量离线验证保持通过。

