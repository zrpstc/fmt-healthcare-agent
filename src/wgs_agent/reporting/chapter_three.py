"""Traceable, plain-language presentation of key microbial findings."""
from __future__ import annotations

import re

from PIL import Image, ImageDraw

from .inputs import finite
from .reference import species_key

FUNCTION_PREDICATES = {
    "PRODUCES", "CONSUMES", "UTILIZES", "DEGRADES", "FERMENTS", "TRANSFORMS",
    "METABOLIZES", "PROMOTES", "INHIBITS", "ASSOCIATED_WITH", "CORRELATED_WITH",
    "INCREASES", "DECREASES", "ENRICHED_IN", "DEPLETED_IN",
}
SUPPORT_FIELDS = ("read_count", "reads", "supporting_reads", "clade_reads", "direct_reads", "coverage", "coverage_breadth", "marker_coverage")


def _topics(document):
    return {t["id"]: t for s in document.get("sections", []) for t in s.get("topics", [])}


def selected_rows(document, subsection):
    from .chapter_two import qc_failed
    from .template_catalog import CHAPTERS
    if qc_failed(document):
        return []
    topics = _topics(document)
    ids = list(CHAPTERS[2][3][subsection - 1][1])
    if subsection == 2:
        ids.extend(t for t in topics if t.startswith("key_taxa.") and t.rsplit(".", 1)[-1] in {"pathogens", "opportunists"})
    rows, seen = [], set()
    for tid in ids:
        topic = topics.get(tid, {})
        if topic.get("status") == "missing":
            continue
        for key in topic.get("evidence_ids", []):
            row = document.get("evidence", {}).get(key, {})
            if row.get("claim_id") or not row:
                continue
            name = species_key(row.get("species") or row.get("name") or row.get("label"))
            if not name or name in seen:
                continue
            rows.append({**row, "chapter_three_evidence_id": key})
            seen.add(name)
    return rows


def _name(row):
    return str(row.get("species") or row.get("name") or row.get("label") or "未提供")


def _matches_name(endpoint, name):
    endpoint = species_key(endpoint)
    name = species_key(name)
    return endpoint == name or endpoint.startswith(name + " ") or endpoint.startswith(name + " (")


def _claim_scope(row, name):
    endpoints = [row.get("subject", ""), row.get("object", "")]
    if any(species_key(v) == species_key(name) for v in endpoints):
        return "species"
    if any(_matches_name(v, name) for v in endpoints):
        return "strain"
    genus = species_key(name).split()[0] if species_key(name) else ""
    if genus and any(species_key(v) == genus for v in endpoints):
        return "genus"
    return None


def _functional(row):
    return (str(row.get("predicate", "")).upper() in FUNCTION_PREDICATES
            and bool(row.get("evidence_text")) and bool(row.get("claim_id"))
            and row.get("negated") is not True and row.get("display_negated") is not True
            and str(row.get("result_status", "")).lower() not in {"not_significant", "no_effect", "no_association", "not_observed", "unsupported"})


