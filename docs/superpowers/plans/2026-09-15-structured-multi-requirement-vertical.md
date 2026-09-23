# 多需求结构化 LLM 纵向生成施工计划

> **目标：** 在现有五阶段产品路径上，确保一次包含多条独立自然语言需求的结构化模型请求能够逐条完成 R→F→L→P→V&V 追溯，而不是只凭离线规则 Runtime 或实体总数证明覆盖。

## 范围与边界

- 复用现有 `ModelGenerationService → StructuredModelRuntime → ProposalCompiler → ModelGraph` 写入链路。
- 不新增数据库表、第二份模型真源、23-task 重复稳定性实验或本机模型调用。
- 不把远程 Provider 不可用伪装成成功；真实远程验收仍需 `windows-5080-ollama` 节点上线后单次执行。
- 需求覆盖以 canonical Requirement ID 为主键；同一阶段不得把多条需求合并成无法追踪的单一结果。

## 实施步骤

### 1. 将逐需求工作清单注入结构化请求

**文件：**

- 修改：`src/rflp_lite/runtime/structured_model.py`
- 测试：`tests/runtime/test_task_execution.py`

**实现：**

- 从当前 `ContextBundle` 中提取活动 Requirement 的 canonical ID、statement/name 和当前阶段缺口。
- 在既有 `user_payload` 中增加 bounded `requirement_worklist`，不复制完整 ModelGraph payload。
- 增加稳定指令：对清单逐条覆盖；复用 canonical ID；不得把多条 Requirement 合并为一个下游实体。
- 没有 Requirement 时不伪造工作项；非垂直/旧任务保持兼容。

### 2. 补齐三需求结构化五阶段验收

**文件：** `tests/application/test_model_generation.py`

**实现：**

- 增加一个 deterministic structured model double，覆盖三条独立 Requirement。
- 每条需求分别生成 Function；Logical/Physical 可按职责共享，但必须为每条需求保留真实分配和 V&V scope。
- 通过生产 `StructuredModelRuntime`、Compiler、Validator、CAS 和五阶段编排，不绕过写入边界。
- 断言每阶段完成、每条需求的 `resolve_requirement_trace` 完整、SysML round-trip 保留实体/关系/关键 payload，且 ModelGraph 可继续编辑。
- 保留现有两需求反馈测试，新增断链回归，确保工作清单能被结构化模型消费。

### 3. 更新产品验收说明

**文件：** `docs/DEVELOPMENT_STATUS.md`

- 只记录已通过的离线结构化三需求验收。
- 明确区分“结构化模型路径证据”和“真实远程 Provider 证据”。
- 不把远程节点离线状态写成 Provider 已验收。

### 4. 验证、提交与远程复核

```bash
./.venv/bin/python -m pytest -q tests/runtime/test_task_execution.py tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py
./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/lint-imports
git diff --check
git status --short --branch
git push origin HEAD
```

远程节点上线后，才运行一次：

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py \
  --track llm --profile windows-5080-ollama --path vertical \
  --case CASE-04 --repeats 1 --timeout 900 --baseline bare
```

该命令仅使用远程 profile，不允许回退到 `127.0.0.1`。

## 完成标准

- 结构化请求对三条 Requirement 暴露明确、有限的逐需求工作清单。
- 三需求一次五阶段结构化路径形成三条完整端到端追溯，并通过 SysML 往返及编辑回归。
- 全量质量门禁通过，工作树干净，提交已推送到当前 GitHub 分支。
- 真实远程 Provider 仍按节点在线状态单独报告，不以离线测试替代。
