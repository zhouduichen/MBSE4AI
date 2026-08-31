# Windows 5080 Ollama Remote Inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure AI4MBSE to use the Windows RTX 5080 Ollama model `qwen3.5:9b-q8_0` through a tailnet-only Tailscale Serve endpoint.

**Architecture:** Keep Ollama bound to Windows `127.0.0.1:11434` and add a Tailscale Serve HTTPS proxy on port `11434`. Store one local AI4MBSE `local` profile pointing to the HTTPS hostname; the existing native Ollama adapter will call `/api/chat`, so no source implementation changes are needed.

**Tech Stack:** Windows PowerShell over SSH, Tailscale Serve 1.102.2, Ollama HTTP API, Python 3.11+ service configuration, existing `urllib`/OpenAI-compatible adapter, pytest.

## Global Constraints

- Keep the Windows Ollama listener on `127.0.0.1:11434`.
- Expose the proxy only to the Tailscale tailnet; do not use Funnel or bind Ollama to `0.0.0.0`.
- Preserve existing Tailscale Serve entries for ports 22, 443, 8443, and 8765.
- Do not write an API key; the local Tailscale/Ollama profile uses an empty key.
- Do not stage or alter unrelated existing worktree changes.
- Use profile ID `windows-5080-ollama`, Base URL `https://autoresearch-5080.tail2530b8.ts.net:11434/v1`, and model `qwen3.5:9b-q8_0`.

---

### Task 1: Add the tailnet-only Windows Ollama proxy

**Files:**
- No repository files; run commands on the authorized Windows host `autoresearch-5080`.

**Interfaces:**
- Consumes: Windows Ollama at `http://127.0.0.1:11434` and the existing Tailscale Serve configuration.
- Produces: `https://autoresearch-5080.tail2530b8.ts.net:11434` forwarding to the loopback Ollama service.

- [ ] **Step 1: Capture the current Serve configuration**

Run:

```bash
ssh -o BatchMode=yes autoresearch-5080 'powershell.exe -NoProfile -NonInteractive -Command "& $env:ProgramFiles\\Tailscale\\tailscale.exe serve get-config $env:TEMP\\ai4mbse-serve-before.json --all; & $env:ProgramFiles\\Tailscale\\tailscale.exe serve status"'
```

Expected: Existing entries for SSH/22, HTTPS/443, HTTPS/8443, and HTTPS/8765 are present, and a complete rollback snapshot is saved at the explicit Windows temp path; no global reset is performed.

- [ ] **Step 2: Configure only the new HTTPS listener**

Run:

```bash
ssh -o BatchMode=yes autoresearch-5080 'powershell.exe -NoProfile -NonInteractive -Command "& $env:ProgramFiles\\Tailscale\\tailscale.exe serve --bg --https=11434 http://127.0.0.1:11434"'
```

Expected: Tailscale reports a tailnet-only HTTPS listener on port 11434. If the command requests confirmation, rerun the same command with `--yes`; do not run `serve reset`.

- [ ] **Step 3: Verify the proxy and model list from macOS**

Run:

```bash
curl --fail --silent --show-error --connect-timeout 5 \
  https://autoresearch-5080.tail2530b8.ts.net:11434/api/tags
```

Expected: JSON includes a model named `qwen3.5:9b-q8_0`. If the request fails, inspect `serve status` and stop before changing AI4MBSE configuration.

- [ ] **Step 4: Commit the infrastructure checkpoint**

```bash
git status --short
git diff --check
```

Expected: The repository has no accidental changes from the infrastructure command; unrelated user changes remain untouched.

### Task 2: Save and activate the AI4MBSE remote model profile

**Files:**
- No repository files; update the user-level LLM profile through `LLMProfileService`.

**Interfaces:**
- Consumes: Verified Tailscale HTTPS Ollama endpoint from Task 1.
- Produces: Active profile `windows-5080-ollama` with no API key.

- [ ] **Step 1: Save the exact profile through the existing service**

Run from the repository root:

```bash
.venv/bin/python -c 'from rflp_lite.application.llm_profiles import LLMProfileService; print(LLMProfileService().save({"id":"windows-5080-ollama","label":"Windows 5080 Ollama","kind":"local","protocol":"openai-chat","base_url":"https://autoresearch-5080.tail2530b8.ts.net:11434/v1","model":"qwen3.5:9b-q8_0","timeout_seconds":300,"api_key":"","active":True}))'
```

Expected: Printed profile has `id` `windows-5080-ollama`, `kind` `local`, `model` `qwen3.5:9b-q8_0`, and `api_key_configured` false or no configured key. The service writes the profile to its normal user-level config path.

- [ ] **Step 2: Confirm the active profile without printing credentials**

Run:

```bash
.venv/bin/python -c 'from rflp_lite.application.llm_profiles import LLMProfileService; s=LLMProfileService().snapshot(); print({"active_id":s["active_id"],"profile":next((p for p in s["profiles"] if p["id"]==s["active_id"]),None)})'
```

