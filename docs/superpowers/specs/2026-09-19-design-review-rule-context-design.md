# DFM/DFA 规则上下文与风险摘要设计

## 背景

当前 `PreviewDesignRuleAdapter` 能检查材料缺失、壁厚、圆角、孔边距、工具可达性和 profile 特征，但阈值固定在代码中，审查请求只携带标注，没有材料工艺、规则集或装配接口上下文。结果虽可回写 ModelGraph，却难以说明“使用了哪套规则、风险集中在哪里、装配接口是否完整”。

## 目标

1. 通过有限的 `rule_set` 选择材料/工艺阈值，未知规则集显式产生 finding，不静默采用错误标准。
2. 支持 `assembly_interfaces` 声明，检查所需接口是否在模型特征中存在。
3. 结果保留规则集、版本、按严重度/类别汇总和稳定 evidence hash。
4. 风险高亮 SVG 继续由同一 findings 生成，并显示每个零件的 high/critical 数量。
5. 保持 development evidence 和人工复核边界；不宣称正式制造批准。

## 接口

审查上下文可来自模型 payload 的 `design_review_context`，也可以由调用方传入：

```json
{
  "rule_set": "cnc_machined",
  "assembly_interfaces": [
    {"part_id": "housing", "feature_id": "mounting-hole-1", "interface": "mounting", "required": true}
  ]
}
```

首批内置规则集为 `generic_preview`、`cnc_machined` 和 `additive_preview`。阈值只影响确定性 finding 的 evidence 和消息；规则集不改变 CAD 几何，也不自动关闭 finding。

## 验收

- 同一个薄壁模型在 `generic_preview` 与 `cnc_machined` 下得到不同但稳定的阈值证据。
- 未知 `rule_set` 产生 `ruleset.unknown` finding，审查状态为 `needs_review`。
- 缺失必需装配接口产生 `dfa.assembly_interface` finding，并包含 part/feature/interface evidence。
- 审查 artifacts 包含规则集、规则版本、finding summary 和稳定 `evidence_hash`；风险 SVG 与 findings 使用同一输入。
- 既有 3.1/3.2、ModelGraph 回写、SysML/交付包和全量离线验证保持通过。
