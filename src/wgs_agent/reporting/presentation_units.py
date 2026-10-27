"""Display formatting for quantities without physical units."""
import re

def display_unit(value):
    text = str(value or "").strip()
    return "" if text.casefold() in {"无量纲", "dimensionless", "unitless", "1"} else text

def display_text(value):
    text = str(value)
    text = re.sub(r"[（(]\s*(?:无量纲|dimensionless|unitless)\s*[）)]", "", text, flags=re.I)
    return re.sub(r"[ \u3000]*(?:无量纲|\b(?:dimensionless|unitless)\b)", "", text, flags=re.I)
