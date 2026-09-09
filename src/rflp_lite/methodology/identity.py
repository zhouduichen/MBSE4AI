"""Deterministic identity for reproducible methodology runs."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from rflp_lite.domain.canonical import canonical_hash


@dataclass(frozen=True, slots=True)
class RunIdentity:
    project_id: str
    model_profile: str
    methodology_version: str
    task_spec_hash: str
    prompt_hash: str
    context_hash: str
    input_hash: str
    run_id: str

    @classmethod
    def create(
        cls,
        project_id: str,
        *,
        model_profile: str,
        methodology_version: str,
        task_spec_hash: str,
        prompt_hash: str,
        context_hash: str,
        input_hash: str,
        force_new: bool = False,
    ) -> "RunIdentity":
        seed = (project_id, model_profile, methodology_version, task_spec_hash, prompt_hash, context_hash, input_hash)
        suffix = uuid4().hex[:16] if force_new else canonical_hash(seed)[:16]
        return cls(project_id, model_profile, methodology_version, task_spec_hash, prompt_hash, context_hash, input_hash, f"run-{suffix}")
