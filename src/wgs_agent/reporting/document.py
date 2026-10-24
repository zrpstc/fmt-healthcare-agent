"""Deterministic evidence topics with a template-aligned reader-facing body.

Keyword routing chooses which existing evidence to display. It does not calculate
metabolite concentrations, host function scores, or disease probabilities.
"""

from __future__ import annotations

import html
import math
from datetime import datetime, timezone
from typing import Any

from .catalog import SECTIONS, TITLE, VERSION
from .inputs import diversity_metrics, finite

DATA_LABELS = {
    "available": "有可用结果",
    "partial": "部分可评估",
    "missing": "暂未评估",
}
TYPE_LABELS = {
    "taxonomic_estimate": "菌群丰度估计",
    "functional_potential": "功能潜能",
    "model_inferred": "模型推算",
    "measured": "检测结果",
    "association": "研究关联",
    "calculated": "计算指标",
    "reported": "问卷或背景记录",
    "prediction": "模型预测",
    "unverified": "来源类型待核实",
    "amr_detection": "耐药基因检测",
    "sequence_detection": "专项序列检测",
}


def records(data: Any, *keys: str) -> list[dict]:
    if isinstance(data, list):
        return [dict(row) for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in (*keys, "observations", "items", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return records(value)
    return []


def text(value: Any, missing: str = "未提供") -> str:
    if value is None or value == "":
        return missing
    return html.unescape(str(value)).replace("|", "／").replace("\n", " ").strip()


def number(value: Any) -> str:
    value = finite(value)
    return f"{value:.5g}" if value is not None else "未提供"


def table(headers: list[str], rows: list[list[Any]]) -> str:
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(text(cell) for cell in row) + " |" for row in rows),
        ]
    )


def _label(row: dict) -> str:
    for key in ("chinese_name", "name", "species", "disease", "gene", "gene_family", "mutation", "marker", "id"):
        if row.get(key):
            return text(row[key])
    return "未命名条目"


def _unit(value: Any) -> str:
    return {"percent": "%", "percentage": "%", "relative_abundance": "相对丰度"}.get(
        str(value), text(value)
    )


def _matches(row: dict, keywords: tuple[str, ...]) -> bool:
    # Search identifying fields only: method descriptions and caveats must not
    # make every record look relevant to a biological topic.
    haystack = " ".join(
        str(row.get(key, ""))
        for key in (
            "name",
            "species",
            "disease",
            "id",
            "annotation",
            "drug_class",
            "mechanism",
            "topic",
            "topic_id",
            "metric",
            "gene",
            "gene_family",
            "symptom",
        )
    ).lower()
    return not keywords or any(word.lower() in haystack for word in keywords)


