# 项目管理首页轻量读取设计

## 目标

让“开始项目”首页 `GET /` 在存在超大 Workbench 的项目时仍能快速返回。首页只读取项目目录和轻量摘要；用户展开某个项目卡片时，才读取该项目的完整 Workbench 并渲染当前需求。

## 范围与不变行为

- 保留 `/` 作为全部项目的项目管理总览页。
- 保留项目卡片默认收起、查看需求、打开项目和提交新需求的交互。
- 首页摘要继续显示项目名、当前需求数量、已接受数量和模型状态。
- 展开卡片后的需求内容通过独立请求按需加载。
- 不删除、不压缩、不迁移现有 `workbench.payload` 和历史项目数据。
- 旧数据库没有摘要快照时，首页不解析完整 payload；卡片显示摘要暂不可用，展开后读取真实内容。

## 方案

在 SQLite 中增加单行 `workbench_summary` 表。每次 `SQLiteRepository.save_workbench()` 保存完整 Workbench 时，从已经位于内存中的新状态计算摘要，并在同一个事务里写入 `workbench_summary`。摘要不复制业务模型，只保存首页所需的派生值：

- `id = 'current'`
- Workbench `revision` 与 `content_revision`
- 当前 claims 数量
- `accepted` claims 数量
- 模型状态：`未生成`、`草稿` 或 `正式模型`
- 更新时间

首页的 `WebFacade.project_summaries()` 只打开每个项目的 SQLite 连接，查询摘要，不调用 `requirements()`、`requirement_overview()` 或 `runs()`。不存在 Workbench 的新项目直接返回 0 和“未生成”；存在 Workbench 但没有快照的旧项目返回未知摘要标记，不读取 payload。

## 页面数据流

1. `GET /` 调用 `project_summaries()`。
2. `project_summaries()` 读取 `workbench_summary` 和必要的 SQLite 元数据，构造轻量项目卡片。
3. 项目卡片 body 初始显示加载提示，并通过 HTMX 的 `toggle` 事件请求 `/w/{workspace}/project/details`。
4. 详情路由调用现有完整 `requirements()` 一次，从当前 claims 构造需求行，返回 `_project-card-details.html` 片段。
5. 详情读取失败只影响该卡片；首页本身不因该项目的大 payload 超时。

## 兼容性与一致性

- 新迁移只执行 `CREATE TABLE IF NOT EXISTS`，不回填旧 Workbench，避免服务启动时扫描大 JSON。
- `save_workbench()` 的摘要更新和 Workbench 更新共享已有原子事务；提交失败时两者一起回滚。
- 所有已有保存入口（Web、CLI、后台任务）继续复用 `save_workbench()`，无需逐个调用方补写摘要。
- 旧项目没有摘要时不伪造需求数量；展开详情后仍使用当前 Workbench 的真实 claims。
- 项目卡片不再读取 runs 文件目录；当前首页模板未使用 `latest_run`，因此移除该不必要读取。

## 测试验收

- 新建空项目后，首页显示 0 条当前需求和“未生成”。
- 保存含 claims、accepted claims、draft 或正式 RFLP 的 Workbench 后，摘要表返回准确数量和模型状态。
- 首页项目汇总即使 `requirements()` 与 `runs()` 被替换为抛错，也能成功返回，证明没有完整读取。
- 首页 HTML 不包含需求正文；请求项目详情后才出现需求正文。
- 没有摘要快照的旧项目首页仍返回 200，并显示摘要不可用而不是读取大 payload。
- 现有项目管理、需求工作台和全量 Web 测试继续通过。
