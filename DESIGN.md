# Web UI Design — Light Precision Instrument (B1)

> Direction pinned by the user in brainstorming（screen B1）。设计决策记录在 `base.html` 头部注释与 `static/app.css`；本文档是稳定摘要，改动样式前先读这里。

## 方向

RFLP-Lite 是工程模型真理的精密仪表，不是 SaaS 仪表盘：拒绝 dark-teal AI 控制台外观、嵌套卡片和青绿黑底强调。

| 维度 | 值 |
|---|---|
| 画布 | 纸白 `#f6f7f9` |
| 面板 | 白色 `#ffffff`，发丝分隔 `#d7dbe2` |
| 文字 | 墨色 `#191c22` / `#2b3038`，弱化 `#6b7280` |
| 强调 | 单一深蓝 `#1b4fd8`（hover `#1437b2`、浅底 `#eef2ff`） |
| 语义色 | ok `#18794e` / warn `#946200` / bad `#b42318`（各带浅底与边界） |
| 形状 | 4px 圆角、扁平表面、tabular numerals |

Token 全部定义在 `app.css` 的 `:root`（短名：`--bg/--panel/--ink/--acc/--ok/--warn/--bad` 等），模板只引用语义类，不写裸色值。

## 布局与叙事

- 固定左侧导航（分组标签）＋ 顶部白条（服务状态点）＋ 内容标题
- 首屏：四个发丝度量块、流水线步骤行、状态胶囊
- 每条模型对象（Claim / Baseline / Candidate / Evidence）都是可见、可验证的单位；每次运行的状态一眼可读

## 收尾状态

- 全量 365 测试通过、Import Linter 4 契约、`python -m build` 成功，`--color-accent` 等旧 token 断言已迁移到 `--acc`
- 无暗色残留（`color-scheme: light` 唯一来源）；SVG 图形由渲染器自带主题，不随页面样式改变