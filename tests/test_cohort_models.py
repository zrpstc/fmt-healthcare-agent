"""Synthetic cohorts exercise cMD cohort-model training and the offline runtime."""
import hashlib
import json

import numpy as np
import pytest

from wgs_agent.reporting import cmd, cohort_insights
from wgs_agent.reporting.cohort_models import MODEL_VERSION, Cohort, train_all

GENERA = {
    "bacteroides": ["bacteroides vulgatus", "bacteroides uniformis"],
    "prevotella": ["prevotella copri"],
    "faecalibacterium": ["faecalibacterium prausnitzii"],
    "ruminococcus": ["ruminococcus bromii"],
    "bifidobacterium": ["bifidobacterium longum"],
    "akkermansia": ["akkermansia muciniphila"],
    "fusobacterium": ["fusobacterium nucleatum"],
    "parvimonas": ["parvimonas micra"],
    "roseburia": ["roseburia hominis"],
    "eubacterium": ["eubacterium rectale"],
}
SPECIES = [s for names in GENERA.values() for s in names]
GENUS_OF = {s: g for g, names in GENERA.items() for s in names}


def synthetic_cohort(seed=7):
    rng = np.random.default_rng(seed)
    rows, labels = [], []
    studies = ["S1", "S2", "S3", "S4"]
    for i in range(480):
        study = studies[i % 4]
        age = float(rng.uniform(20, 80))
        kind = i % 3
        base = rng.gamma(1.0, 1.0, len(SPECIES))
        idx = {s: j for j, s in enumerate(SPECIES)}
        if kind == 0:
            base[idx["bacteroides vulgatus"]] += 25; base[idx["bacteroides uniformis"]] += 10
        elif kind == 1:
            base[idx["prevotella copri"]] += 35
        else:
            base[idx["faecalibacterium prausnitzii"]] += 15; base[idx["ruminococcus bromii"]] += 12
        base[idx["akkermansia muciniphila"]] *= (age / 30) ** 2  # increases with age
        base[idx["bifidobacterium longum"]] *= (60 / age) ** 2  # decreases with age
        base[idx["fusobacterium nucleatum"]] = 0 if rng.random() < .8 else base[idx["fusobacterium nucleatum"]] * .1
        base[idx["parvimonas micra"]] = 0 if rng.random() < .85 else base[idx["parvimonas micra"]] * .1
        rows.append(base); labels.append({"sample_id": f"H{i}", "study_id": study, "group": "healthy", "age": str(age)})
    for i in range(150):
        study = ["S1", "S2", "S3"][i % 3]
        base = rng.gamma(1.0, 1.0, len(SPECIES))
        base[SPECIES.index("fusobacterium nucleatum")] += 4
        base[SPECIES.index("parvimonas micra")] += 3
        base[SPECIES.index("roseburia hominis")] *= .2
        rows.append(base); labels.append({"sample_id": f"C{i}", "study_id": study, "group": "CRC", "age": "60"})
    values = np.array(rows)
    values = 100 * values / values.sum(axis=1, keepdims=True)
    return Cohort(species=SPECIES, values=values, genus_of=GENUS_OF, labels=labels)


@pytest.fixture(scope="module")
def models():
    return train_all(synthetic_cohort(), ["CRC", "T2D"])


def test_training_outputs_auditable_models(models):
    assert models["version"] == MODEL_VERSION
    age = models["gut_age"]
    assert age["n_train"] == 480 and age["cv_mae"] < 15 and age["cv_r"] > 0.3
    assert len(age["reference_points"]) == 400
    ids = sorted(c["id"] for c in models["enterotype"]["centroids"])
    assert ids == ["ET-B", "ET-F", "ET-P"]
    assert models["health_index"]["cv_auc"] > 0.7
    assert [d["id"] for d in models["diseases"]] == ["CRC"]  # T2D absent -> skipped
    crc = models["diseases"][0]
    assert crc["control_source"] == "same_studies"
    assert "fusobacterium nucleatum" in [r["species"] for r in crc["enriched"]]
    assert crc["cv_auc"] > 0.7
    assert models["prevalence"]["groups"][0]["id"] == "healthy"
    json.dumps(models, allow_nan=False)  # bundle must be strict JSON


def write_bundle(tmp_path, models):
    base = tmp_path / "cohort"
    base.mkdir()
    payload = json.dumps(models, allow_nan=False).encode()
    (base / "models.json").write_bytes(payload)
    (base / "manifest.json").write_text(json.dumps({
        "schema_version": MODEL_VERSION, "cohort_id": "synthetic", "cohort_version": "t",
        "pipeline": cmd.PIPELINE, "normalization": cmd.NORMALIZATION,
        "n_healthy": 480, "n_disease": 150, "n_studies": 4,
        "files": {"models.json": hashlib.sha256(payload).hexdigest()}}))
    return base


def write_target(tmp_path, sid, abundances, age=None):
    folder = tmp_path / "targets" / sid
    folder.mkdir(parents=True)
    lines = [f"#{cmd.PIPELINE['database_version']}", "#MetaPhlAn version 3.0.14",
             "#clade_name\tNCBI_tax_id\trelative_abundance"]
    for name, value in abundances.items():
        genus = GENUS_OF[name]
        lines.append(f"k__Bacteria|g__{genus.capitalize()}|s__{name.capitalize().replace(' ', '_')}\t1\t{value}")
    raw = ("\n".join(lines) + "\n").encode()
    (folder / "profile.tsv").write_bytes(raw)
    meta = {"age": age} if age is not None else {}
    (folder / "provenance.json").write_text(json.dumps({
        "sample_id": sid, "pipeline": {**cmd.PIPELINE, "profiler_version": "3.0.14"},
        "normalization": cmd.NORMALIZATION, "profile_sha256": cmd.digest(raw), "comparison_metadata": meta}))
    return tmp_path / "targets"


