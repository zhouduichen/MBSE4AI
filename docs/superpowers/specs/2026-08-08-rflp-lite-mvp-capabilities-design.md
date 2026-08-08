# RFLP Lite 最小可执行能力设计

## 目标

把当前能力中心中的占位能力变成可运行的本地 MVP，同时保持模块边界清晰，后续可以替换为真实外部适配器。MVP 不伪造外部服务成功：没有配置的外部能力必须返回明确的 `not_configured` 或 `unsupported` 状态。

## 能力边界

- 场景执行：读取结构化场景，按步骤产生确定性事件、断言和证据；故障只作为可追踪的注入事件，不执行任意代码。
- Profile / Pack：通过现有 profile schema 校验、保存、读取和导出版本化配置。
- SysML-lite：提供 RFLP 模型的轻量 JSON 交换格式导入、导出和往返校验；不宣称完整 SysML v2 语义覆盖。
- 本地运行追踪：基于现有 run manifest 和 SQLite catalog 记录参数、状态、结果哈希，并导出 MLflow 可映射的 JSON；未安装 MLflow 时不调用外部服务。
- Web API：提供 `/api/v1` 下的本地 JSON 读写接口，复用 application facade，不复制业务逻辑。
- 后台任务：使用持久化 job 记录包装长操作，先提供同步执行加状态查询，保留异步 worker 接口。
- 插件：提供本地、进程内注册表和能力发现；远程执行、签名和隔离仍返回未配置。
- LLM、Docling、真正 SysML v2、真正 MLflow、登录权限和远程运行：保留明确的 capability 状态和适配器接口，不在本轮伪造实现。

## 解耦方式

业务层只依赖小型输入/输出数据结构和 facade 方法。文件格式、SQLite、Web 路由和可选第三方库分别位于 adapters 或 interface 层。每个 MVP 能力至少提供一个纯函数或独立服务方法，CLI、Web 和 API 只负责参数转换。

## 数据流与失败处理

请求 → 输入校验 → application service → 可选 adapter → 结构化结果。结果统一包含稳定 ID、状态、时间戳/哈希和诊断信息。输入错误返回可读的 4xx/CLI 错误；外部依赖缺失返回 `not_configured`；执行过程失败保留失败记录和诊断，不生成成功证据。

## 验证标准

每项能力都有单元测试和至少一个接口级测试；核心交换格式必须能 round-trip；现有全量测试、import contract、build 和 profile schema 校验继续通过。能力中心只将已具备真实本地路径的项目标为 `available`，其余显示准确的限制。
