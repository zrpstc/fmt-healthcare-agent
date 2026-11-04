"""Disease feature presentation (source Word chapter 12, public chapter 11)."""
from .inputs import finite


def _module(document):
    return document.get("template_inputs", {}).get("diseases", {})


def table_headers(document, block):
    if block.get("id") == "12.2.t1" and _module(document).get("generated_by") == "disease-species-features-v1":
        return ["研究模块", "物种及本次相对丰度", "原研究组间方向", "证据与文献"]
    return None


def feature_rows(document, data):
    if _module(document).get("generated_by") != "disease-species-features-v1":
        return None
    rows = []
    for record in data.group("disease"):
        for detail in record.get("details", []):
            value = finite(detail.get("abundance"))
            observed = f"{value:.5g}%" if value is not None else "未在物种谱报告，未定量"
            rows.append([record["label"], f"{detail['species']}：{observed}",
                         detail["direction"], f"{detail.get('evidence_level', '未提供')}；DOI: {detail.get('doi', '未提供')}"])
    return rows


def status_note(document):
    module = _module(document)
    if not module:
        return "疾病关联分析尚未生成；需检查物种输入与关联参考，不将空结果解释为无疾病关联。"
    if module.get("generated_by") != "disease-species-features-v1":
        return None
    if module.get("status") != "completed":
        reasons = {
            "TAXONOMY_UNAVAILABLE": "缺少完整有效的物种谱",
            "DISEASE_REFERENCE_UNAVAILABLE": "疾病关联参考文件不可读或不存在",
            "DISEASE_REFERENCE_INVALID": "疾病关联参考格式或证据字段不完整",
            "TAXONOMY_UNIT_INCOMPATIBLE": "物种丰度单位与关联流程不兼容",
            "INVALID_TAXONOMY": "物种谱记录格式无效",
            "INVALID_OR_AMBIGUOUS_TAXONOMY": "物种谱存在无效值、重复名称或混合单位",
        }
        return "疾病物种关联未评估：" + reasons.get(module.get("reason_code"), "输入或参考条件不足") + "。"
    note = "物种关联流程已完成：本次仅核对结直肠癌与克罗恩病的文献物种特征。其他疾病类别及疾病功能标记尚未评估；现有健康参考不提供同口径病例/对照比较。"
    if not any(row.get("kind") == "prediction" for row in document.get("evidence", {}).values()):
        note += " 模型未启用：未配置可执行且符合本样本条件的疾病模型；缺少特征/预处理定义及独立外部验证资料。"
    return note


def references(document):
    seen = set()
    result = []
    for module in _module(document).get("diseases", []):
        for ref in module.get("references", []):
            if ref.get("doi") and ref["doi"] not in seen:
                seen.add(ref["doi"])
                result.append(f"{ref.get('authors', '')} ({ref.get('year', '')}). {ref.get('title', '')}. DOI: {ref['doi']}；定位：{ref.get('locator', '')}。")
    return result


def paragraph_text(document, block, data):
    module = _module(document)
    if module.get("generated_by") != "disease-species-features-v1":
        return None
    text = block.get("text", "")
    if text.startswith("结果解读") and block.get("sub") == 4 and not data.group("prediction"):
        return "模型结果解读：本次未启用疾病预测模型，不能报告分类分值、未来发病概率或预测区间。物种关联结果见第11.2节。"
    if text.startswith("文献来源"):
        if data.qc_failed:
            return "本次样本质控未通过，不进行疾病相关特征解读。"
        return "文献依据：" + "；".join(references(document)) + " 本次未估计组间效应或统计显著性。"
    if text.startswith("所选模块的主要线索"):
        if data.qc_failed:
            return "本次样本质控未通过，不进行疾病相关特征解读。"
        return "所选模块的主要线索：" + "；".join(r["result"] for r in module.get("diseases", [])) + "。文献中的富集/减少是原研究组间方向，本样本尚未判定同向或反向。"
    return None
