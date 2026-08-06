# Python 项目接入验证记录

**日期：** 2026-08-05
**设计：** `docs/superpowers/specs/2026-08-05-rflp-lite-project-bridge-design.md`

## 结论

Python 项目接入链路已实现并通过全部验证：**76 passed**（原 49 + 新增 27），Import Linter 3 contracts kept / 0 broken，`python -m build` 构建成功。演示管线 `application/demo.py` 与既有 `calculate_delta` 未改动。

## 验证内容

### 1. 单元测试：目录扫描（`tests/adapters/test_project_scanner.py`）

- 对 `examples/versioned-content-service` 的元素构成：`module 1 / class 1 / function 3 / api-operation 3 / test-case 1`，符号名与 API 操作齐全；
- 确定性：两次扫描 `canonical_json` 字节一致；
- 跳过规则：`.git`、`.cache`、`node_modules` 与符号链接；
- 超大文件计数、文件数量上限、深度上限、不再下探超深目录；
- 空目录／无可解析制品抛 `AdapterFailure`；根目录不存在或非目录抛 `ContractViolation`；
- 坏 `.py`/`.json`/`.xml` 记入 `parse_errors` 不中断扫描。

### 2. 单元测试：应用层（`tests/application/test_project_bridge.py`）

- 未生成 RFLP 时批准基线抛 `ContractViolation("请先生成 RFLP 规划图")`；
- 批准后 `state["baseline"]` 写入 id/hash/status，元素全部 `approved`，`project` 清空；
- 未批准基线时分析抛 `ContractViolation("请先批准基线")`；
- 全链路（analyze→accept→generate→approve→analyze 对示例项目）产出非空 matches/delta/tasks/evidence；delta 仅含 `MISSING`/`EXTRA`；evidence `target_id` 全部指向 ActualModel 元素；
- 确定性：两次执行 `state["project"]` 字节一致、delta/actual/evidence id 一致；
- 失效语义：`review_item` 与 `generate_model` 均清空 `baseline` 与 `project`。

### 3. Web 路由（`tests/interface/web/test_project.py`）

- 空工作台页面引导文案；
- 未生成 RFLP 时批准基线返回 422；
- 全流程：批准基线→分析项目→页面展示 MISSING/EXTRA/任务契约/匹配→7 个白名单下载均 200；
- 非白名单下载与路径穿越文件名均 404；
- 未批准基线时分析返回 422；
- 两次分析后 `project.json` 下载字节一致；
- SQLite `audit_events` 包含 `baseline.approved`、`project.analyzed`、`requirements.accepted`。

### 4. CLI（`tests/interface/test_cli.py`）

- `rflp project approve` 与 `rflp project analyze --source` 成功输出规范化 JSON（status ok、baseline_hash、actual_model_id、missing、extra、tasks）；
- 空工作台报“需求工作台为空”，未批准基线分析报“请先批准基线”，均退出码 1。

### 5. 端到端（TestClient 真实流程）

对 `examples/versioned-content-service` 连接一条混合中英文需求：

- 扫描 3 个文件、`files_used=3`、`parse_errors=()`；
- `matched=4`：英文义务句（restore a historical version / record an audit event for every restore）与 `restore_version`/`save_version` 按关键词匹配；
- 中文义务句（恢复历史版本 / 查看恢复记录）如实判为 `MISSING`（跨语言无法用关键词匹配，属已知诚实边界）；
- `list_versions`/`listVersions`/`saveVersion`/`restoreVersion`/`VersionedContentService` 判为 `EXTRA`；
- 派生 3 条链式 TaskContract（depends_on 串行）；
- 二次分析字节级确定。

## 复现命令

```bash
.venv/bin/pytest -q
.venv/bin/lint-imports
.venv/bin/python -m build
```

## 已知边界

- 匹配只在 baseline 的 R/F 层与 actual 的 class/function/api-operation 之间按分词交集进行；中英文之间无法用关键词匹配，明确义务如实标为 MISSING 而非猜测；
- 扫描只读 .py/.json/.xml；测试结果来自已有 JUnit，不实际执行测试；
- 目录为只读输入，不复制、不写入、不上传。