# 自动多分块 LLM 分析设计

## 目标

用户提交需求一次，页面等待 LLM 自动完成六个分析块，完成后自动刷新。默认只分析新增或变化内容；单块失败不阻断其他块。

## 已确认方案

- 使用当前启用的同一个 LLM。
- 一个父 Job 汇总六个独立 Block Job：system_scope、stakeholders、concerns_needs、requirements、scenarios、architecture。
- 本地 Ollama 默认单并发，按上述顺序执行。
- 前序块成功时后序块使用其结果；前序块失败时后序块使用规则基线和已有成功结果继续。
- LLM 结果进入候选工作台，不绕过现有人工确认门禁。
- 复用现有 Job、lease、heartbeat、metadata 和 CAS，不新增外部队列或依赖。

## 用户流程

1. 用户提交文本或文件。
2. 系统保存规则基线和输入版本，创建父 Job 与六个子 Job。
3. 浏览器进入等待页，显示：排队 → 分析中 → 校验中 → 已完成/部分失败。
4. 页面每 1–2 秒查询父 Job；刷新或关闭页面不影响后台任务。
5. 六个子任务全部结束后，页面自动跳转到结果页。
6. 部分失败时保留成功结果，只显示一个主要操作：“重试全部失败项”；单块重试放入高级详情。

等待页使用状态查询，不长时间挂起最初的 HTTP POST。

## 应用边界

- RequirementsAnalysisCoordinator：创建父子任务、增量范围、幂等键和汇总状态。
- AnalysisBlockRunner：执行一个分析块，调用 LLM、校验、修复并通过 CAS 提交。
- SourceReferenceGuard：限制和修复来源 ID。
- AnalysisRunPresenter：输出等待页需要的聚合进度和诊断。

父 Job kind 为 requirements.analysis；子 Job kind 为 requirements.analysis.block。父任务保存子 Job ID 和模块状态，子任务保存 parent_job_id、block_id、耗时、尝试次数、失败阶段和修复记录。

## 入口

    POST /requirements/analyze
    POST /requirements/analysis-runs
    POST /requirements/analysis/blocks/:block_id
    GET  /requirements/analysis-runs/:run_id
    POST /requirements/analysis-runs/:run_id/retry-failed

Web 和 /api/v1 共用应用服务。现有 reanalyze、retry-block 路由保留并转发到新服务。

## 来源 ID Bug 修复

已复现：真实 ID region-306bc6c648e7 被 4B 模型返回成 region-306bc6c6c8e7。

- 将当前批次允许的来源 ID 注入 response schema 和提示词。
- 单来源批次中，缺失或非法 ID 自动替换为唯一真实 ID，并记录 source_region_repaired。
- 多来源批次不做模糊猜测；自动发起一次语义修复请求，仍失败则拒绝合并。
- 修复结果必须重新通过 Schema 和语义校验。

## 失败与恢复

- 连接或超时自动重试两次。
- JSON/Schema 错误自动修复一次。
- 单块失败不阻断其余块；父任务最终为 completed、degraded、failed、interrupted 或 superseded。
- 相同工作区、内容版本、输入哈希、分析模式和模块使用幂等键，避免重复请求。
- 内容在分析期间变化时，旧任务标记 superseded，不得覆盖新内容。
- 服务器重启后沿用现有 lease 机制恢复未完成任务。

## 最小验收

1. 一次提交自动产生一个父 Job 和六个子 Job。
2. 页面等待、展示进度，并在全部终止后自动刷新。
3. 一个模块失败时其他模块仍完成，成功结果不丢失。
4. 上述来源 ID 抄写错误在单来源场景自动修复并留下审计记录。
5. “重试全部失败项”不重跑成功模块。
6. 重复提交不产生重复活动任务。
7. 重启恢复和 CAS 版本保护有效。
8. 相关单元、Job、Web/API 与集成测试通过；真实 Ollama 仅作为可选冒烟测试。