def _safe_json(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    return value


def _measurement_type(row: dict, parent: dict, fallback: str) -> str:
    declared = row.get("data_type", parent.get("data_type", ""))
    if declared in {"measured", "metabolomics", "clinical_measurement"}:
        if row.get("method", parent.get("method")) and row.get("unit", parent.get("unit")):
            return "measured"
        return "unverified"
    if (
        declared in {"model_inferred", "model_prediction"}
        or parent.get("status") == "model_inferred"
    ):
        return "model_inferred"
    if declared in {"functional_potential", "association", "taxonomic_estimate", "reported"}:
        return declared
    return fallback


def build_document(
    sample_id: str,
    species: dict,
    compare: dict,
    enterotype: dict,
    pathways: dict,
    metabolites: dict,
    drugs: dict,
    diseases: dict,
    knowledge: dict,
    proteins: dict | None = None,
    matching: dict | None = None,
    context: dict | None = None,
) -> dict:
    context = context or {}
    inputs = context.get("health_inputs") or {}
    evidence: dict[str, dict] = {}
    groups: dict[str, list[str]] = {}
    counts: dict[str, int] = {}

    def add(group: str, prefix: str, row: dict, kind: str, parent: dict | None = None) -> None:
        parent = parent or {}
        counts[prefix] = counts.get(prefix, 0) + 1
        key = f"{prefix}{counts[prefix]}"
        item = dict(row)
        # Legacy heuristic risk labels are not clinical predictions.
        for field in ("risk_level", "is_high_risk", "api_key", "token", "password"):
            item.pop(field, None)
        value = next((item[k] for k in ("value", "abundance", "risk_score") if k in item), None)
        unit = item.get("unit", parent.get("unit"))
        label = _label(item)
        item.update(
            {
                "kind": group,
                "label": label,
                "unit": _unit(unit),
                "measurement_type": kind,
                "value": finite(value),
            }
        )
        if value is not None and item["value"] is None:
            return  # NaN, infinity and malformed measurements never become results.
        if "risk_score" in item:
            item["unit"] = "关联分（非患病概率）"
        reference = item.get("comparison_reason_cn") or {
            "species_not_in_reference": "参考库未覆盖该物种",
            "zero_width_reference_interval": "参考分布为零宽区间，暂不判定高低",
            "incompatible_unit": "当前单位与参考库不兼容，暂不比较",
            "invalid_observation": "输入值无效，暂不比较",
        }.get(item.get("comparison_reason"), "未建立参考比较")
        p5, p95 = finite(item.get("p5")), finite(item.get("p95"))
        item["comparison"] = "unknown"
        if (
            item.get("status") in {"normal", "high", "low", "absent"}
            and p5 is not None
            and p95 is not None
            and p95 > p5
        ):
            reference = f"参考人群 P5–P95：{number(p5)}–{number(p95)}"
            if item["value"] is not None:
                item["comparison"] = (
                    "above" if item["value"] > p95 else "below" if item["value"] < p5 else "within"
                )
        item["reference_text"] = reference
        if item["value"] is not None:
            result = f"{number(item['value'])} {item['unit']}"
        else:
            result = text(item.get("result", item.get("answer", item.get("reported"))))
            if result == "未提供" and (item.get("detected") is not None or item.get("detection_status") is not None):
                state = item.get("detection_status", item.get("detected"))
                result = "检出" if state is True else "本次未检出" if state is False else text(state)
            if (
                isinstance(item.get("reported"), bool)
                and not item.get("result")
                and not item.get("answer")
            ):
                result = "已报告该情况" if item["reported"] else "未报告该情况"
            if result == "未提供":
                return
        if item["comparison"] != "unknown":
            reference += (
                "（"
                + {"above": "高于参考", "below": "低于参考", "within": "区间内"}[item["comparison"]]
                + "）"
            )
            item["reference_text"] = reference
        if item["comparison"] != "unknown":
            median = finite(item.get("reference_median"))
            if median is not None:
                reference += f"；中位数 {number(median)}"
            n_reference = finite(item.get("n_reference"))
            if n_reference is not None:
                reference += f"；参考样本 n={int(n_reference)}"
            percentile = finite(item.get("percentile"))
            if percentile is not None:
                population = "健康人群" if item.get("generated_by") == "healthy-reference-v1" else "供体子集"
                reference += f"；{population}经验百分位 {number(percentile)}"
            if item.get("generated_by") == "reference-comparison-v1":
                reference += "（探索性）"
            item["reference_text"] = reference
        item["result_text"] = result
        item["finding"] = (
            f"{label}：{result}；{reference}；数据类型：{TYPE_LABELS.get(kind, kind)}。"
        )
        if group == "disease":
            details = records(item, "details", "key_species")
            item["feature_summary"] = "；".join(
                f"{text(r.get('species'))}（样本状态：{text(r.get('status_cn', r.get('status')))}；研究方向：{text(r.get('direction'))}）"
                for r in details[:8]
            )
            if item["feature_summary"]:
                item["finding"] += "关联菌群记录：" + item["feature_summary"]
        evidence[key] = item
        groups.setdefault(group, []).append(key)

    sp = (
        records(species, "species_list")
        or records(compare, "comparison", "species_list")
        or records(species, "abnormal_species")
    )
    for row in sp:
        add("species", "S", row, "taxonomic_estimate", species)
    taxonomy = inputs.get("taxonomy") or species.get("taxonomy") or {}
    ranks = taxonomy.get("ranks", {})
    for rank in ("phylum", "genus", "class", "order", "family"):
        for row in records(ranks.get(rank)):
            add(f"tax_{rank}", "T", row, "taxonomic_estimate", taxonomy)
    if not sp:
        for row in records(ranks.get("species")):
            add("species", "S", {**row, "species": row.get("name")}, "taxonomic_estimate", taxonomy)
    if enterotype.get("enterotype") or enterotype.get("type"):
        add(
            "enterotype",
            "E",
            {
                **enterotype,
                "name": "优势菌群分型",
                "result": enterotype.get("enterotype", enterotype.get("type")),
                "method": enterotype.get("method", "输入算法，校准信息未提供"),
            },
            "calculated",
        )
    complete_sp = records(ranks.get("species")) if taxonomy.get("complete") is True else []
    if not complete_sp and species.get("is_complete_profile") is True:
        complete_sp = sp
    diversity = (
        inputs.get("diversity")
        or species.get("diversity")
        or diversity_metrics(complete_sp, complete=bool(complete_sp))
    )
    for name, title in (
        ("richness", "检出丰富度"),
        ("shannon", "Shannon 指数"),
        ("simpson", "Simpson 指数（1−D）"),
        ("evenness", "Pielou 均匀度"),
    ):
        value = diversity.get(name)
        if value is None and name in {"shannon", "simpson"}:
            value = species.get(name)
        if finite(value) is not None:
            add(
                f"div_{name}",
                "V",
                {
                    "name": title,
                    "value": value,
                    "unit": "种" if name == "richness" else "无量纲",
                    "method": diversity.get(
                        "definition", diversity.get("method", "沿用输入，需核对指数定义")
                    ),
                },
                "calculated",
            )
    for row in records(diversity.get("reference_comparisons")) + records(diversity.get("longitudinal")):
        add("div_reference", "V", row, "calculated")
    if complete_sp:
        values = [finite(row.get("abundance")) for row in complete_sp]
        if all(v is not None and v >= 0 for v in values) and math.fsum(values) > 0:
            total = math.fsum(values)
            concentration = math.fsum(sorted(values, reverse=True)[:5]) / total * 100
            add(
                "dominance",
                "V",
                {
                    "name": "前五位物种合计占比",
                    "value": concentration,
                    "unit": "%",
                    "method": "完整输入物种谱内归一化占比",
                },
                "calculated",
            )
    for row in records(pathways, "pathways"):
        name = str(row.get("id", row.get("name", row.get("pathway", "")))).split("|")[0]
        if name in {"UNMAPPED", "UNINTEGRATED"}:
            continue
        add("pathway", "P", row, "functional_potential", pathways)
    for row in records(metabolites, "metabolites"):
        add("metabolite", "M", row, _measurement_type(row, metabolites, "unverified"), metabolites)
    for row in records(diseases, "diseases"):
        add("disease", "D", row, "association", diseases)
    for key, group, prefix, kind in (
        ("functional_modules", "function", "U", "functional_potential"),
        ("nutrition", "nutrition", "N", "reported"),
        ("diet", "diet", "H", "reported"),
        ("symptoms", "symptom", "Y", "reported"),
        ("gut_brain", "axis", "X", "functional_potential"),
        ("pathogens", "pathogen", "J", "sequence_detection"),
    ):
        parent = inputs.get(key) or {}
        for row in records(parent, "associations", "measurements"):
            add(
                group,
                prefix,
                row,
                _measurement_type(row, parent if isinstance(parent, dict) else {}, kind),
                parent if isinstance(parent, dict) else {},
            )
    resistance = inputs.get("resistance") or {}
    for row in records(resistance, "genes"):
        # A drug interaction score is not a resistance-gene detection.
        if row.get("gene") or row.get("gene_family") or row.get("mutation"):
            add(
                "amr", "A", row, "amr_detection", resistance if isinstance(resistance, dict) else {}
            )
    for module, group, prefix, keys in (
        ("virulence", "virulence", "Z", ("markers", "genes")),
    ):
        parent = inputs.get(module) or {}
        for row in records(parent, *keys):
            item = dict(row)
            if not any(k in item for k in ("value", "abundance", "result")):
                state = item.get("detection_status", item.get("detected"))
                if state is not None:
                    item["result"] = "检出" if state is True else "本次未检出" if state is False else str(state)
            add(group, prefix, item, "sequence_detection", parent if isinstance(parent, dict) else {})
    skipped_predictions = 0
    for row in records(inputs.get("disease_models"), "predictions"):
        if (
            row.get("externally_validated") is True
            and row.get("applicable") is True
            and row.get("model_version")
        ):
            add("prediction", "Q", row, "prediction")
        else:
            skipped_predictions += 1
    from wgs_agent.tools.detailed_report import REFERENCES

    for row in REFERENCES:
        evidence[row["id"]] = {**row, "kind": "method_reference"}
    for prefix, key in (("K", "matched_docs"), ("B", "pubmed_results")):
        for index, row in enumerate(records(knowledge, key), 1):
            evidence[f"{prefix}{index}"] = {**row, "kind": "literature"}

    qc_failed = str(context.get("qc_status", "")).strip().lower() in {
        "failed",
        "fail",
        "不通过",
        "未通过",
    }
    sections = []
    for spec in SECTIONS:
        topics = []
        for topic in spec.topics:
            selected = []
            for group in topic.sources:
                candidates = groups.get(group, [])
                if group.endswith("_other"):
                    base = group.removesuffix("_other")
                    sibling_specs = [t for t in spec.topics if base in t.sources and t.keywords]
                    candidates = [
                        key
                        for key in groups.get(base, [])
                        if not any(_matches(evidence[key], t.keywords) for t in sibling_specs)
                    ]
                selected.extend(
                    key for key in candidates if _matches(evidence[key], topic.keywords)
                )
            if spec.id == "symptoms" and selected:
                related = set()
                for key in selected:
                    names = evidence[key].get("related_species", [])
                    if isinstance(names, list):
                        related.update(str(name).casefold() for name in names)
                relevant_claims = []
                for row in evidence.values():
                    if row.get("kind") != "literature":
                        continue
                    claim_text = " ".join(
                        str(row.get(field, ""))
                        for field in ("evidence_text", "conclusion", "abstract")
                    ).casefold()
                    if any(word.casefold() in claim_text for word in topic.keywords):
                        relevant_claims.append(claim_text)
                for key in groups.get("species", []):
                    name = str(evidence[key].get("species", "")).casefold()
                    if name and (
                        name in related or any(name in claim for claim in relevant_claims)
                    ):
                        selected.append(key)
            selected = list(dict.fromkeys(selected))
            priority = {
                "measured": 0,
                "calculated": 1,
                "taxonomic_estimate": 1,
                "reported": 1,
                "amr_detection": 1,
                "association": 1,
                "prediction": 1,
                "model_inferred": 2,
                "functional_potential": 3,
                "unverified": 4,
            }
            selected.sort(
                key=lambda key: (
                    priority.get(evidence[key]["measurement_type"], 4),
                    evidence[key]["measurement_type"],
                    evidence[key]["unit"],
                    -(evidence[key].get("value") or 0),
                )
            )
            topic_id = f"{spec.id}.{topic.id}"
            knowledge_ids = [
                key
                for key, row in evidence.items()
                if row.get("kind") == "literature"
                and (
                    topic_id in (row.get("topic_ids") or [])
                    or any(
                        word.lower()
                        in " ".join(
                            str(row.get(field, ""))
                            for field in ("evidence_text", "conclusion", "abstract")
                        ).lower()
                        for word in (topic.keywords or (topic.title,))
                    )
                    or any(
                        str(evidence[sample_key].get("species", "__no_species__")).lower()
                        in str(row).lower()
                        for sample_key in selected[:8]
                    )
                )
            ]
            # One generic methods paper cannot support a clinical or mechanistic claim.
            allowed = selected[:24] + knowledge_ids[:8]
            status = "available" if selected else "missing"
            if (
                selected
                and all(
                    evidence[key]["measurement_type"] in {"functional_potential", "unverified"}
                    for key in selected
                )
                and spec.id in {"metabolites", "gut_brain"}
            ):
                status = "partial"
            notes = _topic_note(spec.id, topic.id, selected, evidence, topic.missing)
            if qc_failed:
                status = "missing"
                notes = "本次样本质控未通过，暂不进行健康解读。"
            topics.append(
                {
                    "id": topic_id,
                    "title": topic.title,
                    "status": status,
                    "evidence_ids": selected,
                    "allowed_narrative_ids": allowed,
                    "finding": _finding(selected, evidence, notes),
                    "note": notes,
                    "interpretation": "",
                    "advice": "",
                    "narrative_source": "rule",
                }
            )
        available = sum(topic["status"] != "missing" for topic in topics)
        status = (
            "missing" if not available else "available" if available == len(topics) else "partial"
        )
        sections.append(
            {
                "id": spec.id,
                "title": spec.title,
                "introduction": spec.introduction,
                "status": status,
                "topics": topics,
            }
        )
    metadata = {
        key: context[key]
        for key in (
            "name",
            "age",
            "sex",
            "collection_time",
            "report_date",
            "sequencing_platform",
            "qc_status",
            "demonstration",
        )
        if context.get(key) not in (None, "")
    }
    document = _safe_json(
        {
            "schema_version": VERSION,
            "title": TITLE,
            "sample_id": sample_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata,
            "sections": sections,
            "template_inputs": _template_inputs(inputs),
            "evidence": evidence,
            "audit": {
                "analysis_sha256": context.get("analysis_sha256"),
                "knowledge_sha256": context.get("knowledge_sha256"),
                "pipeline_version": context.get("pipeline_version"),
                "reference_version": context.get("reference_version"),
                "reference_comparison": context.get("reference_comparison", {}),
                "omitted_unvalidated_predictions": skipped_predictions,
                "pathway_annotation": pathways.get("special_rows", {}),
                "gene_family_count": (proteins or {}).get("n_total"),
                "llm_status": "not_generated",
                "semantic_entailment_verified": False,
            },
            "references": knowledge,
            "fmt_matching": matching or {},
        }
    )

    from .knowledge_graph import attach_subgraphs

    attach_subgraphs(document)
    return document


def _template_inputs(inputs: dict) -> dict:
    """Retain only declared report modules; never retain credentials in nested data."""
    from .template_catalog import TEMPLATE_INPUT_KEYS

    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()
                    if str(k).lower() not in {"api_key", "token", "password", "secret", "authorization"}}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    return _safe_json({key: clean(inputs[key]) for key in TEMPLATE_INPUT_KEYS if key in inputs})


