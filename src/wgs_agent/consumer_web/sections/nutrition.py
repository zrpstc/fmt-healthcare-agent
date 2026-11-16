"""Food and nutrition section (professional chapter 7)."""

from __future__ import annotations

from typing import Any

from ..format import count
from ..functions import fiber_contributors, load_substrate_map, load_vitamin_map, vitamin_table
from .context import Context


def _substrate_cards(ctx: Context) -> list[dict[str, Any]]:
    fibers = fiber_contributors(ctx.document)
    mapping = load_substrate_map()
    cards = []
    for substrate in mapping.get("substrates", []):
        ident = str(substrate["id"])
        item = fibers.get(ident)
        if item is None:
            continue
        sources = "、".join(substrate.get("food_sources", []))
        meaning = ctx.glossary.one_liner(str(substrate.get("term_id") or ""))
        status = item["conclusion"]
        tone = "good" if status == "多种菌具备" else "neutral"
        members = [ctx.names.plain(row["name"]) for row in item["named"][:5]]
        cards.append({
            "title": str(substrate.get("name") or ident),
            "text": f"常见食物：{sources}。{meaning}",
            "status": status,
            "tone": tone,
            "tier": None,
            "members": members or None,
        })
    return cards


def _vitamin_rows(ctx: Context) -> list[list[str]]:
    rows = []
    for item in vitamin_table(ctx.document):
        vitamin = item["vitamin"]
        name = str(vitamin.get("name") or "")
        named = [ctx.names.plain(row["name"]) for row in item["named"][:3]]
        members = "、".join(named) if named else "通路已检出，分层贡献未确定"
        rows.append([
            name,
            item["status"],
            members,
            str(vitamin.get("role") or ""),
        ])
    return rows


def build(ctx: Context) -> dict[str, Any]:
    subsections = []
    cards = _substrate_cards(ctx)
    if cards:
        subsections.append({
            "id": "nutrition-fiber",
            "title": "能分解哪些膳食纤维",
            "blocks": [{"type": "card_grid", "cards": cards}],
            "summary": "不同纤维由不同菌群分担；基因潜力不代表实际分解量。",
            "summary_source": "rule",
            "graph": ctx.graph_for(
                ["nutrient_metabolism.fiber", "nutrient_metabolism.carbohydrate"],
                ["淀粉", "葡萄糖代谢", "葡萄糖", "膳食纤维", "抗性淀粉"],
            ),
        })
    else:
        ctx.omit("nutrition", "膳食纤维分解", "没有可用的底物通路注释")

    rows = _vitamin_rows(ctx)
    if rows:
        subsections.append({
            "id": "nutrition-vitamins",
            "title": "能合成哪些维生素",
            "blocks": [
                {
                    "type": "table",
                    "columns": ["维生素", "是否具备合成潜力", "主要参与的菌", "一句话作用"],
                    "rows": rows,
                    "footnote": "肠道菌合成的维生素有多少能被人体吸收利用，目前尚不确定，不能代替饮食摄入。",
                }
            ],
            "summary": "多种维生素相关通路被检出，但这不等于人体已经获得足够维生素。",
            "summary_source": "rule",
            "graph": ctx.graph_for(
                ["nutrient_metabolism.vitamin"],
                ["大肠杆菌", "叶酸生物合成", "叶酸生物合成通路", "维生素"],
            ),
        })
    else:
        ctx.omit("nutrition", "维生素合成", "没有可用的维生素通路注释")

    return {
        "id": "nutrition",
        "nav_label": "食物与营养",
        "title": "菌群能分解哪些食物成分、合成哪些营养",
        "intro": f"这一部分讲菌群的{ctx.term('functional_potential', '功能潜力')}，不是实际吃了多少或吸收了多少。",
        "source_chapters": [7],
        "terms_banner": ["functional_potential", "resistant_starch", "vitamin_synthesis"],
        "subsections": subsections,
    }
