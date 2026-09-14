# AI4MBSE Harness

AI4MBSE Harness 产品版本为 `0.2.0`，方法论协议版本为 `v2.1`。它是一个本地优先、可复现、可审计的 MBSE 模型生成工作台。默认产品链路是：

```text
自然语言 / 文档 → Requirements → Functional → Logical → Physical → V&V
               → Typed ModelGraph → SysML v2 subset / 可编辑模型
```

ModelGraph 是模型唯一真源。默认纵向生成器按五个阶段调用结构化 Runtime，将每一阶段的局部 Patch 写入图并保留完整追溯链；显式的 `analyze run` 入口则按 23 个方法论任务逐任务执行同一份 ModelGraph，形成可审查的 R→F→L→P→V&V 生命周期。两条入口都显式生成 System、Stakeholder、Lifecycle stage/transition、Scenario、Concern、State、Hazard 和 FailureMode，不把它们藏在阶段 payload 中。SQLite 保存项目、文档区域、证据、运行、步骤、Patch、Revision 和 Issue。

## 安装

需要 Python 3.11+：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,web,documents]'
```

不安装远程模型也可以完整运行离线规则 Runtime。OpenAI-compatible 模型是可选的，配置由 `model-profile` 管理。

## 最短路径

从自然语言生成完整模型：

```bash
.venv/bin/ai4mbse --workspace-root .local-workspaces project create campus-demo
.venv/bin/ai4mbse --workspace-root .local-workspaces analyze generate campus-demo \
  --text "系统应在校园内完成配送，并允许运营人员人工接管"
.venv/bin/ai4mbse --workspace-root .local-workspaces model export campus-demo --format sysml > campus-demo.sysml
```

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
.venv/bin/ai4mbse --workspace-root .local-workspaces analyze generate document-demo
```

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
analyze generate|run|status
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

页面收敛为 Projects、Analysis、MBSE Model、Evidence & Issues、Settings；API 资源以 `/projects` 为根，提供项目、分析运行、模型、实体 CAS 编辑、证据、已登记工程工具、V&V 执行结果、Issue、Repair 和 Export。Assurance 页面可以直接为 VerificationCase/ValidationCase 记录真实执行结果；结果进入 Evidence 表，并同步物化为 ModelGraph 的 `Evidence` 节点和 Case→Evidence `describedBy` 关系，失败结果生成 Issue 并给出下游迭代动作。工程工具适配器通过注册表接入，工具只能返回明确的 V&V outcome 和证据，再由统一服务写入 ModelGraph；内置 `model.constraint_check` 只分析已传播约束，缺少测量字段时返回 `inconclusive`。MBSE Model 页面按 System Definition、Functional、Logical、Physical、V&V 展示真实 ModelGraph 实体，并支持实体编辑、Review、锁定和重新分析。

Analysis 页面可以直接保存“系统目标 / 项目使命”；目标同时作为 System intent 和候选 Requirement 进入后续 R→F→L→P→V&V。Controller 的历史项目检索只读其他 managed project 的模型、文档区域和证据 FTS，命中结果以 `historical_project` Evidence 回写当前项目，不跨项目修改模型。

Analysis 页面支持上传已有 `.sysml` 模型。导入使用与命令行相同的确定性 SysML v2 子集解析器，写入当前项目的 ModelGraph，并在实体 ID 冲突时拒绝整次导入；任何包含活动实体的已有模型（包括只有部分层的模型）都可以作为分析输入，继续生成、编辑和导出。如果部分模型只有 Activity、Operational Scenario 或 System 等运行上下文而尚无 Requirement，Requirements 阶段会从这些类型化字段派生一个可 Review 的系统 Requirement，并用 `derivedFrom` 保留来源 ID，再继续贯通 F/L/P/V&V。缺失层和追溯缺口会保留为 warnings/review findings。

