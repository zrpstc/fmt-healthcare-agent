"""Apply the cMD cohort models to a sample's independent MetaPhlAn3/v30 profile.

Offline and read-only: reads the audited bundle written by
``scripts/prepare_cmd_cohort_models.py`` and the same independent target profile
used by the healthy comparison.  Missing or invalid inputs return
``audit.status = "unavailable"`` with a reason code; nothing is guessed.
"""
from __future__ import annotations

import bisect
import copy
import json
import math
from pathlib import Path
from threading import RLock

import numpy as np

from wgs_fmt_platform.paths import runtime_path

from . import cmd
from .cohort_models import ENTEROTYPES, MODEL_VERSION, PSEUDOCOUNT, BACTEROIDES_GROUP, PREVOTELLA_GROUP
from .inputs import finite
from .population_reference import digest, normalize, read_target, species_key, token, valid_sample_id

VERSION = "cohort-insights-v1"
REASONS = {
    "bundle_missing": "人群模型文件尚未准备或不可读取",
    "invalid_bundle": "人群模型文件格式、校验和或版本不符合约定",
    "target_missing": "尚未生成该样本独立的对照物种谱",
    "target_unreadable": "当前运行用户无权读取独立对照谱",
    "invalid_target": "独立对照谱不完整或与运行记录不一致",
    "incompatible_pipeline": "独立对照谱的软件或数据库版本与人群模型不一致",
    "target_qc_failed": "待测样本质控未通过，暂停人群模型分析",
}
MIN_DISEASE_AUC = 0.65
_CACHE: dict = {}
_LOCK = RLock()


class IncompatiblePipeline(Exception):
    pass


def bundle_dir() -> Path:
    """Explicit setting, else the bundle prepared under WGS_CMD_DATA_ROOT once complete, else default."""
    import os
    from wgs_fmt_platform.cmd_data import prepared_dir
    if os.environ.get("WGS_CMD_COHORT_DIR", "").strip():
        return runtime_path("WGS_CMD_COHORT_DIR", "reference", "cmd", "cohort-models-v1")
    return prepared_dir("cohort") or runtime_path("WGS_CMD_COHORT_DIR", "reference", "cmd", "cohort-models-v1")


def load_bundle(base: Path) -> tuple[dict, dict, dict]:
    raw = {name: (base / name).read_bytes() for name in ("manifest.json", "models.json")}
    hashes = {name: digest(value) for name, value in raw.items()}
    key = tuple(sorted(hashes.items()))
    with _LOCK:
        if key not in _CACHE:
            manifest = json.loads(raw["manifest.json"])
            models = json.loads(raw["models.json"])
            if (not isinstance(manifest, dict) or manifest.get("schema_version") != MODEL_VERSION
                    or manifest.get("files", {}).get("models.json") != hashes["models.json"]
                    or manifest.get("pipeline") != cmd.PIPELINE
                    or manifest.get("normalization") != cmd.NORMALIZATION
                    or not isinstance(models, dict) or models.get("version") != MODEL_VERSION):
                raise ValueError("invalid_bundle")
            _CACHE.clear()
            _CACHE[key] = (manifest, models)
        manifest, models = _CACHE[key]
    return copy.deepcopy(manifest), models, hashes


def _target(sample_id: str, metadata: dict):
    folder = cmd.profiles_dir() / sample_id
    raw = (folder / "profile.tsv").read_bytes()
    provenance = json.loads((folder / "provenance.json").read_bytes())
    if not isinstance(provenance, dict):
        raise ValueError("invalid_target")
    target, header = read_target(raw)
    if (provenance.get("sample_id") != sample_id or provenance.get("profile_sha256") != digest(raw)
            or provenance.get("normalization") != cmd.NORMALIZATION):
        raise ValueError("invalid_target")
    expected = dict(cmd.SPEC.target_pipeline)
    if provenance.get("pipeline") != expected or header.get("database_version") != expected["database_version"]:
        raise IncompatiblePipeline("incompatible_pipeline")
    prepared = provenance.get("comparison_metadata", {})
    merged = {**(prepared if isinstance(prepared, dict) else {}), **metadata}
    target, _ = normalize(target)
    genus_of = {}
    for line in raw.decode("utf-8-sig").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        lineage = line.split("\t", 1)[0]
        if not lineage.rsplit("|", 1)[-1].startswith("s__"):
            continue
        genus = next((part[3:] for part in lineage.split("|") if part.startswith("g__")), "")
        genus_of[species_key(lineage)] = genus.replace("_", " ").casefold()
    return target, genus_of, merged, digest(raw)


