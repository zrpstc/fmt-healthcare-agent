"""Overview section: headline, status cards and the three key findings."""

from __future__ import annotations

from typing import Any

from ..format import count, number, pct, tier
from ..narrative import headline
from . import assessment
from .context import Context
from .panel import category_total, load_panel
from .resistance import resistance_genes
from .virulence import high_concern_results


def _diversity_row(ctx: Context, metric: str = "richness") -> dict | None:
    rows = ctx.healthy_comparison.get("diversity", [])
    if isinstance(rows, list):
        for row in rows:
            if row.get("metric") == metric:
                return row
    return None


def _beneficial_total(ctx: Context) -> float:
    panel = load_panel()
    return sum(category_total(ctx, c) for c in panel.get("categories", []) if c.get("section") == "helpful")


def _watch_total(ctx: Context) -> float:
    panel = load_panel()
    return sum(category_total(ctx, c) for c in panel.get("categories", []) if c.get("section") == "watch")


def build(ctx: Context) -> dict[str, Any]:
    diversity = _diversity_row(ctx)
    cards: list[dict[str, Any]] = []
    if diversity and diversity.get("percentile") is not None:
        t = tier(diversity["percentile"], metric="richness", borderline=bool(diversity.get("borderline")))
        value = float(diversity.get("value") or 0)
        shannon = _diversity_row(ctx, "shannon")
        shannon_text = ""
        if shannon and shannon.get("value") is not None:
            shannon_text = f"香农指数{number(float(shannon['value']))}；"
        cards.append({
            "id": "diversity",
            "label": "菌群多样性",
            "tier_label": t.label,
            "tone": t.tone,
            "line": f"检出{count(value)}种菌，{shannon_text}菌种数{t.phrase}。",
            "anchor": "#diversity",
        })
    elif ctx.species_rows:
        cards.append({
            "id": "diversity",
            "label": "菌群多样性",
            "tier_label": f"{count(len(ctx.species_rows))}种",
            "tone": "neutral",
            "line": f"本次检出{count(len(ctx.species_rows))}种菌。",
            "anchor": "#diversity",
        })

    beneficial = _beneficial_total(ctx)
    if beneficial > 0:
        cards.append({
            "id": "beneficial",
            "label": "有益菌",
            "tier_label": f"合计 {pct(beneficial)}",
            "tone": "neutral",
            "line": "双歧杆菌、乳杆菌类、产丁酸菌与阿克曼菌合计占比，供结合参考人群理解。",
            "anchor": "#key-taxa",
        })

    watch = _watch_total(ctx)
    if watch > 0:
        cards.append({
            "id": "watch",
            "label": "需留意的菌",
            "tier_label": f"合计 {pct(watch)}",
            "tone": "watch",
            "line": "脆弱拟杆菌、大肠埃希菌、艰难梭菌等合计占比；它们也可出现在健康人肠道中。",
            "anchor": "#key-taxa",
        })

    high = high_concern_results(ctx)
    if high:
        names = "、".join(str(row.get("name") or "") for row in high[:2])
        cards.append({
            "id": "virulence",
            "label": "致病相关基因",
            "tier_label": f"检出{count(len(high))}项高关注毒素",
            "tone": "watch",
            "line": f"检出{names}相关基因，需结合菌株与临床情况理解。",
            "anchor": "#virulence",
        })
    elif ctx.module("virulence").get("status") == "completed":
        cards.append({
            "id": "virulence",
            "label": "致病相关基因",
            "tier_label": "未检出高关注毒素",
            "tone": "neutral",
            "line": "本次筛查范围内未检出高关注毒素基因。",
            "anchor": "#virulence",
        })

    genes = resistance_genes(ctx)
    if genes:
        cards.append({
            "id": "resistance",
            "label": "耐药基因",
            "tier_label": f"检出{count(len(genes))}种",
            "tone": "neutral",
            "line": "检出获得性耐药基因，对应药物类别见后文；不等同于药敏试验。",
            "anchor": "#resistance",
        })
    elif ctx.module("resistance").get("status") == "completed":
        cards.append({
            "id": "resistance",
            "label": "耐药基因",
            "tier_label": "未检出获得性耐药基因",
            "tone": "neutral",
            "line": "本次检测范围内未检出获得性耐药基因。",
            "anchor": "#resistance",
        })

    # Nutrition potential: count substrate and vitamin signals.
    from ..functions import fiber_contributors, load_substrate_map, load_vitamin_map, vitamin_table
    fibers = fiber_contributors(ctx.document)
    vitamins = vitamin_table(ctx.document)
    fiber_count = sum(1 for item in fibers.values() if item["has_signal"])
    vitamin_count = sum(1 for item in vitamins if item["has_signal"])
    fiber_total = len(load_substrate_map().get("substrates", []))
    vitamin_total = len(load_vitamin_map().get("vitamins", []))
    if fiber_count or vitamin_count:
        cards.append({
            "id": "nutrition",
            "label": "营养潜力",
            "tier_label": f"纤维{count(fiber_count)}/{count(fiber_total)} · 维生素{count(vitamin_count)}/{count(vitamin_total)}",
            "tone": "neutral",
            "line": f"{count(fiber_count)}类纤维和{count(vitamin_count)}种维生素显示相关基因潜力。",
            "anchor": "#nutrition",
        })

    # Findings: consult -> watch -> good, at least one positive.
    findings: list[dict[str, Any]] = []
    if high:
        first = high[0]
        findings.append({
            "rank": 1,
            "tone": "consult",
            "title": f"检出{first.get('name')}相关基因",
            "big": {"value": 1, "display": "1", "unit": "项"},
            "compare": "本次筛查范围内检出",
            "meaning": "检出不代表正在发生感染。若有持续腹泻、发热或便血，请就医并带上本报告。",
            "anchor": "#virulence",
        })
    if diversity and diversity.get("percentile") is not None:
        t = tier(diversity["percentile"], metric="richness", borderline=bool(diversity.get("borderline")))
        findings.append({
            "rank": len(findings) + 1,
            "tone": "watch" if t.tone == "watch" else "neutral",
            "title": "菌种数偏少",
            "big": {"value": float(diversity.get("value") or 0), "display": count(diversity.get("value") or 0), "unit": "种"},
            "compare": t.phrase,
            "meaning": "菌种较少时，菌群对饮食和外界变化的缓冲可能更有限；这不等于疾病。",
            "anchor": "#diversity",
        })
    butyrate_total = sum(
        category_total(ctx, c) for c in load_panel().get("categories", []) if c.get("id") == "helpful.butyrate"
    )
    if butyrate_total > 0:
        findings.append({
            "rank": len(findings) + 1,
            "tone": "good",
            "title": "检出主要产丁酸菌",
            "big": {"value": butyrate_total, "display": pct(butyrate_total), "unit": "%"},
            "compare": "普拉梭菌与罗氏菌合计",
            "meaning": "这类菌能把膳食纤维转化为丁酸，丁酸是结肠细胞的重要能量来源。",
            "anchor": "#key-taxa",
        })
    # Ensure three findings and a positive if one exists.
    if len(findings) < 3 and genes:
        findings.append({
            "rank": len(findings) + 1,
            "tone": "neutral",
            "title": "检出获得性耐药基因",
            "big": {"value": len(genes), "display": count(len(genes)), "unit": "种"},
            "compare": "对应四环素类",
            "meaning": "这提示样本中的细菌携带耐药相关基因，不等同于药物无效。",
            "anchor": "#resistance",
        })
    findings = findings[:3]
    positive = next((item["title"] for item in findings if item["tone"] == "good"), "")
    watch_phrase = next((item["title"] for item in findings if item["tone"] in {"consult", "watch"}), "")
    text = headline(positive, watch_phrase)

    return {
        "summary": {
            "headline": text,
            "headline_source": "rule",
            "status_cards": cards[:6],
            "key_findings": findings,
            "assessments": assessment.build(ctx),
        }
    }