def _plain_sentence(claim, name, scope):
    predicate = str(claim.get("predicate", "")).upper()
    subject = str(claim.get("subject", ""))
    obj = str(claim.get("object", ""))
    text = obj.casefold()
    prefix = "同属细菌的研究显示，" if scope == "genus" else "特定菌株的研究发现，" if scope == "strain" else "研究发现，"
    if claim.get("speculative") is True:
        prefix = "关于同属细菌的研究提示，" if scope == "genus" else "研究提示，"
    actor = "这类细菌" if scope == "genus" else "部分菌株" if scope == "strain" else "它"
    if predicate == "PRODUCES" and _matches_name(subject, name if scope == "species" else name.split()[0]):
        products = [("butyrate", "丁酸"), ("丁酸", "丁酸"), ("acetate", "乙酸"), ("乙酸", "乙酸"), ("lactate", "乳酸"), ("乳酸", "乳酸"), ("hydrogen sulfide", "硫化氢"), ("硫化氢", "硫化氢")]
        product = next((label for token, label in products if token in text), None)
        if product:
            return prefix + actor + "能产生" + product + ("等发酵产物。" if product != "硫化氢" else "，是否造成影响仍取决于数量和肠道环境。")
        vitamins = [("folate", "叶酸"), ("niacin", "维生素B3"), ("pyridoxine", "维生素B6"), ("thiamine", "维生素B1"), ("riboflavin", "维生素B2")]
        vitamin = next((label for token, label in vitamins if token in text), None)
        if vitamin:
            return ("特定菌株的研究提示，部分菌株" if scope == "strain" else "研究提示，它") + "可能参与" + vitamin + "的合成。"
        if any(w in text for w in ("acetylcholine", "norepinephrine", "serotonin", "dopamine")):
            return "部分研究发现，该菌可产生参与细胞传递信息的小分子。"
    if predicate in {"CONSUMES", "UTILIZES", "DEGRADES", "FERMENTS", "METABOLIZES", "TRANSFORMS"} and _matches_name(subject, name if scope == "species" else name.split()[0]):
        if any(w in text for w in ("mucin", "黏蛋白", "黏液")):
            return prefix + actor + "能利用肠道黏液中的部分成分生长。"
        if any(w in text for w in ("fiber", "fibre", "starch", "polysaccharide", "纤维", "淀粉", "多糖")):
            return prefix + actor + "能帮助分解部分膳食纤维或复杂糖类。"
        if any(w in text for w in ("lactate", "乳酸")):
            return prefix + actor + "能利用乳酸，参与肠道内的发酵产物周转。"
        if any(w in text for w in ("acetate", "乙酸")):
            if "butyrate" in str(claim.get("evidence_text", "")).casefold():
                return prefix + actor + "能利用乙酸参与丁酸的生成。"
            return prefix + actor + "能利用乙酸，参与肠道中的发酵过程。"
        if any(w in text for w in ("5-fluorouracil", "5-fu", "氟尿嘧啶")):
            return "实验研究发现，它能转化抗癌药氟尿嘧啶，人体内的影响仍需结合具体研究条件。"
    # Preserve the association boundary when the graph has no usable functional verb.
    return prefix + actor + "与某些代谢或健康现象有关，具体作用需结合菌株和研究背景。"


def _claim_rank(row, name):
    scope = _claim_scope(row, name)
    obj = str(row.get("object", "")).casefold()
    relevant = any(w in obj for w in ("butyrate", "acetate", "lactate", "mucin", "fiber", "fibre", "starch", "hydrogen sulfide", "丁酸", "乙酸", "乳酸", "黏液", "纤维", "淀粉", "硫化氢"))
    return ({"species": 3, "strain": 2, "genus": 1}.get(scope, 0), relevant, row.get("predicate") in {"PRODUCES", "CONSUMES", "UTILIZES", "DEGRADES", "FERMENTS"}, row.get("speculative") is not True, finite(row.get("confidence")) or 0)


def background(document, row):
    name = _name(row)
    claims = [r for r in document.get("evidence", {}).values() if _functional(r) and _claim_scope(r, name)]
    if not claims:
        retrieval = document.get("audit", {}).get("knowledge_graph_retrieval", {})
        status = retrieval.get("status")
        if status == "unavailable":
            sentence = "本次LitKG检索超时，功能介绍暂不可用。" if retrieval.get("error_type") in {"ReadTimeout", "ConnectTimeout", "TimeoutException"} else "本次LitKG连接或检索失败，功能介绍暂不可用。"
        elif status == "partial" or retrieval.get("scan_truncated"):
            sentence = "本次LitKG检索覆盖不完整，尚未取得该物种的功能介绍。"
        elif status == "cached" and retrieval.get("refresh_error_type"):
            sentence = "最近一次LitKG知识快照中未匹配到该物种的直接功能证据。"
        elif status in {"disabled", "not_configured"}:
            sentence = "本次未启用LitKG检索，功能介绍暂不可用。"
        elif retrieval.get("source") == "targeted":
            sentence = "本次定向检索未匹配到该物种可直接使用的功能证据。"
        else:
            sentence = "LitKG暂缺可用于介绍该物种功能的直接证据。"
        return {"sentence": sentence, "scope": "missing", "claim_ids": [], "evidence_count": 0, "retrieval_status": status}
    claims.sort(key=lambda r: _claim_rank(r, name), reverse=True)
    claim = claims[0]
    scope = _claim_scope(claim, name)
    return {"sentence": _plain_sentence(claim, name, scope), "scope": scope, "claim_ids": [str(r["claim_id"]) for r in claims[:3]], "evidence_count": len(claims)}


