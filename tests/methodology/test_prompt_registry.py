import pytest

from rflp_lite.domain.errors import ContractViolation
from rflp_lite.methodology.registries import PromptRegistry
from rflp_lite.methodology.tasks import task_catalog


REQUIRED_HEADINGS = (
    "# Role", "# Goal", "# Inputs", "# MBSE Method", "# Required Coverage",
    "# Semantic Constraints", "# Evidence Rules", "# Relation Rules",
    "# Forbidden Behavior", "# Output Guidance", "# Self-check Before Emitting Patch",
)


def test_all_task_specs_resolve_to_nonempty_methodology_prompts():
    registry = PromptRegistry()

    prompts = [registry.resolve(task.prompt_template_id) for task in task_catalog()]

    assert len(prompts) == 23
    assert all(prompt.version == "v1" and prompt.prompt_hash for prompt in prompts)
    assert all(all(heading in prompt.text for heading in REQUIRED_HEADINGS) for prompt in prompts)


def test_missing_prompt_fails_fast_instead_of_using_id_as_prompt():
    with pytest.raises(ContractViolation, match="missing|registered"):
        PromptRegistry().resolve("operational.does_not_exist")


def test_empty_registered_prompt_fails_fast():
    with pytest.raises(ValueError, match="required"):
        PromptRegistry({"task": "   "})


def test_semantically_different_tasks_have_different_content_hashes():
    registry = PromptRegistry()

    stakeholder = registry.resolve("operational.stakeholder_analysis")
    logical = registry.resolve("logical_physical.logical_analysis")

    assert stakeholder.prompt_hash != logical.prompt_hash
    assert "stakeholder" in stakeholder.text
    assert "logical" in logical.text


def test_stakeholder_requirement_prompt_keeps_traceability_out_of_payload():
    prompt = PromptRegistry().resolve("operational.stakeholder_requirements")

    assert "payload" in prompt.text
    assert "concern_ids" in prompt.text
    assert "canonical entity id" in prompt.text


def test_vertical_prompts_define_reanalysis_reuse_and_protection():
    registry = PromptRegistry()

    for template_id in (
        "vertical.functional",
        "vertical.logical",
        "vertical.physical",
        "vertical.verification_validation",
    ):
        prompt = registry.resolve(template_id)
        assert "updates" in prompt.text
        assert "canonical id" in prompt.text
        assert "锁定" in prompt.text
        assert "人工修改" in prompt.text


def test_vertical_prompts_expose_typed_flow_and_closure_evidence():
    registry = PromptRegistry()

    functional = registry.resolve("vertical.functional")
    assurance = registry.resolve("vertical.verification_validation")

    assert "source_function_ids" in functional.text
    assert "target_function_ids" in functional.text
    assert "functional_behavior_ids" in functional.text
    assert "feasibility_review" in assurance.text
    assert "cross_analysis_status" in assurance.text


def test_registered_template_text_change_changes_prompt_hash():
    first = PromptRegistry({"custom": "first"}).resolve("custom")
    second = PromptRegistry({"custom": "second"}).resolve("custom")

    assert first.prompt_hash != second.prompt_hash
