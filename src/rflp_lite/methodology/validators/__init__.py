"""Composable deterministic validators for TaskSpec output."""

from rflp_lite.methodology.validators import evidence, identity, patch_policy, reference, schema, semantic
from rflp_lite.methodology.validators.coverage import validate_coverage
from rflp_lite.methodology.validators.lifecycle import validate_lifecycle
from rflp_lite.methodology.validators.operational import validate_operational
from rflp_lite.methodology.validators.rflp import validate_rflp
from rflp_lite.methodology.validators.verification import validate_verification



def default_validators():
    return {
        "schema": schema.validate,
        "identity": identity.validate,
        "reference": reference.validate,
        "evidence": evidence.validate,
        "semantic": semantic.validate,
        "patch_policy": patch_policy.validate,
    }


__all__ = [
    "default_validators", "validate_coverage", "validate_lifecycle", "validate_operational",
    "validate_rflp", "validate_verification",
]
