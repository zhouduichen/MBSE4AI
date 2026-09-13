# Existing Model Seed Continuation Design

## Context

AI4MBSE 已经可以把已有 SysML v2 子集模型导入同一份 Typed ModelGraph，也已经有五阶段生成、Review、编辑和交付包导出。但当前分析入口的输入门禁只识别用户 Requirement 或已解析文档。一个只包含 Function、Logical Component 或 Physical Block 的历史/局部模型虽然已经存在于 ModelGraph，仍会被 Web 和 API 判断为“没有输入”。这使已有模型无法真正进入后续分析链。

## Goal

让任意包含至少一个非弃用实体的已有 ModelGraph 成为合法分析种子，并保持以下行为：

- 空项目仍必须先提交需求或上传文档；
- 显式提交的自然语言需求优先作为生成输入，并按现有逻辑复用或新增 Requirement；
- 已有 Requirement 和文档输入的行为不变；
- 只有部分层的模型可以开始生成，但缺失层、追溯和 V&V 缺口必须在现有结果中保留为 warnings/needs-review；
- 输入判定本身不创建 Revision、不绕过 CAS，也不修改已有实体；
- Web 页面和 API 使用同一判定，不再出现按钮可用性与后端拒绝不一致。

## Alternatives

1. **推荐：把非空 ModelGraph 作为输入种子。** 在 `ProjectService.has_analysis_input` 和 `ModelGenerationService._ensure_input` 共享同一语义：有任意非弃用实体即允许分析。实现最小，适用于导入模型、历史模型和已生成但尚未完整的局部模型。
2. **只把 SysML 导入实体标记为 IMPORT。** 语义更窄，但需要改变导入元数据，并不能覆盖通过其他合法入口进入的历史模型或局部图。
3. **新增独立的“继续分析”模式。** 可以区分全新生成和已有模型延续，但会复制输入门禁、页面状态和 API 分支，当前阶段不必要。

选择方案 1，因为 ModelGraph 是产品唯一真源，输入资格应由图是否有可用模型内容决定，而不是由某一种来源或文件格式决定。

## Architecture and data flow

```text
已有 SysML / 历史模型 / 已生成局部图
                 ↓
          active ModelGraph entity
                 ↓
       Web 状态 + analysis API 输入门禁
                 ↓
    VerticalStage 继续使用现有图作为 Context
                 ↓
      ModelGraph Patch → Revision → Trace / V&V
```

`ProjectService.has_analysis_input(project_id)` 首先检查当前图中是否存在状态不是 `DEPRECATED` 的实体；没有实体时再检查现有文档证据。`ModelGenerationService._ensure_input` 使用同样的判断顺序：显式文本和文档仍优先创建/复用 Requirement；没有文本时，已有 Requirement 或任意活动模型实体都允许继续；只有空图且没有可读文档时才抛出 `InputRequired`。

阶段 Runtime、PatchPolicy、Review/CAS 和交付投影不变。部分模型缺少 Requirements 或 V&V 时由现有阶段缺口、Traceability 和 Methodology 结果表达，不把输入门禁放宽误报为完整模型。

## Error handling and safety

- `DEPRECATED` 实体不计入输入资格，避免已废弃模型重新激活生成链；
- 空图仍返回现有输入错误；
- 输入资格检查只读 ModelGraph；
- 所有生成写入仍必须经过现有 Runtime 验证和 CAS Revision；
- 导入冲突保护保持不变；
- 部分模型的成功响应可以是 `completed_with_warnings`，页面继续展示缺口和 Review，而不是隐藏缺失追溯。

## Testing and acceptance

- 单元测试覆盖：有活动实体时 `has_analysis_input` 为真，只有弃用实体时为假；
- API 测试覆盖：上传只含 Function 的 SysML 后，无 Requirement 文本也能调用 `/analysis`，返回运行结果而不是 `InputRequired`；
- Web 页面测试覆盖：导入局部模型后 Analysis 页面启用生成入口；
- 回归测试覆盖：空项目仍被拒绝、自然语言/文档生成、完整 SysML 导入和交付包导出保持通过；
- 全量 pytest、verify_full、compileall、Ruff、Import Linter 和架构指标必须通过。
