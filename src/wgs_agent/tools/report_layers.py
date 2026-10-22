"""Build the three report layers consumed by people, reviewers, and the web UI."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "wgs-fmt-interactive-report-v1"


def _rows(value: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get(key), list):
        return []
    return [row for row in value[key] if isinstance(row, dict)]


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _text(value: Any, default: str = "未提供") -> str:
    if value is None or value == "":
        return default
    return str(value).replace("|", "／").replace("\n", " ")


def _table(headers: list[str], values: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(_text(item) for item in row) + " |" for row in values)
    return "\n".join(lines)


def _series(
    evidence: dict[str, Any],
    prefix: str,
    label_keys: tuple[str, ...],
    value_keys: tuple[str, ...],
    limit: int = 20,
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for evidence_id, record in evidence.items():
        if not evidence_id.startswith(prefix) or not evidence_id[len(prefix):].isdigit() or not isinstance(record, dict):
            continue
        label = next((_text(record.get(key), "") for key in label_keys if record.get(key) not in (None, "")), evidence_id)
        number = next((_number(record.get(key)) for key in value_keys if _number(record.get(key)) is not None), None)
        if number is None:
            continue
        values.append({
            "evidence_id": evidence_id,
            "label": label,
            "value": number,
            "status": record.get("status") or record.get("risk_level") or "unknown",
            "unit": record.get("unit") or "",
            "p5": _number(record.get("p5")),
            "p95": _number(record.get("p95")),
            "record": record,
        })
    return sorted(values, key=lambda item: item["value"], reverse=True)[:limit]


def build_main_report(
    sample_id: str,
    species_data: dict[str, Any],
    enterotype_data: dict[str, Any],
    pathway_data: dict[str, Any],
    disease_data: dict[str, Any],
    matching_data: dict[str, Any],
    context: dict[str, Any],
) -> str:
    """A short user-facing report. It intentionally omits large evidence tables."""
    species = _rows(species_data, "species_list") or _rows(species_data, "abnormal_species")
    pathways = _rows(pathway_data, "pathways")
    diseases = _rows(disease_data, "diseases")
    donors = _rows(matching_data, "top_k_matches")
    top_species = sorted(species, key=lambda row: _number(row.get("abundance")) or -1, reverse=True)[:10]
    top_pathways = sorted(pathways, key=lambda row: _number(row.get("abundance")) or -1, reverse=True)[:8]
    lines = [
        "# WGS.FMT 肠道宏基因组分析主报告",
        "",
        f"- 样本编号：{_text(sample_id)}",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"报告版本：{_text(context.get('report_version'))}-three-layer",
        "- 报告定位：面向用户的结果摘要；完整方法、参数、证据表和版本见技术附录。",
        "",
        "> 本报告用于科研与健康管理参考，不构成疾病诊断、治疗建议或 FMT 临床决策。",
        "",
        "## 结果概览",
        "",
        _table(["模块", "本次结果", "解释边界"], [
            ["物种组成", f"{len(species)} 条可用记录", "相对丰度是计算估计，受数据库和组成性约束"],
            ["群落结构", _text(enterotype_data.get("enterotype") or enterotype_data.get("type")), "肠型与二维投影不能单独用于诊断"],
            ["功能通路", f"{len(pathways)} 条可用记录", "表示 DNA 编码潜能，不是代谢物浓度或酶活性"],
            ["疾病关联", f"{len(diseases)} 项关联结果", "关联分不是患病概率"],
            ["FMT 配型", f"{len(donors)} 个候选", "排序分不是移植成功率"],
        ]),
        "",
        "## 主要物种组成",
        "",
    ]
    if top_species:
        lines.append(_table(["物种", "相对丰度", "参考状态"], [
            [row.get("species") or row.get("name"), row.get("abundance"), row.get("status_cn") or row.get("status")]
            for row in top_species
        ]))
    else:
        lines.append("本次没有可展示的物种明细。")
    lines.extend(["", "## 功能摘要", ""])
    if top_pathways:
        lines.append(_table(["通路", "丰度", "单位"], [
            [row.get("name") or row.get("pathway"), row.get("abundance"), row.get("unit") or pathway_data.get("unit")]
            for row in top_pathways
        ]))
    else:
        lines.append("本次没有可展示的功能通路结果，不能由物种名称直接推断功能。")
    lines.extend(["", "## FMT 候选供体", ""])
    if matching_data.get("status") == "ok" and donors:
        lines.append(_table(["排序", "候选供体", "相对匹配分", "距离"], [
            [index, row.get("donor_id"), row.get("score"), row.get("distance")]
            for index, row in enumerate(donors[:5], 1)
        ]))
        lines.append("候选结果还需结合适应证、供体筛查、抗生素暴露、采样时间以及菌株级随访证据判断。")
    else:
        lines.append("本次没有可用的 FMT 候选排序。")
    lines.extend([
        "",
        "## 阅读与复核",
        "",
        "- 在交互展示中查看 Top 物种、通路、疾病关联和供体排序，并按模块筛选。",
        "- 在技术附录中核对质控、参考人群、算法版本、证据编号、完整表格和限制条件。",
        f"- 分析文件校验值：{_text(context.get('analysis_sha256'))}。",
    ])
    return "\n".join(lines).rstrip() + "\n"


def build_technical_appendix(full_report: str, context: dict[str, Any]) -> str:
    """Preserve the complete evidence-led report as the audit/review layer."""
    provenance = _table(["项目", "记录"], [
        ["分析 SHA256", context.get("analysis_sha256")],
        ["知识证据 SHA256", context.get("knowledge_sha256")],
        ["Pipeline 版本", context.get("pipeline_version")],
        ["参考数据库版本", context.get("reference_version")],
        ["报告版本", context.get("report_version")],
        ["LLM 状态", context.get("llm_status")],
        ["LLM 模型", context.get("llm_model")],
    ])
    body = full_report.lstrip()
    if body.startswith("# "):
        body = body.split("\n", 1)[1] if "\n" in body else ""
    return (
        "# WGS.FMT 技术附录与审计记录\n\n"
        "本文件面向研究人员和审核人员，保留完整数据表、计算边界、证据编号和可复现信息。\n\n"
        "## 产物与版本溯源\n\n"
        + provenance
        + "\n\n## 完整分析结果\n\n"
        + body.rstrip()
        + "\n"
    )


def build_interactive_payload(
    sample_id: str,
    evidence: dict[str, Any],
    enterotype_data: dict[str, Any],
    matching_data: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Machine-readable view model. The UI must not infer new clinical claims."""
    charts = [
        {"id": "species", "title": "主要物种相对丰度", "kind": "bar", "boundary": "相对丰度为计算估计。", "items": _series(evidence, "S", ("species", "name"), ("abundance",))},
        {"id": "pathways", "title": "功能通路", "kind": "bar", "boundary": "表示编码潜能，不代表代谢物实测浓度。", "items": _series(evidence, "P", ("name", "pathway"), ("abundance",))},
        {"id": "diseases", "title": "疾病关联", "kind": "bar", "boundary": "关联分不是患病概率。", "items": _series(evidence, "D", ("disease", "name"), ("risk_score", "association_score"))},
        {"id": "matching", "title": "FMT 候选供体", "kind": "bar", "boundary": "匹配分只用于当前候选库排序，不是成功率。", "items": _series(evidence, "F", ("donor_id", "sample_id"), ("score",))},
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "sample_id": sample_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "enterotype": enterotype_data.get("enterotype") or enterotype_data.get("type"),
            "fmt_status": matching_data.get("status"),
            "analysis_sha256": context.get("analysis_sha256"),
            "knowledge_sha256": context.get("knowledge_sha256"),
            "reference_cohort": context.get("reference_cohort") or {},
        },
        "charts": charts,
        "available_modules": [chart["id"] for chart in charts if chart["items"]],
        "disclaimer": "仅用于科研与健康管理参考，不构成诊断、治疗或 FMT 临床决策。",
    }


def build_report_layers(
    *,
    sample_id: str,
    full_report: str,
    evidence: dict[str, Any],
    species_data: dict[str, Any],
    enterotype_data: dict[str, Any],
    pathway_data: dict[str, Any],
    disease_data: dict[str, Any],
    matching_data: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "main_markdown": build_main_report(
            sample_id, species_data, enterotype_data, pathway_data, disease_data, matching_data, context
        ),
        "technical_markdown": build_technical_appendix(full_report, context),
        "interactive": build_interactive_payload(sample_id, evidence, enterotype_data, matching_data, context),
    }
