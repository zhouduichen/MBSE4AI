# RFLP-Lite 本地链路验证记录

**验证日期：** 2026-08-04  
**平台：** macOS 26.5（arm64）  
**Python：** 3.12.13  
**项目版本：** rflp-lite 0.1.0

## 已安装的首批开源组件

- pytest 9.1.1
- Hypothesis 6.165.0
- Import Linter 2.13
- check-jsonschema 0.37.4
- jsonschema 4.26.0
- Prance 26.7.19.0
- junitparser 5.0.1
- OR-Tools 9.15.6755

所有组件安装在项目专用 `.venv` 中。未要求或启动 Docker、GPU、PostgreSQL、Neo4j 或外部服务。

## 验证命令

```bash
.venv/bin/python -m pytest -v
.venv/bin/lint-imports
.venv/bin/check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json
.venv/bin/check-jsonschema --check-metaschema schemas/profile.schema.json schemas/run-manifest.schema.json
.venv/bin/rflp demo --workspace .local-demo-heuristic --seed 42 --solver heuristic
.venv/bin/rflp demo --workspace .local-demo-cp-sat --seed 42 --solver cp-sat
```

## 验证结果

- 测试：19 项全部通过。
- 架构：3 条 Import Linter 契约全部保持，无反向依赖。
- Schema：Profile 实例及两个 Schema 元模式检查全部通过。
- 启发式 Solver：完整链路通过，重复运行结果一致。
- CP-SAT Solver：完整链路通过，重复运行结果一致。
- 两个 Solver 均产生 3 个 Candidate、3 个 Claim、9 条 Evidence 和 3 个 TaskContract。
- 两个 Profile 得到相同的已批准 Baseline 哈希。
- 故障注入测试证明 Solver 异常时事务回滚，已有 Baseline 哈希不变，并记录 `run.failed`。

## 结果哈希

- Baseline：`a5f3f51e6e63d90041acb89bdfdb752f6b41a19dc396d8fa49584e80029aed51`
- Heuristic result：`8f74626cd873219a95a7f874051bbe31ac2bbe919ab8a0088cc447a3a302cfab`
- CP-SAT result：`0be6ec9548f8b537837a0697b9573dbbb613fbfba01ac4a1405b5276e482d2c7`

## SQLite 骨架数据

每个首次运行的演示数据库包含：1 个 Artifact、3 个 TextSpan、3 个 Claim、11 个 RFLP ModelElement、9 条 Relation、3 个 Candidate、1 个 SimulationRun、1 个 Baseline、3 个 TaskContract 和 9 条 Evidence。

## 产物位置

- Heuristic：`.local-demo-heuristic/.rflp/runs/8f74626cd873219a95a7f874051bbe31ac2bbe919ab8a0088cc447a3a302cfab/`
- CP-SAT：`.local-demo-cp-sat/.rflp/runs/0be6ec9548f8b537837a0697b9573dbbb613fbfba01ac4a1405b5276e482d2c7/`

每个目录都包含 Claims、RFLP、Candidates、Simulation、Baseline、Delta、TaskContracts、Evidence 和 Run Manifest 的规范化 JSON。

## 延后能力

LLM/Ollama/llama.cpp、Docling、MLflow、SysON、向量模型、Web UI 和远程插件 Runtime 仍按设计延后，未进入本次本地闭环。

