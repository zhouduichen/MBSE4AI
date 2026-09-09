# AI4MBSE 0.1.0 交付说明

- 源码提交：`ac9ded1`
- 分支：`codex/web-audit-2026-08-18`
- Python：`>=3.11`
- 打包日期：2026-09-08

## 交付内容

- `AI4MBSE-0.1.0-source-ac9ded1.zip`：提交 `ac9ded1` 的受控源码、测试和文档。
- `python/rflp_lite-0.1.0-py3-none-any.whl`：Python wheel 安装包。
- `python/rflp_lite-0.1.0.tar.gz`：Python source distribution。
- `AI4MBSE-0.1.0-ac9ded1-delivery.zip`：上述文件和本说明的汇总交付包。
- `SHA256SUMS.txt`：交付文件的 SHA-256 校验值。

源码归档由 `git archive HEAD` 生成，不包含 `.git`、虚拟环境、缓存、运行数据库、构建目录及未跟踪的参考 PPT/PDF/DOCX。wheel 和源码包从同一提交的临时源码树构建，避免混入工作区未提交内容。

## 安装与网页启动

在解压后的交付目录中执行：

```bash
python3.11 -m venv .venv
.venv/bin/pip install 'python/rflp_lite-0.1.0-py3-none-any.whl[web,documents,schema]'
.venv/bin/uvicorn rflp_lite.interface.web.app:create_app --factory --host 127.0.0.1 --port 8000
```

浏览器访问：`http://127.0.0.1:8000/ui/projects`

Windows PowerShell 对应启动命令：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install "python\rflp_lite-0.1.0-py3-none-any.whl[web,documents,schema]"
.venv\Scripts\python -m uvicorn rflp_lite.interface.web.app:create_app --factory --host 127.0.0.1 --port 8000
```

## 本版本重点

- 完成代码级轻量化重构与依赖边界治理。
- 修复旧版 SQLite 数据库兼容迁移和项目详情页 500 错误。
- 恢复网页静态资源与模板渲染。
- 增加已有项目删除接口、删除按钮及二次确认交互。

## 验证结果

- 全量 pytest：通过。
- Ruff：通过。
- import-linter：5 个约束通过，0 个失败。
- 架构预算：模块循环、适配层反向依赖、超长函数等关键指标均为 0。
- wheel/sdist 完整性和隔离安装冒烟测试：通过。

## 当前边界

本交付是 `0.1.0` 轻量化工程版本。项目列表、详情、分析、模型、证据与设置页面已可运行；更完整的“新建项目—需求录入—利益相关方场景分析”一体化网页向导不在本提交范围内。
