"""Strict offline, subject-level population comparisons, independent of a provider."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, OrderedDict
from collections.abc import Mapping
import copy
import csv
from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import re
from threading import RLock
from types import MappingProxyType
from typing import Callable

import numpy as np

from .inputs import diversity_metrics, finite

METRICS = (("richness", "检出丰富度"), ("shannon", "Shannon 指数"),
           ("simpson", "Simpson 指数（1−D）"), ("evenness", "Pielou 均匀度"))
BOOTSTRAP_SEED = 20261114
BOOTSTRAP_ITERATIONS = 1000
DEFAULT_AGE_BANDS = (18, 30, 40, 50, 60, 70, 80)
REASONS = {
    "reference_missing": "健康参考文件尚未准备或不可读取",
    "invalid_reference": "参考格式、校验和或版本不符合约定",
    "target_missing": "尚未生成独立对照谱",
    "target_unreadable": "当前运行用户无权读取独立对照谱目录或文件",
    "invalid_target": "独立对照谱不完整、含无效数值或与运行记录不一致",
    "incompatible_pipeline": "独立对照谱的软件或数据库版本与参考不一致",
    "missing_matching_metadata": "缺少所配置的人口学匹配信息",
    "insufficient_subjects": "筛选及排除同一个体后，参考人数低于配置门槛（至少30人）",
    "target_qc_failed": "待测样本质控未通过，暂停健康人群比较",
    "unsupported_provider": "不支持的参考来源；仅支持 curatedMetagenomicData（cmd）",
}


@dataclass(frozen=True)
class ProviderSpec:
    """A new release (including a future cMD4) supplies its own exact contracts."""
    provider: str
    version: str
    pipeline: Mapping[str, str]
    target_pipeline: Mapping[str, str]
    normalization: str
    phenotype: str
    population: str
    scope: str
    method: str
    reference_dir: Callable[[], Path]
    profiles_dir: Callable[[], Path]
    minimum_subjects: int = 30
    limitations: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.minimum_subjects) is not int or self.minimum_subjects < 30:
            raise ValueError("minimum_subjects must be at least 30")
        object.__setattr__(self, "pipeline", MappingProxyType(dict(self.pipeline)))
        object.__setattr__(self, "target_pipeline", MappingProxyType(dict(self.target_pipeline)))
        object.__setattr__(self, "limitations", tuple(self.limitations))


class PopulationReferenceError(ValueError):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def species_key(value: object) -> str:
    name = str(value if value is not None else "").strip()
    for part in name.split("|"):
        if part.startswith("s__"):
            name = part[3:]
            break
    return name.replace("_", " ").casefold().strip()


def present(value: object) -> bool:
    return value is not None and str(value).strip().casefold() not in {
        "", "na", "n/a", "nan", "none", "null", "unknown", "not available"}


def token(value: object, field: str = "") -> str:
    text = str(value).strip().casefold() if present(value) else ""
    return {"f": "female", "m": "male", "女": "female", "男": "male"}.get(text, text) if field == "sex" else text


def quantile(values, probability, *, axis=None):
    """The single linear quantile implementation, including bootstrap CIs."""
    result = np.quantile(values, probability, axis=axis, method="linear")
    return float(result) if np.ndim(result) == 0 else result


def percentile(ordered, value: float) -> float:
    """Midrank empirical percentile; callers supply sorted observations."""
    if not len(ordered):
        raise ValueError("empty distribution")
    return 50 * (bisect_left(ordered, value) + bisect_right(ordered, value)) / len(ordered)


def distribution(values) -> dict:
    ordered = sorted(values)
    return {"p5": quantile(ordered, .05), "p95": quantile(ordered, .95),
            "reference_median": quantile(ordered, .5), "n_reference": len(ordered),
            "_distribution": ordered}


def _bootstrap_quantile(ordered, probability, rng, iterations):
    # Exact marginal empirical-bootstrap law, without allocating B x N x taxa.
    # Floor(n * U_(k)) is the kth resampled index for uniform order statistics.
    n = len(ordered)
    position = (n - 1) * probability
    lower = math.floor(position)
    weight = position - lower
    k = lower + 1
    u = rng.beta(k, n + 1 - k, size=iterations)
    left = np.minimum((n * u).astype(int), n - 1)
    if not weight:
        return ordered[left]
    following = u + (1 - u) * rng.beta(1, n - k, size=iterations)
    right = np.minimum((n * following).astype(int), n - 1)
    return ordered[left] * (1 - weight) + ordered[right] * weight


def comparison(value, values, *, seed=BOOTSTRAP_SEED, iterations=BOOTSTRAP_ITERATIONS) -> dict:
    ordered = np.sort(np.asarray(values, dtype=float))
    if len(ordered) < 30 or not np.isfinite(ordered).all() or not math.isfinite(value):
        raise ValueError("invalid comparison distribution")
    rng = np.random.default_rng(seed)
    summary = distribution(ordered.tolist())
    summary.pop("_distribution")
    for p, key in ((.05, "p5_ci95"), (.95, "p95_ci95")):
        draws = _bootstrap_quantile(ordered, p, rng, iterations)
        summary[key] = quantile(draws, [.025, .975]).tolist()
    n = len(ordered)
    less = bisect_left(ordered, value)
    equal = bisect_right(ordered, value) - less
    draws_less = rng.binomial(n, less / n, size=iterations)
    draws_equal = rng.binomial(n - draws_less, equal / (n - less), size=iterations) if less < n else np.zeros(iterations)
    summary["percentile"] = percentile(ordered, value)
    summary["percentile_ci95"] = quantile(100 * (draws_less + .5 * draws_equal) / n, [.025, .975]).tolist()
    borderline = any(lo <= value <= hi for lo, hi in (summary["p5_ci95"], summary["p95_ci95"]))
    not_detected = value == 0 and summary["p5"] > 0
    # Detection and uncertainty are separate: a measured zero remains not_detected,
    # and an overlapping boundary CI prevents counting it as a confirmed outlier.
    status = ("not_detected" if not_detected else "borderline" if borderline else
              "unknown" if summary["p5"] == summary["p95"] else
              "low" if value < summary["p5"] else "high" if value > summary["p95"] else "normal")
    return {**summary, "status": status, "borderline": borderline,
            "uncertainty_status": "borderline" if borderline else "resolved",
            "comparison_reason": "borderline" if borderline else "zero_width_reference_interval" if status == "unknown" else "compared",
            "bootstrap_iterations": iterations, "bootstrap_seed": seed}


def abnormal(row: dict) -> bool:
    return row.get("status") in {"high", "low", "not_detected"} and not row.get("borderline", False)


def valid_sample_id(sample_id: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+", sample_id)) and sample_id not in {".", ".."}


def normalize(profile: dict[str, float]) -> tuple[dict[str, float], float]:
    if not profile or any(not key or finite(value) is None or not 0 <= value <= 100 for key, value in profile.items()):
        raise PopulationReferenceError("invalid_target")
    total = math.fsum(profile.values())
    if not 0 < total <= 101:
        raise PopulationReferenceError("invalid_target")
    return {key: value * 100 / total for key, value in profile.items()}, total


def read_target(raw: bytes) -> tuple[dict[str, float], dict]:
    profile, pipeline = {}, {"profiler": "MetaPhlAn"}
    for line in raw.decode("utf-8-sig").splitlines():
        if line.startswith("#mpa_"):
            pipeline["database_version"] = line[1:].strip()
        match = re.match(r"#\s*MetaPhlAn(?: version)?\s+(\d+\.\d+\.\d+)", line, re.I)
        if match:
            pipeline["profiler_version"] = match[1]
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if not fields[0].rsplit("|", 1)[-1].startswith("s__"):
            continue
        key = species_key(fields[0])
        value = finite(fields[2]) if len(fields) > 2 else None
        if key in profile or value is None or not 0 <= value <= 100:
            raise PopulationReferenceError("invalid_target")
        profile[key] = value
    normalize(profile)
    return profile, pipeline


def profile_read_count(raw: bytes):
    for line in raw.decode("utf-8-sig").splitlines():
        if not line.startswith('#'):
            continue
        match = re.fullmatch(r'#\s*(\d+)\s+reads processed\s*', line, re.I)
        match = match or re.fullmatch(r'#\s*(?:number of )?reads processed\s*:\s*(\d+)\s*', line, re.I)
        if match and int(match[1]) > 0:
            return int(match[1])
    return None


def age_band(value, boundaries=DEFAULT_AGE_BANDS):
    age = finite(value)
    if age is None or age < boundaries[0]:
        return ""
    index = bisect_right(boundaries, age) - 1
    return f"{boundaries[index]:g}-<{boundaries[index+1]:g}" if index + 1 < len(boundaries) else f"{boundaries[index]:g}+"


def validate_stratification(fields, boundaries):
    if (not isinstance(fields, (list, tuple)) or len(fields) != len(set(fields))
            or any(key not in {"country", "sex", "age_band"} for key in fields)
            or not isinstance(boundaries, (list, tuple)) or len(boundaries) < 2
            or any(finite(v) is None for v in boundaries)
            or boundaries[0] != 18 or any(a >= b for a, b in zip(boundaries, boundaries[1:]))):
        raise PopulationReferenceError("invalid_reference")


def stratum(label, fields, boundaries):
    return tuple(age_band(label.get("age"), boundaries) if key == "age_band" else token(label.get(key), key) for key in fields)


def stratum_counts(labels, fields, boundaries):
    return {json.dumps(key, ensure_ascii=False): count for key, count in sorted(Counter(stratum(r, fields, boundaries) for r in labels).items())}


def depth_distribution(labels):
    result = {}
    for key in ("number_reads", "number_bases"):
        values = [finite(row.get(key)) for row in labels]
        values = [v for v in values if v is not None and v > 0]
        if values:
            summary = distribution(values)
            summary.pop("_distribution")
            result[key] = summary
    return result


class PopulationMatrix(Mapping):
    """Compact immutable matrix, with the mapping API needed by ordination."""
    def __init__(self, ids, features, values):
        self.ids = tuple(ids)
        self.features = tuple(features)
        self.indices = {sid: i for i, sid in enumerate(ids)}
        values.flags.writeable = False
        self.values_array = values

    def __getitem__(self, sid):
        return dict(zip(self.features, self.values_array[self.indices[sid]].tolist()))

    def __iter__(self):
        return iter(self.ids)

    def __len__(self):
        return len(self.ids)

    def selected(self, ids):
        return self.values_array[[self.indices[sid] for sid in ids]]


_CACHE = OrderedDict()
_CACHE_LOCK = RLock()


def clear_bundle_cache():
    with _CACHE_LOCK:
        _CACHE.clear()


def _table(raw):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter="\t")
    columns = reader.fieldnames or []
    if len(columns) != len(set(columns)):
        raise PopulationReferenceError("invalid_reference")
    return columns, list(reader)


def _parse_bundle(raw, hashes, spec):
    manifest = json.loads(raw["manifest.json"])
    if (not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict)
            or manifest.get("schema_version") != spec.version or manifest.get("pipeline") != dict(spec.pipeline)
            or manifest.get("normalization") != spec.normalization or manifest.get("unit") != "%"
            or manifest.get("phenotype") != spec.phenotype or manifest.get("body_site") != "stool"
            or manifest.get("complete_species_profiles") is not True or manifest.get("feature_level") != "species"
            or not all(present(manifest.get(k)) for k in ("cohort_id", "cohort_version", "source_url"))
            or any(manifest["files"].get(name) != hashes[name] for name in ("metadata.tsv", "species_abundance.tsv"))):
        raise PopulationReferenceError("invalid_reference")
    minimum = manifest.get("minimum_subjects", 30)
    fields = manifest.get("stratify_by", [])
    boundaries = manifest.get("age_band_boundaries", list(DEFAULT_AGE_BANDS))
    if type(minimum) is not int or minimum < spec.minimum_subjects:
        raise PopulationReferenceError("invalid_reference")
    validate_stratification(fields, boundaries)
    columns, labels = _table(raw["metadata.tsv"])
    required = {"sample_id", "subject_id", "study_id", "phenotype", "source_runs"}
    ids = [row.get("sample_id", "") for row in labels]
    if (not required.issubset(columns) or not ids or not all(ids) or len(set(ids)) != len(ids)
            or any(not all(present(row.get(k)) for k in ("subject_id", "study_id")) or row.get("phenotype") != spec.phenotype or None in row for row in labels)):
        raise PopulationReferenceError("invalid_reference")
    for label in labels:
        for key in ("sample_id", "subject_id", "study_id"):
            label[key] = str(label[key]).strip()
    ids = [row['sample_id'] for row in labels]
    if not all(ids) or len(set(ids)) != len(ids):
        raise PopulationReferenceError("invalid_reference")
    if len({(r["study_id"], r["subject_id"]) for r in labels}) != len(labels):
        raise PopulationReferenceError("invalid_reference")
    counts = stratum_counts(labels, fields, boundaries)
    if "stratum_subject_counts" in manifest and manifest["stratum_subject_counts"] != counts:
        raise PopulationReferenceError("invalid_reference")
    reader = csv.reader(io.StringIO(raw["species_abundance.tsv"].decode("utf-8-sig")), delimiter="\t")
    header = next(reader, [])
    features = [species_key(c) for c in header[1:]]
    if not header or header[0] != "sample_id" or not features or not all(features) or len(set(features)) != len(features):
        raise PopulationReferenceError("invalid_reference")
    positions = {sid: i for i, sid in enumerate(ids)}
    values = np.empty((len(ids), len(features)), dtype=np.float64)
    seen = set()
    for row in reader:
        if not row or len(row) != len(header) or row[0] not in positions or row[0] in seen:
            raise PopulationReferenceError("invalid_reference")
        vector = np.asarray(row[1:], dtype=np.float64)
        if not np.isfinite(vector).all() or (vector < 0).any() or (vector > 100).any() or not math.isclose(math.fsum(vector), 100, abs_tol=.0001):
            raise PopulationReferenceError("invalid_reference")
        seen.add(row[0])
        values[positions[row[0]]] = vector
    if seen != set(ids):
        raise PopulationReferenceError("invalid_reference")
    # Metadata is authoritative for depth: do not trust an unverified manifest summary.
    actual_depth = depth_distribution(labels)
    if "depth_distribution" in manifest and manifest["depth_distribution"] != actual_depth:
        raise PopulationReferenceError("invalid_reference")
    return manifest, labels, features, PopulationMatrix(ids, features, values), hashes


def load_bundle(base: Path, spec: ProviderSpec):
    raw = {name: (base / name).read_bytes() for name in ("manifest.json", "metadata.tsv", "species_abundance.tsv")}
    hashes = {name: digest(value) for name, value in raw.items()}
    key = (spec.version, tuple(sorted(spec.pipeline.items())), spec.normalization, spec.phenotype, spec.minimum_subjects, tuple(hashes.items()))
    with _CACHE_LOCK:
        if key not in _CACHE:
            _CACHE[key] = _parse_bundle(raw, hashes, spec)
            if len(_CACHE) > 2:
                _CACHE.popitem(last=False)
        _CACHE.move_to_end(key)
        manifest, labels, features, matrix, cached_hashes = _CACHE[key]
        return copy.deepcopy(manifest), copy.deepcopy(labels), list(features), matrix, dict(cached_hashes)


def _runs(value):
    return set(re.findall(r"(?:ERR|SRR|DRR)\d+", str(value or "")))


def outlier_baseline(values, target):
    """A descriptive count baseline, never a corrected hypothesis-test p-value."""
    target = np.asarray(target)
    p5, p95 = quantile(values, [.05, .95], axis=0)
    count = int(((target < p5) | (target > p95)).sum())
    n = len(values)
    if n <= 300:
        counts = []
        for i in range(n):
            lo, hi = quantile(np.delete(values, i, axis=0), [.05, .95], axis=0)
            counts.append(int(((values[i] < lo) | (values[i] > hi)).sum()))
        method = "leave_one_subject_out"
    else:
        counts = ((values < p5) | (values > p95)).sum(axis=1).astype(int).tolist()
        method = "full_cohort_quantiles_approximate_leave_one_out"
    summary = distribution(counts)
    ordered = summary.pop("_distribution")
    return {**summary, "target_outside_count": count, "target_percentile": percentile(ordered, count),
            "reference_counts": counts, "n_species": int(values.shape[1]), "method": method}


def compare(sample_id, metadata, *, spec, loader, ordination, reasons=REASONS):
    audit = {"provider": spec.provider, "status": "unavailable", "configured": True,
             "generated_by": spec.version, "file": str(spec.reference_dir()),
             "reference_population": spec.population, "normalization": spec.normalization,
             "scope": spec.scope, "pipeline": dict(spec.pipeline)}
    result = {"audit": audit, "species": [], "diversity": []}

    def fail(reason):
        audit.update(reason=reason, reason_cn=reasons[reason], display_status="未建立健康对照")
        return result

    if not valid_sample_id(sample_id):
        return fail("invalid_target")
    if token(metadata.get("qc_status")) in {"failed", "fail", "不通过", "未通过"}:
        return fail("target_qc_failed")
    try:
        manifest, labels, features, matrix, hashes = loader(spec.reference_dir())
    except OSError:
        return fail("reference_missing")
    except (ValueError, TypeError, KeyError, UnicodeError, csv.Error):
        return fail("invalid_reference")
    matching = manifest.get("stratify_by", [])
    boundaries = manifest.get("age_band_boundaries", list(DEFAULT_AGE_BANDS))
    minimum = manifest.get("minimum_subjects", spec.minimum_subjects)
    audit.update(cohort_id=manifest["cohort_id"], cohort_version=manifest["cohort_version"],
                 source_url=manifest["source_url"], file_sha256=hashes,
                 minimum_subjects=minimum, stratify_by=matching, age_band_boundaries=boundaries)
    folder = spec.profiles_dir() / sample_id
    try:
        raw = (folder / "profile.tsv").read_bytes()
        provenance = json.loads((folder / "provenance.json").read_bytes())
        if not isinstance(provenance, dict):
            return fail("invalid_target")
        target, header = read_target(raw)
        if (provenance.get("sample_id") != sample_id or provenance.get("profile_sha256") != digest(raw)
                or provenance.get("normalization") != spec.normalization):
            return fail("invalid_target")
        expected = dict(spec.target_pipeline)
        if (provenance.get("pipeline") != expected or header.get("database_version") != expected["database_version"]
                or any(expected.get(k) != v for k, v in header.items())):
            return fail("incompatible_pipeline")
        prepared = provenance.get("comparison_metadata", {})
        if not isinstance(prepared, dict):
            return fail("invalid_target")
        fields = ("subject_id", "study_id", "source_runs", "run_ids", "NCBI_accession", "age", "sex", "country", "qc_status", "number_reads", "number_bases")
        metadata = {**{k: prepared[k] for k in fields if k in prepared}, **metadata}
        if token(metadata.get("qc_status")) in {"failed", "fail", "不通过", "未通过"}:
            return fail("target_qc_failed")
        target, raw_total = normalize(target)
        audit.update(target_profile=str(folder / "profile.tsv"), target_profile_sha256=digest(raw),
                     target_raw_species_sum=raw_total, target_provenance=provenance)
    except FileNotFoundError:
        return fail("target_missing")
    except PermissionError:
        return fail("target_unreadable")
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return fail("invalid_target")
    target_stratum = stratum(metadata, matching, boundaries)
    if any(not v for v in target_stratum):
        return fail("missing_matching_metadata")
    target_runs = set().union(*(_runs(metadata.get(k)) for k in ("source_runs", "run_ids", "NCBI_accession")), _runs(provenance.get("source_runs")))
    exclusions = {"self": 0, "matching": 0}
    selected, selected_labels = [], []
    for label in labels:
        same_person = (present(metadata.get("subject_id")) and str(metadata["subject_id"]).strip() == str(label["subject_id"]).strip()
                       and (not present(metadata.get("study_id")) or str(metadata["study_id"]).strip() == str(label["study_id"]).strip()))
        if label["sample_id"] == sample_id or str(label.get("original_sample_id", "")) == sample_id or same_person or target_runs & _runs(label["source_runs"]):
            exclusions["self"] += 1
        elif stratum(label, matching, boundaries) != target_stratum:
            exclusions["matching"] += 1
        else:
            selected.append(label["sample_id"])
            selected_labels.append(label)
    audit.update(n_subjects=len(selected), n_reference=len(selected), exclusions=exclusions, selected_stratum=list(target_stratum))
    if len(selected) < minimum:
        return fail("insufficient_subjects")
    version = "sha256:" + digest(json.dumps({"files": hashes, "selected": sorted(selected), "target": digest(raw),
        "normalization": spec.normalization, "bootstrap": [BOOTSTRAP_SEED, BOOTSTRAP_ITERATIONS]}, sort_keys=True).encode())
    common = {"generated_by": spec.version, "reference_version": version, "reference_population": spec.population,
              "n_subjects": len(selected), "n_reference": len(selected), "method": spec.method, "source_file": str(folder / "profile.tsv")}
    values = matrix.selected(selected)
    positions = {key: i for i, key in enumerate(features)}
    lineages = {species_key(line.split("\t", 1)[0]): line.split("\t", 1)[0] for line in raw.decode("utf-8-sig").splitlines()
                if line.split("\t", 1)[0].rsplit("|", 1)[-1].startswith("s__")}
    union = sorted(set(features) | set(target))
    for key in union:
        column = values[:, positions[key]] if key in positions else np.zeros(len(selected))
        positive = column[column > 0]
        result["species"].append({**common, **comparison(target.get(key, 0), column), "species": key,
            "abundance": target.get(key, 0), "unit": "%", "n_detected": len(positive), "n_zero": len(selected) - len(positive),
            "detection_rate": len(positive) / len(selected), "reference_detected_median": quantile(positive, .5) if len(positive) else None,
            "taxonomy_lineage": lineages.get(key, "")})
    result["species"].sort(key=lambda row: (-row["abundance"], row["species"]))
    observed = diversity_metrics([{"abundance": v} for v in target.values()], complete=True)
    population_metrics = [diversity_metrics([{"abundance": v} for v in row], complete=True) for row in values]
    for key, title in METRICS:
        reference_values = [row[key] for row in population_metrics if row.get(key) is not None]
        if observed.get(key) is not None and len(reference_values) >= minimum:
            result["diversity"].append({**common, **comparison(observed[key], reference_values), "metric": key,
                "name": title, "value": observed[key], "unit": "种" if key == "richness" else "无量纲", "definition": observed["definition"]})
    # A common species universe includes reference-absent target species as zeros.
    baseline_values = np.zeros((len(selected), len(union)))
    for j, key in enumerate(union):
        if key in positions:
            baseline_values[:, j] = values[:, positions[key]]
    result["outlier_baseline"] = outlier_baseline(baseline_values, np.array([target.get(k, 0) for k in union]))
    result["n_abnormal"] = sum(abnormal(row) for row in result["species"])
    result["n_borderline"] = sum(row["borderline"] for row in result["species"])
    studies = {}
    for label, metrics in zip(selected_labels, population_metrics):
        studies.setdefault(str(label["study_id"]), []).append(metrics)
    per_study = [{"study_id": study, "n_subjects": len(rows),
                  **{key + "_median": quantile([r[key] for r in rows], .5) for key in ("richness", "shannon")}} for study, rows in sorted(studies.items())]
    batch = {"n_studies": len(per_study), "studies": per_study,
             **{key + "_median_range": [min(r[key + "_median"] for r in per_study), max(r[key + "_median"] for r in per_study)] for key in ("richness", "shannon")}}
    depth = {"reference": depth_distribution(selected_labels), "target": {}, "warnings": []}
    for key in ("number_reads", "number_bases"):
        value = finite(provenance.get(key))
        value = value if value is not None else finite(metadata.get(key))
        if value is None and key == "number_reads":
            value = profile_read_count(raw)
        depth["target"][key] = value if value is not None and value > 0 else None
    for key, summary in depth["reference"].items():
        value = depth["target"][key]
        if value is not None and value > 0 and not summary["p5"] <= value <= summary["p95"]:
            depth["warnings"].append("待测样本" + key + "位于参考人群深度P5–P95之外，丰富度可能不可比；未进行下采样。")
    result["ordination"] = ordination(target, matrix, selected, reference_version=version, stratify_by=matching)
    limitations = list(spec.limitations)
    if not matching:
        limitations.append("使用cMD总体，未按年龄、性别或地区匹配。")
    if not present(metadata.get("subject_id")) and not target_runs:
        limitations.append("仅能排除同名样本；未提供个体或run标识，不能核验其他编号是否属于同一个体。")
    if "number_reads" not in depth["reference"] or depth["target"].get("number_reads") is None:
        limitations.append("参考或待测缺少可比reads数，无法核验测序深度对丰富度的影响。")
    audit.update(status="available", version=version, limitations=limitations, study_batch=batch, sequencing_depth=depth,
                 bootstrap={"iterations": BOOTSTRAP_ITERATIONS, "seed": BOOTSTRAP_SEED, "confidence": .95,
                            "method": "exact_marginal_empirical_bootstrap_order_statistics_and_multinomial"},
                 percentile_method="midrank empirical CDF; zeros included", quantile_method="linear interpolation at (n-1)*p")
    return result