Expected: `active_id` is `windows-5080-ollama`, Base URL is the HTTPS Tailscale URL, and the output contains no API key value.

- [ ] **Step 3: Run the adapter and profile regression tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/adapters/test_llm_client.py \
  tests/adapters/test_openai_compatible_model.py \
  tests/application/test_llm_profiles.py
```

Expected: All selected tests pass; no source changes are required for this configuration path.

### Task 3: Test one real remote completion and the application connection path

**Files:**
- No repository files unless a test exposes an existing defect; do not preemptively refactor adapters.

**Interfaces:**
- Consumes: Active profile and Tailscale proxy from Tasks 1–2.
- Produces: Evidence that `/api/chat`, the AI4MBSE connection test, and one short analysis use the Windows Ollama model.

- [ ] **Step 1: Send a minimal non-streaming native Ollama request**

Run:

```bash
curl --fail --silent --show-error --connect-timeout 5 \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5:9b-q8_0","messages":[{"role":"user","content":"Reply with OK only."}],"stream":false,"think":false,"options":{"temperature":0,"num_predict":16}}' \
  https://autoresearch-5080.tail2530b8.ts.net:11434/api/chat
```

Expected: JSON contains a non-empty `message.content` and the model is `qwen3.5:9b-q8_0`.

- [ ] **Step 2: Exercise the configured adapter connection test**

Run:

```bash
.venv/bin/python -c 'from rflp_lite.application.llm_profiles import LLMProfileService; print(LLMProfileService().test({"id":"windows-5080-ollama","label":"Windows 5080 Ollama","kind":"local","protocol":"openai-chat","base_url":"https://autoresearch-5080.tail2530b8.ts.net:11434/v1","model":"qwen3.5:9b-q8_0","timeout_seconds":30}))'
```

Expected: Result has `status` `connected`, the remote model name, and a short preview.

- [ ] **Step 3: Confirm GPU execution on Windows**

Run:

```bash
ssh -o BatchMode=yes autoresearch-5080 'powershell.exe -NoProfile -NonInteractive -Command "ollama.exe ps"'
```

Expected: `qwen3.5:9b-q8_0` appears while the test or analysis is active, confirming the computation is remote.

- [ ] **Step 4: Run one minimal AI4MBSE analysis smoke test**

With the local web server running at `http://127.0.0.1:8000`, submit a short requirement and invoke the existing AI route:

```bash
curl --fail --silent --show-error -X POST \
  -F 'text=The system SHALL preserve an auditable history.' \
  http://127.0.0.1:8000/w/demo/requirements/analyze \
  -o /dev/null -w '%{http_code}\n'
curl --fail --silent --show-error -X POST \
  http://127.0.0.1:8000/w/demo/requirements/ai \
  -o /dev/null -w '%{http_code}\n'
curl --fail --silent --show-error \
  http://127.0.0.1:8000/api/v1/workspaces/demo/requirements
```

Expected: The first two commands return HTTP 303, the state JSON shows an analysis Job, and the Job reaches `completed` or `degraded`. Confirm the result page reports the LLM block status and no local Ollama process is required. If `demo` does not exist, create it from the Web UI first; do not create a second workspace just for this smoke test.

Expected: The request succeeds through the configured profile; if the remote service is interrupted, the deterministic baseline remains available and the UI reports a visible LLM failure.

### Task 4: Record the completed configuration and rollback procedure

**Files:**
- Modify: `docs/DEVELOPMENT_STATUS.md` only if it currently claims remote Ollama is unavailable after successful verification.

**Interfaces:**
- Consumes: Verification evidence from Tasks 1–3.
- Produces: Accurate capability status and a reversible operator procedure.

- [ ] **Step 1: Recheck the final Serve configuration**

Run the Task 1 status command and confirm ports 22, 443, 8443, 8765, and 11434 all remain configured.

- [ ] **Step 2: Document only verified capability changes**

If documentation still says remote Ollama is unconfigured, update the smallest matching sentence in `docs/DEVELOPMENT_STATUS.md` to state that a tailnet-only Tailscale Serve path is configured for `qwen3.5:9b-q8_0`. Do not rewrite unrelated status text.

- [ ] **Step 3: Verify rollback is scoped to one listener**

Before any rollback, inspect the status and restore the captured all-services snapshot with the supported declarative operation:

```bash
ssh -o BatchMode=yes autoresearch-5080 'powershell.exe -NoProfile -NonInteractive -Command "& $env:ProgramFiles\\Tailscale\\tailscale.exe serve set-config $env:TEMP\\ai4mbse-serve-before.json --all"'
```

Never use `tailscale serve reset`; then restore the prior AI4MBSE profile via the LLM settings page or `LLMProfileService.activate`.

- [ ] **Step 4: Final repository hygiene check**

Run:

```bash
git status --short
git diff --check
```

Expected: No accidental edits, generated artifacts, credentials, or staged unrelated files.