def integrate_knowledge(document, references):
    """Retain functional claims that generic top-eight topic ranking can omit."""
    rows = selected_rows(document, 1) + selected_rows(document, 2)
    evidence = document.setdefault("evidence", {})
    by_claim = {str(r.get("claim_id")): key for key, r in evidence.items() if r.get("claim_id")}
    matched = document.setdefault("references", {}).setdefault("matched_docs", [])
    added = []
    for row in rows:
        name = _name(row)
        candidates = [r for r in references if _functional(r) and _claim_scope(r, name)]
        candidates.sort(key=lambda r: _claim_rank(r, name), reverse=True)
        for claim in candidates[:3]:
            ident = str(claim["claim_id"])
            key = by_claim.get(ident)
            if key is None:
                key = "C3KG_" + re.sub(r"[^A-Za-z0-9_]", "_", ident)
                evidence[key] = {**claim, "kind": "literature"}
                matched.append(claim)
                by_claim[ident] = key
                added.append(ident)
            for topic in _topics(document).values():
                if row.get("chapter_three_evidence_id") in topic.get("evidence_ids", []):
                    allowed = topic.setdefault("allowed_narrative_ids", [])
                    if key not in allowed:
                        allowed.append(key)
    document.setdefault("audit", {})["chapter_three_knowledge"] = {"added_functional_claims": len(added), "claim_ids": added}


def reference_for(document, row):
    value = finite(row.get("percentile"))
    if value is not None and 0 <= value <= 100:
        return {"percentile": value, "value": finite(row.get("value", row.get("abundance"))), "scope": "same_profile", "n_reference": row.get("n_subjects", row.get("n_reference"))}
    comparison = document.get("template_inputs", {}).get("healthy_comparison") or {}
    if comparison.get("audit", {}).get("status") != "available":
        return None
    name = species_key(_name(row))
    for r in comparison.get("species", []):
        if species_key(r.get("species") or r.get("name") or r.get("label")) != name:
            continue
        pct = finite(r.get("percentile"))
        observed = finite(r.get("value", r.get("abundance")))
        if pct is None and isinstance(r.get("_distribution"), list) and observed is not None:
            values = [finite(v) for v in r["_distribution"]]
            if values and all(v is not None and v >= 0 for v in values):
                pct = 100 * (sum(v < observed for v in values) + .5 * sum(v == observed for v in values)) / len(values)
        if pct is not None and 0 <= pct <= 100 and observed is not None and observed >= 0:
            return {"percentile": pct, "value": observed, "scope": "independent_profile", "n_reference": r.get("n_subjects", r.get("n_reference"))}
    return None


def _quantity(value):
    value = finite(value)
    return f"{value:.6g} %" if value is not None and value >= 0 else "未提供"


def _category(document, row):
    from .template_catalog import CHAPTERS
    labels = ("双歧杆菌相关", "乳杆菌相关属", "粪杆菌及产丁酸菌相关", "阿克曼菌及黏液相关")
    for tid, label in zip(CHAPTERS[2][3][0][1], labels):
        if row.get("chapter_three_evidence_id") in _topics(document).get(tid, {}).get("evidence_ids", []):
            return label
    return "条件致病或其他关注菌"


