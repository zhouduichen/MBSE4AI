# 设计审查决策同步 ModelGraph 设计

## 背景

DFM/DFA Review 当前会把 finding 决策保存到 DetailDesignStore，但 CAD 模型应用后，`PhysicalBlock.payload.design_review` 是当时的快照。用户确认、误报或关闭 finding 后，ModelGraph、SysML 和工程交付包仍可能展示旧的风险状态。

## 设计

`DesignReviewService.update_finding` 继续先生成不可变的 Review 新版本，然后查找当前 ModelGraph 中与 `review_id` 或 `model_id` 对应的 CAD `PhysicalBlock`。若存在非锁定实体，使用 `Patch(UpdateEntity)` 将完整更新后的 review 写回 `payload.design_review`，因此同步具备 CAS revision、审计和交付包可见性。若实体已锁定，拒绝同步写入，避免绕过 ModelGraph 锁定策略；Review Store 不产生一个看似成功但无法回写的分裂事实。

Finding 决策只改变 finding 状态和 Review 汇总状态，不自动修改几何、标注或工程规则结论；重新生成模型后仍需重新执行 Review。锁定实体保持只读，用户必须先走既有解锁流程。

## 验收边界

离线 preview 验收覆盖：生成 CAD 模型并执行 Review → 应用到 ModelGraph → 确认/关闭 finding → 重新读取 ModelGraph、SysML 和交付包，三者均反映新状态；测试不启动 LLM、服务器、SSH 或 FreeCAD。
