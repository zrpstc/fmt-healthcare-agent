"""More clues section (professional chapters 9, 10 and 12)."""

from __future__ import annotations

from typing import Any

from ..functions import metabolite_contributors
from .context import Context


def _specialized(ctx: Context, ident: str) -> dict | None:
    module = ctx.module("specialized_metabolism")
    for group in ("dietary", "drugs"):
        for row in module.get(group, []) if isinstance(module.get(group), list) else []:
            if row.get("id") == ident and row.get("status") == "annotation_detected":
                return row
    return None


def _stratified_names(row: dict) -> list[str]:
    values = row.get("stratified_contributions") or []
    result = []
    for item in values if isinstance(values, list) else []:
        if isinstance(item, dict):
            name = item.get("taxon") or item.get("species") or item.get("name")
            if name and str(name).lower() not in {"unclassified", "unassigned", "unknown"}:
                result.append(str(name))
    return result


def build(ctx: Context) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []

    beta_glucosidase = _specialized(ctx, "beta_glucosidase")
    if beta_glucosidase:
        members = _stratified_names(beta_glucosidase)
        cards.append({
            "title": "多酚与异黄酮转化",
            "text": ctx.glossary.one_liner("polyphenol") if ctx.glossary.is_publishable("polyphenol") else "检出与糖苷水解相关的基因家族。",
            "status": "检出相关基因",
            "tone": "neutral",
            "tier": None,
            "members": [ctx.names.plain(name) for name in members[:3]] or None,
        })

    beta_glucuronidase = _specialized(ctx, "beta_glucuronidase")
    azoreductase = _specialized(ctx, "azoreductase")
    tyrosine = _specialized(ctx, "tyrosine_decarboxylase")
    if beta_glucuronidase or azoreductase or tyrosine:
        members = []
        for row in (beta_glucuronidase, azoreductase, tyrosine):
            if row:
                members.extend(_stratified_names(row))
        cards.append({
            "title": "药物与化学物转化",
            "text": ctx.glossary.one_liner("drug_transformation") if ctx.glossary.is_publishable("drug_transformation") else "检出与药物或化学物转化相关的基因家族。",
            "status": "检出相关基因",
            "tone": "neutral",
            "tier": None,
            "members": [ctx.names.plain(name) for name in dict.fromkeys(members)][:3] or None,
        })

    gaba = metabolite_contributors(ctx.document, ["GLUDEG-I-PWY"])
    if gaba["has_signal"]:
        cards.append({
            "title": "γ-氨基丁酸相关代谢",
            "text": ctx.glossary.one_liner("gaba") if ctx.glossary.is_publishable("gaba") else "检出与GABA代谢相关的通路。",
            "status": "具备相关基因",
            "tone": "neutral",
            "tier": None,
            "members": [ctx.names.plain(row["name"]) for row in gaba["named"][:3]] or None,
        })

    mucin = next((row for row in ctx.species_rows if ctx.names.plain(row["name"]) == "嗜黏蛋白阿克曼菌"), None)
    if mucin:
        cards.append({
            "title": "黏液糖链利用",
            "text": ctx.glossary.one_liner("mucin_utilization") if ctx.glossary.is_publishable("mucin_utilization") else "阿克曼菌能利用肠道黏液中的部分成分。",
            "status": "检出相关菌",
            "tone": "neutral",
            "tier": None,
            "members": [ctx.names.plain(mucin["name"])],
        })

    if not cards:
        return {
            "id": "more",
            "nav_label": "更多线索",
            "title": "其他功能线索",
            "source_chapters": [9, 10, 12],
            "subsections": [],
        }

    subsections = [{
        "id": "more-cards",
        "title": "其他功能线索",
        "blocks": [{"type": "card_grid", "cards": cards}, {"type": "paragraph", "text": "这是研究中的新方向，结论仍在发展。"}],
        "summary": "这些是研究中的新方向，适合作为背景阅读。",
        "summary_source": "rule",
        "graph": ctx.graph_for(
            ["ecology.mucin", "gut_brain.gaba", "metabolites.phenols"],
            ["多酚", "GABA", "黏液", "阿克曼菌"],
        ),
    }]

    return {
        "id": "more",
        "nav_label": "更多线索",
        "title": "其他功能线索",
        "intro": "这些线索来自功能基因或菌种特性，结论仍在发展。",
        "source_chapters": [9, 10, 12],
        "terms_banner": ["polyphenol", "gaba", "mucin_utilization"],
        "subsections": subsections,
    }
