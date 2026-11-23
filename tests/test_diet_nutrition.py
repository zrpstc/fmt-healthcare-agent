from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from wgs_agent.reporting import diet_nutrition
from wgs_agent.reporting.cohort_models import Cohort

ROOT = Path(__file__).resolve().parents[1]
SPECIES = [
    "bacteroides vulgatus", "faecalibacterium prausnitzii", "eubacterium rectale",
    "escherichia coli", "akkermansia muciniphila", "roseburia intestinalis",
]


def _trait(kind, name, beta, p):
    return {"kind": kind, "name": name, "trait": name, "beta": beta, "p": p, "neg_lg_p": -math.log10(p)}


def _nutrient(nid, direction, traits, group="维生素"):
    return {"id": nid, "outcome": nid + "_X.v1.1", "name_en": nid, "name_cn": "营养" + nid, "group": group,
            "direction": direction, "tested": 400, "traits": traits}


FIBRE = [  # more F. prausnitzii / E. rectale -> higher fibre-intake tendency
    _trait("species", "Faecalibacterium prausnitzii D", 0.20, 1e-3),
    _trait("species", "Agathobacter rectalis, GCA_1", 0.10, 1e-2),
    _trait("species", "Escherichia coli", -0.10, 1e-2),
]
SUGAR = [  # more E. coli -> higher sugar-intake tendency
    _trait("species", "Escherichia coli, GCF_1", 0.30, 1e-4),
    _trait("genus", "Akkermansia", -0.05, 0.02),
    _trait("species", "Faecalibacterium prausnitzii", -0.10, 1e-2),
]


def _weights(*nutrients):
    return {"schema_version": "diet-mr-weights-v1", "source": {"mr_file": "t.xlsx"},
            "groups": ["能量与宏量营养素", "维生素"], "nutrients": list(nutrients)}


def _all(min_overall=2):
    nutrients = []
    for i in range(min_overall + 2):
        nutrients.append(_nutrient(f"9{i:05d}", "encourage" if i % 2 == 0 else "limit", FIBRE if i % 2 == 0 else SUGAR))
    nutrients.append(_nutrient("100002", "neutral", FIBRE, group="能量与宏量营养素"))
    nutrients.append(_nutrient("100018", "neutral", [_trait("species", "Escherichia coli", 0.1, 0.01)]))
    return _weights(*nutrients)


def _cohort(n_healthy=300, n_other=40, seed=3):
    rng = np.random.default_rng(seed)
    rows, labels = [], []
    for i in range(n_healthy + n_other):
        base = rng.lognormal(mean=1.0, sigma=0.6, size=len(SPECIES))
        base[rng.random(len(SPECIES)) < 0.15] = 0.0
        if i >= n_healthy:
            base[3] *= 50  # patients must not shift the healthy reference
        rows.append(100 * base / base.sum())
        labels.append({"sample_id": f"s{i}", "study_id": "st" + str(i % 3), "subject_id": str(i),
                       "group": "healthy" if i < n_healthy else "T2D", "age": "50"})
    return Cohort(species=SPECIES, values=np.array(rows), genus_of={k: k.split()[0] for k in SPECIES}, labels=labels)


def test_overall_value_adjusts_direction_and_needs_enough_nutrients():
    directions = {"a": "encourage", "b": "limit", "c": "neutral", "d": "encourage", "e": "limit", "f": "encourage"}
    pct = {"a": 80.0, "b": 80.0, "c": 99.0, "d": 60.0, "e": 10.0, "f": 50.0}
    value, n = diet_nutrition.overall_value(pct, directions)
    assert n == 5 and value == pytest.approx((80 + 20 + 60 + 90 + 50) / 5)
    assert diet_nutrition.overall_value({"a": 80.0, "c": 50.0}, directions) == (None, 1)


