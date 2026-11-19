"""Disease risk section: MR-weighted score per disease against healthy (and patient) populations.

Score = Σ β × (−lgP) × z (see ``wgs_agent.reporting.disease_risk``).  The score is
shown only as a position among healthy adults; levels are healthy-population
percentile bands (≥P90 偏高, P75–P90 中等, otherwise 较低).  Nothing here is a
probability of disease, and the copy says so.
"""

from __future__ import annotations

import re
from typing import Any

from wgs_agent.reporting.disease_risk import ALPHA_LABELS, display_latin

from ..format import count, sig
from .context import Context

SECTION_ID = "disease-risk"
SYSTEM_ORDER = (
    "消化系统", "内分泌/营养/代谢系统", "循环系统", "神经系统", "精神与行为障碍", "血液及免疫系统",
    "肌肉骨骼/结缔组织系统", "呼吸系统", "皮肤及皮下组织", "眼及附器", "肿瘤", "未分类（多系统疼痛）",
)
# Endpoints that are not diseases (e.g. tobacco use) are not scored for consumers.
EXCLUDED_SYSTEMS = {"健康影响因素（行为因素）"}
LEVEL_TONE = {"high": "watch", "medium": "neutral", "low": "good"}
FEATURED_MAX = 12
FEATURED_PER_SYSTEM = 4


def _slug(system: str) -> str:
    index = SYSTEM_ORDER.index(system) if system in SYSTEM_ORDER else len(SYSTEM_ORDER)
    return f"{SECTION_ID}-s{index + 1:02d}"


def _position(percentile: float, group: str = "健康成人") -> str:
    p = max(0.0, min(100.0, float(percentile)))
    if p >= 99:
        return f"高于99%以上的{group}"
    if p <= 1:
        return f"低于99%以上的{group}"
    if p >= 50:
        return f"高于约{round(p)}%的{group}"
    return f"低于约{round(100 - p)}%的{group}"


def _taxon_label(ctx: Context, feature: str) -> str:
    kind, _, name = feature.partition(":")
    if kind == "alpha":
        return ALPHA_LABELS.get(name, name)
    latin = display_latin(feature)
    plain = ctx.plain_name(latin)
    if plain.startswith("未命名菌") or plain.endswith("的一种"):
        return f"*{latin}*"
    return plain


def _driver(ctx: Context, item: dict) -> str:
    label = _taxon_label(ctx, item["feature"])
    if item["feature"].startswith("alpha:"):
        return label + ("偏高" if item["z"] > 0 else "偏低")
    if item["z"] < 0 and not item.get("detected"):
        return label + "未检出"
    return label + ("偏多" if item["z"] > 0 else "偏少")


def _bands(row: dict) -> list[dict]:
    grid = row["grid"]
    lo, hi = grid[0], grid[-1]
    p75 = min(max(row["healthy"]["p75"], lo), hi)
    p90 = min(max(row["healthy"]["p90"], p75), hi)
    return [
        {"key": "low", "label": "较低", "start": lo, "end": p75},
        {"key": "medium", "label": "中等", "start": p75, "end": p90},
        {"key": "high", "label": "偏高", "start": p90, "end": hi},
    ]


