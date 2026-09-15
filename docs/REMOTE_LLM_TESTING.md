# Remote LLM testing through Jiayu-intern

This project can use a model served on `Jiayu-intern` through an SSH local
forward. The loopback URL below is the SSH tunnel endpoint; it is not a model
running on the development computer. Do not start Ollama, vLLM, or another
model server locally.

## 1. Check the remote service

The controller launcher must have a healthy vLLM API on the remote loopback
port before opening the tunnel:

```bash
ssh Jiayu-intern 'ss -ltn | grep -E ":8000($| )"'
```

The expected model name is `qwen3.5-controller`. If the port is not listening,
wait for the remote launcher/GPU queue; do not stop unrelated GPU jobs.

## 2. Open an SSH tunnel

Keep this command running in a separate terminal:

```bash
ssh -N -T \
  -o BatchMode=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L 18000:127.0.0.1:8000 \
  Jiayu-intern
```

Verify the tunnel without invoking a generation:

```bash
curl --fail http://127.0.0.1:18000/v1/models
```

## 3. Save an isolated profile

Write a temporary profile JSON outside the repository. `kind` is `local`
because the application connects to the local end of the SSH forward; the
actual model remains remote.

```json
{
  "id": "jiayuinter-vllm",
  "label": "Jiayu-intern vLLM",
  "kind": "local",
  "model_location": "remote",
  "provider": "openai-compatible",
  "base_url": "http://127.0.0.1:18000/v1",
  "model": "qwen3.5-controller",
  "timeout_seconds": 300,
  "context_window": 32768,
  "max_output_tokens": 4096,
  "temperature": 0.0,
  "structured_output_mode": "json_schema",
  "active": false
}
```

Save it with the CLI in an isolated configuration directory, then use the
profile explicitly. This keeps the user's normal profile directory and
active profile unchanged:

```bash
RFLP_CONFIG_DIR=/tmp/ai4mbse-jiayuinter-profile \
  .venv/bin/ai4mbse model-profile save /tmp/jiayuinter-vllm.json
RFLP_CONFIG_DIR=/tmp/ai4mbse-jiayuinter-profile \
  .venv/bin/ai4mbse --workspace-root .local-workspaces \
  analyze generate campus-demo \
  --profile jiayuinter-vllm \
  --text "系统应在校园内完成配送，并允许运营人员人工接管"
```

The run ledger records the selected profile, provider, model, prompt/context
hashes, patches, revisions, and final traceability. A run using
`offline-rule` is not evidence of a real Provider run.

## 4. Run the focused acceptance

After `/v1/models` reports `qwen3.5-controller`, run one real vertical case:

```bash
RFLP_CONFIG_DIR=/tmp/ai4mbse-jiayuinter-profile \
  ./.venv/bin/python tests/mbse_benchmark/run_benchmark.py \
  --track llm \
  --profile jiayuinter-vllm \
  --path vertical \
  --case CASE-04 \
  --repeats 1 \
  --timeout 900 \
  --baseline bare
```

The result is an explicit LLM-track report. It must be kept separate from the
deterministic offline Harness acceptance and must not be described as a local
model test.
