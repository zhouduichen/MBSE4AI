"""Deterministic matrix views for allocation and traceability."""

from __future__ import annotations

from html import escape

from rflp_lite.application.mbse_views import semantic_model_for_view, view_definition
from rflp_lite.domain.errors import ContractViolation


def matrix_view_data(model: object, view_id: str) -> dict[str, object]:
    definition = view_definition(view_id)
    if definition.compiler != "matrix":
        raise ContractViolation(f"view {definition.id} is not a matrix view")
    semantic = semantic_model_for_view(model)
    sections = semantic.get("sections", {})
    if not isinstance(sections, dict):
        sections = {}
    functional = sections.get("functional", {}) if isinstance(sections.get("functional"), dict) else {}
    logical = sections.get("logical", {}) if isinstance(sections.get("logical"), dict) else {}
    physical = sections.get("physical", {}) if isinstance(sections.get("physical"), dict) else {}
    technical = sections.get("technical_requirements", [])
    entity_index: dict[str, dict[str, object]] = {}
    for section in sections.values():
        values = section if isinstance(section, list) else [item for items in section.values() if isinstance(items, list) for item in items] if isinstance(section, dict) else []
        for item in values:
            if isinstance(item, dict) and item.get("id"):
                entity_index[str(item["id"])] = item
    relations = [item for item in semantic.get("relations", ()) if isinstance(item, dict)]
    if definition.id == "allocation_matrix":
        row_ids = [str(item.get("id")) for item in functional.get("functions", ()) if isinstance(item, dict)]
        col_ids = [str(item.get("id")) for item in logical.get("components", ()) if isinstance(item, dict)]
        col_ids.extend(str(item.get("id")) for item in physical.get("components", ()) if isinstance(item, dict))
        allowed = {"allocatedTo", "realizedBy"}
    else:
        row_ids = [str(item.get("id")) for item in functional.get("requirements", ()) if isinstance(item, dict)]
        row_ids.extend(str(item.get("id")) for item in technical if isinstance(item, dict))
        col_ids = sorted(
            {
                str(item.get("target_id"))
                for item in relations
                if item.get("target_id") and str(item.get("target_id")) in entity_index
            }
        )
        allowed = {"derivedFrom", "satisfiedBy", "refines", "allocatedTo", "realizedBy", "verifiedBy"}
    row_ids = list(dict.fromkeys(row_ids))
    col_ids = list(dict.fromkeys(col_ids))
    cells: dict[tuple[str, str], list[str]] = {}
    for relation in relations:
        source_id = str(relation.get("source_id", ""))
        target_id = str(relation.get("target_id", ""))
        kind = str(relation.get("kind", ""))
        if kind not in allowed:
            continue
        if source_id in row_ids and target_id in col_ids:
            cells.setdefault((source_id, target_id), []).append(kind)
        if definition.id == "traceability_matrix" and target_id in row_ids and source_id in col_ids:
            cells.setdefault((target_id, source_id), []).append(kind)
    return {
        "view_id": definition.id,
        "rows": [entity_index[item_id] for item_id in row_ids if item_id in entity_index],
        "columns": [entity_index[item_id] for item_id in col_ids if item_id in entity_index],
        "cells": {f"{row}|{col}": tuple(sorted(values)) for (row, col), values in cells.items()},
    }


def render_matrix_view(model: object, view_id: str, options: dict[str, object] | None = None) -> str:
    del options
    data = matrix_view_data(model, view_id)
    rows = list(data["rows"])
    columns = list(data["columns"])
    cells = data["cells"]
    cell_width = 150
    row_height = 44
    left = 230
    top = 90
    width = max(720, left + cell_width * max(1, len(columns)) + 40)
    height = max(180, top + row_height * max(1, len(rows)) + 80)
    title = "分配矩阵" if view_id == "allocation_matrix" else "追溯矩阵"
    parts = [
        f'<svg class="mbse-matrix-svg" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}" xmlns="http://www.w3.org/2000/svg">',
        f'<rect width="{width}" height="{height}" fill="#ffffff" stroke="#cbd5e1"/>',
        f'<text x="24" y="34" font-family="Arial" font-size="18" font-weight="700" fill="#0f172a">{escape(title)}</text>',
        f'<text x="24" y="58" font-family="Arial" font-size="11" fill="#64748b">关系单元格显示关系类型，空白表示当前没有直接追溯</text>',
    ]
    for index, column in enumerate(columns):
        x = left + index * cell_width
        parts.append(f'<rect x="{x}" y="{top - 32}" width="{cell_width}" height="32" fill="#eff6ff" stroke="#cbd5e1"/>')
        parts.append(f'<text x="{x + 8}" y="{top - 12}" font-family="Arial" font-size="10" fill="#1e3a8a">{escape(str(column.get("name", column.get("id", "")))[:20])}</text>')
    for row_index, row in enumerate(rows):
        y = top + row_index * row_height
        parts.append(f'<rect x="0" y="{y}" width="{left}" height="{row_height}" fill="#f8fafc" stroke="#cbd5e1"/>')
        parts.append(f'<text x="12" y="{y + 27}" font-family="Arial" font-size="11" fill="#0f172a">{escape(str(row.get("name", row.get("id", "")))[:30])}</text>')
        for column_index, column in enumerate(columns):
            x = left + column_index * cell_width
            key = f'{row.get("id")}|{column.get("id")}'
            values = cells.get(key, ())
            fill = "#dbeafe" if values else "#ffffff"
            parts.append(f'<rect x="{x}" y="{y}" width="{cell_width}" height="{row_height}" fill="{fill}" stroke="#cbd5e1"/>')
            if values:
                parts.append(f'<text x="{x + 10}" y="{y + 26}" font-family="Arial" font-size="10" font-weight="700" fill="#1d4ed8">{escape(str(values[0]))}</text>')
    parts.append("</svg>")
    return "".join(parts)
