# 需求到完整 MBSE 模型的纵向生成设计

**日期：** 2026-09-13  
**状态：** 已确认设计，进入实施计划  
**目标版本：** rflp-lite 0.3.0

## 1. 目标与非目标

本设计把产品主价值定义为：用户输入一段自然语言需求或需求文档，系统使用 LLM 自动分析并产出一个可查看、可编辑、可追溯、可导出并可重新读取的完整 MBSE 模型。

首个纵向验收必须覆盖：

```text
输入 → R → F → L → P → V&V → ModelGraph → SysML v2 子集
```

其中：

- R 产生系统边界、利益相关者、场景和需求；
- F 产生功能、功能分解、功能流和功能场景；
- L 产生逻辑组件、接口和功能到逻辑的分配；
- P 产生物理候选、物理分配和技术需求；
- V&V 产生验证/确认用例、通过准则和需求追溯；
- 每个正式需求至少有一条 `R → F → L → P → V&V` 闭合链，无法确定的地方以假设和评审项表达，而不是用占位实体冒充完成。

本轮不做以下事情：

- 不继续扩大 23 个细粒度任务的稳定性实验；
- 不重写已经可用的 SQLite、CAS、结构化输出和基础关系校验；
- 不把多人协作、仿真、CAD、供应商联网检索或全量 SysML v2 语言实现纳入首个纵向切片。

## 2. 产品入口与运行模式

新增 `ModelGenerationService` 作为产品入口。默认的“开始分析/生成模型”调用它；现有 `WorkflowRunner` 仍可通过显式高级入口运行，用于兼容既有测试、单阶段调试和研究基准。

产品生成接口接收：

```python
GenerateModelRequest(
    project_id: str,
    requirement_text: str | None = None,
    document_ids: tuple[str, ...] = (),
    run_id: str | None = None,
    force_new: bool = False,
)
```

产品生成结果至少包含：

```python
GenerateModelResult(
    run_id: str,
    project_id: str,
    status: Literal["completed", "completed_with_warnings", "failed"],
    revision: int,
    stage_results: tuple[StageResult, ...],
    traceability: TraceabilitySummary,
    warnings: tuple[str, ...],
    sysml_text: str,
)
```

未配置 LLM 时允许使用现有 RuleRuntime 进行开发和离线测试，但产品验收必须显式运行配置的 LLM。离线运行不得把规则填充的 `xxx 候选` 计作完整模型。

## 3. 推荐架构

### 3.1 五段式生成器

生成器按以下顺序执行，每一段使用一个小型结构化响应契约：

1. `requirements`：从原始需求生成 R 层对象；
2. `functional`：基于已编译 R 层生成 F 层对象；
3. `logical`：基于 R/F 生成 L 层对象和分配关系；
4. `physical`：基于 R/F/L 生成 P 层对象、候选和技术需求；
5. `verification_validation`：基于完整 RFLP 生成验证、确认、通过准则和追溯关系。

每段遵循同一协议：

```text
StageContext + StagePrompt
        ↓ LLM structured response
StageProposal
        ↓ StageCompiler
Validated StagePatch
        ↓ ModelGraph revision
Next StageContext
```

阶段输出只允许声明本阶段负责的实体种类和关系谓词；稳定 ID 由编译器基于 kind、名称和来源生成，LLM 不直接决定数据库身份。

### 3.2 与现有 Harness 的边界

现有能力分为两类：

- 必须复用：`TaskRuntime`/OpenAI-compatible provider、Schema 注册、Proposal 编译、ModelGraph、Repository、关系端点校验、来源和运行台账、基础 Gate/Traceability 投影；
- 不再主导产品流程：23-task 调度、逐任务失败路由、细粒度 repair loop、稳定性 benchmark 和过早的阻断状态机。

结构错误、无法编译或关系端点非法仍然是生成失败；语义不完整、低置信度和未决假设记录为 warning / review issue，生成器继续推进后续阶段。只有缺少某一整层的不可恢复错误才返回 `failed`。

阶段成功后立即写入一个可编辑 revision，实体 producer 为 `llm`，状态为 `validated`；不自动设为 `locked`。如果后续阶段失败，前面已产生的模型和明确诊断仍可查看，但完整验收只对五段全部完成的运行通过。

## 4. 阶段最小契约

所有阶段响应统一为：

```json
{
  "entities": [
    {
      "kind": "function",
      "name": "配送任务规划",
      "payload": {},
      "source_ids": [],
      "evidence_ids": [],
      "confidence": 0.86
    }
  ],
  "relations": [
    {
      "source_ref": "requirement:及时送达",
      "predicate": "satisfiedBy",
      "target_ref": "function:配送任务规划"
    }
  ],
  "assumptions": [],
  "open_questions": []
}
```

