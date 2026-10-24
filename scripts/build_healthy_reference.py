"""Build a healthy-reference-v1 bundle from completed, versioned MetaPhlAn profiles."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import tempfile
from pathlib import Path

from wgs_agent.reporting.healthy import _profile, _table, _token, load_healthy_reference
from wgs_agent.reporting.inputs import load_existing_report_inputs


def build(manifest_path: Path, metadata_path: Path, profiles_root: Path, output: Path) -> dict:
    manifest_raw, metadata_raw = manifest_path.read_bytes(), metadata_path.read_bytes()
    manifest = json.loads(manifest_raw)
    _, labels = _table(metadata_raw)
    profiles, taxonomy_by_sample = {}, {}
    for label in labels:
        if (_token(label.get("health_status")) != "healthy"
                or _token(label.get("qc_pass")) not in {"true", "1", "pass"}
                or _token(label.get("body_site")) != "stool"):
            continue
        sid = label["sample_id"].strip()
        if sid in profiles:
            raise ValueError("duplicate sample_id")
        taxonomy = load_existing_report_inputs(sid, profiles_root).get("taxonomy", {})
        pipeline = dict(taxonomy.get("pipeline", {}))
        # Older MetaPhlAn TSV headers omit software version. The manifest value
        # must be verified against the original run environment, never inferred
        # from whatever executable happens to be installed today.
        if "profiler_version" not in pipeline:
            pipeline["profiler_version"] = manifest["pipeline"]["profiler_version"]
        if pipeline != manifest["pipeline"]:
            raise ValueError(f"incompatible profile pipeline: {sid}")
        rows = taxonomy.get("ranks", {}).get("species", [])
        profile = _profile(rows, taxonomy.get("unit", "%")) if taxonomy.get("complete") else {}
        if not profile:
            raise ValueError(f"missing or invalid complete profile: {sid}")
        profiles[sid], taxonomy_by_sample[sid] = profile, {**taxonomy, "pipeline": pipeline}
    if not profiles:
        raise ValueError("no eligible healthy stool profiles")
    features = sorted({key for profile in profiles.values() for key in profile})
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    writer.writerow(["sample_id", *features])
    for sid, profile in sorted(profiles.items()):
        writer.writerow([sid, *(profile.get(key, 0) for key in features)])
    if output.exists():
        raise ValueError("output already exists; build a new version directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".healthy-build-", dir=output.parent) as directory:
        staging = Path(directory) / "bundle"
        staging.mkdir(mode=0o700)
        (staging / "manifest.json").write_bytes(manifest_raw)
        (staging / "metadata.tsv").write_bytes(metadata_raw)
        (staging / "species_abundance.tsv").write_text(stream.getvalue(), encoding="utf-8")
        original_env = os.environ.get("WGS_HEALTHY_REFERENCE_DIR")
        os.environ["WGS_HEALTHY_REFERENCE_DIR"] = str(staging.resolve())
        try:
            # A synthetic external identity only validates the bundle. It is
            # never written as a sample or used in a report.
            first = next(iter(profiles))
            taxonomy = taxonomy_by_sample[first]
            demographics = next(r for r in labels if r["sample_id"].strip() == first)
            target = {k: demographics.get(k) for k in ("age", "sex", "country")}
            _, _, audit = load_healthy_reference(
                "__BUNDLE_VALIDATION_ONLY__", taxonomy["ranks"]["species"], taxonomy, target,
                complete=True,
            )
        finally:
            if original_env is None:
                os.environ.pop("WGS_HEALTHY_REFERENCE_DIR", None)
            else:
                os.environ["WGS_HEALTHY_REFERENCE_DIR"] = original_env
        if audit["status"] != "available":
            raise ValueError(audit["reason_cn"])
        for path in staging.iterdir():
            path.chmod(0o600)
        # Build elsewhere, then atomically publish the complete new directory.
        staging.rename(output)
    return {k: audit[k] for k in ("cohort_id", "cohort_version", "n_subjects", "file_sha256")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--profiles-root", type=Path, required=True,
                        help="Root containing profiles/metaphlan/{sample_id}_profile.tsv")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        audit = build(args.manifest, args.metadata, args.profiles_root, args.output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Healthy reference build failed: {error}\n")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
