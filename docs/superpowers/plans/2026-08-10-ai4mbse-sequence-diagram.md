# AI4MBSE 标准顺序图模块实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 为 AI4MBSE 增加按已确认场景选择、生成、查看和下载的标准顺序图模块。

**Architecture:** 场景转换为 Interaction 语义模型，独立计算 SequenceLayout，再由 SVG renderer 输出真实消息箭头。WebFacade 负责场景门禁和编排，路由和模板只负责选择、展示和下载。

**Tech Stack:** Python 3.11+、FastAPI、Jinja2、确定性 SVG、pytest；不增加生产依赖或前端画布库。

## Global Constraints

- 保持 Python >=3.11。
- 不引入 Mermaid、Graphviz、React 或 Canvas。
- 同步调用为实线实心箭头，异步消息为实线开放箭头，返回消息为虚线开放箭头。
- 纵向位置表示时间，生命线为垂直虚线，消息为横向 SVG 箭头。
- 只有 accepted 场景生成场景绑定图；不确定消息标记 candidate。
- Interaction 不含坐标和 SVG；Layout 不修改 Interaction；路由不计算坐标。
- 保留现有 mbse.svg 兼容接口。
- 用户文本进入 SVG 前必须 XML 转义。
- 不持久化 SVG 和坐标。

## Files

- Create: src/rflp_lite/domain/sequence.py
- Create: src/rflp_lite/application/sequence_modeling.py
- Create: src/rflp_lite/application/sequence_layout.py
- Create: src/rflp_lite/application/sequence_svg.py
- Create: src/rflp_lite/application/sequence_render.py
- Modify: src/rflp_lite/application/mbse_render.py
- Modify: src/rflp_lite/application/web_facade.py
- Modify: src/rflp_lite/interface/web/routes.py
- Create: src/rflp_lite/interface/web/templates/mbse-diagrams.html
- Modify: src/rflp_lite/interface/web/templates/base.html
- Modify: src/rflp_lite/interface/web/templates/requirements-scenarios.html
- Modify: src/rflp_lite/interface/web/static/app.css
- Create: tests/domain/test_sequence.py
- Create: tests/application/test_sequence_modeling.py
- Create: tests/application/test_sequence_layout.py
- Create: tests/application/test_sequence_render.py
- Modify: tests/application/test_mbse_render.py
- Modify: tests/interface/web/test_pages.py
- Modify: docs/DEVELOPMENT_STATUS.md

---

### Task 1: Interaction 语义和场景转换

**Interfaces:**

~~~python
validate_sequence_interaction(value: object) -> dict[str, object]
build_sequence_interaction(state: dict[str, object], scenario_id: str) -> dict[str, object]
message_sort_style(sort: str) -> str
~~~

Interaction 必须包含 format、version、id、name、source scenario revision/hash、lifelines、messages、occurrences、executions、fragments、combined fragments、operands、trace links 和 status。

- [ ] 编写失败测试：校验五种 message sort、唯一 ID、生命线引用、occurrence 引用和 operator。
- [ ] 运行：.venv/bin/python -m pytest tests/domain/test_sequence.py -q；确认新模块不存在导致失败。
- [ ] 实现 src/rflp_lite/domain/sequence.py；只做常量、引用校验和 JSON-safe 规范化，不导入 Web 或 SVG。
- [ ] 编写场景转换测试：accepted 场景生成 Interaction；draft 场景拒绝；显式“发送者 -> 接收者：消息”按顺序生成；无法解析的步骤标记 candidate。
- [ ] 实现 src/rflp_lite/application/sequence_modeling.py：优先读取 interaction_steps，否则读取旧 steps；按场景 revision/hash 生成稳定 ID；不从 faults 或 expected_outcomes 猜测 fragment。
- [ ] 运行：.venv/bin/python -m pytest tests/domain/test_sequence.py tests/application/test_sequence_modeling.py -q。
- [ ] 提交：git add src/rflp_lite/domain/sequence.py src/rflp_lite/application/sequence_modeling.py tests/domain/test_sequence.py tests/application/test_sequence_modeling.py；git commit -m "feat: add sequence interaction model"。

### Task 2: 确定性布局

**Interface:**

~~~python
layout_sequence(interaction: dict[str, object]) -> dict[str, object]
~~~

- [ ] 编写失败测试：生命线横向排列、消息从上到下排列、self-call 有 loop 坐标、reply 有独立 arrow style、fragment 无子消息时拒绝。
- [ ] 运行：.venv/bin/python -m pytest tests/application/test_sequence_layout.py -q；确认失败。
- [ ] 实现固定布局常量：LEFT=64、TOP=40、MESSAGE_TOP=128、MESSAGE_GAP=72、LIFELINE_GAP=220、BOTTOM=64；宽度至少 720，高度随消息数增长。
- [ ] 为接收方生成 activation rectangle；为 alt/opt/loop/par 计算 fragment 边界和 operand separator。
- [ ] 运行：.venv/bin/python -m pytest tests/application/test_sequence_modeling.py tests/application/test_sequence_layout.py -q。
- [ ] 提交：git add src/rflp_lite/application/sequence_layout.py tests/application/test_sequence_layout.py；git commit -m "feat: add deterministic sequence layout"。

### Task 3: SVG 箭头和渲染

**Interfaces:**