MBSE Model 页面还提供“导出完整交付包”：同一份 ModelGraph 快照一次性输出 `model.json`、`evidence.json`、SysML v2 子集、RFLP JSON 与 `rflp.svg`、Requirements、Traceability、V&V Plan 和 Architecture Report，并在 manifest 中绑定项目、revision 和 snapshot hash。`evidence.json` 固化项目级证据正文及独立 evidence hash；被实体、关系或 V&V payload 引用的已有证据会在模型补丁提交时以稳定 ID 物化为 ModelGraph 的 `Evidence` 节点，未绑定的检索结果仍只保留在外部证据库。导出本身不会隐式创建 ModelGraph revision。SysML 子集把实体的 kind、name、status、来源、修订和 payload 写入实际声明属性，同时保留稳定 ID/关系元数据；外部编辑声明属性后重新导入会回写同一 ModelGraph。交付包可以重新读取 SysML 后继续编辑；报告中的缺口仍保留为 BLOCKED/INCOMPLETE，不会被下载过程隐藏。

未配置模型时页面会明确显示 `Offline Rule Mode`；配置并激活 Profile 后，每次新分析都会记录实际使用的 profile/provider/model。服务默认只监听 `127.0.0.1`，适用于单用户本地工作区。

当前产品验收重点是一次真实的纵向链：`自然语言/文档 → R → F → L → P → V&V → ModelGraph → SysML`。`analyze generate` 是面向用户的五阶段快速入口；`analyze run` 是完整的 23-task 方法论入口，两个入口都消费同一份输入并写入同一份 Typed ModelGraph。自然语言句子、列表项和文档中的独立条目保持为独立 Requirement，分别进入下游追溯；输入中的显式功耗、质量、时延、带宽、成本和续航边界会被规范化为 canonical constraints，并保留 `constraint_provenance`，再随 R→F→L→P 传播。对明确存在的 `max_*`/`min_*` 工程约束，P 层还会创建 `level=technical` 的 Technical Requirement，通过 `derivedFrom` 回接来源需求、通过 `satisfiedBy` 连接物理候选，并由 V&V 单独覆盖；没有明确约束的普通需求不会被额外拆分。追溯结果分开显示 RFLP、Verification、Validation 和端到端闭环，只有两类 V&V 都存在才算端到端完成。阶段完成还会逐条检查每个活动 Requirement 在 F/L/P/V&V 的覆盖情况，输出缺失的 canonical Requirement ID；结构化反馈轮只针对这些精确缺口补全，并复用已有 ID，避免用总体实体数量掩盖单条需求断链。未配置模型时使用离线规则 Runtime 验证产品闭环；配置并激活 OpenAI-compatible Profile 后，`analyze generate` 和 `analyze run` 都会通过 StructuredModelRuntime 逐阶段/逐任务调用结构化 LLM，并记录 profile/provider/model、Prompt、上下文、Patch 和追溯摘要；如果当前阶段检查出缺口，结构化路径会用最新 ModelGraph 和重新构建的 guidance 再调用同一阶段一次，最多两次，未闭合的阶段仍显示为 `needs_review`，离线规则路径不增加重复调用。上传文档解析出的每个 Source Region 会登记为 `document_region` Evidence，文档 Requirement 同时保存对应 `source_ids` 和 `evidence_ids`，模型补丁提交后证据节点会进入同一份 ModelGraph 并随交付包输出。语义校验失败的 LLM 输出只保存为 candidate 并进入 review，不计入完成度。离线 fallback 的 F/L/P 也消费图中的功能职责、分区键、共享状态和 Requirement 关系；未知 SWaP-C/续航仍保持 `needs_measurement`，不会伪造可行性。历史 Ollama conformance artifact 仍只代表结构化边界，不等同于真实 Provider 的 23-task 稳定性。

每次 `POST /projects/{id}/analysis` 成功返回的 `run` 还会携带一个轻量 `deliverable` 清单：它与本次运行的 `revision`、`snapshot_hash` 一致，并提供结构化交付包与 ZIP 下载入口；完整模型内容只通过交付包接口读取，避免在运行响应中重复传输。未填写远程 Profile 的预算时，Harness 默认使用 8192 token 上下文窗口和 4096 token 结构化输出预算；显式配置仍优先。

