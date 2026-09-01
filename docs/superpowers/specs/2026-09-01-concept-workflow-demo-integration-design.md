# 一键概念方案主流程整合设计

**日期：** 2026-09-01  
**范围：** 1.1 → 1.2 → 2.1 → 2.2 现场演示主链  
**目标：** 在现有 RFLP-Lite 模块之上补齐需求入口、Requirement→Envelope 桥、历史方案 Demo 数据、工作流编排和 Web 结果展示，使用户可以从一句话或文档一次运行到概念设计推荐基线。

## 1. 背景与现状

当前项目已经具备以下可复用能力：

- `requirement_semantics`、`requirement_details` 和需求工作台可生成带来源和审核状态的结构化 Requirement；
- 需求工作台已经能够生成 MBSE 草稿/模型，现有 `requirements/run-flow` 仍是独立入口；
- `create_indicator_envelope()`、领域包参数规则和单位转换已经存在；
- `SchemeRecord`、方案导入、相似检索、参数化 SVG 布局生成和 `DisciplineAdapter` 批量评估已经存在；
- `run_optimization()` 已经有迭代记录结构，但当前概念设计服务将评估预算限制为初始批次，导致默认演示通常没有真正新增候选；
- Web 已有概念设计、需求输入和候选评审页面，但概念设计页没有在缺少 `run_id` 时自动读取最近概念运行，结果页也主要展示内部状态和 ID。

本设计只做连接层、演示数据、页面和验收收口，不重写现有算法，不实施 3.1–3.3 的三维 CAD、PMI/GD&T 或 DFM/DFA。

## 2. 设计目标与非目标

### 2.1 目标

1. 同一句话重复执行时，子句顺序、Requirement 身份、数值、单位、比较符和来源稳定。
2. 已审核 Requirement 能自动形成 2.1 使用的 `IndicatorEnvelope`，每个字段可追溯到 Requirement，并区分 `explicit`、`derived`、`suggested`。
3. 历史方案作为版本化 Demo Dataset 导入一次即可复用，重复初始化不会重复写入。
4. 一个 Application Service 负责固定主链和中间结果保存，Web 不负责编排。
5. 默认 Demo 至少完成“初始 5 个候选 → 新增 2~3 个优化候选 → 第二次评估 → 最终 Pareto”，并有非空 `iteration_records`。
6. Web 首页提供一句话/文档入口，结果页按工程过程展示需求、MBSE、检索、布局、数值评估、Pareto 和推荐基线。
7. 概念推荐与正式工程批准分离：推荐基线使用 `provisional_selected`，正式批准仍受 `development_only` / evaluator approval 门禁约束。
8. 端到端测试覆盖从 Demo Workspace 到最终推荐，安装增加一个包含 Web、文档、OCR、证据和优化依赖的 `demo` extra。

### 2.2 非目标

- 不把 LLM 作为明确数值约束的唯一来源，也不让 LLM 直接生成最终 Requirement 对象；
- 不在 Web 层复制 Requirement、Envelope、检索、布局或评估算法；
- 不伪造用户未提供的参数值；
- 不把低阶开发评估器标记为正式 CFD/FEA/结构验证；
- 不改变 3.x 功能边界，不引入登录、远程求解器、CAD 驱动或公网部署。

## 3. 总体架构

```text
自然语言 / DOCX / PDF
        ↓
RequirementClauseSplitter
        ↓
现有 Requirement Semantics + Requirement Details
        ↓
现有需求审核 / MBSE Pipeline
        ↓
RequirementToEnvelopeService
        ↓
现有 Scheme Library + Scheme Retrieval
        ↓
现有 Layout Generation
        ↓
现有 Discipline Batch
        ↓
现有 Optimization（至少一轮新候选）
        ↓
ConceptWorkflowOrchestrator
        ↓
Web Demo Result View
```

