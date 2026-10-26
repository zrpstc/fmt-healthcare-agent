"""Offline MHOmicrobiome comparisons on an isolated MetaPhlAn 4.2.2 profile."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from pathlib import Path

from wgs_fmt_platform.paths import runtime_path

from .healthy import METRICS, distribution, percentile
from .inputs import diversity_metrics, finite
from .reference import species_key

VERSION = "mhomic-reference-v1"
NORMALIZATION = "species_classified_sum_100_v1"
PIPELINE = {"profiler": "MetaPhlAn", "profiler_version": "4.2.2",
            "database_version": "mpa_vJan25_CHOCOPhlAnSGB_202503"}
POPULATION = "MHOmicrobiome MHNO（代谢健康且非肥胖）"
REASONS = {
    "reference_missing": "MHOmicrobiome 参考文件尚未准备或不可读取",
    "invalid_reference": "MHOmicrobiome 参考格式、校验和或版本不符合约定",
    "target_missing": "尚未生成该样本独立的 MetaPhlAn 4.2.2 健康对照谱",
    "target_unreadable": "当前运行用户无权读取独立对照谱目录或文件",
    "invalid_target": "独立对照谱不完整、含无效数值或与运行记录不一致",
    "incompatible_pipeline": "独立对照谱的软件或数据库版本与 MHOmicrobiome 不一致",
    "missing_matching_metadata": "缺少所配置的人口学匹配信息",
    "insufficient_subjects": "筛选及排除同一个体后，参考人数低于配置门槛",
    "target_qc_failed": "待测样本质控未通过，暂停健康人群比较",
}


class MhoError(ValueError):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def reference_dir() -> Path:
    return runtime_path("WGS_HEALTHY_REFERENCE_DIR", "reference", "mho")


def profiles_dir() -> Path:
    return runtime_path("WGS_MHO_PROFILES_DIR", "reference-targets", "mho")


def valid_sample_id(sample_id: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+", sample_id)) and sample_id not in {".", ".."}


def normalize(profile: dict[str, float]) -> tuple[dict[str, float], float]:
    """Same explicit conditional denominator on both reference and target spectra."""
    if not profile or any(not key or finite(value) is None or not 0 <= value <= 100
                          for key, value in profile.items()):
        raise MhoError("invalid_target")
    total = math.fsum(profile.values())
    if not 0 < total <= 101:
        raise MhoError("invalid_target")
    return {key: value * 100 / total for key, value in profile.items()}, total


def read_target(raw: bytes) -> tuple[dict[str, float], dict]:
    """Read species nodes only; never count both s__ parents and t__ leaves."""
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
            raise MhoError("invalid_target")
        profile[key] = value
    normalize(profile)  # Validate raw units and nonempty species mass.
    return profile, pipeline


def read_table(raw: bytes) -> tuple[list[str], list[dict]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter="\t")
    columns = reader.fieldnames or []
    if len(columns) != len(set(columns)):
        raise MhoError("invalid_reference")
    return columns, list(reader)


def load_bundle(base: Path) -> tuple[dict, list[dict], list[str], dict, dict]:
    raw = {name: (base / name).read_bytes()
           for name in ("manifest.json", "metadata.tsv", "species_abundance.tsv")}
    manifest = json.loads(raw["manifest.json"])
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        raise MhoError("invalid_reference")
    hashes = {name: digest(value) for name, value in raw.items()}
    if (manifest.get("schema_version") != VERSION or manifest.get("pipeline") != PIPELINE
            or manifest.get("normalization") != NORMALIZATION or manifest.get("unit") != "%"
            or manifest.get("phenotype") != "MHNO" or manifest.get("body_site") != "stool"
            or manifest.get("complete_species_profiles") is not True
            or manifest.get("feature_level") != "species"
            or not all(manifest.get(key) for key in ("cohort_id", "cohort_version", "source_url"))
            or any(manifest.get("files", {}).get(name) != hashes[name]
                   for name in ("metadata.tsv", "species_abundance.tsv"))):
        raise MhoError("invalid_reference")
    minimum = manifest.get("minimum_subjects", 30)
    matching = manifest.get("stratify_by", [])
    window = finite(manifest.get("age_window_years", 10))
    if (type(minimum) is not int or minimum < 30 or not isinstance(matching, list)
            or any(key not in {"age", "sex", "country"} for key in matching)
            or len(matching) != len(set(matching)) or window is None or window < 0):
        raise MhoError("invalid_reference")
    manifest["age_window_years"] = window
    columns, labels = read_table(raw["metadata.tsv"])
    required = {"sample_id", "subject_id", "study_id", "phenotype", "source_runs"}
    ids = [row.get("sample_id", "") for row in labels]
    if (not required.issubset(columns) or not all(ids) or len(set(ids)) != len(ids)
            or any(not row.get("subject_id") or not row.get("study_id")
                   or row.get("phenotype") != "MHNO" for row in labels)
            or len({(row["study_id"], row["subject_id"]) for row in labels}) != len(labels)):
        raise MhoError("invalid_reference")
    columns, rows = read_table(raw["species_abundance.tsv"])
    features = [species_key(column) for column in columns[1:]]
    if (not columns or columns[0] != "sample_id" or not features or not all(features)
            or len(set(features)) != len(features)):
        raise MhoError("invalid_reference")
    matrix = {}
    for row in rows:
        sid = row.get("sample_id")
        values = [finite(row.get(column)) for column in columns[1:]]
        if (sid not in ids or sid in matrix or None in row or None in values
                or any(not 0 <= value <= 100 for value in values)
                or not math.isclose(math.fsum(values), 100, abs_tol=0.0001)):
            raise MhoError("invalid_reference")
        matrix[sid] = dict(zip(features, values))
    if set(matrix) != set(ids):
        raise MhoError("invalid_reference")
    return manifest, labels, features, matrix, hashes


def _runs(value: object) -> set[str]:
    return set(re.findall(r"(?:ERR|SRR|DRR)\d+", str(value or "")))


def compare(sample_id: str, metadata: dict) -> dict:
    """Return only a dedicated comparison payload; never alter primary results."""
    audit = {"provider": "mho", "status": "unavailable", "configured": True,
             "generated_by": VERSION, "file": str(reference_dir()),
             "reference_population": POPULATION, "normalization": NORMALIZATION,
             "scope": "published_MHNO_exploratory", "pipeline": PIPELINE}
    result = {"audit": audit, "species": [], "diversity": []}

    def fail(reason):
        audit.update(reason=reason, reason_cn=REASONS[reason])
        return result

    if not valid_sample_id(sample_id):
        return fail("invalid_target")
    if str(metadata.get("qc_status", "")).lower() in {"failed", "fail", "不通过", "未通过"}:
        return fail("target_qc_failed")
    try:
        manifest, labels, features, matrix, hashes = load_bundle(reference_dir())
    except OSError:
        return fail("reference_missing")
    except (ValueError, TypeError, KeyError, UnicodeError, csv.Error):
        return fail("invalid_reference")
    audit.update(cohort_id=manifest["cohort_id"], cohort_version=manifest["cohort_version"],
                 source_url=manifest["source_url"], file_sha256=hashes,
                 minimum_subjects=manifest.get("minimum_subjects", 30),
                 stratify_by=manifest.get("stratify_by", []))
    folder = profiles_dir() / sample_id
    try:
        profile_raw = (folder / "profile.tsv").read_bytes()
        provenance = json.loads((folder / "provenance.json").read_bytes())
        if not isinstance(provenance, dict):
            return fail("invalid_target")
        target, header_pipeline = read_target(profile_raw)
        if (provenance.get("sample_id") != sample_id
                or provenance.get("profile_sha256") != digest(profile_raw)
                or provenance.get("normalization") != NORMALIZATION):
            return fail("invalid_target")
        if (provenance.get("pipeline") != PIPELINE
                or any(PIPELINE.get(key) != value for key, value in header_pipeline.items())
                or "database_version" not in header_pipeline):
            return fail("incompatible_pipeline")
        target, raw_total = normalize(target)
        audit.update(target_profile=str(folder / "profile.tsv"),
                     target_profile_sha256=digest(profile_raw),
                     target_raw_species_sum=raw_total, target_provenance=provenance)
    except FileNotFoundError:
        return fail("target_missing")
    except PermissionError:
        return fail("target_unreadable")
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return fail("invalid_target")
    matching = manifest.get("stratify_by", [])
    if any(metadata.get(key) in (None, "", "unknown") for key in matching):
        return fail("missing_matching_metadata")
    if "age" in matching and (finite(metadata["age"]) is None or float(metadata["age"]) < 0):
        return fail("missing_matching_metadata")
    target_runs = _runs(provenance.get("source_runs")) | _runs(metadata.get("source_runs"))
    target_runs |= _runs(metadata.get("run_ids")) | _runs(metadata.get("NCBI_accession"))
    exclusions = {"self": 0, "matching": 0}
    selected = []
    for label in labels:
        same_person = (str(metadata.get("subject_id", "")) == label["subject_id"]
                       and (not metadata.get("study_id") or metadata["study_id"] == label["study_id"]))
        if label["sample_id"] == sample_id or same_person or target_runs & _runs(label["source_runs"]):
            exclusions["self"] += 1
            continue
        matches = True
        for key in matching:
            value = label.get(key, "")
            if key == "age":
                age = finite(value)
                matches &= age is not None and age >= 0 and abs(age - float(metadata[key])) <= manifest.get("age_window_years", 10)
            else:
                def token(item):
                    text = str(item).strip().casefold()
                    return {"f": "female", "m": "male", "女": "female", "男": "male"}.get(text, text) if key == "sex" else text
                matches &= bool(value) and token(value) == token(metadata[key])
        if matches:
            selected.append(label["sample_id"])
        else:
            exclusions["matching"] += 1
    audit.update(n_subjects=len(selected), n_reference=len(selected), exclusions=exclusions)
    if len(selected) < manifest.get("minimum_subjects", 30):
        return fail("insufficient_subjects")
    version = "sha256:" + digest(json.dumps({"files": hashes, "selected": sorted(selected),
        "target": audit["target_profile_sha256"], "normalization": NORMALIZATION}, sort_keys=True).encode())
    common = {"generated_by": VERSION, "reference_version": version,
              "reference_population": POPULATION, "n_subjects": len(selected),
              "n_reference": len(selected),
              "method": "MetaPhlAn 4.2.2 Jan25；已分类物种内归一化", "source_file": audit["target_profile"]}

    def comparison(value, values):
        summary = distribution(values)
        ordered = summary.pop("_distribution")
        p5, p95 = summary["p5"], summary["p95"]
        status = "unknown" if p5 == p95 else "low" if value < p5 else "high" if value > p95 else "normal"
        return {**summary, **common, "percentile": percentile(ordered, value), "status": status,
                "comparison_reason": "zero_width_reference_interval" if p5 == p95 else "compared"}

    for key in sorted(set(features) | set(target)):
        values = [matrix[sid].get(key, 0) for sid in selected]
        result["species"].append({**comparison(target.get(key, 0), values),
            "species": key, "abundance": target.get(key, 0), "unit": "%",
            "n_detected": sum(value > 0 for value in values),
            "detection_rate": sum(value > 0 for value in values) / len(selected)})
    result["species"].sort(key=lambda row: (-row["abundance"], row["species"]))
    observed = diversity_metrics([{"abundance": value} for value in target.values()], complete=True)
    population_metrics = [diversity_metrics([{"abundance": value} for value in matrix[sid].values()], complete=True) for sid in selected]
    for key, title in METRICS:
        values = [row[key] for row in population_metrics if row.get(key) is not None]
        if observed.get(key) is not None and len(values) >= manifest.get("minimum_subjects", 30):
            result["diversity"].append({**comparison(observed[key], values), "metric": key,
                "name": title, "value": observed[key], "unit": "种" if key == "richness" else "无量纲",
                "definition": observed["definition"]})
    limitations = ["MHNO 是原研究定义的代谢健康非肥胖人群，不是通用临床正常值。",
        "丰度为已分类物种内归一化比例；未分类部分不参与分母，不能与主分析原始百分数混用。",
        "原研究的抽样深度及研究间差异未统一校正；尤其检出丰富度仅作探索性比较。",
        "P5–P95 和经验百分位描述该参考队列，不代表疾病概率。"]
    if not matching:
        limitations.append("使用 MHNO 总体，未按年龄、性别或地区匹配。")
    if not metadata.get("subject_id") and not target_runs:
        limitations.append("仅能排除同名样本；未提供个体或 run 标识，不能核验其他编号是否属于同一个体。")
    audit.update(status="available", version=version, limitations=limitations,
                 percentile_method="midrank empirical CDF; zeros included",
                 quantile_method="linear interpolation at (n-1)*p")
    return result
