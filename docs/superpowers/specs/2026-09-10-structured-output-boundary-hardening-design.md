# PR09：Structured Output Boundary Hardening 设计规格

日期：2026-09-10  
状态：待用户评审

## 1. 背景与问题判定

真实 Ollama 运行已证明连接链路可用：

- provider：`ollama`
- model：`qwen3.5:9b-q8_0`
- invocation 与 prompt delivery：通过
- JSON/schema conformance：失败
- proposal 到 Patch：失败
- 完整 MBSE workflow：不接受

回归运行 `run-07efa6e07f0a6b14` 保留在本地项目数据库中。运行中出现过三类关键错误：

- `LLM response is not valid JSON after one repair`
- `LLM response schema is invalid`
- `task patch field is required: kind`

其中 `kind` 缺失不是单纯的提示词问题，而是协议边界设计问题：模型被要求直接输出 Harness 内部的 Patch operation。PR09 的目标是把模型的不确定性限制在“工程语义提案”内，把 Patch 的协议、身份、版本和状态全部收回 Harness。

## 2. 目标与非目标

### 目标

建立并验证以下稳定边界：

```text
LLM
  ↓ 仅输出 TaskProposal
JSON decode / schema validation
  ↓ 结构失败只做有限 structural retry
Harness-owned Proposal Compiler
  ↓ 生成 canonical Patch
Domain / semantic validators
  ↓
CAS repository apply
```

具体目标：

1. LLM 不再拥有 `op`、Patch ID、`project_id`、`base_revision`、`producer`、默认 `status` 或版本字段的决定权。
2. Ollama 请求实际使用 provider-level JSON Schema `format`，而不是仅依赖 prompt 中的 JSON 指令。
3. JSON 解析/schema 校验失败与 MBSE 语义失败分离；结构失败不得进入 `Gate → Semantic Repair`。
4. structural retry 有明确上限，失败运行必须终止在可审计的 degraded 状态。
5. 先提供三类 Task 的小型 Contract Conformance Benchmark，再恢复 23 Task 完整生命周期。
6. 保存故障原文、schema/prompt hash、模型和 retry ledger，使失败可复现、可比较。

### 非目标

- 不修改 Track A 的既有能力评分及 `41.31/100 REJECTED` 结果。
- 不把 Harness deterministic harness status 与 MBSE capability score 合并。
- 不扩展 Agent 系统，不引入新的异步执行架构。
- 不在 PR09 中进行模型排行榜、模型替换或 Simulation/MDO 实现。
- 不修改现有 `tests/mbse_benchmark/` 工作区中的未提交用户改动。

## 3. TaskProposal 协议

LLM 的顶层输出改为 `TaskProposal`，只表达当前 Task 的工程语义：

```json
{
  "entities": [
    {
      "ref": "e1",
      "kind": "requirement",
      "name": "系统应在任务窗口内完成投递",
      "payload": {
        "text": "系统应在任务窗口内完成投递",
        "obligation": "shall"
      },
      "confidence": 0.9,
      "source_ids": [],
      "evidence_ids": [],
      "lifecycle_ids": []
    }
  ],
  "relations": [
    {
      "source_ref": "e1",
      "predicate": "satisfiedBy",
      "target_ref": "existing-function-id",
      "evidence_ids": []
    }
  ],
  "updates": [
    {
      "entity_id": "existing-entity-id",
      "field_patch": {"payload": {"priority": "high"}}
    }
  ],
  "deprecations": [],
  "reason": "从当前上下文提取需求并建立可追溯关系"
}
```

### 3.1 模型可声明的内容

- 新实体的语义 `kind`、名称、payload、confidence。
- 新实体引用的 `source_ids`、`evidence_ids`、`lifecycle_ids`。
- 关系的源/目标引用、predicate 和 evidence。
- 对现有实体的受限字段更新。
- 对现有实体的弃用请求。
- 面向审计的 reason。

`kind` 仍然属于工程语义，因此由模型提出、由 schema 和 Task policy 校验；但 `AddEntity` 这个 operation discriminant 不再由模型输出。

