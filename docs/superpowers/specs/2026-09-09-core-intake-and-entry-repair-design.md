# AI4MBSE 核心输入与入口修复设计

## 目标

修复 AI4MBSE 当前 Web 主流程，使用户可以从项目列表进入项目，直接输入一条需求或上传需求文档，确认已有输入后再运行分析，并在页面上访问模型导出与模型配置入口。

## 问题边界

- “本地工作区”继续表示本地服务运行模式，不自动创建项目。
- 根路径 `/` 重定向到 `/ui/projects`，避免用户看到 404。
- 项目分析页增加需求文本输入；提交后创建一个 `REQUIREMENT` 实体，状态为 `candidate`、生产者为 `user`，原始文本保存在 payload 中。
- 项目分析页增加文档上传；服务端复用现有 `LocalDocumentParser`，把上传内容复制到项目 inputs 目录并记录文档与 source regions。
- 分析前要求项目至少存在一个用户/导入的需求实体或一个已接入文档；空项目返回明确的 422，不得生成规则占位模型。
- 保留离线规则 Runtime，但其输出仍必须标记为 candidate，不能被当作用户事实。
- 模型页增加 JSON、DOT、SVG、SysML-lite 导出入口；Web API 的 `sysml` 格式复用 CLI 的稳定 SysML-lite 序列化逻辑。
- 设置页增加最小模型配置表单和激活操作；密钥仍只进入 keyring/session，不进入页面响应。

## 接口设计

- `POST /projects/{project_id}/requirements`：JSON `{text}`，返回创建的 requirement 和新 revision。
- `POST /projects/{project_id}/documents`：支持 multipart 上传字段 `file`；保留 JSON `{path}` 作为本地 CLI/自动化兼容入口。
- `POST /projects/{project_id}/analysis`：在 pipeline 或 phase 运行前调用输入门禁；无输入返回 `422 InputRequired`。
- `GET /`：303 到 `/ui/projects`。
- `POST /projects/{project_id}/export`：支持 `json`、`dot`、`svg`、`sysml`。
- `POST /model-profiles/{profile_id}/activate`：设置页提供可见按钮。

## 数据与安全

- 需求实体使用 `make_entity(EntityKind.REQUIREMENT, ..., producer=Producer.USER)`，不会绕过 ModelGraph 的 Patch/CAS 约束。
- 上传文件名只取 basename，写入受项目目录约束的 `inputs/`；不接受客户端绝对目标路径。
- 空项目门禁只读当前项目图和文档记录，不改变已有数据。
- 不改变现有用户工作区，不自动删除或迁移旧数据。

## 验收标准

1. 新建项目后分析页可直接提交需求文本，刷新后需求模块显示一条候选需求。
2. 新建空项目点击任意分析按钮返回 422，数据库仍为空。
3. 上传 TXT/MD/DOCX/PDF 后页面显示导入成功和区域数量。
4. `/` 不再 404；模型页可下载四种声明支持的格式，SysML 不返回 422。
5. 设置页可以保存并激活本地模型配置；API key 不出现在 HTML/JSON。
6. 既有 API、CLI、领域和仓储测试继续通过。
