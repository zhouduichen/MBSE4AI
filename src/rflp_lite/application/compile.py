from __future__ import annotations

from rflp_lite.application.dependencies import ApplicationDependencies, configured_dependencies
from rflp_lite.domain.errors import InvariantViolation
from rflp_lite.domain.models import Claim, TextSpan


def compile_claims(
    spans: tuple[TextSpan, ...],
    *,
    dependencies: ApplicationDependencies | None = None,
) -> tuple[Claim, ...]:
    deps = configured_dependencies(dependencies)
    claims = deps.claim_extractor_factory().extract(spans)
    if not claims:
        raise InvariantViolation("no normative claims were extracted")
    if len({claim.id for claim in claims}) != len(claims):
        raise InvariantViolation("claim extraction produced duplicate ids")
    return claims
