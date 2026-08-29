from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from rflp_lite.application.use_cases.analyze_project import AnalyzeProjectCommand, AnalyzeProjectUseCase
from rflp_lite.application.use_cases.dependencies import (
    AnalyzeProjectDeps,
    GenerateMbseDeps,
    GenerateRflpDeps,
    RecordEvidenceDeps,
    RunProjectTestsDeps,
)
from rflp_lite.application.use_cases.generate_mbse import GenerateMbseCommand, GenerateMbseUseCase
from rflp_lite.application.use_cases.generate_rflp import GenerateRflpCommand, GenerateRflpUseCase
from rflp_lite.application.use_cases.record_evidence import RecordEvidenceCommand, RecordEvidenceUseCase
from rflp_lite.application.use_cases.run_project_tests import RunProjectTestsCommand, RunProjectTestsUseCase


def test_generation_use_cases_only_call_their_narrow_port() -> None:
    state = {"id": "state"}
    rflp = GenerateRflpUseCase(GenerateRflpDeps(SimpleNamespace(), lambda value: {**value, "rflp": True}))
    mbse = GenerateMbseUseCase(GenerateMbseDeps(SimpleNamespace(), lambda value, revision=None: {**value, "mbse": revision or 1}))
    assert rflp.execute(GenerateRflpCommand(state))["rflp"] is True
    assert mbse.execute(GenerateMbseCommand(state, revision=4))["mbse"] == 4


def test_project_and_evidence_use_cases_keep_operations_separate(tmp_path: Path) -> None:
    project = SimpleNamespace(scan=lambda source: (source, {"files_used": 1}))
    analyzed = AnalyzeProjectUseCase(AnalyzeProjectDeps(SimpleNamespace(), project)).execute(
        AnalyzeProjectCommand(tmp_path)
    )
    assert analyzed[1]["files_used"] == 1

    executed = RunProjectTestsUseCase(
        RunProjectTestsDeps(
            SimpleNamespace(),
            SimpleNamespace(run=lambda *args, **kwargs: ("runner-result",)),
        )
    ).execute(RunProjectTestsCommand(tmp_path))
    assert executed == ("runner-result",)

    recorded = RecordEvidenceUseCase(
        RecordEvidenceDeps(SimpleNamespace(), lambda value, evidence: {"state": value, "evidence": evidence})
    ).execute(RecordEvidenceCommand({"id": "state"}, ()))
    assert recorded["evidence"] == ()
