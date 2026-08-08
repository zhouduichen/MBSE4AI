from __future__ import annotations

import sys
from pathlib import Path

from rflp_lite.adapters.mlflow_tracking import track_run_with_mlflow
from rflp_lite.application.demo import run_demo
from rflp_lite.application.run_catalog import load_run
from rflp_lite.governance.profile import Profile


def test_mlflow_reports_optional_dependency_boundary(tmp_path: Path, monkeypatch):
    monkeypatch.setitem(sys.modules, "mlflow", None)
    record = load_run(tmp_path, run_demo(tmp_path, Profile()).result_hash)

    result = track_run_with_mlflow(record)

    assert result["status"] == "not_configured"
    assert "tracking" in result["install"]


class _Run:
    class Info:
        run_id = "fake-run-id"

    info = Info()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class _FakeMlflow:
    def __init__(self):
        self.params = {}
        self.metrics = {}
        self.tags = {}
        self.artifacts = []

    def set_tracking_uri(self, uri):
        self.uri = uri

    def set_experiment(self, name):
        self.experiment = name

    def start_run(self, run_name):
        self.run_name = run_name
        return _Run()

    def log_params(self, values):
        self.params.update(values)

    def log_metrics(self, values):
        self.metrics.update(values)

    def set_tags(self, values):
        self.tags.update(values)

    def log_artifacts(self, path, artifact_path):
        self.artifacts.append((path, artifact_path))


def test_mlflow_adapter_logs_real_run_contract_to_optional_sdk(tmp_path: Path, monkeypatch):
    fake = _FakeMlflow()
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    record = load_run(tmp_path, run_demo(tmp_path, Profile()).result_hash)

    result = track_run_with_mlflow(record, tracking_uri=tmp_path / "mlruns")

    assert result["status"] == "tracked"
    assert result["run_id"] == "fake-run-id"
    assert fake.params["solver"] == "heuristic"
    assert fake.metrics["claims"] > 0
    assert fake.artifacts[0][1] == "rflp"
