from __future__ import annotations

import os
from pathlib import Path

from rflp_lite.ports.tracking import TrackingRecord


def _metrics(record: TrackingRecord) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for filename, key in (
        ("claims.json", "claims"),
        ("candidates.json", "candidates"),
        ("task-contracts.json", "tasks"),
        ("evidence.json", "evidence"),
    ):
        value = record.outputs.get(filename)
        if isinstance(value, list):
            metrics[key] = float(len(value))
    simulation = record.outputs.get("simulation.json")
    if isinstance(simulation, dict):
        metrics["simulation_passed"] = 1.0 if simulation.get("passed") else 0.0
        metrics["simulation_events"] = float(len(simulation.get("events", ())))
    return metrics


def track_run_with_mlflow(
    record: TrackingRecord,
    *,
    tracking_uri: str | Path | None = None,
    experiment_name: str = "rflp-lite",
) -> dict[str, object]:
    """Log one local RFLP run to MLflow when the optional SDK is installed."""
    try:
        import mlflow
    except ImportError:
        return {
            "status": "not_configured",
            "reason": "mlflow optional dependency is not installed",
            "install": "pip install -e '.[tracking]'",
        }

    uri = str(tracking_uri or (record.run_dir.parent.parent / "mlruns"))
    try:
        if "://" not in uri or uri.startswith("file:"):
            # MLflow 3.x protects the legacy local file store by default. The
            # adapter intentionally supports a self-contained local directory.
            os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(experiment_name)
        with mlflow.start_run(run_name=record.result_hash[:12]) as run:
            profile = record.manifest.get("profile", {})
            if isinstance(profile, dict):
                mlflow.log_params({str(key): str(value) for key, value in profile.items()})
            mlflow.log_params({"result_hash": record.result_hash})
            mlflow.log_metrics(_metrics(record))
            mlflow.set_tags(
                {
                    "rflp_format": "rflp-lite-run",
                    "status": str(record.manifest.get("status", "unknown")),
                    "result_hash": record.result_hash,
                }
            )
            mlflow.log_artifacts(str(record.run_dir), artifact_path="rflp")
            return {
                "status": "tracked",
                "run_id": run.info.run_id,
                "experiment_name": experiment_name,
                "tracking_uri": uri,
                "metrics": _metrics(record),
            }
    except Exception as exc:
        return {
            "status": "failed",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "tracking_uri": uri,
            "experiment_name": experiment_name,
        }
