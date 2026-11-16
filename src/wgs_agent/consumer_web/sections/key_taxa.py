"""Key taxa section (professional chapter 3)."""

from __future__ import annotations

from typing import Any

from ..format import pct
from .context import Context
from .panel import category_rows, category_term, evidence_badge, load_panel, reliability_badge


WATCH_CALLOUT = "无症状人群中也可检出这类菌；若有持续腹泻、发热或便血，请就医并带上本报告。"


def _member_text(ctx: Context, member: dict, row_name: str) -> str | None:
    term_id = str(member.get("term_id") or "")
    if term_id and ctx.glossary.is_approved(term_id):
        return ctx.glossary.one_liner(term_id)
    note = str(member.get("watch_note") or member.get("note") or "").strip()
    return note or None


def _cards(ctx: Context, section: str) -> list[dict[str, Any]]:
    panel = load_panel()
    result = []
    taxonomy_complete = ctx.taxonomy.get("complete") is True
    for category in panel.get("categories", []):
        if category.get("section") != section:
            continue
        rows = category_rows(ctx, category)
        term_id = category_term(category)
        text = ctx.glossary.one_liner(term_id) if term_id and ctx.glossary.is_approved(term_id) else ""
        members = []
        member_defs = []
        for member in category.get("members", []):
            for row in rows:
                from .panel import matches
                if matches(row["name"], member):
                    member_defs.append((member, row))
        seen = set()
        for member, row in member_defs:
            key = row["name"].casefold()
            if key in seen:
                continue
            seen.add(key)
            members.append(ctx.taxon_card(
                row["name"],
                row["value"],
                text=_member_text(ctx, member, row["name"]),
                evidence_badge=evidence_badge(ctx, row["name"]),
                reliability_badge=reliability_badge(row, panel.get("reliability_thresholds")),
            ))
        total = sum(row["value"] for row in rows)
        absent = total <= 0 and taxonomy_complete and not ctx.qc_failed
        callout = None
        if section == "watch":
            detected = {ctx.names.plain(row["name"]) for row in rows}
            if any(name in detected for name in ("艰难梭菌", "产气荚膜梭菌")):
                callout = {"tone": "consult", "text": WATCH_CALLOUT}
        result.append({
            "title": str(category.get("display_name") or ""),
            "text": text or "这一类菌在肠道中常见，具体作用取决于菌株和宿主情况。",
            "total": {"value": total, "display": pct(total), "unit": "%"} if total > 0 else None,
            "tier": None,
            "members": members,
            "absent_text": "本次未检出这类菌的成员。" if absent else None,
            "callout": callout,
        })
    return result


def build(ctx: Context) -> dict[str, Any]:
    helpful = _cards(ctx, "helpful")
    watch = _cards(ctx, "watch")
    subsections = []
    if helpful:
        seeds = []
        for card in helpful:
            for member in card["members"]:
                seeds.append(member["name"])
        subsections.append({
            "id": "key-taxa-helpful",
            "title": "与健康相关的几类菌",
            "blocks": [{"type": "category_cards", "cards": helpful}],
            "summary": "这些类别合计占一定比例，但类别内不同菌的作用并不相同。",
            "summary_source": "rule",
            "graph": ctx.graph_for(
                ["key_taxa.bifidobacteria", "key_taxa.lactic_acid", "key_taxa.butyrate", "key_taxa.mucin"],
                seeds + ["双歧杆菌", "丁酸", "阿克曼菌"],
            ),
        })
    if watch:
        seeds = []
        for card in watch:
            for member in card["members"]:
                seeds.append(member["name"])
        subsections.append({
            "id": "key-taxa-watch",
            "title": "需要留意的菌",
            "blocks": [{"type": "category_cards", "cards": watch}],
            "summary": "这些菌在健康人群中也可能检出，是否需要注意取决于丰度、菌株和症状。",
            "summary_source": "rule",
            "graph": ctx.graph_for(
                ["key_taxa.opportunists", "key_taxa.pathogens"],
                seeds + ["条件致病", "肠道炎症"],
            ),
        })

    ctx.omit("key-taxa", "研究证据徽标之外的菌种档案", "没有可用的独立物种级研究计数时只保留已批准的解释")
    return {
        "id": "key-taxa",
        "nav_label": "重点菌",
        "title": "值得关注的几类菌",
        "intro": "这一部分按“可能有益”和“需要留意”两类，介绍样本中检出的重点菌。",
        "source_chapters": [3],
        "terms_banner": ["opportunists", "butyrate_producers", "conditional_commensal"],
        "subsections": subsections,
    }
