"""Auditable, subject-level healthy stool cohorts; no network or pipeline execution."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from bisect import bisect_left, bisect_right

from wgs_fmt_platform.paths import runtime_path

from .inputs import diversity_metrics, finite

VERSION = "healthy-reference-v1"
METRICS = (
    ("richness", "检出丰富度"),
    ("shannon", "Shannon 指数"),
    ("simpson", "Simpson 指数（1−D）"),
    ("evenness", "Pielou 均匀度"),
)
REASONS = {
    "healthy_reference_not_installed": "尚未安装带元数据和分析版本的健康人群参考库",
    "healthy_reference_unreadable": "健康参考库文件缺失、不可读或格式错误",
    "invalid_healthy_manifest": "健康参考库清单不完整或不符合数据契约",
    "invalid_healthy_metadata": "健康参考库缺少必要标签或样本编号重复",
    "invalid_healthy_matrix": "健康参考物种矩阵列名或样本编号无效",
    "incomplete_target_profile": "待测样本缺少完整有效的物种谱",
    "unknown_target_pipeline": "待测样本未记录物种分析软件或数据库版本",
    "incompatible_target_pipeline": "待测样本与健康参考库的分析软件或数据库版本不一致",
    "missing_matching_metadata": "待测样本缺少参考库要求的人口学匹配信息",
    "insufficient_healthy_subjects": "筛选、去重并排除待测个体后的健康参考人数不足",
}


def quantile(ordered: list[float], probability: float) -> float:
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[min(lower + 1, len(ordered) - 1)] * weight


def percentile(ordered: list[float], value: float) -> float:
    """Midrank empirical percentile, including zeros and ties (not interpolation)."""
    return 50 * (bisect_left(ordered, value) + bisect_right(ordered, value)) / len(ordered)


def distribution(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "p5": quantile(ordered, 0.05),
        "p95": quantile(ordered, 0.95),
        "reference_median": quantile(ordered, 0.5),
        "n_reference": len(ordered),
        "_distribution": ordered,
    }


def _table(raw: bytes) -> tuple[list[str], list[dict]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter="\t")
    columns = reader.fieldnames or []
    if len(columns) != len(set(columns)):
        raise ValueError("duplicate columns")
    return columns, list(reader)


def _present(value: object) -> bool:
    return str(value or "").strip().casefold() not in {"", "na", "nan", "none", "unknown"}


def _token(value: object) -> str:
    return str(value or "").strip().casefold()


def _sex(value: object) -> str:
    token = _token(value)
    return {"m": "male", "男": "male", "f": "female", "女": "female"}.get(token, token)


def _profile(rows: list[dict], unit: str) -> dict[str, float]:
    from .reference import species_key

    if unit not in {"%", "percent", "percentage", "fraction", "proportion"}:
        return {}
    factor = 100 if unit in {"fraction", "proportion"} else 1
    result = {}
    for row in rows:
        key = species_key(row.get("species", row.get("name")))
        value = finite(row.get("abundance", row.get("value")))
        row_unit = row.get("unit", unit)
        if (not key or key in result or value is None or not 0 <= value * factor <= 100
                or row_unit != unit):
            return {}
        result[key] = value * factor
    if not result or not 99 <= math.fsum(result.values()) <= 101:
        return {}
    return result


def load_healthy_reference(
    sample_id: str, rows: list[dict], taxonomy: dict, metadata: dict, *, complete: bool
) -> tuple[dict, list[dict], dict]:
    """Read the configured bundle. Explicit configuration never falls back to another cohort."""
    base = runtime_path("WGS_HEALTHY_REFERENCE_DIR", "reference", "healthy")
    configured = bool(os.environ.get("WGS_HEALTHY_REFERENCE_DIR", "").strip())
    try:
        configured = configured or base.exists()
    except OSError:
        configured = True  # An inaccessible installed cohort must not select another population.
    audit = {
        "status": "unavailable", "configured": configured, "file": str(base),
        "scope": "healthy_subject_cohort", "generated_by": VERSION,
    }

    def unavailable(reason: str) -> tuple[dict, list[dict], dict]:
        return {}, [], {**audit, "reason": reason, "reason_cn": REASONS[reason]}

    if not configured:
        return unavailable("healthy_reference_not_installed")
    try:
        names = ("manifest.json", "metadata.tsv", "species_abundance.tsv")
        raw = {name: (base / name).read_bytes() for name in names}
        audit["file_sha256"] = {n: hashlib.sha256(v).hexdigest() for n, v in raw.items()}
        manifest = json.loads(raw["manifest.json"])
        if not isinstance(manifest, dict):
            return unavailable("invalid_healthy_manifest")
        pipeline = manifest.get("pipeline")
        matching = manifest.get("stratify_by", [])
        minimum = manifest.get("minimum_subjects", 30)
        window = finite(manifest.get("age_window_years", 10))
        if (
            manifest.get("schema_version") != VERSION
            or manifest.get("body_site") != "stool"
            or manifest.get("unit") != "%"
            or manifest.get("complete_species_profiles") is not True
            or not all(_present(manifest.get(k)) for k in (
                "cohort_id", "cohort_version", "source_url", "inclusion_criteria"
            ))
            or not isinstance(pipeline, dict)
            or not all(_present(pipeline.get(k)) for k in (
                "profiler", "profiler_version", "database_version"
            ))
            or not isinstance(matching, list)
            or any(k not in {"sex", "country", "age"} for k in matching)
            or len(matching) != len(set(matching))
            or type(minimum) is not int or minimum < 30
            or window is None or window < 0
        ):
            return unavailable("invalid_healthy_manifest")
        audit.update({k: manifest[k] for k in (
            "cohort_id", "cohort_version", "source_url", "inclusion_criteria"
        )})
        audit.update(pipeline=pipeline, minimum_subjects=minimum, stratify_by=matching)
        target = _profile(rows, taxonomy.get("unit", "%")) if complete else {}
        if not target:
            return unavailable("incomplete_target_profile")
        observed_pipeline = taxonomy.get("pipeline") or metadata.get("taxonomy_pipeline") or {}
        if not isinstance(observed_pipeline, dict) or not all(
            _present(observed_pipeline.get(k)) for k in pipeline
        ):
            return unavailable("unknown_target_pipeline")
        if any(str(observed_pipeline.get(k)).strip() != str(v).strip() for k, v in pipeline.items()):
            return unavailable("incompatible_target_pipeline")
        columns, labels = _table(raw["metadata.tsv"])
        required = {"sample_id", "subject_id", "study_id", "health_status", "qc_pass", "body_site"}
        ids = [str(r.get("sample_id") or "").strip() for r in labels]
        if not required.issubset(columns) or not all(ids) or len(ids) != len(set(ids)):
            return unavailable("invalid_healthy_metadata")
        labels = {r["sample_id"].strip(): r for r in labels}
        identity_fields = ("sample_id", "study_id", "subject_id", "age", "sex", "country")
        target_label = {
            k: metadata.get(k) if _present(metadata.get(k)) else labels.get(sample_id, {}).get(k)
            for k in identity_fields
        }
        if any(not _present(target_label.get(k)) for k in matching) or (
            "age" in matching and (finite(target_label.get("age")) is None
                                   or float(target_label["age"]) < 0)
        ):
            return unavailable("missing_matching_metadata")
        from .reference import species_key

        matrix = csv.DictReader(
            io.StringIO(raw["species_abundance.tsv"].decode("utf-8-sig")), delimiter="\t"
        )
        columns = matrix.fieldnames or []
        features = [species_key(c) for c in columns[1:]]
        if (
            not columns or columns[0] != "sample_id" or not features or not all(features)
            or len(features) != len(set(features))
        ):
            return unavailable("invalid_healthy_matrix")
        candidates, seen = {}, set()
        exclusions = {k: 0 for k in ("labels", "self", "matching", "invalid_profile", "repeat_subject")}
        for row in matrix:
            sid = str(row.get("sample_id") or "").strip()
            if not sid or sid in seen:
                return unavailable("invalid_healthy_matrix")
            seen.add(sid)
            label = labels.get(sid, {})
            if (
                _token(label.get("health_status")) != "healthy"
                or _token(label.get("qc_pass")) not in {"true", "1", "pass"}
                or _token(label.get("body_site")) != "stool"
                or not all(_present(label.get(k)) for k in ("subject_id", "study_id"))
            ):
                exclusions["labels"] += 1
                continue
            subject = (label["study_id"].strip(), label["subject_id"].strip())
            same_person = (
                _present(target_label.get("subject_id"))
                and subject[1] == str(target_label["subject_id"]).strip()
                and (not _present(target_label.get("study_id"))
                     or subject[0] == str(target_label["study_id"]).strip())
            )
            if sid == sample_id or same_person:
                exclusions["self"] += 1
                continue
            matches = True
            for key in matching:
                if key == "age":
                    age = finite(label.get("age"))
                    matches &= age is not None and age >= 0 and abs(age - float(target_label["age"])) <= window
                else:
                    normalise = _sex if key == "sex" else _token
                    matches &= _present(label.get(key)) and normalise(label[key]) == normalise(target_label[key])
            if not matches:
                exclusions["matching"] += 1
                continue
            values = [finite(row.get(c)) for c in columns[1:]]
            if (None in row or any(v is None or not 0 <= v <= 100 for v in values)
                    or not 99 <= math.fsum(values) <= 101):
                exclusions["invalid_profile"] += 1
                continue
            if subject in candidates:
                exclusions["repeat_subject"] += 1
                if sid >= candidates[subject][0]:
                    continue
            candidates[subject] = (sid, values)
        selected = sorted(candidates.values())
        n_subjects = len(candidates)
        audit.update(n_reference=n_subjects, n_subjects=n_subjects, exclusions=exclusions,
                     n_profiles_input=len(seen))
        if len(selected) < minimum:
            return unavailable("insufficient_healthy_subjects")
        selection = json.dumps({"ids": [s for s, _ in selected], "target": target_label,
                                "files": audit["file_sha256"]}, sort_keys=True, default=str)
        version = "sha256:" + hashlib.sha256(selection.encode()).hexdigest()
        population = str(manifest["cohort_id"]) + "（健康人群）"
        common = {"reference_version": version, "reference_population": population,
                  "generated_by": VERSION, "n_subjects": n_subjects}
        entries = {}
        for index, feature in enumerate(features):
            values = [v[index] for _, v in selected]
            entries[feature] = {
                **distribution(values), **common,
                "reference_taxon": columns[index + 1],
                "n_detected": sum(v > 0 for v in values),
                "detection_rate": sum(v > 0 for v in values) / len(values),
            }
        observed = diversity_metrics([{"abundance": v} for v in target.values()], complete=True)
        diversity = {key: [] for key, _ in METRICS}
        for _, values in selected:
            metrics = diversity_metrics([{"abundance": v} for v in values], complete=True)
            for key in diversity:
                if metrics.get(key) is not None:
                    diversity[key].append(metrics[key])
        comparisons = []
        for key, title in METRICS:
            value = observed.get(key)
            if value is None or len(diversity[key]) < minimum:
                continue
            summary = distribution(diversity[key])
            ordered = summary.pop("_distribution")
            p5, p95 = summary["p5"], summary["p95"]
            status = ("unknown" if p5 == p95 else "low" if value < p5
                      else "high" if value > p95 else "normal")
            comparisons.append({
                **summary, **common, "metric": key, "name": title + "（健康人群对照）",
                "value": value, "unit": "种" if key == "richness" else "无量纲",
                "percentile": percentile(ordered, value), "status": status,
                "comparison_reason": "zero_width_reference_interval" if p5 == p95 else "compared",
                "method": observed["definition"],
            })
        limitations = ["P5–P95 为该队列的描述分布，经验百分位不代表疾病概率。"]
        if not matching:
            limitations.append("本次使用健康队列总体，未按年龄、性别或地区匹配。")
        if not _present(target_label.get("subject_id")):
            limitations.append("已排除同名待测样本，待测者未提供个体标识，无法核验其他编号是否属于同一个体。")
        audit.update(status="available", version=version, source=population, limitations=limitations,
                     percentile_method="midrank empirical CDF; zeros included",
                     quantile_method="linear interpolation at (n-1)*p")
        return entries, comparisons, audit
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, csv.Error):
        return unavailable("healthy_reference_unreadable")
