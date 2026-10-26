"""Select a small, traceable reading priority from results, never chapter coverage."""

from __future__ import annotations

from .inputs import finite
from .template_catalog import TOPIC_PLACEMENT

RULE_VERSION = "health-priority-findings-v1"
MAX_FINDINGS = 5


def detected(row: dict) -> bool:
    """Unknown, unassessed and explicitly negative results cannot become alerts."""
    values = [row.get(k) for k in ("detected", "detection_status", "result", "status")]
    negative = {
        "not_detected",
        "not detected",
        "negative",
        "absent",
        "未检出",
        "本次未检出",
        "阴性",
        "未评估",
        "无法判断",
        "unknown",
        "insufficient_coverage",
        "覆盖不足无法判断",
    }
    if any(v is False or (isinstance(v, str) and v.strip().lower() in negative) for v in values):
        return False
    positive = {"detected", "positive", "present", "检出", "已检出", "阳性"}
    if any(v is True or (isinstance(v, str) and v.strip().lower() in positive) for v in values):
        return True
    # Numerical abundance is detection evidence only within a dedicated assay.
    value = finite(row.get("value"))
    return row.get("kind") in {"amr", "pathogen", "virulence"} and value is not None and value > 0


def select_findings(document: dict, limit: int = MAX_FINDINGS) -> list[dict]:
    if limit <= 0:
        return []
    if str(document.get("metadata", {}).get("qc_status", "")).lower() in {
        "failed",
        "fail",
        "不通过",
        "未通过",
    }:
        return []
    evidence = document["evidence"]
    placements: dict[str, list[str]] = {}
    for section in document["sections"]:
        for topic in section["topics"]:
            if topic["status"] != "missing":
                for key in topic["evidence_ids"]:
                    placements.setdefault(key, []).append(topic["id"])
    candidates = []
    for key, row in evidence.items():
        kind = row.get("kind")
        if (
            kind in {"literature", "method_reference"}
            or row.get("measurement_type") == "unverified"
        ):
            continue
        topics = placements.get(key, [])
        source = TOPIC_PLACEMENT.get(topics[-1], "") if topics else ""
        rank, reason, priority, deviation = None, "", "重点关注", 0.0
        if kind in {"pathogen", "virulence", "amr"} and detected(row):
            rank = {"pathogen": 0, "virulence": 0, "amr": 1}[kind]
            source = {"pathogen": "3.3", "virulence": "4.2", "amr": "5.1"}[kind]
            priority = "优先复核"
            reason = {
                "pathogen": "专项检测有检出记录，需结合序列支持和菌株信息解释，不等同于感染。",
                "virulence": "存在毒力相关标记记录，需核对完整性及宿主连接证据，不代表已表达或产毒。",
                "amr": "存在耐药决定因素记录，需核对注释和遗传背景，不等同于药敏结果。",
            }[kind]
        elif row.get("comparison") in {"above", "below"}:
            if kind in {"disease", "prediction", "symptom", "diet", "nutrition"}:
                continue  # No heuristic association score or questionnaire value is a health threshold.
            value, p5, p95 = (finite(row.get(k)) for k in ("value", "p5", "p95"))
            if None in (value, p5, p95) or p95 <= p5 or value < 0:
                continue
            focused = any(t.startswith("key_taxa.") for t in topics)
            rank = 2 if row.get("measurement_type") == "measured" else 3 if focused else 4
            source = "1.4" if kind in {"species", "healthy_species"} else source or "2.1"
            deviation = (value - p95 if value > p95 else p5 - value) / (p95 - p5)
            reason = "偏离所用参考人群区间；健康含义需结合具体项目、参考人群适用性及背景解释。"
        if rank is None:
            continue
        direction = {"above": "，高于所用参考区间", "below": "，低于所用参考区间"}.get(
            row.get("comparison"), ""
        )
        candidates.append(
            {
                "evidence_id": key,
                "priority": priority,
                "finding": f"{row['label']}：{row['result_text']}{direction}。",
                "reason": reason,
                "source": source,
                "evidence_type": row.get("measurement_type"),
                "_rank": rank,
                "_deviation": deviation,
                "_identity": (
                    kind,
                    str(row.get("species") or row.get("gene") or row["label"]).casefold(),
                ),
            }
        )
    candidates.sort(key=lambda r: (r["_rank"], -r["_deviation"], r["evidence_id"]))
    selected, seen = [], set()
    for row in candidates:
        if row["_identity"] in seen:
            continue
        seen.add(row["_identity"])
        selected.append({k: v for k, v in row.items() if not k.startswith("_")})
        if len(selected) >= max(0, min(limit, MAX_FINDINGS)):
            break
    return selected
