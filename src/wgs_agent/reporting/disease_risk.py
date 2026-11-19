"""Disease risk score from gut-microbiome Mendelian-randomisation (MR) evidence.

For every FinnGen endpoint in ``knowledge_base/disease_mr/disease_mr_weights.json``::

    score = sum_i  beta_i * (-log10 P_i) * z_i

* ``beta_i`` / ``P_i``: IVW MR estimate of trait i (a species, a genus or an
  alpha-diversity index) on the disease;
* ``z_i``: the sample's value of trait i standardised against the cMD healthy
  adults: (log10(relative abundance % + PSEUDOCOUNT) - mean) / sd for taxa,
  the raw index for alpha diversity; clipped to +/- ``Z_CLIP``.

A positive score means the traits that MR links to *higher* risk are above the
healthy-population average (or the protective ones below it).  The score has no
absolute meaning, so it is always reported as a position in the score
distribution of the same healthy adults, and - where curatedMetagenomicData has
a patient cohort for that disease - next to the patients' distribution.

The MR traits use GTDB names; profiles are MetaPhlAn 3 (NCBI names).  A small
explicit rename table bridges the two; unmatched traits are dropped and the
remaining share of evidence weight is recorded per disease.

Training (``train``) runs on the cMD matrices when the bundle is prepared; the
report only reads the stored bundle (``analyze``).  Plain JSON, no pickles.
"""
from __future__ import annotations

import copy
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from threading import RLock

import numpy as np

VERSION = "disease-risk-v1"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEIGHTS_PATH = PROJECT_ROOT / "knowledge_base" / "disease_mr" / "disease_mr_weights.json"
PSEUDOCOUNT = 1e-3  # percent; identical to cohort_models
Z_CLIP = 4.0
MIN_PREVALENCE = 0.05  # a taxon must be detected in >=5% of healthy adults to be standardised
MIN_TRAITS = 3
MIN_PATIENTS = 30
GRID_POINTS = 80
KDE_SAMPLE = 3000
QUANTILES = np.linspace(0, 1, 101)
RANDOM_STATE = 20261118
# Healthy-population percentile cut-offs for the three display levels.
LEVELS = ((90.0, "high", "偏高"), (75.0, "medium", "中等"), (0.0, "low", "较低"))

# FinnGen endpoint -> cMD patient cohorts usable as the "patients" distribution
# (first one with enough subjects wins).
CMD_COHORTS: dict[str, tuple[str, ...]] = {
    "T2D": ("T2D",),
    "T2D_WIDE": ("T2D",),
    "K11_IBD_STRICT": ("IBD",),
    "K11_FIBROCHIRLIV": ("cirrhosis",),
    "I9_CORATHER": ("ACVD", "CAD"),
    "I9_CHD": ("CAD", "ACVD"),
    "I9_IHD": ("CAD", "ACVD"),
    "F5_SCHZPHR": ("schizophrenia",),
}

# MetaPhlAn 3 (NCBI) species -> GTDB species, only where the name differs after
# suffix stripping.  Genus membership follows the GTDB name.
MPA_TO_GTDB: dict[str, str] = {
    "eubacterium rectale": "agathobacter rectalis",
    "eubacterium hallii": "anaerobutyricum hallii",
    "eubacterium eligens": "lachnospira eligens",
    "eubacterium siraeum": "ruminiclostridium siraeum",
    "eubacterium biforme": "holdemanella biformis",
    "bacteroides vulgatus": "phocaeicola vulgatus",
    "bacteroides dorei": "phocaeicola dorei",
    "bacteroides massiliensis": "phocaeicola massiliensis",
    "bacteroides plebeius": "phocaeicola plebeius",
    "bacteroides coprocola": "phocaeicola coprocola",
    "bacteroides coprophilus": "phocaeicola coprophilus",
    "bacteroides sartorii": "phocaeicola sartorii",
    "bacteroides salanitronis": "phocaeicola salanitronis",
    "ruminococcus torques": "mediterraneibacter torques",
    "ruminococcus lactaris": "mediterraneibacter lactaris",
    "ruminococcus faecis": "mediterraneibacter faecis",
    "ruminococcus obeum": "blautia obeum",
    "coprococcus comes": "bariatricus comes",
    "clostridium bolteae": "enterocloster bolteae",
    "clostridium citroniae": "enterocloster citroniae",
    "clostridium clostridioforme": "enterocloster clostridioformis",
    "clostridium lavalense": "enterocloster lavalensis",
    "clostridium aldenense": "enterocloster aldenensis",
    "clostridium asparagiforme": "enterocloster asparagiformis",
    "clostridium ramosum": "thomasclavelia ramosa",
    "erysipelatoclostridium ramosum": "thomasclavelia ramosa",
    "clostridium hathewayi": "hungatella hathewayi",
    "clostridium bartlettii": "intestinibacter bartlettii",
}
GTDB_TO_MPA = {v: k for k, v in MPA_TO_GTDB.items()}
# MR trait names that denote the same MetaPhlAn 3 species.
MR_ALIASES = {
    "faecalibacterium duncaniae": "faecalibacterium prausnitzii",
    "anaerobutyricum soehngenii": "anaerobutyricum hallii",
    "instestinimonas gabonensis": "intestinimonas gabonensis",
}
_GTDB_SUFFIX = re.compile(r"^[A-Z]{1,2}$")
ALPHA_FEATURES = ("shannon", "richness", "inverse_simpson")
ALPHA_LABELS = {"shannon": "香农多样性", "richness": "物种丰富度", "inverse_simpson": "逆辛普森多样性"}


