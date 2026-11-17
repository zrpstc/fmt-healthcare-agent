"""Overall gut-health score (0-100) for the overview.

A transparent weighted average of component scores that are each derived from
results already shown in the body.  Missing components are dropped and the
remaining weights renormalised; with fewer than three components no score is
shown.  The score is a management/retest aid, not a diagnosis or a probability.

Components (weight):

* diversity (25): Shannon percentile in the healthy reference; at or above the
  median earns 100, falling linearly to 30 at the lowest percentile;
* similarity (25): health-index probability of resembling the healthy cohort
  rather than the pooled disease cohorts (x100); without the cohort model, the
  composition typicality percentile (<=75 earns 100, falling to 40 at 100);
* nutrition (20): 50% fibre/vitamin/SCFA coverage + 50% mean SCFA potential score;
* safety (20): starts at 100, deductions for high-concern toxin genes, other
  marker genes, the combined share of watch taxa and resistance genes;
* gut age (10): only when the chronological age is known; younger than or equal
  to the age-typical value earns 100, -5 per year older, floor 30.
"""
from __future__ import annotations

from typing import Any

from ..format import count, percentile_phrase
from .assessment import nutrition_metrics
from .context import Context
from .panel import watch_species
from .resistance import high_concern_resistance, resistance_genes
from .virulence import panel_results

WEIGHTS = {"diversity": 25, "similarity": 25, "nutrition": 20, "safety": 20, "gut_age": 10}
MIN_COMPONENTS = 3


def grade(score: float) -> tuple[str, str]:
    if score >= 80:
        return "良好", "good"
    if score >= 65:
        return "中等", "neutral"
    if score >= 50:
        return "需关注", "watch"
    return "需重点关注", "consult"


def _tone(score: float) -> str:
    return grade(score)[1]


def _num(score: float) -> dict:
    value = int(round(max(0.0, min(100.0, score))))
    return {"value": float(value), "display": str(value), "unit": "分"}


def _diversity(ctx: Context) -> dict | None:
    rows = {row.get("metric"): row for row in ctx.healthy_comparison.get("diversity", []) or [] if isinstance(row, dict)}
    row = rows.get("shannon") or rows.get("richness")
    if not row or row.get("percentile") is None:
        return None
    p = float(row["percentile"])
    score = 100.0 if p >= 50 else 30.0 + 70.0 * p / 50.0
    name = "香农指数" if row.get("metric") == "shannon" else "菌种数"
    return {"score": score, "text": f"{name}{percentile_phrase(p)}。", "anchor": "#diversity"}


def _similarity(ctx: Context) -> dict | None:
    if ctx.cohort_available and isinstance(ctx.cohort.get("health_index"), dict):
        index = ctx.cohort["health_index"]
        probability = float(index["probability_healthy"])
        text = (f"菌群整体特征与{count(index['n_healthy'])}名健康成人、{count(index['n_disease'])}名患者的公开数据比较，"
                f"更像健康人群的程度约为{round(probability * 100)}%。")
        return {"score": 100.0 * probability, "text": text, "anchor": "#gut-profile"}
    typicality = ctx.healthy_comparison.get("typicality")
    if isinstance(typicality, dict) and typicality.get("percentile") is not None:
        p = float(typicality["percentile"])
        score = 100.0 if p <= 75 else 100.0 - 60.0 * (p - 75) / 25
        return {"score": score, "text": "按与健康参考者的整体组成差异评估，差异越小得分越高。", "anchor": "#composition"}
    return None


def _nutrition(ctx: Context) -> dict | None:
    metrics = nutrition_metrics(ctx)
    if not metrics:
        return None
    score = 100.0 * (0.5 * metrics["ratio"] + 0.5 * metrics["scfa_mean"] / 100.0)
    text = (f"膳食纤维分解{count(metrics['fiber_count'])}/{count(metrics['fiber_total'])}类、"
            f"维生素合成{count(metrics['vitamin_count'])}/{count(metrics['vitamin_total'])}种具备相关基因，"
            f"短链脂肪酸平均潜力{round(metrics['scfa_mean'])}分。")
    return {"score": score, "text": text, "anchor": "#nutrition"}


