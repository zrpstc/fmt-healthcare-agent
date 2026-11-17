"""Refresh only cMD comparisons; historical population estimates are discarded."""
from __future__ import annotations
import copy
import logging
import os
from .population_reference import species_key

VERSION = "reference-comparison-v2"
logger = logging.getLogger(__name__)
STATUS_LABELS = {"high": "高于参考", "low": "低于参考", "normal": "参考区间内",
                 "not_detected": "未检出", "borderline": "边界不确定", "unknown": "未建立健康对照"}
_OLD_GENERATORS = {"reference-comparison-v1", "healthy-reference-v1", "mhomic-reference-v1"}
_COMPARISON_FIELDS = {
    "p5", "p95", "p5_ci95", "p95_ci95", "percentile", "percentile_ci95", "deviation",
    "mean_health", "n_health", "n_reference", "n_detected", "n_subjects", "reference_median",
    "reference_detected_median", "detection_rate", "reference_population", "reference_version",
    "generated_by", "reference_taxon", "comparison_reason", "comparison_reason_cn", "status_cn",
    "_distribution", "borderline", "uncertainty_status", "bootstrap_iterations", "bootstrap_seed",
}


def _clear_historical(data):
    # Keep primary abundances; old thresholds cannot describe an independent spectrum.
    for name in ("species", "compare"):
        section = data.get(name)
        if not isinstance(section, dict):
            continue
        for field in ("species_list", "comparison", "abnormal_species"):
            for row in section.get(field, []) or []:
                if not isinstance(row, dict):
                    continue
                if (any(k in row for k in ("p5", "p95", "percentile")) or row.get("generated_by") in _OLD_GENERATORS
                        or row.get("status") in {"high", "low", "normal", "absent"}):
                    for key in _COMPARISON_FIELDS:
                        row.pop(key, None)
                    row.update(status="unknown", status_cn="未建立健康对照", comparison_reason="independent_cmd_profile_required")
        if "abnormal_species" in section:
            section["abnormal_species"] = []
        for key in ("n_high", "n_low", "n_normal", "n_absent", "n_not_detected", "n_borderline", "n_abnormal"):
            if key in section:
                section[key] = 0
        if "n_unknown" in section:
            rows = section.get("species_list") or section.get("comparison") or []
            section["n_unknown"] = sum(isinstance(row, dict) and row.get("status") == "unknown" for row in rows)
        section.pop("reference", None)
    diversity = data.get("diversity")
    if isinstance(diversity, dict):
        diversity["reference_comparisons"] = []
    data.pop("healthy_comparison", None)
    data.pop("cohort_insights", None)


def cohort_insights_for(sample_id: str, metadata: dict) -> dict:
    """Gut age, enterotype, health index and disease references; never raises."""
    from . import cohort_insights
    try:
        return cohort_insights.analyze(sample_id, metadata)
    except Exception:  # noqa: BLE001 - an optional module must not block the report
        logger.exception("cohort insights failed")
        return {"audit": {"status": "unavailable", "reason": "invalid_bundle",
                          "reason_cn": cohort_insights.REASONS["invalid_bundle"]}}


def refresh_reference_comparisons(data: dict, inputs: dict) -> dict:
    """Read local cMD artifacts; never mutate input, execute profiling or fall back."""
    from . import cmd
    result = copy.deepcopy(data)
    _clear_historical(result)
    metadata = result.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("分析元数据必须是JSON对象")
    provider = os.environ.get("WGS_HEALTHY_REFERENCE_PROVIDER", "").strip().lower()
    if provider not in {"", "cmd"}:
        logger.warning("Unsupported healthy reference provider; only cmd is supported")
        comparison = {"audit": {"provider": "cmd", "status": "unavailable", "configured": True,
            "reason": "unsupported_provider", "reason_cn": cmd.REASONS["unsupported_provider"],
            "display_status": "未建立健康对照"}, "species": [], "diversity": []}
    else:
        comparison = cmd.compare(str(result.get("sample_id", "")), metadata)
    result["healthy_comparison"] = comparison
    result["cohort_insights"] = cohort_insights_for(str(result.get("sample_id", "")), metadata)
    metadata["reference_comparison"] = {"version": VERSION, "healthy_population": comparison["audit"]}
    metadata["reference_version"] = comparison["audit"].get("version")
    return result
