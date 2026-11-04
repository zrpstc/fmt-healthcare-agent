"""Traceable host-interaction clues from observed functional annotations.

Pathway abundance describes microbial functional potential. It is neither an
assay of mucin cleavage nor a measurement of host inflammation or permeability.
No pathway abundances or overlapping superpathways are summed into a score.
"""
from __future__ import annotations

import html
import math
import re

VERSION = "host-interaction-v1"
LIMITATION = "仅反映微生物功能潜力；不代表实际代谢通量、定植抗力、黏液损伤、宿主炎症或屏障通透性，未计算能力分。"
NO_EVIDENCE = "未提供可匹配的有效功能注释，不能据此判定该功能不存在。"
FEATURES = (
    ("substrate", "底物利用", 1),
    ("fermentation", "发酵相关代谢环境", 1),
    ("antimicrobial", "抑菌产物合成", 1),
    ("lipid_a", "lipid A / 脂多糖合成", 2),
    ("cell_wall", "肽聚糖合成与成熟", 2),
    ("flagellin", "鞭毛蛋白注释", 2),
    ("host_glycan", "宿主糖链相关单糖利用", 3),
    ("mucin_enzyme", "黏液糖链切割酶", 3),
    ("redox", "微生物氧化应激相关功能", 4),
)
TOPIC_FEATURES = {
    "ecology.colonization": ("substrate", "fermentation", "antimicrobial"),
    "ecology.inflammation": ("lipid_a", "cell_wall", "flagellin"),
    "ecology.mucin": ("host_glycan", "mucin_enzyme"),
    "ecology.barrier": ("fermentation", "host_glycan", "redox"),
    "ecology.redox": ("redox",),
}


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _failed(document):
    value = document.get("metadata", {}).get("qc_status", "")
    return str(value).strip().lower() in {"failed", "fail", "不通过", "未通过", "rejected", "qc_failed"}


def _text(row):
    return html.unescape(" ".join(str(row.get(k, "")) for k in ("name", "label", "gene", "gene_family"))).casefold().replace("_", " ")


def _classify(row):
    text = _text(row)
    pathway = row.get("kind") == "pathway"
    gene = row.get("kind") == "function" and row.get("measurement_type") in {"sequence_detection", "functional_potential"}
    degradation = any(s in text for s in ("degradation", "catabolism", "catabolic", "降解", "分解代谢"))
    synthesis = any(s in text for s in ("biosynthesis", "生物合成", "合成"))
    matches = set()
    if pathway and degradation and any(s in text for s in ("starch", "glycogen", "sucrose", "maltose", "galactose", "lactose", "fucose", "rhamnose", "acetylneuram", "acetylglucosamine", "淀粉", "岩藻糖", "唾液酸")):
        matches.add("substrate")
    if pathway and "fermentation" in text and not any(s in text for s in ("engineered", "chlamydomonas")):
        matches.add("fermentation")
    if (pathway or gene) and synthesis and any(s in text for s in ("bacteriocin", "microcin", "lantibiotic", "nisin")) and not any(s in text for s in ("immunity", "resistance")):
        matches.add("antimicrobial")
    if pathway and synthesis and any(s in text for s in ("lipid a", "lipopolysaccharide", "脂多糖")):
        matches.add("lipid_a")
    if pathway and "peptidoglycan" in text and (synthesis or "maturation" in text):
        matches.add("cell_wall")
    if gene and re.search(r"\bflagellin\b|鞭毛蛋白", text):
        matches.add("flagellin")
    if pathway and degradation and any(s in text for s in ("fucose", "acetylneuram", "sialic acid", "acetylglucosamine", "岩藻糖", "唾液酸")):
        matches.add("host_glycan")
    if gene and any(s in text for s in ("sialidase", "neuraminidase", "fucosidase", "mucinase", "唾液酸酶", "岩藻糖苷酶")):
        matches.add("mucin_enzyme")
    if (pathway and any(s in text for s in ("glutathione biosynthesis", "glutathione redox", "mycothiol biosynthesis"))) or (gene and any(s in text for s in ("superoxide dismutase", "catalase", "peroxidase", "thioredoxin reductase"))):
        matches.add("redox")
    return matches


