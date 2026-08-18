"""Explicit application use cases with narrow dependency bundles."""

from rflp_lite.application.use_cases.requirements_analysis import (
    RequirementsAnalysisDependencies,
    RequirementsAnalysisService,
)
from rflp_lite.application.use_cases.project_analysis import (
    ProjectAnalysisDependencies,
    ProjectAnalysisService,
)

__all__ = [
    "ProjectAnalysisDependencies",
    "ProjectAnalysisService",
    "RequirementsAnalysisDependencies",
    "RequirementsAnalysisService",
]
