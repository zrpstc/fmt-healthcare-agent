"""Gut age and enterotype section, from the cMD cohort models."""

from __future__ import annotations

from typing import Any

from ..format import count, number, pct
from .context import Context

GENUS_NAMES = {
    "bacteroides": "拟杆菌属",
    "phocaeicola": "Phocaeicola属（拟杆菌近缘）",
    "prevotella": "普雷沃菌属",
    "segatella": "Segatella属（普雷沃菌近缘）",
    "faecalibacterium": "粪杆菌属",
    "ruminococcus": "瘤胃球菌属",
    "alistipes": "另枝菌属",
    "bifidobacterium": "双歧杆菌属",
}
ENTEROTYPE_ORDER = ("ET-B", "ET-P", "ET-F")
ENTEROTYPE_NOTES = {
    "ET-B": "拟杆菌型在饮食中动物蛋白和脂肪较多的人群里更常见。",
    "ET-P": "普雷沃菌型在以谷物、蔬菜等植物性食物为主的人群里更常见。",
    "ET-F": "厚壁菌型以瘤胃球菌科等厚壁菌为主，这类人群的菌种多样性通常较高。",
}


def age_phrase(gap: float | None) -> str:
    if gap is None:
        return ""
    if abs(gap) < 3:
        return "与同龄人的典型值相近"
    if gap < 0:
        return f"比同龄人的典型值年轻约{round(abs(gap))}岁"
    return f"比同龄人的典型值大约{round(gap)}岁"


def age_tone(gap: float | None) -> str:
    if gap is None or abs(gap) < 3:
        return "neutral"
    return "good" if gap < 0 else "watch"


def confidence_phrase(confidence: float) -> str:
    if confidence >= 0.3:
        return "归类较明确"
    if confidence >= 0.1:
        return "靠近另一种肠型，归类不太明确"
    return "介于几种肠型之间，归类不明确"


def status_cards(ctx: Context) -> list[dict[str, Any]]:
    if not ctx.cohort_available:
        return []
    cards = []
    age = ctx.cohort.get("gut_age") or {}
    if age.get("predicted_age") is not None:
        gap = age.get("gap")
        cards.append({
            "id": "gut_age",
            "label": "肠道年龄",
            "tier_label": f"约{round(float(age['predicted_age']))}岁",
            "tone": age_tone(gap),
            "line": (age_phrase(gap) + "；只反映菌群组成，不代表身体衰老程度。") if gap is not None
            else "根据菌群组成推测；样本信息中没有实际年龄，未做同龄比较。",
            "anchor": "#gut-profile",
        })
    entero = ctx.cohort.get("enterotype") or {}
    if entero.get("label"):
        cards.append({
            "id": "enterotype",
            "label": "肠型",
            "tier_label": str(entero["label"]),
            "tone": "neutral",
            "line": f"以{entero['driver']}为主，{confidence_phrase(float(entero.get('confidence') or 0))}；肠型没有好坏之分。",
            "anchor": "#gut-profile",
        })
    return cards


