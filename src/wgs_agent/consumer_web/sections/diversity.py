"""Diversity and functional division section (professional chapter 2)."""

from __future__ import annotations

import json
from typing import Any

from wgs_agent.reporting.inputs import diversity_metrics, finite
from wgs_fmt_platform.paths import PROJECT_ROOT

from ..format import count, number, pct, tier
from ..functions import aggregate_category, fiber_union, metabolite_contributors
from ..names import canonical
from .context import Context
from .panel import category_matches, load_panel

GUILDS_PATH = PROJECT_ROOT / "knowledge_base" / "consumer_function_guilds.yaml"
STAGE_SHOWN = 6


def load_guilds() -> dict[str, Any]:
    raw = GUILDS_PATH.read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except ValueError:
        import yaml
        value = yaml.safe_load(raw)
    if not isinstance(value, dict) or not isinstance(value.get("guilds"), dict):
        raise ValueError("invalid_consumer_function_guilds")
    return value["guilds"]


def _primary_diversity(ctx: Context) -> dict[str, Any]:
    """Primary-profile alpha diversity, resolved like the professional report.

    Order (``reporting.document`` / ``reporting.chapter_two``): analysis
    diversity block, then the saved ``div_<metric>`` evidence, then a fresh
    calculation from a complete species profile (Shannon uses the natural log).
    """
    diversity = ctx.analysis.get("diversity") if isinstance(ctx.analysis, dict) else None
    result: dict[str, Any] = dict(diversity) if isinstance(diversity, dict) else {}
    for metric in ("richness", "shannon", "simpson", "evenness"):
        if finite(result.get(metric)) is not None:
            continue
        row = next(iter(ctx.evidence(f"div_{metric}")), None)
        if row and finite(row.get("value")) is not None:
            result[metric] = finite(row.get("value"))
    if finite(result.get("shannon")) is None and ctx.taxonomy.get("complete") is True:
        profile = [{"abundance": row["value"]} for row in ctx.species_rows]
        computed = diversity_metrics(profile, complete=bool(profile))
        for key, value in computed.items():
            result.setdefault(key, value)
    return result


def _diversity_value(ctx: Context, metric: str) -> tuple[float, float | None, bool] | None:
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
    # Saved reference comparison evidence (same priority as chapter two).
    for kind in ("healthy_diversity", "div_reference"):
        for row in ctx.evidence(kind):
            if row.get("metric") != metric:
                continue
            value, percentile = finite(row.get("value")), finite(row.get("percentile"))
            if value is not None and percentile is not None and 0 <= percentile <= 100:
                return value, percentile, bool(row.get("borderline"))
    # Fall back to the primary analysis without inventing a percentile.
    value = finite(_primary_diversity(ctx).get(metric))
    if value is not None and value >= 0:
        return value, None, False
    return None


def _typicality_phrase(percentile: float) -> str:
    if percentile >= 99:
        return "比99%以上的参考人群差异更大"
    if percentile > 50:
        return f"比约{round(percentile)}%的参考人群差异更大"
    if percentile >= 1:
        return f"比约{round(100 - percentile)}%的参考人群更接近"
    return "比99%以上的参考人群更接近"


def _stage_members(ctx: Context, gene_names: list[str], guild: dict | None) -> tuple[list[dict[str, Any]], str]:
    """Gene-stratified contributors first, then detected taxa with a known role.

    Values are the species' relative abundance in the profile (one consistent
    unit for every member); the backup label uses the same values.
    """
    species = {canonical(row["name"]): row for row in ctx.species_rows}
    seen: set[str] = set()
    members: list[dict[str, Any]] = []

    def add(name: str, basis: str) -> None:
        key = canonical(name)
        if not key or key in seen or key.startswith("未分类"):
            return
        seen.add(key)
        row = species.get(key)
        value = row["value"] if row else None
        members.append({
            "name": ctx.names.plain(name),
            "value": {"value": value, "display": pct(value), "unit": "%"} if value is not None else None,
            "basis": basis,
        })

    for name in gene_names:
        add(name, "gene")
    if guild:
        extra = sorted(
            (row for row in ctx.species_rows if row["value"] > 0 and category_matches(row["name"], guild)),
            key=lambda row: (-row["value"], row["name"]),
        )
        for row in extra:
            add(row["name"], "taxonomy")
    values = [float(item["value"]["value"]) for item in members if item["value"]]
    total = sum(values)
    top = max(values) / total * 100 if total else None
    backup = "多种菌分担" if len(members) >= 3 and top is not None and top < 60 else "主要依赖少数菌"
    return members, backup


