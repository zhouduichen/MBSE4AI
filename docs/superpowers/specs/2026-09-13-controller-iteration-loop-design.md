# Controller 自动迭代闭环设计

## 背景

AI4MBSE 已经能够把自然语言、文档和已有 ModelGraph 输入到五阶段纵向生成链，并在生成结束后计算 Traceability、Methodology 和 Systems Engineering Controller 计划。当前 Controller 可以执行单个动作，但产品仍要求用户逐个点击动作；一次生成、方法论反馈、局部重分析和下一次质量评估没有被组织成一个统一的迭代操作。

这使系统更像“生成器加诊断面板”，还不像能够持续推进工程工作的 AI Systems Engineer。下一条切片将补足一个有界的控制闭环，同时保留用户对工程决策和输入的最终控制权。

## 目标

新增 Controller iteration 能力，使一次操作可以：

1. 读取当前 ModelGraph 并重新计算 Methodology findings；
2. 选择现有 Controller 排序后的最高优先级动作；
3. 对安全动作执行局部重分析或证据检索；
4. 重新计算 ModelGraph revision、Traceability、Methodology 和 Controller；
5. 在缺少用户决策/输入、没有进展或达到预算时明确暂停；
6. 返回每一轮动作、受影响阶段、修订变化和质量变化，供 API、Web 和审计使用。

“安全动作”定义为现有 `reanalyze` 和能够成功调用 Tool Layer 的 `collect_evidence`。`trade_study` 不自动选择方案，`collect_input` 不自动编造用户输入。

## 非目标

- 不引入新的后台队列、Worker 或持久化 Job 状态机；每个局部重分析继续使用已有 Run/Step/Patch/Revision 台账。
- 不让 Controller 绕过 CAS、PatchPolicy、LLM Compiler、Validator、Review 或锁定保护。
- 不让 LLM 直接决定要覆盖的实体；Methodology 负责发现缺口，Controller 负责有限动作路由，LLM 负责被选阶段的模型内容生成。
- 不自动选择物理 Trade Study、逻辑分区方案或修改 `locked`/`user_modified` 实体。

## 方案选择

### 方案 A：应用层有界迭代器（采用）

在 `ModelGenerationService` 中增加 `iterate_controller`，复用现有 `controller_plan` 和 `execute_controller_action`。每轮重新读取图和计划，执行一个安全动作，再用 revision 和 action fingerprint 检测是否真正取得进展。它不新增模型语义协议，能够直接复用当前 LLM Runtime、Tool Layer、CAS 和定向重分析路径。

### 方案 B：让 LLM 直接生成 Controller 计划

让模型输出下一阶段和动作列表，语义弹性更强，但会把已经确定的工程路由交给非确定输出，增加越权动作、重复迭代和无法复现的问题。它可以作为未来的建议来源，不能替代当前 Methodology/Controller 的确定性边界。

### 方案 C：后台作业驱动的长循环

可以支持长时间仿真和外部工具，但需要新的 Job、取消、恢复、租约和前端进度协议，超出当前“先打通可用纵向链”的范围。

## 架构与数据流

```text
当前 ModelGraph
      ↓
MethodologyEngine.analyze
      ↓
SystemsEngineeringController.plan
      ↓
最高优先级 ControllerAction
      ├── reanalyze ──────────────┐
      ├── collect_evidence ──────┤
      ├── trade_study → 等待用户  │
      └── collect_input → 等待用户│
                                    ↓
                  新 Revision / 新 Run / 新模型输出
                                    ↓
                    Trace + Methodology + Controller
                                    ↓
                         完成、等待或继续下一轮
```

应用层接口为：

```python
def iterate_controller(
    self,
    project_id: str,
    *,
    max_iterations: int = 3,
    expected_revision: int | None = None,
) -> Mapping[str, object]: ...
```

返回值至少包含：

```json
{
  "iteration_id": "controller-iteration-...",
  "project_id": "robot",
  "execution_status": "completed|awaiting_decision|awaiting_input|no_progress|max_iterations",
  "start_revision": 12,
  "revision": 14,
  "iterations": [
    {
      "sequence": 1,
      "action": {},
      "execution_status": "completed",
      "revision_before": 12,
      "revision_after": 14,
      "traceability": {},
      "finding_codes": []
    }
  ],
  "traceability": {},
  "methodology": {},
  "controller": {}
}
```

`max_iterations` 在应用层限制为 1 到 8。每轮执行前记录 action id、action kind、当前 revision 和 findings；如果相同 action 在相同 revision 上再次出现，或执行后 revision 没有增加，则返回 `no_progress`。如果计划没有动作，返回 `completed`；遇到 `trade_study` 返回 `awaiting_decision`；遇到 `collect_input` 返回 `awaiting_input`；达到预算返回 `max_iterations`。证据动作若 Tool Layer 返回等待状态，则保留其工具结果并返回等待状态；成功采集并完成重分析时才进入下一轮。

## 审计与错误处理

- 开始、每轮、等待、完成和无进展分别写入 `controller.iteration.*` audit event；事件中绑定 iteration id、revision、action、run id 和执行状态。
- 首轮 `expected_revision` 只校验一次；之后每轮从 Repository 读取最新 revision，并由现有 CAS 保护局部 Patch。
- 任意已有 `ContractViolation`、`ConflictError`、工具错误或重分析失败都沿现有 API 错误和 Run 状态返回，不吞掉为成功。
- 迭代器不把 `completed_with_warnings` 改成 `completed`；最终质量仍由 Traceability 和 Methodology findings 决定。
- 迭代结果只汇总现有对象，不另建第二份 ModelGraph 或复制 Patch。

## API 与工作台

新增：

```text
POST /projects/{project_id}/controller/iterate
body: {"max_iterations": 3, "expected_revision": 14}
```

Analysis 页面在 Controller 区域增加“自动推进安全动作”入口。它显示运行中的迭代状态、已执行轮数、revision 变化、Traceability 摘要和停止原因；Trade Study 选项继续使用现有单动作按钮，以便用户明确选择。已有单动作 `/controller/execute` 保持兼容。

## LLM 边界

当当前 profile 是结构化 LLM Runtime 时，`reanalyze` 或证据触发的定向重分析仍按既有 Stage Prompt → TaskProposal → Compiler → Patch 路径执行；`iterate_controller` 不另造聊天接口。离线 Rule Runtime 也经过同一应用编排，因此可以复现控制流、停止条件和追溯变化，但不会伪造缺失的工程证据或物理测量结果。

## 测试与验收

- 应用层：无动作时立即完成；安全 `reanalyze` 可以产生新 revision 并重新计算报告；重复 action 无 revision 增长时返回 `no_progress`；达到 max iterations 返回 `max_iterations`。
- 决策边界：`trade_study` 返回 `awaiting_decision` 且不改图；`collect_input` 返回 `awaiting_input`；证据工具等待态不会继续盲跑。
- API：新 endpoint 接收 revision 和预算，返回统一 iteration payload；过期 revision 返回冲突；旧 `/controller/execute` 测试保持通过。
- 工作台：页面包含自动推进入口和停止状态，并保留 Trade Study 用户决策入口。
- 回归：单需求、多需求、已有 SysML 种子、交付包、SysML 往返、五阶段 LLM 调用、全量 pytest、compileall、Ruff、Import Linter 和架构指标保持通过。
