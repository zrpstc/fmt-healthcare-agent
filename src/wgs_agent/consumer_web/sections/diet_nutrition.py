"""Dietary-nutrition section: MR-weighted intake tendency per nutrient and an overall diet score.

Per nutrient, score = Σ β × (−lgP) × z (see ``wgs_agent.reporting.diet_nutrition``),
shown only as a position among healthy adults.  The overall score (0–100) is the
mean of the direction-adjusted percentiles of the nutrients to encourage and to
limit.  None of this is a measured intake, and the copy says so.
"""

from __future__ import annotations

from typing import Any

from ..format import count, tier
from .context import Context
from .disease_risk import _driver, _position

SECTION_ID = "diet-nutrition"
GROUP_ORDER = ("能量与宏量营养素", "脂肪构成", "膳食纤维", "维生素", "矿物质", "酒精")
GROUP_SLUGS = {name: f"{SECTION_ID}-g{i + 1:02d}" for i, name in enumerate(GROUP_ORDER)}
METRIC = {"encourage": "diet_encourage", "limit": "diet_limit", "neutral": "diet_neutral"}
LOW, HIGH = 25.0, 75.0  # healthy-adult percentiles: outside the common middle half

# What to eat more (encourage) or less (limit) of, by UK Biobank nutrient field.
FOODS: dict[str, str] = {
    "100007": "深海鱼、坚果和植物油",
    "100009": "全谷物、豆类、蔬菜和水果",
    "100011": "瘦肉、动物血和深绿色叶菜（搭配富含维生素C的蔬果有助吸收）",
    "100012": "禽肉、鱼、豆类和香蕉",
    "100013": "肉、鱼、蛋和奶",
    "100014": "深绿色叶菜、豆类和柑橘",
    "100015": "新鲜蔬菜和水果，如青椒、猕猴桃、柑橘",
    "100016": "蔬菜、水果、豆类和薯类",
    "100017": "坚果、全谷物和深绿色叶菜",
    "100019": "胡萝卜、南瓜和深绿色、橙黄色蔬菜",
    "100021": "深海鱼和蛋黄，并适量晒太阳",
    "100024": "奶及奶制品、豆制品和深绿色叶菜",
    "100025": "植物油、坚果和种子",
    "100006": "肥肉、黄油、油炸食品和加工肉",
    "100008": "含糖饮料、甜点和糖果",
    "100022": "各类酒精饮料",
}
DRINKS = {"100022"}


def _advice(row: dict) -> str:
    if row["direction"] == "limit":
        return ("可以少喝" if row["id"] in DRINKS else "可以少吃") + FOODS[row["id"]]
    return "可以多吃" + FOODS[row["id"]]


def scored(ctx: Context) -> list[dict]:
    if not ctx.diet_nutrition_available:
        return []
    return list(ctx.diet_nutrition.get("nutrients", []))


