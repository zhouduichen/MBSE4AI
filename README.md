# AI4MBSE Harness

AI4MBSE Harness 产品版本为 `0.2.0`，方法论协议版本为 `v2.1`。它是一个本地优先、可复现、可审计的 MBSE 模型生成工作台。默认产品链路是：

```text
自然语言 / 文档 → Requirements → Functional → Logical → Physical → V&V
               → Typed ModelGraph → SysML v2 subset / 可编辑模型
```

ModelGraph 是模型唯一真源。纵向生成器按五个阶段调用结构化 Runtime，将每一阶段的局部 Patch 写入图并保留完整追溯链；SQLite 保存项目、文档区域、证据、运行、步骤、Patch、Revision 和 Issue。原有 23-task 生命周期仍保留为调试和兼容入口，不是默认产品路径。

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

也可以从已解析的需求文档生成：

```bash
.venv/bin/ai4mbse --workspace-root .local-workspaces project create document-demo
.venv/bin/ai4mbse --workspace-root .local-workspaces project ingest document-demo requirements.txt
.venv/bin/ai4mbse --workspace-root .local-workspaces analyze generate document-demo
```

旧的 Golden fixture 生命周期用于兼容性和方法论调试：

```bash
.venv/bin/ai4mbse --workspace-root .local-workspaces project create campus-demo
.venv/bin/ai4mbse --workspace-root .local-workspaces project ingest campus-demo tests/e2e/fixtures/campus_delivery_robot.json
.venv/bin/ai4mbse --workspace-root .local-workspaces analyze run campus-demo
# 调试单阶段时再指定 --phase operational|functional|logical_physical|assurance
.venv/bin/ai4mbse --workspace-root .local-workspaces model export campus-demo --format json
```

CLI 的主要命令：

```text
project create|ingest
analyze generate|run|status
model export|import-sysml
issue list
repair run
model-profile list|save|activate
```

## Web

```bash
.venv/bin/uvicorn rflp_lite.interface.web.app:create_app --factory --host 127.0.0.1 --port 8000
```

页面收敛为 Projects、Analysis、MBSE Model、Evidence & Issues、Settings；API 资源以 `/projects` 为根，提供项目、分析运行、模型、实体 CAS 编辑、证据、Issue、Repair 和 Export。

未配置模型时页面会明确显示 `Offline Rule Mode`；配置并激活 Profile 后，每次新分析都会记录实际使用的 profile/provider/model。服务默认只监听 `127.0.0.1`，适用于单用户本地工作区。

当前产品验收重点已经转为一次真实的五阶段纵向链：`自然语言/文档 → R → F → L → P → V&V → ModelGraph → SysML`。追溯结果分开显示 RFLP、Verification、Validation 和端到端闭环；只有两类 V&V 都存在才算端到端完成。未配置模型时使用离线规则 Runtime 验证产品闭环；配置并激活 OpenAI-compatible Profile 后，`analyze generate` 会对五个阶段分别调用结构化 LLM Runtime，并记录 profile/provider/model、Prompt、上下文、Patch 和追溯摘要。语义校验失败的 LLM 输出只保留为 `candidate` 并进入 review，不计入完成度。既有 Ollama 3 Task × 20 conformance artifact 仍只代表结构化边界，不等同于完整产品链验收。

纵向链完成后由 Methodology Engine 对 ModelGraph 做确定性工程分析：逻辑层报告分配覆盖、分区和内聚/耦合信号；物理层传播约束并区分冲突与待测量；V&V 分开报告 Verification、Validation 和结构化字段完整度；Review 重新分析请求沿图返回影响实体、阶段、路径和下一步内部任务。引擎只读模型，不替代 LLM Controller，也不把未知工程数据误报为可行。

## 开发与验收

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall -q src
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
