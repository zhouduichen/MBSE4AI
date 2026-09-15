# LLM Controller 决策提案设计

## 状态

设计规格，待用户确认后进入实施计划。

## 目标

在现有确定性 `SystemsEngineeringController` 之上增加一个可选的 LLM Controller 提案层，使 AI4MBSE 能根据当前 Typed ModelGraph、Methodology findings 和影响链提出下一步工程动作，同时保持 ModelGraph、CAS、Review 和 Trade Study 的现有权威边界。

本切片完成后，用户能够看到：

```text
当前模型问题
    ↓
LLM Controller 提案
    ↓
确定性校验
    ↓
用户确认动作/方案
    ↓
现有局部重分析或证据流程
```

LLM 只提出动作，不直接改写模型、不直接选择 Trade Study 方案，也不取代确定性 Controller 对可执行动作的事实约束。

## 当前缺口与复用边界

当前系统已经具备：

- `MethodologyEngine.analyze(graph)`：生成逻辑/物理/V&V findings、指标、架构候选和影响链；
- `SystemsEngineeringController.plan(graph, report)`：将 findings 映射为确定性 `ControllerAction`；
- `ModelGenerationService.execute_controller_action(...)`：执行安全动作，或等待用户选择 Trade Study/补充输入；
- `reanalyze(...)`、PatchPolicy、Compiler、Validator、CAS 和审计链；
- OpenAI-compatible `GenerativeModel.complete_json(GenerationRequest)` 及远程 Profile 选择。

本切片不重新建设上述能力，只为用户可见的 Controller 计划增加一个受约束的 LLM recommendation overlay。确定性 `ControllerAction` 列表仍是可执行动作的唯一目录。

## 用户体验

用户在 Analysis 或 Controller 页面看到：

```text
确定性发现：物理候选超过功耗约束
LLM 建议：先比较替代物理候选，再重新验证受影响需求
建议动作：controller-action-...
建议方案：trade-option-...
理由：当前影响链覆盖 Requirement → Function → Logical → Physical → V&V
假设：功耗实测值仍需确认
待补输入：确认是否允许替代计算平台
```

用户点击确认后仍通过现有 `controller/execute` 接口提交 `action_id` 和可选 `option_id`。如果建议的是 Trade Study，缺少 `option_id` 时只能展示等待状态；LLM 提案不会绕过用户确认自动执行。

没有配置远程 LLM 时，页面继续显示确定性 Controller；不把离线 RuleRuntime 的结果伪装成 LLM 提案。远程 Provider 不可达或返回非法提案时，系统保留确定性计划并显示有界的 `fallback` 诊断，不阻断已有模型生成结果。

## 提案契约

新增内部值对象 `ControllerProposal`，只表达对已有动作目录的引用：

```python
@dataclass(frozen=True, slots=True)
class ControllerProposal:
    status: str  # proposed | fallback | not_configured | not_needed
    action_id: str | None
    option_id: str | None
    rationale: str
    assumptions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    input_hash: str = ""
    output_hash: str = ""
```

`ControllerPlan` 增加可选 `proposal` 字段；其 `actions`、`next_action`、`impacted_entity_ids` 和 `impacted_stages` 语义保持不变。序列化时以 `llm_proposal` 字段附加提案，不改变现有 action JSON。

LLM wire payload 不是新的 ModelGraph 对象，也不允许携带 Patch/Revision/Entity payload。响应 schema 只允许：

```json
{
  "action_id": "controller-action-...",
  "option_id": "trade-option-...",
  "rationale": "简体中文工程理由",
  "assumptions": ["..."],
  "open_questions": ["..."]
}
```

`action_id` 和 `option_id` 可以为 `null`，自然语言字段有长度和数组上限。LLM 不返回 `kind`、`task_id`、`stage`、`entity_ids` 或任何可执行字段；这些字段始终从确定性 action catalog 查回。

## LLM Controller 服务

新增独立的 `LLMController`（或等价的单一职责服务），接口为：

```python
def propose(
    self,
    graph: ModelGraph,
    report: MethodologyReport,
    plan: ControllerPlan,
) -> ControllerProposal:
    ...
```

服务行为：

1. 若没有 provider model，返回 `not_configured`，不产生网络调用。
2. 若 `plan.actions` 为空，返回 `not_needed`，不产生网络调用。
3. 构造有界 Controller context：项目 ID、revision、snapshot hash、系统目标摘要、active entity 的 ID/kind/name/status、关系摘要、Methodology findings、关键 metrics、impact paths 和完整的确定性 action/option catalog。实体、关系、findings 和文本数组分别设置固定上限，避免把完整数据库 payload 无界发送给 Provider。
4. 通过现有 `GenerationRequest` 和 `GenerativeModel.complete_json` 调用远程模型，使用专用 `controller.proposal.v1` schema 和有限 output budget；不直接调用 HTTP、Ollama 或本地 endpoint。
5. 对返回 JSON 做契约校验，再验证 `action_id` 属于 `plan.actions`，`option_id` 属于该 action 的 options；校验失败返回 `fallback`，不把模型返回的未知 ID 传给应用层。
6. 校验成功后从确定性 action catalog 复制动作语义，只保留 LLM 的理由、假设和待补问题，返回 `proposed`。
7. 对 Transport、结构化响应、schema 或未知引用错误只保存错误码、provider/model 和 hash/size 摘要，不保存无界原始响应；确定性计划仍正常返回。