# ------------------------------------------------------------------ naming
def gtdb_name(raw: str) -> str:
    """'Blautia_A obeum, GCA_1' / 'Faecalibacterium prausnitzii D' -> 'blautia obeum'."""
    name = str(raw).split(",")[0].replace("_", " ")
    tokens = [t for t in name.split() if not _GTDB_SUFFIX.match(t)]
    key = " ".join(tokens[:2]).casefold()
    return MR_ALIASES.get(key, key)


def species_to_gtdb(mpa_key: str) -> str:
    key = str(mpa_key).replace("_", " ").casefold().strip()
    return MPA_TO_GTDB.get(key, key)


def feature_id(kind: str, name: str) -> str:
    if kind == "alpha":
        return "alpha:" + name
    return f"{kind}:{gtdb_name(name) if kind == 'species' else gtdb_name(name).split()[0]}"


def display_latin(feature: str) -> str:
    """Latin name to show for a feature, preferring the MetaPhlAn 3 spelling."""
    kind, _, name = feature.partition(":")
    if kind == "species":
        name = GTDB_TO_MPA.get(name, name)
    return " ".join(part.capitalize() if i == 0 else part for i, part in enumerate(name.split()))


# ------------------------------------------------------------- features
def profile_features(profile: dict[str, float]) -> dict[str, float]:
    """Transformed feature values for one species profile (percent, keys = MetaPhlAn species)."""
    species: dict[str, float] = defaultdict(float)
    genus: dict[str, float] = defaultdict(float)
    positive = []
    for key, value in profile.items():
        value = float(value or 0.0)
        if value <= 0 or not math.isfinite(value):
            continue
        name = species_to_gtdb(key)
        species[name] += value
        genus[name.split()[0]] += value
        positive.append(value)
    features = {f"species:{k}": math.log10(v + PSEUDOCOUNT) for k, v in species.items()}
    features.update({f"genus:{k}": math.log10(v + PSEUDOCOUNT) for k, v in genus.items()})
    total = sum(positive)
    if total > 0:
        p = np.asarray(positive) / total
        features["alpha:shannon"] = float(-(p * np.log(p)).sum())
        features["alpha:richness"] = float(len(positive))
        features["alpha:inverse_simpson"] = float(1.0 / (p ** 2).sum())
    return features


def absent_value(feature: str) -> float:
    return math.log10(PSEUDOCOUNT) if not feature.startswith("alpha:") else 0.0


