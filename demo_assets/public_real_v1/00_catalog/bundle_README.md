 # 公开真实资料测试包 - AI4MBSE 1.x + 2.x

生成日期：2026-09-01

这个包专门用于当前项目的 1.1 / 1.2 / 2.1 / 2.2 演示测试。

## 目录

- `manifests/requirements_sources_manifest.csv/json`：真实公开的 NASA/FAA 需求、ConOps、FRD、法规资料索引，其中包含真实公开 DOCX。
- `data/historical_uav_public_facts.csv/json`：9 型真实公开无人机的统一事实字段，无空单元格。
- `data/fixed-wing-schemes-public-demo.json/csv`：可直接用于当前 `fixed-wing-v1` 历史方案导入的完整数据，无空字段。
- `data/materials_public_reference.json`：NASA/Hexcel 公开材料参考数据。
- `data/atmosphere_public_reference.json`：NASA 标准大气海平面参数。
- `data/test_prompts.json`：3 条一句话端到端测试 Prompt。

## 数据真实性规则

`historical_uav_public_facts.*` 只放统一后的公开事实或单位换算/区间中点，所有行都有来源。

当前项目的 `fixed-wing-v1` 还强制要求公开资料通常不会给出的字段，例如 `wing_area_m2`、`section_modulus_m3`、`cg_x_m`。因此 `fixed-wing-schemes-public-demo.*` 为了“无缺失且能直接跑”采用三类值：

1. **published**：公开来源直接给出的真实值；
2. **derived**：只由公开值做确定性换算/计算，例如 MTOW-payload；
3. **demo_assumption**：只用于软件演示的工程占位值，字段中明确写明推导规则，绝不能作为真实飞机数据或 formal 工程证据。

尤其注意：多数型号的 `空机质量` 在当前导入文件里实际是 `MTOW - 最大任务载荷` 的“非任务载荷质量代理”，以便当前 2.2 的 `mass + payload` 计算回到真实公开 MTOW。MQ-1B 是例外，它有 USAF 公开空重。

## 推荐测试顺序

1. 从 `requirements_sources_manifest` 下载 REQDOC-01、02、06、07：分别测试复杂需求 PDF、ConOps 场景、长法规 PDF、真实 DOCX。
2. 导入 `fixed-wing-schemes-public-demo.json` 作为历史方案库。
3. 先运行 `PROMPT-TACTICAL-ISR`，观察是否优先命中 Tactical Heron / TB2 / Hermes 450。
4. 再运行 `PROMPT-MALE-ISR`，观察是否命中 Heron / Hermes 900 / MQ-1B。
5. 对候选运行 2.2；所有内置评估器仍应保持 `development_only`。

## 重要边界

这套数据可以验证“系统流程、追溯、检索、候选生成、批量评估、Pareto、证据治理”。它不能把当前低阶气动/结构模型变成正式 CFD/FEA，也不能把 demo_assumption 变成真实飞机内部设计参数。
