# MBSE4AI External Benchmark CI

The ordinary `CI / quality` check is intentionally offline and reproducible. Real
provider, FreeCAD, and GPU evidence is collected only by
`.github/workflows/integration.yml`.

## Remote LLM A–E comparison

Configure these repository-level values:

- Variable `AI4MBSE_LLM_PROFILE`: the profile `id` to execute on the scheduled run.
- Secret `AI4MBSE_LLM_PROFILE_JSON`: the complete profile JSON, including the
  provider endpoint and credentials. The JSON `id` must equal the variable.
  It must also declare `input_cost_per_1m_tokens` and
  `output_cost_per_1m_tokens`; use `0` explicitly for a genuinely free local
  endpoint so the comparison can still prove that cost was measured.

Budget-matched runs also require a positive `--total-output-token-budget`. The
provider must return an output-token count (`output_tokens`, `completion_tokens`,
or native `eval_count`); without it the adapter fails closed, and any measured
repeat above the cap makes the comparison invalid.

For an operator-triggered run, supply the profile id through the workflow input
and keep the JSON in the repository secret. The job runs
`--compare-a-e --repeats 3 --comparison-mode natural`; a budget-matched
publication run can be launched separately with the benchmark CLI.

The job is evidence-bearing only when its own run is `success`. A missing profile
leaves the job skipped and the contract summary records `remote LLM profile: NOT
CONFIGURED`.

## FreeCAD acceptance

Enable variable `AI4MBSE_FREECAD_ENABLED=true` and provide the secrets
`AI4MBSE_CAD_SSH_HOST`, `AI4MBSE_FREECAD_COMMAND`, and
`AI4MBSE_CAD_REMOTE_ROOT`. Register a Linux self-hosted runner with labels
`self-hosted`, `linux`, and `freecad`; configure its SSH authentication and the
remote FreeCAD installation before enabling the variable.

The acceptance job must reach the labelled runner and pass
`tests/integration/test_freecad_remote.py`. A skipped job is not FreeCAD
evidence.

## GPU acceptance

Enable variable `AI4MBSE_GPU_ENABLED=true` and register a Linux self-hosted
runner with labels `self-hosted`, `linux`, and `gpu`. The runner must expose a
working `nvidia-smi` command and the repository must contain GPU-tagged
acceptance tests. The repository's explicit test is
`tests/integration/test_gpu_acceptance.py`; it is opt-in and verifies that
`nvidia-smi` reports at least one visible device. The workflow fails instead of
claiming PASS when that test is missing or the runner has no visible GPU.

## Evidence policy

The scheduled contract job always runs and executes the offline integration
contract plus robustness benchmark. It records the status of every external
prerequisite in the job summary. Only a completed, successful external job on a
configured runner is valid evidence for that integration; local fallback runs,
skipped jobs, and missing credentials are reported as unavailable.
