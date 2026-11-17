"""Learn-more appendix: glossary, methods, omissions, references and downloads."""

from __future__ import annotations

from typing import Any

from .context import Context

SECTION_NAMES = {
    "overview": "总览",
    "composition": "菌群组成",
    "diversity": "多样性",
    "gut-profile": "肠龄肠型",
    "key-taxa": "重点菌",
    "virulence": "致病基因",
    "resistance": "耐药基因",
    "beyond": "细菌以外",
    "nutrition": "食物与营养",
    "metabolites": "代谢产物",
    "more": "更多线索",
    "actions": "行动建议",
    "knowledge-graph": "知识子图",
}


def build(ctx: Context, downloads: list[dict]) -> dict[str, Any]:
    subsections = []

    glossary_rows = [
        [entry["name"], entry["text"]]
        for entry in ctx.glossary.used_entries()
    ]
    if glossary_rows:
        subsections.append({
            "id": "learn-glossary",
            "title": "术语表",
            "blocks": [{"type": "table", "columns": ["术语", "解释"], "rows": glossary_rows}],
        })

    n = ctx.reference_n
    available = f"本样本可用对照为 {n:,} 人。" if n else ""
    methods = [
        ("参考人群", f"参考数据来自 curatedMetagenomicData 的 healthy/control 成人粪便谱；{available}参考谱为 MetaPhlAn 3 / v30，目标谱固定为 MetaPhlAn 3.0.14；分类物种内归一化，未按年龄、性别、地区再做匹配。P5–P95 是参考人群中间 90% 的区间，经验百分位由 bootstrap 估计，均不是疾病概率。"),
        ("分档规则", "低于 P5 为明显偏低，P5–P25 为略低，P25–P75 为常见，P75–P95 为略高，高于 P95 为明显偏高。置信区间跨越档位边界时降一档，不使用“明显”。"),
        ("两套口径", "主分析物种谱与 cMD 独立对照谱来自不同 MetaPhlAn 版本。组成比较一节使用对照谱重新归一化的数值；其余重点菌与功能部分使用主分析谱。两者不能直接相加。"),
        ("组成典型度", "把样本与参考个体之间的 Bray-Curtis 距离，换算成该样本在参考人群留一法分布中的位置；数值越高表示组成越不典型。"),
        ("功能潜力", "功能结果来自 HUMAnN 通路和分层贡献。同一功能类别会汇总该类别下所有已观测通路；EC 注释仅作为补充贡献证据，不加入通路丰度或占比分母。功能潜力不等于实际产量。"),
        ("毒力与耐药", "毒力结果来自 VFDB core 参考序列筛查，耐药结果来自 ResFinder 获得性耐药参考序列筛查。阈值、参考覆盖广度和序列一致性均按模块输出记录；reads 筛查不等同于药敏试验，也不覆盖点突变或完整质粒。"),
        ("知识子图", "子图只保留与本节展示实体相连、已发表研究报道过的关系；删除研究分组、探针、编号、测定方法和样本类型节点，删除“位于”“靶向”“测定方法为”等关系。清洗后不足两条关系时不展示。虚线表示尚待人工核对的研究结论。"),
        ("未纳入", "疾病风险模型分数、无症状推断、用药建议和个体营养摄入评估不在消费者版中；它们也不代表正常或异常。患病人群参考只描述菌群特征与公开患者群体的相似程度，不是患病概率。"),
    ]
    from .gut_profile import method_rows
    methods.extend(method_rows(ctx))
    for title, body in methods:
        subsections.append({
            "id": "learn-method-" + title,
            "title": title,
            "blocks": [{"type": "paragraph", "text": body}],
        })

    if ctx.omissions:
        rows = [
            [SECTION_NAMES.get(row["section"], row["section"]), row["item"], row["reason"]]
            for row in ctx.omissions
        ]
        subsections.append({
            "id": "learn-omissions",
            "title": "本次未包含的项目",
            "blocks": [{
                "type": "table",
                "columns": ["部分", "项目", "原因"],
                "rows": rows,
                "footnote": "未包含不代表正常或异常。",
            }],
        })

    refs = ctx.refs.references
    if refs:
        rows = [
            [ref.id, ref.title, str(ref.year) if ref.year else "", ref.doi or ref.url or ""]
            for ref in refs
        ]
        subsections.append({
            "id": "learn-references",
            "title": "参考文献",
            "blocks": [{"type": "table", "columns": ["编号", "标题", "年份", "DOI/链接"], "rows": rows}],
        })

    if downloads:
        subsections.append({
            "id": "learn-downloads",
            "title": "数据下载",
            "blocks": [{
                "type": "paragraph",
                "text": "以下文件只在已经生成时提供；专业版 PDF 与 CSV 明细分开下载。",
            }],
        })

    return {
        "id": "learn",
        "nav_label": "了解更多",
        "title": "术语、方法与数据",
        "intro": "这一部分供需要核对方法和数据的人阅读。",
        "source_chapters": [0],
        "terms_banner": [],
        "subsections": subsections,
    }
