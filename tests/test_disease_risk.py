from __future__ import annotations

import json
import math

import numpy as np
import pytest

from wgs_agent.reporting import disease_risk
from wgs_agent.reporting.cohort_models import Cohort

SPECIES = [
    "bacteroides vulgatus", "faecalibacterium prausnitzii", "eubacterium rectale",
    "escherichia coli", "akkermansia muciniphila", "roseburia intestinalis",
]


def _weights(*diseases):
    return {"schema_version": "disease-mr-weights-v1", "source": {"mr_file": "t.xlsx"}, "diseases": list(diseases)}


def _disease(code, traits):
    return {"id": code, "outcome": "finngen_R13_" + code, "name_en": code, "name_cn": "测试" + code,
            "system": "消化系统", "traits": traits}


def _trait(kind, name, beta, p):
    return {"kind": kind, "name": name, "trait": name, "beta": beta, "p": p, "neg_lg_p": -math.log10(p)}


def _cohort(n_healthy=300, n_t2d=80, seed=1):
    rng = np.random.default_rng(seed)
    rows, labels = [], []
    for i in range(n_healthy + n_t2d):
        t2d = i >= n_healthy
        base = rng.lognormal(mean=1.0, sigma=0.6, size=len(SPECIES))
        if t2d:
            base[3] *= 6.0  # E. coli up
            base[1] *= 0.3  # F. prausnitzii down
        base[rng.random(len(SPECIES)) < 0.15] = 0.0
        rows.append(100 * base / base.sum())
        labels.append({"sample_id": f"s{i}", "study_id": "st" + str(i % 3), "subject_id": str(i),
                       "group": "T2D" if t2d else "healthy", "age": "50"})
    return Cohort(species=SPECIES, values=np.array(rows), genus_of={k: k.split()[0] for k in SPECIES}, labels=labels)


def test_gtdb_names_are_normalised_to_metaphlan_keys():
    assert disease_risk.gtdb_name("Blautia_A obeum, GCA_000153905.1") == "blautia obeum"
    assert disease_risk.gtdb_name("Faecalibacterium prausnitzii D") == "faecalibacterium prausnitzii"
    assert disease_risk.gtdb_name("Coprococcus A catus A") == "coprococcus catus"
    assert disease_risk.gtdb_name("Faecalibacterium duncaniae, GCF_1") == "faecalibacterium prausnitzii"
    assert disease_risk.feature_id("genus", "Phocaeicola") == "genus:phocaeicola"
    feats = disease_risk.profile_features({"bacteroides vulgatus": 30.0, "eubacterium rectale": 10.0})
    # NCBI names become GTDB names, and genus follows the GTDB genus.
    assert "species:phocaeicola vulgatus" in feats and "genus:phocaeicola" in feats
    assert "species:agathobacter rectalis" in feats and "genus:bacteroides" not in feats
    assert feats["alpha:richness"] == 2


def test_score_follows_formula_and_population_distributions():
    weights = _weights(
        _disease("T2D", [
            _trait("species", "Escherichia coli, GCF_1", 0.30, 1e-4),
            _trait("species", "Faecalibacterium prausnitzii D", -0.20, 1e-3),
            _trait("genus", "Akkermansia", -0.05, 0.02),
            _trait("species", "Unmatched sp000000001, GCA_1", 0.9, 1e-6),
        ]),
        _disease("G6_MIGRAINE", [_trait("species", "Escherichia coli", 0.1, 0.01)]),
    )
    model = disease_risk.train(_cohort(), weights)
    assert [d["id"] for d in model["diseases"]] == ["T2D"]
    assert model["skipped"] == [{"id": "G6_MIGRAINE", "reason": "too_few_matched_traits", "matched": 1}]
    spec = model["diseases"][0]
    assert spec["coverage"]["used"] == 3 and spec["coverage"]["features"] == 4
    assert 0 < spec["coverage"]["weight_share"] < 1
    assert len(spec["grid"]) == len(spec["healthy"]["density"]) == disease_risk.GRID_POINTS
    assert spec["patients"]["cohort"] == "T2D" and spec["patients"]["n"] == 80
    # Patients carry the risk-raising pattern, so their scores separate from healthy adults.
    assert spec["patients"]["auc"] > 0.6
    assert spec["patients"]["quantiles"][50] > spec["healthy"]["quantiles"][50]

    # The stored weight is beta * (-lgP).
    ecoli = next(t for t in spec["terms"] if t["feature"] == "species:escherichia coli")
    assert ecoli["weight"] == pytest.approx(0.30 * 4)

    risky = disease_risk.score_profile(model, {"escherichia coli": 40.0, "bacteroides vulgatus": 60.0})[0]
    typical = disease_risk.score_profile(model, dict(zip(SPECIES, [20, 20, 20, 5, 15, 20])))[0]
    assert risky["percentile_healthy"] > 90 and risky["level"] == "high"
    assert risky["score"] > typical["score"]
    # Raised E. coli (risk) and absent F. prausnitzii (protective) both push the score up.
    drivers = {d["feature"] for d in risky["risk_drivers"]}
    assert {"species:escherichia coli", "species:faecalibacterium prausnitzii"} <= drivers
    assert risky["patients"]["label"] == "2型糖尿病"

    # Manual recomputation of the formula for the risky profile.
    feats = disease_risk.profile_features({"escherichia coli": 40.0, "bacteroides vulgatus": 60.0})
    total = 0.0
    for term in spec["terms"]:
        ref = model["features"][term["feature"]]
        x = feats.get(term["feature"], disease_risk.absent_value(term["feature"]))
        total += term["weight"] * max(-4, min(4, (x - ref["mean"]) / ref["sd"]))
    assert risky["score"] == pytest.approx(total, abs=1e-5)


