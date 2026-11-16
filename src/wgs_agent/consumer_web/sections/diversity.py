"""Diversity and functional division section (professional chapter 2)."""

from __future__ import annotations

from typing import Any

from ..format import count, number, pct, sig, tier
from ..functions import aggregate_category, fiber_union, taxonomy_fallback_contributors
from ..names import canonical
from .context import Context
from .panel import category_rows, load_panel


def _diversity_value(ctx: Context, metric: str) -> tuple[float, float, bool] | None:
    rows = ctx.healthy_comparison.get("diversity", [])
    if isinstance(rows, list):
        for row in rows:
            if row.get("metric") != metric:
                continue
            value = row.get("value")
            percentile = row.get("percentile")
            if value is None or percentile is None:
                continue
            try:
                return float(value), float(percentile), bool(row.get("borderline"))
            except (TypeError, ValueError):
                continue
    # Fall back to the primary analysis without inventing a percentile.
    diversity = ctx.analysis.get("diversity") if isinstance(ctx.analysis, dict) else {}
    if isinstance(diversity, dict) and diversity.get(metric) is not None:
        return float(diversity[metric]), None, False
    return None


def _typicality_phrase(percentile: float) -> str:
    if percentile >= 99:
        return "比99%以上的参考人群差异更大"
    if percentile > 50:
        return f"比约{round(percentile)}%的参考人群差异更大"
    if percentile >= 1:
        return f"比约{round(100 - percentile)}%的参考人群更接近"
    return "比99%以上的参考人群更接近"


def _stage_members(ctx: Context, names: list[str], values: dict[str, float], more: int = 0) -> tuple[list[str], int, str, float | None]:
    labels = [ctx.names.plain(name) for name in names]
    total = sum(values.values())
    top = max(values.values()) / total * 100 if total else None
    backup = "多种菌分担" if len(labels) >= 3 and top is not None and top < 60 else "主要依赖少数菌"
    return labels, max(0, len(labels) - 3), backup, top


