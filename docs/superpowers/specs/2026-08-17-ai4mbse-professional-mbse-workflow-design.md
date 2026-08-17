# AI4MBSE 领域中立专业 MBSE 工作流设计

日期：2026-08-17

## 目标

在不改变现有项目创建、需求输入、一次提交自动分析和页面导航习惯的前提下，把当前基础需求/RFLP/MBSE 输出提升为接近 Toothbrush 案例 PPT 的专业 MBSE 多视图工作流。

新项目默认由领域中立 LLM 根据当前项目输入生成内容；领域包保留为项目级可选配置接口，默认不启用，不参与默认自动分析。所有数据继续按项目工作区隔离。

最终交付的不是静态 PPT 图片，而是当前项目的一份统一、可编辑、可追溯的 MBSE 语义模型，以及由专业绘图引擎生成的不同工程视图。

## 背景与现状

参考文件 `MBSE 实践案例Toothbrush(1).pptx` 展示了完整的 MBSE 过程：利益相关方/环境分析、需求分析、生命周期分析、用例分析、运行场景、功能分析、功能交互、功能场景、逻辑分解、逻辑交互、物理构建模块、组件—构建模块分配、物理交互和技术需求细分。

当前项目已经具备：

- 项目工作区和独立 SQLite 工作台；
- 需求输入、结构化需求和审核队列；
- 利益相关方、场景、需求追溯和基础 RFLP；
- 基础 MBSE actors/use_cases/activities/messages；
- 场景顺序图的语义模型和确定性 SVG 渲染；
- 显式领域包和领域发现入口。

当前缺口主要是：

- 默认自动分析仍有领域包路径和固定领域内容残留风险；
- MBSE 模型尚未形成运行—功能—逻辑—物理—技术需求的统一闭环；
- RFLP/MBSE 渲染仍有列表式或简化卡片式视图；
- 功能交互、生命周期、逻辑/物理交互、分配表和技术需求分类缺少统一模型与专业布局；
- 渲染器与语义模型耦合，后续接入 Graphviz/PlantUML 等工具不够清晰。

## 范围

### 本次范围

1. 保留当前主交互：项目 → 需求输入 → 点击分析 → 自动生成并查看结果。
2. 默认分析不调用 `urban-medical-aam-v1`、`common-v1` 或其他领域包。
3. 保留领域包注册、查看和项目级显式选择接口；默认 `pack_id` 为空，窄领域包不在本次新增。
4. 增强统一 MBSE 语义模型，覆盖运行、功能、逻辑、物理和技术需求分区。
5. 为不同图类型提供专业布局：Graphviz 主引擎、PlantUML 场景/活动引擎、矩阵渲染器和 SVG 兼容兜底。
6. 需求编辑、审核和删除沿用当前入口；自动派生内容随需求变化同步失效或重建，用户手工内容不被无提示删除。
7. 所有自动分析、模型保存、渲染和导出保持项目作用域校验。

### 非目标

- 不把 PPT 页面转换成静态图片或复制其具体品牌样式；
- 不引入微服务、全局共享工作台或跨项目知识库；
- 不要求本次支持商业 SysML 工具的原生模型编辑协议；
- 不在本次新增窄领域专业包；
- 不训练新模型；
- 不为主流程增加人工配置或重复确认步骤。

## 设计

### 1. 总体架构

保留现有 `WebFacade`、工作区目录和 SQLite 工作台作为应用边界，在应用层增加统一的 MBSE 模型编排和渲染适配层：

```text
需求输入 / 当前项目状态
          ↓
项目作用域绑定与引用校验
          ↓
一次领域中立 LLM 分析
          ↓
Project Analysis Normalizer
          ↓
统一 MBSE Semantic Model
          ↓
MBSE View Registry
    ┌──────────┬───────────┬──────────┬──────────┐
    │ Graphviz │ PlantUML  │ Matrix   │ SVG      │
    │ 结构/关系│ 时序/活动 │ 表格/矩阵 │ fallback │
    └──────────┴───────────┴──────────┴──────────┘
          ↓
当前项目页面、SVG/PDF/PNG、JSON/SysML/源文件导出
```

渲染器只接收已经归一化、已验证的当前项目模型，不读取其他工作区，也不调用领域包。绘图工具不保存业务状态，SQLite 仍然是项目模型和审计记录的唯一持久化边界。

### 2. 统一 MBSE 语义模型

`mbse` 升级为版本化模型，保留旧字段的兼容投影，增加以下分区：

```text
context
├─ system
├─ stakeholders
├─ environment_nodes
└─ environment_exchanges

operational
├─ requirements
├─ requirement_categories
├─ lifecycle_phases
├─ lifecycle_transitions
├─ use_cases
└─ operational_scenarios

functional
├─ functions
├─ function_decomposition
├─ functional_flows
├─ functional_scenarios
└─ functional_requirements

logical
├─ logical_components
├─ logical_decomposition
└─ logical_flows

physical
├─ physical_blocks
├─ component_allocations
├─ physical_flows
└─ technical_requirements

traceability
└─ typed_relations
```

