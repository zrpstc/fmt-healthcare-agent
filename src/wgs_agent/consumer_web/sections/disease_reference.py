"""Disease-cohort reference for the pathogen section (published cMD patient cohorts)."""

from __future__ import annotations

from typing import Any

from wgs_agent.reporting.population_reference import species_key

from ..format import count, pct
from .context import Context
from .panel import watch_species

POSITION_TEXT = {
    "near_control": "更接近健康对照",
    "between": "介于健康对照与患者之间",
    "near_disease": "与患者群体较接近",
}


def informative(ctx: Context) -> list[dict]:
    if not ctx.cohort_available:
        return []
    return [row for row in ctx.cohort.get("diseases") or [] if row.get("informative")]


def _taxon(ctx: Context, key: str) -> str:
    latin = " ".join(part.capitalize() if i == 0 else part for i, part in enumerate(key.split()))
    plain = ctx.plain_name(latin)
    return latin if plain.startswith("未命名菌") else plain


def _rate(value: float | None) -> str:
    return "—" if value is None else pct(min(100.0, 100.0 * float(value)))


def assessment_point(ctx: Context) -> str | None:
    rows = informative(ctx)
    if not rows:
        return None
    near = [row["label"] for row in rows if row["position"] == "near_disease"]
    if near:
        return "患病人群参考：菌群特征与" + "、".join(near[:3]) + "患者群体较接近，仅说明组成相似，不代表患病。"
    return f"患病人群参考：与{count(len(rows))}类疾病的公开患者数据相比，未见与患者群体较接近的特征。"


def watch_prevalence_rows(ctx: Context) -> list[list[str]]:
    table = ctx.cohort.get("prevalence") or {}
    groups = table.get("groups") or []
    species = table.get("species") or {}
    if not groups or not species:
        return []
    rows = []
    for item in watch_species(ctx):
        record = species.get(species_key(item["name"]))
        if not record:
            continue
        rates = record.get("prevalence") or []
        healthy = rates[0] if rates else None
        disease = [(rates[i], groups[i]["label"]) for i in range(1, min(len(rates), len(groups)))]
        top = max(disease, key=lambda pair: pair[0]) if disease else None
        rows.append([
            ctx.plain_name(item["name"]),
            pct(min(100.0, item["value"])),
            _rate(healthy),
            f"{top[1]} {_rate(top[0])}" if top else "—",
        ])
    return rows


def subsection(ctx: Context) -> dict[str, Any] | None:
    if not ctx.cohort_available:
        return None
    rows = informative(ctx)
    prevalence = watch_prevalence_rows(ctx)
    if not rows and not prevalence:
        return None
    audit = ctx.cohort.get("audit") or {}
    groups = (ctx.cohort.get("prevalence") or {}).get("groups") or []
    n_patients = sum(int(g.get("n") or 0) for g in groups[1:]) or audit.get("n_disease")
    n_healthy = groups[0].get("n") if groups else audit.get("n_healthy")
    blocks: list[dict[str, Any]] = [{
        "type": "paragraph",
        "text": (f"为了让致病相关的结果有参照，我们把您的菌群与公开研究中{count(n_patients or 0)}名成年患者"
                 f"和{count(n_healthy or 0)}名健康成人的数据对照。比较的是菌群特征更像哪一组，不是患病概率，也不能用于诊断。"),
    }]
    if rows:
        table_rows = []
        for row in rows:
            detected = [_taxon(ctx, item["species"]) for item in row.get("enriched_detected", [])[:3]]
            table_rows.append([
                row["label"],
                count(row["n_disease"]),
                POSITION_TEXT.get(row["position"], "—"),
                "、".join(detected) if detected else "未检出",
            ])
        blocks.append({
            "type": "table",
            "columns": ["疾病人群", "患者人数", "您的菌群特征", "您检出的该病富集菌"],
            "rows": table_rows,
            "footnote": "富集菌指在该病患者中比同研究健康对照更常见或更多的菌。只列出菌群特征能较好区分患者与对照的疾病。",
        })
        near = [row["label"] for row in rows if row["position"] == "near_disease"]
        if near:
            blocks.append({
                "type": "callout",
                "tone": "watch",
                "text": ("您的菌群特征与" + "、".join(near[:3]) + "患者群体较接近。这只说明组成相似，不代表患病；"
                         "如有相关症状、家族史或体检异常，可带上本报告咨询医生。"),
            })
    if prevalence:
        blocks.append({
            "type": "table",
            "columns": ["需留意的菌", "您的占比", "健康成人中检出率", "患者人群中检出率最高的"],
            "rows": prevalence,
            "footnote": "检出率指该人群中检出这种菌的人所占比例；健康人中也常能检出这些菌。",
        })
    return {
        "id": "virulence-disease-reference",
        "title": "与公开患病人群数据对照",
        "blocks": blocks,
        "summary": "患病人群数据帮助理解“检出的菌在患者和健康人中各有多常见”；单次检测不能据此判断疾病。",
        "summary_source": "rule",
        "graph": None,
    }
