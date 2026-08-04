# RFLP-Lite 本地 Web UI 设计

**日期：** 2026-08-04
**状态：** 用户已批准架构、页面范围与视觉方向
**目标环境：** macOS 本机、单用户、仅监听 `127.0.0.1`、无需 Node.js、Docker 或外部服务

## 1. 目标

在已经跑通的 RFLP-Lite 本地垂直链路上增加一个可直接操作和验证的 Web UI。用户应当可以从浏览器创建受控工作区、启动完整链路，并沿以下路径查看真实产物：

`Artifact -> TextSpan -> Claim -> R/F/L/P -> Candidate -> Simulation -> Baseline -> Delta -> TaskContract -> Evidence`

首版优先保证稳定、可追溯和诚实呈现能力边界。当前核心已具备的数据和操作必须真正接通；尚未开发的能力只展示说明充分的占位页，不返回伪造结果。

## 2. 已选方案

采用 `FastAPI + Jinja2 + HTMX + 本地 CSS`：

- FastAPI 提供本地 HTTP 入口和 HTML 路由。
- Jinja2 在服务端生成页面，不引入前端构建链。
- HTMX 只承担表单提交、局部刷新和加载状态，不建设前端状态管理框架。
- CSS、图标和字体全部随项目保存，不依赖 CDN。
- Uvicorn 以单进程形式监听 `127.0.0.1`。
- CLI 保持独立可用；Web UI 与 CLI 调用同一应用服务。

没有选择 React/Vite，因为首版不需要复杂客户端状态，其 Node 构建链、依赖树和前后端契约会扩大部署及排错范围。没有选择 Streamlit/Gradio，因为其页面组织、复杂导航、可访问性和后续产品化空间不适合长期承载模型追溯与治理工作台。

## 3. 产品与安全边界

- 首版是本机单用户工具，不提供登录、账户、权限或多人协作。
- 服务默认且只能通过显式配置改动监听地址；标准启动命令固定使用 `127.0.0.1`。
- Web UI 只管理仓库下 `workspaces/` 中的工作区。创建时只接受规范化名称，不接受浏览器提交的任意绝对路径或 `..` 路径。
- 任意外部路径继续由 CLI 操作，避免 Web 服务获得超出首版需要的文件系统写入范围。
- Web 层不得直接修改 SQLite 中的领域记录、Baseline 或审计数据。所有写操作必须调用 Application Service。
- 数据库和运行 JSON 仍是事实来源；页面不维护第二套业务状态。
- 首版不修改已批准 Baseline。运行失败、Schema 失败或 Adapter 失败必须保持原 Baseline 哈希不变。

## 4. 视觉与交互方向

界面采用“本地工程驾驶舱”，而不是通用表格管理后台：

- 深墨绿黑作为导航和驾驶舱底色，薄荷绿表示通过或可执行状态，低饱和蓝表示信息，琥珀色表示等待或规划中，红色只用于失败。
- 页面使用清晰的数字层级、短标签、链路图和状态徽标组织高密度信息。
- 长表格、JSON、原文和证据详情使用较亮的内容面板，保证持续阅读时的对比度和舒适度。
- 左侧导航固定，顶部显示当前工作区、本地服务状态和最近运行；主区保持最大阅读宽度。
- 动效只用于加载、状态切换和轻微的导航反馈，不使用装饰性大动画。
- 桌面宽屏为主要目标；窄屏保持可查看，但首版不以手机操作为验收目标。
- 所有关键状态同时使用文字或图标表达，不只依赖颜色。

## 5. 信息架构与页面

### 5.1 Overview

**驾驶舱**展示当前工作区、最新运行、完整性门禁、RFLP 元素数量、候选数量、已选方案、Baseline 哈希、证据覆盖和最近审计活动。空工作区展示明确的首次运行引导。

**运行中心**允许：

- 创建或选择 `workspaces/` 下的工作区；
- 选择 Heuristic 或 CP-SAT Solver；
- 设置整数 seed；
- 启动当前真实的完整 demo 链路；
- 查看运行输入、耗时、结果哈希、产物目录和结构化失败原因；
- 下载本次运行已经生成的 JSON 文件。

首版不开放任意 Profile 字段、候选上限和超时的自由编辑；这些参数沿用已验证的默认 Profile，避免 UI 产生未覆盖的运行组合。

### 5.2 Model

**工件与声明**以列表和详情抽屉展示 Artifact、TextSpan、Claim、来源定位和原文片段。

