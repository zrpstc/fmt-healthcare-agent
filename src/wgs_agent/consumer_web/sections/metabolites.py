"""Metabolite section (professional chapter 8)."""

from __future__ import annotations

from typing import Any

from ..functions import metabolite_contributors
from .context import Context
from .panel import category_rows, load_panel


PRODUCTS = {
    "乙酸": ("acetate", ["PWY-5100", "P41-PWY", "P461-PWY"], []),
    "丙酸": ("propionate", ["P108-PWY"], []),
    "丁酸": ("butyrate", ["CENTFERM-PWY", "PWY-5676", "P162-PWY", "P163-PWY", "PWY-5022"], []),
    "吲哚类": ("indole", [], ["4.1.99.1"]),
    "对甲酚与酪胺": ("protein_fermentation", ["PWY-6305", "PWY0-1277"], ["4.1.1.25"]),
    "氢气": ("hydrogen", ["PWY-8086"], []),
    "甲烷": ("methane", ["METH-ACETATE-PWY"], []),
}


def _card(ctx: Context, title: str, term_id: str, pathway_ids: list[str], ecs: list[str]) -> dict[str, Any] | None:
    item = metabolite_contributors(ctx.document, pathway_ids, ecs)
    if not item["has_signal"]:
        return None
    members = [ctx.names.plain(row["name"]) for row in item["named"][:5]]
    text = ctx.glossary.one_liner(term_id) if ctx.glossary.is_publishable(term_id) else "相关功能基因被检出。"
    if not members:
        text += " 分层注释不足以确定具体菌。"
    return {
        "title": title,
        "text": text,
        "status": "具备相关基因",
        "tone": "neutral",
        "tier": None,
        "members": members or None,
    }


def build(ctx: Context) -> dict[str, Any]:
    subsections = []
    scfa = []
    for title in ("乙酸", "丙酸", "丁酸"):
        term_id, paths, ecs = PRODUCTS[title]
        card = _card(ctx, title, term_id, paths, ecs)
        if card and title == "丁酸":
            members = list(card.get("members") or [])
            panel = load_panel()
            for category in panel.get("categories", []):
                if category.get("id") != "helpful.butyrate":
                    continue
                for row in category_rows(ctx, category):
                    name = ctx.names.plain(row["name"])
                    if name not in members:
                        members.append(name)
            card["members"] = members or None
        if card:
            scfa.append(card)
    if scfa:
        subsections.append({
            "id": "metabolites-scfa",
            "title": "短链脂肪酸",
            "blocks": [{"type": "card_grid", "cards": scfa}],
            "summary": "这些产物与膳食纤维发酵有关；基因潜力不代表体内产量。",
            "summary_source": "rule",
            "graph": ctx.graph_for(["metabolites.scfa"], ["乙酸", "丙酸", "丁酸"]),
        })

    indoles = _card(ctx, "吲哚类", "indole", [], ["4.1.99.1"])
    if indoles:
        subsections.append({
            "id": "metabolites-indoles",
            "title": "色氨酸代谢",
            "blocks": [{"type": "card_grid", "cards": [indoles]}],
            "summary": "色氨酸可以被部分肠道菌转化为吲哚类物质，具体影响仍在研究。",
            "summary_source": "rule",
            "graph": ctx.graph_for(["metabolites.indoles", "gut_brain.tryptophan"], ["吲哚", "色氨酸"]),
        })

    protein = _card(ctx, "对甲酚与酪胺", "protein_fermentation", ["PWY-6305", "PWY0-1277"], ["4.1.1.25"])
    if protein:
        subsections.append({
            "id": "metabolites-protein",
            "title": "蛋白质发酵产物",
            "blocks": [{"type": "card_grid", "cards": [protein]}],
            "summary": "蛋白质发酵产物在研究中与肠道环境相关，不能据此判断症状。",
            "summary_source": "rule",
            "graph": ctx.graph_for(["metabolites.phenols"], ["对甲酚", "酪胺", "蛋白质"]),
        })

    gases = []
    for title in ("氢气", "甲烷"):
        term_id, paths, ecs = PRODUCTS[title]
        card = _card(ctx, title, term_id, paths, ecs)
        if card:
            gases.append(card)
    if gases:
        subsections.append({
            "id": "metabolites-gases",
            "title": "气体",
            "blocks": [{"type": "card_grid", "cards": gases}],
            "summary": "肠道气体由多种菌共同产生，检出相关基因不等于实际产气量高。",
            "summary_source": "rule",
            "graph": ctx.graph_for(["ecology.gas", "metabolites.sulfur"], ["氢气", "甲烷", "气体"]),
        })

    ctx.omit("metabolites", "胆汁酸转化", "本次没有可用的胆汁酸通路结果")
    ctx.omit("metabolites", "TMA", "本次没有可用的TMA通路结果")
    ctx.omit("metabolites", "硫化氢", "本次没有直接产硫化氢的通路结果")

    return {
        "id": "metabolites",
        "nav_label": "代谢产物",
        "title": "菌群能产生哪些物质",
        "intro": f"这一部分按产物主题展示基因层面的{ctx.term('functional_potential', '功能潜力')}，不代表体内实际浓度。",
        "source_chapters": [8],
        "terms_banner": ["short_chain_fatty_acid", "indole", "protein_fermentation", "methane"],
        "subsections": subsections,
    }
