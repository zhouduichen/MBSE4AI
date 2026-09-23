# 结构化结构选型推荐实施计划

> **执行约束：** 本计划只使用离线规则和 preview CAD backend 验证；不启动本机模型、远程模型、SSH、服务器、FreeCAD 或实验任务。

## 任务 1：扩展结构化契约和领域对象

- [x] 修改 `src/rflp_lite/resources/schemas/design_intent_draft.v1.json`，增加 `structure_options` 对象数组。
- [x] 修改 `src/rflp_lite/resources/prompts/design_intent.v1.md`，要求结构候选显式标记为 recommendation。
- [x] 修改 `src/rflp_lite/domain/detail_design.py`，为 `DesignIntent` 保存候选，为 `CadExecutionPlan` 保存选择 ID。
- [x] 修改 `src/rflp_lite/application/design_intent.py`，增加按目标类型生成的离线确定性候选，并把候选纳入意图哈希和序列化。
- [x] 增加领域/应用测试，覆盖候选字段、推荐状态和未选择语义。

## 任务 2：接入计划、API、UI 和 PhysicalBlock

- [x] 修改 `src/rflp_lite/application/cad_workflow.py`，校验选择 ID 属于草案候选，并在计划、模型和 PhysicalBlock 中保留追溯。
- [x] 修改 `src/rflp_lite/interface/web/resource_api.py`，允许 CAD 计划请求提交 `selected_structure_option_id`。
- [x] 修改 `src/rflp_lite/interface/web/templates/cad-design.html`，在生成计划前展示候选并提供“选择/不预选”控件。
- [x] 更新 `tests/application/test_cad_workflow.py`、`tests/interface/web/test_cad_design.py` 和 `tests/e2e/test_local_product_acceptance.py`。

## 任务 3：交付物、文档和离线验收

- [x] 确认 `detail-design.json`、PhysicalBlock 和 SysML 投影通过已有 `as_dict` 路径保留候选与选择。
- [x] 更新 `README.md`、`docs/DEVELOPMENT_STATUS.md` 和 `docs/superpowers/README.md`。
- [x] 运行聚焦测试、`git diff --check` 和 `scripts/verify_full.py`，其中配置临时 `RFLP_CONFIG_DIR` 和 `AI4MBSE_CAD_BACKEND=preview`。
- [ ] 提交并推送到当前 GitHub 分支。
