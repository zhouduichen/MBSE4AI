"""Deterministic layout renderers.

The renderer is deliberately a tiny, declaration-selected adapter.  A domain
pack may select one of the explicitly allow-listed renderer names, but it
cannot provide executable rendering code.  The fixed-wing renderer emits a
stable SVG suitable for a candidate card or download.
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape

from rflp_lite.domain.concept_design import LayoutCandidate
from rflp_lite.domain.errors import ContractViolation


def _contract(message: str) -> ContractViolation:
    return ContractViolation(message)


def _values(candidate: LayoutCandidate | Mapping[str, object]) -> dict[str, object]:
    if isinstance(candidate, LayoutCandidate):
        return dict(candidate.parameters)
    if isinstance(candidate, Mapping):
        values = candidate.get("parameters", candidate)
        if not isinstance(values, Mapping):
            raise _contract("candidate parameters must be an object")
        return dict(values)
    raise _contract("candidate must be a LayoutCandidate or mapping")


def _number(values: Mapping[str, object], name: str) -> float:
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _contract(f"candidate parameter {name!r} must be numeric")
    result = float(value)
    if result <= 0:
        raise _contract(f"candidate parameter {name!r} must be positive")
    return result


def _candidate_id(candidate: LayoutCandidate | Mapping[str, object]) -> str:
    if isinstance(candidate, LayoutCandidate):
        return candidate.id
    if isinstance(candidate, Mapping):
        identifier = candidate.get("id", "candidate")
        return str(identifier)
    return "candidate"


def _render_fixed_wing(pack: Mapping[str, object], candidate: LayoutCandidate | Mapping[str, object]) -> str:
    values = _values(candidate)
    span = _number(values, "span_m")
    area = _number(values, "wing_area_m2")
    fuselage_length = _number(values, "fuselage_length_m")
    chord = area / span
    identifier = escape(_candidate_id(candidate), quote=True)
    display_name = escape(str(pack.get("display_name", pack.get("id", "Fixed-wing"))), quote=True)

    # Coordinates are intentionally fixed.  The dimensions are scaled into
    # bounded panels independently, keeping output readable for every valid
    # pack range and byte-identical for repeated input.
    top_x = 500.0
    top_y = 145.0
    top_scale = min(360.0 / span, 210.0 / max(chord, 0.001))
    half_span = span * top_scale / 2.0
    half_chord = chord * top_scale / 2.0
    fuselage_top = min(640.0, max(120.0, fuselage_length * top_scale))
    top_left = top_x - fuselage_top / 2.0
    top_right = top_x + fuselage_top / 2.0

    side_scale = min(640.0 / fuselage_length, 70.0 / max(chord, 0.001))
    side_length = fuselage_length * side_scale
    side_chord = chord * side_scale
    side_left = 500.0 - side_length / 2.0
    side_right = 500.0 + side_length / 2.0
    side_y = 385.0

    fmt = lambda number: f"{number:.6f}"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 520" '
        f'role="img" aria-labelledby="title-{identifier}">'
        f'<title id="title-{identifier}">{display_name} {identifier}</title>'
        '<rect width="1000" height="520" fill="#fff"/>'
        '<g fill="none" stroke="#263238" stroke-width="2">'
        '<rect x="20" y="20" width="960" height="220" rx="8" stroke="#cfd8dc"/>'
        '<rect x="20" y="270" width="960" height="220" rx="8" stroke="#cfd8dc"/>'
        f'<path d="M {fmt(top_left)} {fmt(top_y)} L {fmt(top_right)} {fmt(top_y)} '
        f'L {fmt(top_right)} {fmt(top_y + 8)} L {fmt(top_left)} {fmt(top_y + 8)} Z" fill="#eceff1"/>'
        f'<path d="M {fmt(top_x - half_span)} {fmt(top_y)} '
        f'L {fmt(top_x - half_chord)} {fmt(top_y - half_chord)} '
        f'L {fmt(top_x + half_chord)} {fmt(top_y - half_chord)} '
        f'L {fmt(top_x + half_span)} {fmt(top_y)} '
        f'L {fmt(top_x + half_chord)} {fmt(top_y + half_chord)} '
        f'L {fmt(top_x - half_chord)} {fmt(top_y + half_chord)} Z" fill="#90caf9"/>'
        f'<path d="M {fmt(top_x - half_span * 0.62)} {fmt(top_y)} '
        f'L {fmt(top_x - half_chord * 0.8)} {fmt(top_y - half_chord * 0.65)} '
        f'L {fmt(top_x + half_chord * 0.8)} {fmt(top_y - half_chord * 0.65)} '
        f'L {fmt(top_x + half_span * 0.62)} {fmt(top_y)} '
        f'L {fmt(top_x + half_chord * 0.8)} {fmt(top_y + half_chord * 0.65)} '
        f'L {fmt(top_x - half_chord * 0.8)} {fmt(top_y + half_chord * 0.65)} Z" fill="#64b5f6"/>'
        f'<path d="M {fmt(side_left)} {fmt(side_y)} '
        f'L {fmt(side_right)} {fmt(side_y)} '
        f'L {fmt(side_right - side_chord * 0.35)} {fmt(side_y - side_chord * 0.35)} '
        f'L {fmt(side_left + side_chord * 0.35)} {fmt(side_y - side_chord * 0.35)} Z" fill="#eceff1"/>'
        f'<path d="M {fmt(500.0 - side_length * 0.32)} {fmt(side_y)} '
        f'L {fmt(500.0 - side_chord * 0.5)} {fmt(side_y - side_chord)} '
        f'L {fmt(500.0 + side_chord * 0.5)} {fmt(side_y - side_chord)} '
        f'L {fmt(500.0 + side_length * 0.32)} {fmt(side_y)} Z" fill="#90caf9"/>'
        '</g>'
        '<g font-family="sans-serif" font-size="16" fill="#263238">'
        '<text x="40" y="52">Top view</text><text x="40" y="302">Side view</text>'
        f'<text x="40" y="465">span={fmt(span)} m · area={fmt(area)} m² · '
        f'fuselage={fmt(fuselage_length)} m · chord={fmt(chord)} m</text>'
        '</g></svg>'
    )


def render_layout_svg(
    pack: Mapping[str, object], candidate: LayoutCandidate | Mapping[str, object]
) -> str:
    """Render ``candidate`` using the pack's allow-listed renderer name."""

    if not isinstance(pack, Mapping):
        raise _contract("domain pack must be an object")
    generation = pack.get("generation", {})
    if not isinstance(generation, Mapping):
        raise _contract("domain pack generation must be an object")
    renderer = generation.get("renderer")
    if renderer != "fixed-wing-svg-v1":
        raise _contract(f"unknown layout renderer: {renderer}")
    return _render_fixed_wing(pack, candidate)


__all__ = ["render_layout_svg"]
