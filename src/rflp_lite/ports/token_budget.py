"""Small provider-neutral token estimates for bounded model requests."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence


_CJK = re.compile(r"[\u3400-\u9fff]")
_LATIN = re.compile(r"[A-Za-z0-9_]+")


def estimate_tokens(value: object) -> int:
    """Estimate tokens conservatively without depending on a model tokenizer."""

    text = str(value)
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    latin_items = _LATIN.findall(text)
    latin = len(latin_items)
    punctuation = len(text) - cjk - sum(len(item) for item in latin_items)
    return max(
        1,
        cjk
        + math.ceil(latin * 1.3)
        + math.ceil(max(0, punctuation) / 4),
    )


def estimate_messages(messages: Sequence[Mapping[str, object]]) -> int:
    """Estimate serialized chat input, including a small per-message margin."""

    return sum(
        estimate_tokens(message.get("content", "")) + 4
        for message in messages
    )
