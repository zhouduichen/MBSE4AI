# AI4MBSE Harness

AI4MBSE Harness 产品版本为 `0.2.0`，方法论协议版本为 `v2.1`。它是一个本地优先、可复现、可审计的 MBSE 模型生成工作台。默认产品链路是：

```text
自然语言 / 文档 → Requirements → Functional → Logical → Physical → V&V
               → Typed ModelGraph → SysML v2 subset / 可编辑模型
```

ModelGraph 是模型唯一真源。产品主入口按五个纵向阶段调用 Runtime，把 Requirements、Functional、Logical、Physical 和 V&V 逐步写入同一张可编辑图；每个阶段内部复用版本化的方法论任务、结构化输出、Patch、Validator 和 CAS。23-task 生命周期作为显式 `analyze run` / `mode=pipeline` 兼容与研究入口保留。两条入口都显式生成 System、Stakeholder、Lifecycle stage/transition、Scenario、Concern、State、Hazard 和 FailureMode，不把它们藏在阶段 payload 中。SQLite 保存项目、文档区域、证据、运行、步骤、Patch、Revision 和 Issue。

五阶段生成入口在写入 ModelGraph 后，会通过 Methodology Engine 和 Systems Engineering Controller 统一投影 Traceability、工程 findings/metrics 和下一步动作；显式 `mode=pipeline` 的旧 23-task 入口则通过只读 Pipeline Report 获得同样的工程投影。`POST /projects/{id}/analysis` 未指定模式时、以及 Analysis 工作台主按钮，默认进入五阶段生成；所有结果和工程交付包都绑定同一 revision/snapshot hash。完整交付包还包含 `behavior.json`，固化 Use Case、Operational Scenario、Activity、Sequence Diagram Framework 和可编辑实体 ID。报告计算不创建 Run/Patch、不改变模型，也不额外调用 LLM。这样产品交付关注的是一份可继续编辑、可追溯并可导出 SysML 的完整工程结果，而不是只返回任务执行台账。

## 安装

需要 Python 3.11+：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,web,documents]'
```

配置并使用 LLM Profile 时，`analyze generate` 会由结构化 LLM 驱动五阶段模型生成；没有可用模型时仍可完整运行离线规则 Runtime。配置由 `model-profile` 管理，单次生成可用 `--profile` 选择档案而不改变全局 active profile。

## 最短路径

从自然语言生成完整模型：

```bash
.venv/bin/ai4mbse --workspace-root .local-workspaces project create campus-demo
.venv/bin/ai4mbse --workspace-root .local-workspaces analyze generate campus-demo \
  --text "系统应在校园内完成配送，并允许运营人员人工接管"
.venv/bin/ai4mbse --workspace-root .local-workspaces model export campus-demo --format sysml > campus-demo.sysml
```

使用已保存的远程 SSH/Tailscale LLM Profile 做本次真实 LLM 生成（不会启动本机模型，也不会切换 active profile）：

```bash
.venv/bin/ai4mbse --workspace-root .local-workspaces analyze generate campus-demo \
  --profile <remote-profile-id> \
  --text "系统应在校园内完成配送，并允许运营人员人工接管"
```

Jiayu-intern 的 SSH 转发、Profile JSON 和一次性 CASE-04 验收命令见
[远程 LLM 测试手册](docs/REMOTE_LLM_TESTING.md)。

也可以先输入项目目标；目标会进入 System 的 mission/objectives，并生成一条可继续追溯的候选需求：

```bash
.venv/bin/ai4mbse --workspace-root .local-workspaces project goal campus-demo \
  "建设一个可在校园内安全完成配送并支持人工接管的系统"
.venv/bin/ai4mbse --workspace-root .local-workspaces analyze generate campus-demo
```

运行完整的 23-task 生命周期：

```bash
.venv/bin/ai4mbse --workspace-root .local-workspaces project create pipeline-demo
.venv/bin/ai4mbse --workspace-root .local-workspaces analyze run pipeline-demo \
  --text "系统应在校园内完成配送，并允许运营人员人工接管"
