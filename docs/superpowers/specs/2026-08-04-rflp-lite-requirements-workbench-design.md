# RFLP-Lite 需求工作台最小设计

## 目标

把现有固定 `requirements.md` 演示改成一个可在本地 Web UI 跑通的真实链路：输入需求与工程资料，先审核利益相关方、Concern 和 Need，再审核候选 Claim，动态生成 R/F/L/P，查看稳定可复现的 SVG 关系图。

## 范围

首版只实现：

- 一个需求建模页面；
- 文本粘贴、Markdown、基础 DOCX 和文本型工程制品读取；
- 明确利益相关方候选、Concern 和 Need 的规则发现与审核；
- 中英文义务句规则提取；
- Claim 接受、编辑和驳回；
- 可选、手动触发的 OpenAI-compatible LLM 建议；
- 从已接受 Claim 动态生成 R/F/L/P；
- R→F、F→L、L→P 覆盖检查；
- 服务端确定性 SVG 与 JSON 导出。

不实现拖拽编辑器、复杂 DOCX 排版还原、组织关系管理、模糊自动合并、自动调用 AI、通用插件系统或多供应商抽象。

## R 层前置链路

首版正式链路为：

```text
SourceArtifact
→ StakeholderCandidate
→ Stakeholder / Concern / Need
→ Claim / Requirement
→ R → F → L → P → Evidence
```

系统负责发现候选并保留证据；人负责接受、修改或拒绝。LLM 推断的角色永远是候选，未经人工接受不能生成正式 Need、Requirement 或 Baseline。

## 复用边界

继续使用现有 FastAPI、Jinja、SQLite、Workspace、`Artifact`、`TextSpan`、`Claim`、`ModelElement`、`Relation` 与运行详情页面。没有必要新增前端构建工具或数据库。

## 页面与操作流

新增 `/w/{workspace}/requirements`：

1. 用户粘贴文本或上传需求、接口、Python、测试、配置或运维资料。
2. 点击“规则分析”，页面显示 Stakeholder、Concern、Need 和 Claim 候选及来源。
3. 如已配置 LLM，用户可点击“AI 辅助分析”；结果仍为待审核候选。
4. 用户接受、编辑或驳回利益相关方和 Need，再处理 Requirement 候选。
5. 点击“生成 RFLP”，系统只使用来源完整、已接受的 Requirement。
6. 同页显示利益相关方卡片、四层 SVG、覆盖率和未解决项，并提供 JSON/SVG 下载。

表单使用普通 HTML POST；提交后重定向回页面，避免为局部刷新增加额外状态同步。

## 数据与持久化

沿用 SQLiteRepository，在现有表基础上保存本次工作台需要的数据。上传文件存入工作区受管目录，数据库保存 Artifact 哈希和定位信息。Claim 和 ModelElement 的 `status` 使用 `candidate`、`accepted`、`rejected`。

为减少新表和重复状态机，首版复用 `ModelElement` 表达前置语义对象：

- `kind=stakeholder_candidate`：attributes 保存 explicit/inferred、source_span、confidence、reason 和 producer；
- `kind=stakeholder`：attributes 保存 category、aliases 和 derived_from；
- `kind=concern`：表示已识别关注点；
- `kind=need`：attributes 保存 stakeholder_id 和 source_claim_id。

关系增加 `mentionedAt`、`hasConcern`、`expresses`、`derivedFrom` 和 `addresses`。正式 Requirement 必须能追到已批准 Need，或明确标记为法规/约束/内部架构需求。

RFLP 继续存为 `ModelElement` 和 `Relation`：

- R 节点携带源 `claim_id`；
- F 节点用 attributes 保存 input、output、precondition、postcondition、failure_mode；
- L 节点表示职责分组；
- P 节点表示本地实现组件；
- 关系谓词固定为 `satisfiedBy`、`allocatedTo`、`realizedBy`。

## 解析与规划规则

