"""Backfill literature disease features into an existing analysis; no sequencing rerun."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "var/results")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    from wgs_agent.pipeline.strain_virulence import sample_name, atomic_json
    from wgs_agent.pipeline.disease_features import analyze_disease_features, merge_disease_features
    from wgs_agent.reporting.report_lock import report_lock
    sample_name(args.sample_id)
    target = args.results_dir / f"{args.sample_id}_analysis.json"
    with report_lock(args.results_dir, args.sample_id):
        original = target.read_bytes()
        data = json.loads(original)
        if data.get("sample_id") not in (None, args.sample_id):
            raise ValueError("SAMPLE_MISMATCH")
        generated = analyze_disease_features(data.get("taxonomy"))
        updated = {**data, **merge_disease_features(generated, data)}
        if not args.check and updated != data:
            if target.read_bytes() != original:
                raise RuntimeError("CONCURRENT_ANALYSIS_UPDATE")
            from datetime import datetime, timezone
            import os
            import shutil
            backup = args.results_dir / (".disease-backup-" + args.sample_id + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
            backup.mkdir(mode=0o700)
            shutil.copy2(target, backup / target.name)
            os.chmod(backup / target.name, 0o600)
            atomic_json(target, updated)
    module = updated["diseases"]
    print(json.dumps({"sample_id": args.sample_id, "status": module.get("status"),
                      "reason_code": module.get("reason_code"), "check_only": args.check,
                      "module_count": len(module.get("diseases", [])),
                      "matched_species": {r["id"]: r.get("matched_species") for r in module.get("diseases", [])},
                      "models_enabled": False}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        raise SystemExit(1)
