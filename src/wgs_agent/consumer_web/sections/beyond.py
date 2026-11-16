"""Non-bacterial microbes section (professional chapter 6)."""

from __future__ import annotations

import re
from typing import Any

from ..format import count, pct, tier
from .context import Context
from ..names import canonical


def _detection_rate(ctx: Context, name: str) -> float | None:
    row = ctx.healthy_by_key().get(canonical(name))
    if not row:
        return None
    value = row.get("detection_rate")
    try:
        return float(value) * 100 if value is not None else None
    except (TypeError, ValueError):
        return None


def _reference_tier(ctx: Context, name: str) -> dict | None:
    row = ctx.healthy_by_key().get(canonical(name))
    if not row:
        return None
    percentile = row.get("percentile")
    if percentile is None or str(row.get("status")) not in {"normal", "high", "low", "borderline"}:
        return None
    try:
        t = tier(float(percentile), metric="species_diff", borderline=bool(row.get("borderline")))
    except (TypeError, ValueError):
        return None
    return {"percentile": percentile, "tier": t}


def _host_from_reference(value: str) -> str | None:
    text = str(value or "")
    if "Enterobacteria" in text or "Escherichia" in text or "Salmonella" in text:
        return "肠杆菌"
    if "Bacteroides" in text:
        return "拟杆菌"
    if "Lactobacillus" in text:
        return "乳杆菌"
    if "Fusobacterium" in text:
        return "梭杆菌"
    if "Streptococcus" in text:
        return "链球菌"
    return None


def build(ctx: Context) -> dict[str, Any]:
    subsections = []
    archaea = ctx.module("archaea")
    archaea_records = [row for row in archaea.get("records", []) if isinstance(row, dict)] if isinstance(archaea.get("records"), list) else []
    if archaea_records:
        cards = []
        scales = []
        for row in archaea_records:
            name = str(row.get("name") or "")
            value = float(row.get("abundance") or 0)
            rate = _detection_rate(ctx, name)
            text = ctx.glossary.one_liner("archaea") if ctx.glossary.is_approved("archaea") else "肠道里常见的产甲烷微生物。"
            if rate is not None:
                text += f"约{pct(rate)}的健康人可检出。"
            cards.append(ctx.taxon_card(name, value, text=text))
            ref = _reference_tier(ctx, name)
            if ref:
                scales.append({
                    "label": ctx.plain_name(name),
                    "value": {"value": value, "display": pct(value), "unit": "%"},
                    "tier": ref["tier"],
                    "note": None,
                })
        blocks: list[dict[str, Any]] = [{"type": "taxon_cards", "cards": cards}]
        if scales:
            blocks.append({"type": "tier_scales", "rows": scales})
        subsections.append({
            "id": "beyond-archaea",
            "title": "产甲烷古菌",
            "blocks": blocks,
            "summary": "古菌在肠道中占比通常很低；检出产甲烷古菌不代表胀气或疾病。",
            "summary_source": "rule",
            "graph": ctx.graph_for(["ecology.gas"], ["甲烷", "古菌"]),
        })
    else:
        ctx.omit("beyond", "产甲烷古菌", "本次没有可用的古菌筛查结果")

    fungi = ctx.module("fungi")
    fungi_records = [row for row in fungi.get("records", []) if isinstance(row, dict)] if isinstance(fungi.get("records"), list) else []
    if fungi_records:
        cards = []
        for row in fungi_records:
            name = str(row.get("name") or "")
            value = float(row.get("abundance") or 0)
            rate = _detection_rate(ctx, name)
            text = ctx.glossary.one_liner("fungi") if ctx.glossary.is_approved("fungi") else "肠道真菌通常来自食物或环境。"
            if rate is not None:
                text += f"约{pct(rate)}的健康人可检出。"
            cards.append(ctx.taxon_card(name, value, text=text))
        subsections.append({
            "id": "beyond-fungi",
            "title": "真菌",
            "blocks": [{"type": "taxon_cards", "cards": cards}],
            "summary": "真菌含量通常远低于细菌；检出也不等于感染。",
            "summary_source": "rule",
            "graph": ctx.graph_for(["composition.species"], ["真菌", "酵母"]),
        })
    else:
        ctx.omit("beyond", "真菌", "本次没有可用的真菌筛查结果")

    viruses = ctx.module("dna_viruses")
    virus_records = [row for row in viruses.get("records", []) if isinstance(row, dict)] if isinstance(viruses.get("records"), list) else []
    if virus_records:
        hosts: dict[str, int] = {}
        unknown = 0
        for row in virus_records:
            host = _host_from_reference(str(row.get("reference_genome") or ""))
            if host:
                hosts[host] = hosts.get(host, 0) + 1
            else:
                unknown += 1
        parts = []
        if hosts:
            parts.append("主要感染的细菌：" + "、".join(f"{host}（{count(number)}种）" for host, number in sorted(hosts.items())))
        if unknown:
            parts.append(f"另有{count(unknown)}种未能确定宿主")
        blocks = [
            {
                "type": "paragraph",
                "text": f"检出{count(len(virus_records))}种噬菌体序列。" + ("；".join(parts) + "。" if parts else ""),
            },
            {
                "type": "paragraph",
                "text": "噬菌体专门感染细菌，不感染人体细胞；检出噬菌体序列不等于存在感染。",
            },
        ]
        subsections.append({
            "id": "beyond-viruses",
            "title": "病毒",
            "blocks": blocks,
            "summary": "噬菌体是肠道里数量最多的病毒，通常不直接作用于人体。",
            "summary_source": "rule",
            "graph": ctx.graph_for(["ecology.gas"], ["噬菌体", "病毒"]),
        })
    else:
        ctx.omit("beyond", "病毒", "本次没有可用的病毒序列筛查结果")

    return {
        "id": "beyond",
        "nav_label": "细菌以外",
        "title": "细菌以外的肠道微生物",
        "intro": "本检测基于DNA，无法检测诺如病毒、轮状病毒等RNA病毒。",
        "source_chapters": [6],
        "terms_banner": ["archaea", "fungi", "bacteriophage"],
        "subsections": subsections,
    }