**RFLP 模型**按 Requirement、Function、Logical、Physical 分类浏览元素，并展示关系、上下游追溯和相关 Claim。首版只读，不提供图形化建模或直接编辑。

### 5.3 Decision

**候选与权衡**比较候选方案、Solver、硬约束、评分、排序、选择理由及 Decision。

**仿真结果**展示 SimulationCase、事件序列、关键指标、约束检查和通过/失败结论。首版使用表格、时间线和指标卡，不建设交互式仿真编辑器。

### 5.4 Governance

**基线与差异**展示 Baseline 版本、成员、哈希、DeltaSet 和逐项变更，但不允许从 Web 直接批准或改写 Baseline。

**任务契约**展示 TaskContract DAG、依赖、读写集合、不变量、验收条件和状态。

**证据与审计**聚合 OpenAPI、JUnit、Python AST、仿真 Evidence 与 AuditEvent，支持按类型和运行过滤。

### 5.5 Extensions

**能力中心**统一承载尚未开发的能力：

- LLM / Ollama 智能建模；
- Docling 高级文档解析；
- SysML v2 导入、导出与图形编辑；
- MLflow 实验追踪；
- Profile / Pack 可视化编辑；
- 后台异步任务队列；
- 对外 Web API；
- 登录、权限及多人协作；
- 插件市场、远程 Runtime 和云部署。

每张能力卡必须显示状态、用途、依赖、预期输入输出及启用条件。未实现操作显示不可点击的“尚未启用”按钮，不提供空表单、假进度或模拟结果。

## 6. 架构与组件边界

Web UI 作为现有模块化单体的新 Interface Adapter：

```text
Browser
  -> FastAPI routes / Jinja templates / HTMX
  -> Web application facade
  -> Existing RFLP application services
  -> Domain + ports
  -> SQLite / JSON / solver / simulation adapters
```

组件职责如下：

- `interface.web.app`：应用工厂、路由注册、静态资源和模板配置。
- `interface.web.routes`：解析 HTTP 输入、调用 Facade、选择页面或局部模板；不包含领域逻辑。
- `interface.web.presenters`：把应用 DTO 转换为稳定的页面 ViewModel，包括状态标签、短哈希和显示顺序。
- `application.web_facade`：提供 Dashboard、Run、Model、Decision、Governance 查询和受控运行用例。
- 现有 `application.demo.run_demo`：继续负责完整链路，不在 Web 层复制编排逻辑。
- 现有 Repository、Adapter、Domain 和 Governance：继续保持现有依赖方向。

查询可以通过 Application Facade 读取 SQLite 和规范化运行 JSON，但模板和路由不能自行执行 SQL。未来替换页面结构或增加 JSON API 时，领域与运行服务不应改变。

Web 依赖放入独立的 `web` optional dependency 分组；核心或 CLI 安装不被迫安装 FastAPI、Uvicorn、Jinja2 和 multipart 支持。

## 7. 请求与数据流

### 7.1 页面查询

1. 浏览器请求页面。
2. Route 校验工作区名和可选运行标识。
3. Web Facade 从 Repository 和运行清单生成只读 DTO。
4. Presenter 生成 ViewModel。
5. Jinja2 返回完整页面或 HTMX 局部片段。

不存在工作区、没有运行结果和只有部分历史产物是正常页面状态，不以 500 错误处理。

### 7.2 创建工作区

1. 用户提交工作区名称。
2. 服务执行字符白名单、长度、规范化和根目录包含关系检查。
3. 调用现有初始化应用服务创建目录、Profile 和 SQLite。
4. 采用 POST/Redirect/GET 返回新工作区驾驶舱，避免刷新重复提交。

同名有效工作区不覆盖；页面提示用户选择已有工作区。

### 7.3 启动运行

1. 用户选择工作区、Solver 和 seed 后提交。
2. 普通同步 FastAPI handler 在线程池中调用 `run_demo`；HTMX 显示不可重复提交的加载状态。
3. `run_demo` 按现有事务和审计规则运行完整链路。
4. 成功后重定向到 Run Detail；失败后返回可恢复错误，并保留失败阶段和审计信息。

首版使用同步运行，因为当前真实 demo 已足够快，且同步模型最容易保证事务边界和重启行为。长耗时 LLM、Docling、远程 Solver 和复杂仿真接入时再实现持久化 Job Queue；首版只保留能力占位，不引入内存任务队列或虚假进度。

