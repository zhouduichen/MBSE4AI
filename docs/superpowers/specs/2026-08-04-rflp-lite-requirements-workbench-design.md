# RFLP-Lite 需求工作台最小设计

## 目标

把现有固定 `requirements.md` 演示改成一个可在本地 Web UI 跑通的真实链路：输入需求文本、Markdown 或 DOCX，审核候选 Claim，动态生成 R/F/L/P，查看稳定可复现的 SVG 关系图。

## 范围

首版只实现：

- 一个需求建模页面；
- 文本粘贴、Markdown 和基础 DOCX 段落读取；
- 中英文义务句规则提取；
- Claim 接受、编辑和驳回；
- 可选、手动触发的 OpenAI-compatible LLM 建议；
- 从已接受 Claim 动态生成 R/F/L/P；
- R→F、F→L、L→P 覆盖检查；
- 服务端确定性 SVG 与 JSON 导出。

不实现拖拽编辑器、复杂 DOCX 排版还原、自动调用 AI、通用插件系统或多供应商抽象。

## 复用边界

继续使用现有 FastAPI、Jinja、SQLite、Workspace、`Artifact`、`TextSpan`、`Claim`、`ModelElement`、`Relation` 与运行详情页面。没有必要新增前端构建工具或数据库。

## 页面与操作流

新增 `/w/{workspace}/requirements`：

1. 用户粘贴文本或上传 `.md` / `.docx`。
2. 点击“规则分析”，页面显示候选 Claim。
3. 如已配置 LLM，用户可点击“AI 辅助分析”；结果仍为待审核候选。
4. 用户接受、编辑或驳回候选。
5. 点击“生成 RFLP”，系统只使用已接受 Claim 生成四层模型。
6. 同页显示四层 SVG、覆盖率和未解决项，并提供 JSON/SVG 下载。

表单使用普通 HTML POST；提交后重定向回页面，避免为局部刷新增加额外状态同步。

## 数据与持久化

沿用 SQLiteRepository，在现有表基础上保存本次工作台需要的数据。上传文件存入工作区受管目录，数据库保存 Artifact 哈希和定位信息。Claim 的 `status` 使用 `candidate`、`accepted`、`rejected`。

RFLP 继续存为 `ModelElement` 和 `Relation`：

- R 节点携带源 `claim_id`；
- F 节点用 attributes 保存 input、output、precondition、postcondition、failure_mode；
- L 节点表示职责分组；
- P 节点表示本地实现组件；
- 关系谓词固定为 `satisfiedBy`、`allocatedTo`、`realizedBy`。

## 解析与规划规则

- Markdown/文本按非空段落和列表项形成 TextSpan；
- DOCX 用标准库 `zipfile` 与 XML 读取 `word/document.xml` 中的基础段落；
- 义务词覆盖 `必须`、`应当`、`不得`、`禁止`、`需要`、`MUST`、`SHALL`、`SHOULD`、`MUST NOT`；
- 每个已接受 Claim 生成一个 R 和一个对应 F；
- F 名称从谓词后的首个动作短语得到，无法判断时使用可人工编辑的“处理 + 对象”；
- L 按 Claim 主体或功能对象的稳定关键词归组；
- P 首版映射到现有本地实现类别：Web/API、SQLite Repository 或 Python Service；
- 所有 ID 来自规范化内容哈希，排序按 layer、name、id，保证重复执行结果一致。

这些启发式规则的上限会用 `ponytail:` 注释标明；当真实样本证明分类不足时再升级。

## SVG 生成

服务端直接生成 SVG：R/F/L/P 固定四栏，节点等距排列，关系使用带箭头的曲线路径。节点文本与属性必须 HTML/XML 转义。相同图模型必须产生字节一致的 SVG。页面点击节点只用锚点和 CSS 展示详情，首版不实现拖拽。

## LLM 边界

LLM 不是主链路。仅当用户点击按钮且环境变量提供 `RFLP_LLM_BASE_URL`、`RFLP_LLM_MODEL`、`RFLP_LLM_API_KEY` 时，使用标准库 HTTP 调用 OpenAI-compatible chat completions。

输入为 TextSpan，输出必须解析为限定 JSON 结构。失败、超时或格式错误时显示错误并保留规则结果。API Key 不进入页面、数据库或日志。AI 结果只能是 `candidate`，不能批准 Claim、RFLP 或 Baseline。

## 错误与安全

- 上传仅接受 `.md`、`.markdown`、`.docx`，限制为 5 MiB；
- 文件名经现有工作区安全路径逻辑处理；
- 空输入、无候选、无已接受 Claim 均显示可操作错误；
- 写入使用现有事务和失败保护；
- SVG、HTML 和下载文件名均转义或校验。

## 验证

新增一个最小端到端测试，覆盖：

1. 输入至少三条中英文需求；
2. 提取并接受 Claim；
3. 生成非固定名称的 R/F/L/P；
4. 三类关系覆盖率均为 100%；
5. 相同输入两次生成完全相同的 JSON 和 SVG；
6. Web 页面可完成输入、审核和查看图；
7. 未配置 LLM 时主链路仍成功。

同时运行现有全量测试与 import contracts。

## 完成标准

用户可以在本机浏览器从自己的需求内容出发，人工确认 Claim，并看到动态生成且可追溯的 R/F/L/P 四层图；不再依赖固定的三条示例需求。
