"""Shared, deterministic consumer-facing number formatting (inputs are percentages)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import math


def _number(value):
    if isinstance(value, bool):
        raise ValueError("not_a_number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite_number")
    return number


def pct(value):
    number = _number(value)
    if number < 0 or number > 100:
        raise ValueError("percentage_out_of_range")
    if number < .01:
        return "<0.01%"
    if number < .1:
        return f"{number:.2g}%"
    places = 2 if number < 1 else 1
    rounded = Decimal(str(number)).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)
    # The significant-digit ceiling takes precedence at the 100% boundary.
    return "100%" if rounded >= 100 else f"{rounded:.{places}f}%"


def count(value):
    number = _number(value)
    if number < 0 or not number.is_integer():
        raise ValueError("invalid_count")
    return f"{int(number):,}"


def percentile_phrase(value):
    p = _number(value)
    if not 0 <= p <= 100:
        raise ValueError("percentile_out_of_range")
    if p >= 99:
        return "高于99%以上的参考人群"
    if p <= 1:
        return "低于99%以上的参考人群"
    if p >= 50:
        return f"高于约{round(p)}%的参考人群"
    return f"低于约{round(100-p)}%的参考人群"


def tier(value, borderline=False):
    p = _number(value)
    if not 0 <= p <= 100:
        raise ValueError("percentile_out_of_range")
    if p < 5:
        return "略低" if borderline else "明显偏低"
    if p < 25:
        return "略低"
    if p <= 75:
        return "常见"
    if p <= 95:
        return "略高"
    return "略高" if borderline else "明显偏高"


def number(value):
    """For other measured quantities; exact counts use count()."""
    return f"{_number(value):.3g}"