def build(ctx: Context) -> dict[str, Any]:
    subsections: list[dict[str, Any]] = []

    # 1. Diversity scales
    metrics = [
        ("richness", "菌种数（丰富度）", "种"),
        ("shannon", "综合多样性", ""),
        ("evenness", "分布均衡度", ""),
    ]
    rows = []
    for metric, label, unit in metrics:
        item = _diversity_value(ctx, metric)
        if item is None:
            continue
        value, percentile, borderline = item
        if percentile is None:
            ctx.omit("diversity", f"{label}参考档位", "缺少同口径参考比较")
            continue
        t = tier(percentile, metric=metric, borderline=borderline)
        display = count(value) if metric == "richness" and float(value).is_integer() else number(value)
        rows.append({
            "label": label,
            "value": {"value": value, "display": display, "unit": unit or None},
            "tier": t,
            "note": None,
        })
    if rows:
        blocks = [{"type": "tier_scales", "rows": rows}]
        if all(row.get("tier") for row in rows):
            summary = "；".join(f"{row['label']}{row['tier'].label}" for row in rows) + "。"
        else:
            summary = "多样性指标用于描述菌的种类和分布，不代表健康好坏。"
        subsections.append({
            "id": "diversity-diversity",
            "title": "菌的种类多不多",
            "blocks": blocks,
            "summary": summary,
            "summary_source": "rule",
            "graph": ctx.graph_for(
                ["diversity.shannon", "diversity.richness"],
                ["菌种数", "综合多样性", "分布均衡度", "diversity", "richness"],
            ),
        })

    # 2. Typicality and scatter
    typicality = ctx.healthy_comparison.get("typicality") or {}
    percentile = typicality.get("percentile")
    if percentile is not None and typicality.get("status") == "available":
        p = float(percentile)
        t = tier(p, metric="typicality", borderline=bool(typicality.get("borderline")))
        phrase = _typicality_phrase(p)
        blocks: list[dict[str, Any]] = [
            {"type": "paragraph", "text": f"从整体组成看，您的菌群{t.label}，{phrase}。"},
        ]
        ordination = ctx.healthy_comparison.get("ordination") or {}
        points = []
        you = None
        if isinstance(ordination, dict) and ordination.get("status") == "available":
            raw = ordination.get("points", [])
            for item in raw[:300] if isinstance(raw, list) else []:
                try:
                    x, y = float(item.get("x")), float(item.get("y"))
                except (TypeError, ValueError):
                    continue
                points.append((x, y))
                if item.get("is_sample"):
                    you = (x, y)
            if you is not None and points:
                blocks.append({
                    "type": "scatter",
                    "points": points,
                    "you": you,
                    "caption": "每个点代表一位健康成人，菱形是您；点越接近，菌群组成越相似。",
                })
        subsections.append({
            "id": "diversity-typicality",
            "title": "您的菌群和健康人像不像",
            "blocks": blocks,
            "summary": "整体组成与参考人群的差异可以用“组成典型度”理解，但它不是健康评分。",
            "summary_source": "rule",
            "graph": ctx.graph_for(
                ["diversity.reference", "composition.species"],
                ["组成典型度", "菌群组成", "健康人群", "diversity"],
            ),
        })
    else:
        ctx.omit("diversity", "组成典型度", "缺少可用的参考派生分布")

    # 3. Functional backup / stage flow
    fiber = fiber_union(ctx.document)
    fiber_names = [item["name"] for item in fiber["named"]]
    fiber_values = {item["name"]: item["value"] for item in fiber["named"]}

    lactate = aggregate_category(ctx.document, "乳酸利用")
    lactate_names = [item["name"] for item in lactate["contributors"] if item["name"] != "未分类贡献"]
    lactate_values = {item["name"]: item["value"] for item in lactate["contributors"] if item["name"] != "未分类贡献" and item["value"] is not None}
    if not lactate_names:
        fallback = taxonomy_fallback_contributors(ctx.document, {"veillonella"})
        lactate_names = [item["name"] for item in fallback]
        lactate_values = {item["name"]: item["value"] for item in fallback}

    butyrate_agg = aggregate_category(ctx.document, "丁酸合成")
    butyrate_values: dict[str, float] = {
        item["name"]: item["value"] for item in butyrate_agg["contributors"]
        if item["name"] != "未分类贡献" and item["value"] is not None
    }
    species_values = {canonical(row["name"]): row["value"] for row in ctx.species_rows}
    for name in list(butyrate_values):
        abundance = species_values.get(canonical(name))
        if abundance is not None:
            butyrate_values[name] = abundance
    panel = load_panel()
    for category in panel.get("categories", []):
        if category.get("id") != "helpful.butyrate":
            continue
        for row in category_rows(ctx, category):
            butyrate_values.setdefault(row["name"], row["value"])
    butyrate_names = sorted(butyrate_values, key=lambda name: -butyrate_values[name])

    stages = []
    for category, title, names, values, meaning_key in (
        ("fiber", "拆解膳食纤维和淀粉", fiber_names, fiber_values, "functional_potential"),
        ("lactate", "转化中间产物（乳酸利用）", lactate_names, lactate_values, "functional_backup"),
        ("butyrate", "生成丁酸", butyrate_names, butyrate_values, "butyrate_producers"),
    ):
        labels, more, backup, _top = _stage_members(ctx, names, values)
        if not labels:
            ctx.omit("diversity", f"分工：{title}", "现有注释没有可用于该环节的菌种记录")
            continue
        meaning = ctx.glossary.one_liner(meaning_key) if ctx.glossary.is_approved(meaning_key) else ""
        stages.append({
            "title": title,
            "members": labels,
            "more": more,
            "backup_label": backup,
            "meaning": meaning,
        })
    if stages:
        blocks = [
            {"type": "stage_flow", "stages": stages, "footnote": "以上为基因层面的功能潜力，不代表实际产量。"},
            {"type": "paragraph", "text": "同一项工作可以由多种菌分担；某种菌减少时，其他菌仍可能接替。"},
        ]
        summary = "菌群在纤维分解、乳酸周转和丁酸生成上具有不同的分工与备份程度。"
        subsections.append({
            "id": "diversity-division",
            "title": "菌群的分工与“备份”",
            "blocks": blocks,
            "summary": summary,
            "summary_source": "rule",
            "graph": ctx.graph_for(
                ["metabolites.scfa", "nutrient_metabolism.fiber", "metabolites.intermediates"],
                ["丁酸", "乳酸", "膳食纤维"] + [ctx.names.plain(name) for name in fiber_names[:2]],
            ),
        })

    # Consistency audit: the fibre stage uses the same union as nutrition cards.
    if fiber["named"] and stages:
        ctx.omissions.append({
            "section": "diversity",
            "item": "功能分工与纤维底物的一致性",
            "reason": "两处使用同一纤维贡献菌并集，已核对一致",
        })

    return {
        "id": "diversity",
        "nav_label": "多样性",
        "title": "菌群的多样性与分工",
        "intro": "这一部分看菌的种类多少、分布是否均衡，以及菌群如何分工完成纤维分解和丁酸生成。",
        "source_chapters": [2],
        "terms_banner": ["diversity", "shannon", "evenness", "functional_backup"],
        "subsections": subsections,
    }
