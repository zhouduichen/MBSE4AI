# Multi-Requirement Intake Design

## Context

当前五阶段入口把自然语言或文档区域拼成一个字符串，再创建一个 Requirement。输入包含多个句子、列表项或文档条目时，后续 Functional、Logical、Physical 和 V&V 只能围绕一个合并需求生成，导致产品验收中的多需求追溯失真。

## Goal

保留输入中的需求边界：自然语言中的句子/分号条目和文档 Source Region 中的独立条目分别成为 Requirement；每条 Requirement 保留自己的 source region 证据，并进入同一轮五阶段生成。单句输入行为保持不变。

## Decision

新增一个无状态的 `split_requirement_statements(text)` 应用辅助函数，按换行、中文/英文分号、中文句号、问号/感叹号以及英文句号后的句首空格拆分，并去除常见列表前缀。它只负责边界切分，不尝试替用户改写工程语义，也不按“并”强行拆分一句需求。

`ModelGenerationService._ensure_input` 组装有序的 `(statement, source_ids)` 候选：显式文本的 source_ids 为空；文档候选逐个绑定对应 region id；同一来源重复文本合并 source ids。它在一个 `user.requirement_input` Patch 中一次写入所有新的 Requirement，并复用文本与来源完全匹配的既有 Requirement。已有 Requirement、已有模型种子、CAS、Runtime 和阶段契约保持不变。

## Data flow

```text
自然语言 / 文档 Source Region
          ↓ split_requirement_statements
   [(Requirement, source_ids), ...]
          ↓ one input Patch
       ModelGraph R*
          ↓ Functional / Logical / Physical / V&V
      per-requirement trace matrix
```

若输入没有可读文本，仍按现有规则优先使用已有活动 ModelGraph；若项目为空且没有可读文档，仍返回 `InputRequired`。切分不把多个 Requirement 误报为完整模型：阶段缺口和 V&V 缺口继续由现有 warnings、Traceability 和 Methodology 报告。

## Testing and acceptance

- 单元测试验证中文/英文句子、分号、列表前缀和小数不会被错误切分；
- 文档测试验证两个 Source Region/句子形成两个带独立 source id 的 Requirement；
- E2E 测试验证三条自然语言 Requirement 形成三条 Function 和三条完整 R→F→L→P→V&V 路径；
- 现有单需求、空项目、已有模型、SysML 往返和统一交付包测试保持通过；
- 全量 pytest、verify_full、compileall、Ruff、Import Linter 和架构指标通过。
