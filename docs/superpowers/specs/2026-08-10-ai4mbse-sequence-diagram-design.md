# AI4MBSE 标准顺序图模块设计说明

## 1. 目标与边界

为 AI4MBSE 增加一个用户可发现、可选择、可查看和可下载的顺序图模块。该模块只服务于 AI4MBSE 内部，不做 Cameo、Capella、Rhapsody 等外部工具互导，也不引入重量级在线画布编辑器。

本次实现以 UML 2.5.1 Interaction / Sequence Diagram 的交互语义为基线，并采用 SysML 的系统工程场景语境。SysML 的顺序图沿用 UML 的顺序图定义，包括生命线、消息、同步/异步通信、返回消息和 `alt`、`opt`、`loop`、`par` 等交互操作符。

规范依据：

- OMG UML 2.5.1：<https://www.omg.org/spec/UML/>
- OMG UML 2.5.1 机器可读抽象语法和 Diagram Interchange 文件：<https://www.omg.org/spec/UML/machine-readable>
- OMG SysML 官方说明：<https://www.omg.org/sysml/SysML_Modelling_Language_explained-finance.pdf>
- OMG SysML 2.0 正式规范：<https://www.omg.org/spec/SysML/2.0>

本次交付的目标是“标准语义的只读顺序图视图”，不是完整 UML/SysML 建模器。模型编辑、实时仿真、协同建模和完整 UMLDI 交换不在本次范围内。

## 2. 现状与问题

项目已经具备以下能力：

- `requirements_workbench` 能保存结构化需求和场景；
- 场景具备参与者、前置条件、步骤、预期结果、故障、Requirement 关联和审核状态；
- `mbse_modeling` 能生成 actors、lifelines、messages 等 MBSE 语义集合；
- `mbse_exchange` 能校验和导出 MBSE JSON/SysML 子集；
- `mbse_render.py` 能返回 SVG，但当前 Sequence 部分只是文字列表；
- Web 已有 `/requirements/mbse.svg?view=...` 原始 SVG 接口，但导航直接指向原始 SVG，缺少可发现、可选择的设计图模块。

当前 MBSE 消息主要只有 `from_id`、`to_id`、`name` 和 `sequence`。所有自动生成需求消息都可能使用相同的 sequence 值，因此不能把该字段当成正式交互顺序。当前场景步骤也主要是自由文本，不能未经确认就推断出真实的发送者和接收者。

设计必须解决：

1. 用户能在系统导航中看见“MBSE 设计图”和“顺序图”；
2. 用户能先选择一个已确认场景，再查看该场景的顺序图；
3. 消息必须以真实 SVG 箭头表达，不是文字清单或 Unicode 箭头；
4. 语义模型、布局和 SVG 渲染相互隔离；
5. 不确定的自由文本不能被伪装成已确认的交互语义；
6. 顺序图改动不影响用例图、活动图、RFLP 和场景执行轨迹。

## 3. 用户工作流

左侧需求规划导航增加独立入口：

```text
需求规划
├── 项目需求概览
├── 需求输入
├── 利益相关方
├── 需求确认
├── 场景生成
├── RFLP 规划图
└── MBSE 设计图
```

进入 MBSE 设计图页面后，用户可以选择：

```text
用例图 | 活动图 | 顺序图
```

顺序图视图必须额外提供场景选择器：

```text
选择场景：[已确认场景 A ▼]
[生成/刷新顺序图] [下载 SVG]
```

场景卡在场景状态为 `accepted` 时提供“查看顺序图”入口。草稿和已驳回场景只显示“需先确认场景”的提示，不生成图。场景确认只代表场景本身通过审核，不代表自由文本已经自动获得完整消息语义；候选消息必须在图中明确标记。

建议的页面和下载地址：

```text
GET /w/{workspace}/requirements/mbse
GET /w/{workspace}/requirements/mbse/sequence?scenario_id={id}
GET /w/{workspace}/requirements/mbse/sequence.svg?scenario_id={id}
```

