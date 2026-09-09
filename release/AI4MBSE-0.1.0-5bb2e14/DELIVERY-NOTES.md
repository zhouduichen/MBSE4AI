# AI4MBSE 0.1.0 交付说明

- 源码提交：`5bb2e14`
- 分支：`codex/web-audit-2026-08-18`
- Python：`>=3.11`
- 打包日期：2026-09-01

## 内容

- `AI4MBSE-0.1.0-source-5bb2e14.zip`：由当前提交生成的受控源码、测试和文档归档。
- `python/rflp_lite-0.1.0-py3-none-any.whl`：Python wheel。
- `python/rflp_lite-0.1.0.tar.gz`：Python source distribution。
- `AI4MBSE-0.1.0-5bb2e14-delivery.zip`：以上交付物及本说明、校验和的总包。

源码归档由 `git archive HEAD` 生成，不包含 `.git`、虚拟环境、缓存、运行数据库、构建目录及根目录未跟踪的参考 PPT/PDF/DOCX。

## 复核结果

- 全量 `pytest`：通过。
- `compileall`：通过。
- 架构门禁：通过。
- 需求 1.1：Gold v3 稳定 key + source anchor 正式验收通过，precision/recall 均为 1.0，来源完整率 100%。
- 需求 1.2：Use Case、活动图、时序图 canonical flow 一致性、追溯和编辑 CAS 验收通过。
- 总体设计 2.1：生成 5 套参数化二维概念布局 SVG，候选差异、约束余量、来源和哈希证据齐全。
- 总体设计 2.2：三学科批量评估、缓存、失败隔离和优化编排软件验收通过；内置低阶评估器仍为 `formal_status=development_only`，不等同 CFD/FEA 或客户工程批准。
- 详细设计 3.1–3.3：未实现三维 CAD 驱动、PMI/GD&T 标注和 DFM/DFA 审查。

## 安装示例

```bash
python3.11 -m venv .venv
.venv/bin/pip install 'python/rflp_lite-0.1.0-py3-none-any.whl[web,documents,schema]'
.venv/bin/rflp --help
```
