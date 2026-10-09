"""Run the narrow contextual three-task chain after system contract repair."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import pr09_output_budget_experiment as budget_experiment


CHAIN = (
    "system_definition",
    "stakeholder_analysis",
    "stakeholder_requirements",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--budget", type=int, default=4000, choices=(4000,))
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    budget_experiment.CHAIN_TASK_IDS = CHAIN
    root = args.root or Path(tempfile.mkdtemp(prefix="ai4mbse-pr09-contextual-chain-"))
    runs = [
        budget_experiment._one_run(args.budget, repetition, root)
        for repetition in range(1, args.repetitions + 1)
    ]
    aggregate = budget_experiment._aggregate(args.budget, runs)
    result = {
        "experiment": "pr09-contextual-three-task-chain",
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
            "chain": list(CHAIN),
            "prompt": "current task prompts plus common local_ref guidance",
            "task_spec": "current TaskSpecs",
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