### 3.2 Harness 必须拥有的内容

Compiler 确定性生成：

- `AddEntity`、`UpdateEntity`、`Relate`、`Deprecate` operation 类型。
- Patch ID、Task ID、`project_id`、`expected_revision`/base revision。
- `Producer.LLM`、默认 `EntityStatus.CANDIDATE`、创建/更新时间和当前 revision。
- 实体 ID 的 canonical 生成与 proposal `ref → entity_id` 映射。
- operation 顺序、最大 operation 数、允许写入范围和 predicate policy。

模型返回旧的 `operations` Patch envelope 不再走兼容编译路径；它应在 proposal schema 阶段被拒绝，避免继续依赖“补一个 `kind`”的脆弱修复。

## 4. 编译器与验证流程

新增 Proposal 解析与编译层，建议放在 `src/rflp_lite/methodology/proposal_compiler.py`，由 `TaskProposal`、proposal parser 和 compiler 组成。

编译步骤固定为：

1. 使用当前 Task 的 proposal schema 做 JSON Schema 校验。
2. 解析为类型化的 `TaskProposal`，拒绝未知字段、未知 entity kind、非法 confidence 和不完整引用。
3. 先根据 kind/name/source/lifecycle 生成新增实体的 canonical ID，再建立 `ref → ID` 表。
4. 将关系引用解析为新增实体 ID 或当前上下文中的既有实体 ID；未知引用直接报告 compiler failure。
5. 根据当前 `PatchPolicy` 检查 writable kinds、fields、predicates、scope 和 operation 上限。
6. 由 Harness 构造领域 Patch；不接受 proposal 中的内部 Patch 元数据。
7. 按现有 schema、identity、reference、evidence、semantic、patch_policy validators 验证。
8. 只有全部通过后才允许 repository CAS apply。

编译器必须是纯确定性逻辑：相同 request context、proposal 和 policy 应生成相同的 canonical Patch。模型输出 hash、proposal hash 和编译结果 hash 进入执行记录。

## 5. 结构失败与语义失败

### 5.1 结构阶段

结构阶段包含：

```text
raw model response
  → JSON decode
  → proposal schema validation
  → structural retry（最多 1 次；配置可提升到 2，但默认不得超过 1）
```

`OpenAICompatibleModel` 对失败应抛出带分类的 `StructuredOutputFailure`，至少记录：

- `stage=structural`
- `code=json_decode` 或 `schema_validation`
- 有界长度的 raw response
- `schema_hash`
- `retry_count`
- provider/model

TaskExecutor 不得对 structural failure 再做一次完整 Task retry，避免一次结构失败被放大为多次 LLM 调用。达到上限后直接返回 degraded response，并保留 diagnostics。

### 5.2 编译与领域阶段

Proposal schema 通过后，compiler failure 使用独立的 `stage=compiler`；例如未知 ref、超出 policy、关系端点类型不允许。它也不得进入 MBSE semantic repair。

只有 proposal 已经成功编译成 Patch、且领域 validators 报告真实的业务语义问题时，才允许进入现有的 semantic repair。semantic repair 仍然通过 Task/RepairStrategy 产生新的 `TaskProposal`，而不是绕过边界直接产生任意 Patch。

Workflow 在收到 `structural` 或 `compiler` failure 时：

- 记录失败步骤和 gate 诊断；
- 不调用 `LifecycleOrchestrator.repair()`；
- 不把缺失输出伪装成 semantic issue；
- 在明确的 retry 上限内结束本次 run。

## 6. Ollama provider 行为

Ollama 继续使用当前 `qwen3.5:9b-q8_0` 做 PR09 压力测试。对于 local/Ollama transport：

- `format` 传入 TaskProposal 的 JSON Schema；
- `stream=false`、`think=false`；
- 当前确定性采样设置保持 `temperature=0`；
- response schema 的 canonical 版本用于本地 post-validation；
- transport grammar 的兼容裁剪不得改变 canonical schema hash；
- adapter 测试必须断言实际请求体存在 `format`，而不是只断言 prompt 含有 JSON 文本。