`source_ref` 在阶段编译时解析为当前图中稳定 ID；解析失败是该阶段的编译错误，不能静默生成孤立关系。每个实体必须有非空名称；每个关系必须通过现有端点类型校验；同名实体在同一项目内合并，不重复创建。

阶段的最低输出约束为：

| 阶段 | 必须生成的真实对象 | 必须形成的关系 |
|---|---|---|
| R | system、stakeholder、requirement、operational_scenario | stakeholder/requirement 与 system、scenario 的来源关系 |
| F | function、functional_flow、functional_scenario | requirement `satisfiedBy` function；function `decomposes` function 或 flow 关系 |
| L | logical_component、interface | function `allocatedTo` logical_component；function/interface 交互关系 |
| P | physical_block、technical requirement | logical_component `allocatedTo` physical_block |
| V&V | verification_case、validation_case | requirement `verifiedBy` / `validatedBy` |

## 5. 追溯与质量口径

新增产品级追溯检查，不再把“某个任务成功”作为主要指标。对每个非废弃系统/功能/技术需求，计算从需求到验证的路径：

```text
requirement
  → function
  → logical_component
  → physical_block
  → verification_case or validation_case
```

结果分为：`complete`、`partial`、`missing`。`complete` 是端到端验收必要条件；`partial` 允许在 UI 中展示并继续编辑；`missing` 生成明确 review issue。质量检查只检查真实模型内容，不把实体数量或运行次数当成进度。

首个代表案例使用校园无人配送机器人，但生成器的实体和关系契约保持领域中立。验收必须从自然语言输入开始，不能直接导入已经包含 F/L/P 的 fixture 来代替 LLM 生成。

## 6. SysML v2 子集与回读

当前导出仅把完整实体放在注释中，不能作为模型交换格式。本轮定义一个明确、确定性的文本子集：

- `package`；
- `part def` / `part` 表示 system、logical component、physical block；
- `requirement` 表示 requirement；
- `action` 表示 function；
- `interface` 表示 interface / functional flow；
- `satisfy`、`allocate`、`verify`、`validate` 表示核心追溯关系；
- `// @id:`、`// @kind:` 和 `// @payload:` 保存稳定 ID 与必要属性。

提供两个纯函数：

```python
graph_to_sysml(graph: ModelGraph) -> str
sysml_to_graph(text: str, project_id: str) -> ModelGraph
```

回读结果必须保留实体 kind、名称、稳定 ID、关键 payload 和上述关系。UI 提供导出和导入入口；回读后的图可以继续通过现有 ModelService 编辑，不自动锁定。

## 7. UI 与 API

默认分析页增加一个清晰的“生成完整 MBSE 模型”动作，提交自然语言需求后显示五段式进度和每层实体数量。结果页优先展示：

- R/F/L/P/V&V 五层是否完成；
- 完整/部分/缺失追溯数量；
- 可编辑的 ModelGraph；
- SysML v2 子集下载和重新导入；
- assumptions、open questions 和 review issues。

现有 Analysis、Model、Traceability 页面继续复用资源 API；旧的逐阶段运行入口收进高级调试区域，不从默认路径移除。

## 8. 验收标准

### 必须通过

1. 从一段自然语言需求开始，配置 LLM 后默认入口完成 R、F、L、P、V&V 五段生成。
2. 生成结果包含真实的 function、logical component、physical block、verification/validation case，不包含以 `候选` 或 `待确认` 作为唯一内容的占位实体。
3. 代表案例至少有一条完整 `R→F→L→P→V&V` 追溯链，且每个关键关系由 ModelGraph 真实保存。
4. 生成后的模型能在现有 Web UI 中查看和编辑，修改后 revision、来源和追溯仍然有效。
5. `graph_to_sysml` 生成明确的 SysML v2 子集文本；`sysml_to_graph` 回读后实体、关系和关键属性保持一致。
6. 无 LLM 配置时离线测试仍可运行，但验收报告明确区分离线规则结果和真实 LLM 结果。

### 不作为本轮门槛

- 23-task 全量多轮稳定性比例；
- 所有异常都进入复杂 FAILED/BLOCKED/DEGRADED 状态机；
- 多模型、多供应商、长文档和全量 SysML v2 语法覆盖。

## 9. 风险与处理

- LLM 阶段输出过长：用五段小契约和图摘要控制上下文；
- 名称不稳定导致重复：由编译器做同项目名称合并和稳定 ID；
- 某层语义不完整：记录 assumptions/open questions，允许继续推进并在追溯报告中标记 partial；
- 真实 provider 不可用：运行记录为 failed 并保留离线开发路径，不能把连接失败伪装成模型完成；
- 旧测试依赖 23-task：保留旧入口并单独标识，不让兼容性约束阻止新产品路径。
