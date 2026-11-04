"""Translate chapter-four execution states without fabricating negative findings."""
from __future__ import annotations


from wgs_agent.pipeline.strain_virulence import load_chapter4_inputs


def status_message(value, module):
    label = "菌株 marker 分析" if module == "strains" else "毒力参考序列筛查"
    if not isinstance(value, dict):
        return f"尚未执行{label}，暂无可展示的样本结果。" if not value else None
    status = value.get("status")
    # Legacy user-supplied result dictionaries remain compatible.
    if status is None:
        return None
    messages = {
        "not_run": f"尚未执行{label}，暂无可展示的样本结果。",
        "running": f"{label}正在运行，结果尚未完成。",
        "missing_input": f"{label}缺少可读取且完整的输入数据；不能据此判为未检出。",
        "missing_database": f"{label}所需参考数据库未配置或不可读取；不能据此判为未检出。",
        "missing_tool": f"{label}所需分析工具不可用，本次尚未获得结果。",
        "insufficient_coverage": f"{label}已运行，但可用 marker 或序列覆盖不足，无法作出可靠的菌株层面判断。",
        "failed": f"{label}运行失败，需要补跑；本节没有有效的阴性结论。",
        "invalid_result": f"{label}产物未通过样本或格式校验，已停止使用。",
    }
    if module == 'strains' and status == 'failed' and value.get('reason_code') == 'INVALID_CONSENSUS_MARKER':
        return '菌株共识结果解析失败（marker 输出字段或格式不兼容），本次无法作出菌株判断。'
    if status != "completed":
        return messages.get(status, f"{label}状态未通过校验，暂无可用结果。")
    rows = value.get("strains" if module == "strains" else "markers", [])
    if rows:
        return None
    if module == "strains":
        return "已完成 marker 共识分析，但未获得达到质量门槛的菌株层面记录。"
    summary = value.get("summary", {})
    candidates = summary.get("subthreshold_groups", 0) if isinstance(summary, dict) else 0
    text = "已完成毒力参考序列筛查，本次未发现达到预设读段数、覆盖广度和身份率门槛的匹配。"
    if isinstance(candidates, int) and candidates > 0:
        text += f"另有 {candidates} 组低于门槛的候选匹配，未计为检出。"
    return text + "该结果仅描述本次序列筛查，不代表整体致病性或临床阴性结论。"


def refresh_analysis_modules(path, sid, root=None):
    """Refresh chapter four under the same lock used by report publication."""
    from .module_refresh import refresh_module_fields
    if root is None:
        from wgs_fmt_platform.paths import bioinformatics_root
        root = bioinformatics_root()
    modules = load_chapter4_inputs(sid, root, include_missing=False)
    return refresh_module_fields(path, sid, modules)


def has_results_schema(document):
    inputs = document.get("template_inputs", {})
    return any(isinstance(inputs.get(key), dict) and "status" in inputs[key]
               for key in ("strains", "virulence"))


def _state(document, module):
    from .template_body import Body

    if not has_results_schema(document) or Body(document).qc_failed:
        return None, None
    value = document.get("template_inputs", {}).get(module)
    if not isinstance(value, dict) or "status" not in value:
        return None, None
    return value, status_message(value, module)


def _screening_summary(value):
    summary = value.get("summary", {})
    reads = summary.get("processed_reads") if isinstance(summary, dict) else None
    parts = []
    if isinstance(reads, int) and not isinstance(reads, bool) and reads >= 0:
        parts.append(f"已分析 {reads:,} 条 reads")
    if value.get("status") == "completed":
        parts.append(f"达标标记 {len(value.get('markers', []))} 项")
    return "；".join(parts)


def table_rows(document, sub):
    """Bind explicit module states to the actual Word template table slots."""
    module = "strains" if sub == 1 else "virulence"
    value, message = _state(document, module)
    if value is None or not message:
        return None  # Keep the established positive and legacy record bindings.
    if sub == 1:
        return [["菌株分析", "marker 共识分析", message, "尚不可作出菌株判断"]]
    if sub == 2:
        summary = _screening_summary(value)
        marker_text = "达标标记 0 项" if value.get("status") == "completed" else "暂无可判定标记"
        return [["VFDB 核心库筛查", marker_text, message, summary or message]]
    if sub == 4:
        if value.get("status") == "completed":
            return [["无达标毒力标记", "不适用", message]]
        return [["暂无可判定标记", "无法判定", message]]
    return None


def _has_host_links(value):
    from .template_body import _linked

    missing = _linked({}, "host")
    for row in value.get("markers", []):
        if not isinstance(row, dict):
            continue
        linked = _linked(row, "host")
        if linked[0] and linked[1] and linked[0] != missing[0] and linked[1] != missing[1]:
            return True
    return False


def interpretation(document, sub):
    module = "strains" if sub == 1 else "virulence"
    value, message = _state(document, module)
    if value is None:
        return None
    if sub in (1, 2):
        if message and sub == 2:
            summary = _screening_summary(value)
            return f"{summary}。{message}" if summary else message
        return message
    if sub in (3, 4):
        if message:
            return message + " 当前没有可用于致病型判断或微生物宿主归属的序列连接证据。"
        if not _has_host_links(value):
            return ("毒力筛查已完成；标记检出与微生物宿主归属分别报告。"
                    "尚缺少菌种与标记的序列连接证据，无法判定致病型或宿主。")
    return None


def paragraph_override(document, block):
    text = block.get("text", "")
    sub = block.get("sub")
    if sub == 3 and text.startswith("重点致病型"):
        return interpretation(document, sub)
    if text.startswith(("结果解读", "结果说明")):
        message = interpretation(document, sub)
        if message:
            return "结果解读：" + message
    return None


def figure_note(document):
    value, message = _state(document, "virulence")
    if value is None or not message and _has_host_links(value):
        return None
    return "图 4-1 暂无法绘制：尚无菌种与毒力标记之间的序列连接证据。"