现有接口 `/w/{workspace}/requirements/mbse.svg?view=...` 保留兼容；其 `view=sequence` 在没有 `scenario_id` 时使用当前 MBSE 模型的兼容投影，并在页面中标记为“未绑定具体场景的兼容视图”。新页面的场景顺序图要求绑定 `scenario_id`。

## 4. 标准交互语义

顺序图不是一个消息数组，而是一个 `Interaction` 及其有序的 `InteractionFragment` 结构。

### 4.1 Interaction

每个已确认场景对应一个交互：

```text
Scenario 1 ──→ Interaction 1 ──→ Sequence Diagram 1
Scenario 2 ──→ Interaction 2 ──→ Sequence Diagram 2
```

交互至少包含：

- `id`：稳定交互 ID；
- `name`：场景标题；
- `source_scenario_id`：来源场景；
- `source_scenario_revision`：来源场景版本；
- `source_scenario_hash`：来源场景内容哈希；
- `lifelines`：生命线集合；
- `messages`：消息集合；
- `occurrences`：消息发送/接收和执行起止事件；
- `executions`：激活区间；
- `fragments`：有序交互片段树；
- `trace_links`：Requirement 和场景来源关系；
- `status`：`candidate`、`ready`、`stale` 或 `invalid`。

该交互模型是顺序图的语义模型，不包含 x/y 坐标、宽高、颜色和 SVG 字符串。

### 4.2 Lifeline

生命线表示参与场景的 Actor、System、Block 或 Part：

```text
Lifeline {
  id
  name
  kind: actor | system | block | part
  classifier_id: optional
  requirement_ids: tuple[str, ...]
}
```

生命线在图上表现为顶部标题、对象框和向下延伸的虚线。纵向位置表示时间推进，但生命线本身不使用向下箭头表示消息。

### 4.3 Message 与 Occurrence

消息必须显式引用发送和接收生命线，并通过 occurrence 表示发生点：

```text
Message {
  id
  name
  sort: sync_call | async_call | reply | create | delete
  sender_lifeline_id
  receiver_lifeline_id
  send_occurrence_id
  receive_occurrence_id
  arguments: tuple[str, ...]
  guard: optional[str]
  requirement_ids: tuple[str, ...]
}
```

正式顺序不能只依赖 `sequence: int`。顶层 `fragments` 和嵌套 fragment 的有序位置才是消息先后关系。旧 `sequence` 字段保留为兼容数据，但不再是新的顺序图语义来源。

第一版箭头规则：

| Message sort | 图形线型 | 箭头 | 含义 |
|---|---|---|---|
| `sync_call` | 实线 | 实心箭头 | 同步操作调用 |
| `async_call` | 实线 | 开放箭头 | 异步调用或信号 |
| `reply` | 虚线 | 开放箭头 | 返回消息 |
| `create` | 虚线 | 开放箭头 | 创建目标生命线 |
| `delete` | 虚线 | 开放箭头，目标生命线末端为 `X` | 删除目标生命线 |

图形箭头必须真正绘制在 SVG 中，消息名称放在箭头附近，不能使用 `→` 字符代替箭头。

### 4.4 ExecutionSpecification

执行规格表示接收消息后目标生命线上的行为执行：

```text
ExecutionSpecification {
  id
  lifeline_id
  start_occurrence_id
  finish_occurrence_id
  operation: optional[str]
  depth: int
}
```

它在图上表现为生命线上的窄矩形激活框。嵌套调用使用更深的 `depth` 和更窄的激活框，不直接修改消息顺序。

### 4.5 CombinedFragment

交互片段使用树结构，而不是用特殊文本拼出分支：

```text
CombinedFragment {
  id
  operator: alt | opt | loop | par
  operands: tuple[InteractionOperand, ...]
}

InteractionOperand {
  id
  guard: optional[str]
  fragments: tuple[InteractionFragment, ...]
}
```

第一版渲染器支持 `alt`、`opt`、`loop`、`par` 的标准框、操作数分隔线和守卫条件。没有结构化来源时，不根据自由文本故障或预期结果擅自推断 `alt` 或 `loop`。

