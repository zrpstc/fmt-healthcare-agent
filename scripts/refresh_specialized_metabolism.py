"""Backfill specialist metabolism from existing HUMAnN output; preserve unrelated analyses."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "var/bioinformatics")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "var/results")
    parser.add_argument("--mapping-dir", type=Path, default=ROOT / "fmt-databases/humann3/utility_mapping")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    from wgs_agent.pipeline.specialized_metabolism import run_sample, analyze_profile, merge_specialized_inputs
    from wgs_agent.pipeline.strain_virulence import sample_name, atomic_json
    from wgs_agent.pipeline.sample_registry import sample_lock, require_active
    from wgs_agent.reporting.report_lock import report_lock
    sid = sample_name(args.sample_id)
    with sample_lock(sid):
        require_active(sid)
        with report_lock(args.results_dir, sid):
            analysis = args.results_dir / f"{sid}_analysis.json"
            original = analysis.read_bytes() if analysis.is_file() else None
            data = json.loads(original) if original else {}
            if data.get("sample_id") not in (None, sid):
                raise ValueError("SAMPLE_MISMATCH")
            if args.check:
                choices = [(args.output_root / "profiles/humann" / f"{sid}_genefamilies_relab.tsv", "relative_abundance"),
                           (args.output_root / "profiles/humann" / f"{sid}_genefamilies.tsv", "RPK")]
                source, unit = next((p, u) for p, u in choices if p.is_file())
                value = analyze_profile(sid, source, args.mapping_dir, unit)
            else:
                value = run_sample(sid, args.output_root, args.mapping_dir, force=args.force)
            if not args.check and original and value["status"] in {"completed", "partial"}:
                updated = {**data, **merge_specialized_inputs({"specialized_metabolism": value}, data)}
                if updated != data:
                    if analysis.read_bytes() != original:
                        raise RuntimeError("CONCURRENT_ANALYSIS_UPDATE")
                    backup = args.results_dir / (".specialized-backup-" + sid + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
                    backup.mkdir(mode=0o700)
                    shutil.copy2(analysis, backup / analysis.name)
                    os.chmod(backup / analysis.name, 0o600)
                    atomic_json(analysis, updated)
    print(json.dumps({k: value[k] for k in ["sample_id", "status", "reason_code", "summary", "input_audit"] if k in value}, ensure_ascii=False))
    return 0 if value["status"] in {"completed", "partial"} else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, StopIteration) as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        raise SystemExit(2)