def _linear(model: dict, target: dict[str, float]) -> tuple[float, float]:
    """Return the linear predictor and the share of |weight| on detected features."""
    total = 0.0
    weight_all = weight_seen = 0.0
    for name, mean, scale, coef in zip(model["features"], model["mean"], model["scale"], model["coef"]):
        value = math.log10(target.get(name, 0.0) + PSEUDOCOUNT)
        total += coef * (value - mean) / (scale or 1.0)
        weight_all += abs(coef)
        if target.get(name, 0.0) > 0:
            weight_seen += abs(coef)
    return model["intercept"] + total, (weight_seen / weight_all if weight_all else 0.0)


def quantile_percentile(quantiles: list[float], value: float) -> float:
    """Percentile of value against a 101-point quantile summary (0..100)."""
    q = list(quantiles)
    if value <= q[0]:
        return 0.0
    if value >= q[-1]:
        return 100.0
    i = bisect.bisect_right(q, value) - 1
    span = q[i + 1] - q[i]
    frac = (value - q[i]) / span if span > 0 else 0.5
    return float(min(100.0, max(0.0, i + frac)))


def gut_age(models: dict, target: dict, metadata: dict) -> dict:
    spec = models["gut_age"]
    predicted, support = _linear(spec["model"], target)
    low, high = spec["age_range"]
    predicted = float(min(high, max(low, predicted)))
    result = {"predicted_age": predicted, "mae": spec["cv_mae"], "r": spec["cv_r"],
              "n_train": spec["n_train"], "n_studies": spec.get("n_studies"), "feature_support": support,
              "reference_points": spec["reference_points"], "age_range": spec["age_range"],
              "chronological_age": None, "expected_for_age": None, "gap": None}
    age = finite(metadata.get("age"))
    if age is not None and low <= age <= 120:
        bias = spec["bias_correction"]
        expected = bias["slope"] * min(age, high) + bias["intercept"]
        result.update(chronological_age=float(age), expected_for_age=float(expected), gap=float(predicted - expected))
    return result


def enterotype(models: dict, target: dict, genus_of: dict) -> dict:
    spec = models["enterotype"]
    genera = spec["genera"]
    totals: dict[str, float] = {}
    for key, value in target.items():
        g = genus_of.get(key, "")
        if g:
            totals[g] = totals.get(g, 0.0) + value
    full = sum(totals.values()) or 1.0
    vector = np.array([math.sqrt(totals.get(g, 0.0) / full) for g in genera])
    distances = {c["id"]: float(np.linalg.norm(vector - np.array(c["vector"]))) for c in spec["centroids"]}
    ordered = sorted(distances.items(), key=lambda item: item[1])
    best, second = ordered[0], ordered[1]
    confidence = 1.0 - best[1] / second[1] if second[1] > 0 else 1.0
    pca = spec["pca"]
    coords = (np.array(pca["components"]) @ (vector - np.array(pca["mean"]))).tolist()
    drivers = []
    for g in spec["driver_genera"]:
        drivers.append({"genus": g, "value": 100 * totals.get(g, 0.0) / full,
                        "typical": {name: spec["driver_medians"].get(name, {}).get(g) for name in ENTEROTYPES}})
    load = lambda group: 100 * sum(totals.get(g, 0.0) for g in group) / full  # noqa: E731
    return {"id": best[0], **ENTEROTYPES[best[0]], "confidence": float(max(0.0, min(1.0, confidence))),
            "distances": distances, "coords": coords, "reference_points": spec["reference_points"],
            "centroids": [{"id": c["id"], "label": c["label"], "pca": c["pca"], "n": c["n"]} for c in spec["centroids"]],
            "drivers": drivers, "bacteroides_load": load(BACTEROIDES_GROUP), "prevotella_load": load(PREVOTELLA_GROUP),
            "explained_variance_ratio": pca.get("explained_variance_ratio"), "n_train": spec["n_train"]}


def health_index(models: dict, target: dict) -> dict:
    spec = models["health_index"]
    score, support = _linear(spec["model"], target)
    probability = 1.0 / (1.0 + math.exp(-max(-50.0, min(50.0, score))))
    return {"score": score, "probability_healthy": probability, "feature_support": support,
            "percentile_healthy": quantile_percentile(spec["healthy_quantiles"], score),
            "percentile_disease": quantile_percentile(spec["disease_quantiles"], score),
            "cv_auc": spec["cv_auc"], "n_healthy": spec["n_healthy"], "n_disease": spec["n_disease"]}


