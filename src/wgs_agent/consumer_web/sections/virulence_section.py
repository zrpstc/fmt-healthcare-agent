"""Virulence section (professional chapter 4)."""

from __future__ import annotations

from typing import Any

from ..format import count
from .context import Context
from .panel import watch_species
from .virulence import high_concern_results, panel_results, virulence_gene_groups


def _strain_rows(ctx: Context) -> list[dict[str, Any]]:
    strains = ctx.module("strains")
    by_name = {}
    for row in strains.get("strains", []) if isinstance(strains.get("strains"), list) else []:
        name = str(row.get("species") or "")
        if name:
            by_name[name.casefold()] = row
    result = []
    for row in watch_species(ctx):
        name = row["name"]
        strain = by_name.get(name.casefold())
        if strain and strain.get("evidence_status"):
            text = "已做菌株标记分析，但未确定具体菌株；不能据此判断毒力型。"
        elif strain:
            text = "已做菌株标记分析，但未确定具体菌株。"
        else:
            text = "本次没有可用的菌株标记分析。"
        result.append([ctx.plain_name(name), text])
    return result


def _toxin_rows(ctx: Context) -> tuple[list[list[str]], list[str]]:
    rows = []
    omitted = []
    for item in panel_results(ctx):
        if item["result"] == "本次筛查未覆盖该基因":
            omitted.append(str(item.get("name") or ""))
            continue
        if item["detected"]:
            source = "可能来自" + ctx.plain_name(item["source"]) if item.get("source") else "来源尚未用序列连接证实"
            term_id = str(item.get("term_id") or "")
            meaning = ctx.glossary.one_liner(term_id) if term_id and ctx.glossary.is_publishable(term_id) else str(item.get("meaning") or "检出相关基因，不等于正在致病")
        elif item["result"] == "未检出":
            source = "本次筛查范围内"
            meaning = "未检出该基因；不代表细菌完全没有其他致病相关能力"
        else:
            source = "本次筛查未完成"
            meaning = "本次没有得到可用于判断的结果"
        rows.append([
            str(item.get("name") or ""),
            item["result"],
            source,
            meaning,
        ])
    return rows, omitted


def _source_rows(ctx: Context) -> list[list[str]]:
    results = {str(item.get("name")): item for item in panel_results(ctx)}
    rows = []
    for row in watch_species(ctx):
        name = row["name"]
        plain = ctx.plain_name(name)
        detected = [
            str(item.get("name")) for item in results.values()
            if item.get("detected") and item.get("source") and name.casefold() in str(item.get("source")).casefold()
        ]
        if name.casefold() == "bacteroides fragilis":
            bft = results.get("脆弱拟杆菌毒素")
            if bft and bft["result"] == "未检出":
                rows.append([plain, "未检出脆弱拟杆菌毒素基因（bft）。"])
            elif bft and bft["result"] == "检出":
                rows.append([plain, "检出脆弱拟杆菌毒素基因（bft），可能来自脆弱拟杆菌，尚未用序列连接证实。"])
            else:
                rows.append([plain, "本次筛查未覆盖脆弱拟杆菌毒素基因，不能据此判断。"])
        elif detected:
            rows.append([plain, "检出" + "、".join(detected[:3]) + "相关基因，可能来自这种菌，尚未用序列连接证实。"])
        else:
            rows.append([plain, "未检出本次面板中的高关注毒素基因。"])
    return rows


def build(ctx: Context) -> dict[str, Any]:
    subsections = []
    strain_rows = _strain_rows(ctx)
    if strain_rows:
        subsections.append({
            "id": "virulence-strain",
            "title": "能区分到具体菌株吗",
            "blocks": [{"type": "table", "columns": ["需留意的菌", "菌株层面能说什么"], "rows": strain_rows}],
            "summary": "菌株层面的判断有限；检出某种菌不等于知道它属于哪个菌株。",
            "summary_source": "rule",
            "graph": ctx.graph_for(["key_taxa.opportunists"], ["菌株", "毒力"]),
        })

    if ctx.module("virulence").get("status") == "completed":
        rows, omitted = _toxin_rows(ctx)
        if rows:
            blocks = [{"type": "table", "columns": ["毒素或标志", "结果", "可能来源菌", "这意味着什么"], "rows": rows}]
            high = high_concern_results(ctx)
            if high:
                blocks.append({
                    "type": "callout",
                    "tone": "consult",
                    "text": "检出高关注毒素基因。无症状人群中也可检出这类基因；若有持续腹泻、发热或便血，请就医并带上本报告。",
                })
            groups = virulence_gene_groups(ctx)
            if groups:
                blocks.append({
                    "type": "ranked_bars",
                    "rows": [
                        {"label": label, "value": {"value": float(count_value), "display": count(count_value), "unit": "项"}, "tone": "neutral"}
                        for label, count_value in groups
                    ],
                })
                blocks.append({
                    "type": "paragraph",
                    "text": "除毒素外，这些基因多数是肠道菌适应环境、获取营养的常见基因。",
                })
            subsections.append({
                "id": "virulence-genes",
                "title": "检出了哪些致病相关基因",
                "blocks": blocks,
                "summary": "重点毒素是本节最需要看的部分；其他毒力基因更多反映细菌的适应能力。",
                "summary_source": "rule",
                "graph": ctx.graph_for(["key_taxa.opportunists", "diseases.gastrointestinal"], ["毒素", "毒力", "艰难梭菌"]),
            })
        if omitted:
            ctx.omit("virulence", "本次筛查未覆盖的毒素基因", "该基因不在此次参考集中，不能给出阴性结论")

        source_rows = _source_rows(ctx)
        if source_rows:
            subsections.append({
                "id": "virulence-source",
                "title": "这些基因来自哪种菌",
                "blocks": [{"type": "table", "columns": ["需留意的菌", "结论"], "rows": source_rows}],
                "summary": "只有序列连接证据才能确定基因来自哪种菌；本报告把“可能来源”和“已证实来源”分开写。",
                "summary_source": "rule",
                "graph": ctx.graph_for(["key_taxa.opportunists"], ["来源", "毒力", "脆弱拟杆菌"]),
            })
    else:
        ctx.omit("virulence", "毒力基因结果", "毒力筛查尚未完成或没有通过校验")

    return {
        "id": "virulence",
        "nav_label": "致病基因",
        "title": "需留意的菌是否带有致病相关基因",
        "intro": f"这一部分回答两个问题：能不能区分到{ctx.term('strain', '菌株')}，以及检出了哪些与致病相关的基因。",
        "source_chapters": [4],
        "terms_banner": ["virulence_factor", "toxin_gene", "source_attribution"],
        "subsections": subsections,
    }
