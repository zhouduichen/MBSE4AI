# Intelligent MBSE Discovery Verification

日期：2026-08-11

范围：从“设计一款城市医疗用途的飞行汽车”生成带来源、假设、置信度和覆盖状态的候选；逐项审核后构造 accepted graph；从同一 graph 生成确定性 SVG。

已验证：

- 领域包包含医疗、运营、监管、公众、气象、通信导航、能源、维修等利益相关方，以及雨天、低能见度、夜间、雷暴、通信/导航丢失、动力与起降点故障场景维度。
- v2 工作区迁移到 v3 时保留既有 MBSE/RFLP 字段。
- 应用层只依赖 generative/renderer ports；模型和 SVG 位于 adapters。
- 未审核候选不会进入 accepted graph；编辑上游候选会将派生下游标记为 stale。
- SVG 输出转义文本并携带 `data-source-id`，相同 accepted graph 输出字节稳定。

主要验证命令：

```bash
.venv/bin/python -m pytest -v
.venv/bin/lint-imports
.venv/bin/python -m build
```

非目标：本垂直切片不替代正式适航认证、安全论证或工程基线审批；模型输出不应直接部署，必须经过领域专家审核。
