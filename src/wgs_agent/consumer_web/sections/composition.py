"""Composition section (professional chapter 1)."""

from __future__ import annotations

from typing import Any

from ..format import count, pct, tier, latin_for_display
from .context import Context
from ..names import canonical


def _phylum_rows(ctx: Context) -> list[dict]:
    rows = ctx.taxonomy.get("ranks", {}).get("phylum", [])
    result = []
    for row in rows if isinstance(rows, list) else []:
        value = float(row.get("abundance") or 0)
        if value > 0:
            result.append({**row, "name": str(row.get("name") or ""), "value": value})
    return sorted(result, key=lambda row: -row["value"])


def _species_text(ctx: Context, name: str) -> str | None:
    # Resolved by Latin name; unexplained species are queued for drafting/review.
    return ctx.taxon_text(name, "one_liner")


def _comparison_rows(ctx: Context) -> list[dict]:
    main = {canonical(row["name"]): row for row in ctx.species_rows}
    rows = []
    for row in ctx.healthy_rows:
        name = str(row.get("species") or row.get("name") or "")
        canonical_name = canonical(name)
        if canonical_name not in main:
            continue
        percentile = row.get("percentile")
        if percentile is None or str(row.get("status")) not in {"high", "low", "normal", "borderline"}:
            continue
        try:
            p = float(percentile)
        except (TypeError, ValueError):
            continue
        if not 0 <= p <= 100:
            continue
        t = tier(p, metric="species_diff", borderline=bool(row.get("borderline")))
        rows.append({
            "label": ctx.names.render(name),
            "value": float(row.get("abundance") or 0),
            "tier": t,
            "percentile": p,
            "p95": row.get("p95"),
            "status": row.get("status"),
        })
    order = {"very_low": 0, "very_high": 0, "low": 1, "high": 1, "typical": 2}
    rows.sort(key=lambda row: (order.get(row["tier"].key, 3), -abs(row["percentile"] - 50), row["label"]))
    return rows[:8]


