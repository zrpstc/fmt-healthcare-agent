"""Shared consumer appendix; technical records retain their original precision."""
from __future__ import annotations


def render_appendices(document):
    from .document import table
    from . import reference_labels
    state = document.get("consumer") or {}
    if not state:
        return []
    from .knowledge_graph import graph_mode, graph_markdown, graph_signature, graph_claim_keys
    mode = graph_mode()
    if mode != "off":
        from .glossary import Glossary
        Glossary(document).get("knowledge_subgraph", kind="concept")
    inputs = document.get("template_inputs", {})
    audit = (inputs.get("healthy_comparison") or {}).get("audit", {})
    output = ["### A1 参考人群与方法说明", reference_labels.method(inputs) + "。",
              "参考与待测谱按已分类物种总和归一化至100%。主分析谱与独立比较谱分别保留。"]
    output.extend(audit.get("limitations", []))
    output.extend(reference_labels.audit_summary(inputs))
    output.append("肠型采用方案B：现有校验参考资产只有物种谱，没有属级参考谱；不从物种名拼出未经验证的肠型。")
    output.append("集中度比较沿用同一参考包、同一个体排除、人口学分层、SHA校验和边界不确定性规则；独立比较谱的数值不替代主分析。")
    for key, title in [("tax_phylum", "门水平原始丰度"), ("tax_genus", "属水平原始丰度"), ("species", "种水平原始丰度")]:
        rows = [r for r in document.get("evidence", {}).values() if r.get("kind") == key]
        if rows and any(state.get("raw_chapter_one", {}).get(key) for key in ["phylum", "genus", "species"]):
            output.extend([f"#### {title}", table(["原始名称", "原始丰度", "单位"],
                          [[r.get("species") or r.get("label", ""), str(r.get("value", "")), r.get("unit", "")] for r in rows])])
    comparison = state.get("chapters", {}).get("1", {}).get("reference_rows", [])
    raw_comparison = [r for r in document.get("evidence", {}).values() if r.get("kind") == "healthy_species"]
    from .word_template import Data
    if raw_comparison and not Data(document).qc_failed:
        output.extend(["#### 原始参考区间及不确定性说明", table(["原始物种名", "独立谱原始丰度", "原始参考文字"],
                       [[r.get("species") or r.get("label", ""), str(r.get("value")), r.get("reference_text", "")] for r in raw_comparison[:8]])])
    if comparison:
        output.extend(["#### 第1章比较统计原始精度", table(["物种", "独立谱丰度", "P5", "P95", "经验百分位", "边界区间"],
            [[r.get("species") or r.get("label", ""), str(r.get("value")), str(r.get("p5")), str(r.get("p95")), str(r.get("percentile")),
              str(r.get("p5_ci95", ""))+" / "+str(r.get("p95_ci95", ""))] for r in comparison])])
    from .consumer_chapter_two import appendix as chapter_two_appendix
    if state.get("chapter_two"):
        output.extend(chapter_two_appendix(document))
    if state.get('chapter_three'):
        from .consumer_chapter_three import appendix as chapter_three_appendix
        output.extend(chapter_three_appendix(document))
    graph_audits = list(state.get('graph_filter_audit', {}).values())
    if graph_audits:
        from collections import Counter
        reasons = Counter()
        for record in graph_audits: reasons.update(record.get('removed_reasons', {}))
        output.append('正文知识子图清洗汇总：节点'+str(sum(row['before_nodes'] for row in graph_audits))+'→'+str(sum(row['after_nodes'] for row in graph_audits))+
                      '，关系'+str(sum(row['before_edges'] for row in graph_audits))+'→'+str(sum(row['after_edges'] for row in graph_audits))+
                      '；删除原因计数：'+str(dict(sorted(reasons.items())))+'。原始主题图及文献关系完整保留在结构化报告。')
    output.append("### A2 术语表")
    entries = list(state.get("glossary", {}).values())
    if entries:
        from .glossary import citation_numbers
        output.append(table(["术语", "解释", "证据范围", "审核状态"], [[r["display_name"],
                      r["one_liner"] + citation_numbers(document, r), r["evidence_scope"], r["review_status"]] for r in entries]))
    output.extend(["### A3 本次未包含的项目", "以下项目因检测范围、证据或审核条件而省略，不代表正常或异常。"])
    omissions = document.get("consumer_omissions", [])
    if omissions:
        output.append(table(["章节", "项目", "原因", "原因码"], [[r["chapter"], r["item"], r["reason_cn"], r["reason_code"]] for r in omissions]))
    graphs = []
    if mode != "off":
        shown = state.get("displayed_subgraphs", []) if mode == "inline" else []
        seen = {row["signature"] for row in shown}
        shown_claims = {claim for row in shown for claim in row["claims"]}
        for section in document.get("sections", []):
            for topic in section["topics"]:
                graph = topic.get("knowledge_subgraph", {})
                signature = graph_signature(graph)
                claims = graph_claim_keys(graph)
                if signature in seen or claims and claims <= shown_claims:
                    continue
                parts = graph_markdown(topic, document=document, placement="appendix")
                if parts:
                    seen.add(signature)
                    graphs.extend(parts)
    if graphs:
        output.extend(["### A4 知识子图", *( ["正文未展示的子图"] if mode == "inline" else []), *graphs])
    state["appendix_sections"] = ["A1", "A2", "A3"] + (["A4"] if graphs else [])
    return output