def table_payload(document, subsection):
    if subsection == 3:
        return support_table(document)
    from .template_body import _detection
    records = selected_rows(document, subsection)
    independent = any((reference_for(document, r) or {}).get("scope") == "independent_profile" for r in records)
    headers = ["菌群范围", "具体物种", "功能背景", "检出状态", "主分析丰度"] if subsection == 1 else ["关注类别", "微生物名称", "检出状态", "主分析丰度"]
    if independent:
        headers.append("对照谱丰度")
    headers.append("人群分位数")
    if subsection == 2:
        headers.append("关注说明")
    rows = []
    for r in records:
        bg = background(document, r)
        ref = reference_for(document, r)
        values = [_category(document, r), _name(r)]
        if subsection == 1:
            values.append(bg["sentence"])
        values.extend([_detection(r), _quantity(r.get("value", r.get("abundance")))])
        if independent:
            values.append(_quantity(ref["value"]) if ref else "未建立同物种对照")
        values.append(f"P{ref['percentile']:.1f}" if ref else "未建立可比参考")
        if subsection == 2:
            values.append(bg["sentence"])
        rows.append(values)
    removed_detection = bool(rows) and all(row[headers.index("检出状态")] == "检出" for row in rows)
    if removed_detection:
        index = headers.index("检出状态")
        headers.pop(index)
        rows = [r[:index] + r[index + 1:] for r in rows]
    note = ""
    if independent:
        note = "主分析丰度与独立对照谱采用不同口径，分别列出；人群分位数仅对应对照谱丰度，按同流程参考人群计算，P50表示位于参考人群中间位置。"
    elif any(reference_for(document, r) for r in records):
        note = "人群分位数按可比参考分布计算，P50表示位于参考人群中间位置；参考分布缺失时保留未建立。"
    return {"headers": headers, "rows": rows, "note": note, "detection_column_removed": removed_detection}


def support_records(document):
    supplemental = selected_rows(document, 3)
    candidates = selected_rows(document, 1) + selected_rows(document, 2) + supplemental
    result, seen = [], set()
    taxonomy = document.get("template_inputs", {}).get("taxonomy") or {}
    source_rows = taxonomy.get("ranks", {}).get("species", [])
    by_name = {species_key(r.get("species") or r.get("name") or r.get("label")): r for r in source_rows}
    extra_by_name = {}
    for row in supplemental:
        key = species_key(_name(row))
        extra = extra_by_name.setdefault(key, {})
        for field in (*SUPPORT_FIELDS, "detection_confidence", "coverage_unit", "coverage_breadth_unit", "source_file"):
            if row.get(field) is not None and row.get(field) != "":
                extra[field] = row[field]
        if row.get("unit") in {"reads", "read_count", "读段", "读段数"} and finite(row.get("value")) is not None:
            extra.setdefault("read_count", finite(row["value"]))
    for row in candidates:
        key = species_key(_name(row))
        if key in seen:
            continue
        merged = {**by_name.get(key, {}), **row, **extra_by_name.get(key, {})}
        result.append(merged)
        seen.add(key)
    return result


def support_table(document):
    from .template_body import _detection
    rows = []
    for row in support_records(document):
        parts = []
        for keys, label in [(("read_count", "reads", "supporting_reads"), "支持读段"), (("clade_reads",), "分类分支读段"), (("direct_reads",), "直接归属读段"), (("coverage", "marker_coverage"), "覆盖度"), (("coverage_breadth",), "覆盖广度")]:
            value = next((finite(row[k]) for k in keys if finite(row.get(k)) is not None), None)
            if value is not None and value >= 0:
                parts.append(f"{label} {value:.6g}")
        quantified = bool(parts)
        if row.get("taxon_id"):
            parts.append("有分类编号")
        if row.get("source_file"):
            parts.append("可追溯至原始分类谱")
        if not quantified:
            parts.append("已有分类与丰度记录；读段数或覆盖度未提供")
        bg = background(document, row)
        knowledge = ("LitKG物种级功能记录" if bg["scope"] == "species" else "LitKG特定菌株功能记录" if bg["scope"] == "strain" else "LitKG属级功能背景" if bg["scope"] == "genus" else "LitKG暂无直接功能记录")
        if bg["evidence_count"]:
            knowledge += f"（{bg['evidence_count']}条）；研究证据等级未单独标注"
        supplied_confidence = row.get("detection_confidence")
        confidence = str(supplied_confidence) if supplied_confidence is not None and supplied_confidence != "" else ("有量化支持记录，未统一校准可信度" if quantified else "有分类记录，无法量化检出可信度")
        rows.append([_name(row) + "（" + _detection(row) + "）", "；".join(parts), confidence, knowledge])
    return {"headers": ["重点结果", "序列支持摘要", "检出可信度", "关联证据等级"], "rows": rows, "note": "知识库研究说明功能背景，不替代本次样本的序列支持；未提供的读段数和覆盖度不按零处理。"}