def _flags(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Nutrients to eat more of (encourage, low tendency) and less of (limit, high tendency)."""
    more = sorted((r for r in rows if r["direction"] == "encourage" and r["percentile_healthy"] < LOW),
                  key=lambda r: r["percentile_healthy"])
    less = sorted((r for r in rows if r["direction"] == "limit" and r["percentile_healthy"] > HIGH),
                  key=lambda r: -r["percentile_healthy"])
    return more, less


def _names(rows: list[dict], limit: int = 4) -> str:
    return "、".join(r["name_cn"] for r in rows[:limit]) + ("等" if len(rows) > limit else "")


def _drivers(ctx: Context, row: dict) -> list[str]:
    items = row.get("raising", []) if row["percentile_healthy"] >= 50 else row.get("lowering", [])
    return [_driver(ctx, item) for item in items[:3]]


def _nutrient_row(ctx: Context, row: dict) -> dict[str, Any]:
    note_parts = []
    drivers = _drivers(ctx, row)
    if drivers:
        note_parts.append("主要相关菌：" + "、".join(drivers) + "。")
    share = (row.get("coverage") or {}).get("weight_share") or 0
    if share < 0.5:
        note_parts.append(f"相关研究证据中约{round(share * 100)}%能与本次检测的菌对应，参考性有限。")
    return {
        "label": row["name_cn"],
        "value": {"value": round(row["percentile_healthy"], 1), "display": "", "unit": None},
        "tier": tier(row["percentile_healthy"], metric=METRIC[row["direction"]]),
        "note": "".join(note_parts) or None,
    }


def assessment(ctx: Context) -> dict[str, Any] | None:
    rows = scored(ctx)
    overall = ctx.diet_nutrition.get("overall") if rows else None
    if not overall:
        return None
    t = tier(overall["percentile_healthy"], metric="diet_overall")
    more, less = _flags(rows)
    if t.key in {"high", "very_high"}:
        verdict, tone = "整体较好", "good"
        text = "菌群特征提示的饮食结构较接近健康膳食。"
    elif t.key == "typical":
        verdict, tone = "中等", "neutral"
        text = "菌群特征提示的饮食结构处在健康成人的常见范围。"
    else:
        verdict, tone = "可以改善", "watch"
        text = "菌群特征提示饮食中鼓励多吃的营养素偏少，或需要限制的偏多。"
    points = [f"膳食营养综合评分{round(overall['score'])}分，{_position(overall['percentile_healthy'])}。"]
    if more:
        points.append("建议增加" + _names(more) + "的食物来源。")
    if less:
        points.append("建议减少" + _names(less) + "的摄入。")
    points.append("评分是根据菌群推测的倾向，不是实际摄入量。")
    return {"id": "diet_nutrition", "title": "膳食营养倾向", "verdict": verdict, "tone": tone, "text": text,
            "points": points, "anchor": f"#{SECTION_ID}"}


def _overview(ctx: Context, rows: list[dict]) -> dict[str, Any]:
    overall = ctx.diet_nutrition.get("overall")
    more, less = _flags(rows)
    n_healthy = rows[0]["healthy"]["n"]
    blocks: list[dict[str, Any]] = [{
        "type": "paragraph",
        "text": ("每种营养素的倾向分 = Σ 菌群特征的效应值 × 证据强度 × 您的偏离程度。效应值和证据强度来自英国大型人群队列"
                 "膳食记录的遗传学因果研究；偏离程度是您每种菌的占比相对"
                 f"{count(n_healthy)}名健康成人平均水平高出或低出多少。分数越高，表示与该营养素摄入较多相关的菌群特征越明显。"),
    }]
    if overall:
        blocks.append({"type": "tier_scales", "rows": [{
            "label": "膳食营养综合评分",
            "value": {"value": overall["score"], "display": f"{round(overall['score'])}分", "unit": "分"},
            "tier": tier(overall["percentile_healthy"], metric="diet_overall"),
            "note": (f"综合了{count(overall['n_nutrients'])}种营养素：膳食纤维、维生素、矿物质等鼓励多吃的营养素倾向越高，"
                     "饱和脂肪、糖和酒精等需要限制的倾向越低，得分越高。能量、蛋白质等总量类指标只展示，不计入。"),
        }]})
    if more or less:
        table_rows = [[r["name_cn"], "偏低", _advice(r)] for r in more if r["id"] in FOODS]
        table_rows += [[r["name_cn"], "偏高", _advice(r)] for r in less if r["id"] in FOODS]
        if table_rows:
            blocks.append({
                "type": "table",
                "columns": ["营养素", "菌群提示的倾向", "饮食建议"],
                "rows": table_rows,
                "footnote": "建议依据一般膳食指南；如有慢性病、过敏或特殊饮食需求，请先咨询医生或营养师。",
            })
    else:
        blocks.append({"type": "paragraph",
                       "text": "鼓励多吃和需要限制的营养素，倾向都处在健康成人的常见范围内。"})
    return {
        "id": f"{SECTION_ID}-overview",
        "title": "总体情况",
        "blocks": blocks,
        "summary": "这是根据菌群特征推测的饮食倾向，不是实际吃了多少；想了解实际摄入，可以记录几天的饮食或咨询营养师。",
        "summary_source": "rule",
        "graph": None,
    }


def build(ctx: Context) -> dict[str, Any]:
    rows = scored(ctx)
    section = {
        "id": SECTION_ID,
        "nav_label": "膳食营养",
        "title": "膳食营养评分",
        "intro": ("菌群会随长期饮食而改变。根据公开的孟德尔随机化研究（一种用遗传数据推断因果方向的方法），"
                  "把与各营养素摄入相关的菌群特征合成倾向分，再看您在健康成人中处于什么位置。结果只供参考。"),
        "source_chapters": [],
        "terms_banner": [],
        "subsections": [],
    }
    if not rows:
        reason = (ctx.diet_nutrition.get("audit") or {}).get("reason_cn") or "膳食营养参考暂不可用"
        ctx.omit(SECTION_ID, "膳食营养评分", reason)
        return section
    section["subsections"].append(_overview(ctx, rows))
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["group"], []).append(row)
    for group in sorted(groups, key=lambda g: GROUP_ORDER.index(g) if g in GROUP_ORDER else len(GROUP_ORDER)):
        items = groups[group]
        high = [r["name_cn"] for r in items if r["percentile_healthy"] > HIGH]
        low = [r["name_cn"] for r in items if r["percentile_healthy"] < LOW]
        parts = []
        if high:
            parts.append("、".join(high) + "倾向偏高")
        if low:
            parts.append("、".join(low) + "倾向偏低")
        summary = ("；".join(parts) + "。") if parts else "这一类营养素的倾向都处在健康成人的常见范围。"
        section["subsections"].append({
            "id": GROUP_SLUGS.get(group, f"{SECTION_ID}-g{len(section['subsections']):02d}"),
            "title": group,
            "blocks": [{"type": "tier_scales", "rows": [_nutrient_row(ctx, r) for r in items]}],
            "summary": summary,
            "summary_source": "rule",
            "graph": None,
        })
    return section


def method_rows(ctx: Context) -> list[tuple[str, str]]:
    if not scored(ctx):
        return []
    audit = ctx.diet_nutrition.get("audit") or {}
    return [(
        "膳食营养评分",
        ("权重来自肠道菌群对英国生物样本库（UK Biobank）24小时膳食回顾中22种营养素估算值的两样本孟德尔随机化结果（逆方差加权法），"
         "只用菌种、菌属丰度和多样性指标中P<0.05的结果。每种营养素倾向分 = Σ β × (−lgP) × z，"
         "z 为该菌占比取对数后相对健康成人均值的标准分（截断在±4）。综合评分为鼓励类营养素的百分位与限制类营养素“100减百分位”的平均值。"
         f"健康成人共{count(audit.get('n_healthy') or 0)}人。这些研究结果经多重检验校正后只有少数仍然显著，"
         "评分反映的是菌群特征与饮食研究结论的吻合程度，不是实际摄入量，也不能替代膳食调查。"),
    )]
