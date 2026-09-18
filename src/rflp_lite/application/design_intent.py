"""Natural-language design-intent extraction with remote-model support."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
from time import time
from typing import Any

import jsonschema

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.detail_design import ClarificationQuestion, DesignIntent
from rflp_lite.domain.errors import AdapterFailure, ContractViolation
from rflp_lite.ports.generative_model import GenerationRequest, GenerativeModel, add_simplified_chinese_instruction


_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "resources" / "schemas" / "design_intent_draft.v1.json"
_PROMPT_PATH = Path(__file__).resolve().parents[1] / "resources" / "prompts" / "design_intent.v1.md"
_NUMBER = r"([0-9]+(?:\.[0-9]+)?)\s*(mm|毫米|cm|厘米|m|米)"
_DIMENSIONS = {
    "length_mm": (r"(?:长度|长)\s*" + _NUMBER, "length"),
    "width_mm": (r"(?:宽度|宽)\s*" + _NUMBER, "width"),
    "height_mm": (r"(?:高度|高|厚度|厚)\s*" + _NUMBER, "height"),
    "diameter_mm": (r"(?:直径|孔径)\s*" + _NUMBER, "diameter"),
    "radius_mm": (r"半径\s*" + _NUMBER, "radius"),
}


def _schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _to_mm(value: float, unit: str) -> float:
    return value * {"mm": 1.0, "毫米": 1.0, "cm": 10.0, "厘米": 10.0, "m": 1000.0, "米": 1000.0}[unit]


def _parameter_matches(text: str) -> list[dict[str, Any]]:
    result = []
    for name, (pattern, _label) in _DIMENSIONS.items():
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            result.append({"name": name, "value": _to_mm(float(match.group(1)), match.group(2)), "unit": "mm", "source": "explicit"})
    return result


def _target(text: str) -> tuple[str, str]:
    known = (("支架", "bracket"), ("底座", "base"), ("壳体", "housing"), ("连接件", "connector"), ("轴", "shaft"), ("齿轮", "gear"))
    for label, kind in known:
        if label in text:
            return kind, label
    return "part", "待确认零件"


def _fallback(text: str) -> dict[str, Any]:
    target_kind, target_name = _target(text)
    parameters = _parameter_matches(text)
    material_match = re.search(r"(铝合金|铝|钢|不锈钢|钛合金|碳纤维|塑料)", text)
    material = material_match.group(1) if material_match else ""
    questions: list[dict[str, Any]] = []
    names = {item["name"] for item in parameters}
    if target_name == "待确认零件":
        questions.append({"question": "请确认需要生成的目标零部件。", "ambiguity": "目标零件未唯一确定", "options": ["支架", "底座", "壳体", "其他"], "recommendation": "支架", "rationale": "自然语言中未发现明确零件名。", "severity": "high"})
    if not {"length_mm", "width_mm", "height_mm"} <= names:
        questions.append({"question": "请补充零件的长、宽和高度/厚度，或确认由设计规则推荐。", "ambiguity": "基础包络尺寸不完整", "options": ["补充尺寸", "采用推荐尺寸"], "recommendation": "补充尺寸", "rationale": "没有完整尺寸不能安全生成参数化实体。", "severity": "high"})
    if "孔" in text and "diameter_mm" not in names:
        questions.append({"question": "请确认孔径和孔的位置基准。", "ambiguity": "孔特征缺少尺寸或定位基准", "options": ["补充孔信息", "暂不生成孔"], "recommendation": "补充孔信息", "rationale": "孔特征会影响加工和装配。", "severity": "high"})
    recommendations = []
    if not material:
        recommendations.append("未指定材料；支架类零件可优先比较铝合金与钢的强度、质量和可制造性。")
    return {
        "schema_version": "design-intent-draft.v1",
        "statement": text,
        "target_kind": target_kind,
        "target_name": target_name,
        "parameters": parameters,
        "material": material,
        "connections": [],
        "clarifications": questions,
        "recommendations": recommendations,
        "diagnostics": ["使用确定性意图解析；未启动本地模型。"],
    }


def _validated(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(payload)
    jsonschema.validate(value, _schema())
    return value


def _intent(payload: Mapping[str, Any], project_id: str, provenance: str) -> DesignIntent:
    params = tuple(
        (str(item["name"]), float(item["value"]))
        for item in payload.get("parameters", ())
        if isinstance(item, Mapping) and item.get("name") and isinstance(item.get("value"), (int, float))
    )
    source = tuple(str(item) for item in payload.get("source_requirement_ids", ()) if str(item).strip())
    identity = (
        project_id,
        payload["statement"],
        payload["target_kind"],
        payload["target_name"],
        payload.get("material", ""),
        params,
        source,
    )
    return DesignIntent(
        id=f"intent-{canonical_hash(identity)[:16]}",
        statement=str(payload["statement"]), target_kind=str(payload["target_kind"]),
        target_name=str(payload["target_name"]), parameters=params,
        material=str(payload.get("material", "")),
        connection_requirements=tuple(str(item) for item in payload.get("connections", ())),
        source_requirement_ids=source, confidence=0.72 if provenance == "rule" else 0.85,
        provenance=provenance,
    )


@dataclass(frozen=True, slots=True)
class DesignIntentDraft:
    draft_id: str
    project_id: str
    input_hash: str
    status: str
    payload: Mapping[str, Any]
    intent: DesignIntent
    clarifications: tuple[ClarificationQuestion, ...]
    provider_id: str = ""
    model_id: str = ""
    diagnostics: tuple[str, ...] = ()
    created_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        clarifications = [
            {
                "id": item.id,
                "question": item.question,
                "ambiguity": item.ambiguity,
                "options": list(item.options),
                "recommendation": item.recommendation,
                "rationale": item.rationale,
                "severity": item.severity,
                "status": item.status,
            }
            for item in self.clarifications
        ]
        return {
            **dict(self.payload),
            "draft_id": self.draft_id,
            "project_id": self.project_id,
            "input_hash": self.input_hash,
            "status": self.status,
            "intent": self.intent.as_dict(),
            "clarifications": clarifications,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "diagnostics": list(self.diagnostics),
            "created_at": self.created_at,
        }


class DesignIntentService:
    """Create reviewable intent drafts; never mutates a CAD model."""

    def __init__(self, model: GenerativeModel | None = None, *, provider_id: str = "", model_id: str = "") -> None:
        self.model = model
        self.provider_id = provider_id
        self.model_id = model_id

    def create_draft(self, project_id: str, text: str, *, source_requirement_ids: tuple[str, ...] = ()) -> DesignIntentDraft:
        clean = " ".join(str(text).split()).strip()
        if not clean:
            raise ContractViolation("design intent text is required")
        input_hash = canonical_hash({"project_id": project_id, "text": clean, "source_requirement_ids": source_requirement_ids})
        payload, provenance, diagnostics = self._generate(clean, input_hash)
        payload["source_requirement_ids"] = list(source_requirement_ids)
        try:
            payload = _validated(payload)
        except jsonschema.ValidationError as exc:
            payload = _fallback(clean)
            payload["source_requirement_ids"] = list(source_requirement_ids)
            diagnostics = (*diagnostics, f"structured design intent rejected: {exc.message}")
            provenance = "rule"
        intent = _intent(payload, project_id, provenance)
        questions = tuple(
            ClarificationQuestion(
                id=f"clarification-{canonical_hash((intent.id, item['question']))[:12]}",
                question=str(item["question"]), ambiguity=str(item["ambiguity"]),
                options=tuple(str(option) for option in item.get("options", ())),
                recommendation=str(item.get("recommendation", "")), rationale=str(item.get("rationale", "")),
                severity=str(item.get("severity", "high")),
            )
            for item in payload.get("clarifications", ()) if isinstance(item, Mapping)
        )
        status = "needs_clarification" if any(item.severity == "high" for item in questions) else "ready"
        draft_id = f"design-draft-{canonical_hash((project_id, input_hash, payload))[:16]}"
        return DesignIntentDraft(draft_id, project_id, input_hash, status, payload, intent, questions, self.provider_id, self.model_id, tuple(diagnostics), time())

    def _generate(self, text: str, input_hash: str) -> tuple[dict[str, Any], str, tuple[str, ...]]:
        if self.model is None:
            return _fallback(text), "rule", ()
        request = GenerationRequest(
            "design.intent", add_simplified_chinese_instruction(_prompt()),
            {"text": text, "input_hash": input_hash}, _schema(), 1800,
        )
        try:
            response = self.model.complete_json(request)
            return dict(response.payload), "llm", ()
        except (AdapterFailure, ValueError, TypeError, json.JSONDecodeError) as exc:
            return _fallback(text), "rule", (f"remote design intent unavailable: {type(exc).__name__}: {exc}",)


__all__ = ["DesignIntentDraft", "DesignIntentService"]
