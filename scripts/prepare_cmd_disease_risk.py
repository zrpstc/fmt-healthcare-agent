"""Build the MR disease-risk reference bundle on the cMD adult cohorts.

Same inputs and download cache as ``prepare_cmd_cohort_models.py``.  For every
FinnGen endpoint in ``knowledge_base/disease_mr/disease_mr_weights.json`` it
standardises the MR traits on the cMD healthy adults and stores the score
distribution of those healthy adults (and of a matching cMD patient cohort,
where one exists).  Writes an immutable bundle:

    <output>/manifest.json   provenance, weights hash, counts, coverage
    <output>/models.json     feature means/sds, per-disease terms and distributions

Point ``WGS_CMD_DISEASE_RISK_DIR`` at the output, or let ``prepare_cmd_data.py``
build it below ``WGS_CMD_DATA_ROOT``.  Report rendering only reads it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from wgs_agent.reporting import cmd, disease_risk  # noqa: E402
from wgs_agent.reporting.cohort_models import DISEASES  # noqa: E402
import prepare_cmd_cohort_models as cohort_script  # noqa: E402
import prepare_cmd_reference as reference  # noqa: E402


def build(package, metadata, catalog, source_dir, output, r_library=None, *,
          antibiotics_policy="no_or_unrecorded", weights_path: Path = disease_risk.WEIGHTS_PATH):
    if output.exists():
        manifest = json.loads((output / "manifest.json").read_text())
        return {"status": "already_built", "output": str(output), "weights_sha256": manifest.get("weights_sha256")}
    weights_bytes = Path(weights_path).read_bytes()
    weights = json.loads(weights_bytes)
    cohort, downloaded, species = cohort_script.load_cohort(
        package, metadata, catalog, source_dir, r_library,
        antibiotics_policy=antibiotics_policy, diseases=tuple(DISEASES))
    model = disease_risk.train(cohort, weights)
    counts: dict[str, int] = {}
    for row in cohort.labels:
        counts[row["group"]] = counts.get(row["group"], 0) + 1
    version = next(line.split(":", 1)[1].strip() for line in (package / "DESCRIPTION").read_text().splitlines()
                   if line.startswith("Version:"))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cmd-disease-risk-", dir=output.parent) as directory:
        stage = Path(directory) / "bundle"
        stage.mkdir(mode=0o750)
        payload = json.dumps(model, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        (stage / "models.json").write_bytes(payload)
        manifest = {
            "schema_version": disease_risk.VERSION,
            "cohort_id": "curatedMetagenomicData-adult-stool-cohorts",
            "cohort_version": "package-" + version + "-" + hashlib.sha256(metadata.read_bytes()).hexdigest()[:12],
            "source_package_version": version,
            "pipeline": cmd.PIPELINE, "normalization": cmd.NORMALIZATION, "unit": "%",
            "antibiotics_policy": antibiotics_policy,
            "weights_file": str(Path(weights_path).relative_to(ROOT)) if Path(weights_path).is_relative_to(ROOT) else str(weights_path),
            "weights_sha256": hashlib.sha256(weights_bytes).hexdigest(),
            "weights_source": weights.get("source"),
            "n_healthy": counts.get("healthy", 0), "group_counts": counts, "n_species": len(species),
            "n_diseases": len(model["diseases"]), "skipped": model["skipped"],
            "coverage": {d["id"]: d["coverage"] for d in model["diseases"]},
            "patients": {d["id"]: {k: d["patients"][k] for k in ("cohort", "n", "auc")}
                         for d in model["diseases"] if d["patients"]},
            "source_resources": [{k: r[k] for k in ("study", "resource_id", "sha256")} for r in downloaded],
            "files": {"models.json": hashlib.sha256(payload).hexdigest()},
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        for f in stage.iterdir():
            f.chmod(0o640)
        stage.rename(output)
    return {"status": "built", "output": str(output), "n_healthy": manifest["n_healthy"],
            "n_diseases": manifest["n_diseases"], "skipped": len(manifest["skipped"]), "patients": manifest["patients"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--r-library", type=Path)
    parser.add_argument("--antibiotics-policy", choices=sorted(reference.ANTIBIOTICS_POLICIES), default="no_or_unrecorded")
    parser.add_argument("--weights", type=Path, default=disease_risk.WEIGHTS_PATH)
    args = parser.parse_args()
    result = build(args.package_dir, args.metadata, args.catalog, args.source_dir, args.output, args.r_library,
                   antibiotics_policy=args.antibiotics_policy, weights_path=args.weights)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