def test_runtime_applies_models(tmp_path, monkeypatch, models):
    base = write_bundle(tmp_path, models)
    profiles = write_target(tmp_path, "T1", {
        "prevotella copri": 45, "faecalibacterium prausnitzii": 10, "bifidobacterium longum": 5,
        "fusobacterium nucleatum": 3, "roseburia hominis": 7, "eubacterium rectale": 30}, age=35)
    monkeypatch.setenv("WGS_CMD_COHORT_DIR", str(base))
    monkeypatch.setenv("WGS_CMD_PROFILES_DIR", str(profiles))
    result = cohort_insights.analyze("T1", {})
    assert result["audit"]["status"] == "available", result["audit"]
    assert result["enterotype"]["id"] == "ET-P"
    assert 0 <= result["enterotype"]["confidence"] <= 1
    age = result["gut_age"]
    assert 18 <= age["predicted_age"] <= 90 and age["chronological_age"] == 35 and age["gap"] is not None
    index = result["health_index"]
    assert 0 <= index["probability_healthy"] <= 1 and 0 <= index["percentile_healthy"] <= 100
    crc = result["diseases"][0]
    assert crc["id"] == "CRC" and crc["position"] in {"near_control", "between", "near_disease"}
    assert any(r["species"] == "fusobacterium nucleatum" for r in crc["enriched_detected"])
    assert "fusobacterium nucleatum" in result["prevalence"]["species"]


def test_runtime_reports_missing_and_tampered_bundle(tmp_path, monkeypatch, models):
    monkeypatch.setenv("WGS_CMD_COHORT_DIR", str(tmp_path / "absent"))
    monkeypatch.setenv("WGS_CMD_PROFILES_DIR", str(tmp_path / "targets"))
    assert cohort_insights.analyze("T1", {})["audit"]["reason"] == "bundle_missing"
    base = write_bundle(tmp_path, models)
    (base / "models.json").write_text("{}")
    monkeypatch.setenv("WGS_CMD_COHORT_DIR", str(base))
    assert cohort_insights.analyze("T1", {})["audit"]["reason"] == "invalid_bundle"


def test_runtime_rejects_incompatible_target(tmp_path, monkeypatch, models):
    base = write_bundle(tmp_path, models)
    profiles = write_target(tmp_path, "T2", {"prevotella copri": 50, "eubacterium rectale": 50})
    provenance = json.loads((profiles / "T2" / "provenance.json").read_text())
    provenance["pipeline"] = {**cmd.PIPELINE, "profiler_version": "4.1"}
    (profiles / "T2" / "provenance.json").write_text(json.dumps(provenance))
    monkeypatch.setenv("WGS_CMD_COHORT_DIR", str(base))
    monkeypatch.setenv("WGS_CMD_PROFILES_DIR", str(profiles))
    assert cohort_insights.analyze("T2", {})["audit"]["reason"] == "incompatible_pipeline"
    assert cohort_insights.analyze("T2", {"qc_status": "failed"})["audit"]["reason"] == "target_qc_failed"


def test_build_script_writes_verified_bundle(tmp_path, monkeypatch):
    import csv
    import importlib.util
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    spec = importlib.util.spec_from_file_location("prepare_cmd_cohort_models", root / "scripts/prepare_cmd_cohort_models.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    cohort = synthetic_cohort(11)
    package = tmp_path / "pkg"; package.mkdir()
    (package / "DESCRIPTION").write_text("Package: curatedMetagenomicData\nVersion: 3.99.0\n")
    meta_rows, by_study = [], {}
    for i, label in enumerate(cohort.labels):
        group = label["group"]
        abx = ["no", "", "NA"][i % 3] if group == "healthy" else "no"
        meta_rows.append({"sample_id": label["sample_id"], "subject_id": "P" + label["sample_id"],
                          "study_name": label["study_id"], "body_site": "stool", "age": label["age"],
                          "disease": "healthy" if group == "healthy" else "CRC",
                          "study_condition": "control" if group == "healthy" else group,
                          "antibiotics_current_use": abx, "days_from_first_collection": "0"})
        by_study.setdefault(label["study_id"], []).append(i)
    meta_rows.append({**meta_rows[0], "sample_id": "abx", "subject_id": "Pabx", "antibiotics_current_use": "yes"})
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
                lineage = f"k__Bacteria|g__{GENUS_OF[name].capitalize()}|s__{name.capitalize().replace(' ', '_')}"
                writer.writerow([lineage, *(cohort.values[i, j] for i in rows)])
        downloaded.append({"study": study, "resource_id": "EH1", "title": f"x.{study}.relative_abundance",
                           "url": "https://example.invalid", "sha256": "0", "bytes": 1, "export": export})
    monkeypatch.setattr(script.reference, "export_matrices", lambda *a, **k: downloaded)
    out = tmp_path / "bundle"
    result = script.build(package, metadata, tmp_path / "catalog", tmp_path / "src", out, diseases=("CRC",))
    assert result["status"] == "built" and result["n_healthy"] == 480 and result["n_disease"] == 150
    manifest, models, _ = cohort_insights.load_bundle(out)
    assert manifest["selection_criteria"]["healthy"]["antibiotics_current_use"] == "no_or_unrecorded"
    assert models["diseases"][0]["id"] == "CRC"
    strict = script.select(meta_rows, "no", {"CRC"})
    assert sum(r["_group"] == "healthy" for r in strict) == 160  # only explicit "no"
    assert script.build(package, metadata, tmp_path / "catalog", tmp_path / "src", out)["status"] == "already_built"