def _gut_age_subsection(ctx: Context) -> dict[str, Any] | None:
    age = ctx.cohort.get("gut_age") or {}
    if age.get("predicted_age") is None:
        return None
    predicted = float(age["predicted_age"])
    gap = age.get("gap")
    chronological = age.get("chronological_age")
    headline = f"根据菌群组成推测，您的肠道年龄约为{round(predicted)}岁"
    headline += ("，" + age_phrase(gap) + "。") if gap is not None else "。"
    blocks: list[dict[str, Any]] = [{"type": "callout", "tone": age_tone(gap), "text": headline}]
    points = [(float(a), float(p)) for a, p in age.get("reference_points") or []]
    if points:
        blocks.append({
            "type": "scatter",
            "title": "实际年龄与菌群推测年龄",
            "points": points,
            "you": (float(chronological), predicted) if chronological is not None else None,
            "x_label": "实际年龄（岁）",
            "y_label": "菌群推测年龄（岁）",
            "diagonal": True,
            "caption": ("浅色点是健康参考者，虚线表示推测年龄与实际年龄相等。"
                        + ("深色菱形是您。" if chronological is not None else "样本信息中没有实际年龄，所以没有标出您的位置。")),
        })
    accuracy = (f"推测模型在{count(age['n_train'])}名健康成人的公开数据中建立，"
                f"推测值与实际年龄平均相差约{round(float(age['mae']))}岁，适合观察前后变化趋势，不适合精确判断年龄。")
    blocks.append({"type": "paragraph", "text": accuracy})
    if gap is not None and age.get("expected_for_age") is not None:
        blocks.append({"type": "paragraph", "text": (
            f"由于模型对年轻人往往推测偏大、对年长者推测偏小，我们先算出{round(float(chronological))}岁的人"
            f"通常会得到的推测值（约{round(float(age['expected_for_age']))}岁），再与您的推测值比较。")})
    if chronological is None:
        blocks.append({"type": "paragraph", "text": "如需同龄比较，请在样本信息中补充实际年龄后重新生成报告。"})
    if float(age.get("feature_support") or 0) < 0.3:
        blocks.append({"type": "callout", "tone": "neutral",
                       "text": "模型主要依据的菌在本样本中检出较少，这次推测的可靠性较低。"})
    return {
        "id": "gut-age",
        "title": "您的肠道年龄",
        "blocks": blocks,
        "summary": "肠道年龄只说明菌群组成更像哪个年龄段的人，不代表身体衰老程度，也不是疾病判断。",
        "summary_source": "rule",
        "graph": None,
    }


def _enterotype_subsection(ctx: Context) -> dict[str, Any] | None:
    entero = ctx.cohort.get("enterotype") or {}
    if not entero.get("id"):
        return None
    confidence = float(entero.get("confidence") or 0)
    blocks: list[dict[str, Any]] = [{
        "type": "callout",
        "tone": "neutral",
        "text": f"您的肠型为{entero['label']}，以{entero['driver']}为主，{confidence_phrase(confidence)}。",
    }]
    groups = [cid for cid in ENTEROTYPE_ORDER if any(c["id"] == cid for c in entero.get("centroids", []))]
    labels = {c["id"]: c["label"] for c in entero.get("centroids", [])}
    reference = entero.get("reference_points") or []
    if reference and entero.get("coords"):
        blocks.append({
            "type": "scatter",
            "title": "您在健康人群肠型分布中的位置",
            "points": [(float(x), float(y)) for x, y, _ in reference],
            "point_groups": [groups.index(g) if g in groups else 0 for _, _, g in reference],
            "groups": [{"id": g, "label": labels.get(g, g)} for g in groups],
            "you": (float(entero["coords"][0]), float(entero["coords"][1])),
            "x_label": "菌属组成主轴一",
            "y_label": "菌属组成主轴二",
            "caption": "每个点是一名健康参考者，颜色代表肠型；点之间越近，菌属组成越相似。深色菱形是您。",
        })
    rows = []
    for driver in entero.get("drivers", []):
        name = GENUS_NAMES.get(driver["genus"], driver["genus"])
        typical = driver.get("typical") or {}
        rows.append([name, pct(min(100.0, float(driver["value"])))] +
                    [pct(min(100.0, float(typical[g]))) if typical.get(g) is not None else "—" for g in groups])
    if rows:
        blocks.append({
            "type": "table",
            "columns": ["菌属", "您"] + [f"{labels.get(g, g)}常见值" for g in groups],
            "rows": rows,
            "footnote": "常见值是该肠型健康参考者的中位数，占比按已分类细菌合计计算。",
        })
    blocks.append({"type": "paragraph", "text": ENTEROTYPE_NOTES.get(entero["id"], "")
                   + "肠型没有好坏之分，长期饮食结构改变后可能随之变化。"})
    return {
        "id": "enterotype",
        "title": "您的肠型",
        "blocks": blocks,
        "summary": "肠型描述的是菌群的整体格局，用于理解饮食习惯与菌群的关系，不用于判断健康与否。",
        "summary_source": "rule",
        "graph": None,
    }


