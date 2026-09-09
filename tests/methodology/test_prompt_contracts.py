from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.tasks import task_catalog


def test_request_contains_actual_prompt_version_and_content_hash():
    task = task_catalog()[0]
    request = TaskExecutor(lambda request: None).request(
        task, ContextBuilder().build(ModelGraph("p1"), task), "v2.1"
    )

    assert request.prompt_text.startswith("# Role")
    assert request.prompt_version == "v1"
    assert request.prompt_hash
    assert request.output_contract["prompt_hash"] == request.prompt_hash


def test_prompt_hash_is_content_hash_not_template_id():
    from rflp_lite.domain.canonical import canonical_hash
    from rflp_lite.methodology.registries import PromptRegistry

    task = task_catalog()[0]
    executor = TaskExecutor(lambda request: None, prompt_registry=PromptRegistry({task.prompt_template_id: "# Role\ncustom"}))
    request = executor.request(task, ContextBuilder().build(ModelGraph("p1"), task), "v2.1")

    assert request.prompt_hash == canonical_hash(request.prompt_text)
    assert request.prompt_hash != canonical_hash(task.prompt_template_id)