编排器是应用层的唯一主链入口。它只协调已有服务，按照步骤写入可恢复的运行状态和中间结果；每一步有明确输入、输出、状态和诊断。结果保存采用现有工作区 JSON/SQLite 边界，不新增一套平行持久化体系。

## 4. 数据契约

### 4.1 需求子句

新增 `src/rflp_lite/application/requirement_clause_splitter.py`，定义不可变的应用层记录：

```python
@dataclass(frozen=True, slots=True)
class NormalizedMetric:
    name: str
    value: float
    unit: str
    operator: str       # <= | >= | < | > | ==
    source_text: str

@dataclass(frozen=True, slots=True)
class RequirementClause:
    id: str
    source_region_id: str
    ordinal: int
    text: str
    kind: str            # mission | metric | behavior | context
    normalized_metrics: tuple[NormalizedMetric, ...]
```

公开接口为：

```python
class RequirementClauseSplitter:
    def split(self, value: str | Sequence[DocumentRegion]) -> tuple[RequirementClause, ...]: ...
    def analyze(self, value: str | Sequence[DocumentRegion]) -> ClauseAnalysis: ...
```

规则约束如下：

- 先按中文/英文逗号、分号、句号和明确连接词切分；不丢失原始文本，不把“通信中断 30 秒后自动返航”拆成互不相关的两条；
- 先用规则抽取数值、单位、指标名和比较关系，再将每个子句构造成临时 `DocumentRegion`，调用现有 `extract_requirement_candidates()`；
- 运算符统一为 `<=`、`>=`、`<`、`>`、`==`。至少支持“不超过、不得大于、不高于、不低于、不少于、至少、以上、≤、≥”；
- 单位至少支持 `kg、m、km、km/h、s`。进入固定翼领域包时按参数声明转换为包内单位，例如 `km/h → m/s`；展示层可以转换回用户单位；
- 同一指标多个条件保留为多个 `NormalizedMetric`，不合并成一个丢失原文的字符串；
- `RequirementClause.id` 基于源区域、子句序号和规范化内容哈希生成；同一输入重复运行必须得到相同 ID 和顺序；
- 规则结果优先。可选 LLM 只补充任务类型、动作关系、领域语义或疑似行为约束，并标记为候选；不能覆盖规则抽出的数值、单位、比较符和来源；
- “设计一型中程侦察无人机”识别为任务/系统语义；数值子句形成显式 Requirement 详情；“通信中断 30 秒后自动返航”形成行为/故障恢复约束，并保留原文和时间阈值来源。

现有 `StructuredRequirement`、`RequirementAttribute`、`RequirementConstraint` 不删除、不改旧字段含义。新增规范化指标通过现有 `constraints`/详情持久化，同时在工作流运行结果中保留 `clause_analysis`，供 UI 展示和 Envelope 映射使用。

### 4.2 Requirement → Envelope

新增 `src/rflp_lite/application/requirement_to_envelope.py`，定义：

```python
@dataclass(frozen=True, slots=True)
class EnvelopeFieldProvenance:
    parameter: str
    source_kind: str                 # explicit | derived | suggested
    requirement_ids: tuple[str, ...]
    note: str

@dataclass(frozen=True, slots=True)
class RequirementEnvelopeResult:
    envelope: IndicatorEnvelope
    field_provenance: tuple[EnvelopeFieldProvenance, ...]
    diagnostics: tuple[str, ...]
```

公开接口为：

```python
def build_envelope_from_requirements(
    pack: Mapping[str, object],
    requirements: Sequence[Mapping[str, object]],
    *,
    attributes: Sequence[Mapping[str, object]] = (),
    constraints: Sequence[Mapping[str, object]] = (),
    history: Sequence[SchemeRecord | Mapping[str, object]] = (),
) -> RequirementEnvelopeResult: ...
```

映射优先级为：领域包显式映射 > 固定翼 Demo 映射 > 可安全推导 > 历史方案建议。固定翼首版的语义映射至少包括：

