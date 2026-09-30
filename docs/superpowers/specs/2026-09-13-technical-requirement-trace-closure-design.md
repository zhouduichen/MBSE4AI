# Physical Technical Requirement and Trace Closure Design

**日期：** 2026-09-13  
**状态：** 已确认设计，进入实施计划  
**目标版本：** rflp-lite 0.3.1

## 1. 问题与目标

当前默认纵向链已经能够从自然语言生成 R、F、L、P 和 V&V，但 P 层只产生 `PhysicalBlock`。当输入明确包含“功耗不超过 50 W”“质量不超过 2 kg”“续航不少于 10 h”等工程约束时，约束虽然会传播到物理候选，却没有形成可独立审查、验证和导出的 Technical Requirement。

本轮补齐一个窄而真实的闭环：

```text
显式工程约束
  → Physical candidate
  → Technical Requirement
  → Verification / Validation
  → Traceability / SysML / Deliverable
```

本轮不为没有明确工程约束的物理候选生成泛化或占位技术需求，也不改变已有测量值、需求数值或可行性结论。

## 2. 设计决策

### 2.1 生成条件

`VerticalRuleRuntime._physical` 对每个物理候选和其来源 Requirement 检查以下 canonical 字段：

- Requirement payload 顶层的 `max_*` / `min_*`；
- `constraints` 或 `limits` Mapping 中的 `max_*` / `min_*`。

至少存在一个明确字段时，生成一个 Technical Requirement。没有这些字段时保持现有 P 行为，不凭空添加技术约束。

### 2.2 Technical Requirement 结构

Technical Requirement 使用既有 `EntityKind.REQUIREMENT`，payload 至少包含：

```json
{
  "level": "technical",
  "type": "constraint",
  "statement": "物理候选……应满足……",
  "obligation": "物理候选应满足显式工程约束",
  "verification_method": "test",
  "constraint_fields": ["max_power_w"],
  "constraints": {"max_power_w": 50},
  "source_requirement_ids": ["requirement-…"],
  "source_physical_ids": ["physical_block-…"],
  "open_questions": ["需要对该物理候选执行约束验证"]
}
```

Technical Requirement 的稳定身份由既有 `kind + name + source_ids` 机制构造；名称包含物理候选和来源 Requirement，保证同一物理候选/来源组合幂等，替代候选拥有独立技术需求。

### 2.3 关系与 V&V

每个 Technical Requirement 添加：

- `technical_requirement derivedFrom source_requirement`；
- `technical_requirement satisfiedBy physical_block`。

第二条关系表示该物理实现直接承载技术约束，不把它伪装成 Function 分配。现有 V&V Runtime 会为所有活动 Requirement（含 Technical Requirement）生成独立 VerificationCase、ValidationCase，并通过 `verifiedBy` / `validatedBy` 连接。

### 2.4 追溯口径

Technical Requirement 的 RFLP 追溯通过 `derivedFrom` 回到来源 Requirement，复用来源 Requirement 的 Function→Logical→Physical 路径；如果存在直接的 `satisfiedBy physical_block`，将其并入物理节点集合。Technical Requirement 自身的 Verification/Validation 关系单独统计。

Functional coverage 不把 Technical Requirement 当作需要重新识别 Function 的系统需求；V&V coverage 则把它作为正式需求统计。这样既不会制造 `functional_requirement_uncovered` 噪声，又不会漏掉技术约束的验证责任。

## 3. 代码边界

- `src/rflp_lite/runtime/rule_based.py`：在现有 Physical candidate 生成后创建 Technical Requirement 和两条关系；复用原始 constraints/provenance，不修改事实。
- `src/rflp_lite/application/model_generation.py`：扩展产品级 TraceabilitySummary 的 Technical Requirement 路径解析。
- `src/rflp_lite/application/projections/common.py`：让 Requirements/RFLP/Trace 页面使用同一技术需求回溯口径。
- `src/rflp_lite/methodology/engine.py`：Functional 分析排除 Technical Requirement，V&V 继续纳入全部正式 Requirement。
- `src/rflp_lite/application/sysml_v2.py`、deliverable 服务不新增特殊格式分支；已有全量实体元数据和关系注释自然保留该类型。

不新增 EntityKind、数据库表、Provider、TaskSpec 或前端状态机。

## 4. 失败与保护

- 约束值缺失、类型不确定或没有 canonical `max_`/`min_` 字段时，不生成 Technical Requirement；现有 `needs_measurement` 继续负责物理候选。
- Physical candidate 被锁定或用户修改时，只能新增独立 Technical Requirement，不能更新或覆盖原候选。
- Technical Requirement 生成失败不得删除或回滚已经写入的 Physical candidate；阶段返回已有的局部结果和明确诊断。
- 任何新增关系继续经过现有端点类型、PatchPolicy 和 CAS 校验。

## 5. 验收标准

1. 含显式 `max_`/`min_` 约束的自然语言生成会产生 Technical Requirement，且保留 constraint provenance、来源 Requirement 和 Physical candidate。
2. Technical Requirement 通过 `derivedFrom` 和 `satisfiedBy` 形成真实关系，并由 V&V 生成独立验证/确认案例。
3. 产品级 Traceability、Requirements 页面和 RFLP 投影把 Technical Requirement 回溯到来源 Requirement 的 F/L/P 路径，不产生误报的功能缺口。
4. 没有明确约束的普通输入保持原有实体数量和追溯结果。
5. SysML 导出/回读、统一交付包和所有既有测试继续通过。