def test_train_and_score_follow_formula(monkeypatch):
    monkeypatch.setattr(diet_nutrition, "MIN_OVERALL_NUTRIENTS", 2)
    weights = _all()
    model = diet_nutrition.train(_cohort(), weights)
    ids = [n["id"] for n in model["nutrients"]]
    assert "100018" not in ids  # a single matched trait is below MIN_TRAITS
    assert model["skipped"] == [{"id": "100018", "reason": "too_few_matched_traits", "matched": 1}]
    assert all(n["healthy"]["n"] == 300 for n in model["nutrients"])  # healthy adults only
    assert model["overall"]["n_nutrients"] == 4 and model["overall"]["healthy"]["n"] == 300
    assert len(model["overall"]["grid"]) == len(model["overall"]["healthy"]["density"]) == diet_nutrition.GRID_POINTS

    fibre_spec = model["nutrients"][0]
    weight = next(t for t in fibre_spec["terms"] if t["feature"] == "species:faecalibacterium prausnitzii")["weight"]
    assert weight == pytest.approx(0.20 * 3)

    good = {"faecalibacterium prausnitzii": 40.0, "eubacterium rectale": 30.0, "bacteroides vulgatus": 30.0}
    poor = {"escherichia coli": 60.0, "bacteroides vulgatus": 40.0}
    g = diet_nutrition.score_profile(model, good)
    p = diet_nutrition.score_profile(model, poor)
    by_id = lambda r: {n["id"]: n for n in r["nutrients"]}  # noqa: E731
    assert by_id(g)[fibre_spec["id"]]["percentile_healthy"] > by_id(p)[fibre_spec["id"]]["percentile_healthy"]
    assert g["overall"]["score"] > p["overall"]["score"]
    assert 0 <= p["overall"]["percentile_healthy"] <= g["overall"]["percentile_healthy"] <= 100
    # The neutral nutrient is scored but not part of the overall score.
    assert by_id(g)["100002"]["direction"] == "neutral" and g["overall"]["n_nutrients"] == 4
    # Low fibre tendency is driven by the lowering traits (F. prausnitzii absent, E. coli up).
    fibre_poor = by_id(p)[fibre_spec["id"]]
    assert {c["feature"] for c in fibre_poor["lowering"]} >= {"species:faecalibacterium prausnitzii"}

    feats = diet_nutrition.profile_features(poor)
    total = 0.0
    for term in fibre_spec["terms"]:
        ref = model["features"][term["feature"]]
        x = feats.get(term["feature"], diet_nutrition.absent_value(term["feature"]))
        total += term["weight"] * max(-4, min(4, (x - ref["mean"]) / ref["sd"]))
    assert fibre_poor["score"] == pytest.approx(total, abs=1e-5)


def test_invalid_direction_is_rejected():
    with pytest.raises(ValueError):
        diet_nutrition.train(_cohort(), _weights(_nutrient("1", "more", FIBRE)))


def test_shipped_weights_cover_all_nutrients():
    weights = diet_nutrition.load_weights()
    assert weights["schema_version"] == "diet-mr-weights-v1"
    assert len(weights["nutrients"]) == 22
    assert {n["direction"] for n in weights["nutrients"]} == {"encourage", "limit", "neutral"}
    for nutrient in weights["nutrients"]:
        assert nutrient["name_cn"] and nutrient["group"] in weights["groups"]
        assert nutrient["outcome"].startswith(nutrient["id"] + "_")
        assert len(nutrient["traits"]) >= 3
        for trait in nutrient["traits"]:
            assert trait["p"] < 0.05 and trait["kind"] in {"species", "genus", "alpha"}
            assert trait["neg_lg_p"] == pytest.approx(-math.log10(trait["p"]), rel=1e-4)


def test_analyze_reports_missing_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("WGS_CMD_DIET_NUTRITION_DIR", str(tmp_path / "missing"))
    result = diet_nutrition.analyze("S1", {})
    assert result["audit"]["status"] == "unavailable"
    assert result["audit"]["reason"] in {"bundle_missing", "invalid_target"}


def test_bundle_round_trip_and_tamper_check(tmp_path, monkeypatch):
    monkeypatch.setattr(diet_nutrition, "MIN_OVERALL_NUTRIENTS", 2)
    model = diet_nutrition.train(_cohort(), _all())
    payload = json.dumps(model, allow_nan=False).encode()
    (tmp_path / "models.json").write_bytes(payload)
    (tmp_path / "manifest.json").write_text(json.dumps({
        "schema_version": diet_nutrition.VERSION, "files": {"models.json": hashlib.sha256(payload).hexdigest()}}))
    _manifest, loaded, _ = diet_nutrition.load_bundle(tmp_path)
    assert loaded["nutrients"][0]["direction"] == "encourage"
    (tmp_path / "models.json").write_bytes(payload + b" ")
    with pytest.raises(ValueError):
        diet_nutrition.load_bundle(tmp_path)


