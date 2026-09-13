"""Run staged real-model probes for task-level relation policies."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import pr09_output_budget_experiment as budget_experiment


CHAINS = {
    "stakeholder_requirements": (
        "stakeholder_requirements",
    ),
    "three-task-chain": (
        "system_definition",
        "stakeholder_analysis",
        "stakeholder_requirements",
    ),
    "operational-prefix": (
        "system_definition",
        "stakeholder_analysis",
        "stakeholder_requirements",
        "lifecycle_analysis",
        "scenario_exploration",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=tuple(CHAINS))
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--budget", type=int, default=4000, choices=(4000,))
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    chain = CHAINS[args.mode]
    budget_experiment.CHAIN_TASK_IDS = chain
    root = args.root or Path(tempfile.mkdtemp(prefix=f"ai4mbse-pr09-{args.mode}-"))
    runs = [
        budget_experiment._one_run(args.budget, repetition, root)
        for repetition in range(1, args.repetitions + 1)
    ]
    aggregate = budget_experiment._aggregate(args.budget, runs)
    result = {
        "experiment": "pr09-task-relation-policy",
        "mode": args.mode,
        "date": "2026-09-13",
        "code_commit": "b4cbb54095c620b8745ac25449edb3b551d89034",
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
            "chain": list(chain),
            "prompt": "current task prompts plus common local_ref guidance",
            "task_spec": "current TaskSpecs and task-level relation policies",
        },
        "relation_policy": {
            "system_definition": [],
            "stakeholder_analysis": ["hasConcern"],
            "stakeholder_requirements": ["derivedFrom"],
        },
        **aggregate,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "experiment": result["experiment"],
        "mode": args.mode,
        "repetitions": args.repetitions,
        "aggregate": result["aggregate"],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