def disease_references(models: dict, target: dict) -> list[dict]:
    rows = []
    for spec in models.get("diseases", []):
        def mean_log(items):
            return (sum(math.log10(target.get(r["species"], 0.0) + PSEUDOCOUNT) for r in items) / len(items)) if items else 0.0
        score = mean_log(spec["enriched"]) - mean_log(spec["depleted"])
        pc = quantile_percentile(spec["control_quantiles"], score)
        pd_ = quantile_percentile(spec["disease_quantiles"], score)
        disease_median = spec["disease_quantiles"][50]
        control_median = spec["control_quantiles"][50]
        if score <= control_median:
            position = "near_control"
        elif score >= disease_median and pc >= 75:
            position = "near_disease"
        else:
            position = "between"
        auc = spec.get("cv_auc")
        rows.append({
            "id": spec["id"], "label": spec["label"], "n_disease": spec["n_disease"], "n_control": spec["n_control"],
            "n_studies": spec["n_studies"], "control_source": spec["control_source"], "cv_auc": auc,
            "informative": auc is not None and auc >= MIN_DISEASE_AUC,
            "score": score, "percentile_control": pc, "percentile_disease": pd_, "position": position,
            "enriched_detected": [{"species": r["species"], "abundance": target[r["species"]],
                                   "prev_disease": r["prev_disease"], "prev_control": r["prev_control"]}
                                  for r in spec["enriched"] if target.get(r["species"], 0) > 0],
            "depleted_detected": [{"species": r["species"], "abundance": target[r["species"]]}
                                  for r in spec["depleted"] if target.get(r["species"], 0) > 0],
            "n_enriched": len(spec["enriched"]), "n_depleted": len(spec["depleted"]),
        })
    return rows


def prevalence_rows(models: dict, target: dict, extra: list[str] = ()) -> dict:
    table = models.get("prevalence", {})
    wanted = {key for key, value in target.items() if value > 0} | {species_key(name) for name in extra}
    species = {key: row for key, row in table.get("species", {}).items() if key in wanted}
    return {"groups": table.get("groups", []), "species": species}


def analyze(sample_id: str, metadata: dict | None = None, *, extra_species: list[str] = ()) -> dict:
    metadata = dict(metadata or {})
    audit = {"status": "unavailable", "generated_by": VERSION, "file": str(bundle_dir())}
    result: dict = {"audit": audit}

    def fail(reason):
        audit.update(reason=reason, reason_cn=REASONS[reason])
        return result

    if not valid_sample_id(sample_id):
        return fail("invalid_target")
    if token(metadata.get("qc_status")) in {"failed", "fail", "不通过", "未通过"}:
        return fail("target_qc_failed")
    try:
        manifest, models, hashes = load_bundle(bundle_dir())
    except OSError:
        return fail("bundle_missing")
    except (ValueError, TypeError, KeyError, UnicodeError):
        return fail("invalid_bundle")
    audit.update(cohort_id=manifest.get("cohort_id"), cohort_version=manifest.get("cohort_version"),
                 source_package_version=manifest.get("source_package_version"), file_sha256=hashes,
                 n_healthy=manifest.get("n_healthy"), n_disease=manifest.get("n_disease"),
                 n_studies=manifest.get("n_studies"), selection_criteria=manifest.get("selection_criteria"))
    try:
        target, genus_of, merged, profile_sha = _target(sample_id, metadata)
    except FileNotFoundError:
        return fail("target_missing")
    except PermissionError:
        return fail("target_unreadable")
    except IncompatiblePipeline:
        return fail("incompatible_pipeline")
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return fail("invalid_target")
    if token(merged.get("qc_status")) in {"failed", "fail", "不通过", "未通过"}:
        return fail("target_qc_failed")
    try:
        result.update(
            gut_age=gut_age(models, target, merged),
            enterotype=enterotype(models, target, genus_of),
            health_index=health_index(models, target),
            diseases=disease_references(models, target),
            prevalence=prevalence_rows(models, target, list(extra_species)),
        )
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):
        for key in ("gut_age", "enterotype", "health_index", "diseases", "prevalence"):
            result.pop(key, None)
        return fail("invalid_bundle")
    audit.update(status="available", target_profile_sha256=profile_sha,
                 version="sha256:" + digest(json.dumps({"bundle": hashes, "target": profile_sha}, sort_keys=True).encode()))
    return result