def _load_script(name):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_script_selects_abundance_traits_and_is_deterministic(tmp_path):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("openpyxl")
    script = _load_script("import_diet_mr")
    mr = pd.DataFrame([
        ["E1", "species abundance", "Escherichia coli, GCF_1", "100009_Englyst_dietary_fibre.v1.1", 12, -0.2, 0.001, -3, 3],
        ["E2", "genus abundance", "Akkermansia", "100009_Englyst_dietary_fibre.v1.1", 9, 0.1, 0.04, -1.4, 1.4],
        ["E3", "alpha diversity abundance", "Shannon diversity", "100022_Alcohol.v1.1", 15, 0.05, 0.01, -2, 2],
        ["E4", "species presence", "Escherichia coli, GCF_1", "100009_Englyst_dietary_fibre.v1.1", 12, 0.5, 1e-6, -6, 6],
        ["E5", "species abundance", "Roseburia sp, GCA_2", "100022_Alcohol.v1.1", 10, 0.3, 0.2, -0.7, 0.7],
        ["E6", "species abundance", "CAG-452 sp000434035, GCA_3", "100022_Alcohol.v1.1", None, None, None, "#NUM!", "#NUM!"],
    ], columns=["exposure", "分类", "肠道菌群/功能通路", "outcome", "nsnp", "IVW_beta", "IVW_pval", "lg(pval)", "负lg(pval)"])
    nutrients = pd.DataFrame([["100009", "Englyst dietary fibre", "Englyst 膳食纤维"], ["100022", "Alcohol", "酒精"]],
                             columns=["Field ID", "英文名称（reported_trait）", "中文名称"])
    mr_path, nutrient_path = tmp_path / "mr.xlsx", tmp_path / "nutrients.xlsx"
    mr.to_excel(mr_path, index=False)
    nutrients.to_excel(nutrient_path, index=False)
    payload = script.load(mr_path, nutrient_path, 0.05, list(script.CATEGORY_KIND))
    by_id = {n["id"]: n for n in payload["nutrients"]}
    assert [n["id"] for n in payload["nutrients"]] == ["100009", "100022"]  # display-group order
    assert by_id["100009"]["direction"] == "encourage" and by_id["100022"]["direction"] == "limit"
    assert [t["kind"] for t in by_id["100009"]["traits"]] == ["species", "genus"]  # presence trait dropped
    assert by_id["100009"]["traits"][0]["name"] == "Escherichia coli" and by_id["100009"]["traits"][0]["nsnp"] == 12
    assert by_id["100022"]["traits"] == [{**by_id["100022"]["traits"][0], "kind": "alpha", "name": "shannon"}]
    assert by_id["100009"]["tested"] == 2 and by_id["100022"]["tested"] == 2  # rows without P are not tested
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    script.write(payload, first)
    script.write(script.load(mr_path, nutrient_path, 0.05, list(script.CATEGORY_KIND)), second)
    assert first.read_bytes() == second.read_bytes()
    json.loads(first.read_text())

    nutrients.loc[2] = ["123456", "Unknown", "未知"]
    nutrients.to_excel(nutrient_path, index=False)
    with pytest.raises(ValueError, match="NUTRIENT_ROLES"):
        script.load(mr_path, nutrient_path, 0.05, list(script.CATEGORY_KIND))


def test_build_script_writes_verified_bundle(tmp_path, monkeypatch):
    import csv
    monkeypatch.setattr(diet_nutrition, "MIN_OVERALL_NUTRIENTS", 2)
    script = _load_script("prepare_cmd_diet_nutrition")
    cohort = _cohort(n_healthy=120, n_other=30)
    package = tmp_path / "pkg"; package.mkdir()
    (package / "DESCRIPTION").write_text("Package: curatedMetagenomicData\nVersion: 3.99.0\n")
    meta_rows, by_study = [], {}
    for i, label in enumerate(cohort.labels):
        group = label["group"]
        meta_rows.append({"sample_id": label["sample_id"], "subject_id": "P" + label["sample_id"],
                          "study_name": label["study_id"], "body_site": "stool", "age": "50",
                          "disease": "healthy" if group == "healthy" else "T2D",
                          "study_condition": "control" if group == "healthy" else group,
                          "antibiotics_current_use": "no", "days_from_first_collection": "0"})
        by_study.setdefault(label["study_id"], []).append(i)
    metadata = tmp_path / "meta.tsv"
    with metadata.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(meta_rows[0]), delimiter="\t")
        writer.writeheader(); writer.writerows(meta_rows)
    downloaded = []
    for study, rows in by_study.items():
        export = tmp_path / f"{study}.species.tsv"
        with export.open("w", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(["taxonomy", *(cohort.labels[i]["sample_id"] for i in rows)])
            for j, name in enumerate(cohort.species):
                genus = name.split()[0].capitalize()
                writer.writerow([f"k__Bacteria|g__{genus}|s__{name.capitalize().replace(' ', '_')}",
                                 *(cohort.values[i, j] for i in rows)])
        downloaded.append({"study": study, "resource_id": "EH1", "title": f"x.{study}.relative_abundance",
                           "url": "https://example.invalid", "sha256": "0", "bytes": 1, "export": export})
    monkeypatch.setattr(script.cohort_script.reference, "export_matrices", lambda *a, **k: downloaded)
    weights = tmp_path / "weights.json"
    weights.write_text(json.dumps(_all()))
    out = tmp_path / "bundle"
    result = script.build(package, metadata, tmp_path / "catalog", tmp_path / "src", out, weights_path=weights)
    assert result["status"] == "built" and result["n_healthy"] == 120 and result["n_nutrients"] == 5
    manifest, model, _ = diet_nutrition.load_bundle(out)
    assert manifest["weights_sha256"] == hashlib.sha256(weights.read_bytes()).hexdigest()
    assert manifest["overall_nutrients"] == 4 and model["overall"]["healthy"]["n"] == 120
    assert script.build(package, metadata, tmp_path / "catalog", tmp_path / "src", out,
                        weights_path=weights)["status"] == "already_built"