## 5. 场景到交互模型的转换

场景是业务意图来源，Interaction 是正式图语义来源。两者不能混为一个对象。

### 5.1 结构化消息优先

如果场景包含结构化 `interaction_steps`，每一步使用：

```text
{
  id,
  order,
  sender,
  receiver,
  message,
  sort,
  guard,
  fragment_id,
  requirement_ids
}
```

转换器按显式 sender/receiver 创建生命线和消息，按 `order` 创建 occurrence 顺序，并生成对应的执行规格。

### 5.2 旧自由文本兼容策略

当前场景只有 `steps` 自由文本时，转换器执行保守兼容：

- 场景的 actors 和“系统”生成候选生命线；
- 能从文本中明确识别发送者/接收者时才建立对应消息；
- 无法识别时生成 `candidate` 消息，使用可见的“待确认语义”标记；
- 不把自由文本自动标记为 `accepted`；
- 页面提示用户补充结构化发送者、接收者和消息类型；
- 不从 faults、expected_outcomes 自动推断 `alt`、`loop` 或返回消息。

这样现有项目可以先显示真实箭头，但不会把 AI 或规则猜测冒充为已确认消息。只要来源场景为 `accepted`，页面就可以展示候选顺序图；如果交互中存在候选消息，页面必须显示“部分消息语义待确认”的状态，不得显示为 `ready`。

### 5.3 版本和失效

Interaction 不修改现有 `ai4mbse/mbse` v1 交换模型，作为顺序图专用的派生模型使用。每次生成都记录来源场景的 revision/hash。Interaction 的状态为 `candidate`、`ready`、`stale` 或 `invalid`；只有所有消息的发送者、接收者和消息类型都具备结构化来源时才能成为 `ready`。

当场景被编辑并产生新 revision 时，旧交互标记为 `stale`；正式页面只展示最新来源的交互。首次实现可以按请求重新派生，不保存 SVG 或坐标；如果后续加入人工消息编辑，再持久化 Interaction 并沿用 revision/hash 门禁。

场景执行轨迹 `scenario_runs` 仍然是声明性验证证据，不作为顺序图模型来源。

## 6. 分层与代码边界

新增顺序图专用边界，文件职责固定如下：

```text
src/rflp_lite/domain/sequence.py
    顺序图值对象、枚举和不变量

src/rflp_lite/application/sequence_modeling.py
    场景/旧 MBSE 数据 → Interaction
    结构化转换、兼容投影和语义校验

src/rflp_lite/application/sequence_layout.py
    Interaction → SequenceLayout
    生命线、消息、激活框和 fragment 的坐标计算

src/rflp_lite/application/sequence_render.py
    SequenceLayout → SVG
    箭头、虚线生命线、激活框、条件框和文字

src/rflp_lite/application/sequence_svg.py
    XML 转义、文本、线段、矩形、箭头、虚线和尺寸等无业务含义的 SVG 基础图元

src/rflp_lite/application/mbse_render.py
    保留统一视图入口，调用独立 sequence 渲染器

src/rflp_lite/application/web_facade.py
    对 Web 暴露顺序图应用接口和场景选择编排

src/rflp_lite/interface/web/routes.py
    只处理路径、参数、响应和错误

src/rflp_lite/interface/web/templates/mbse-diagrams.html
    MBSE 设计图选择、场景选择、状态提示和 SVG 展示
```

依赖方向固定为：

```text
Web route → WebFacade → sequence_modeling → sequence_layout → sequence_render
                  ↑              ↑              ↑                 ↑
          domain/sequence  domain/sequence  domain/sequence  sequence_svg
```

禁止：

- domain 导入 SVG、FastAPI 或模板；
- layout 修改 Interaction；
- render 读取需求工作台或场景数据库；
- route 计算坐标、拼接 SVG 或判断消息语义；
- 顺序图模块依赖用例图、活动图或 RFLP renderer。

