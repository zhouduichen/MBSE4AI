from rflp_lite.domain.mbse import Actor, UseCase


def test_mbse_value_objects_are_immutable_records():
    actor = Actor("actor-1", "设计师")
    use_case = UseCase("usecase-1", "导入需求", (actor.id,), ("requirement-1",))
    assert use_case.actor_ids == ("actor-1",)