提案服务不持久化新的 ModelGraph 节点或数据库表。提案随当前 API/运行结果返回，并以受限审计事件记录输入/输出 hash、选定 action/option、provider/model 和状态。

## 运行时装配

`RuntimeFactory` 对配置的 OpenAI-compatible Profile 只创建一个共享 provider model：

```text
OpenAICompatibleModel
   ├── StructuredModelRuntime       → 五阶段模型生成
   └── LLMController                → Controller 提案
```

离线 `RuleRuntime` 不提供 LLM Controller model，保持现有可复现测试路径。运行时选择结果向 `ModelGenerationService` 注入可选提案服务；注入的测试 double 只实现现有 `GenerativeModel` port，不触碰本机模型。

## 应用流程

### 生成完成后的 Controller

五阶段生成完成后，应用先按现有逻辑计算 `MethodologyReport` 和确定性 `ControllerPlan`，再在配置了远程 model 时附加一次 `ControllerProposal`。LLM 提案失败不会把已经完成的 R→F→L→P→V&V 运行改成失败。

### Controller 查询

`GET /projects/{project_id}/controller` 和现有 Analysis/API 结果复用同一投影逻辑，返回确定性 action catalog 及 `llm_proposal`。同一个 revision 上重复查询可以重新生成提案，但不得改变 ModelGraph；实现可以在请求级复用结果，不新增持久化状态。

### 用户确认与执行

现有 `POST /projects/{project_id}/controller/execute` 保持兼容，并继续以确定性 plan 查找 `action_id`/`option_id`。只有用户明确提交合法 ID 后，才调用现有证据采集、Trade Study 决策或局部 `reanalyze`；LLM 的 rationale 不作为执行权限。

`iterate_controller` 的自动安全迭代仍只使用确定性 `next_action`，不把 LLM 提案当作自动执行指令，避免模型输出改变自动迭代的可复现性和安全边界。

## 错误与降级

| 情况 | Controller 结果 | ModelGraph | 用户动作 |
|---|---|---|---|
| 没有配置 Profile | `not_configured` | 不变 | 使用确定性 action |
| 没有 findings/action | `not_needed` | 不变 | 继续查看或结束 |
| 远程网络/Provider 失败 | `fallback` + code | 不变 | 使用确定性 action 或等待 |
| JSON/schema 非法 | `fallback` + code | 不变 | 使用确定性 action 或重试查询 |
| action/option 未知 | `fallback` + invalid reference code | 不变 | 不执行该提案 |
| 合法提案 | `proposed` | 不变 | 用户确认后执行 |
| 用户确认后 CAS/重分析失败 | 走现有失败路径 | 按现有 CAS 语义 | Review/Controller 继续处理 |

提案服务永远不返回可提交 Patch。所有实际模型变化仍只能经现有 Compiler、Validator、PatchPolicy 和 CAS。

## 验收标准

1. 配置的远程 provider 对包含物理冲突和 V&V 失败的 ModelGraph 生成合法 `ControllerProposal`；提案只能引用确定性 action/option，返回完整理由和有限的待补问题。
2. LLM 返回未知 action 或 option 时，API 返回 `fallback`，不产生异常动作、不修改图、不触发 reanalysis。
3. 合法 Trade Study 提案在用户未提交 `option_id` 时只返回 `awaiting_decision`；提交合法 option 后复用现有定向重分析，产生新 revision 和审计记录。
4. 五阶段自然语言/结构化验收仍保持完整 R→F→L→P→V&V、SysML 往返和可编辑 revision；Controller 提案附加失败不能破坏主链。
5. 离线 RuleRuntime 不产生网络调用，现有 deterministic Controller/iterate_controller 行为保持不变。
6. API 和 Analysis 页面显示 `llm_proposal` 的状态、理由、假设和待补输入，但不暴露 TaskSpec、Patch、CAS 或原始凭据。
7. 全量 pytest、compileall、Ruff、architecture metrics、import-linter 和 `git diff --check` 通过；真实 Provider smoke 只在远程 SSH 节点在线时执行，不调用本机模型。

## 测试策略

- `LLMController` 单元测试：无 provider、无动作、合法提案、未知 action、未知 option、远程失败和有界 diagnostics；验证 revision 不变。
- Runtime 装配测试：配置 Profile 的同一 OpenAI-compatible model 同时服务结构化生成和 Controller proposal；offline 选择不创建 provider model。
- Application 测试：五阶段生成后附加合法 proposal；proposal 失败时主生成仍完成；用户确认 Trade Study 后仍进入已有 reanalysis。
- API/Web 测试：Controller 查询暴露 proposal，执行接口只接受确定性 action/option，旧接口响应保持兼容。
- 全量回归：继续验证多需求 V&V 批处理、追溯、SysML round-trip、交付包、CAS、锁定保护和现有迭代停止条件。
