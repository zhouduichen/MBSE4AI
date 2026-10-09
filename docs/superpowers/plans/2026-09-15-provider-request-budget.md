# Provider 请求上下文预算施工计划

## 目标

让五阶段结构化 LLM 请求使用与实际序列化内容一致的上下文预算，避免 ModelGraph 上下文估算通过、Provider 却因 `prompt + output > context_window` 隐式截断。

## 实施边界

- 复用现有 ContextPlanner 和 OpenAI-compatible/Ollama 适配器。
- 共享一个轻量、无模型依赖的 token 估算函数；不安装 tokenizer，不启动本机模型。
- 只压缩重复的 Methodology guidance，不删除需求、关系、证据或结构化 schema 约束。
- 远程 Ollama profile 固定显式 `context_window=8192`、`max_output_tokens=2048`；节点在线后仍只执行一次真实远程纵向验收。

## 变更与验收

1. `ContextPlanner` 与 Provider 使用同一 heuristic token estimate。
2. Methodology guidance 限制 findings/decisions 数量，保留逐需求 coverage、stage completion 和架构证据。
3. Provider 发送前按 `context_window - prompt_estimate - margin` 限制输出；若连最小输出也放不下，返回 `context_window_exceeded`，不发送超窗请求；结构化 repair 使用同一规则。
4. Adapter 回归覆盖输出裁剪和不可容纳请求；三需求五阶段结构化验收与既有全量测试保持通过。

## 远程验收

远程 `autoresearch-5080` 可用后运行：

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py \
  --track llm --profile windows-5080-ollama --path vertical \
  --case CASE-04 --repeats 1 --timeout 900 --baseline bare
```

当前节点离线时不得改用本机 Ollama 代替。
