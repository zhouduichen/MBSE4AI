"""Read-only application query views.

Query views deliberately expose immutable, template/API-friendly data rather
than the mutable Workbench aggregate.
"""

from rflp_lite.application.queries.mbse import MBSEView, mbse_view
from rflp_lite.application.queries.requirements import (
    RequirementItemView,
    RequirementsPageView,
    requirements_page_view,
)
from rflp_lite.application.queries.workspace import WorkspaceView, workspace_view

__all__ = [
    "MBSEView",
    "RequirementItemView",
    "RequirementsPageView",
    "WorkspaceView",
    "mbse_view",
    "requirements_page_view",
    "workspace_view",
]
