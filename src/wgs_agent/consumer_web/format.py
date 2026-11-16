"""Shared deterministic formatting for consumer-facing values.

Rule set (from the product specification):
* percentages >= 1 -> one decimal place
* 0.1 .. 1 -> two decimal places
* 0.01 .. 0.1 -> two significant digits
* < 0.01 -> "<0.01%"
* counts -> thousands separators
* percentiles are never shown directly, only a natural-language phrase
* no scientific notation anywhere in consumer prose
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, ROUND_HALF_UP

from .schema import Tier

METRIC_LABELS: dict[str, tuple[str, str, str, str, str]] = {
    "richness": ("偏少", "略少", "常见", "较丰富", "很丰富"),
    "shannon": ("偏少", "略少", "常见", "较丰富", "很丰富"),
    "evenness": ("较集中", "略集中", "常见", "较均衡", "很均衡"),
    "beneficial": ("偏少", "略少", "常见", "较多", "很多"),
    "watch": ("较少", "略少", "常见", "略多", "明显偏多"),
    "species_diff": ("明显偏低", "略低", "常见", "略高", "明显偏高"),
    "typicality": ("很典型", "较典型", "略少见", "少见", "很少见"),
}
METRIC_TONES: dict[str, tuple[str, str, str, str, str]] = {
    "richness": ("watch", "watch", "neutral", "good", "good"),
    "shannon": ("watch", "watch", "neutral", "good", "good"),
    "evenness": ("watch", "watch", "neutral", "good", "good"),
    "beneficial": ("watch", "watch", "neutral", "good", "good"),
    "watch": ("good", "good", "neutral", "watch", "watch"),
    "species_diff": ("watch", "watch", "neutral", "watch", "watch"),
    "typicality": ("good", "good", "neutral", "watch", "watch"),
}


def _number(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("not_a_number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite_number")
    return number


def _round_decimal(value: float, places: int) -> Decimal:
    return Decimal(str(value)).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)


def pct(value: object) -> str:
    """Format a percentage without scientific notation."""
    number = _number(value)
    if number < 0 or number > 100:
        raise ValueError("percentage_out_of_range")
    if number < 0.01:
        return "<0.01%"
    if number < 0.1:
        # Two significant digits, expressed as a fixed decimal.
        places = max(0, 1 - int(math.floor(math.log10(number))))
        text = f"{_round_decimal(number, places):.{places}f}"
        return f"{text}%"
    places = 2 if number < 1 else 1
    rounded = _round_decimal(number, places)
    if rounded >= Decimal("100"):
        return "100%"
    return f"{rounded:.{places}f}%"


def count(value: object) -> str:
    number = _number(value)
    if number < 0 or not number.is_integer():
        raise ValueError("invalid_count")
    return f"{int(number):,}"


def sig(value: object, digits: int = 3) -> str:
    """Three significant digits, always fixed-point (never e-notation)."""
    number = _number(value)
    if number == 0:
        return "0"
    exponent = int(math.floor(math.log10(abs(number))))
    places = max(0, digits - 1 - exponent)
    rounded = _round_decimal(number, places)
    text = f"{rounded:.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def number(value: object) -> str:
    return sig(value, 3)


def percentile_phrase(percentile: object) -> str:
    p = _number(percentile)
    if not 0 <= p <= 100:
        raise ValueError("percentile_out_of_range")
    if p >= 99:
        return "高于99%以上的参考人群"
    if p <= 1:
        return "低于99%以上的参考人群"
    if p >= 50:
        return f"高于约{round(p)}%的参考人群"
    return f"低于约{round(100 - p)}%的参考人群"


def tier(percentile: object, *, metric: str, borderline: bool = False) -> Tier:
    p = _number(percentile)
    if not 0 <= p <= 100:
        raise ValueError("percentile_out_of_range")
    if p < 5:
        index = 1 if borderline else 0
    elif p < 25:
        index = 1
    elif p <= 75:
        index = 2
    elif p <= 95:
        index = 3
    else:
        index = 3 if borderline else 4
    labels = METRIC_LABELS[metric]
    tones = METRIC_TONES[metric]
    return Tier(
        key=("very_low", "low", "typical", "high", "very_high")[index],
        label=labels[index],
        tone=tones[index],  # type: ignore[arg-type]
        percentile=round(p, 3),
        phrase=percentile_phrase(p),
        borderline=borderline,
    )


def tier_from_key(key: str, percentile: float, *, metric: str, borderline: bool = False) -> Tier:
    """Build a Tier from a known key while preserving the displayed percentile."""
    index = {
        "very_low": 0, "low": 1, "typical": 2, "high": 3, "very_high": 4,
    }[key]
    labels = METRIC_LABELS[metric]
    tones = METRIC_TONES[metric]
    return Tier(
        key=key,  # type: ignore[arg-type]
        label=labels[index],
        tone=tones[index],  # type: ignore[arg-type]
        percentile=round(float(percentile), 3),
        phrase=percentile_phrase(percentile),
        borderline=borderline,
    )


def value_or_none(value: object) -> float | None:
    try:
        number = _number(value)
    except (ValueError, TypeError):
        return None
    return number if number >= 0 else None


DISALLOWED_PHRASES = (
    "未提供",
    "未启用",
    "暂无法判断",
    "已记录",
    "本节",
    "如图所示",
    "综上所述",
    "值得注意的是",
    "【",
    "】",
)

TECHNICAL_PATTERNS = (
    r"\bg__",
    r"\bs__",
    r"\bk__",
    r"\bP5\b",
    r"\bP95\b",
    r"经验百分位",
    r"bootstrap",
    r"MetaPhlAn",
    r"HUMAnN",
    r"cMD",
    r"VFDB",
    r"ResFinder",
    r"RPKM",
    r"\breads\b",
    r"PWY-",
    r"\bMV\d+",
    r"NC_\d+",
    r"[+-]?\d+(?:\.\d+)?[eE][+-]?\d+",
)


def text_violations(text: str) -> list[str]:
    """Return disallowed consumer-language hits; technical hits only for body copy."""
    hits: list[str] = []
    for phrase in DISALLOWED_PHRASES:
        if phrase in text:
            hits.append(phrase)
    for pattern in TECHNICAL_PATTERNS:
        if re.search(pattern, text):
            hits.append(pattern)
    return hits


def business_number_violations(text: str) -> list[str]:
    """Check that prose numbers have at most three significant digits.

    Thousand-separated integer counts (e.g. ``3,537``) are explicitly requested
    by the product specification and therefore exempt from the significant-digit
    ceiling.  Percentages and measured values are not exempt.
    """
    violations: list[str] = []
    for token in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        if "," in token:
            continue
        digits = token.replace(".", "").lstrip("0")
        # A trailing zero after the decimal is still part of the displayed value,
        # but rounding to three significant digits already guarantees the ceiling.
        if len(digits) > 3 and not token.startswith("100"):
            violations.append(token)
    return violations


def latin_for_display(value: str | None) -> str | None:
    if not value:
        return None
    latin = re.sub(r"\s+ex\s+.*$", "", value, flags=re.I).replace("_", " ")
    return latin.strip() or None
