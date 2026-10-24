"""Refresh descriptive reference comparisons from existing local resources only."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import math
import os

from wgs_fmt_platform.paths import runtime_path, species_reference_path

from .inputs import diversity_metrics, finite

VERSION = "reference-comparison-v1"
STATUS_LABELS = {
    "high": "高于参考",
    "low": "低于参考",
    "normal": "参考区间内",
    "absent": "未检出",
    "unknown": "未建立参考比较",
}


def species_key(value: object) -> str:
    name = str(value or "").strip()
    for part in name.split("|"):
        if part.startswith("s__"):
            name = part[3:]
            break
    return name.replace("_", " ").casefold().strip()


def _integer(value: object) -> int | None:
    number = finite(value)
    return int(number) if number is not None and number >= 0 and number.is_integer() else None


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_species_reference() -> tuple[dict, dict]:
    path = species_reference_path()
    audit = {"status": "unavailable", "file": str(path), "unit": "%"}
    try:
        raw = path.read_bytes()
        reader = csv.DictReader(
            io.StringIO(raw.decode("utf-8-sig")),
            delimiter="\t" if path.suffix.lower() in {".tsv", ".txt"} else ",",
        )
        if not {"species", "p5", "p95"}.issubset(reader.fieldnames or []):
            return {}, {**audit, "reason": "invalid_reference_columns"}
        entries, duplicates, invalid = {}, set(), 0
        for row in reader:
            key = species_key(row.get("species"))
            p5, p95 = finite(row.get("p5")), finite(row.get("p95"))
            if (
                not key
                or p5 is None
                or p95 is None
                or not 0 <= p5 <= p95 <= 100
                or row.get("unit", "%") not in {"%", "percent", "percentage"}
            ):
                invalid += 1
                continue
            if key in entries or key in duplicates:
                entries.pop(key, None)
                duplicates.add(key)
                continue
            median = finite(row.get("median", row.get("p50")))
            entries[key] = {
                "p5": p5,
                "p95": p95,
                "reference_median": median if median is not None and p5 <= median <= p95 else None,
                "n_reference": _integer(row.get("n_samples")),
                "n_detected": _integer(row.get("n_detected", row.get("cond_n"))),
                "detection_rate": finite(row.get("detection_rate")),
                "reference_population": row.get("stratum") or "overall",
            }
        return entries, {
            **audit,
            "status": "available" if entries else "unavailable",
            "version": "sha256:" + _digest(raw),
            "species_count": len(entries),
            "usable_interval_count": sum(r["p95"] > r["p5"] for r in entries.values()),
            "invalid_rows": invalid,
            "duplicate_names": len(duplicates),
            "scope": "precomputed_population_distribution",
            "limitations": ["参考表的健康纳入标准、独立人数和分析数据库版本尚待核验。"],
        }
    except FileNotFoundError:
        return {}, {**audit, "reason": "reference_file_missing"}
    except (OSError, UnicodeError, csv.Error):
        return {}, {**audit, "reason": "reference_file_unreadable"}


def _compare(row: dict, ref: dict | None, parent: dict, version: str) -> dict:
    result = dict(row)
    # Remove stale comparison fields when a newer reference cannot cover a taxon.
    for field in (
        "p5",
        "p95",
        "deviation",
        "mean_health",
        "n_health",
        "n_reference",
        "n_detected",
        "reference_median",
        "detection_rate",
        "reference_population",
        "percentile",
        "generated_by",
        "n_subjects",
        "reference_taxon",
        "comparison_reason_cn",
    ):
        result.pop(field, None)
    result.update(status="unknown", status_cn=STATUS_LABELS["unknown"], reference_version=version)
    value = finite(row.get("abundance", row.get("value")))
    unit = row.get("unit") or parent.get("unit") or "%"
    result["unit"] = unit
    if value is None or value < 0:
        result["comparison_reason"] = "invalid_observation"
        return result
    if unit in {"%", "percent", "percentage"}:
        scale = 1
    elif unit in {"fraction", "proportion"}:
        scale = 0.01
    else:
        result["comparison_reason"] = "incompatible_unit"
        return result
    if value > 100 * scale:
        result["comparison_reason"] = "invalid_observation"
        return result
    if ref is None:
        result["comparison_reason"] = "species_not_in_reference"
        return result
    result.update({key: value for key, value in ref.items() if key != "_distribution"})
    if ref.get("_distribution"):
        from .healthy import percentile

        result["percentile"] = percentile(ref["_distribution"], value / scale)
    result["p5"], result["p95"] = ref["p5"] * scale, ref["p95"] * scale
    if ref.get("reference_median") is not None:
        result["reference_median"] = ref["reference_median"] * scale
    if ref["p95"] <= ref["p5"]:
        result["comparison_reason"] = "zero_width_reference_interval"
        return result
    status = (
        "absent"
        if value == 0
        else "low"
        if value < result["p5"]
        else "high"
        if value > result["p95"]
        else "normal"
    )
    result.update(status=status, status_cn=STATUS_LABELS[status], comparison_reason="compared")
    return result


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    fraction = position - lower
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * fraction


def _diversity_reference(sample_id: str, observed: dict) -> tuple[list[dict], dict]:
    """The labelled donor subset is exploratory, never a matched clinical cohort."""
    explicit = os.environ.get("WGS_FMT_MATCHING_DIR", "").strip()
    base = runtime_path("WGS_FMT_MATCHING_DIR", "data", "fmt-matching")
    matrix, metadata = base / "species_abundance_train.csv", base / "match.xlsx"
    audit = {"status": "unavailable", "reason": "healthy_donor_data_missing"}
    if not matrix.is_file() or not metadata.is_file():
        return [], audit
    try:
        import pandas as pd

        matrix_raw, metadata_raw = matrix.read_bytes(), metadata.read_bytes()
        labels = pd.read_excel(io.BytesIO(metadata_raw))
        if not {"sample_id", "group", "disease"}.issubset(labels.columns):
            return [], {**audit, "reason": "invalid_healthy_donor_labels"}
        labels["sample_id"] = labels["sample_id"].astype(str).str.strip()
        if labels["sample_id"].duplicated().any():
            return [], {**audit, "reason": "duplicate_sample_labels"}
        healthy = labels[
            labels["group"].astype(str).str.casefold().eq("donor")
            & labels["disease"].astype(str).str.casefold().eq("healthy")
        ]
        # Exclude the target sample; independent people cannot be established
        # when the historical metadata lacks subject_id.
        eligible = set(healthy["sample_id"]) - {sample_id}
        subject_map = (
            healthy.set_index("sample_id")["subject_id"].to_dict()
            if "subject_id" in healthy
            else {}
        )
        current_subject = (
            labels.loc[labels["sample_id"].eq(sample_id), "subject_id"] if subject_map else []
        )
        if len(current_subject) and pd.notna(current_subject.iloc[0]):
            eligible -= {
                sid for sid, person in subject_map.items() if person == current_subject.iloc[0]
            }
        distributions = {name: [] for name in ("richness", "shannon", "simpson", "evenness")}
        subjects, seen, valid = set(), set(), 0
        reader = csv.reader(io.StringIO(matrix_raw.decode("utf-8-sig")))
        header = next(reader)
        if len(set(header[1:])) != len(header[1:]) or len(header) < 2:
            return [], {**audit, "reason": "invalid_donor_matrix_columns"}
        for row in reader:
            if not row or row[0].strip() not in eligible:
                continue
            sid = row[0].strip()
            if sid in seen:
                return [], {**audit, "reason": "duplicate_donor_profiles"}
            seen.add(sid)
            person = subject_map.get(sid)
            if pd.notna(person) and person in subjects:
                continue
            values = [finite(value) for value in row[1:]]
            if len(row) != len(header) or any(v is None or v < 0 for v in values):
                continue
            total = math.fsum(values)
            if not 99 <= total <= 101:
                continue  # The installed training-matrix contract uses percent.
            metrics = diversity_metrics([{"abundance": v} for v in values], complete=True)
            if not metrics:
                continue
            valid += 1
            if pd.notna(person):
                subjects.add(person)
            for name in distributions:
                value = finite(metrics.get(name))
                if value is not None:
                    distributions[name].append(value)
        if valid < 30:
            return [], {
                **audit,
                "reason": "insufficient_healthy_donor_profiles",
                "n_reference": valid,
            }
        version = "sha256:" + _digest(matrix_raw + metadata_raw + sample_id.encode())
        results = []
        for name, title in (
            ("richness", "检出丰富度"),
            ("shannon", "Shannon 指数"),
            ("simpson", "Simpson 指数（1−D）"),
            ("evenness", "Pielou 均匀度"),
        ):
            value, reference = finite(observed.get(name)), distributions[name]
            if value is None or len(reference) < 30:
                continue
            p5, p95 = _quantile(reference, 0.05), _quantile(reference, 0.95)
            results.append(
                {
                    "name": title + "（健康供体子集对照）",
                    "metric": name,
                    "value": value,
                    "unit": "种" if name == "richness" else "无量纲",
                    "p5": p5,
                    "p95": p95,
                    "reference_median": _quantile(reference, 0.5),
                    "n_reference": len(reference),
                    "reference_version": version,
                    "reference_population": "标注健康供体研究子集（探索性）",
                    "percentile": 100
                    * (sum(v < value for v in reference) + 0.5 * sum(v == value for v in reference))
                    / len(reference),
                    "status": "unknown"
                    if p95 <= p5
                    else "low"
                    if value < p5
                    else "high"
                    if value > p95
                    else "normal",
                    "comparison_reason": "zero_width_reference_interval"
                    if p95 <= p5
                    else "compared",
                    "method": observed["definition"],
                    "generated_by": VERSION,
                }
            )
        return results, {
            "status": "available",
            "version": version,
            "n_reference": valid,
            "scope": "exploratory_healthy_donor_subset",
            "configured_path": bool(explicit),
            "limitations": [
                "该供体子集未按待测者年龄、地区或性别匹配，分析数据库和完整特征口径尚待核验。",
                "历史标注缺少完整个体信息，样本数不等同于已核验的独立健康人数。",
            ],
        }
    except (OSError, ValueError, ImportError, csv.Error, StopIteration):
        return [], {**audit, "reason": "healthy_donor_data_unreadable"}


def refresh_reference_comparisons(data: dict, inputs: dict) -> dict:
    """Return enriched input; never mutate data or write files during preparation."""
    result = copy.deepcopy(data)
    species = result.get("species") if isinstance(result.get("species"), dict) else {}
    taxonomy = inputs.get("taxonomy") or {}
    full = taxonomy.get("ranks", {}).get("species", []) if taxonomy.get("complete") is True else []
    compare = result.get("compare") if isinstance(result.get("compare"), dict) else {}
    rows = species.get("species_list") or compare.get("comparison") or []
    if full:
        prior = {
            species_key(r.get("species", r.get("name"))): r for r in rows if isinstance(r, dict)
        }
        rows = [
            {**prior.get(species_key(r.get("name")), {}), **r, "species": r["name"]}
            for r in full
            if isinstance(r, dict) and r.get("name")
        ]
    if not full and species.get("is_complete_profile") is True and taxonomy.get("complete") is not False:
        full = rows
    from .healthy import VERSION as HEALTHY_VERSION, load_healthy_reference

    healthy_entries, healthy_diversity, healthy_audit = load_healthy_reference(
        str(data.get("sample_id", "")), full, {"unit": species.get("unit", "%"), **taxonomy},
        data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
        complete=bool(full),
    )
    strict = healthy_audit["configured"]
    if strict:
        entries, audit = healthy_entries, dict(healthy_audit)
        if entries and full:
            # Absence is a measured zero only for a complete, compatible profile.
            # Include cohort taxa absent from the sample so depletion is visible.
            present = {species_key(r.get("species", r.get("name"))) for r in rows}
            rows = [*rows, *(
                {"species": entries[key]["reference_taxon"], "abundance": 0,
                 "unit": taxonomy.get("unit", species.get("unit", "%"))}
                for key in sorted(entries.keys() - present)
            )]
    else:
        entries, audit = load_species_reference()
    workflow = {"version": VERSION, "species": audit, "healthy_population": healthy_audit}
    if entries or strict:
        compared = [
            _compare(
                r,
                entries.get(species_key(r.get("species", r.get("name")))),
                species,
                audit.get("version", HEALTHY_VERSION),
            )
            for r in rows
            if isinstance(r, dict)
        ]
        if strict and not entries:
            for row in compared:
                row.update(comparison_reason=audit["reason"], comparison_reason_cn=audit["reason_cn"])
        counts = {
            f"n_{status}": sum(r["status"] == status for r in compared) for status in STATUS_LABELS
        }
        species.update(counts, species_list=compared, n_total=len(compared))
        if full:
            species["is_complete_profile"] = True
        species["abnormal_species"] = [r for r in compared if r["status"] in {"high", "low"}]
        result["species"] = species
        result["compare"] = {
            "sample_id": result.get("sample_id"),
            "comparison": compared,
            "abnormal_species": species["abnormal_species"],
            "total_species": len(compared),
            "n_abnormal": counts["n_high"] + counts["n_low"],
            "reference": audit,
        }
        audit.update(
            compared_count=len(compared) - counts["n_unknown"], uncovered_count=counts["n_unknown"]
        )
    # Compute both sample and reference metrics with this implementation. Never
    # compare an arbitrary upstream index with an unspecified logarithm/definition.
    observed = diversity_metrics(full, complete=bool(full))
    if observed or strict:
        if strict:
            comparisons, diversity_audit = healthy_diversity, dict(healthy_audit)
        else:
            comparisons, diversity_audit = _diversity_reference(
                str(data.get("sample_id", "")), observed
            )
        workflow["diversity"] = diversity_audit
        diversity = copy.deepcopy(inputs.get("diversity") or {})
        diversity.update(observed)
        retained = [
            r
            for r in diversity.get("reference_comparisons", [])
            if r.get("generated_by") not in {VERSION, HEALTHY_VERSION}
        ]
        diversity["reference_comparisons"] = retained + comparisons
        result["diversity"] = diversity
    metadata = result.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("分析元数据必须是 JSON 对象")
    metadata["reference_comparison"] = workflow
    metadata["reference_version"] = audit.get("version")
    return result
