"""Rule-based gene-potential score for a metabolic product.

The score is a transparent summary of the evidence already shown in the report,
not a comparison against a reference population and not a concentration:

* pathway coverage (40): detected / mapped pathways for the product; products
  defined only by a key enzyme count as fully covered when that enzyme is seen;
* contributor breadth (30): named contributing species, saturating at five;
* sharing (15): how evenly the work is spread (largest contributor share
  of 50% or less earns the full points; a single contributor earns none);
* contributor abundance (15): relative abundance of the named contributors in
  the species profile, saturating at 10%.
"""

from __future__ import annotations

from typing import Any

from ..format import count, pct
from ..names import canonical
from .context import Context

WEIGHTS = {"coverage": 40, "breadth": 30, "sharing": 15, "abundance": 15}
BREADTH_FULL = 5
ABUNDANCE_FULL = 10.0


def level(score: int) -> str:
    if score >= 70:
        return "较强"
    if score >= 40:
        return "中等"
    return "较弱"


def potential_score(
    ctx: Context,
    *,
    mapped_pathways: int,
    detected_pathways: int,
    named: list[dict[str, Any]],
    enzyme_signal: bool = False,
) -> dict[str, Any]:
    if mapped_pathways:
        coverage = min(1.0, detected_pathways / mapped_pathways)
    else:
        coverage = 1.0 if enzyme_signal else 0.0
    breadth = min(len(named), BREADTH_FULL) / BREADTH_FULL
    top = named[0].get("share") if named else None
    if len(named) >= 2 and top is not None:
        sharing = max(0.0, min(1.0, (100.0 - float(top)) / 50.0))
    else:
        sharing = 0.0
    species = {canonical(row["name"]): row["value"] for row in ctx.species_rows}
    abundance_total = sum(species.get(canonical(row["name"]), 0.0) for row in named)
    abundance_total = min(100.0, abundance_total)
    abundance = min(1.0, abundance_total / ABUNDANCE_FULL)
    parts = {
        "coverage": round(WEIGHTS["coverage"] * coverage),
        "breadth": round(WEIGHTS["breadth"] * breadth),
        "sharing": round(WEIGHTS["sharing"] * sharing),
        "abundance": round(WEIGHTS["abundance"] * abundance),
    }
    score = int(sum(parts.values()))
    return {
        "score": score,
        "level": level(score),
        "parts": parts,
        "abundance_total": abundance_total,
        "mapped": mapped_pathways,
        "detected": detected_pathways,
        "enzyme_only": not mapped_pathways,
    }


def score_details(ctx: Context, result: dict[str, Any], named: list[dict[str, Any]]) -> list[dict[str, str]]:
    parts = result["parts"]
    rows = [{
        "label": "评分怎么算",
        "text": (
            f"满分100分：通路覆盖{WEIGHTS['coverage']}分（得{parts['coverage']}分）、"
            f"参与菌种数{WEIGHTS['breadth']}分（得{parts['breadth']}分）、"
            f"分工程度{WEIGHTS['sharing']}分（得{parts['sharing']}分）、"
            f"参与菌占比{WEIGHTS['abundance']}分（得{parts['abundance']}分）。"
        ),
    }]
    if result["enzyme_only"]:
        rows.append({"label": "检出依据", "text": "按关键酶基因判断，本次检出相关酶基因。"})
    else:
        rows.append({
            "label": "检出的相关通路",
            "text": f"本次检出{count(result['detected'])}条，参考清单共{count(result['mapped'])}条。",
        })
    if named:
        shown = []
        for row in named[:6]:
            share = row.get("share")
            label = ctx.names.plain(row["name"])
            shown.append(f"{label}（约占贡献{pct(share)}）" if share is not None else label)
        more = len(named) - len(shown)
        tail = f"等{count(len(named))}种" if more > 0 else f"，共{count(len(named))}种"
        rows.append({"label": "参与的菌", "text": "、".join(shown) + tail + "。"})
        if result["abundance_total"] > 0:
            rows.append({
                "label": "参与菌合计占比",
                "text": f"这些菌合计约占全部细菌的{pct(result['abundance_total'])}。",
            })
    else:
        rows.append({"label": "参与的菌", "text": "分层注释不足以确定具体菌。"})
    rows.append({
        "label": "怎么理解",
        "text": "评分只反映基因层面的潜力，没有与参考人群比较，不代表体内实际浓度。",
    })
    return rows