~~~python
svg_text(x, y, value, *, fill, size, weight=None) -> str
svg_line(x1, y1, x2, y2, *, style, arrow=None) -> str
render_sequence_svg(layout: dict[str, object]) -> str
~~~

- [ ] 编写失败测试：SVG 包含 arrow-filled、arrow-open、生命线虚线、reply 虚线、candidate 标记、self-call 路径和转义后的用户文本。
- [ ] 运行：.venv/bin/python -m pytest tests/application/test_sequence_render.py -q；确认失败。
- [ ] 实现 sequence_svg.py：只提供 XML 转义、文字、线段、矩形、路径和 marker，不导入业务模块。
- [ ] 实现 sequence_render.py：输出 title、defs、生命线、activation、messages、fragment 和 legend；同步/异步/reply 使用不同箭头规则。
- [ ] 运行：.venv/bin/python -m pytest tests/application/test_sequence_render.py tests/application/test_sequence_layout.py tests/application/test_mbse_render.py -q。
- [ ] 提交：git add src/rflp_lite/application/sequence_svg.py src/rflp_lite/application/sequence_render.py tests/application/test_sequence_render.py；git commit -m "feat: render sequence diagrams with UML arrows"。

### Task 4: Web 模块入口和场景选择

**Interfaces:**

~~~python
WebFacade.sequence_diagram(workspace_name: str, scenario_id: str) -> dict[str, object]
GET /w/{workspace}/requirements/mbse
GET /w/{workspace}/requirements/mbse/sequence
GET /w/{workspace}/requirements/mbse/sequence.svg
~~~

- [ ] 编写失败 Web 测试：accepted 场景能返回 scenario、interaction、svg；draft 场景拒绝；页面出现“顺序图”；accepted 场景卡包含“查看顺序图”；下载返回 image/svg+xml。
- [ ] 运行：.venv/bin/python -m pytest tests/interface/web/test_pages.py -k sequence -q；确认失败。
- [ ] 在 WebFacade 实现 sequence_diagram，调用 modeling、layout、render，返回 scenario、interaction、svg、status、warnings，不返回 layout。
- [ ] 在 routes.py 增加 MBSE 设计图页面、sequence 专用页面和 SVG 下载；无场景时显示选择器和空状态；旧 mbse.svg 无 scenario_id 时保留兼容。
- [ ] 在 base.html 增加 MBSE 设计图导航；在场景模板中仅给 accepted 场景增加查看顺序图。
- [ ] 新建 mbse-diagrams.html，提供图类型选择、accepted 场景 select、candidate warning、SVG 展示和下载。
- [ ] 只增加 diagram-toolbar、diagram-tabs、diagram-warning、sequence-svg、sequence-legend 局部样式。
- [ ] 运行：.venv/bin/python -m pytest tests/interface/web/test_pages.py -k sequence -q。
- [ ] 提交：git add src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/templates/mbse-diagrams.html src/rflp_lite/interface/web/templates/base.html src/rflp_lite/interface/web/templates/requirements-scenarios.html src/rflp_lite/interface/web/static/app.css tests/interface/web/test_pages.py；git commit -m "feat: expose scenario sequence diagram module"。

### Task 5: 兼容性、状态和完整验证

- [ ] 修改 mbse_render.py：view=sequence 使用 legacy model adapter、sequence_layout 和 sequence_render；all/use_case/activity 保持现有结果。
- [ ] 修改 test_mbse_render.py：旧 sequence SVG 断言 Sequence Diagram、filled marker、open marker；all 继续断言 Use Case、Activity、Sequence。
- [ ] 修改 DEVELOPMENT_STATUS.md，增加 MBSE 顺序图模块入口和首版能力，不宣称完整 SysML v2/UMLDI。
- [ ] 运行回归：.venv/bin/python -m pytest tests/application/test_mbse_render.py tests/application/test_mbse_modeling.py tests/application/test_mbse_exchange.py tests/application/test_scenarios.py tests/application/test_scenario_execution.py tests/interface/web/test_pages.py -q。
- [ ] 运行完整测试：.venv/bin/python -m pytest -q；预期全部通过。
- [ ] 运行构建：python -m build；预期 wheel 和 sdist 构建成功。
- [ ] 运行导入边界：.venv/bin/python -m importlinter；预期 broken=0。
- [ ] 运行差异检查：git diff --check && git status --short；确认无 whitespace 错误且无关未跟踪文件未被触碰。
- [ ] 提交：git add src/rflp_lite/application/mbse_render.py tests/application/test_mbse_render.py tests/interface/web/test_pages.py docs/DEVELOPMENT_STATUS.md；git commit -m "test: verify sequence diagram integration"。

## Plan Self-Review

- Spec coverage: Task 1 covers Interaction/Lifeline/Message/Occurrence/Execution/fragment and conservative text conversion; Task 2 covers time layout and activation; Task 3 covers real arrows, escaping and self-call; Task 4 covers visible module, scenario selection, gate, download and isolation; Task 5 covers compatibility, status and complete verification.
- Placeholder scan: no TBD, TODO or unspecified test command remains.
- Type consistency: build_sequence_interaction feeds layout_sequence; layout_sequence feeds render_sequence_svg; WebFacade returns scenario, interaction, svg, status and warnings without exposing layout.
- Scope check: one independent sequence-diagram subsystem; existing use-case/activity/RFLP behavior remains unchanged except for sequence compatibility rendering and navigation.
