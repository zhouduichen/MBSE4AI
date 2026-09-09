# AI4MBSE 0.1.0 交付说明

## 版本信息

- 源码提交：`578c0d7`
- 分支：`codex/web-audit-2026-08-18`
- 交付日期：2026-09-01
- 运行环境：Python 3.11 及以上

## 交付文件

- `AI4MBSE-0.1.0-source-578c0d7.zip`：仅包含 Git 已跟踪源码、测试、文档和资源，不包含 `.git`、虚拟环境、缓存、数据库及构建目录。
- `python/rflp_lite-0.1.0-py3-none-any.whl`：Python wheel 安装包。
- `python/rflp_lite-0.1.0.tar.gz`：Python source distribution。
- `SHA256SUMS.txt`：上述交付文件及本说明文件的 SHA-256 校验和。

## 验证结果

- 全量测试：通过。
- Python 编译检查：`python3 -m compileall -q src tests` 通过。
- 架构预算测试：8 项通过。
- 需求验收：正式状态 `passed`，29/29 条原子需求匹配，precision/recall 均为 1.0，1.1/1.2/2.1/2.2 四个树节点全部通过。
- 概念布局验收：软件检查通过；当前正式状态为 `development_only`。

## 本版本范围与边界

本版本只收口需求 1.1、1.2、2.1、2.2：

- 1.1：文档需求捕获、来源区域证据、实体/属性/显式约束/隐含约束、MBSE 映射和追溯矩阵。
- 1.2：场景、Use Case、Activity、Sequence、人机修改和追溯闭环。
- 2.1：基于指标包络与历史方案的 3~5 套参数化二维总体概念布局，包含约束、来源和差异证据。
- 2.2：多学科批量评估、失败隔离、缓存、指标汇总、Pareto/优化反馈；内置评估器仍标记为 `development_only`，不会冒充客户正式仿真模型。

3.1、3.2、3.3（三维自然语言建模、二维/三维智能标注、设计规则审查）本版本明确不实现。

`corpus-manifest.json` 中列出的 DOCX 表格/跨页、数字 PDF、扫描 OCR PDF 和混合约束样例是后续真实客户语料计划；在人工标注前不宣称为正式验收输入。

## 安装示例

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install python/rflp_lite-0.1.0-py3-none-any.whl
```

安装后可使用 `rflp acceptance` 和 `rflp concept acceptance` 命令复现上述验收。
