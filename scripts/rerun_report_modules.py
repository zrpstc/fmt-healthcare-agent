"""Supplement report analyses from existing dehosted reads and HUMAnN files.

Does not upload reads, repeat QC/dehosting/HUMAnN, call models, or write reports.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def preflight(sid, output, results, db, tax):
    from wgs_agent.pipeline.strain_virulence import sample_name
    sample_name(sid)
    expected = {
        "dehosted_reads": output / "clean_merged" / f"{sid}.dehosted.fastq.gz",
        "taxonomy": output / "profiles/metaphlan" / f"{sid}_profile.tsv",
        "gene_families": output / "profiles/humann" / f"{sid}_genefamilies_relab.tsv",
        "vfdb": db / "vfdb/VFDB_setA_nt.fas.gz",
        "ec_names": db / "humann3/utility_mapping/map_ec_name.txt.gz",
        "ec_mapping": db / "humann3/utility_mapping/map_level4ec_uniref90.txt.gz",
    }
    try:
        if not expected["gene_families"].is_file():
            expected["gene_families"] = output / "profiles/humann" / f"{sid}_genefamilies.tsv"
    except OSError:
        pass
    checks = {}
    for key, path in expected.items():
        try:
            checks[key] = path.is_file() and os.access(path, os.R_OK)
        except OSError:
            checks[key] = False
    for name in ("metaphlan", "sample2markers.py", "samtools", "bowtie2", "bowtie2-build"):
        checks["tool_" + name] = os.access(tax / name, os.X_OK)
    for name, path in (("output_writable", output), ("results_writable", results)):
        checks[name] = path.is_dir() and os.access(path, os.W_OK | os.X_OK)
    marker = db / "metaphlan4/mpa_vJan25_CHOCOPhlAnSGB_202503.pkl"
    checks["marker_database"] = marker.is_file() and os.access(marker, os.R_OK)
    analysis = results / f"{sid}_analysis.json"
    try:
        checks["analysis_readable"] = not analysis.is_file() or os.access(analysis, os.R_OK)
    except OSError:
        checks["analysis_readable"] = False
    return {"sample_id": sid, "ready": all(checks.values()), "checks": checks}


def run(sid, output, results, db, tax, threads):
    from wgs_agent.pipeline.sample_registry import sample_lock, require_active
    from wgs_agent.pipeline.strain_virulence import settings_from_env, run_sample
    from wgs_agent.pipeline.resistome_mge import run_module
    from wgs_agent.pipeline.non_bacterial import main as non_bacterial, load_chapter6_inputs
    from wgs_agent.pipeline.functional_annotations import run_sample as annotate
    from wgs_agent.reporting.module_refresh import refresh_analysis_inputs
    from wgs_agent.reporting.report_lock import report_lock
    with sample_lock(sid):
        require_active(sid)
        # Refuse before running any node if another report currently owns the lock.
        with report_lock(results, sid):
            pass
        settings = settings_from_env(output, sid, db_root=db, env_bin=tax, threads=threads)
        four = run_sample(settings)
        five = {module: run_module(output, sid, settings["reads"], db / "resistome_mge", tax,
                                  module, threads=threads) for module in ("resistance", "mobile_elements")}
        six_exit = non_bacterial(["--sample-id", sid, "--output-root", str(output), "--ensure-viral",
            "--metaphlan", str(tax / "metaphlan"), "--db-dir", str(db / "metaphlan4"),
            "--index", "mpa_vJan25_CHOCOPhlAnSGB_202503", "--threads", str(threads)])
        six = load_chapter6_inputs(sid, output)
        functional = annotate(sid, output, db / "humann3/utility_mapping")
        analysis = results / f"{sid}_analysis.json"
        if analysis.is_file():
            # Snapshot the original analysis without changing existing reports.
            with report_lock(results, sid):
                backup = results / (".module-rerun-backup-" + sid + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
                backup.mkdir(mode=0o700)
                shutil.copy2(analysis, backup / analysis.name)
                os.chmod(backup / analysis.name, 0o600)
            refresh_analysis_inputs(analysis, sid, output)
        states = {k: {n: v[n] for n in ("status", "reason_code") if n in v}
                  for k, v in {**four, **five, **six, "functional_modules": functional}.items()}
        ok = (all(v["status"] in {"completed", "insufficient_coverage"} for v in four.values())
              and all(v["status"] == "completed" for v in five.values()) and six_exit == 0
              and all(v.get("complete") for v in six.values()) and functional["status"] == "completed")
        return {"sample_id": sid, "status": "completed" if ok else "incomplete", "modules": states,
                "reports_regenerated": False, "base_pipeline_rerun": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-id", action="append", required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "var/bioinformatics")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "var/results")
    parser.add_argument("--database-root", type=Path, default=ROOT / "fmt-databases")
    parser.add_argument("--tax-bin", type=Path, default=ROOT / "var/runtime/envs/fmt-tax/bin")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        checks = [preflight(sid, args.output_root, args.results_dir, args.database_root, args.tax_bin)
                  for sid in args.sample_id]
        if args.check or not all(x["ready"] for x in checks):
            print(json.dumps({"preflight": checks}, ensure_ascii=False))
            return 0 if all(x["ready"] for x in checks) else 2
        outcomes = []
        for sid in args.sample_id:
            value = run(sid, args.output_root, args.results_dir, args.database_root, args.tax_bin,
                        max(1, min(args.threads, 32)))
            outcomes.append(value)
            if value["status"] != "completed":
                break
        print(json.dumps({"samples": outcomes}, ensure_ascii=False))
        return 0 if all(x["status"] == "completed" for x in outcomes) else 2
    except BlockingIOError:
        print(json.dumps({"status": "blocked", "reason_code": "SAMPLE_OR_REPORT_BUSY"}))
        return 2
    except PermissionError:
        print(json.dumps({"status": "blocked", "reason_code": "SERVICE_OWNER_PERMISSION_REQUIRED"}))
        return 2
    except (OSError, ValueError):
        print(json.dumps({"status": "failed", "reason_code": "MODULE_RERUN_FAILED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
