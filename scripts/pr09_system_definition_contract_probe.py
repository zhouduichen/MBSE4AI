"""Run the narrow real-model system_definition contract probe."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import pr09_output_budget_experiment as budget_experiment


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--budget", type=int, default=4000, choices=(4000,))
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    budget_experiment.CHAIN_TASK_IDS = ("system_definition",)
    root = args.root or Path(tempfile.mkdtemp(prefix="ai4mbse-pr09-system-definition-"))
    runs = [
        budget_experiment._one_run(args.budget, repetition, root)
        for repetition in range(1, args.repetitions + 1)
    ]
    aggregate = budget_experiment._aggregate(args.budget, runs)
    result = {
        "experiment": "pr09-system-definition-identity-contract",
        "date": "2026-09-13",
        "code_commit": "6565397020f2b47142bbd5d22df5af2f18ca34d1",
        "fixture": str(budget_experiment.FIXTURE),
        "provider": {
            "display_name": "Windows 5080 Ollama",
            "runtime_provider_id": "windows-5080-ollama",
            "model": "qwen3.5:9b-q8_0",
            "temperature": 0.0,
            "seed": None,
            "structured_output_mode": "json_schema",
        },
        "fixed": {
            "max_output_tokens": args.budget,
            "chain": ["system_definition"],
            "prompt": "current system_definition.v1 plus common local_ref guidance",
            "task_spec": "current system_definition TaskSpec",
        },
        "acceptance": {
            "finish_reason_stop": "all successful calls",
            "duplicate_local_ref": 0,
            "identity_conflict": 0,
            "compile_rate_minimum": 0.95,
            "domain_validation_rate_minimum": 0.95,
            "system_cardinality_correct": "one active SYSTEM",
            "invalid_repository_write": 0,
        },
        **aggregate,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "experiment": result["experiment"],
        "repetitions": args.repetitions,
        "aggregate": result["aggregate"],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