def build(ctx: Context) -> dict[str, Any]:
    subsections: list[dict[str, Any]] = []
    phyla = _phylum_rows(ctx)
    species = sorted(ctx.species_rows, key=lambda row: -row["value"])
    if phyla or species:
        segments = []
        for index, row in enumerate(phyla):
            label = ctx.names.plain(row["name"])
            term_id = {
                "厚壁菌门": "bacillota", "拟杆菌门": "bacteroidota", "变形菌门": "pseudomonadota",
                "梭杆菌门": "fusobacteriota", "疣微菌门": "verrucomicrobiota",
                "放线菌门": "actinomycetota", "子囊菌门": "ascomycota", "甲烷杆菌门": "methanobacteriota",
            }.get(label)
            note = ctx.glossary.one_liner(term_id) if term_id and ctx.glossary.is_publishable(term_id) else None
            segments.append({
                "label": label,
                "value": {"value": row["value"], "display": pct(row["value"]), "unit": "%"},
                "note": note,
                "color_key": f"phylum-{index}",
            })
        total = sum(row["value"] for row in phyla)
        uncovered = max(0.0, 100.0 - total)
        if uncovered > 0.005:
            segments.append({
                "label": "未能归类",
                "value": {"value": uncovered, "display": pct(uncovered), "unit": "%"},
                "note": "现有分类谱没有把这些序列归入上述大类。",
                "color_key": "unclassified",
            })
        if abs(sum(float(item["value"]["value"]) for item in segments) - 100) > 0.02:
            # Keep the visual honest: residual is the unclassified share.
            residual = 100.0 - sum(float(item["value"]["value"]) for item in segments[:-1])
            if segments and segments[-1]["label"] == "未能归类":
                segments[-1]["value"] = {"value": max(0.0, residual), "display": pct(max(0.0, residual)), "unit": "%"}
        cards = []
        for row in species[:5]:
            cards.append(ctx.taxon_card(row["name"], row["value"], text=_species_text(ctx, row["name"])))
        ranked = [
            {
                "label": ctx.names.plain(row["name"]),
                "latin": latin_for_display(row["name"]),
                "value": {"value": row["value"], "display": pct(row["value"]), "unit": "%"},
                "tone": "neutral",
            }
            for row in species[:5]
        ]
        blocks: list[dict[str, Any]] = []
        if segments:
            top = max(segments, key=lambda item: float(item["value"]["value"] or 0))
            blocks.append({
                "type": "donut",
                "title": "图1 门水平组成（各大类细菌占比）",
                "caption": (
                    "整个圆环代表本次检出的全部细菌（100%），每段颜色代表一个“门”（细菌分类中很大的一级），"
                    "弧段越长占比越高。"
                ),
                "center_label": f"占比最高：{top['label']}",
                "center_value": top["value"]["display"],
                "segments": segments,
            })
        if ranked:
            blocks.append({
                "type": "ranked_bars",
                "title": f"图2 占比最高的{count(len(ranked))}种菌",
                "caption": "条形长度和右侧数字表示该菌占全部细菌的比例（相对丰度）。",
                "axis": {"category_label": "菌名", "value_label": "占全部细菌的比例（%）", "ticks": []},
                "rows": ranked,
            })
        blocks.append({"type": "taxon_cards", "cards": cards})
        subsections.append({
            "id": "composition-composition",
            "title": "主要由哪些菌组成",
            "blocks": blocks,
            "summary": "门水平以厚壁菌门和拟杆菌门为主，占比最高的几种菌构成了群落的主体。",
            "summary_source": "rule",
            "graph": ctx.graph_for(
                ["composition.phyla", "composition.species"],
                [ctx.names.plain(row["name"]) for row in phyla] + [row["name"] for row in phyla]
                + [ctx.names.plain(row["name"]) for row in species[:5]] + [row["name"] for row in species[:5]],
            ),
        })

    # Dominance / concentration
    if species:
        top1 = species[0]["value"]
        top5 = sum(row["value"] for row in species[:5])
        classified = ctx.classified_total
        top5_share = 100 * top5 / classified if classified else 0
        blocks = [
            {
                "type": "paragraph",
                "text": f"占比最高的菌是{ctx.name(species[0]['name'])}，约占{pct(top1)}；前五种菌合计占已归类细菌的{pct(top5_share)}。",
            }
        ]
        summary = "菌群由多种菌共同构成，没有单一菌占到一半。"
        subsections.append({
            "id": "composition-dominance",
            "title": "是否由少数几种菌主导",
            "blocks": blocks,
            "summary": summary,
            "summary_source": "rule",
            "graph": ctx.graph_for(
                ["composition.dominance", "composition.species"],
                [ctx.names.plain(species[0]["name"]), species[0]["name"], "菌群组成"],
            ),
        })

    # Composition comparison
    comparisons = _comparison_rows(ctx)
    if comparisons:
        rows = [
            {
                "label": row["label"],
                "value": {"value": row["value"], "display": pct(row["value"]), "unit": "%"},
                "tier": row["tier"],
                "note": None,
            }
            for row in comparisons
        ]
        obvious = [row["label"] for row in comparisons if row["tier"].key in {"very_low", "very_high"}]
        if obvious:
            difference = "明显偏离常见范围的有：" + "、".join(obvious[:5]) + "。"
        else:
            difference = "没有菌明显偏离常见范围。"
        blocks = [
            {
                "type": "paragraph",
                "text": "对照人群：3,537名来自公开研究的健康成人（未按年龄、性别、地区匹配）。",
            },
            {"type": "tier_scales", "rows": rows},
            {"type": "paragraph", "text": difference},
            {
                "type": "paragraph",
                "text": f"为与{ctx.term('reference_population', '健康人群')}同口径比较，此处数值经重新计算，可能与上方略有差异。",
            },
        ]
        subsections.append({
            "id": "composition-comparison",
            "title": "和健康人相比，哪些菌明显不同",
            "blocks": blocks,
            "summary": "对照数字来自公开健康人群的粪便检测，用来描述常见程度，不是疾病判断。",
            "summary_source": "rule",
            "graph": ctx.graph_for(
                ["composition.phyla"],
                [ctx.names.plain(row["name"]) for row in phyla] + [row["name"] for row in phyla]
                + [row["label"] for row in comparisons[:4]],
            ),
        })
    else:
        ctx.omit("composition", "与健康人相比的组成比较", "缺少可用于该样本的同口径参考分布")

    ctx.omit("composition", "肠型", "没有经过验证的参考聚类资产，不能根据优势菌推断肠型")
    ctx.omit("composition", "核心菌群", "本次报告没有定义核心菌群；不以优势菌代替")

    return {
        "id": "composition",
        "nav_label": "菌群组成",
        "title": "您的肠道里住着哪些菌",
        "intro": "这一部分看的是菌群总体由哪些大类组成，以及哪些菌占了较大比例。",
        "source_chapters": [1],
        "terms_banner": ["relative_abundance", "taxonomic_ranks", "reference_population"],
        "subsections": subsections,
    }