- Markdown/文本型工程制品按非空段落和列表项形成 TextSpan；
- DOCX 用标准库 `zipfile` 与 XML 读取 `word/document.xml` 中的基础段落；
- Python 使用标准库 `ast` 读取类名、函数名、权限常量和测试名称；OpenAPI、JSON、YAML、TOML 首版按文本行扫描，不做完整语法建模；
- 明确角色使用角色词典和“某角色可以/负责/维护/批准”等句式识别；`AdminRole`、`unauthorized_user`、`/admin` 等名称按分词规则生成候选；
- 规则只自动发现 explicit 候选；隐含角色只能由 LLM 或遗漏检查清单提出，并标记 inferred；
- 首版只提供精确别名表和人工合并建议，不根据相似度自动合并；
- Concern 和 Need 从角色所在句的动作、目标和质量词生成候选，必须单独接受；
- 义务词覆盖 `必须`、`应当`、`不得`、`禁止`、`需要`、`MUST`、`SHALL`、`SHOULD`、`MUST NOT`；
- 每个来源合格的已接受 Requirement 生成一个 R 和一个对应 F；
- F 名称从谓词后的首个动作短语得到，无法判断时使用可人工编辑的“处理 + 对象”；
- L 按 Claim 主体或功能对象的稳定关键词归组；
- P 首版映射到现有本地实现类别：Web/API、SQLite Repository 或 Python Service；
- 所有 ID 来自规范化内容哈希，排序按 layer、name、id，保证重复执行结果一致。

这些启发式规则的上限会用 `ponytail:` 注释标明；当真实样本证明分类不足时再升级。

## 利益相关方门禁

- 正式 Stakeholder 必须有 TextSpan 来源或可解释的推断依据及审核状态；
- 正式 Need 必须关联已接受 Stakeholder、至少一个 Concern 和原始 Claim/TextSpan；
- inferred 候选未经接受不得产生正式模型；
- Requirement 必须来自 Need、法规/约束或内部架构标记；
- 首版不提供删除和自动合并，因此不会静默破坏既有追踪链。

遗漏检查清单只显示澄清问题：谁使用、管理权限、维护部署、负责数据、查看审计、批准变更、承担安全风险，以及哪些外部系统参与；它不会自动写入模型。

## SVG 生成

服务端直接生成 SVG：R/F/L/P 固定四栏，节点等距排列，关系使用带箭头的曲线路径。利益相关方不增加第五栏，只在图上方显示总览卡，并在选中 Requirement 时显示 Stakeholder→Concern→Need→来源链。节点文本与属性必须 HTML/XML 转义。相同图模型必须产生字节一致的 SVG。页面点击节点只用锚点和 CSS 展示详情，首版不实现拖拽。

## LLM 边界

LLM 不是主链路。仅当用户点击按钮且环境变量提供 `RFLP_LLM_BASE_URL`、`RFLP_LLM_MODEL`、`RFLP_LLM_API_KEY` 时，使用标准库 HTTP 调用 OpenAI-compatible chat completions。

输入为 TextSpan，输出必须解析为限定 JSON 结构，可包含 inferred StakeholderCandidate、Concern、Need 和 Claim。失败、超时或格式错误时显示错误并保留规则结果。API Key 不进入页面、数据库或日志。AI 结果只能是 `candidate`，不能批准 Stakeholder、Need、Claim、RFLP 或 Baseline。

## 错误与安全

- 上传仅接受 `.txt`、`.md`、`.markdown`、`.docx`、`.py`、`.json`、`.yaml`、`.yml`、`.toml`，限制为 5 MiB；
- 文件名经现有工作区安全路径逻辑处理；
- 空输入、无候选、无已接受 Claim 均显示可操作错误；
- 写入使用现有事务和失败保护；
- SVG、HTML 和下载文件名均转义或校验。

## 验证

新增一个最小端到端测试，覆盖：

1. 输入至少三条中英文需求及一个 Python/OpenAPI 文本制品；
2. 识别明确角色，并把隐含角色保持为待审核候选；
3. 接受 Stakeholder、Concern、Need 和 Claim/Requirement；
4. 验证未审核 inferred 候选不能进入正式模型；
5. 生成非固定名称的 R/F/L/P，三类关系覆盖率均为 100%；
6. 相同输入两次生成完全相同的 JSON 和 SVG；
7. Web 页面可完成输入、审核和查看来源链；
8. 未配置 LLM 时主链路仍成功。

同时运行现有全量测试与 import contracts。

## 完成标准

用户可以在本机浏览器从自己的需求与工程资料出发，人工确认利益相关方、Concern、Need 和 Requirement，并看到动态生成且可追溯到原始证据的 R/F/L/P 四层图；不再依赖固定的三条示例需求。