def intro(document):
    healthy, other = len(selected_rows(document, 1)), len(selected_rows(document, 2))
    return f"本次记录{healthy}种重点健康相关菌和{other}种其他关注微生物，以下展示其丰度与LitKG研究背景；物种检出不能单独判断感染，也不代表所有菌株作用相同，菌株和毒力需结合第4章的序列证据，感染判断还需症状、临床检查及必要的复核。"


def support_note(document):
    rows = support_records(document)
    supported = sum(any(finite(r.get(k)) is not None for k in SUPPORT_FIELDS) for r in rows)
    if not rows:
        return "本章尚无可关联的物种分类或专项检测记录，暂无法补充序列支持。"
    return f"本章可关联{len(rows)}项分类或检测记录，其中{supported}项提供读段数或覆盖度；下表列出已有依据，缺少的序列指标保留为未提供。"


def chart_payload(document, ident):
    if ident == "3.1.1":
        rows = [r for r in selected_rows(document, 1) if r.get("unit") == "%" and finite(r.get("value")) is not None and r["value"] >= 0]
        return {"chapter_three_mode": "abundance", "rows": rows, "labels": [_name(r) for r in rows], "series": [{"name": "主分析相对丰度", "values": [r["value"] for r in rows]}], "unit": "%", "status": "available" if rows else "missing"}
    rows = []
    for r in support_records(document):
        value = next((finite(r[k]) for k in ("read_count", "reads", "supporting_reads") if finite(r.get(k)) is not None), None)
        if value is not None and value >= 0:
            rows.append({**r, "chart_value": value})
    return {"chapter_three_mode": "reads", "rows": rows, "labels": [_name(r) for r in rows], "series": [{"name": "支持读段数", "values": [r["chart_value"] for r in rows]}], "unit": "读段", "status": "available" if rows else "missing"}


def draw_chart(payload, width):
    from .word_figures import _font, _text
    rows = payload["rows"]
    height = max(260, 115 + len(rows) * 92)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    regular, small = _font(31), _font(27)
    left, right = width * .36, width - 225
    values = payload["series"][0]["values"]
    maximum = max(values + [0]) or 1
    if not rows:
        _text(draw, (40, 65), "未提供可展示的对应记录", regular)
        return image
    for i, (row, value) in enumerate(zip(rows, values)):
        cy = 45 + i * 92
        _text(draw, (left - 25, cy + 5), _name(row), regular, width=left - 65, anchor="rt", max_lines=2)
        x2 = left + (right - left) * value / maximum
        draw.rectangle((left, cy + 12, right, cy + 40), fill="#E8EFF3")
        if value > 0:
            draw.rectangle((left, cy + 12, x2, cy + 40), fill="#216C7A")
        text = _quantity(value) if payload["chapter_three_mode"] == "abundance" else f"{value:.6g} 读段"
        _text(draw, (x2 + 16, cy + 5), text, regular, fill="#173D4D")
    footer = "主分析相对丰度；与表中主分析丰度一致" if payload["chapter_three_mode"] == "abundance" else "仅展示输入中实际提供的支持读段数"
    _text(draw, (40, height - 48), footer, small, fill="#536C79")
    return image


def prepare_chapter_three(document):
    rows = selected_rows(document, 1) + selected_rows(document, 2)
    document["chapter_three_backgrounds"] = {species_key(_name(r)): background(document, r) for r in rows}
    document["chapter_three_results"] = {
        "version": "chapter-three-v1", "intro": intro(document),
        "healthy": table_payload(document, 1), "other": table_payload(document, 2),
        "support": support_table(document),
        "reference_method": "Empirical percentile from the existing compatible reference profile; main-profile abundance is kept separate.",
    }
