"""Versioned consumer key-taxa panel matching, shared by overview and key-taxa."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wgs_fmt_platform.paths import PROJECT_ROOT

from .context import Context
from ..names import canonical

PANEL_PATH = PROJECT_ROOT / "knowledge_base" / "consumer_key_taxa.yaml"


def load_panel(path: Path | None = None) -> dict[str, Any]:
    raw = Path(path or PANEL_PATH).read_text(encoding="utf-8")
    try:
        panel = json.loads(raw)
    except ValueError:
        import yaml
        panel = yaml.safe_load(raw)
    if not isinstance(panel, dict) or not isinstance(panel.get("categories"), list):
        raise ValueError("invalid_consumer_key_taxa_panel")
    return panel


def matches(name: str, member: dict) -> bool:
    key = canonical(name)
    names = [canonical(str(item)) for item in [member.get("name"), *(member.get("aliases") or [])] if item]
    if member.get("rank") == "genus":
        return any(key == item or key.startswith(item + " ") for item in names)
    return key in names


def category_matches(name: str, category: dict) -> bool:
    return any(matches(name, member) for member in category.get("members", []))


def category_rows(ctx: Context, category: dict) -> list[dict]:
    rows = []
    for row in ctx.species_rows:
        if row["value"] > 0 and category_matches(row["name"], category):
            rows.append(row)
    return sorted(rows, key=lambda row: (-row["value"], row["name"]))


def category_total(ctx: Context, category: dict) -> float:
    return sum(row["value"] for row in category_rows(ctx, category))


def watch_species(ctx: Context) -> list[dict]:
    panel = load_panel()
    result = []
    seen = set()
    for category in panel.get("categories", []):
        if category.get("section") != "watch":
            continue
        for row in category_rows(ctx, category):
            key = canonical(row["name"])
            if key not in seen:
                seen.add(key)
                result.append({**row, "category": category})
    return sorted(result, key=lambda row: -row["value"])


def evidence_badge(ctx: Context, name: str) -> str | None:
    """Count independent species-level literature sources for one taxon."""
    claims = []
    key = canonical(name)
    for row in ctx.evidence("literature"):
        if str(row.get("subject_type")) != "MicrobialTaxon" and str(row.get("object_type")) != "MicrobialTaxon":
            continue
        subject = canonical(str(row.get("subject") or ""))
        obj = canonical(str(row.get("object") or ""))
        if subject == key or obj == key:
            claims.append(row)
    documents = {str(row.get("document_id") or row.get("claim_id")) for row in claims}
    if len(documents) >= 3:
        return "多项研究"
    if documents:
        return "少量研究"
    return None


def reliability_badge(row: dict, thresholds: dict | None = None) -> str | None:
    thresholds = thresholds or {"high": 1000, "medium": 100}
    for field in ("estimated_reads", "estimated_read_count", "estimated_number_of_reads",
                  "estimated_number_of_reads_from_the_clade", "read_count", "reads"):
        if field not in row:
            continue
        try:
            number = float(row[field])
        except (TypeError, ValueError):
            return None
        if number < 0 or not number.is_integer():
            return None
        return "高" if number >= thresholds["high"] else "中" if number >= thresholds["medium"] else "低"
    return None


def member_text(ctx: Context, member: dict, category: dict, row_name: str) -> str | None:
    """Publishable text for the detected taxon (resolved by Latin name)."""
    field = "watch_note" if category.get("section") == "watch" else "one_liner"
    return ctx.taxon_text(row_name, field)


def category_term(category: dict) -> str:
    return str(category.get("concept_term_id") or "")