```text
最大起飞重量 → mass_kg.maximum（仅在 pack 明确声明该参数语义时启用）
翼展         → span_m.maximum
航程         → range_km.minimum（需要 pack 声明 range_km）
任务载荷     → payload_kg.minimum
巡航速度     → cruise_speed_mps.minimum（km/h 先转 m/s）
机翼面积     → wing_area_m2
机身长度     → fuselage_length_m
```

当前固定翼 v1 若没有 `range_km` 或 MTOW 专用参数，桥接层必须输出“领域包缺少目标参数”的诊断，不能把航程/MTOW 静默写入不相干字段。Demo pack 会在不破坏旧参数的前提下声明所需的语义映射或提供兼容别名。

字段处理规则：

- `explicit`：Requirement 已审核且明确提供指标；写入 Envelope bounds/value，并记录 Requirement ID；
- `derived`：只调用现有安全公式，所有输入必须来自 explicit/derived；记录公式和输入 Requirement ID；
- `suggested`：来自历史方案或领域包默认值；写入可用的 generation target，但不冒充用户约束；Web 以黄色标记；
- 未命中的参数不填值、不生成随机数字；若领域包要求参数才能生成候选，编排器在 Envelope 步骤停下并显示缺失参数；
- 最终 `IndicatorEnvelope.source_requirement_ids` 是所有字段来源 Requirement ID 的稳定去重序列；字段级 provenance 作为运行结果的增量数据保存。

桥接层最后调用现有 `create_indicator_envelope()`，复用单位转换、参数合法性、bounds 和 `input_hash` 校验。

### 4.3 历史方案规范化

新增 `scheme_import_mapper` 应用层适配，核心 `SchemeRecord` 不增加客户专用列。导入规则：

- 统一字段包括 `scheme_id、name、task_type、span_m、wing_area_m2、fuselage_length_m、mtow_kg、empty_mass_kg、payload_kg、range_km、cruise_speed_kmh`；
- 其中平台已有的固定翼计算参数映射到 `SchemeRecord.parameters`；名称、任务类型、原始 MTOW/航程等无法进入当前 pack 参数的字段保存在 `extensions`；
- 若源文件提供 `scheme_id`，导入器优先使用经校验的稳定值作为 `SchemeRecord.id`；缺少时才按 pack、来源、行号和内容生成确定性 ID；
- 缺失字段保持空/缺失，检索结果明确列出 `missing_features`，不使用默认值伪造历史数据；
- 导入脚本和 Web 初始化按钮调用同一个 mapper；导入前检查版本和现有 ID，已存在的同一数据只报告 skipped，不重复写入；
- 数据集至少包含 5 条固定翼历史方案，其中 1~2 条在重量/翼展/航程上明显被支配，确保 Pareto 结果具备演示可读性。

## 5. 后端主链设计

### 5.1 Workflow 状态

新增 `src/rflp_lite/application/intelligent_concept_workflow.py`。运行对象使用现有 canonical JSON/hash 方式持久化，步骤固定为：

```text
requirements_completed
mbse_completed
envelope_completed
retrieval_completed
generation_completed
evaluation_completed
optimization_completed
```

每一步记录：`key、status、started_at、completed_at、input_hash、result_ref、diagnostics`。状态只允许 `pending、running、completed、failed、skipped`。失败状态携带可读原因和已有中间结果；不能因 Pareto/第二代失败而删除 Requirement、MBSE、Envelope 或第一代候选。

### 5.2 编排接口

```python
@dataclass(frozen=True, slots=True)
class ConceptWorkflowRequest:
    workspace_name: str
    text: str = ""
    filename: str = "requirements.txt"
    document_bytes: bytes | None = None
    pack: Mapping[str, object] | str = "fixed-wing-v1"
    evaluator_profile: Mapping[str, object] | str = "development-v1"
    seed: int = 42
    demo_mode: bool = True

class ConceptWorkflowOrchestrator:
    def run(self, request: ConceptWorkflowRequest) -> ConceptWorkflowResult: ...
    def resume(self, run_id: str) -> ConceptWorkflowResult: ...
```