每个实体至少包含：

- `id`、`name`、`description`、`status`、`producer`；
- `source_region_ids` 或 `source_requirement_ids`；
- `requirement_ids`、`parent_id`、`input_ids`、`output_ids` 等适用追溯字段；
- `confidence`、`diagnostics` 和 `needs_analysis` 标记。

关系只使用明确的工程语义：

```text
refines / satisfies / allocatedTo / realizedBy / contains
exchanges / triggers / verifies / constrainedBy / derivedFrom
```

LLM 只负责提出领域实体、语义、候选关系和来源；确定性归一化器负责去重、限制数量、过滤未知引用、补齐最小链路和生成诊断。缺失内容使用 `needs-analysis` 占位，不使用固定行业名称伪造。

### 3. 领域中立 LLM 分析

默认一次分析请求的 payload 只包含：

- 当前项目需求输入和输入区段；
- 当前项目已有的用户手工对象和必要的当前项目上下文；
- 当前激活的 LLM 配置；
- 可选的项目级 `domain_pack_id`，仅在用户明确选择领域增强时存在。

默认请求不得包含任何领域包内容、其他工作区数据、派生 SVG、历史审计全集或与当前输入无关的对象。

响应应覆盖以下结构：

```json
{
  "system": {},
  "stakeholders": [],
  "environment": {"nodes": [], "exchanges": []},
  "requirements": [],
  "requirement_categories": [],
  "lifecycle": {"phases": [], "transitions": []},
  "use_cases": [],
  "operational_scenarios": [],
  "functions": [],
  "functional_flows": [],
  "functional_scenarios": [],
  "functional_requirements": [],
  "logical_components": [],
  "logical_flows": [],
  "physical_blocks": [],
  "component_allocations": [],
  "physical_flows": [],
  "technical_requirements": [],
  "relations": [],
  "open_questions": [],
  "diagnostics": []
}
```

仍然只发送一次完整项目分析请求；允许一次 JSON 修复重试，但不按每种图重复发送同一份完整文本。LLM 失败、未配置或结构无效时保留当前项目可解析需求，状态为 `waiting_for_llm`，不生成默认领域对象。

### 4. 视图注册与专业渲染

视图注册表为每种视图声明：源模型分区、允许的节点/关系、布局引擎、导出格式、空状态和诊断规则。

| 视图 | 主引擎 | 布局语义 |
|---|---|---|
| environment | Graphviz | 系统中心、外部利益相关方和交换流 |
| stakeholder_hierarchy | Graphviz | 利益相关方层级树 |
| requirements_tree | Graphviz | 需求类别和需求分解树 |
| lifecycle | Graphviz | 生命周期阶段与转换时间线 |
| use_case_tree | Graphviz | 生命周期/阶段/用例运行分解树 |
| operational_scenario | PlantUML | 参与者泳道和外部交换时序 |
| function_tree | Graphviz | 功能分解树 |
| function_interaction | Graphviz | 功能、环境和流的交互网络 |
| functional_scenario | PlantUML | 功能活动、顺序、循环和并行 |
| logical_tree | Graphviz | 逻辑组件/PBS 分解树 |
| logical_interaction | Graphviz | 逻辑组件和利益相关方之间的交换流 |
| allocation_matrix | Matrix | 组件、构建模块、制造/购买或实现方式 |
| physical_interaction | Graphviz | 物理构建模块、接口和外部交换 |
| technical_requirements | Graphviz | 技术需求类别和需求细分树 |
| traceability_matrix | Matrix | 利益相关方—需求—架构—验证覆盖 |
| rflp | Graphviz | R/F/L/P 分层追溯与接口关系 |

Graphviz 作为结构/关系图主引擎，PlantUML 作为时序/活动图引擎，矩阵使用项目内确定性表格渲染器。现有 SVG renderer 保留为兼容 fallback，并在页面和导出 metadata 中记录 `renderer=fallback` 与原因。

绘图源文件必须由模型编译器生成，不能接受 LLM 直接提供坐标或未经校验的绘图代码。所有文本在转换为 DOT/PlantUML 前转义；节点和边仍保留 `data-source-id`、关系语义和追溯 ID。

### 5. 专业绘图引擎适配器

新增统一端口，不在业务服务中直接拼接命令：

```python
class DiagramEngine(Protocol):
    engine_id: str

    def available(self) -> bool: ...
    def render(self, source: str, output_format: str = "svg") -> bytes: ...

class DiagramCompiler(Protocol):
    def compile(self, model: dict[str, object], view_id: str) -> str: ...
```

实现边界：

- `GraphvizEngine`：检测 `dot`，设置固定超时、禁止任意文件访问，输出 SVG/PDF/PNG；
- `PlantUMLEngine`：检测 PlantUML/JVM 可用性，只接收内部生成的 PlantUML 文本；
- `MatrixRenderer`：不依赖外部二进制，输出语义化 HTML/SVG/CSV；
- `FallbackSvgEngine`：沿用现有确定性 renderer，输出可读但较简化的图并提供诊断。

