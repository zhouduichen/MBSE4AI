# 结构选型驱动参数化 CAD 设计

## 背景

结构选型推荐已经拥有稳定 ID，并能随着 CAD 计划和 PhysicalBlock 追溯。但计划编译目前只使用尺寸和材料；用户选择“加筋板式支架”或“整体机加工块式支架”不会改变操作序列，因而 3.1 还没有完成“结构意图驱动参数化建模”。

## 目标

本切片把支架/底座的两类结构选型编译为不同的 allowlisted CAD 操作：

- 加筋板式：基础包络实体后增加确定性加强筋实体；
- 整体块式：基础包络实体后增加确定性圆角操作。

两类结果都必须在 preview 适配器中产生不同的参数化 payload，并由远程 FreeCAD 适配器使用同一操作契约生成相应几何。用户不选择结构方案时，保持现有基础包络计划，不隐式采用任何候选。

## 方案选择

### 方案 A：应用层结构 profile → 固定 CAD 操作（采用）

应用层只接受已验证的候选 ID，并将其编译为 `add_rib` 或已有 `add_fillet` 操作。适配器只执行白名单操作，preview 与 FreeCAD 共享计划语义。这样选择结果真正影响模型，同时保留现有审批、审计和远程执行边界。

### 方案 B：让 LLM 直接生成 CAD 操作

会扩大自由度，但会绕过结构候选和操作白名单，无法保证不同 Provider 的操作安全和可复现性。本阶段不采用。

### 方案 C：为每个结构类型新建独立 CAD 适配器

会重复 preview、FreeCAD 和计划校验逻辑，过早扩大适配器数量。本阶段不采用。

## 数据流与契约

```text
DesignIntent.structure_options
  → selected_structure_option_id
  → CadWorkflowService._plan_operations
  → CadOperation(add_rib / add_fillet)
  → PreviewCadAdapter 或 FreeCadRemoteAdapter
  → model_payload.parts[].features / geometry
  → PhysicalBlock 与 detail-design.json
```

`add_rib` 的参数为 `part_id`、`length_mm`、`width_mm`、`height_mm`、`x_mm`、`y_mm`、`z_mm`，全部由已解析包络尺寸确定性计算；它不接受任意脚本或表达式。加筋板式生成两条平行加强筋，整体块式生成一个圆角操作，圆角半径由最小包络尺寸的固定比例计算并受正值校验。

仅以下 profile 在本切片进入几何操作编译：

- `bracket-gusseted-plate`、`base-ribbed-plate` → `add_rib` × 2；
- `bracket-machined-block`、`base-machined-block` → `add_fillet`。

其他目标类型的候选仍可展示和追踪，但不会被错误地映射成支架几何；后续切片再为壳体、轴和齿轮增加专用 profile。

## 门禁与失败处理

- 只有结构候选 ID 已存在于当前设计意图时才能生成计划。
- 没有完整长宽高时，仍按既有规则保持 `needs_clarification`，不生成结构 profile 操作。
- preview 和 FreeCAD 都校验操作顺序、正数参数、依赖关系和白名单。
- 结构 profile 不改变 `approval_status`；执行仍必须经过用户审批。
- FreeCAD 圆角失败时保留适配器诊断，不把失败伪装为正式制造结论。

## 验收

1. 同一组支架尺寸分别选择加筋板式和整体块式，计划操作序列不同。
2. preview 两种模型的 feature/geometry payload 和 artifact hash 不同；未选择时不包含 profile 操作。
3. 加筋 preview 的包络高度包含加强筋，整体块 preview 包含 `add_fillet` 特征。
4. 选择结果和实际操作随模型、PhysicalBlock、SysML/详细设计交付物保存。
5. 非法候选、负数 profile 参数、未审批执行继续被拒绝。
6. 全量离线测试、架构检查和 lint 通过；不启动本机/远程模型、服务器、SSH 或 FreeCAD。

