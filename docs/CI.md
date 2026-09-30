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

The repository's `main` branch protection is configured to require `CI / quality` before merging, require a pull request with one approval, dismiss stale reviews, enforce the rule for administrators, and reject force-pushes/deletion. Remote LLM, FreeCAD, and GPU checks are intentionally in the separate manual/nightly `Integration` workflow and are not dependencies of ordinary CI.