def build(ctx: Context) -> dict[str, Any]:
    subsections = []
    if ctx.cohort_available:
        for item in (_gut_age_subsection(ctx), _enterotype_subsection(ctx)):
            if item:
                subsections.append(item)
    else:
        reason = (ctx.cohort.get("audit") or {}).get("reason_cn") or "人群模型不可用"
        ctx.omit("gut-profile", "肠道年龄与肠型", reason)
    audit = ctx.cohort.get("audit") or {}
    n = audit.get("n_healthy")
    intro = ("肠道年龄根据菌群组成推测“更像多大年龄的人”；肠型描述菌群以哪类菌为主的整体格局。"
             + (f"两者都来自{count(n)}名健康成人的公开研究数据。" if n else ""))
    return {
        "id": "gut-profile",
        "nav_label": "肠龄肠型",
        "title": "肠道年龄与肠型",
        "intro": intro,
        "source_chapters": [2],
        "terms_banner": [],
        "subsections": subsections,
    }


def method_rows(ctx: Context) -> list[tuple[str, str]]:
    """Plain-language method notes for the learn appendix."""
    audit = ctx.cohort.get("audit") or {} if ctx.cohort_available else {}
    rows = []
    age = ctx.cohort.get("gut_age") if ctx.cohort_available else None
    if age:
        rows.append(("肠道年龄", (
            f"在 curatedMetagenomicData 健康成人粪便谱（{count(age['n_train'])}人、{count(age.get('n_studies') or 0)}项研究）上，"
            "用物种对数丰度做岭回归预测实际年龄；按研究分组交叉验证的平均绝对误差约"
            f"{number(age['mae'])}岁，相关系数{number(age['r'])}。同龄比较先校正回归均值效应（以交叉验证预测值对实际年龄的线性关系"
            "得到该年龄的典型推测值），再计算差值。")))
    entero = ctx.cohort.get("enterotype") if ctx.cohort_available else None
    if entero:
        rows.append(("肠型", (
            f"在{count(entero['n_train'])}名健康成人的属水平组成上做 Hellinger 变换和 k-means（k=3）聚类，"
            "按普雷沃菌属、拟杆菌属负荷命名为普雷沃菌型、拟杆菌型，其余为厚壁菌型；样本归入最近的中心，"
            "“归类明确程度”= 1 − 最近距离 / 次近距离。散点图为主成分投影。")))
    index = ctx.cohort.get("health_index") if ctx.cohort_available else None
    if index:
        rows.append(("总体健康得分", (
            "多样性25%、与健康人群相似度25%、营养代谢潜力20%、致病与耐药信号20%、肠道年龄10%加权；缺项按比例重新分配，"
            f"不足三项不计算。相似度来自健康（{count(index['n_healthy'])}人）对比患者（{count(index['n_disease'])}人）的"
            f"类别平衡逻辑回归，按研究分组交叉验证 AUC={number(index['cv_auc'])}。得分不是疾病概率。")))
    if ctx.cohort_available and ctx.cohort.get("diseases"):
        rows.append(("患病人群参考", (
            "对每类疾病，用同一批研究中的健康对照与患者比较（Mann-Whitney 检验，BH 校正 q<0.1），取富集和缺失最明显的各至多15种菌，"
            "特征分=富集菌平均对数丰度−缺失菌平均对数丰度；按研究分组交叉验证 AUC≥0.65 的疾病才展示。"
            "“更接近健康对照”表示特征分不高于对照中位数，“与患者群体较接近”表示不低于患者中位数且高于75%的对照。")))
    if audit.get("source_package_version"):
        rows.append(("人群模型来源", f"curatedMetagenomicData {audit['source_package_version']}，MetaPhlAn 3 / v30 物种谱，与健康对照使用同一份独立待测谱。"))
    return rows