其他 OpenAI-compatible provider 可以复用统一接口，但不得降低 Ollama 路径的 provider-level constraint。需要 provider-specific 行为时，放在 transport adapter 内，不把约束逻辑散落到 Task prompt。

## 7. Contract Conformance Benchmark

新增独立于现有 MBSE benchmark 的小型 conformance runner，目录建议为 `tests/contract_conformance/`，结果写入独立的 PR09 artifact 目录，不触碰 `tests/mbse_benchmark/`。

首批 Task 固定为：

- `system_definition`
- `stakeholder_requirements`
- `function_identification`

每个 Task 默认重复 20 次；live LLM 运行通过显式开关启用，不纳入普通单元测试。每条样本记录：

- run/sample/task id
- provider、model、sampling 参数
- prompt hash、canonical schema hash
- raw response 或有界的失败原文
- JSON parse、schema、compile、domain validation 结果
- structural retry 次数
- diagnostics/repair ledger

输出指标定义：

| 指标 | 定义 |
| --- | --- |
| `json_parse_rate` | raw response 可被 JSON decoder 解析的样本比例 |
| `schema_pass_rate` | 通过 TaskProposal canonical schema 的样本比例 |
| `proposal_compile_rate` | 成功编译为 canonical Patch 的样本比例 |
| `domain_validation_rate` | Patch 通过领域 validators 的样本比例 |
| `first_pass_success_rate` | 无 structural retry 且前述阶段全部成功的比例 |
| `structural_retry_rate` | 至少触发一次 structural retry 的样本比例 |

只有结构层接近 100%，且 compiler/domain 指标稳定后，才重新执行 23 Task 完整生命周期。该 benchmark 不改变 Track A 分数，只回答“结构化输出边界是否可靠”。

## 8. 回归运行保留策略

不删除或重写 `run-07efa6e07f0a6b14` 对应的数据库。新增 PR09 regression manifest，记录：

- run id 与项目数据库位置；
- provider/model；
- 已观察到的三类失败代码；
- 原始 run 的步骤、prompt hash、task id 和 retry/repair 状态（现有记录能提供的部分）；
- PR09 后的预期行为：同类旧 Patch-shaped 输出或非法 proposal 不得穿过 Structured Output Boundary，也不得触发 semantic repair。

旧 run 中如果没有完整 raw response，则不臆造恢复内容；从 PR09 开始，`StructuredOutputFailure` 必须把有界 raw response 写入 diagnostics，供后续 fixture 导出和回放使用。

## 9. 测试与验收标准

### 单元与集成测试

1. proposal schema 要求 entity `kind`，但不接受顶层 `operations` Patch envelope。
2. 合法 proposal 能编译出正确的 `AddEntity`/`Relate`/`UpdateEntity`/`Deprecate`。
3. Patch 的 producer、status、project、revision、operation discriminant 和 ID 不受模型字段覆盖。
4. 新增实体 ref、既有实体 ID、未知 ref 的解析行为确定且有测试。
5. policy、scope、endpoint 和 operation limit 违规在 compiler/validator 阶段被拒绝。
6. Ollama 请求真实携带 proposal schema `format`。
7. 非法 JSON 或 schema invalid 最多发生配置上限内的 structural retry，且不会调用 semantic repair。
8. structural/compiler failure 的 run 可结束为 degraded，不会长期停留在 `repairing`。
9. diagnostics 包含 raw response、failure code、schema hash、retry count 和模型元数据。
10. conformance runner 能产出六项指标及逐样本 ledger。

### PR09 通过条件

- 三类 Task 的 contract benchmark 能重复运行并生成可审计结果。
- Ollama schema constraint 已由请求体测试和一次 live sample 双重确认。
- 旧故障类型被隔离在结构/编译边界，不能进入 semantic repair。
- 默认 structural retry 有硬上限，失败 run 能确定性收口。
- 所有相关测试通过，且现有 PR08/UI 和 benchmark 未提交工作区改动保持不变。
- 在上述条件满足前，不宣称 23 Task full workflow accepted。
