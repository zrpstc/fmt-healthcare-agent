"""Resistance section (professional chapter 5)."""

from __future__ import annotations

from typing import Any

from ..format import count
from .context import Context
from .resistance import grouped_resistance, high_concern_resistance, mobile_elements, resistance_genes


INTRO_LIMIT = "本章不等同于药敏试验，也不覆盖耐药点突变。"


def build(ctx: Context) -> dict[str, Any]:
    subsections = []
    genes = resistance_genes(ctx)
    if genes:
        cards = []
        for group in grouped_resistance(ctx):
            examples = "、".join(group.get("examples") or [])
            genes = "、".join(group["genes"])
            cards.append({
                "title": group["title"],
                "text": f"常见药物：{examples}；机制：{group['mechanism']}。检出基因：{genes}。需要使用这类抗生素时，可把本报告给医生参考。",
                "status": f"检出{count(len(group['genes']))}种",
                "tone": "watch" if any(
                    high.get("gene") in group["genes"] for high in high_concern_resistance(ctx)
                ) else "neutral",
                "tier": None,
                "members": None,
            })
        blocks = [{"type": "card_grid", "cards": cards}]
        if high_concern_resistance(ctx):
            blocks.append({
                "type": "callout",
                "tone": "consult",
                "text": "这属于临床重点关注的耐药类型，就医时请主动告知医生。",
            })
        subsections.append({
            "id": "resistance-genes",
            "title": "检出了哪些耐药基因，对应哪类药",
            "blocks": blocks,
            "summary": "检出耐药基因说明细菌携带相应机制，不等于这类药一定无效。",
            "summary_source": "rule",
            "graph": ctx.graph_for(
                ["resistance.tetracycline", "resistance.mechanisms"],
                ["耐药基因", "四环素", "抗生素"],
            ),
        })
    elif ctx.module("resistance").get("status") == "completed":
        subsections.append({
            "id": "resistance-empty",
            "title": "检出了哪些耐药基因，对应哪类药",
            "blocks": [{"type": "paragraph", "text": "本次检测范围内未检出获得性耐药基因。"}],
            "summary": "阴性结果只说明本次参考库和阈值内没有发现，不代表完全没有其他耐药机制。",
            "summary_source": "rule",
        })
    else:
        ctx.omit("resistance", "耐药基因结果", "耐药筛查尚未完成或没有通过校验")

    elements = mobile_elements(ctx)
    if elements:
        subsections.append({
            "id": "resistance-mobile",
            "title": "能在细菌间转移的DNA片段",
            "blocks": [
                {
                    "type": "paragraph",
                    "text": f"检出{count(len(elements))}种{ctx.term('mobile_element', '可移动遗传元件')}。这类片段能在DNA内部或细菌之间移动，有时会带着耐药或毒力基因一起转移。",
                },
                {
                    "type": "paragraph",
                    "text": "本次方法无法确定耐药基因是否位于这些片段上，也无法确定它们来自哪种菌。",
                },
            ],
            "summary": "可移动元件的检出本身不等于耐药基因已经转移。",
            "summary_source": "rule",
            "graph": ctx.graph_for(["resistance.mechanisms"], ["可移动遗传元件", "耐药基因"]),
        })
    else:
        ctx.omit("resistance", "可移动遗传元件", "本次没有可用的元件筛查结果")

    return {
        "id": "resistance",
        "nav_label": "耐药基因",
        "title": "耐药基因与可“搬家”的DNA片段",
        "intro": INTRO_LIMIT,
        "source_chapters": [5],
        "terms_banner": ["resistance_gene", "mobile_element"],
        "subsections": subsections,
    }