### 7.4 导出

下载端点只允许访问 Facade 返回的已登记产物。响应使用固定内容类型和安全文件名，不接受用户提交的任意文件路径。

## 8. 错误处理

- 表单错误在字段旁显示中文说明，同时保留用户已输入的非敏感值。
- 应用错误映射为稳定错误码、阶段、简要原因和下一步建议；页面不显示原始堆栈。
- 未知异常记录到本地日志并显示关联 ID，HTTP 返回 500，但不得吞掉异常审计。
- 运行按钮提交后立即禁用；POST/Redirect/GET 防止刷新重复执行。
- 不存在的工作区或运行返回 404 页面；非法路径输入返回 400，不自动纠正到其他路径。
- Adapter、Solver、Schema 或证据校验失败时，事务回滚并验证 Baseline 哈希不变。
- 模板缺少可选字段时显示“暂无数据”，不得用 `0`、`PASS` 或其他值假装真实结果。

## 9. 启动与使用

增加独立命令：

```bash
rflp web --host 127.0.0.1 --port 8000
```

启动成功后终端打印完整本地地址和工作区根目录。浏览器访问 `http://127.0.0.1:8000`。命令启动前检查 `web` extras 是否安装；缺失时输出明确的安装命令，不显示第三方 ImportError 堆栈。

首版不自动打开浏览器、不作为系统后台服务、不注册登录启动项。停止方式为终端 `Ctrl+C`，SQLite 和已完成运行产物正常保留。

## 10. 测试策略

### 10.1 单元测试

- 工作区名称和路径根目录校验；
- Presenter 的空状态、状态色、短哈希和缺失字段处理；
- 应用错误到 HTTP 错误 ViewModel 的映射；
- 能力占位目录必须明确标记为未启用。

### 10.2 Web 集成测试

使用 FastAPI TestClient 覆盖：

- 驾驶舱和所有主导航页面返回成功；
- 空工作区页面不伪造数据；
- 创建工作区后产生合法 Profile 和 SQLite；
- Heuristic 和 CP-SAT 表单均能跑通并进入真实 Run Detail；
- 非法工作区名、路径穿越、重复提交和不存在资源返回正确状态；
- 下载端点不能越过已登记产物范围；
- 运行失败后错误可见且 Baseline 哈希不变；
- 每个规划能力都有可见占位说明且没有可执行操作。

### 10.3 回归与视觉验证

- 现有 19 项测试与 Import Linter 契约必须继续通过。
- CLI 的两种 Solver 演示结果保持可复现。
- 使用真实本地服务器执行浏览器冒烟：导航、运行、详情、下载、错误和空状态。
- 在常见桌面宽度进行截图检查，验证溢出、层级、对比度、焦点状态和 HTMX 加载反馈。
- 首版至少检查 Safari/WebKit 和 Chromium 系浏览器的基础可用性；不承诺旧版浏览器兼容。

## 11. 验收标准

以下条件全部满足才算首版 Web UI 跑通：

1. 安装 `web` extras 后，一条 `rflp web` 命令可在本地启动；核心与 CLI 安装仍可不包含 Web 依赖。
2. 浏览器能够创建受控工作区，并用 Heuristic 和 CP-SAT 分别完成真实链路。
3. 用户可以从驾驶舱沿导航查看 Artifact、Claim、RFLP、Candidate、Simulation、Baseline、Delta、TaskContract、Evidence 和 Audit。
4. 页面展示的数量、状态、哈希和文件均来自 SQLite 或当前运行产物。
5. 失败运行不会改写现有 Baseline，并在页面给出可恢复信息。
6. 未实现能力有清晰占位，但不存在假按钮、假数据或假进度。
7. 页面视觉符合已确认的深色工程驾驶舱方向，长内容区域可读，键盘焦点清晰。
8. Web 新测试、现有测试、Import Linter、两种 Solver 冒烟和浏览器视觉检查全部通过。

## 12. 首版明确不做

- 登录、用户管理、权限、多租户或网络暴露加固；
- Web 中的 Baseline 批准、模型编辑、Profile 任意编辑或数据库管理；
- React/Vue 前端、Node 构建链、WebSocket、SSE 或后台任务队列；
- LLM、Docling、SysML v2、MLflow、插件市场和云端服务的真实接入；
- 移动端专项设计、桌面应用封装或系统服务安装。
