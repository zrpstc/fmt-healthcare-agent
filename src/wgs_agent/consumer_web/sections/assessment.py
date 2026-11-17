"""Overall verdicts shown on the overview: pathogen signals and nutrition/metabolism.

Both verdicts are rule-based summaries of findings already shown in the body.
They are not disease risk scores (those are explicitly out of scope).
"""

from __future__ import annotations

from typing import Any

from ..format import count, pct
from ..functions import fiber_contributors, load_substrate_map, load_vitamin_map, vitamin_table
from .context import Context
from .panel import category_total, load_panel, watch_species
from .resistance import high_concern_resistance, resistance_genes
from .virulence import panel_results


def pathogen_assessment(ctx: Context) -> dict[str, Any] | None:
    virulence = ctx.module("virulence")
    completed = virulence.get("status") == "completed" and not ctx.qc_failed
    watch = watch_species(ctx)
    if not completed and not watch:
        return None
    results = panel_results(ctx) if completed else []
    high = [row for row in results if row.get("detected") and row.get("level") == "high"]
    moderate = [row for row in results if row.get("detected") and row.get("level") != "high"]
    markers = virulence.get("markers", []) if isinstance(virulence.get("markers"), list) else []
    genes = resistance_genes(ctx)
    high_resistance = high_concern_resistance(ctx)

    points: list[str] = []
    watch_total = sum(row["value"] for row in watch)
    if watch:
        names = "、".join(ctx.plain_name(row["name"]) for row in watch[:3])
        tail = "等" if len(watch) > 3 else ""
        points.append(f"需留意的菌：检出{names}{tail}{count(len(watch))}种，合计约占{pct(min(100.0, watch_total))}。")
    else:
        points.append("需留意的菌：本次未检出面板中的条件致病菌。")
    if completed:
        if high:
            points.append("高关注毒素基因：检出" + "、".join(str(row.get("name")) for row in high[:3]) + "。")
        else:
            points.append("高关注毒素基因：本次筛查范围内未检出。")
        if moderate:
            points.append("其他重点标志：检出" + "、".join(str(row.get("name")) for row in moderate[:3]) + "。")
        if markers:
            points.append(f"毒力相关基因共检出{count(len(markers))}个，按功能分类见正文。")
    else:
        points.append("毒力基因筛查本次未完成，不能评价致病基因情况。")
    if genes:
        extra = "，其中包含需重点关注的类型" if high_resistance else ""
        points.append(f"耐药基因：检出{count(len(genes))}种{extra}；不等同于药敏试验。")
    from .disease_reference import assessment_point
    reference = assessment_point(ctx)
    if reference:
        points.append(reference)

    if not completed:
        verdict, tone = "不能完整评价", "neutral"
        text = "致病基因筛查未完成，下面只列出需留意的菌。"
    elif high:
        verdict, tone = "需要留意", "consult"
        text = "检出高关注毒素基因；检出不代表正在感染。若有持续腹泻、发热或便血，请就医并带上本报告。"
    elif moderate or high_resistance:
        verdict, tone = "建议关注", "watch"
        text = "未检出高关注毒素基因，但有少量需要留意的标志，可结合身体感受定期复查。"
    else:
        verdict, tone = "未见高关注信号", "good"
        text = "本次筛查范围内没有检出高关注毒素基因；需留意的菌在健康人肠道中也很常见。"
    return {
        "id": "pathogen",
        "title": "致病菌与致病相关基因",
        "verdict": verdict,
        "tone": tone,
        "text": text,
        "points": points,
        "anchor": "#virulence",
    }