def _distribution(ctx: Context, row: dict) -> dict[str, Any]:
    patients = row.get("patients")
    n_h = row["healthy"]["n"]
    text = (f"您的{row['name_cn']}风险评分为{sig(row['score'])}，{_position(row['percentile_healthy'])}，"
            f"属于“{row['level_label']}”。")
    if patients:
        text += f"与{count(patients['n'])}名{patients['label']}患者相比，您的评分{_position(patients['percentile'], '患者')}。"
    caption = f"绿色为{count(n_h)}名健康成人的评分分布"
    if patients:
        caption += f"，橙色为{count(patients['n'])}名{patients['label']}患者"
    caption += "；虚线为您的位置。评分越高，表示研究提示与该病风险升高相关的菌群特征越明显。"
    share = row["coverage"].get("weight_share") or 0
    if share < 0.5:
        caption += f"该病的研究证据中约{round(share * 100)}%能与本次检测的菌对应，评分参考性有限。"
    you = min(max(row["score"], row["grid"][0]), row["grid"][-1])
    return {
        "type": "risk_distribution",
        "title": row["name_cn"],
        "level": row["level"],
        "level_label": row["level_label"],
        "text": text,
        "score": {"value": round(row["score"], 4), "display": sig(row["score"]), "unit": None},
        "percentile": {"value": round(row["percentile_healthy"], 1), "display": f"{round(row['percentile_healthy'])}%",
                       "unit": "%"},
        "grid": row["grid"],
        "healthy": row["healthy"]["density"],
        "healthy_label": f"健康成人（{count(n_h)}人）",
        "patients": patients["density"] if patients else None,
        "patients_label": f"{patients['label']}患者（{count(patients['n'])}人）" if patients else None,
        "you": you,
        "bands": _bands(row),
        "x_label": "风险评分",
        "drivers": [_driver(ctx, item) for item in row.get("risk_drivers", [])[:3]],
        "caption": caption,
    }


def scored(ctx: Context) -> list[dict]:
    if not ctx.disease_risk_available:
        return []
    return [row for row in ctx.disease_risk.get("diseases", []) if row.get("system") not in EXCLUDED_SYSTEMS]


def assessment(ctx: Context) -> dict[str, Any] | None:
    rows = scored(ctx)
    if not rows:
        return None
    high = sorted((r for r in rows if r["level"] == "high"), key=lambda r: -r["percentile_healthy"])
    medium = [r for r in rows if r["level"] == "medium"]
    if high:
        verdict, tone = "部分偏高", "watch"
        text = "与健康成人相比，以下疾病相关的菌群特征较明显。这只说明菌群特征的位置，不代表已经患病。"
    elif medium:
        verdict, tone = "未见偏高", "neutral"
        text = "没有疾病评分进入健康成人的最高一成，少数处于中等位置。"
    else:
        verdict, tone = "整体较低", "good"
        text = "各疾病评分都处在健康成人的常见范围内。"
    points = [f"评估了{count(len(rows))}种疾病：偏高{count(len(high))}种、中等{count(len(medium))}种。"]
    if high:
        points.append("偏高：" + "、".join(r["name_cn"] for r in high[:3]) + ("等" if len(high) > 3 else "") + "。")
    points.append("评分依据公开的遗传学因果研究，只供参考，不能用于诊断。")
    return {"id": "disease_risk", "title": "疾病风险参考", "verdict": verdict, "tone": tone, "text": text,
            "points": points, "anchor": f"#{SECTION_ID}"}


def _featured(rows: list[dict]) -> set[str]:
    with_patients = [r for r in rows if r.get("patients")]
    high = sorted((r for r in rows if r["level"] == "high"), key=lambda r: -r["percentile_healthy"])
    chosen: list[str] = []
    for row in [*with_patients, *high]:
        if row["id"] not in chosen:
            chosen.append(row["id"])
    return set(chosen[:FEATURED_MAX])