def _topic_note(section: str, topic: str, ids: list[str], evidence: dict, missing: str) -> str:
    if not ids:
        return missing
    if section == "diversity":
        return "参考人群与测序方法会影响比较；本次不设置通用健康分界值。"
    if section == "key_taxa":
        return "菌群分组用于整理检测线索；物种检出不等于致病菌株或毒力标志阳性。"
    if section == "metabolites":
        if all(evidence[key]["measurement_type"] == "functional_potential" for key in ids):
            return "本项目前仅有相关通路证据，尚不能判断代谢物浓度或实际产量。"
        return "请结合来源类型与单位阅读；通路丰度、模型推算和代谢物检测分别呈现。"
    if section == "gut_brain":
        return "相关微生物功能不能直接换算为血液、脑内神经递质或宿主激素水平。"
    if section == "nutrition":
        return "营养状态需结合饮食与专项检验；菌群丰度不用于直接判定缺铁、缺锌或维生素缺乏。"
    if section == "diseases":
        return "关联分不是患病概率；预测模型仅在验证和样本适用条件满足时单独呈现。"
    if section == "resistance":
        return "耐药基因检出不等于致病菌表型耐药，不能直接用于选择或停用抗生素。"
    if section == "symptoms":
        return "症状记录与菌群关联不确定病因，需结合病程、饮食和用药背景。"
    if section in {"ecology", "nutrient_metabolism"}:
        return "宏基因组通路反映功能潜能；宿主功能和代谢活性需结合专项检测。"
    return "参考区间描述对应人群的分布，偏离区间不等于疾病。"