def extract(document):
    qc_failed = _failed(document)
    features = {key: {"id": key, "label": label, "sub": sub, "evidence_ids": [], "status": "missing", "reason": NO_EVIDENCE} for key, label, sub in FEATURES}
    seen = set()
    if not qc_failed:
        for evidence_id, row in document.get("evidence", {}).items():
            if not isinstance(row, dict) or row.get("kind") not in {"pathway", "function"}:
                continue
            if row.get("measurement_type") not in {"functional_potential", "sequence_detection"}:
                continue
            if row.get("data_type") in {"model_inferred", "taxonomic_estimate", "literature_association"}:
                continue
            value = _number(row.get("value", row.get("abundance")))
            if value is None or value <= 0:
                continue
            identity = str(row.get("id") or row.get("name") or row.get("label") or evidence_id)
            if "|" in identity or identity in {"UNMAPPED", "UNINTEGRATED"}:
                continue
            duplicate = (row.get("kind"), row.get("source_file"), identity)
            if duplicate in seen:
                continue
            seen.add(duplicate)
            for key in _classify(row):
                features[key]["evidence_ids"].append(evidence_id)
    for item in features.values():
        if item["evidence_ids"]:
            item.update(status="available", reason="已提供样本功能注释；关联方向与宿主表型未测定。")
        elif qc_failed:
            item["reason"] = "样本质控未通过，停止解释功能线索。"
    return {"version": VERSION, "status": "qc_failed" if qc_failed else "partial" if any(x["evidence_ids"] for x in features.values()) else "missing", "features": features, "limitations": LIMITATION, "host_measurements": "not_provided"}


def prepare_document(document):
    result = extract(document)
    document["chapter_nine_results"] = result
    for section in document.get("sections", []):
        if section.get("id") != "ecology":
            continue
        for topic in section.get("topics", []):
            keys = TOPIC_FEATURES.get(topic.get("id"))
            if keys is None:
                continue
            ids = list(dict.fromkeys(eid for key in keys for eid in result["features"][key]["evidence_ids"]))
            topic["evidence_ids"] = ids
            topic["allowed_narrative_ids"] = list(dict.fromkeys(ids + [eid for eid in topic.get("allowed_narrative_ids", []) if eid in document.get("evidence", {}) and document["evidence"][eid].get("kind") not in {"pathway", "function"}]))
            topic["status"] = "available" if ids else "missing"
            topic["finding"] = (f"获得 {len(ids)} 条微生物功能注释线索。" if ids else NO_EVIDENCE) + LIMITATION
        count = sum(t.get("status") != "missing" for t in section.get("topics", []))
        section["status"] = "available" if count == len(section.get("topics", [])) else "partial" if count else "missing"
    return result


def _rows(document, keys):
    result = extract(document)
    ids = list(dict.fromkeys(eid for key in keys for eid in result["features"][key]["evidence_ids"]))
    return [(eid, document["evidence"][eid]) for eid in ids]


def _label(eid, row):
    ident = row.get("id") or eid
    name = row.get("name") or row.get("label") or ident
    return f"{ident}: {name}" if str(ident) not in str(name) else str(name)


def _quantity(row):
    value = _number(row.get("value", row.get("abundance")))
    unit = str(row.get("unit") or "单位未提供")
    if value is None:
        return "未提供有效定量"
    if unit.casefold() in {"relative_abundance", "relab"}:
        return f"{value * 100:.6g}%（通路相对丰度）"
    return f"{value:.6g} {unit}"


def _contributors(row):
    from .functional_metrics import taxon_name
    names = []
    for member in row.get("contributors") or []:
        if not isinstance(member, dict):
            continue
        name = member.get("taxon") or member.get("species") or member.get("name")
        value = _number(member.get("abundance", member.get("value")))
        if name and value is not None and value > 0:
            normalized = taxon_name(name)
            if normalized not in names:
                names.append(normalized)
    return "、".join(names[:3]) if names else "未提供物种分层贡献"


def _describe(document, keys, limit=6):
    rows = _rows(document, keys)
    if not rows:
        return "样本质控未通过，停止解释。" if _failed(document) else NO_EVIDENCE
    parts = [f"{_label(eid, row)}；{_quantity(row)}；贡献菌：{_contributors(row)}；证据[{eid}]" for eid, row in rows[:limit]]
    if len(rows) > limit:
        parts.append(f"另有 {len(rows)-limit} 条注释，完整列表见 chapter_nine_results 的 evidence_ids。")
    return "；".join(parts)