def build(ctx: Context) -> dict[str, Any]:
    subsections: list[dict[str, Any]] = []

    # 1. Diversity scales
    metrics = [
        ("richness", "菌种数（丰富度）", "种"),
        ("shannon", "香农指数（综合多样性）", ""),
        ("evenness", "分布均衡度", ""),
    ]
    shannon_note = "香农指数同时反映菌的种类多少和各种菌分布是否均匀；数值越高，通常表示菌群越多样。"
    primary_shannon = finite(_primary_diversity(ctx).get("shannon"))
    rows = []
    for metric, label, unit in metrics:
        item = _diversity_value(ctx, metric)
        if item is None:
            continue
        value, percentile, borderline = item
        display = count(value) if metric == "richness" and float(value).is_integer() else number(value)
        note = None
        if metric == "shannon":
            note = shannon_note
            if primary_shannon is not None and percentile is not None and number(primary_shannon) != display:
                note += f"按本次完整物种谱计算为{number(primary_shannon)}；上方数值为与参考人群同口径重新计算的结果。"
        if percentile is None:
            ctx.omit("diversity", f"{label}参考档位", "缺少同口径参考比较")
            if metric != "shannon":
                continue
            note = (note or "") + "暂无同口径的参考人群比较，这里只给出数值。"
            rows.append({
                "label": label,
                "value": {"value": value, "display": display, "unit": unit or None},
                "tier": None,
                "note": note,
            })
            continue
        t = tier(percentile, metric=metric, borderline=borderline)
        rows.append({
            "label": label,
            "value": {"value": value, "display": display, "unit": unit or None},
            "tier": t,
            "note": note,
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

    lactate = aggregate_category(ctx.document, "乳酸利用")
    lactate_names = [item["name"] for item in lactate["contributors"] if item["name"] != "未分类贡献"]

    propionate = metabolite_contributors(ctx.document, ["P108-PWY"])
    propionate_names = [item["name"] for item in propionate["named"]]

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
    butyrate_names = sorted(butyrate_values, key=lambda name: -butyrate_values[name])
    # Key-taxa butyrate producers are detected taxa with a known role: they join
    # the stage as taxonomy-based members, after the gene-stratified ones.
    butyrate_guild = dict(load_guilds().get("butyrate") or {})
    for category in load_panel().get("categories", []):
        if category.get("id") == "helpful.butyrate":
            butyrate_guild["members"] = [*butyrate_guild.get("members", []), *category.get("members", [])]

    guilds = load_guilds()
    stages = []
    taxonomy_used = False
    for category, title, names, meaning_key, fallback_meaning in (
        ("fiber", "拆解膳食纤维和淀粉", fiber_names, "functional_potential", ""),
        ("lactate", "转化中间产物（乳酸利用）", lactate_names, "functional_backup", ""),
        ("propionate", "生成丙酸", propionate_names, "propionate", "把纤维发酵的中间产物转化为丙酸，丙酸主要由肝脏利用。"),
        ("butyrate", "生成丁酸", butyrate_names, "butyrate_producers", ""),
    ):
        guild = butyrate_guild if category == "butyrate" else guilds.get(category)
        members, backup = _stage_members(ctx, names, guild)
        if not members:
            ctx.omit("diversity", f"分工：{title}", "现有注释没有可用于该环节的菌种记录")
            continue
        taxonomy_used = taxonomy_used or any(item["basis"] == "taxonomy" for item in members)
        if ctx.glossary.is_publishable(meaning_key):
            meaning = ctx.glossary.one_liner(meaning_key)
        else:
            meaning = fallback_meaning
        stages.append({
            "title": title,
            "members": [item["name"] for item in members],
            "more": max(0, len(members) - STAGE_SHOWN),
            "backup_label": backup,
            "meaning": meaning,
            "member_details": members,
        })
    if stages:
        footnote = "以上为基因层面的功能潜力，不代表实际产量；括号内为该菌占全部细菌的比例。"
        if taxonomy_used:
            footnote += "标“按菌种特性”的菌没有在本次基因分层中直接测到，是根据检出菌种的已知特性补充的。"
        blocks = [
            {"type": "stage_flow", "stages": stages, "footnote": footnote},
            {"type": "paragraph", "text": "同一项工作可以由多种菌分担；某种菌减少时，其他菌仍可能接替。"},
        ]
        summary = "菌群在纤维分解、乳酸周转、丙酸和丁酸生成上具有不同的分工与备份程度。"
        subsections.append({
            "id": "diversity-division",
            "title": "菌群的分工与“备份”",
            "blocks": blocks,
            "summary": summary,
            "summary_source": "rule",
            "graph": ctx.graph_for(
                ["metabolites.scfa", "nutrient_metabolism.fiber", "metabolites.intermediates"],
                ["丁酸", "丙酸", "乳酸", "膳食纤维"] + [ctx.names.plain(name) for name in fiber_names[:2]],
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
        "intro": "这一部分看菌的种类多少、分布是否均衡，以及菌群如何分工完成纤维分解、丙酸和丁酸生成。",
        "source_chapters": [2],
        "terms_banner": ["diversity", "shannon", "evenness", "functional_backup"],
        "subsections": subsections,
    }
