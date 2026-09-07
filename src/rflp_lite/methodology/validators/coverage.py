from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.coverage import evaluate


def validate_coverage(graph: ModelGraph) -> tuple[str, ...]:
    return tuple(gap.code for gap in evaluate(graph).gaps)