def build(ctx: Context) -> dict[str, Any]:
    rows = scored(ctx)
    section = {
        "id": SECTION_ID,
        "nav_label": "疾病风险",
        "title": "疾病风险评估",
        "intro": ("根据公开的孟德尔随机化研究（一种用遗传数据推断因果方向的方法），"
                  "把与各疾病相关的菌群特征合成一个评分，再看您在健康成人中处于什么位置。评分只是参考，不能用于诊断。"),
        "source_chapters": [],
        "terms_banner": [],
        "subsections": [],
    }
    if not rows:
        reason = (ctx.disease_risk.get("audit") or {}).get("reason_cn") or "疾病风险参考暂不可用"
        ctx.omit(SECTION_ID, "疾病风险评估", reason)
        return section
    n_healthy = rows[0]["healthy"]["n"]
    high = sorted((r for r in rows if r["level"] == "high"), key=lambda r: -r["percentile_healthy"])
    medium = sorted((r for r in rows if r["level"] == "medium"), key=lambda r: -r["percentile_healthy"])
    overview_blocks: list[dict[str, Any]] = [{
        "type": "paragraph",
        "text": (f"每种疾病的评分 = Σ 菌群特征的效应值 × 证据强度 × 您的偏离程度。效应值和证据强度来自芬兰大型人群队列的"
                 f"遗传学因果研究；偏离程度是您每种菌的占比相对{count(n_healthy)}名健康成人平均水平高出或低出多少。"
                 "评分进入健康成人最高一成记为“偏高”，前一成到前四分之一之间记为“中等”，其余为“较低”。"),
    }]
    if high:
        overview_blocks.append({
            "type": "callout",
            "tone": "watch",
            "text": ("您在" + "、".join(r["name_cn"] for r in high[:3]) + ("等" if len(high) > 3 else "")
                     + "上的评分偏高。这说明与这些疾病相关的菌群特征较明显，不代表患病；"
                     "如有相关症状、家族史或体检异常，可带上本报告咨询医生。"),
        })
    if high or medium:
        overview_blocks.append({
            "type": "table",
            "columns": ["疾病", "所属系统", "相对风险", "在健康成人中的位置"],
            "rows": [[r["name_cn"], r["system"], r["level_label"], _position(r["percentile_healthy"])]
                     for r in [*high, *medium]],
            "footnote": f"共评估{count(len(rows))}种疾病，其余{count(len(rows) - len(high) - len(medium))}种为“较低”，按系统列在下面。",
        })
    else:
        overview_blocks.append({
            "type": "paragraph",
            "text": f"共评估{count(len(rows))}种疾病，评分都处在健康成人的常见范围内。",
        })
    section["subsections"].append({
        "id": f"{SECTION_ID}-overview",
        "title": "总体情况",
        "blocks": overview_blocks,
        "summary": "评分高低只反映菌群特征与研究结论的吻合程度；饮食、用药、近期感染都会影响菌群，单次检测不能据此判断疾病。",
        "summary_source": "rule",
        "graph": None,
    })

    featured = _featured(rows)
    systems: dict[str, list[dict]] = {}
    for row in rows:
        systems.setdefault(row["system"], []).append(row)
    order = sorted(systems, key=lambda s: SYSTEM_ORDER.index(s) if s in SYSTEM_ORDER else len(SYSTEM_ORDER))
    for system in order:
        items = sorted(systems[system], key=lambda r: -r["percentile_healthy"])
        blocks: list[dict[str, Any]] = []
        for row in [r for r in items if r["id"] in featured][:FEATURED_PER_SYSTEM]:
            blocks.append(_distribution(ctx, row))
        blocks.append({
            "type": "table",
            "columns": ["疾病", "相对风险", "在健康成人中的位置"],
            "rows": [[r["name_cn"], r["level_label"], _position(r["percentile_healthy"])] for r in items],
            "footnote": "位置指您的评分在健康成人评分中的排位。",
        })
        n_high = sum(1 for r in items if r["level"] == "high")
        summary = (f"这一类中有{count(n_high)}种评分偏高，建议结合自身情况关注。" if n_high
                   else "这一类疾病的评分没有进入健康成人的最高一成。")
        section["subsections"].append({
            "id": _slug(system),
            "title": re.sub(r"（.*?）", "", system) or system,
            "blocks": blocks,
            "summary": summary,
            "summary_source": "rule",
            "graph": None,
        })
    return section


def method_rows(ctx: Context) -> list[tuple[str, str]]:
    if not scored(ctx):
        return []
    audit = ctx.disease_risk.get("audit") or {}
    return [(
        "疾病风险评分",
        ("权重来自肠道菌群对芬兰人群队列（FinnGen 第13版）各疾病的两样本孟德尔随机化结果（逆方差加权法），"
         "只用菌种、菌属丰度和多样性指标中P<0.05的结果。每种疾病评分 = Σ β × (−lgP) × z，"
         "z 为该菌占比取对数后相对健康成人均值的标准分（截断在±4）。名称按菌种改名对照表对应，对应不上的证据不计入。"
         f"健康成人共{count(audit.get('n_healthy') or 0)}人；有公开患者数据的疾病同时给出患者分布。"
         "评分不是患病概率。"),
    )]