应用启动或项目图形页面读取引擎状态，不改变主需求输入页面。缺失引擎不会阻断需求分析或项目保存。

### 6. 项目隔离与需求生命周期

- 每个项目继续使用 `workspace/.rflp/model.db`；
- `project_scope.workspace` 和输入哈希在工作台保存时绑定；
- 所有场景、需求、RFLP、MBSE、关系、图规格和审计引用在保存前验证属于当前项目；
- 用户编辑/删除需求沿用现有入口；自动派生对象按来源需求清理或重建；
- 手工对象保留，只解除删除需求的关联；
- 旧工作区中已有的领域包历史不主动删除，但默认重新分析不再追加固定领域结果；
- 显式领域包操作必须记录项目、pack ID、版本和审计事件。

### 7. 页面与交互

不新增主流程步骤。现有需求输入、项目切换和分析按钮保持不变。

分析完成后的既有 MBSE/RFLP 页面增加视图选择和引擎状态信息：

- 默认进入总览，显示当前系统、模型层级、追溯覆盖和待分析数量；
- 用户可在现有图形入口中选择环境、生命周期、功能、逻辑、物理、场景、分配表等视图；
- 每个视图提供 SVG/PDF/PNG 和结构 JSON/源文件下载；
- 视图节点显示来源需求、状态和关系摘要；
- 领域包配置放在项目设置/高级接口，不进入主分析按钮的必填表单。

### 8. 错误与降级

| 情况 | 行为 |
|---|---|
| LLM 未配置 | 保留可解析需求，状态 `waiting_for_llm` |
| LLM 超时/失败 | 保留旧项目人工内容，清理本次临时自动结果并显示诊断 |
| 响应 JSON 无效 | 允许一次修复重试，仍失败则进入等待状态 |
| 响应缺少某模型层 | 生成 `needs-analysis` 占位和诊断 |
| Graphviz 不可用 | 使用 fallback，标记渲染器状态 |
| PlantUML 不可用 | 场景/活动图使用已有 SVG 时序兼容渲染，标记降级 |
| 跨项目引用 | 保存前抛出作用域错误，不写入当前项目 |
| 图节点过多 | 依据视图和层级分页/折叠，不删除模型数据 |

## 测试策略

1. **模型契约**：验证各分区字段、关系语义、状态、来源和未知引用过滤。
2. **领域中立**：以牙刷、制造设备、软件平台等不同输入夹具验证不出现固定医疗航空实体。
3. **项目隔离**：两个项目生成不同利益相关方、场景、架构和图，刷新/重启后不交叉；伪造跨项目引用必须拒绝。
4. **一次分析**：默认提交只调用一次项目分析请求，payload 不含领域包或派生图；只允许一次 JSON 修复重试。
5. **全视图生成**：同一模型能生成环境、需求、生命周期、用例、场景、功能、逻辑、物理、分配表、技术需求和追溯视图。
6. **渲染适配器**：Graphviz/PlantUML 可用时校验 SVG/PDF/源文件；引擎缺失时验证 fallback 和诊断，不影响保存。
7. **图质量**：验证关系方向、层级、箭头、节点 source ID、分页稳定性和转义；不出现列表式伪图或 `Python Service` 等固定占位名称。
8. **需求生命周期**：需求编辑/删除后自动派生对象和图状态正确更新，用户对象与审计历史保留。
9. **回归**：现有项目管理、领域包显式入口、导入导出、场景顺序图、MBSE 审核和全量 Web 测试继续通过。

## 验收标准

- 新项目输入“设计一款医用安全电动牙刷”并点击一次分析后，能在现有项目页面中看到与输入相关的利益相关方、环境、需求分类、生命周期、用例、运行场景、功能分解/交互、逻辑分解/交互、物理交互、分配表、技术需求和 RFLP/追溯视图。
- 上述视图来自同一份当前项目模型，节点之间能够通过来源需求和关系互相追溯。
- 不同领域项目生成各自领域实体；默认流程不出现飞行员、空管、患者、飞行汽车等固定领域内容。
- 不同项目切换、刷新和重启后只显示当前项目数据，跨项目引用保存失败。
- 用户不需要额外填写领域、视图或绘图配置才能获得完整自动分析；领域包只作为可选高级能力。
- Graphviz/PlantUML 可用时输出专业图形；缺失时系统仍可保存并明确显示 fallback 原因。
- LLM 或绘图引擎失败时不污染其他项目、不生成伪造领域结果，并给出可读诊断。

## 取舍

这不是微服务架构：只有一个统一语义模型、一个视图注册表和几个本地渲染适配器。实现复杂度主要集中在 MBSE 模型契约和视图编译器，运行时依赖通过能力探测和 fallback 控制。

不在本轮引入 Cameo、Capella 等商业 SysML 建模工具的原生集成；保留 SysML/JSON/图源文件导出接口，后续可以通过新增适配器连接更重的专业工具，而不改变项目模型和用户主流程。
