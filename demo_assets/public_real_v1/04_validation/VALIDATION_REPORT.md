# AI4MBSE public-real-v1 验证报告

验证日期：2026-09-01  
目标版本：当前工作区代码 / `fixed-wing-v1` 领域包  
SQLite：`workspaces/public-real-v1/.rflp/model.db`

## Dataset

| 项目 | 数量 | 结果 |
|---|---:|---|
| 官方原始文档 | 8（7 PDF、1 DOCX） | 已下载到 `05_original_sources/`，未覆盖原文件 |
| 历史公开飞机事实 | 9 | JSON/CSV 均保留行级 `source_url`、authority、provenance |
| 可运行固定翼方案 | 9 | JSON/CSV 均可由当前 importer 读取 |
| 材料参考 | 2 | Aluminum 7075-T6、HexPly 8552 |
| 大气参考 | 1 组海平面参数 | NASA 公共标准大气来源 |
| 端到端 Prompt | 3 | Tactical ISR、MALE ISR、High Payload 边界测试 |

原始文档的 SHA-256 在 `00_catalog/catalog.json` / `catalog.csv` 中维护。原始包未修改。

## 1.1 需求分析

核心 smoke test 已使用项目的 `LocalDocumentParser` 和现有工作台链路，并将三份文档的工件、页面区域、需求候选与 provenance 写入 SQLite workbench：

| 文档 | 解析结果 |
|---|---|
| REQDOC-01 | 106 页、5,212 个区域/需求候选、0 diagnostics |
| REQDOC-02 | 80 页、2,358 个区域/需求候选、8 个 `pdf_page_hybrid_ocr` diagnostics；解析成功 |
| REQDOC-07 | 1 页、80 个区域/需求候选；DOCX ingestion 成功 |

三份核心文档合计 7,650 个区域/结构化需求候选，全部保留 artifact SHA-256、定位信息和源文档关系。其余 5 份官方原始文档也通过同一 parser 做了格式 smoke check：

```text
REQDOC-03: 56 pages / 1,678 regions / 7 diagnostics
REQDOC-04: 54 pages / 2,317 regions / 2 diagnostics
REQDOC-05: 51 pages / 2,053 regions / 1 diagnostic
REQDOC-06: 104 pages / 4,551 regions / 0 diagnostics
REQDOC-08: 37 pages / 1,092 regions / 0 diagnostics
```

REQDOC-02 的 sparse-page OCR 路径曾暴露 RapidOCR ndarray 坐标兼容问题；已在 `src/rflp_lite/adapters/documents/ocr.py` 增加安全的 array-like 坐标展开，并有回归测试。原始 PDF 没有被 OCR 覆盖。

## 1.2 MBSE / ConOps 场景

REQDOC-02 已进入 workbench，并完成现有语义 MBSE 生成：

- actors：27
- use-case flows：7,650
- activities：15,300
- lifelines：28
- sequence messages：7,650
- MBSE model status：`accepted`

所有 7,650 个 use-case flow 都有对应 activity，并共享 `canonical_flow_id` / `canonical_flow_hash`；sequence message 和 requirement id 也保留在同一语义模型中。源文档区域中检出 `lost-link` 4 次（含连字符和空格写法）、`contingency` 42 次、`BVLOS` 55 次。

说明：当前实现把场景表达为 use-case flow；`workbench.scenarios` 独立集合没有被自动填充，因此这里不将其误报为独立的 scenario 表。原文、actor、流程与跨视图 canonical flow 仍可追溯。

## 2.1 概念方案

使用当前源码中的 `import_scheme_rows` 和 `fixed-wing-v1` pack 验证：

```text
JSON input rows: 9
JSON imported records: 9
JSON rejected: 0
CSV input rows: 9
CSV imported records: 9
CSV rejected: 0
```

JSON 方案已正式写入 SQLite `scheme_records`，共 9 条；数据库同时保存固定翼领域包 revision。

Tactical ISR 指标包络的相似检索 Top 5：

1. Bayraktar TB2（0.929511）
2. Hermes 450（0.855816）
3. IAI Tactical Heron（0.818832）
4. MQ-1B Predator（0.653856）
5. Hermes 900（0.563233）

随后实际生成 5 个候选布局；每个候选都带有 envelope、reference scheme、parameter source、SVG layout manifest 和 hard-constraint 结果。验收检查通过：候选数量、多样性、硬约束、来源追溯、可复现性和 layout manifest 均为 `true`。

## 2.2 多学科评估

已将 Tactical ISR 运行结果写入 SQLite，运行 id 为 `FW-RUN-b39e6fd111bb`：

| 项目 | 结果 |
|---|---:|
| 候选 | 5 |
| 气动评估 | 5 |
| 结构评估 | 5 |
| 重量/重心评估 | 5 |
| 总评估数 | 15 |
| succeeded | 15 |
| failed | 0 |
| optimization runs | 1 |
| Pareto front candidates | 4 |
| evaluator evidence status | `development` |
| formal status | `development_only` |

内存验收还验证了 structures 单学科失败时气动和重量/重心仍能成功、缓存身份稳定、优化/Pareto 轨迹存在。所有评估都保留 `no customer approval entry` 诊断；没有把内置 evaluator 标成 formal。

## Data Integrity

可运行方案的字段级 provenance 注释统计如下（不是把复合文件误算成单一事实等级）：

```text
published:       1 annotation（MQ-1B published empty weight）
derived:        17 annotations（非任务载荷代理、允许应力等）
demo_assumption: 27 annotations（翼面积、截面模量、CG 等）
```

9/9 个方案行都含有显式 `demo_assumption`，9/9 个方案行都含有 derived 信息。`fixed-wing-schemes-public-demo.*` 在 catalog 中标为 `demo_assumption`，因为它是包含 published、derived 和 demo_assumption 的复合可运行层；这不表示所有字段都是占位值。

`demo_assumption` 仅用于软件功能演示，不是原型号真实内部设计参数。当前未创建或修改任何 3.x CAD/GD&T/DFM-DFA 内容。