def _finding(ids: list[str], evidence: dict, missing: str) -> str:
    if not ids:
        return missing
    first = evidence[ids[0]]
    suffix = {
        "above": "，高于所用参考人群区间",
        "below": "，低于所用参考人群区间",
        "within": "，位于所用参考人群区间",
    }.get(first.get("comparison"), "")
    return f"{first['label']}：{first['result_text']}{suffix}。"


def render_markdown(document: dict) -> str:
    """Both PDF and online preview consume this exact, reader-facing content."""
    from .knowledge_graph import attach_subgraphs
    from .template_body import prepare_presentation, render_overview, render_toc
    from .word_template import render_body

    attach_subgraphs(document)
    prepare_presentation(document)
    output = [
        f"# {document['title']}",
        f"样本编号：{text(document['sample_id'])}  \n报告日期：{document['generated_at'][:10]}  \n报告版本：{document['schema_version']}",
    ]
    if document["metadata"].get("demonstration") is True:
        output.append(
            "> 演示说明：本报告全部检测数值为合成示例，仅用于检查结构、文案与排版，不用于健康判断。"
        )
    labels = {
        "name": "姓名",
        "age": "年龄",
        "sex": "性别",
        "collection_time": "采样时间",
        "sequencing_platform": "测序平台",
        "qc_status": "质控记录",
    }
    if document["metadata"]:
        output.append(
            table(
                ["基本信息", "记录"],
                [
                    [labels[key], value]
                    for key, value in document["metadata"].items()
                    if key in labels
                ],
            )
        )
    output.extend(render_toc())
    output.extend(render_overview(document))
    reference = document["audit"].get("reference_comparison") or {}
    healthy = reference.get("healthy_population") or {}
    if healthy.get("status") == "available":
        output.append(
            f"健康人群对照：{text(healthy.get('cohort_id'))}，参考独立个体 n={healthy['n_subjects']}；"
            f"队列版本：{text(healthy.get('cohort_version'))}。"
            + " ".join(healthy.get("limitations", []))
        )
    elif healthy:
        output.append("健康人群对照：未建立。" + text(healthy.get("reason_cn")) + "。")
    species_reference = reference.get("species") or {}
    if species_reference.get("status") == "available":
        output.append(
            f"参考比较：本次 {species_reference.get('compared_count', 0)} 个物种条目有可用参考区间，"
            f"{species_reference.get('uncovered_count', 0)} 个条目因覆盖、单位或参考分布限制暂不比较。"
            + (
                "物种 P5–P95 描述所选健康队列中央 90% 的分布。"
                if healthy.get("status") == "available" else
                "物种 P5–P95 描述参考人群中央 90% 的分布；参考人群的健康筛选和分析数据库版本尚待核验。"
            )
        )
    elif species_reference:
        output.append(
            "参考比较：健康参考条件不满足，本次不发布物种高低判断。"
            if healthy.get("configured") else
            "参考比较：当前物种参考表不可用，未自动建立新的物种比较；输入中已有比较予以保留。"
        )
    diversity_reference = reference.get("diversity") or {}
    if diversity_reference.get("status") == "available" and healthy.get("status") != "available":
        output.append(
            f"多样性参照：使用 {diversity_reference['n_reference']} 份标注健康供体的研究样本，"
            "与本样本采用相同公式计算。该子集未按年龄、性别和地区匹配，数据库与完整特征口径尚待核验，"
            "仅呈现探索性人群位置；样本数不等同于已核验的独立人数。"
        )
    output.append(
        "> 阅读提示：本报告分别标识菌群估计、功能潜能、检测结果和模型推算。未评估项目不表示正常，报告用于健康管理与研究参考，不能替代临床诊断。"
    )
    output.extend(render_body(document))
    output.extend(
        [
            "## 附录与参考资料",
            "### 数据说明",
            "物种相对丰度以对应输入单位呈现；参考人群 P5–P95 为分布区间。HUMAnN 基因家族不等于蛋白质表达，功能通路不等于代谢物浓度。完整来源、方法、数值与引用记录保存在结构化报告及证据文件中。",
        ]
    )
    from .bibliography import render_bibliographies
    output.extend(render_bibliographies(document))
    matching = document.get("fmt_matching") or {}
    if matching.get("top_k_matches"):
        output.extend(_fmt_appendix(matching))
    return "\n\n".join(output) + "\n"


