"""Data presentation for public chapter 12 (source Word chapter 13)."""
from .inputs import finite


def module(document):
    value = document.get("template_inputs", {}).get("specialized_metabolism", {})
    return value if isinstance(value, dict) else {}


def status_note(document):
    value = module(document)
    if not value:
        return "专项代谢转化流程尚未生成；需核对基因家族产物和专项参考。"
    if value.get("generated_by") != "specialized-metabolism-v1":
        return None
    status = value.get("status")
    if status in {"completed", "partial"}:
        summary = value.get("summary", {})
        note = f"本次核对{summary.get('panel_count', 0)}项专项参考，其中{summary.get('supported_panels', 0)}项获得基因家族注释支持。"
        count = value.get("input_audit", {}).get("quarantined_rows", 0)
        if count:
            note += f"源文件有{count}条非标准UniRef条目已隔离，未参与计量；本次不据未匹配结果作功能阴性判断。"
        return note + "丰度保留HUMAnN原始单位，表示注释支持，不代表体内产物浓度或药物反应。"
    reasons = {"not_run": "尚未运行专项注释", "missing_input": "缺少或无法读取HUMAnN基因家族产物",
               "missing_database": "缺少专项参考映射", "invalid_input": "输入或专项参考校验未通过"}
    return "专项代谢转化未评估：" + reasons.get(status, "条件不足") + "；状态码：" + str(value.get("reason_code", "UNAVAILABLE")) + "。"


def source_notes(document, section):
    rows = module(document).get(section, [])
    seen, result = set(), []
    for row in rows:
        for reference in row.get("references", []):
            key = reference.get("doi") or reference.get("url")
            if key and key not in seen:
                seen.add(key)
                result.append(reference.get("title", "") + "；" + (("DOI: " + reference["doi"]) if reference.get("doi") else reference.get("url", "")))
    return result


def paragraph_text(document, block, data):
    value = module(document)
    if value.get("generated_by") != "specialized-metabolism-v1":
        return None
    text = block.get("text", "")
    if text.startswith("各项目独立填写"):
        return "反应方向及参考标记见表。分层贡献仅为HUMAnN指派；未提供用药信息，不判定实际药物转化、药效或剂量。"
    if text.startswith("结果解读"):
        if data.qc_failed:
            return "本次样本质控未通过，不进行专项代谢转化解读。"
        rows = [r for group in ["dietary", "drugs"] for r in value.get(group, [])]
        positive = [r["name"] for r in rows if r.get("status") == "annotation_detected"]
        return ("专项注释结果：" + ("；".join(positive) if positive else "当前未取得可展示的专项注释支持")
                + "。EC家族与实验参考蛋白同簇证据分开报告；未验证底物活性、完整通路和个体应用效应。")
    return None



def render_section(body, block):
    value = module(body.doc)
    if value.get("generated_by") != "specialized-metabolism-v1":
        return False
    key = {1: "dietary", 2: "drugs", 3: "validation"}[block]
    rows = [] if body.qc_failed else value.get(key, [])
    if block == 1:
        body.emit(["专项底物", "路径或酶证据", "主要贡献菌", "本次功能结果"],
            [[r["substrate"], r["enzyme"] + "；" + r["pathway"], r["contributors"], r["result"]] for r in rows])
    elif block == 2:
        body.emit(["专项项目", "已知酶或序列变异", "本次序列支持", "适用用药背景"],
            [[r["name"], r["enzyme"], r["result"] + "；" + r["sequence_support"], r["medication_background"]] for r in rows])
    else:
        body.emit(["专项项目", "路径注释证据", "健康关联或应用证据", "报告用途"],
            [[r["name"], r["annotation_evidence"], r["application_evidence"], r["intended_use"]] for r in rows])
    return True
