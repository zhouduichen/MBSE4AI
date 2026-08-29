"""Application use cases with explicit, narrow dependency bundles."""

from rflp_lite.application.use_cases.dependencies import (
    AnalyzeProjectDeps,
    GenerateMbseDeps,
    GenerateRflpDeps,
    RecordEvidenceDeps,
    ReanalyzeRequirementsDeps,
    ReviewRequirementDeps,
    RunEnrichmentBlockDeps,
    RunProjectTestsDeps,
)
from rflp_lite.application.use_cases.analyze_project import (
    AnalyzeProjectCommand,
    AnalyzeProjectUseCase,
)
from rflp_lite.application.use_cases.generate_mbse import (
    GenerateMbseCommand,
    GenerateMbseUseCase,
)
from rflp_lite.application.use_cases.generate_rflp import (
    GenerateRflpCommand,
    GenerateRflpUseCase,
)
from rflp_lite.application.use_cases.project_analysis import (
    ProjectAnalysisDependencies,
    ProjectAnalysisService,
)
from rflp_lite.application.use_cases.record_evidence import (
    RecordEvidenceCommand,
    RecordEvidenceUseCase,
)
from rflp_lite.application.use_cases.reanalyze_requirements import (
    ReanalyzeRequirementsCommand,
    ReanalyzeRequirementsDependencies,
    ReanalyzeRequirementsUseCase,
)
from rflp_lite.application.use_cases.requirements_analysis import (
    RequirementsAnalysisDependencies,
    RequirementsAnalysisService,
)
from rflp_lite.application.use_cases.run_project_tests import (
    RunProjectTestsCommand,
    RunProjectTestsUseCase,
)

__all__ = [
    "AnalyzeProjectCommand",
    "AnalyzeProjectDeps",
    "AnalyzeProjectUseCase",
    "GenerateMbseCommand",
    "GenerateMbseDeps",
    "GenerateMbseUseCase",
    "GenerateRflpCommand",
    "GenerateRflpDeps",
    "GenerateRflpUseCase",
    "ProjectAnalysisDependencies",
    "ProjectAnalysisService",
    "RecordEvidenceCommand",
    "RecordEvidenceDeps",
    "RecordEvidenceUseCase",
    "ReanalyzeRequirementsCommand",
    "ReanalyzeRequirementsDeps",
    "ReanalyzeRequirementsDependencies",
    "ReanalyzeRequirementsUseCase",
    "RequirementsAnalysisDependencies",
    "RequirementsAnalysisService",
    "ReviewRequirementDeps",
    "RunEnrichmentBlockDeps",
    "RunProjectTestsCommand",
    "RunProjectTestsDeps",
    "RunProjectTestsUseCase",
]
