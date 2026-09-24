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
  "timeout_seconds": 900,
  "context_window": 16384,
  "max_output_tokens": 4096,
  "temperature": 0.0,
  "reasoning_effort": "none",
  "think": false,
  "chat_template_kwargs": {"enable_thinking": false},
  "vertical_feedback": false,
  "vertical_batch_size": 2,
  "vertical_vv_batch_size": 1,
  "vertical_batch_output_tokens": 3072,
  "max_parallel_requests": 2,
  "structured_output_mode": "json_schema",
  "active": false
}
```

The current Jiayu-intern Controller endpoint advertises
`max_model_len=16384`; keep the client Profile at or below that value. If the
endpoint reports a different limit, use the advertised value for the isolated
Profile instead of assuming a larger local context window.

For Qwen3.5 served by vLLM, keep thinking disabled for this structured
endpoint. Otherwise the model can spend the output budget on a visible
`Thinking Process` instead of the TaskProposal JSON, causing truncation and
making a full vertical run exceed its timeout. These are transport controls;
they do not replace the Methodology Engine or the post-response validators.

For a remote profile, `vertical_feedback` defaults to `false` so a multi-
requirement run does not repeat every F/L/P provider batch. The product path
still gives Requirements a bounded, targeted completion loop (up to four
passes) for missing operational kinds such as Activity; this is completion of
the R-layer prerequisite, not a repeatability experiment. The typed vertical
completion bridge remains an explicit deterministic fallback; set
`vertical_completion_bridge` to `true` only when that fallback is desired.

The repository also includes a compatibility profile at
`docs/jiayuinter-vllm-fast-profile.json`. It is intended for completing an
integration experiment when the remote vLLM structured-sampling path is
unstable: it disables remote Schema transport, limits each response to 256
tokens, fails fast on a truncated vertical response, and records the
deterministic vertical-rule bridge explicitly. This profile is suitable for
pipeline/traceability acceptance, not for measuring pure remote-model
semantic quality.

V&V defaults to one requirement per batch for remote profiles and then splits
that requirement into one VerificationCase request and one ValidationCase
request. Each request has a narrowed contract requiring the canonical
`requirement_ids`, so post-response scope enrichment can align the Case to the
same R→F→L→P trace. These singleton Case requests still run in parallel up to
`max_parallel_requests`; set `vertical_vv_batch_size` explicitly only when the
remote model has enough output budget for larger assurance batches.

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

## 4. Run the reproducible A–E comparison

After `/v1/models` reports `qwen3.5-controller`, run one real case through all
five same-model scenarios. A–E comparisons require at least three repeats;
`--benchmark-token-budget` makes the shared per-provider-call cap explicit:

```bash
RFLP_CONFIG_DIR=/tmp/ai4mbse-jiayuinter-profile \
  ./.venv/bin/python tests/mbse_benchmark/run_benchmark.py \
  --track llm \
  --profile jiayuinter-vllm \
  --path vertical \
  --case CASE-04 \
  --repeats 3 \
  --benchmark-token-budget 4096 \
  --timeout 2700 \
  --compare-a-e
```

The result is an explicit same-model A–E LLM-track comparison. It must be kept
separate from the deterministic offline Harness acceptance and must not be
described as a local model test. The report records the scenario controls and
the model/provider, prompt/task/input/graph hashes, temperature, token usage,
latency, verifier, repair, and CAS settings for every scenario.
`--timeout` is the outer timeout for one case/repeat; keep the profile's
per-provider-request timeout at or below 900 seconds. B staged and C/D/E
Harness paths make multiple provider calls, so the outer timeout must not be
confused with the single-request limit.

For the compatibility/diagnostic 23-task lifecycle, use the same isolated
profile with `--path lifecycle`:

```bash
RFLP_CONFIG_DIR=/tmp/ai4mbse-jiayuinter-profile \
  ./.venv/bin/python tests/mbse_benchmark/run_benchmark.py \
  --track llm \
  --profile jiayuinter-vllm \
  --path lifecycle \
  --case CASE-04 \
  --repeats 1 \
  --timeout 2400 \
  --scenario E_full_harness
```

When the configured Runtime advertises parallel support, this path dispatches
only dependency-safe task groups concurrently. The profile's
`max_parallel_requests` bounds both task-level and requirement-batch calls
(1–4; remote profiles default to 2). The
Operational, Functional, Logical/Physical, and Assurance phase boundaries
remain ordered; patches are merged deterministically through the normal
Validator/CAS path. If the remote port is unavailable, wait for the GPU
launcher and do not start a local model or stop unrelated remote jobs.

Transient SSH-forward or provider restarts are retried once by default for a
remote profile. HTTP errors, invalid JSON, and schema/semantic failures are not
retried; those remain visible as reviewable LLM-stage issues.

## 5. Verified compatibility run

The following command was verified against `qwen3.5-controller` for CASE-05:

```bash
RFLP_CONFIG_DIR=/tmp/ai4mbse-bridge-config \
  .venv/bin/ai4mbse model-profile save \
  docs/jiayuinter-vllm-fast-profile.json
RFLP_CONFIG_DIR=/tmp/ai4mbse-bridge-config \
  ./.venv/bin/python tests/mbse_benchmark/run_benchmark.py \
  --track llm \
  --profile jiayuinter-vllm-fast \
  --path vertical \
  --case CASE-05 \
  --repeats 1 \
  --timeout 300 \
  --scenario E_full_harness
```

Observed result: `ACCEPTED`, `100 / 100`, P0 `6 / 6`, 37 entities, 54
relations, and 2/2 complete R→F→L→P→V&V paths. The Chinese delivery summary
is written to `tests/mbse_benchmark/reports/llm/jiayuinter-vllm-fast/实验报告_中文.md`.