固定执行顺序：

1. 读取一句话或文档；文档解析复用现有 `analyze_artifact`，规则输入通过 `RequirementClauseSplitter`；
2. 保存需求候选，并在 Demo 模式对明确输入执行现有 quick-flow 审核规则；UI 仍展示来源和确认状态；
3. 调用现有 MBSE 生成服务，保存 Use Case / Activity / Sequence 中间结果；
4. 调用 Requirement→Envelope 桥；
5. 读取工作区方案库，调用现有相似检索，固定保存 Top 3 展示项，同时保留领域包声明的完整匹配集；
6. 调用现有布局生成器生成第一代 5 个候选；
7. 调用现有三学科批量评估器，保留每个 `Candidate × Discipline` 的状态、数值指标、证据状态和诊断；
8. 调用现有优化器至少一轮：选择 Pareto 前沿/排名靠前的 2~3 个 Parent，围绕 Parent 产生 2~3 个新候选，评估后重新计算 Pareto；
9. 保存推荐候选和推荐理由，等待用户执行“选择为概念设计推荐基线”。

编排器通过依赖注入接收现有 Requirement、MBSE、Scheme、Layout、Discipline 和 Repository 服务，避免复制算法。WebFacade 只负责构造请求、调用编排器、读取查询 DTO。

### 5.3 真实优化闭环

现有 `run_optimization()` 保留通用能力，但 Demo 模式的 evaluation budget 必须大于初始评估数量，且生成器必须使用 Parent 的参数作为扰动中心，而不是每轮重复同一批历史方案变体。至少满足：

```text
initial_candidates = 5
optimization iteration 1 generated = 2~3
iteration_records != ()
candidate source includes previous candidate IDs
final candidate set includes initial + optimized candidates
```

`OptimizationRun.iteration_records` 每条记录至少包含 `parent_ids、candidate_ids、front_ids、generation_index`。`concept_acceptance.py` 增加两道检查：存在至少一个 optimization iteration；至少一个新增候选的来源 Parent 属于前一轮候选。若评估器全部为 development-only，优化运行仍可完成，但 `formal_status` 仍为 `development_only`/`development`。

### 5.4 推荐基线操作

新增 `select_as_concept_baseline` 应用操作及 API/Web 入口。它写入 candidate review/audit 记录：

```text
decision = provisional_selected
candidate_id = Cxx
run_id = workflow run
selected_by / selected_at / rationale
```

该状态不改变候选的正式评估证据，不绕过 `formal_approved`。原有 accepted/rejected 行为继续保留，正式批准仍需要批准过的评估器档案。

## 6. Web 设计

### 6.1 入口

在工作区首页或需求入口增加明显的“智能生成概念方案”入口，表单只包含：

- 一句话描述文本框；
- DOCX/PDF 上传控件；
- 生成按钮；
- 可选 Demo 模式提示，不暴露 pack、evaluator profile 等内部参数。

提交后跳转到 workflow run 页面或概念结果页。现有 `/requirements/run-flow` 改为调用同一个主链服务或成为兼容重定向，不再保留没人能发现的独立能力。

### 6.2 进度状态

页面按以下 7 步显示 `pending/running/completed/failed`：

```text
①需求分析 → ②MBSE建模 → ③指标包络 → ④历史方案检索
→ ⑤候选生成 → ⑥多学科评估 → ⑦方案优选
```

失败步骤显示诊断和“已保留的中间结果”，支持从最近成功步骤恢复或返回需求审核。缺少 `run_id` 的 `/concept-design` 自动读取当前工作区最近一次 concept workflow run；没有运行时才显示空状态。

### 6.3 结果页

`concept-design.html` 重组为工程过程视图：

