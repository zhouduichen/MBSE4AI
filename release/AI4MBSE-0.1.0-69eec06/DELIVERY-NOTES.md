# AI4MBSE 0.1.0 交付说明

- 源码提交：`69eec06`
- 分支：`codex/web-audit-2026-08-18`
- Python：`>=3.11`
- 打包日期：2026-09-01

## 内容

- `AI4MBSE-0.1.0-source-69eec06.zip`：当前提交的受控源码、测试和文档。
- `python/rflp_lite-0.1.0-py3-none-any.whl`：Python wheel。
- `python/rflp_lite-0.1.0.tar.gz`：Python source distribution。

源码归档由 `git archive HEAD` 生成，不包含 `.git`、虚拟环境、缓存、运行数据库、构建目录及根目录未跟踪的参考 PPT/PDF/DOCX。

## 复核结果

- 全量 pytest：通过。
- 需求 1.1/1.2：软件功能检查全部通过；示例 gold 的正式验收当前为 `failed`，原因是 gold 使用固定 `region-gold-*` 来源 ID，而实际导入会生成内容相关来源 ID，正式匹配契约仍需统一。
- 总体设计 2.1/2.2：软件验收通过，生成 5 套候选并覆盖三学科、失败隔离、优化追踪和审批门禁；内置评估器正式状态为 `development_only`。
- 详细设计 3.1/3.2/3.3：未实现真实 CAD、二维/三维 PMI/GD&T 和 DFM/DFA 闭环。

## 安装示例

```bash
python3.11 -m venv .venv
.venv/bin/pip install 'python/rflp_lite-0.1.0-py3-none-any.whl[web,documents,schema]'
.venv/bin/rflp --help
```
