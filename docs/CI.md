# CI and integration boundaries

The required pull-request check is `CI / quality`. It runs the offline suite:

```bash
pytest -q
ruff check src tests scripts
python -m compileall -q src tests scripts
lint-imports
python scripts/architecture_metrics.py
python tests/mbse_benchmark/run_benchmark.py --track robustness
```

Configure the repository's `main` branch protection to require `CI / quality` before merging. Remote LLM, FreeCAD, and GPU checks are intentionally in the separate manual/nightly `Integration` workflow and are not dependencies of ordinary CI.
