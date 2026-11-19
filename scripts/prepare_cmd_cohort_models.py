"""Build the cMD cohort-model bundle: gut age, enterotype, health index and disease references.

Uses the same official curatedMetagenomicData inputs as ``prepare_cmd_reference.py``
(package source, exported sample metadata, ExperimentHub catalog) and the same
download/export cache (``--source-dir``).  Writes an immutable bundle:

    <output>/manifest.json   provenance, selection, counts, model metrics, sha256
    <output>/models.json     linear coefficients, centroids, quantiles (plain JSON)

Point ``WGS_CMD_COHORT_DIR`` at the output.  Report rendering only reads it.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from wgs_agent.reporting import cmd  # noqa: E402
from wgs_agent.reporting.cohort_models import DISEASES, MODEL_VERSION, Cohort, train_all  # noqa: E402
from wgs_agent.reporting.population_reference import species_key  # noqa: E402
import prepare_cmd_reference as reference  # noqa: E402


def select(rows, antibiotics_policy, diseases):
    """Earliest valid record per (study, subject, group); adults, stool only."""
    chosen = {}

    def priority(row):
        try:
            days = float(row.get("days_from_first_collection", ""))
            days = days if math.isfinite(days) else math.inf
        except ValueError:
            days = math.inf
        return days, row["sample_id"]

    for row in sorted(rows, key=priority):
        if not reference.adult_stool(row):
            continue
        if reference.eligible(row, antibiotics_policy):
            group = "healthy"
        elif row.get("disease") != "healthy" and row.get("study_condition") in diseases:
            group = row["study_condition"]
        else:
            continue
        key = (row["study_name"], row["subject_id"], group)
        chosen.setdefault(key, {**row, "_group": group})
    return list(chosen.values())


def read_matrices(downloaded, wanted):
    """Return {(study, sample_id): {species: value}} and species -> genus."""
    profiles, genus_of = {}, {}
    by_study = {}
    for row in wanted:
        by_study.setdefault(row["study_name"], set()).add(row["sample_id"])
    for resource in downloaded:
        ids = by_study.get(resource["study"], set())
        if not ids:
            continue
        with resource["export"].open() as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            ids = ids & set(reader.fieldnames or [])
            data = {sid: {} for sid in ids}
            for line in reader:
                lineage = line["taxonomy"]
                key = species_key(lineage)
                genus = next((p[3:] for p in lineage.split("|") if p.startswith("g__")), "")
                genus_of.setdefault(key, genus.replace("_", " ").casefold())
                for sid in ids:
                    if key in data[sid]:
                        raise ValueError("duplicate reference species")
                    data[sid][key] = float(line[sid])
        for sid, values in data.items():
            try:
                normalized, _ = cmd.normalize(values)
            except ValueError:
                continue
            profiles[(resource["study"], sid)] = normalized
    return profiles, genus_of


def load_cohort(package, metadata, catalog, source_dir, r_library=None, *,
                antibiotics_policy="no_or_unrecorded", diseases=tuple(DISEASES)):
    """Selected adults as a Cohort, plus the downloaded resources (shared with disease-risk)."""
    with metadata.open() as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    selected = select(rows, antibiotics_policy, set(diseases))
    if not selected:
        raise ValueError("no eligible subjects")
    downloaded = reference.export_matrices(package, catalog, source_dir,
                                           {r["study_name"] for r in selected}, r_library)
    profiles, genus_of = read_matrices(downloaded, selected)
    selected = [r for r in selected if (r["study_name"], r["sample_id"]) in profiles]
    # A subject can appear as both control and case only by mislabelling; keep cases.
    cases = {(r["study_name"], r["subject_id"]) for r in selected if r["_group"] != "healthy"}
    selected = [r for r in selected if r["_group"] != "healthy" or (r["study_name"], r["subject_id"]) not in cases]
    species = sorted({k for r in selected for k, v in profiles[(r["study_name"], r["sample_id"])].items() if v > 0})
    index = {k: i for i, k in enumerate(species)}
    values = np.zeros((len(selected), len(species)))
    for i, r in enumerate(selected):
        for k, v in profiles[(r["study_name"], r["sample_id"])].items():
            if v > 0:
                values[i, index[k]] = v
    labels = [{"sample_id": r["study_name"] + "::" + r["sample_id"], "study_id": r["study_name"],
               "subject_id": r["subject_id"], "group": r["_group"], "age": r.get("age", "")} for r in selected]
    cohort = Cohort(species=species, values=values, genus_of=genus_of, labels=labels)
    return cohort, downloaded, species


def build(package, metadata, catalog, source_dir, output, r_library=None, *,
          antibiotics_policy="no_or_unrecorded", diseases=tuple(DISEASES)):
    if output.exists():
        manifest = json.loads((output / "manifest.json").read_text())
        return {"status": "already_built", "output": str(output), "cohort_version": manifest.get("cohort_version")}
    cohort, downloaded, species = load_cohort(package, metadata, catalog, source_dir, r_library,
                                              antibiotics_policy=antibiotics_policy, diseases=diseases)
    labels = cohort.labels
    models = train_all(cohort, list(diseases))
    counts = {}
    for row in labels:
        counts[row["group"]] = counts.get(row["group"], 0) + 1
    version = next(line.split(":", 1)[1].strip() for line in (package / "DESCRIPTION").read_text().splitlines()
                   if line.startswith("Version:"))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cmd-cohort-", dir=output.parent) as directory:
        stage = Path(directory) / "bundle"
        stage.mkdir(mode=0o750)
        payload = json.dumps(models, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        (stage / "models.json").write_bytes(payload)
        manifest = {
            "schema_version": MODEL_VERSION,
            "cohort_id": "curatedMetagenomicData-adult-stool-cohorts",
            "cohort_version": "package-" + version + "-" + hashlib.sha256(metadata.read_bytes()).hexdigest()[:12],
            "source_package": "curatedMetagenomicData", "source_package_version": version,
            "source_url": "https://github.com/waldronlab/curatedMetagenomicData",
            "pipeline": cmd.PIPELINE, "normalization": cmd.NORMALIZATION, "unit": "%",
            "selection_criteria": {"minimum_age": 18, "body_site": "stool",
                                   "healthy": {"disease": "healthy", "study_condition": "control",
                                               "antibiotics_current_use": antibiotics_policy},
                                   "diseases": list(diseases), "deduplicate_by": ["study_id", "subject_id", "group"],
                                   "repeat_selection": "earliest valid profile then sample_id",
                                   "exclude_known_pregnant_or_lactating": True},
            "n_healthy": counts.get("healthy", 0), "n_disease": sum(v for k, v in counts.items() if k != "healthy"),
            "group_counts": counts, "n_studies": len({r["study_id"] for r in labels}), "n_species": len(species),
            "metrics": {
                "gut_age": {k: models["gut_age"][k] for k in ("cv_mae", "cv_r", "cv_method", "n_train", "n_studies")},
                "enterotype": {"n_train": models["enterotype"]["n_train"],
                               "clusters": {c["id"]: c["n"] for c in models["enterotype"]["centroids"]}},
                "health_index": {k: models["health_index"][k] for k in ("cv_auc", "cv_method", "n_healthy", "n_disease")},
                "diseases": {d["id"]: {"cv_auc": d["cv_auc"], "n_disease": d["n_disease"], "n_control": d["n_control"],
                                       "control_source": d["control_source"]} for d in models["diseases"]},
            },
            "source_resources": [{k: r[k] for k in ("study", "resource_id", "title", "url", "sha256", "bytes")}
                                 for r in downloaded],
            "files": {"models.json": hashlib.sha256(payload).hexdigest()},
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        for f in stage.iterdir():
            f.chmod(0o640)
        stage.rename(output)
    return {"status": "built", "output": str(output), **{k: manifest[k] for k in ("n_healthy", "n_disease", "n_studies")},
            "metrics": manifest["metrics"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--r-library", type=Path)
    parser.add_argument("--antibiotics-policy", choices=sorted(reference.ANTIBIOTICS_POLICIES), default="no_or_unrecorded")
    parser.add_argument("--diseases", nargs="+", default=list(DISEASES), choices=sorted(DISEASES))
    args = parser.parse_args()
    result = build(args.package_dir, args.metadata, args.catalog, args.source_dir, args.output, args.r_library,
                   antibiotics_policy=args.antibiotics_policy, diseases=tuple(args.diseases))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
