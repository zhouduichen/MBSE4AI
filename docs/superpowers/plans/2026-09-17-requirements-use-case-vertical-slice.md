# M1/M2 需求捕获与用例建模纵向切片实施计划

> **For the implementer:** REQUIRED SUB-SKILL: Use the `writing-plans` skill to execute this plan task-by-task.

**目标：** 把 Word/PDF/Markdown/TXT 文档或文本输入转成可追溯的需求、实体、约束、用例、运行场景和活动候选，并接入现有 ModelGraph、人工评审、行为视图和 RFLP 入口。

**实现策略：** 新增一个领域无关的结构化 IntakeDraft 层；LLM 只产生 draft，确定性编译器负责校验、来源绑定、显式约束优先级、稳定 ID、关系和幂等 Patch。远程 profile 使用现有 RuntimeFactory；离线测试使用 fake model 或规则 fallback，不启动本机模型。

## 任务 1：建立 IntakeDraft 数据契约与 schema

**文件：** `src/rflp_lite/application/requirements_use_case.py`（新建）、`src/rflp_lite/resources/schemas/requirements_use_case_draft.v1.json`（新建）、`tests/application/test_requirements_use_case.py`（新建）

- 定义 draft 的不可变 DTO/序列化函数，覆盖 `system_context`、entities、requirements、use_cases、scenarios、clarifications、diagnostics。
- 对实体类型、约束来源、运算符、置信度、步骤序号和分支目标做有限 schema 校验。
- 实现 source reference 校验所需的轻量 helper；不允许未知实体类型或任意关系直接进入图。
- 编写 schema、中文字段和无效输入单元测试。

## 任务 2：实现远程 LLM 提取器和确定性 fallback

**文件：** `src/rflp_lite/application/requirements_use_case.py`、`src/rflp_lite/resources/prompts/requirements_use_case.v1.md`（新建）、`tests/application/test_requirements_use_case.py`

- 读取项目文档区域和 evidence；文本输入无文档区域时生成稳定的内存 source refs。
- 通过现有 `GenerativeModel.complete_json(GenerationRequest)` 发出 `requirements.use_case` 请求，使用 draft schema 和远程 runtime 的 provider/model 元数据。
- 将结果限制在 draft schema 内，保留 provider、model、input/output hash、耗时和 diagnostics。
- 使用现有 `extract_requirement_constraints` 重新从原文提取显式约束，与 LLM 约束合并为 explicit > derived > llm_inferred；冲突写入 diagnostics，不覆盖显式值。
- 没有可用模型时提供只基于规则/句法的可查看 draft，明确 `degraded` 和待人工复核，不伪造 LLM 置信度。
- 测试 fake model、远程 GenerationRequest、显式值覆盖、LLM 失败和中文 prompt。

## 任务 3：实现 draft 到 ModelGraph 的确定性编译与幂等写入

**文件：** `src/rflp_lite/application/requirements_use_case.py`、`src/rflp_lite/bootstrap/v2.py`、`tests/application/test_requirements_use_case.py`

- 解析 local_ref，优先复用当前项目中同类型、同规范名称且未弃用的实体；禁止覆盖用户修改/锁定 payload。
- 将实体和关系编译为 `AddEntity`/`Relate`/必要的 `UpdateEntity`，所有新对象状态为 candidate、producer 为 llm，source/evidence ids 绑定真实区域。
- 将 use case、scenario、activity 的 actor、sequence、branch 引用解析为 canonical IDs；无效引用记录诊断并跳过单条关系/步骤。
- 为行为关系使用已有谓词并调用 `ModelGraph.validate_relation`；保持非法关系不能污染仓库。
- 以 draft hash + 当前 revision 保证重复 apply 不新增 revision/实体/关系；记录 `requirements_use_case.draft_created`、`requirements_use_case.draft_applied` 审计事件。
- 将服务挂载到 `V2Services.requirements_use_case(project_id, profile_id=None)`。
- 测试来源、状态、重复运行、用户修改保护、关系端点和冲突 revision。

## 任务 4：接入 API 与行为投影

**文件：** `src/rflp_lite/interface/web/resource_api.py`、`src/rflp_lite/application/projections/behavior.py`、`tests/interface/web/test_requirements_use_case.py`（新建）

- 新增 `POST /projects/{project_id}/requirements-use-case/draft`：接受文本、document_ids、profile_id，返回 draft 和运行元数据，不写入图。
- 新增 `POST /projects/{project_id}/requirements-use-case/apply`：接收 draft 或 draft_id，执行确定性编译和单 Patch 写入。
- 新增 `GET /projects/{project_id}/requirements-use-case/drafts`：从审计事件返回当前项目可查看的提取批次。
- 复用现有 entity review API 支持候选接受、编辑、驳回；不新建审批状态机。
- 扩展 behavior projection 包含 `USE_CASE`、`OPERATIONAL_SCENARIO` 和场景化活动步骤/分支，同时保留现有 interface/state/function 记录。
- API 测试完整调用顺序：导入文档 → draft → apply → graph/behavior → accept/edit。

## 任务 5：接入 Web 需求分析工作台

**文件：** `src/rflp_lite/interface/web/resource_pages.py`、`src/rflp_lite/interface/web/templates/analysis.html`、`src/rflp_lite/interface/web/templates/requirements-use-case.html`（新建）、`src/rflp_lite/interface/web/static/app.css`、`tests/interface/web/test_requirements_use_case.py`

- 在需求分析页增加提取入口，选择已导入文档或粘贴文本，并选择当前模型 profile。
- 展示 draft 的需求、实体、用例/场景、约束来源、证据定位、置信度、假设、澄清问题和 diagnostics。
- 提供应用 draft、进入行为视图、进入 RFLP 的操作；候选对象继续使用现有 review API。
- 页面只显示脱敏后的 profile 元数据，不渲染 API key、原始秘密或不必要的 prompt。
- 用页面测试保证在离线模式也能显示规则 fallback 的降级结果，远程模式显示模型信息。

## 任务 6：端到端验证和回归

**文件：** `tests/e2e/test_requirements_use_case_vertical_slice.py`（新建）、`tests/fixtures/requirements_use_case_acceptance.txt`（新建）

- 使用固定中文验收文档，验证至少 3 条需求、1 个 Use Case、1 个 Operational Scenario、1 个 Activity。
- 验证每个候选具有文档 region/evidence 追溯或显式 `llm_inferred` provenance。
- 验证人工接受后可进入现有 RFLP 生成，行为投影能再读取，SysML 子集导出/导入不破坏结果。
- 远程 vLLM 仅作为显式集成测试入口，不把网络可用性作为离线回归的必要条件；不在本机启动模型。
- 运行相关单测、API/e2e 测试和既有回归测试；记录实际缺口，不扩张到重复稳定性矩阵。

## 任务 7：提交与推送

- `git diff --check`、相关 pytest、全量 pytest（若环境允许）和 git status。
- 提交一个聚焦 M1/M2 的 commit，推送当前 GitHub 分支。
- 最终报告真实已实现范围、远程模型测试结果、未完成的 M3/M4/M5/M6/M7 和下一条纵向切片。

