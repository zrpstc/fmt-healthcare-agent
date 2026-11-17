"""Train transparent cMD cohort models: gut age, enterotype, health index, disease signatures.

Everything here is pure computation on in-memory matrices so it can be tested on
synthetic data.  ``scripts/prepare_cmd_cohort_models.py`` supplies the official
curatedMetagenomicData matrices; ``cohort_insights`` applies the stored models.

Only linear models and centroids are stored, as plain JSON (no pickles), so the
runtime is a dot product and every coefficient can be audited.

Design choices (also recorded in the bundle manifest):

* features are log10(relative abundance % + PSEUDOCOUNT) of species seen in at
  least ``MIN_PREVALENCE`` of the training subjects, standardised;
* gut age: ridge regression on healthy adults, honest error from study-grouped
  cross-validation, plus the usual regression-to-the-mean correction
  (expected prediction for a given chronological age) so the age gap is not
  biased toward the cohort mean;
* enterotype: k-means (k=3) on Hellinger-transformed genus profiles of healthy
  adults; clusters are named by their mean Prevotella / Bacteroides load;
* health index: class-balanced logistic regression, healthy vs the configured
  disease cohorts, with study-grouped cross-validated AUC;
* disease signatures: species enriched/depleted in each disease cohort versus
  healthy controls from the same studies (Mann-Whitney + BH).  The signature
  score is mean log-abundance of enriched minus depleted species; its AUC is
  estimated with study-grouped cross-validation that reselects species per fold.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np

MODEL_VERSION = "cmd-cohort-models-v1"
PSEUDOCOUNT = 1e-3  # percent units, i.e. 1e-5 as a fraction
MIN_PREVALENCE = 0.10
GENUS_MIN_PREVALENCE = 0.05
AGE_RANGE = (18.0, 90.0)
RANDOM_STATE = 20261117
REFERENCE_POINTS = 400
QUANTILES = np.linspace(0, 1, 101)

BACTEROIDES_GROUP = ("bacteroides", "phocaeicola")
PREVOTELLA_GROUP = ("prevotella", "segatella")
ENTEROTYPES = {
    "ET-B": {"label": "拟杆菌型", "driver": "拟杆菌属"},
    "ET-P": {"label": "普雷沃菌型", "driver": "普雷沃菌属"},
    "ET-F": {"label": "厚壁菌型", "driver": "瘤胃球菌科等厚壁菌"},
}
# Adult disease cohorts in cMD3 with enough subjects to describe; Chinese labels for display.
DISEASES = {
    "CRC": "结直肠癌",
    "adenoma": "结直肠腺瘤",
    "IBD": "炎症性肠病",
    "T2D": "2型糖尿病",
    "IGT": "糖耐量受损",
    "ACVD": "动脉粥样硬化性心血管病",
    "CAD": "冠心病",
    "cirrhosis": "肝硬化",
    "AS": "强直性脊柱炎",
    "schizophrenia": "精神分裂症",
}
MIN_DISEASE_SUBJECTS = 50
MIN_CONTROLS = 20
SIGNATURE_SIZE = 15
SIGNATURE_Q = 0.1


@dataclass
class Cohort:
    """Subject-level species matrix (percent, rows sum to 100) and labels."""

    species: list[str]
    values: np.ndarray  # subjects x species
    genus_of: dict[str, str]  # species key -> genus (lower case)
    labels: list[dict]  # sample_id, study_id, group ("healthy" or disease id), age
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        self.values = np.asarray(self.values, dtype=float)
        if self.values.shape != (len(self.labels), len(self.species)):
            raise ValueError("cohort matrix shape does not match labels/species")
        if not np.isfinite(self.values).all() or (self.values < 0).any():
            raise ValueError("cohort matrix contains invalid abundances")

    def mask(self, predicate) -> np.ndarray:
        return np.array([bool(predicate(row)) for row in self.labels])


# ----------------------------------------------------------------- utilities
def log_features(values: np.ndarray) -> np.ndarray:
    return np.log10(np.asarray(values, dtype=float) + PSEUDOCOUNT)


def genus_matrix(cohort: Cohort, genera: list[str] | None = None) -> tuple[list[str], np.ndarray]:
    names = sorted({g for g in cohort.genus_of.values() if g}) if genera is None else list(genera)
    index = {g: i for i, g in enumerate(names)}
    result = np.zeros((cohort.values.shape[0], len(names)))
    for j, key in enumerate(cohort.species):
        g = cohort.genus_of.get(key)
        if g in index:
            result[:, index[g]] += cohort.values[:, j]
    return names, result


def hellinger(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    totals = values.sum(axis=1, keepdims=True)
    totals[totals == 0] = 1
    return np.sqrt(values / totals)


def _groups(labels: list[dict]) -> np.ndarray:
    return np.array([str(row.get("study_id", "")) for row in labels])


def _folds(groups: np.ndarray, y=None, n_splits: int = 5):
    from sklearn.model_selection import GroupKFold, StratifiedKFold, KFold
    unique = len(set(groups.tolist()))
    if unique >= 3:
        return list(GroupKFold(n_splits=min(n_splits, unique)).split(np.zeros(len(groups)), groups=groups))
    if y is not None:
        return list(StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE).split(np.zeros(len(groups)), y))
    return list(KFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE).split(np.zeros(len(groups))))


def _quantiles(values) -> list[float]:
    return [float(v) for v in np.quantile(np.asarray(values, dtype=float), QUANTILES)]


def _subset(n: int, size: int = REFERENCE_POINTS) -> np.ndarray:
    if n <= size:
        return np.arange(n)
    return np.sort(np.random.default_rng(RANDOM_STATE).choice(n, size=size, replace=False))


def _bh(pvalues: np.ndarray) -> np.ndarray:
    p = np.asarray(pvalues, dtype=float)
    n = len(p)
    if not n:
        return p
    order = np.argsort(p)
    ranked = p[order] * n / np.arange(1, n + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    result = np.empty(n)
    result[order] = np.minimum(ranked, 1.0)
    return result


def _auc(scores_negative, scores_positive) -> float:
    from scipy.stats import mannwhitneyu
    if not len(scores_negative) or not len(scores_positive):
        return float("nan")
    u = mannwhitneyu(scores_positive, scores_negative, alternative="two-sided").statistic
    return float(u / (len(scores_positive) * len(scores_negative)))


def _linear_payload(species, mean, scale, coef, intercept) -> dict:
    keep = [i for i, w in enumerate(coef) if abs(w) > 1e-12]
    return {
        "features": [species[i] for i in keep],
        "mean": [float(mean[i]) for i in keep],
        "scale": [float(scale[i]) for i in keep],
        "coef": [float(coef[i]) for i in keep],
        "intercept": float(intercept),
    }


def prevalent_species(cohort: Cohort, mask: np.ndarray, minimum: float = MIN_PREVALENCE) -> list[int]:
    detected = (cohort.values[mask] > 0).mean(axis=0)
    return [i for i, rate in enumerate(detected) if rate >= minimum]


# ------------------------------------------------------------------ gut age
def train_gut_age(cohort: Cohort) -> dict:
    from sklearn.linear_model import RidgeCV
    from sklearn.preprocessing import StandardScaler

    ages = np.array([float(row.get("age", "nan") or "nan") for row in cohort.labels])
    mask = cohort.mask(lambda row: row["group"] == "healthy") & np.isfinite(ages)
    mask &= (ages >= AGE_RANGE[0]) & (ages <= AGE_RANGE[1])
    if mask.sum() < 100:
        raise ValueError("insufficient healthy adults with age for the gut-age model")
    columns = prevalent_species(cohort, mask)
    x = log_features(cohort.values[mask][:, columns])
    y = ages[mask]
    groups = _groups([row for row, keep in zip(cohort.labels, mask) if keep])
    alphas = np.logspace(0, 4, 13)
    predictions = np.zeros_like(y)
    for train, test in _folds(groups):
        scaler = StandardScaler().fit(x[train])
        model = RidgeCV(alphas=alphas).fit(scaler.transform(x[train]), y[train])
        predictions[test] = model.predict(scaler.transform(x[test]))
    scaler = StandardScaler().fit(x)
    model = RidgeCV(alphas=alphas).fit(scaler.transform(x), y)
    # Regression-to-the-mean: expected prediction given chronological age.
    slope, intercept = np.polyfit(y, predictions, 1)
    species = [cohort.species[i] for i in columns]
    subset = _subset(len(y))
    return {
        "model": _linear_payload(species, scaler.mean_, scaler.scale_, model.coef_, model.intercept_),
        "alpha": float(model.alpha_),
        "age_range": list(AGE_RANGE),
        "bias_correction": {"slope": float(slope), "intercept": float(intercept)},
        "cv_mae": float(np.mean(np.abs(predictions - y))),
        "cv_r": float(np.corrcoef(predictions, y)[0, 1]),
        "cv_method": "study_grouped_kfold" if len(set(groups.tolist())) >= 3 else "kfold",
        "n_train": int(mask.sum()),
        "n_studies": int(len(set(groups.tolist()))),
        "reference_points": [[round(float(y[i]), 1), round(float(predictions[i]), 1)] for i in subset],
    }


# --------------------------------------------------------------- enterotype
def _name_clusters(centroid_genus: np.ndarray, genera: list[str]) -> list[str]:
    def load(group):
        idx = [i for i, g in enumerate(genera) if g in group]
        return centroid_genus[:, idx].sum(axis=1) if idx else np.zeros(len(centroid_genus))
    prevotella, bacteroides = load(PREVOTELLA_GROUP), load(BACTEROIDES_GROUP)
    names = [""] * len(centroid_genus)
    remaining = list(range(len(centroid_genus)))
    p = max(remaining, key=lambda i: prevotella[i]); names[p] = "ET-P"; remaining.remove(p)
    b = max(remaining, key=lambda i: bacteroides[i]); names[b] = "ET-B"; remaining.remove(b)
    for i in remaining:
        names[i] = "ET-F"
    return names


def train_enterotype(cohort: Cohort) -> dict:
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA

    mask = cohort.mask(lambda row: row["group"] == "healthy")
    all_genera, matrix = genus_matrix(cohort)
    matrix = matrix[mask]
    prevalence = (matrix > 0).mean(axis=0)
    keep = [i for i, rate in enumerate(prevalence) if rate >= GENUS_MIN_PREVALENCE]
    genera = [all_genera[i] for i in keep]
    for group in (BACTEROIDES_GROUP, PREVOTELLA_GROUP):
        for g in group:
            if g in all_genera and g not in genera:
                genera.append(g); keep.append(all_genera.index(g))
    # Hellinger on the full genus profile, then restricted to the kept genera.
    transformed = hellinger(matrix)[:, keep]
    km = KMeans(n_clusters=3, n_init=20, random_state=RANDOM_STATE).fit(transformed)
    names = _name_clusters(km.cluster_centers_ ** 2, genera)
    pca = PCA(n_components=2, random_state=RANDOM_STATE).fit(transformed)
    coords = pca.transform(transformed)
    assigned = [names[i] for i in km.labels_]
    subset = _subset(len(assigned))
    drivers = {}
    driver_genera = [g for g in ("bacteroides", "phocaeicola", "prevotella", "segatella",
                                 "faecalibacterium", "ruminococcus", "alistipes", "bifidobacterium") if g in genera]
    raw = matrix[:, keep]
    for name in ENTEROTYPES:
        rows = raw[np.array(assigned) == name]
        drivers[name] = {g: float(np.median(rows[:, genera.index(g)])) if len(rows) else 0.0 for g in driver_genera}
    centroids_2d = pca.transform(km.cluster_centers_)
    return {
        "genera": genera,
        "centroids": [{"id": names[i], **ENTEROTYPES[names[i]],
                       "vector": [float(v) for v in km.cluster_centers_[i]],
                       "pca": [float(v) for v in centroids_2d[i]],
                       "n": int(sum(1 for a in assigned if a == names[i]))} for i in range(3)],
        "pca": {"mean": [float(v) for v in pca.mean_], "components": [[float(v) for v in row] for row in pca.components_],
                "explained_variance_ratio": [float(v) for v in pca.explained_variance_ratio_]},
        "driver_genera": driver_genera,
        "driver_medians": drivers,
        "reference_points": [[round(float(coords[i, 0]), 4), round(float(coords[i, 1]), 4), assigned[i]] for i in subset],
        "n_train": int(mask.sum()),
        "method": "kmeans_k3_hellinger_genus",
    }


# ------------------------------------------------------------- health index
def train_health_index(cohort: Cohort, diseases: list[str]) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    mask = cohort.mask(lambda row: row["group"] == "healthy" or row["group"] in diseases)
    y = np.array([1 if row["group"] == "healthy" else 0 for row, keep in zip(cohort.labels, mask) if keep])
    if y.sum() < 100 or (1 - y).sum() < 100:
        raise ValueError("insufficient subjects for the health index")
    columns = prevalent_species(cohort, mask)
    x = log_features(cohort.values[mask][:, columns])
    groups = _groups([row for row, keep in zip(cohort.labels, mask) if keep])

    def fit(x_train, y_train):
        scaler = StandardScaler().fit(x_train)
        model = LogisticRegression(C=0.05, class_weight="balanced", max_iter=2000).fit(scaler.transform(x_train), y_train)
        return scaler, model

    scores = np.zeros(len(y))
    # Disease studies usually contain their own controls, so grouping by study is
    # valid: both classes appear in most held-out folds.
    for train, test in _folds(groups, y):
        if len(set(y[train].tolist())) < 2:
            continue
        scaler, model = fit(x[train], y[train])
        scores[test] = model.decision_function(scaler.transform(x[test]))
    auc = _auc(scores[y == 0], scores[y == 1])
    scaler, model = fit(x, y)
    full = model.decision_function(scaler.transform(x))
    species = [cohort.species[i] for i in columns]
    return {
        "model": _linear_payload(species, scaler.mean_, scaler.scale_, model.coef_[0], model.intercept_[0]),
        "cv_auc": auc,
        "cv_method": "study_grouped_kfold" if len(set(groups.tolist())) >= 3 else "stratified_kfold",
        "healthy_quantiles": _quantiles(full[y == 1]),
        "disease_quantiles": _quantiles(full[y == 0]),
        "n_healthy": int(y.sum()),
        "n_disease": int((1 - y).sum()),
        "diseases": list(diseases),
    }


# -------------------------------------------------------- disease signatures
def _signature(x_control: np.ndarray, x_disease: np.ndarray, species: list[str]):
    from scipy.stats import mannwhitneyu
    prev_c = (x_control > 0).mean(axis=0)
    prev_d = (x_disease > 0).mean(axis=0)
    candidates = [j for j in range(len(species)) if max(prev_c[j], prev_d[j]) >= MIN_PREVALENCE]
    if not candidates:
        return [], []
    lc, ld = log_features(x_control[:, candidates]), log_features(x_disease[:, candidates])
    pvalues = np.array([mannwhitneyu(ld[:, k], lc[:, k], alternative="two-sided").pvalue
                        if np.ptp(np.concatenate([ld[:, k], lc[:, k]])) > 0 else 1.0 for k in range(len(candidates))])
    qvalues = _bh(pvalues)
    effect = ld.mean(axis=0) - lc.mean(axis=0)
    rows = [{"index": candidates[k], "species": species[candidates[k]], "effect": float(effect[k]),
             "q": float(qvalues[k]), "prev_disease": float(prev_d[candidates[k]]), "prev_control": float(prev_c[candidates[k]]),
             "median_disease": float(np.median(x_disease[:, candidates[k]])),
             "median_control": float(np.median(x_control[:, candidates[k]]))}
            for k in range(len(candidates)) if qvalues[k] < SIGNATURE_Q]
    enriched = sorted((r for r in rows if r["effect"] > 0), key=lambda r: -r["effect"])[:SIGNATURE_SIZE]
    depleted = sorted((r for r in rows if r["effect"] < 0), key=lambda r: r["effect"])[:SIGNATURE_SIZE]
    return enriched, depleted


def signature_score(values: np.ndarray, enriched_idx: list[int], depleted_idx: list[int]) -> np.ndarray:
    logs = log_features(values)
    up = logs[:, enriched_idx].mean(axis=1) if enriched_idx else 0
    down = logs[:, depleted_idx].mean(axis=1) if depleted_idx else 0
    return np.asarray(up - down, dtype=float) * np.ones(len(values))


def train_disease(cohort: Cohort, disease: str) -> dict | None:
    diseased = cohort.mask(lambda row: row["group"] == disease)
    if diseased.sum() < MIN_DISEASE_SUBJECTS:
        return None
    studies = {row["study_id"] for row, keep in zip(cohort.labels, diseased) if keep}
    control = cohort.mask(lambda row: row["group"] == "healthy" and row["study_id"] in studies)
    control_source = "same_studies"
    if control.sum() < MIN_CONTROLS:
        control = cohort.mask(lambda row: row["group"] == "healthy")
        control_source = "all_healthy"
    both = diseased | control
    x, y = cohort.values[both], diseased[both].astype(int)
    groups = _groups([row for row, keep in zip(cohort.labels, both) if keep])
    scores = np.full(len(y), np.nan)
    for train, test in _folds(groups, y):
        tr_c, tr_d = x[train][y[train] == 0], x[train][y[train] == 1]
        if not len(tr_c) or not len(tr_d):
            continue
        up, down = _signature(tr_c, tr_d, cohort.species)
        if not up and not down:
            continue
        scores[test] = signature_score(x[test], [r["index"] for r in up], [r["index"] for r in down])
    valid = np.isfinite(scores)
    cv_auc = _auc(scores[valid & (y == 0)], scores[valid & (y == 1)]) if valid.any() else float("nan")
    enriched, depleted = _signature(x[y == 0], x[y == 1], cohort.species)
    if not enriched and not depleted:
        return None
    full = signature_score(x, [r["index"] for r in enriched], [r["index"] for r in depleted])
    strip = lambda rows: [{k: v for k, v in r.items() if k != "index"} for r in rows]  # noqa: E731
    return {
        "id": disease,
        "label": DISEASES.get(disease, disease),
        "n_disease": int(y.sum()),
        "n_control": int((1 - y).sum()),
        "n_studies": len(studies),
        "control_source": control_source,
        "enriched": strip(enriched),
        "depleted": strip(depleted),
        "cv_auc": None if math.isnan(cv_auc) else cv_auc,
        "control_quantiles": _quantiles(full[y == 0]),
        "disease_quantiles": _quantiles(full[y == 1]),
    }


# --------------------------------------------------------------- prevalence
def prevalence_table(cohort: Cohort, diseases: list[str], minimum: float = 0.01) -> dict:
    groups = [("healthy", "健康成人")] + [(d, DISEASES.get(d, d)) for d in diseases]
    masks = [cohort.mask(lambda row, g=g: row["group"] == g) for g, _ in groups]
    present = cohort.values > 0
    rates = np.vstack([present[m].mean(axis=0) if m.any() else np.zeros(len(cohort.species)) for m in masks])
    rows = {}
    for j, key in enumerate(cohort.species):
        if rates[:, j].max() < minimum:
            continue
        medians = []
        for m in masks:
            column = cohort.values[m, j]
            column = column[column > 0]
            medians.append(round(float(np.median(column)), 6) if len(column) else None)
        rows[key] = {"prevalence": [round(float(v), 4) for v in rates[:, j]], "detected_median": medians}
    return {"groups": [{"id": g, "label": label, "n": int(m.sum())} for (g, label), m in zip(groups, masks)],
            "species": rows}


def train_all(cohort: Cohort, diseases: list[str] | None = None) -> dict:
    present = {row["group"] for row in cohort.labels}
    diseases = [d for d in (diseases or list(DISEASES)) if d in present]
    disease_models = [m for m in (train_disease(cohort, d) for d in diseases) if m]
    kept = [m["id"] for m in disease_models]
    return {
        "version": MODEL_VERSION,
        "pseudocount": PSEUDOCOUNT,
        "gut_age": train_gut_age(cohort),
        "enterotype": train_enterotype(cohort),
        "health_index": train_health_index(cohort, kept),
        "diseases": disease_models,
        "prevalence": prevalence_table(cohort, kept),
    }