def test_levels_use_healthy_percentiles():
    assert disease_risk.level_for(95)[0] == "high"
    assert disease_risk.level_for(80)[0] == "medium"
    assert disease_risk.level_for(40)[0] == "low"


def test_shipped_weights_cover_all_finngen_endpoints():
    weights = disease_risk.load_weights()
    assert weights["schema_version"] == "disease-mr-weights-v1"
    assert len(weights["diseases"]) == 102
    for disease in weights["diseases"]:
        assert disease["name_cn"] and disease["system"]
        for trait in disease["traits"]:
            assert trait["p"] < 0.05 and trait["kind"] in {"species", "genus", "alpha"}
            assert trait["neg_lg_p"] == pytest.approx(-math.log10(trait["p"]), rel=1e-4)


def test_analyze_reports_missing_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("WGS_CMD_DISEASE_RISK_DIR", str(tmp_path / "missing"))
    result = disease_risk.analyze("S1", {})
    assert result["audit"]["status"] == "unavailable"
    assert result["audit"]["reason"] in {"bundle_missing", "invalid_target"}


def test_bundle_round_trip(tmp_path, monkeypatch):
    weights = _weights(_disease("T2D", [
        _trait("species", "Escherichia coli", 0.30, 1e-4),
        _trait("species", "Faecalibacterium prausnitzii", -0.20, 1e-3),
        _trait("alpha", "shannon", -0.1, 0.01),
    ]))
    model = disease_risk.train(_cohort(), weights)
    payload = json.dumps(model, allow_nan=False).encode()
    import hashlib
    (tmp_path / "models.json").write_bytes(payload)
    (tmp_path / "manifest.json").write_text(json.dumps({
        "schema_version": disease_risk.VERSION, "files": {"models.json": hashlib.sha256(payload).hexdigest()}}))
    manifest, loaded, _ = disease_risk.load_bundle(tmp_path)
    assert loaded["diseases"][0]["id"] == "T2D"


def test_build_script_writes_verified_bundle(tmp_path, monkeypatch):
    import csv
    import importlib.util
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    spec = importlib.util.spec_from_file_location("prepare_cmd_disease_risk", root / "scripts/prepare_cmd_disease_risk.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    cohort = _cohort(n_healthy=120, n_t2d=40)
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
    weights.write_text(json.dumps(_weights(_disease("T2D", [
        _trait("species", "Escherichia coli", 0.30, 1e-4),
        _trait("species", "Faecalibacterium prausnitzii", -0.20, 1e-3),
        _trait("alpha", "shannon", -0.1, 0.01),
    ]))))
    out = tmp_path / "bundle"
    result = script.build(package, metadata, tmp_path / "catalog", tmp_path / "src", out, weights_path=weights)
    assert result["status"] == "built" and result["n_healthy"] == 120 and result["n_diseases"] == 1
    assert result["patients"]["T2D"]["n"] == 40
    manifest, model, _ = disease_risk.load_bundle(out)
    assert manifest["weights_sha256"] and model["diseases"][0]["patients"]["cohort"] == "T2D"
    assert script.build(package, metadata, tmp_path / "catalog", tmp_path / "src", out,
                        weights_path=weights)["status"] == "already_built"