1. 需求理解：原始输入、Requirement、约束、来源区域、explicit/inferred 标记；
2. MBSE：Use Case、Activity、Sequence 的摘要/图形和追溯关系；
3. 历史方案检索：Top 3、相似度、方案名称、任务类型、主要特征差异和缺失特征；
4. 候选布局：横向显示 3~5 张 SVG，展示候选 ID、来源方案、约束余量和 `conceptual_2d_svg`；优化新增候选用“第二代”标签；
5. 多学科评估：显示重量/总质量、L/D、结构应力裕度、CG/CG fraction 等实际数值、单位、学科状态和证据状态；
6. Pareto：使用当前结果生成散点图/轻量 SVG，标记前沿与被支配候选；
7. 推荐：单独突出显示“推荐概念方案 Cxx”，列出推荐依据（约束通过、Pareto、学科指标、历史参考、优化来源）；提供“选择为概念设计推荐基线”按钮；
8. 边界声明：固定显示“当前多学科结果来自 development-only 快速评估器，仅用于概念方案筛选，不作为正式工程验证依据。”

页面继续支持原有候选 accepted/rejected 评审和导出。所有模板字段通过 presenter/DTO 准备，Jinja 不读取复杂领域对象内部结构。

## 7. 异常隔离与持久化

- 输入为空、文档格式不支持、文档/OCR 依赖缺失：在 `requirements` 步骤失败，保留原始输入和诊断；
- Requirement 数量为零或没有任何明确约束：流程可完成需求/MBSE 草稿，但 Envelope 步骤显示缺失指标并停止候选生成；
- 历史方案库为空：检索步骤完成但标记 `no_history`，生成器可在有足够 explicit 参数时继续；UI 显示“无历史参考”；
- 候选生成不足 3 个、约束全部失败：generation 失败，保留失败原因和尝试统计；
- 单个学科失败/超时/越出适用域：只隔离该 Candidate × Discipline，其他学科和候选继续；
- 第二轮优化失败：保留第一代候选、评估和 Pareto，workflow 标记 `optimization_failed`，不伪造“优化完成”；
- Repository 写入通过现有事务/CAS 边界完成；每个步骤先保存中间结果，再更新状态；页面读取最近成功的状态快照。

## 8. 测试与验收

### 8.1 单元测试

- 子句切分：混合中文连接词、比较词、数值、单位、行为条件；重复运行 ID 和结果稳定；
- 详情抽取：五个关键数值约束全部得到正确 operator/value/unit；行为约束不误写进 Envelope；
- Envelope：explicit/derived/suggested 三类来源、单位转换、缺失参数诊断、source requirement IDs；
- Scheme mapper：字段映射、缺失字段、显式 scheme_id、重复导入幂等；
- Optimization：Parent 来源、非空 iteration record、第二代候选、重新计算 Pareto；
- Concept acceptance：缺少 optimization iteration 或没有上一轮来源时失败；
- 推荐基线：`provisional_selected` 不改变 formal approval 状态。

### 8.2 Web/API 测试

- 首页入口提交一句话和上传 DOCX/PDF；
- `/concept-design` 无 `run_id` 时读取最新 workflow run；
- 进度页面能展示成功、失败和中间结果；
- 结果页出现 Top 3、SVG 候选、数值评估、Pareto、推荐理由和 development-only 声明；
- 选择概念基线后可在页面和审计记录看到 `provisional_selected`；
- 旧的 concept run API、candidate review API 和 requirements 页面兼容。

### 8.3 端到端验收

测试以临时工作区和确定性依赖运行，执行：

```text
创建 Demo Workspace
→ 初始化历史方案库（重复初始化不重复写入）
→ 输入一句话
→ 得到至少 5 个 Requirement/Constraint
→ 生成 MBSE
→ 自动形成 Envelope
→ 检索 Top 3
→ 生成 5 个初始候选
→ 完成三学科评估
→ 至少一轮优化并新增 2~3 个候选
→ 重新计算 Pareto
→ 得到推荐方案
→ 选择 provisional_selected 概念基线
```