def load_weights(path: Path = WEIGHTS_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _terms(disease: dict) -> dict[str, dict]:
    """Collapse MR traits onto features; traits naming the same feature add up."""
    terms: dict[str, dict] = {}
    for trait in disease.get("traits", []):
        fid = feature_id(trait["kind"], trait["name"])
        weight = float(trait["beta"]) * float(trait["neg_lg_p"])
        row = terms.setdefault(fid, {"feature": fid, "weight": 0.0, "traits": []})
        row["weight"] += weight
        row["traits"].append({"trait": trait["trait"], "beta": trait["beta"], "p": trait["p"]})
    return terms


# -------------------------------------------------------------- training
def _quantiles(values) -> list[float]:
    return [float(v) for v in np.quantile(np.asarray(values, dtype=float), QUANTILES)]


def _kde(values: np.ndarray, grid: np.ndarray, rng: np.random.Generator) -> list[float]:
    values = np.asarray(values, dtype=float)
    if len(values) > KDE_SAMPLE:
        values = rng.choice(values, KDE_SAMPLE, replace=False)
    sd = float(values.std(ddof=1)) if len(values) > 1 else 0.0
    iqr = float(np.subtract(*np.percentile(values, [75, 25])))
    spread = min(sd, iqr / 1.349) if iqr > 0 else sd
    h = 0.9 * (spread or 1.0) * len(values) ** (-0.2)  # Silverman
    density = np.exp(-0.5 * ((grid[:, None] - values[None, :]) / h) ** 2).sum(axis=1)
    density /= len(values) * h * math.sqrt(2 * math.pi)
    return [round(float(v), 6) for v in density]


def _auc(negative: np.ndarray, positive: np.ndarray) -> float | None:
    if not len(negative) or not len(positive):
        return None
    ranks = np.argsort(np.argsort(np.concatenate([negative, positive]))) + 1
    r_pos = ranks[len(negative):].sum()
    return float((r_pos - len(positive) * (len(positive) + 1) / 2) / (len(negative) * len(positive)))


def train(cohort, weights: dict) -> dict:
    """Standardise MR features on cMD healthy adults and store score distributions.

    ``cohort`` is a ``cohort_models.Cohort`` (subjects x MetaPhlAn species, percent).
    """
    healthy = np.array([row["group"] == "healthy" for row in cohort.labels])
    if healthy.sum() < 50:
        raise ValueError("too few healthy subjects for the disease-risk reference")
    diseases = [d for d in weights.get("diseases", [])]
    wanted = sorted({fid for d in diseases for fid in _terms(d)})
    profiles = [profile_features(dict(zip(cohort.species, row))) for row in cohort.values]
    matrix = np.array([[p.get(f, absent_value(f)) for f in wanted] for p in profiles], dtype=float)
    detected = np.array([[f.startswith("alpha:") or f in p for f in wanted] for p in profiles], dtype=bool)
    prevalence = detected[healthy].mean(axis=0)
    mean = matrix[healthy].mean(axis=0)
    sd = matrix[healthy].std(axis=0, ddof=1)
    usable = (prevalence >= MIN_PREVALENCE) & (sd > 0)
    features = {
        f: {"mean": round(float(mean[j]), 8), "sd": round(float(sd[j]), 8), "prevalence": round(float(prevalence[j]), 4)}
        for j, f in enumerate(wanted) if usable[j]
    }
    column = {f: j for j, f in enumerate(wanted)}
    z = np.clip((matrix - mean) / np.where(sd > 0, sd, 1.0), -Z_CLIP, Z_CLIP)
    groups = np.array([row["group"] for row in cohort.labels])
    rng = np.random.default_rng(RANDOM_STATE)
    models, skipped = [], []
    for disease in diseases:
        terms = _terms(disease)
        used = [t for f, t in terms.items() if f in features]
        total_weight = sum(abs(t["weight"]) for t in terms.values())
        used_weight = sum(abs(t["weight"]) for t in used)
        if len(used) < MIN_TRAITS:
            skipped.append({"id": disease["id"], "reason": "too_few_matched_traits", "matched": len(used)})
            continue
        idx = [column[t["feature"]] for t in used]
        w = np.array([t["weight"] for t in used])
        scores = z[:, idx] @ w
        h_scores = scores[healthy]
        patient = None
        for group in CMD_COHORTS.get(disease["id"], ()):
            mask = groups == group
            if mask.sum() >= MIN_PATIENTS:
                patient = (group, scores[mask])
                break
        pool = np.concatenate([h_scores, patient[1]]) if patient else h_scores
        lo, hi = np.percentile(pool, [0.5, 99.5])
        pad = 0.08 * (hi - lo or 1.0)
        grid = np.linspace(lo - pad, hi + pad, GRID_POINTS)
        model = {
            "id": disease["id"],
            "outcome": disease["outcome"],
            "name_cn": disease["name_cn"],
            "name_en": disease["name_en"],
            "system": disease["system"],
            "terms": [{"feature": t["feature"], "weight": round(t["weight"], 8), "traits": t["traits"]}
                      for t in sorted(used, key=lambda t: -abs(t["weight"]))],
            "coverage": {"traits": len(disease.get("traits", [])), "features": len(terms), "used": len(used),
                         "weight_share": round(used_weight / total_weight, 4) if total_weight else 0.0},
            "grid": [round(float(v), 6) for v in grid],
            "healthy": {"n": int(healthy.sum()), "quantiles": _quantiles(h_scores),
                        "density": _kde(h_scores, grid, rng)},
            "patients": None,
        }
        if patient:
            group, p_scores = patient
            from .cohort_models import DISEASES
            model["patients"] = {"cohort": group, "label": DISEASES.get(group, group), "n": int(len(p_scores)),
                                 "quantiles": _quantiles(p_scores), "density": _kde(p_scores, grid, rng),
                                 "auc": _auc(h_scores, p_scores)}
        models.append(model)
    return {
        "version": VERSION,
        "pseudocount": PSEUDOCOUNT,
        "z_clip": Z_CLIP,
        "min_prevalence": MIN_PREVALENCE,
        "levels": [{"percentile": p, "key": k, "label": label} for p, k, label in LEVELS],
        "weights_schema": weights.get("schema_version"),
        "weights_source": weights.get("source"),
        "weights_selection": weights.get("selection"),
        "features": features,
        "diseases": models,
        "skipped": skipped,
    }


# --------------------------------------------------------------- runtime
def level_for(percentile: float) -> tuple[str, str]:
    for cut, key, label in LEVELS:
        if percentile >= cut:
            return key, label
    return "low", "较低"


def score_disease(model: dict, spec: dict, values: dict[str, float]) -> dict:
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
    key, label = level_for(pct)
    patients = spec.get("patients")
    result = {
        "id": spec["id"], "name_cn": spec["name_cn"], "name_en": spec["name_en"], "system": spec["system"],
        "score": round(total, 6), "percentile_healthy": round(pct, 2), "level": key, "level_label": label,
        "coverage": spec["coverage"], "grid": spec["grid"],
        "healthy": {"n": spec["healthy"]["n"], "density": spec["healthy"]["density"],
                    "p75": spec["healthy"]["quantiles"][75], "p90": spec["healthy"]["quantiles"][90],
                    "median": spec["healthy"]["quantiles"][50]},
        "patients": None,
        "risk_drivers": sorted((c for c in contributions if c["contribution"] > 0), key=lambda c: -c["contribution"])[:5],
        "protective": sorted((c for c in contributions if c["contribution"] < 0), key=lambda c: c["contribution"])[:3],
        "n_terms": len(contributions),
    }
    if patients:
        result["patients"] = {"cohort": patients["cohort"], "label": patients["label"], "n": patients["n"],
                              "density": patients["density"], "median": patients["quantiles"][50],
                              "percentile": round(quantile_percentile(patients["quantiles"], total), 2),
                              "auc": patients.get("auc")}
    return result


def score_profile(model: dict, profile: dict[str, float]) -> list[dict]:
    values = profile_features(profile)
    return [score_disease(model, spec, values) for spec in model.get("diseases", [])]


_CACHE: dict = {}
_LOCK = RLock()
REASONS = {
    "bundle_missing": "疾病风险参考尚未在服务器上准备",
    "invalid_bundle": "疾病风险参考文件格式或校验和不符合约定",
    "target_missing": "尚未生成该样本独立的对照物种谱",
    "target_unreadable": "当前运行用户无权读取独立对照谱",
    "invalid_target": "独立对照谱不完整或与运行记录不一致",
    "incompatible_pipeline": "独立对照谱的软件或数据库版本与参考人群不一致",
    "target_qc_failed": "待测样本质控未通过，暂停疾病风险评估",
}


def bundle_dir() -> Path:
    """Explicit WGS_CMD_DISEASE_RISK_DIR, else the bundle prepared under WGS_CMD_DATA_ROOT."""
    import os
    from wgs_fmt_platform.cmd_data import prepared_dir
    from wgs_fmt_platform.paths import runtime_path
    if os.environ.get("WGS_CMD_DISEASE_RISK_DIR", "").strip():
        return runtime_path("WGS_CMD_DISEASE_RISK_DIR", "reference", "cmd", VERSION)
    return prepared_dir("disease_risk") or runtime_path("WGS_CMD_DISEASE_RISK_DIR", "reference", "cmd", VERSION)


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
    """Score every disease for one sample; ``audit.status`` says whether it worked."""
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
        result["diseases"] = score_profile(model, target)
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):
        result.pop("diseases", None)
        return fail("invalid_bundle")
    audit.update(status="available", file_sha256=hashes, target_profile_sha256=profile_sha,
                 n_healthy=manifest.get("n_healthy"), cohort_version=manifest.get("cohort_version"),
                 weights_sha256=manifest.get("weights_sha256"), z_clip=model.get("z_clip"),
                 formula="score = Σ β × (−lgP) × z")
    return result
