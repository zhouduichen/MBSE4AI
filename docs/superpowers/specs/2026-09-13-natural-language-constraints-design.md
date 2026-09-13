# 自然语言工程约束抽取设计

## 背景

AI4MBSE 当前可以在 Requirement payload 已经包含 `constraints`、`limits` 或 `max_`/`min_` 字段时，将约束传播到 Physical candidate，并由 Methodology Engine 做数值可行性判断。但用户直接输入“系统应在功耗不超过 50 W 且续航不少于 10 h 时运行”时，这些数字只保留在 `statement` 中，Requirement 仍没有结构化约束，Physical payload 的 `propagated_constraints` 为空。

这让同一条自然语言需求无法直接驱动物理架构评估，也使 Controller 只能在人工编辑 JSON 后才发现约束冲突。需要在输入适配边界增加一个小而明确的 Typed Requirement enrichment，不把解析器误当成完整的系统工程推理器。

## 目标

从自然语言 Requirement statement 中提取明确的工程约束，并保持可追溯：

- 支持功耗、质量/重量、时延/延迟、带宽、成本和续航/持续运行时间等常见指标；
- 支持中文和英文比较表达，包括“不超过/不大于/最多/≤/<=”与“不少于/不小于/至少/≥/>=”；
- 将单位归一化为稳定的 canonical field，例如 `max_power_w`、`min_mass_kg`、`max_latency_ms`、`min_endurance_h`；
- 只在语句显式出现指标、数值、单位和比较方向时提取，不根据领域名称或裸数字猜测；
- 在 Requirement payload 中保存归一化 `constraints` 和简短的 `constraint_provenance`，保留原始 statement 不变；
- 新建 Requirement 时在自然语言入口和项目手工录入入口复用同一 helper；已有显式结构化 constraints 不被覆盖；
- Physical candidate 继续通过 Requirement→Function→Logical 关系传播这些约束，未知物理测量值仍为 `needs_measurement`。

## 非目标

- 不替代 LLM 对复杂条件、跨句逻辑、预算分配或架构方案的语义推理；
- 不从“续航 10 h”这种没有比较方向的表达推导 `min` 或 `max`；
- 不从温度、可靠性、概率、范围、条件分支等需要领域语义的表达中生成未经确认的数值模型；
- 不把文本中普通编号、日期、小数或版本号误识别为工程约束；
- 不自动填写 Physical 的实测值，也不把约束满足宣称为可行。

## 方案选择

### 方案 A：确定性、单位感知的输入 enrichment（采用）

新增纯函数 `extract_requirement_constraints(statement: str) -> Mapping[str, object]`，使用受限的指标别名、比较符号和单位换算表。它在 Requirement 创建时运行，输出可审计的 canonical mapping；LLM 仍在五阶段中负责运行上下文、功能分解、逻辑/物理候选和 V&V 内容。这样离线 Runtime、文档输入和远程模型共享同一结构化输入边界。

### 方案 B：只让 LLM 抽取约束

对长句和复杂条件更灵活，但每次输出可能使用不同字段、单位或解释，离线验收无法复现；若模型漏掉约束，物理阶段也没有稳定的最低保障。

### 方案 C：LLM 抽取与规则解析合并为两个互相覆盖的来源

表达能力最高，但会引入冲突合并、来源优先级和重复约束的额外协议。后续可以把 LLM 提议作为候选来源加入，不作为本切片的输入契约。

## Canonical 约束模型

支持的 canonical metric 与单位为：

| 语义指标 | canonical value field | 接受单位 | 归一化单位 |
|---|---|---|---|
| 功耗 | `power_w` | W、kW、瓦、千瓦 | W |
| 质量/重量 | `mass_kg` | kg、g、千克、克 | kg |
| 时延/延迟/响应时间 | `latency_ms` | ms、s、毫秒、秒 | ms |
| 带宽 | `bandwidth_mbps` | Mbps、Gbps、兆比特/秒 | Mbps |
| 成本/费用 | `cost` | 数字、元、CNY、¥ | 原数值 |
| 续航/持续运行时间 | `endurance_h` | h、min、小时、分钟 | h |

输出示例：

```json
{
  "constraints": {
    "max_power_w": 50.0,
    "min_endurance_h": 10.0
  },
  "constraint_provenance": [
    {"field": "power_w", "operator": "max", "value": 50.0, "unit": "W", "text": "功耗不超过 50 W"},
    {"field": "endurance_h", "operator": "min", "value": 10.0, "unit": "h", "text": "续航不少于 10 h"}
  ]
}
```

如果同一 field 出现多个约束，保留最严格的方向值：多个 `max` 取较小值，多个 `min` 取较大值；冲突的上下界不在输入层自行裁决，而交给 Methodology/Controller。若同一语句存在无法换算的单位或不完整表达，则跳过该片段，并保留其他明确片段。

## 数据流与边界

```text
用户/文档 statement
          ↓
extract_requirement_constraints
          ↓
Requirement.payload.constraints + provenance
          ↓
Function satisfiedBy Requirement
          ↓
Logical allocation
          ↓
Physical propagated_constraints
          ↓
Methodology: conflict / needs_measurement
          ↓
Controller: evidence / trade study / reanalysis
```

输入 enrichment 只对新建 Requirement 写入缺失字段：若调用方已经提供 `constraints` 或 `constraint_provenance`，保留调用方结构化值，并且规则解析结果只补齐不存在的 key。ProjectService、ModelGenerationService 和未来文档批处理入口调用同一 helper，避免不同入口得到不同 schema。

物理层把 `endurance_h` 纳入可测量 Physical fields，使 `min_endurance_h` 能与 `physical.endurance_h` 比较；其余未知值和现有 `needs_measurement` 语义保持不变。任何提取出的约束都必须沿已有关系进入 Physical payload 的 `source_requirement_ids` 和 `propagated_constraints`，不能只存在于报告文字中。

## 错误处理与可解释性

- 空语句、无单位数字和不支持的指标返回空 mapping，不阻塞 Requirement 创建；
- 解析只产生确定性数值，不抛出由自然语言格式导致的异常；非法输入类型按空字符串处理；
- provenance 保存原始匹配短语和归一化结果，供 Web payload、SysML 元数据和交付报告继续查看；
- 解析出来的约束仍是用户/LLM 可 Review 的 Requirement payload，用户后续编辑可替换它们；
- 约束冲突、物理值缺失和上下界矛盾由 Methodology Engine 生成 finding，Controller 不能绕过用户决策自动改需求。

## 测试与验收

- 单元测试覆盖中文/英文比较符、六类指标、单位换算、复合句、重复约束、裸数字不提取和小数/版本号不误提取；
- 应用测试验证自然语言生成后 Requirement payload 立即包含 canonical constraints；项目手工录入也使用同一 helper；
- E2E 验证自然语言约束经过 Requirement→Function→Logical→Physical，Physical payload 包含来源 ID、归一化约束和 `endurance_h` 字段；
- Methodology 测试验证有物理测量值时能报告冲突，无物理测量值时仍报告 `needs_measurement`；
- 既有多需求、已有 SysML、交付包、Controller iteration 和结构化 LLM 测试保持通过；
- 全量 pytest、verify_full、compileall、Ruff、Import Linter、架构指标和 diff check 通过。
