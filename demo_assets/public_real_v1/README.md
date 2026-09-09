# AI4MBSE public-real-v1

这是面向功能 1.1、1.2、2.1、2.2 的可重复 Demo Dataset。

- 原始公开 PDF/DOCX 保存在 `05_original_sources/`，不在其上做 OCR 覆盖。
- 真实公开事实和可运行方案分层保存，分别位于 `02_concept_design/2_1_public_facts/` 与 `02_concept_design/2_1_runnable_schemes/`。
- 统一索引、数据字典和 SHA-256 见 `00_catalog/` 与 `04_validation/`。
- 专用 SQLite 工作区为 `../../workspaces/public-real-v1/.rflp/model.db`（相对于本文件）。现有其他工作区未修改。

## 数据边界

`fixed-wing-schemes-public-demo.*` 允许 `published`、`derived`、`demo_assumption` 三类字段共存，并在扩展字段中保留 provenance。它不是九型飞机的完整官方工程数据库。当前内置气动、结构、重量平衡评估器仍保持 `development_only`。

当前工作区的 2.1/2.2 可执行入口：

```text
rflp concept import --workspace workspaces/public-real-v1 \
  --pack src/rflp_lite/resources/domain-packs/fixed-wing-v1.json \
  --data demo_assets/public_real_v1/02_concept_design/2_1_runnable_schemes/fixed-wing-schemes-public-demo.json

rflp concept acceptance \
  --pack src/rflp_lite/resources/domain-packs/fixed-wing-v1.json \
  --schemes demo_assets/public_real_v1/02_concept_design/2_1_runnable_schemes/fixed-wing-schemes-public-demo.json \
  --envelope demo_assets/public_real_v1/04_validation/tactical-isr-envelope.json \
  --evaluator-profile demo_assets/public_real_v1/04_validation/development-evaluator-profile.json
```