def table_rows(document, sub, data=None):
    if sub == 1:
        return [[label, _describe(document, (key,), 3), f"{len(_rows(document, (key,)))} 条注释；竞争或抑菌效果未验证" if _rows(document, (key,)) else "无法评价", "样本功能潜力注释；非宿主功能实测" if _rows(document, (key,)) else "证据缺失"] for key, label in (("substrate", "底物竞争相关利用线索"), ("fermentation", "代谢环境"), ("antimicrobial", "抑菌相关功能"))]
    if sub == 2:
        return [[label + "；" + _describe(document, (key,), 3), "宿主炎症方向未测定", "微生物结构/功能注释，未测定宿主免疫反应", "样本功能潜力注释" if _rows(document, (key,)) else "证据缺失"] for key, label in (("lipid_a", "lipid A / 脂多糖"), ("cell_wall", "肽聚糖"), ("flagellin", "鞭毛蛋白"))]
    if sub == 3:
        return [[label, _describe(document, (key,)), "糖链底物可有饮食或其他来源；利用不等于黏蛋白切割或屏障损伤"] for key, label in (("host_glycan", "宿主糖链相关单糖利用"), ("mucin_enzyme", "黏液糖链切割酶"))]
    if sub == 4:
        return [[label, _describe(document, keys, 3), scope] for label, keys, scope in (("第7章底物利用 / 本章9.3", ("host_glycan",), "仅见共享单糖利用潜力；未证实宿主来源或黏液降解"), ("第8章代谢功能", ("fermentation",), "仅见发酵通路潜力；未测定代谢物浓度、pH 或屏障通透性"), ("氧化应激相关功能", ("redox",), "仅描述微生物应激相关注释；不推算宿主抗氧化或屏障能力"))]
    raise ValueError("chapter 9 subsection out of range")


def interpretation(document, sub):
    if _failed(document):
        return "样本质控未通过，停止解释宿主互作相关功能。"
    if sub == 3:
        return "黏液糖链切割酶：" + _describe(document, ("mucin_enzyme",)) + "。相关单糖利用通路：" + _describe(document, ("host_glycan",)) + "。糖链底物可来自宿主、饮食或其他微生物；下游单糖利用不能证明黏蛋白切割。"
    keys = {1: ("substrate", "fermentation", "antimicrobial"), 2: ("lipid_a", "cell_wall", "flagellin"), 4: ("host_glycan", "fermentation", "redox")}.get(sub, ())
    count = len(_rows(document, keys))
    return (f"本节获得 {count} 条去重后的功能注释记录；不同通路可能重叠，未合并计分。" if count else NO_EVIDENCE) + LIMITATION


def render_section(body, sub):
    headers = {1: ["相关维度", "代表证据", "本次结果", "证据等级"], 2: ["相关特征", "关联方向", "适用背景", "证据等级"], 3: ["功能层次", "本次功能证据", "可解释范围"], 4: ["引用结果", "与本章的联系", "本次可解释范围"]}
    body.emit(headers[sub], table_rows(body.doc, sub))
    body.out.append(interpretation(body.doc, sub))


def paragraph(document, block):
    sub = block.get("sub", 0)
    text = block.get("text", "")
    if sub == 3 and ("待填" in text or "主要贡献菌" in text):
        return interpretation(document, 3)
    if text.strip().startswith("结果解读"):
        return "结果解读  " + interpretation(document, sub)
    return text


def flow_labels(document, spec):
    labels = []
    index = 0
    groups = (("substrate",), ("fermentation", "antimicrobial"), ("substrate", "fermentation", "antimicrobial"))
    for shape in spec.get("shapes", []):
        if not shape.get("text"):
            labels.append([])
            continue
        count = len(_rows(document, groups[min(index, 2)]))
        detail = "质控未通过" if _failed(document) else f"{count} 条功能注释；效果未验证" if count else "缺少有效功能注释"
        labels.append([shape["text"][0], detail])
        index += 1
    return labels