def _fmt_appendix(matching: dict) -> list[str]:
    output = [
        "### 扩展分析：FMT 候选配对",
        "候选排序分不是临床成功概率；历史响应率也不是当前受体的疗效预测。",
    ]
    if matching.get("model_name") == "fmt-triplet-contrastive":
        output.append("当前模型将嵌入距离转换为 exp(-d/τ) 形式的相对匹配分。")
    output.append(
        table(
            ["候选供体", "相对匹配分", "嵌入距离", "历史响应率"],
            [
                [
                    row.get("donor_id"),
                    number(row.get("score")),
                    number(row.get("distance")),
                    number(row.get("historical_response_rate")),
                ]
                for row in matching["top_k_matches"][:10]
            ],
        )
    )
    output.append("物种丰度差是描述性比较，不能等同于模型贡献、定植预测或因果机制。")
    for row in matching["top_k_matches"][:3]:
        comparison = records(row, "species_comparison")
        if comparison:
            output.append(f"候选 {text(row.get('donor_id'))}")
            output.append(
                table(
                    ["物种", "受体丰度", "供体丰度", "差值（百分点）"],
                    [
                        [
                            r.get("species"),
                            number(r.get("query")),
                            number(r.get("donor")),
                            number(r.get("difference")),
                        ]
                        for r in comparison[:10]
                    ],
                )
            )
    return output
