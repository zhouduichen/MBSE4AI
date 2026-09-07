# Web UI Design — Light Precision Instrument (B1)

这是 v2 资源型 Web UI 的视觉基线。页面以工程模型和运行状态为主，不把模型对象包装成营销型 SaaS 仪表盘。

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

- 五个资源页保持同一套浅色、细分隔线和可读状态标签。
- Projects 展示项目范围；Analysis 展示阶段运行；MBSE Model 展示图/矩阵投影；Evidence & Issues 展示证据和门禁问题；Settings 展示模型配置。
- 页面不复制模型真源，所有对象和状态来自资源 API / ModelGraph。

## 收尾状态

- 资源页使用本地 CSS 和 HTMX，不需要前端构建步骤。
- SVG 由确定性渲染器生成；页面主题不改变模型导出的内容哈希。
