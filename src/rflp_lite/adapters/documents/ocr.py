"""Lazy OCR adapter boundary."""

from __future__ import annotations

from typing import Any

from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.ports.document_intelligence import OcrPort


class RapidOcrAdapter:
    """Lazy local RapidOCR adapter; model downloads are never implicit here."""

    def __init__(self, engine: Any = None):
        self._engine = engine

    def _load(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from rapidocr import RapidOCR
        except ImportError as exc:
            raise AdapterFailure(
                "OCR is unavailable; install the 'documents' optional dependencies"
            ) from exc
        self._engine = RapidOCR()
        return self._engine

    def extract(
        self, image: Any
    ) -> tuple[tuple[str, tuple[float, float, float, float]], ...]:
        result = self._load()(image)
        if isinstance(result, tuple):
            result = result[0]
        if not result:
            return ()
        values: list[tuple[str, tuple[float, float, float, float]]] = []
        if hasattr(result, "txts") and hasattr(result, "boxes"):
            iterable = zip(result.boxes, result.txts, strict=False)
        else:
            iterable = result
        for item in iterable:
            if isinstance(item, dict):
                text = str(item.get("text", "")).strip()
                box = item.get("box") or item.get("bbox") or ()
            else:
                try:
                    box, text = item[0], item[1]
                except (IndexError, TypeError):
                    continue
                text = str(text).strip()
            if not text:
                continue
            flat = [
                float(point)
                for pair in box
                for point in (pair if isinstance(pair, (list, tuple)) else (pair,))
            ]
            if len(flat) >= 8:
                bbox = (min(flat[0::2]), min(flat[1::2]), max(flat[0::2]), max(flat[1::2]))
            elif len(flat) >= 4:
                bbox = (flat[0], flat[1], flat[2], flat[3])
            else:
                bbox = (0.0, 0.0, 0.0, 0.0)
            values.append((text, bbox))
        return tuple(values)

    def recognize(
        self, image: Any, *, page: int
    ) -> tuple[tuple[str, tuple[float, float, float, float], float], ...]:
        return tuple((text, bbox, 0.8) for text, bbox in self.extract(image))


def ocr_port(value: OcrPort | None = None) -> OcrPort:
    return value or RapidOcrAdapter()
