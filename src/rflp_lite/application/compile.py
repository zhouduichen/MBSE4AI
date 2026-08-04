from __future__ import annotations

from rflp_lite.adapters.readers import RuleClaimExtractor
from rflp_lite.domain.errors import InvariantViolation
from rflp_lite.domain.models import Claim, TextSpan


def compile_claims(spans: tuple[TextSpan, ...]) -> tuple[Claim, ...]:
    claims = RuleClaimExtractor().extract(spans)
    if not claims:
        raise InvariantViolation("no normative claims were extracted")
    if len({claim.id for claim in claims}) != len(claims):
        raise InvariantViolation("claim extraction produced duplicate ids")
    return claims

