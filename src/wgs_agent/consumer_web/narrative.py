"""Rule-first consumer narrative with an optional, heavily validated LLM polish.

The platform report model configuration is not persisted with the report, so the
builder defaults to deterministic rules.  ``polish`` is a hook for an already
configured report model: any output containing a number that is not already
displayed in the section is rejected.
"""

from __future__ import annotations

import os
import re
from typing import Iterable

FORBIDDEN = {
    "未提供", "未启用", "暂无法判断", "已记录", "本节", "如图所示",
    "综上所述", "值得注意的是", "【", "】",
}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d,]*(?:\.\d+)?%?", text))


def reject_reason(text: str, allowed: Iterable[str]) -> str | None:
    if not isinstance(text, str):
        return "not_text"
    clean = text.strip()
    if not 8 <= len(clean) <= 120:
        return "length"
    if any(word in clean for word in FORBIDDEN):
        return "forbidden"
    if re.search(r"[A-Za-z_\u4e00-\u9fff]*[A-Za-z_]", clean):
        return "latin_or_technical"
    if re.search(r"异常|患病概率|导致|引起|造成|治疗|用药|益生菌|补充剂|有益菌|有害菌", clean):
        return "medical_overreach"
    sentences = [piece for piece in re.split(r"[。！？]", clean) if piece.strip()]
    if len(sentences) > 2:
        return "too_many_sentences"
    allowed_numbers = set()
    for value in allowed:
        allowed_numbers.update(_numbers(str(value)))
    if any(number not in allowed_numbers for number in _numbers(clean)):
        return "numeric_mismatch"
    return None


def polish(text: str, allowed: Iterable[str], *, enabled: bool = False) -> tuple[str, str]:
    """Return (text, source).  LLM is disabled unless explicitly configured."""
    if not enabled or os.environ.get("WGS_CONSUMER_LLM_ENABLED", "0") != "1":
        return text, "rule"
    # The actual call is intentionally delegated to the platform narrative
    # service by the caller.  Without a validated response, stay with rules.
    return text, "rule"


def headline(positive: str, watch: str) -> str:
    if positive and watch:
        return f"{positive}，但{watch}。"
    if watch:
        return f"{watch}。"
    if positive:
        return f"{positive}。"
    return "本次报告从菌群组成、功能潜力和检测范围三个方面提供参考。"
