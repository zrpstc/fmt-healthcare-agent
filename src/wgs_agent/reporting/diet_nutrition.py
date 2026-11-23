"""Dietary-nutrient tendency scores from gut-microbiome Mendelian-randomisation (MR) evidence.

For every UK Biobank nutrient in ``knowledge_base/diet_mr/diet_mr_weights.json``
(24-hour recall estimates: energy, macronutrients, fibre, vitamins, minerals,
alcohol)::

    score = sum_i  beta_i * (-log10 P_i) * z_i

with the same features, GTDB/MetaPhlAn naming and z standardisation as the
disease-risk score (``wgs_agent.reporting.disease_risk``).  A positive score means
the microbiome traits that MR links to a *higher* intake of the nutrient are above
the healthy-adult average.  It is a tendency, not an intake: it is only ever shown
as a percentile among the cMD healthy adults.

Overall score (0-100): the mean over the nutrients with a direction of the
percentile (``encourage``) or 100 - percentile (``limit``); ``neutral`` nutrients
are shown but not included.  It is reported with its own percentile among the same
healthy adults (their overall scores are computed the same way when the bundle is
built).

Training (``train``) runs on the cMD matrices when the bundle is prepared; the
report only reads the stored bundle (``analyze``).  Plain JSON, no pickles.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from threading import RLock

import numpy as np

from .disease_risk import (
    MIN_PREVALENCE,
    MIN_TRAITS,
    PSEUDOCOUNT,
    Z_CLIP,
    _kde,
    _quantiles,
    _terms,
    absent_value,
    profile_features,
)

VERSION = "diet-nutrition-v1"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEIGHTS_PATH = PROJECT_ROOT / "knowledge_base" / "diet_mr" / "diet_mr_weights.json"
GRID_POINTS = 80
RANDOM_STATE = 20261123
DIRECTIONS = ("encourage", "limit", "neutral")
MIN_OVERALL_NUTRIENTS = 5


def load_weights(path: Path = WEIGHTS_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _percentiles_within(values: np.ndarray) -> np.ndarray:
    """Percentile (0..100) of every value within its own sample, against a 101-point summary."""
    from .cohort_insights import quantile_percentile
    q = _quantiles(values)
    return np.array([quantile_percentile(q, float(v)) for v in values])


def overall_value(percentiles: dict[str, float], directions: dict[str, str]) -> tuple[float | None, int]:
    """Mean of direction-adjusted percentiles; (None, n) below ``MIN_OVERALL_NUTRIENTS``."""
    parts = []
    for nid, pct in percentiles.items():
        direction = directions.get(nid)
        if direction == "encourage":
            parts.append(pct)
        elif direction == "limit":
            parts.append(100.0 - pct)
    if len(parts) < MIN_OVERALL_NUTRIENTS:
        return None, len(parts)
    return float(sum(parts) / len(parts)), len(parts)


# -------------------------------------------------------------- training
def train(cohort, weights: dict) -> dict:
    """Standardise MR features on cMD healthy adults and store score distributions.

    ``cohort`` is a ``cohort_models.Cohort`` (subjects x MetaPhlAn species, percent);
    only its healthy adults are used.
    """
    healthy = np.array([row["group"] == "healthy" for row in cohort.labels])
    if healthy.sum() < 50:
        raise ValueError("too few healthy subjects for the diet-nutrition reference")
    nutrients = list(weights.get("nutrients", []))
    for nutrient in nutrients:
        if nutrient.get("direction") not in DIRECTIONS:
            raise ValueError(f"nutrient {nutrient.get('id')} has no valid direction")
    wanted = sorted({fid for n in nutrients for fid in _terms(n)})
    rows = [row for row, keep in zip(cohort.values, healthy) if keep]
    profiles = [profile_features(dict(zip(cohort.species, row))) for row in rows]
    matrix = np.array([[p.get(f, absent_value(f)) for f in wanted] for p in profiles], dtype=float)
    detected = np.array([[f.startswith("alpha:") or f in p for f in wanted] for p in profiles], dtype=bool)
    prevalence = detected.mean(axis=0)
    mean = matrix.mean(axis=0)
    sd = matrix.std(axis=0, ddof=1)
    usable = (prevalence >= MIN_PREVALENCE) & (sd > 0)
    features = {
        f: {"mean": round(float(mean[j]), 8), "sd": round(float(sd[j]), 8), "prevalence": round(float(prevalence[j]), 4)}
        for j, f in enumerate(wanted) if usable[j]
    }
    column = {f: j for j, f in enumerate(wanted)}
    z = np.clip((matrix - mean) / np.where(sd > 0, sd, 1.0), -Z_CLIP, Z_CLIP)
    models, skipped = [], []
    subject_pct: dict[str, np.ndarray] = {}
    for nutrient in nutrients:
        terms = _terms(nutrient)
        used = [t for f, t in terms.items() if f in features]
        total_weight = sum(abs(t["weight"]) for t in terms.values())
        used_weight = sum(abs(t["weight"]) for t in used)
        if len(used) < MIN_TRAITS:
            skipped.append({"id": nutrient["id"], "reason": "too_few_matched_traits", "matched": len(used)})
            continue
        idx = [column[t["feature"]] for t in used]
        w = np.array([t["weight"] for t in used])
        scores = z[:, idx] @ w
        subject_pct[nutrient["id"]] = _percentiles_within(scores)
        models.append({
            "id": nutrient["id"],
            "outcome": nutrient.get("outcome"),
            "name_cn": nutrient["name_cn"],
            "name_en": nutrient["name_en"],
            "group": nutrient["group"],
            "direction": nutrient["direction"],
            "terms": [{"feature": t["feature"], "weight": round(t["weight"], 8), "traits": t["traits"]}
                      for t in sorted(used, key=lambda t: -abs(t["weight"]))],
            "coverage": {"traits": len(nutrient.get("traits", [])), "tested": nutrient.get("tested"),
                         "features": len(terms), "used": len(used),
                         "weight_share": round(used_weight / total_weight, 4) if total_weight else 0.0},
            "healthy": {"n": int(len(scores)), "quantiles": _quantiles(scores)},
        })
    directions = {m["id"]: m["direction"] for m in models}
    overall = None
    if subject_pct:
        per_subject = [overall_value({nid: float(p[i]) for nid, p in subject_pct.items()}, directions)
                       for i in range(len(profiles))]
        values = np.array([v for v, _n in per_subject if v is not None], dtype=float)
        if len(values):
            lo, hi = 0.0, 100.0
            grid = np.linspace(lo, hi, GRID_POINTS)
            overall = {
                "n_nutrients": per_subject[0][1],
                "grid": [round(float(v), 6) for v in grid],
                "healthy": {"n": int(len(values)), "quantiles": _quantiles(values),
                            "density": _kde(values, grid, np.random.default_rng(RANDOM_STATE))},
            }
    return {
        "version": VERSION,
        "pseudocount": PSEUDOCOUNT,
        "z_clip": Z_CLIP,
        "min_prevalence": MIN_PREVALENCE,
        "weights_schema": weights.get("schema_version"),
        "weights_source": weights.get("source"),
        "weights_selection": weights.get("selection"),
        "groups": weights.get("groups", []),
        "features": features,
        "nutrients": models,
        "overall": overall,
        "skipped": skipped,
    }


# --------------------------------------------------------------- runtime
def score_nutrient(model: dict, spec: dict, values: dict[str, float]) -> dict:
    from .cohort_insights import quantile_percentile

    features = model["features"]
    total = 0.0
    contributions = []
    for term in spec["terms"]:
        ref = features[term["feature"]]
        x = values.get(term["feature"], absent_value(term["feature"]))
        z = max(-Z_CLIP, min(Z_CLIP, (x - ref["mean"]) / (ref["sd"] or 1.0)))
        part = term["weight"] * z
        total += part
        contributions.append({"feature": term["feature"], "weight": term["weight"], "z": round(z, 4),
                              "contribution": round(part, 6),
                              "detected": term["feature"].startswith("alpha:") or term["feature"] in values})
    pct = quantile_percentile(spec["healthy"]["quantiles"], total)
    return {
        "id": spec["id"], "name_cn": spec["name_cn"], "name_en": spec["name_en"],
        "group": spec["group"], "direction": spec["direction"],
        "score": round(total, 6), "percentile_healthy": round(pct, 2),
        "coverage": spec["coverage"], "n_terms": len(contributions),
        "healthy": {"n": spec["healthy"]["n"], "median": spec["healthy"]["quantiles"][50]},
        # Traits pushing the tendency up (towards a higher intake) and down.
        "raising": sorted((c for c in contributions if c["contribution"] > 0), key=lambda c: -c["contribution"])[:5],
        "lowering": sorted((c for c in contributions if c["contribution"] < 0), key=lambda c: c["contribution"])[:5],
    }


def score_profile(model: dict, profile: dict[str, float]) -> dict:
    from .cohort_insights import quantile_percentile

    values = profile_features(profile)
    nutrients = [score_nutrient(model, spec, values) for spec in model.get("nutrients", [])]
    result: dict = {"nutrients": nutrients, "overall": None}
    spec = model.get("overall")
    if spec:
        directions = {n["id"]: n["direction"] for n in nutrients}
        value, used = overall_value({n["id"]: n["percentile_healthy"] for n in nutrients}, directions)
        if value is not None:
            result["overall"] = {
                "score": round(value, 2),
                "percentile_healthy": round(quantile_percentile(spec["healthy"]["quantiles"], value), 2),
                "n_nutrients": used,
                "grid": spec["grid"],
                "healthy": {"n": spec["healthy"]["n"], "density": spec["healthy"]["density"],
                            "median": spec["healthy"]["quantiles"][50],
                            "p25": spec["healthy"]["quantiles"][25], "p75": spec["healthy"]["quantiles"][75]},
            }
    return result


_CACHE: dict = {}
_LOCK = RLock()
REASONS = {
    "bundle_missing": "膳食营养参考尚未在服务器上准备",
    "invalid_bundle": "膳食营养参考文件格式或校验和不符合约定",
    "target_missing": "尚未生成该样本独立的对照物种谱",
    "target_unreadable": "当前运行用户无权读取独立对照谱",
    "invalid_target": "独立对照谱不完整或与运行记录不一致",
    "incompatible_pipeline": "独立对照谱的软件或数据库版本与参考人群不一致",
    "target_qc_failed": "待测样本质控未通过，暂停膳食营养评分",
}


def bundle_dir() -> Path:
    """Explicit WGS_CMD_DIET_NUTRITION_DIR, else the bundle prepared under WGS_CMD_DATA_ROOT."""
    import os
    from wgs_fmt_platform.cmd_data import prepared_dir
    from wgs_fmt_platform.paths import runtime_path
    if os.environ.get("WGS_CMD_DIET_NUTRITION_DIR", "").strip():
        return runtime_path("WGS_CMD_DIET_NUTRITION_DIR", "reference", "cmd", VERSION)
    return prepared_dir("diet_nutrition") or runtime_path("WGS_CMD_DIET_NUTRITION_DIR", "reference", "cmd", VERSION)


def load_bundle(base: Path) -> tuple[dict, dict, dict]:
    from .population_reference import digest
    raw = {name: (base / name).read_bytes() for name in ("manifest.json", "models.json")}
    hashes = {name: digest(value) for name, value in raw.items()}
    key = tuple(sorted(hashes.items()))
    with _LOCK:
        if key not in _CACHE:
            manifest = json.loads(raw["manifest.json"])
            model = json.loads(raw["models.json"])
            if (not isinstance(manifest, dict) or manifest.get("schema_version") != VERSION
                    or manifest.get("files", {}).get("models.json") != hashes["models.json"]
                    or not isinstance(model, dict) or model.get("version") != VERSION):
                raise ValueError("invalid_bundle")
            _CACHE.clear()
            _CACHE[key] = (manifest, model)
        manifest, model = _CACHE[key]
    return copy.deepcopy(manifest), model, hashes


def analyze(sample_id: str, metadata: dict | None = None) -> dict:
    """Score every nutrient for one sample; ``audit.status`` says whether it worked."""
    from . import cohort_insights
    from .population_reference import token, valid_sample_id

    metadata = dict(metadata or {})
    audit: dict = {"status": "unavailable", "generated_by": VERSION}
    result: dict = {"audit": audit}

    def fail(reason):
        audit.update(reason=reason, reason_cn=REASONS[reason])
        return result

    if not valid_sample_id(sample_id):
        return fail("invalid_target")
    if token(metadata.get("qc_status")) in {"failed", "fail", "不通过", "未通过"}:
        return fail("target_qc_failed")
    try:
        manifest, model, hashes = load_bundle(bundle_dir())
    except OSError:
        return fail("bundle_missing")
    except (ValueError, TypeError, KeyError, UnicodeError):
        return fail("invalid_bundle")
    try:
        target, _genus, merged, profile_sha = cohort_insights._target(sample_id, metadata)
    except FileNotFoundError:
        return fail("target_missing")
    except PermissionError:
        return fail("target_unreadable")
    except cohort_insights.IncompatiblePipeline:
        return fail("incompatible_pipeline")
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return fail("invalid_target")
    if token(merged.get("qc_status")) in {"failed", "fail", "不通过", "未通过"}:
        return fail("target_qc_failed")
    try:
        scored = score_profile(model, target)
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):
        return fail("invalid_bundle")
    if not math.isfinite(sum(n["score"] for n in scored["nutrients"])):
        return fail("invalid_bundle")
    result.update(scored)
    audit.update(status="available", file_sha256=hashes, target_profile_sha256=profile_sha,
                 n_healthy=manifest.get("n_healthy"), cohort_version=manifest.get("cohort_version"),
                 weights_sha256=manifest.get("weights_sha256"), z_clip=model.get("z_clip"),
                 formula="score = Σ β × (−lgP) × z")
    return result