固定使用 `RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config`，避免本机 LLM 配置影响。验收还要验证同一个输入和 seed 的 workflow/result hash 稳定，以及任意中间步骤失败不会清空此前结果。

### 8.4 安装收口

在 `pyproject.toml` 增加：

```toml
demo = [
  "pytest>=8.3",
  "hypothesis>=6.112",
  "jsonschema>=4.23",
  "prance>=23.6.21",
  "junitparser>=3.2",
  "ortools>=9.11",
  "pdfplumber>=0.11,<1",
  "pypdfium2>=4.30,<5",
  "Pillow>=11,<13",
  "rapidocr>=3.6,<4",
  "onnxruntime>=1.22,<2",
  "fastapi>=0.116,<1",
  "uvicorn>=0.35,<1",
  "jinja2>=3.1,<4",
  "python-multipart>=0.0.20,<1",
  "httpx>=0.28,<1",
  "keyring>=25",
]
```

`README.md` 改为推荐 `pip install -e '.[demo]'` 和一键演示命令；保留细分 extras 供开发者使用。新增安装 smoke test，确保 `demo` 环境可导入 Web、PDF/OCR、evidence、OR-Tools 和概念流程模块。

## 9. 预期文件边界

### 新建

- `src/rflp_lite/application/requirement_clause_splitter.py`
- `src/rflp_lite/application/requirement_to_envelope.py`
- `src/rflp_lite/application/intelligent_concept_workflow.py`
- `src/rflp_lite/application/scheme_import_mapper.py`
- `src/rflp_lite/resources/examples/concept-design/demo-schemes.json`
- `scripts/seed_demo_schemes.py`
- `tests/application/test_requirement_clause_splitter.py`
- `tests/application/test_requirement_to_envelope.py`
- `tests/application/test_scheme_import_mapper.py`
- `tests/application/test_intelligent_concept_workflow.py`
- `tests/e2e/test_concept_workflow_demo.py`

### 重点修改

- `src/rflp_lite/application/requirement_semantics.py`
- `src/rflp_lite/application/requirement_details.py`
- `src/rflp_lite/application/parameter_rules.py`
- `src/rflp_lite/application/concept_design_service.py`
- `src/rflp_lite/application/multidisciplinary_optimization.py`
- `src/rflp_lite/application/concept_acceptance.py`
- `src/rflp_lite/application/web_facade.py`
- `src/rflp_lite/application/requirements_flow.py`
- `src/rflp_lite/interface/web/routes.py`
- `src/rflp_lite/interface/web/api_v1.py`
- `src/rflp_lite/interface/web/templates/requirements-input.html`
- `src/rflp_lite/interface/web/templates/concept-design.html`
- `src/rflp_lite/interface/web/templates/dashboard.html`
- `src/rflp_lite/interface/web/static/app.css`
- `src/rflp_lite/adapters/sqlite_repository.py`（仅在现有 concept/run 结构确实不足时增量扩展）
- `pyproject.toml`
- `README.md`

### 不纳入提交

根目录已有的未跟踪参考 PPT/PDF/DOCX、`release/` 交付目录和虚拟环境保持原样，不加入本次代码或文档提交。

## 10. 验收结果定义

交付完成必须同时满足：

- 一句话连续运行的结构化需求结果稳定，关键五个数值约束全部正确；
- Envelope 有 `source_requirement_ids` 和字段级来源状态；
- Demo 历史方案可初始化、可筛选、不可重复写入；
- 主链从需求到推荐可一次运行，失败停在正确步骤并保留中间结果；
- 初始候选 5 个、优化新增至少 2 个、`iteration_records` 非空、最终 Pareto 可解释；
- 结果页不以内部 JSON 作为主要内容，显示真实数值和固定边界声明；
- 推荐基线状态为 `provisional_selected`，不伪装成 `formal_approved`；
- `demo` extra 可安装，端到端测试稳定通过；
- 1.1、1.2、2.1、2.2 既有测试保持通过，3.x 仍明确未实施。