`sequence_svg.py` 只能包含 XML 转义、文本、线段、矩形、箭头、虚线和尺寸计算等通用能力，不包含 Actor、Requirement、Scenario 等业务判断。

## 7. 应用和 Web 接口

应用层接口：

```python
build_sequence_interaction(state: dict[str, object], scenario_id: str) -> Interaction
layout_sequence(interaction: Interaction) -> SequenceLayout
render_sequence_svg(layout: SequenceLayout) -> str
```

WebFacade 对外提供：

```python
sequence_diagram(
    workspace_name: str,
    scenario_id: str,
) -> dict[str, object]
```

返回内容包含场景信息、交互状态、候选/确认提示、可用视图和 SVG，不向路由泄漏布局实现。

错误边界：

- workspace 不存在：沿用现有工作区错误；
- scenario 不存在：返回 404/页面错误提示；
- scenario 未 `accepted`：不生成图，显示审核门禁；
- Interaction 结构非法：返回明确的 ContractViolation；
- 没有消息：输出合法空图和“暂无可显示消息”；
- 不支持的 view：统一拒绝，不进入 renderer；
- SVG 文本：继续进行 XML 转义；
- 任何图形失败：不修改需求、场景、MBSE 或执行轨迹。

## 8. 测试和验收

### 8.1 领域和建模测试

- Interaction、Lifeline、Message、Occurrence、Execution 和 CombinedFragment 的 ID、引用和状态不变量；
- 同一场景 revision 生成稳定的交互 ID 和消息 ID；
- 显式 sender/receiver 按 order 形成正确发送/接收 occurrence；
- 无法解析的自由文本被标记为 candidate，不被误标 accepted；
- `alt`、`opt`、`loop`、`par` 的嵌套结构可校验；
- 场景 revision/hash 变化会使旧交互 stale。

### 8.2 布局和 SVG 测试

- 生命线按确定性 x 坐标排列；
- 消息按 occurrence 顺序从上到下排列；
- 同步消息是实线实心箭头；
- 异步消息是实线开放箭头；
- 返回消息是虚线开放箭头；
- 自调用、激活框和返回消息不破坏布局；
- fragment 包含标准框、守卫文字和操作数分隔线；
- 重复输入得到字节稳定 SVG；
- SVG 不出现未转义的用户文本或 Unicode 箭头替代图形箭头。

### 8.3 Web 测试

- 左侧导航出现 MBSE 设计图；
- MBSE 设计图页面能够选择顺序图；
- 已确认场景出现在场景选择器；
- 场景卡能够跳转到对应顺序图；
- 未确认场景显示门禁；
- 页面显示真实横向消息箭头、纵向生命线和从上到下的时间顺序；
- SVG 下载按场景返回正确内容；
- 旧 `/requirements/mbse.svg?view=sequence` 接口继续可用；
- 用例图、活动图、RFLP、场景执行和现有 JSON/SysML 导出测试全部通过。

## 9. 非目标和后续扩展

本次不实现：

- 拖拽移动生命线和消息；
- 直接在 SVG 上编辑语义；
- 运行时仿真或执行真实消息；
- 完整 UMLDI 文件导入导出；
- 完整 SysML v2 抽象语法映射；
- 外部商业 MBSE 工具互导；
- 多人协同锁定和权限控制。

后续如需编辑，编辑对象应是 Interaction 语义模型，而不是 SVG 坐标；如需扩展状态图或组件图，应新增独立的领域、建模、布局和渲染边界，不修改顺序图内部实现。

## 10. 设计决策总结

1. 顺序图以场景为选择和生成单位，不把多个需求消息混成一张图。
2. 采用 UML Interaction 语义，不把消息数组直接当成正式顺序图。
3. 横向图形箭头表达消息，纵向位置表达时间，生命线使用垂直虚线。
4. 结构化消息优先，自由文本只能生成候选并明确提示不确定性。
5. 语义、布局、SVG 和 Web 四层隔离。
6. 图是场景/Interaction 的派生视图，不把 SVG 当作模型存储。
7. 先完成稳定只读模块和真实箭头，再考虑编辑和仿真。