纵向链完成后由 Methodology Engine 对 ModelGraph 做确定性工程分析：逻辑层报告分配覆盖、State 模型、分区和内聚/耦合信号；物理层传播约束并区分冲突与待测量；V&V 分开报告 Verification、Validation、Hazard/FailureMode 覆盖、计划字段完整度和执行证据。现在 Methodology 还会基于功能流、共享状态、显式依赖和当前分配，生成可比较的 Logical 架构候选，给出分区、跨组件交互、耦合/内聚和评分；同时输出每个 Physical candidate 的约束传播、冲突、缺失测量字段和可行性评分。默认 fallback 的 Function 会保留输入需求驱动的 decomposition，Physical candidate 会保留结构化 trade study 与选择依据。每个生成任务都会收到有界的 `methodology_guidance`，把当前阶段的确定性 findings、关键指标、架构候选和推荐任务交给 LLM 作为下一步工程推理输入，而不是只在生成结束后验收。计划字段和 evidence 始终分层，空 evidence 不会伪装成已执行。Systems Engineering Controller 将这些 findings 汇总为下一步动作：证据缺口先通过 Tool Layer 检索文档、历史项目和本地 FTS，检索到的证据落库后触发受影响阶段重分析；仍无结果时暂停等待用户。逻辑分区或物理约束需要权衡时展示候选方案，用户选择后触发受影响阶段的定向重分析；V&V 失败会沿 R→F→L→P 返回影响实体和 impact paths，并在 Assurance 页面给出功能重构、架构替换、需求调整或修订验证条件等 Trade Study 选项，不自动盲目重跑；其中 `dependency_cluster_search` 也会由离线 Runtime 实际应用为版本化逻辑架构。Review 和 Controller 都沿图返回影响实体、阶段、路径和审计记录，不绕过 CAS，也不替用户无审查地作工程决策。

Trade Study 的用户选择现在会真正改变架构图：Logical 选择可生成“每功能一个组件”或“共享协调器”变体，保留旧组件并对未锁定旧组件做版本化弃用；Physical 选择“更换物理候选或计算架构”会新增可比较的替代候选。每个变体都保留 `architecture_decision` 来源，锁定或用户修改的实体不会被覆盖；替代候选不填充虚假的 SWaP-C 测量，原有约束、冲突和待验证问题继续可见。

在实体 Review 后，用户可以先创建影响分析请求，也可以执行定向重新分析：编辑 Requirement 会从 Requirements 向下重跑，编辑 Function 从 Functional 向下重跑，Logical/Physical/V&V 编辑只重跑受影响的后续阶段。重分析沿现有 trace 复用未被人工修改或锁定的派生对象，用 `updates` 保持 canonical ID 并刷新下游语义；人工修改或锁定对象作为只读锚点保留，必要时产生待评审差异。确认实体后还可以显式执行“继续生成下游”，从已确认层的下一个阶段运行到 V&V；锁定实体作为只读锚点参与推理，不会被修改。完整交互闭环是：`Review 实体 → 接受/锁定 → 继续生成下游 → 重新计算 Trace/Methodology → Review 新结果`。每次重分析或继续生成仍写入独立 Run、Patch、Revision 和 audit，不覆盖锁定实体。

Controller 还提供有界的“自动推进安全动作”入口：它可以连续执行安全的局部重分析或证据检索，并在每轮重新计算 Traceability、Methodology 和下一步动作；遇到 Trade Study、缺少用户输入/证据、无进展或迭代预算耗尽时暂停。Trade Study 方案仍必须由用户明确选择，LLM 生成内容继续经过结构化 Runtime、Compiler、Validator 和 CAS。

对完整 fixture 的 23-task 兼容链，后置功能/技术/反向需求会回接已有 Function 与 V&V 案例，最终交付包以 7/7 需求形成完整 R→F→L→P→V&V 追溯作为验收证据。

每次编辑都会生成绑定当前 revision/snapshot hash 的 Typed Impact Plan，明确 R→F→L→P→V&V 影响实体、关系路径、V&V 案例和推荐任务；`GET /projects/{id}/entities/{entity_id}/impact` 与编辑响应会把这份计划和 Controller 下一动作交给工作台，定向重分析还返回 before/after Traceability。

## 开发与验收

```bash
./.venv/bin/python -m pytest -q
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

## 边界

Core 不包含旧版智能发现、Concept/MDO、Project Bridge、测试执行沙箱、仿真、旧 Baseline/TaskContract/Job 体系或 MLflow 适配器。它们不再作为隐式依赖存在；如未来需要，应以独立插件或独立研究包接入。