def _safety(ctx: Context) -> dict | None:
    completed = ctx.module("virulence").get("status") == "completed" and not ctx.qc_failed
    watch = watch_species(ctx)
    genes = resistance_genes(ctx)
    if not completed and not watch and not genes:
        return None
    score = 100.0
    reasons = []
    if completed:
        results = panel_results(ctx)
        high = [row for row in results if row.get("detected") and row.get("level") == "high"]
        moderate = [row for row in results if row.get("detected") and row.get("level") != "high"]
        if high:
            score -= min(60.0, 40.0 + 10.0 * (len(high) - 1))
            reasons.append(f"检出{count(len(high))}项高关注毒素基因")
        if moderate:
            score -= min(20.0, 10.0 * len(moderate))
            reasons.append(f"{count(len(moderate))}项其他重点标志")
    total = sum(row["value"] for row in watch)
    if total > 10:
        score -= 20
    elif total > 3:
        score -= 10
    elif total > 1:
        score -= 5
    if watch:
        reasons.append(f"需留意的菌{count(len(watch))}种")
    if high_concern_resistance(ctx):
        score -= 15
        reasons.append("含需重点关注的耐药类型")
    elif genes:
        score -= 5
        reasons.append(f"耐药基因{count(len(genes))}种")
    text = ("扣分项：" + "、".join(reasons) + "。") if reasons else "本次筛查范围内未见需要扣分的信号。"
    if not completed:
        text += "毒力基因筛查未完成，只按菌种和耐药基因评估。"
    return {"score": max(0.0, score), "text": text, "anchor": "#virulence"}


def _gut_age(ctx: Context) -> dict | None:
    if not ctx.cohort_available:
        return None
    age = ctx.cohort.get("gut_age") or {}
    gap = age.get("gap")
    if gap is None:
        return None
    gap = float(gap)
    score = 100.0 if gap <= 0 else max(30.0, 100.0 - 5.0 * gap)
    if abs(gap) < 3:
        text = "肠道年龄与同龄人的典型值相近。"
    elif gap < 0:
        text = f"肠道年龄比同龄人的典型值年轻约{round(abs(gap))}岁。"
    else:
        text = f"肠道年龄比同龄人的典型值大约{round(gap)}岁。"
    return {"score": score, "text": text, "anchor": "#gut-profile"}


LABELS = {
    "diversity": "菌群多样性",
    "similarity": "与健康人群的相似度",
    "nutrition": "营养代谢潜力",
    "safety": "致病与耐药信号",
    "gut_age": "肠道年龄",
}


def build(ctx: Context) -> dict[str, Any] | None:
    builders = {"diversity": _diversity, "similarity": _similarity, "nutrition": _nutrition,
                "safety": _safety, "gut_age": _gut_age}
    components = []
    for key, function in builders.items():
        try:
            item = function(ctx)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            item = None
        if item is None:
            continue
        components.append({"id": key, "label": LABELS[key], "score": _num(item["score"]), "weight": WEIGHTS[key],
                           "tone": _tone(item["score"]), "text": item["text"], "anchor": item["anchor"]})
    if len(components) < MIN_COMPONENTS or not {"diversity", "similarity"} & {c["id"] for c in components}:
        ctx.omit("overview", "总体健康得分", "可用于评分的方面不足三项，未计算总体得分")
        return None
    weight = sum(c["weight"] for c in components)
    score = sum(c["score"]["value"] * c["weight"] for c in components) / weight
    label, tone = grade(score)
    names = "、".join(c["label"] for c in components)
    missing = [LABELS[key] for key in WEIGHTS if key not in {c["id"] for c in components}]
    text = f"综合{names}{count(len(components))}个方面，按权重加权得到。"
    if missing:
        text += "本次缺少" + "、".join(missing) + "的结果，其权重按比例分配给其他方面。"
    return {
        "score": _num(score),
        "grade": label,
        "tone": tone,
        "text": text,
        "components": components,
        "note": "80分以上为良好，65至79分为中等，50至64分为需关注，50分以下为需重点关注。得分用于健康管理和复测对比，不是疾病诊断或患病概率。",
    }
