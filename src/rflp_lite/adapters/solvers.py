from __future__ import annotations

from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.domain.models import Candidate, ModelElement
from rflp_lite.governance.profile import Profile


_PATTERNS = (
    (
        "candidate-event-split",
        "event-split",
        ("ContentStore", "RestoreService", "AuditLog", "EventBus"),
        78,
        ("strong isolation", "higher operational complexity"),
    ),
    (
        "candidate-modular-monolith",
        "modular-monolith",
        ("VersioningModule", "AuditModule", "SQLiteStore"),
        88,
        ("simple local deployment", "single transaction boundary"),
    ),
    (
        "candidate-ports-adapters",
        "ports-adapters",
        ("ApplicationCore", "RepositoryPort", "SQLiteAdapter", "AuditAdapter"),
        94,
        ("replaceable adapters", "explicit ownership"),
    ),
)


def _candidate(pattern: tuple[str, str, tuple[str, ...], int, tuple[str, ...]]) -> Candidate:
    return Candidate(
        id=pattern[0],
        pattern=pattern[1],
        components=pattern[2],
        score=pattern[3],
        rationale=pattern[4],
    )


class HeuristicSolver:
    def solve(
        self, elements: tuple[ModelElement, ...], profile: Profile
    ) -> tuple[Candidate, ...]:
        if not any(element.layer == "L" for element in elements):
            raise AdapterFailure("heuristic solver requires logical elements")
        selected = sorted(_PATTERNS, key=lambda item: (-item[3], item[0]))[
            : profile.candidate_limit
        ]
        return tuple(sorted((_candidate(item) for item in selected), key=lambda item: item.id))


class CpSatSolver:
    def solve(
        self, elements: tuple[ModelElement, ...], profile: Profile
    ) -> tuple[Candidate, ...]:
        if not any(element.layer == "L" for element in elements):
            raise AdapterFailure("CP-SAT solver requires logical elements")
        try:
            from ortools.sat.python import cp_model
        except ImportError as exc:
            raise AdapterFailure("OR-Tools opt extra is required for CP-SAT") from exc

        model = cp_model.CpModel()
        selected = [model.new_bool_var(f"pattern_{index}") for index in range(len(_PATTERNS))]
        model.add(sum(selected) == 1)
        model.maximize(sum(variable * _PATTERNS[index][3] for index, variable in enumerate(selected)))
        solver = cp_model.CpSolver()
        solver.parameters.random_seed = profile.seed
        solver.parameters.num_search_workers = 1
        solver.parameters.max_time_in_seconds = float(profile.timeout_seconds)
        results: list[Candidate] = []
        for _ in range(profile.candidate_limit):
            status = solver.solve(model)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                break
            chosen = next(index for index, variable in enumerate(selected) if solver.value(variable))
            results.append(_candidate(_PATTERNS[chosen]))
            model.add(selected[chosen] == 0)
        if len(results) < 2:
            raise AdapterFailure("CP-SAT returned fewer than two candidates")
        return tuple(sorted(results, key=lambda item: item.id))


CpSatSolverAdapter = CpSatSolver

