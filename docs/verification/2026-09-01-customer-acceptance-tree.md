# 1.x/2.x 客户验收需求树验证记录

**日期：** 2026-09-01  
**范围：** 1.1、1.2、2.1、2.2；明确不包含 3.1～3.3

## 正式需求树

`requirements-gold-v3.json` 现在包含 29 条原子条款，分为四个父节点：

| 父节点 | 原子条款数 | 验收方式 |
|---|---:|---|
| 1.1 需求文档自动捕获与结构化 | 8 | 文档解析、实体/属性/约束、MBSE 映射和追溯证据 |
| 1.2 MBSE 用例模型智能辅助构建 | 6 | 场景、Use Case、Activity、Sequence、编辑 CAS 和追溯 |
| 2.1 总体概念参数布局生成 | 7 | 指标包络、历史方案、3～5 候选、二维草图、差异和来源证据 |
| 2.2 多学科快速评估与优化反馈 | 8 | 三学科批量编排、失败隔离、缓存、汇总、Pareto 和证据状态 |

Gold v3 通过 `tree`、`parent_key`、`area`、`acceptance_method` 和 `evidence` 校验父子关系。需求验收报告的 `acceptance_tree` 会逐节点给出 `expected`、`matched`、`missing`、`extra` 和 `status`；树不完整时正式状态失败。

## 可复现命令

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config \
  .venv/bin/rflp acceptance \
  --requirements src/rflp_lite/resources/examples/customer-acceptance/customer-requirements.txt \
  --gold src/rflp_lite/resources/examples/customer-acceptance/requirements-gold-v3.json
```

期望结果：`formal_status=passed`、`matched=29`、precision/recall 均为 `1.0`，四个父节点均为 `passed`。该命令验证的是需求文本到结构化/MBSE 的正式契约；2.1/2.2 的工程证据仍需单独执行 `rflp concept acceptance`。

## 文档级验收样本计划

当前源码包保留可重复的文本基线，不把临时二进制资料混入交付包。正式客户验收应在同一 Gold 树上分别准备并登记以下输入：

1. 含表格、跨页标题和行列定位的 DOCX；
2. 含文本层、页眉页脚和数值单位的数字 PDF；
3. 无文本层、需要 OCR 的扫描 PDF；
4. 同时包含复杂指标、数值范围、单位、显式禁止和隐含约束线索的综合样本。

每份样本都应保留页面/区域来源、解析诊断、人工标注和 Gold 版本。扫描 PDF 依赖 `.[documents]`，缺少 OCR 依赖时应报告诊断而不能把结果标为正式通过。

## 边界

2.1 输出仍是 `conceptual_2d_svg` 参数化二维顶/侧视概念布局；2.2 内置评估器仍是 `development_only`。3.1、3.2、3.3 未实现，不出现在本验收树或正式通过条件中。