```

也可以从已解析的需求文档生成：

```bash
.venv/bin/ai4mbse --workspace-root .local-workspaces project create document-demo
.venv/bin/ai4mbse --workspace-root .local-workspaces project ingest document-demo requirements.txt
.venv/bin/ai4mbse --workspace-root .local-workspaces analyze run document-demo
```

导入文档后，`analyze run` 会自动执行 Intake 并直接进入 23-task 生命周期，不需要手动调用需求草稿 API；Web 端可用 `{"mode":"pipeline","document_ids":[...]}` 获得相同路径。

`analyze generate`、`analyze run` 和 Web `/analysis` 现在共享同一个结构化需求/用例摄取边界：文本或已上传的 TXT、Markdown、DOCX、PDF 先生成带来源、约束来源、置信度和澄清问题的 `IntakeDraft`，经现有 CAS 写入候选 ModelGraph 后再继续五阶段或 23-task R→F→L→P→V&V。离线模式明确标记为 `degraded`/`RULE`，不会伪装成 LLM 结果；除显式数值约束外，有限语义规则会生成低置信度 `derived` 隐含约束，保留假设并显示“需人工确认”，不会自动批准。之后同一请求会产出 Use Case、Operational Scenario、Activity、完整追溯、SysML 和交付包。需求分析工作台 `/ui/projects/<project-id>/requirements-use-case` 仍保留为需要人工逐稿审查时的独立 M1/M2 入口。

行为工作台 `/ui/projects/<project-id>/behavior` 会从已写入的 Operational Scenario/Activity 确定性投影 Sequence Diagram Framework：参与者、消息顺序、守卫、分支、Mermaid 文本和可编辑实体 ID 均来自同一份 ModelGraph；通过工作台编辑源实体后重新读取即可刷新，不额外调用 LLM。

总体设计页的“从 ModelGraph 提取指标”会调用 `/projects/<project-id>/concept-design/input`，把需求中的显式质量、尺寸、速度等约束回填到可编辑指标包络，并明确显示缺失必填参数；生成后页面按候选展示气动、结构、重量/重心评估指标、状态、适用域/批准诊断、候选完成度、Pareto 候选和优化停止原因。`concept-design.json` 同步保存每条评估的输入参数、有效域状态、验证数据集、误差/批准信息和候选级优化反馈。

详细设计开发切片位于 `/ui/projects/<project-id>/cad-design`：输入“生成铝合金支架，长100毫米，宽50毫米，高10毫米”这类意图后，系统会给出澄清问题（若信息不完整）和带稳定 ID 的结构选型推荐，用户可选择或保留未选择状态；对于支架/底座，加筋板式选择会编译为两条 `add_rib` 参数化加强筋，整体块式选择会编译为 `add_fillet` 圆角操作，随后生成可审查的 CAD 操作计划，并严格按“预览 → 审批 → 执行”创建参数化工件。默认是离线 preview；显式设置 `AI4MBSE_CAD_BACKEND=freecad-remote` 后，操作计划会通过 SSH 在远程 FreeCAD headless 中生成真实 `.FCStd`/`.step`，重新读取校验实体、回传到项目 `.rflp/cad_artifacts`，并可通过页面下载。执行结果可回写为 `PhysicalBlock` 并与来源 Requirement 建立 `satisfiedBy` 关系；随后可生成共享 2D/3D 语义标注、基准 A、基础 GD&T 建议、厂商无关的二维图纸 SVG 预览、风险高亮 SVG 和带特征位置证据的 DFM/DFA finding。二维图纸预览与标注共享同一语义对象和哈希，并明确标记为 development evidence；结构选型、用户选择、实际 CAD 操作和已有审查结果会一并回接 PhysicalBlock，并随 SysML v2 子集往返和完整交付包输出。推荐不会自动变成批准事实，CAD 意图仍遵循“未显式选择远程 Profile 时不调用本机模型”的约束。

当总体布局或 CAD 意图没有显式传入来源需求时，系统会从当前 ModelGraph 选择未拒绝的根 Requirement 自动建立来源范围；显式选择仍优先。这样需求分析后的概念候选和详细设计 PhysicalBlock 不再依赖手工复制需求 ID，且保留完整 R→设计对象的追溯关系。

已有 SysML v2 子集模型也可以在 Web Analysis 页面上传，导入同一份 Typed ModelGraph；导入后可以继续生成下游层、Review、编辑并导出完整工程交付包。

Golden fixture 也可以作为完整 23-task 生命周期的离线回归输入：

```bash
.venv/bin/ai4mbse --workspace-root .local-workspaces project create campus-demo
.venv/bin/ai4mbse --workspace-root .local-workspaces project ingest campus-demo tests/e2e/fixtures/campus_delivery_robot.json
.venv/bin/ai4mbse --workspace-root .local-workspaces analyze run campus-demo
# 调试单阶段时再指定 --phase operational|functional|logical_physical|assurance
.venv/bin/ai4mbse --workspace-root .local-workspaces model export campus-demo --format json
```

CLI 的主要命令：

```text
project create|ingest|goal
analyze generate|run|status（generate 支持 `--profile`）
model export|import-sysml
vv record|tool
issue list
repair run
model-profile list|save|activate
```

## Web

```bash
.venv/bin/uvicorn rflp_lite.interface.web.app:create_app --factory --host 127.0.0.1 --port 8000
```

完整生成按钮通过 `POST /projects/{id}/analysis/runs` 立即创建后台 Run 并返回 `202`，前端轮询 `GET /projects/{id}/runs/{run_id}` 展示需求、功能、逻辑、物理、验证与确认五个阶段的进度；单阶段调试和 23-task pipeline 入口保持兼容。

页面收敛为 Projects、Analysis、MBSE Model、Evidence & Issues、Settings；API 资源以 `/projects` 为根，提供项目、分析运行、模型、实体 CAS 编辑、证据、已登记工程工具、V&V 执行结果、Issue、Repair 和 Export。Assurance 页面可以直接为 VerificationCase/ValidationCase 记录真实执行结果；结果进入 Evidence 表，并同步物化为 ModelGraph 的 `Evidence` 节点和 Case→Evidence `describedBy` 关系，失败结果生成 Issue 并给出下游迭代动作。工程工具适配器通过注册表接入，工具只能返回明确的 V&V outcome 和证据，再由统一服务写入 ModelGraph；内置 `model.constraint_check` 只分析已传播约束，缺少测量字段时返回 `inconclusive`。MBSE Model 页面按 System Definition、Functional、Logical、Physical、V&V 展示真实 ModelGraph 实体，并支持实体编辑、Review、锁定、查看 revision-bound 影响分析和重新分析。

Analysis 页面可以直接保存“系统目标 / 项目使命”；目标同时作为 System intent 和候选 Requirement 进入后续 R→F→L→P→V&V。Controller 的历史项目检索只读其他 managed project 的模型、文档区域和证据 FTS，命中结果以 `historical_project` Evidence 回写当前项目，不跨项目修改模型。Assurance 工作台首屏先返回确定性下一步动作；需要 LLM Controller 建议时再按需请求 `/projects/{id}/controller?include_llm=true`，远程 SSH/Tailscale 节点不可达不会阻塞页面，也不会回退到本机模型。

Analysis 页面支持上传已有 `.sysml` 模型。导入使用与命令行相同的确定性 SysML v2 子集解析器，写入当前项目的 ModelGraph，并在实体 ID 冲突时拒绝整次导入；任何包含活动实体的已有模型（包括只有部分层的模型）都可以作为分析输入，继续生成、编辑和导出。如果部分模型只有 Activity、Operational Scenario 或 System 等运行上下文而尚无 Requirement，Requirements 阶段会从这些类型化字段派生一个可 Review 的系统 Requirement，并用 `derivedFrom` 保留来源 ID，再继续贯通 F/L/P/V&V。缺失层和追溯缺口会保留为 warnings/review findings。Analysis 页面还可以为本次分析选择已保存的 LLM Profile；选择只作用于当前请求，不切换 active Profile，页面不显示凭据。

MBSE Model 页面还提供“导出完整交付包”：同一份 ModelGraph 快照一次性输出 `model.json`、`evidence.json`、SysML v2 子集、RFLP JSON 与 `rflp.svg`、Requirements、Traceability、V&V Plan 和 Architecture Report，并在 manifest 中绑定项目、revision 和 snapshot hash。若项目已经完成概念设计或详细设计，交付包会额外包含审计记录投影的 `concept-design.json` 与 `detail-design.json`，保留候选布局、学科评估、优化运行、CAD 参数化模型、标注和 DFM/DFA Review。`evidence.json` 固化项目级证据正文及独立 evidence hash；被实体、关系或 V&V payload 引用的已有证据会在模型补丁提交时以稳定 ID 物化为 ModelGraph 的 `Evidence` 节点，未绑定的检索结果仍只保留在外部证据库。导出本身不会隐式创建 ModelGraph revision。SysML 子集把实体的 kind、name、status、来源、修订和 payload 写入实际声明属性，同时保留稳定 ID/关系元数据；外部编辑声明属性后重新导入会回写同一 ModelGraph。交付包可以重新读取 SysML 后继续编辑；报告中的缺口仍保留为 BLOCKED/INCOMPLETE，不会被下载过程隐藏。

未配置模型时页面会明确显示 `Offline Rule Mode`；配置并激活 Profile 后，每次新分析都会记录实际使用的 profile/provider/model。Analysis 页面也支持请求级选择 Profile，优先级为请求选择、显式 Runtime、active Profile、离线规则；服务默认只监听 `127.0.0.1`，适用于单用户本地工作区。

当前产品验收重点是一次真实的纵向链：`自然语言/文档 → R → F → L → P → V&V → ModelGraph → SysML`。`analyze generate` 和 Web/API 未指定模式的主入口执行五阶段产品链；`analyze run` / `mode=pipeline` 保留完整 23-task 方法论生命周期，两个入口都消费同一份输入并写入同一份 Typed ModelGraph。自然语言句子、列表项和文档中的独立条目保持为独立 Requirement，分别进入下游追溯；输入中的显式功耗、质量、时延、带宽、成本和续航边界会被规范化为 canonical constraints，并保留 `constraint_provenance`，再随 R→F→L→P 传播。对明确存在的 `max_*`/`min_*` 工程约束，P 层还会创建 `level=technical` 的 Technical Requirement，通过 `derivedFrom` 回接来源需求、通过 `satisfiedBy` 连接物理候选，并由 V&V 单独覆盖；没有明确约束的普通需求不会被额外拆分。追溯结果分开显示 RFLP、Verification、Validation 和端到端闭环，只有两类 V&V 都存在才算端到端完成。阶段完成还会逐条检查每个活动 Requirement 在 F/L/P/V&V 的覆盖情况，输出缺失的 canonical Requirement ID；结构化反馈轮只针对这些精确缺口补全，并复用已有 ID，避免用总体实体数量掩盖单条需求断链。未配置模型时使用离线规则 Runtime 验证产品闭环；配置并激活 OpenAI-compatible Profile 后，主入口会通过 StructuredModelRuntime 逐阶段调用结构化 LLM，并记录 profile/provider/model、Prompt、上下文、Patch 和追溯摘要；默认保持五个阶段串行，同一阶段内独立 Requirement batches 可按配置并行，远程 Profile 默认只做一次 LLM Proposal pass 加 typed completion bridge，反馈回合可显式开启。未闭合的阶段仍显示为 `needs_review`，离线规则路径不增加重复调用。上传文档解析出的每个 Source Region 会登记为 `document_region` Evidence，文档 Requirement 同时保存对应 `source_ids` 和 `evidence_ids`，模型补丁提交后证据节点会进入同一份 ModelGraph 并随交付包输出。语义校验失败的 LLM 输出只保存为 candidate 并进入 review，不计入完成度。离线 fallback 的 F/L/P 也消费图中的功能职责、分区键、共享状态和 Requirement 关系；未知 SWaP-C/续航仍保持 `needs_measurement`，不会伪造可行性。历史 Ollama conformance artifact 仍只代表结构化边界，不等同于真实 Provider 的 23-task 稳定性。

配置远程 Runtime 时，23-task `analyze run` / `mode=pipeline` 会在依赖安全的同阶段任务组内并行请求；`max_parallel_requests` 统一限制任务级和 Requirement batch 级并发（1–4，远程 Profile 默认 2），各组仍按 Operational→Functional→Logical/Physical→Assurance 顺序推进，结果按固定顺序合并并经过既有 Validator/CAS。Runtime 未声明并行能力或使用离线规则时保持串行。系统级需求的质量、功耗、内存、带宽、成本和续航预算会在完整 R→F→L→P 作用域内做确定性汇总，合计超限与测量缺口分别进入 Methodology、Controller、V&V 工具和架构交付物；技术需求默认保持单 PhysicalBlock 检查，只有显式 `constraint_scope=system` 才参与系统预算分析。

每次 `POST /projects/{id}/analysis` 成功返回的 `run` 还会携带一个轻量 `deliverable` 清单：它与本次运行的 `revision`、`snapshot_hash` 一致，并提供结构化交付包与 ZIP 下载入口；完整模型内容只通过交付包接口读取，避免在运行响应中重复传输。未填写远程 Profile 的预算时，Harness 默认使用 8192 token 上下文窗口和 4096 token 结构化输出预算；显式配置仍优先。

五阶段 `generate` 结果和显式 Pipeline `run` 都携带 `traceability`、`methodology`、`controller` 以及与交付物绑定的 revision/hash。Analysis 页面主结果呈现五阶段纵向链、RFLP/V&V 闭环、逻辑架构候选、物理可行性矩阵、工程问题和下一步动作；`mode=pipeline` 仍提供完整 23-task 生命周期兼容结果。

纵向链完成后由 Methodology Engine 对 ModelGraph 做确定性工程分析：逻辑层报告分配覆盖、State 模型、分区和内聚/耦合信号；物理层传播约束并区分冲突与待测量；V&V 分开报告 Verification、Validation、Hazard/FailureMode 覆盖、计划字段完整度和执行证据。现在 Methodology 还会基于功能流、共享状态、显式依赖和当前分配，生成可比较的 Logical 架构候选，给出分区、跨组件交互、耦合/内聚和评分；同时输出每个 Physical candidate 的约束传播、冲突、缺失测量字段和可行性评分。五阶段入口和完整 23-task Runtime 都把这套结果作为 `architecture_reasoning` / `feasibility_reasoning` 写入 ModelGraph，后续 Controller、Workbench、SysML 往返和交付包读取同一份事实。默认 fallback 的 Function 会保留输入需求驱动的 decomposition，Physical candidate 会保留结构化 trade study 与选择依据。每个生成任务都会收到有界的 `methodology_guidance`，把当前阶段的确定性 findings、关键指标、架构候选和推荐任务交给 LLM 作为下一步工程推理输入，而不是只在生成结束后验收。计划字段和 evidence 始终分层，空 evidence 不会伪装成已执行。Systems Engineering Controller 将这些 findings 汇总为下一步动作：证据缺口先通过 Tool Layer 检索文档、历史项目和本地 FTS，检索到的证据落库后触发受影响阶段重分析；仍无结果时暂停等待用户。逻辑分区或物理约束需要权衡时展示候选方案，用户选择后触发受影响阶段的定向重分析；V&V 失败会沿 R→F→L→P 返回影响实体和 impact paths，并在 Assurance 页面给出功能重构、架构替换、需求调整或修订验证条件等 Trade Study 选项，不自动盲目重跑；其中 `dependency_cluster_search` 也会由离线 Runtime 实际应用为版本化逻辑架构。Review 和 Controller 都沿图返回影响实体、阶段、路径和审计记录，不绕过 CAS，也不替用户无审查地作工程决策。

Trade Study 的用户选择现在会真正改变架构图：Logical 选择可生成“每功能一个组件”或“共享协调器”变体，保留旧组件并对未锁定旧组件做版本化弃用；Physical 选择“更换物理候选或计算架构”会新增可比较的替代候选。每个变体都保留 `architecture_decision` 来源，锁定或用户修改的实体不会被覆盖；替代候选不填充虚假的 SWaP-C 测量，原有约束、冲突和待验证问题继续可见。

在实体 Review 后，用户可以先创建影响分析请求，也可以执行定向重新分析：编辑 Requirement 会从 Requirements 向下重跑，编辑 Function 从 Functional 向下重跑，Logical/Physical/V&V 编辑只重跑受影响的后续阶段。重分析沿现有 trace 复用未被人工修改或锁定的派生对象，用 `updates` 保持 canonical ID 并刷新下游语义；人工修改或锁定对象作为只读锚点保留，必要时产生待评审差异。确认实体后还可以显式执行“继续生成下游”，从已确认层的下一个阶段运行到 V&V；锁定实体作为只读锚点参与推理，不会被修改。完整交互闭环是：`Review 实体 → 接受/锁定 → 继续生成下游 → 重新计算 Trace/Methodology → Review 新结果`。每次重分析或继续生成仍写入独立 Run、Patch、Revision 和 audit，不覆盖锁定实体。

Controller 还提供有界的“自动推进安全动作”入口：它可以连续执行安全的局部重分析或证据检索，并在每轮重新计算 Traceability、Methodology 和下一步动作；遇到 Trade Study、缺少用户输入/证据、无进展或迭代预算耗尽时暂停。Trade Study 方案仍必须由用户明确选择，LLM 生成内容继续经过结构化 Runtime、Compiler、Validator 和 CAS。

对完整 fixture 的 23-task 兼容链，后置功能/技术/反向需求会回接已有 Function 与 V&V 案例，最终交付包以 7/7 需求形成完整 R→F→L→P→V&V 追溯作为验收证据。

每次编辑都会生成绑定当前 revision/snapshot hash 的 Typed Impact Plan，明确 R→F→L→P→V&V 影响实体、关系路径、V&V 案例和推荐任务；`GET /projects/{id}/entities/{entity_id}/impact` 与编辑响应会把这份计划和 Controller 下一动作交给工作台，定向重分析还返回 before/after Traceability。

## 开发与验收

本地产品纵向验收只使用离线规则 Runtime，不启动服务器、不连接 SSH，也不调用本机或远程模型：

```bash
./.venv/bin/python -m pytest -q tests/e2e/test_local_product_acceptance.py
```

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview ./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/lint-imports
```