def nutrition_metrics(ctx: Context) -> dict[str, Any] | None:
    """Coverage of fibre / vitamin / short-chain fatty acid potential; shared with the health score."""
    from .metabolites import product_score

    fibers = fiber_contributors(ctx.document)
    vitamins = vitamin_table(ctx.document)
    fiber_total = len(load_substrate_map().get("substrates", []))
    vitamin_total = len(load_vitamin_map().get("vitamins", []))
    fiber_count = sum(1 for item in fibers.values() if item["has_signal"])
    vitamin_count = sum(1 for item in vitamins if item["has_signal"])
    scfa = {title: product_score(ctx, title) for title in ("乙酸", "丙酸", "丁酸")}
    scfa_found = {title: item for title, item in scfa.items() if item is not None}
    if not (fiber_count or vitamin_count or scfa_found):
        return None
    covered = fiber_count + vitamin_count + len(scfa_found)
    total = fiber_total + vitamin_total + len(scfa)
    return {
        "ratio": covered / total if total else 0.0,
        "scfa_mean": sum(item["score"] for item in scfa_found.values()) / len(scfa_found) if scfa_found else 0.0,
        "fiber_count": fiber_count, "fiber_total": fiber_total,
        "vitamin_count": vitamin_count, "vitamin_total": vitamin_total,
    }


def nutrition_assessment(ctx: Context) -> dict[str, Any] | None:
    from .metabolites import product_score

    fibers = fiber_contributors(ctx.document)
    vitamins = vitamin_table(ctx.document)
    fiber_total = len(load_substrate_map().get("substrates", []))
    vitamin_total = len(load_vitamin_map().get("vitamins", []))
    fiber_count = sum(1 for item in fibers.values() if item["has_signal"])
    vitamin_count = sum(1 for item in vitamins if item["has_signal"])
    scfa = {title: product_score(ctx, title) for title in ("乙酸", "丙酸", "丁酸")}
    scfa_found = {title: item for title, item in scfa.items() if item is not None}
    if not (fiber_count or vitamin_count or scfa_found):
        return None

    points = [
        f"膳食纤维：{count(fiber_count)}/{count(fiber_total)}类具备分解相关基因。",
        f"维生素：{count(vitamin_count)}/{count(vitamin_total)}种具备合成相关基因。",
    ]
    if scfa_found:
        parts = "、".join(f"{title}{item['score']}分（{item['level']}）" for title, item in scfa_found.items())
        points.append(f"短链脂肪酸潜力评分：{parts}。")
    missing = [title for title, item in scfa.items() if item is None]
    if missing:
        points.append("未检出" + "、".join(missing) + "相关基因。")
    butyrate_total = sum(
        category_total(ctx, c) for c in load_panel().get("categories", []) if c.get("id") == "helpful.butyrate"
    )
    if butyrate_total > 0:
        points.append(f"主要产丁酸菌合计约占{pct(min(100.0, butyrate_total))}。")

    covered = fiber_count + vitamin_count + len(scfa_found)
    total = fiber_total + vitamin_total + len(scfa)
    ratio = covered / total if total else 0
    scfa_mean = sum(item["score"] for item in scfa_found.values()) / len(scfa_found) if scfa_found else 0
    if ratio >= 0.67 and scfa_mean >= 40:
        verdict, tone = "潜力较全面", "good"
        text = "多数纤维分解、维生素合成和短链脂肪酸生成环节都有相关基因，分工较完整。"
    elif ratio >= 0.34 or scfa_mean >= 40:
        verdict, tone = "部分具备", "neutral"
        text = "部分营养代谢环节有相关基因，另一些环节本次没有检出；多样的膳食纤维有助于支持这些功能。"
    else:
        verdict, tone = "潜力有限", "watch"
        text = "多数营养代谢环节本次没有检出相关基因；可从增加膳食纤维种类入手。"
    text += "以上是基因层面的潜力，不代表实际吸收量。"
    return {
        "id": "nutrition",
        "title": "营养与代谢",
        "verdict": verdict,
        "tone": tone,
        "text": text,
        "points": points,
        "anchor": "#nutrition",
    }


def build(ctx: Context) -> list[dict[str, Any]]:
    return [item for item in (pathogen_assessment(ctx), nutrition_assessment(ctx)) if item]