设计说明、施工计划和当前状态：

- [当前架构](docs/CURRENT_ARCHITECTURE.md)
- [开发状态](docs/DEVELOPMENT_STATUS.md)
- [v2.0 设计规格](docs/superpowers/specs/2026-09-07-ai4mbse-harness-v2-design.md)
- [v2.0 实施计划](docs/superpowers/plans/2026-09-07-ai4mbse-harness-v2-implementation.md)
- [施工要求索引](docs/superpowers/README.md)

## 远程 GPU LLM 当前行为

远程 Profile 的普通 F/L/P 反馈回合默认关闭，但 Requirements 会按当前方法论缺口自动执行最多 4 轮有界补全；V&V 会为每条 Requirement 分别生成一个 VerificationCase 和一个 ValidationCase，并强制保留 canonical `requirement_ids` 以闭合 R→F→L→P→V&V 追溯。单需求 Case 请求可按 `max_parallel_requests` 并行。typed completion bridge 仍需显式开启，远程模型的实质建模不会被离线规则静默替代。

## 边界

Core 已包含当前版的 M3/M4 概念布局切片和 M5 详细设计开发切片：总体设计页面和 `/projects/{id}/concept-design/run` 可基于固定翼领域包检索历史方案、生成 3–5 套可行概念布局、输出确定性二维 SVG，并并行执行气动/结构/重量重心开发评估及帕累托反馈；每条评估现在保留可复核的输入、适用域、验证数据集和批准诊断，候选级摘要记录失败隔离与优化反馈。详细设计页面提供自然语言 CAD 意图、操作计划、远程 FreeCAD 实体生成、共享 2D/3D 标注、厂商无关二维图纸 SVG 预览和 DFM/DFA 审查；默认 preview 的图纸与规则结果均是 development evidence，FreeCAD 后端只在显式配置后连接远程服务器，正式制造结论仍需客户批准的标准、规则库和验证适配器。旧版智能发现、Project Bridge、测试执行沙箱、旧 Baseline/TaskContract/Job 体系或 MLflow 适配器仍不作为隐式依赖存在。
