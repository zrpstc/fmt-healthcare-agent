"""Export only validated biological identifiers and numeric abundances for workflow development."""
import argparse
from collections import Counter
import grp
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def export_profile(source, target, sid):
    counts = Counter()
    selected = 1
    rows = []
    headers = None
    with source.open(encoding="utf-8-sig") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            if line.startswith("#"):
                parts = line.lstrip("# ").rstrip("\r\n").split("\t")
                if len(parts) > 1 and "gene" in parts[0].casefold():
                    headers = parts
                    candidates = [i for i, name in enumerate(parts[1:], 1) if name == sid or name.startswith(sid + "_") or name.startswith(sid + ".")]
                    if len(parts) > 2:
                        if len(candidates) != 1:
                            return {"status": "blocked", "reason_code": "AMBIGUOUS_SAMPLE_COLUMNS", "column_count": len(parts)}
                        selected = candidates[0]
                continue
            parts = line.rstrip("\r\n").split("\t")
            counts["rows"] += 1
            counts[f"columns_{len(parts)}"] += 1
            if len(parts) < 2 or selected >= len(parts) or (headers and len(parts) != len(headers)):
                return {"status": "blocked", "reason_code": "INVALID_COLUMNS", "line_number": number, "counts": dict(counts)}
            base, sep, taxon = parts[0].partition("|")
            family = base.split(":", 1)[0]
            if family not in {"UNMAPPED", "READS_UNMAPPED", "UNINTEGRATED", "UNGROUPED"} and not re.fullmatch(r"UniRef(?:50|90)_[A-Za-z0-9]+", family):
                return {"status": "blocked", "reason_code": "UNAPPROVED_IDENTIFIER", "line_number": number, "counts": dict(counts)}
            if sep and taxon != "unclassified" and not re.fullmatch(r"(?:[dkpcofgst]__[A-Za-z0-9_.-]+)(?:[.;][dkpcofgst]__[A-Za-z0-9_.-]+)*", taxon):
                return {"status": "blocked", "reason_code": "UNAPPROVED_TAXON_FORMAT", "line_number": number, "counts": dict(counts)}
            try:
                value = float(parts[selected])
            except ValueError:
                return {"status": "blocked", "reason_code": "NONNUMERIC_ABUNDANCE", "line_number": number, "counts": dict(counts)}
            counts["finite_nonnegative"] += int(math.isfinite(value) and value >= 0)
            if sep:
                counts["stratified"] += 1
            rows.append(family + ("|" + taxon if sep else "") + "\t" + parts[selected])
    # Values and identifiers are released only after the entire file passes the allowlist.
    target.write_text("# Gene Family\t" + sid + "_Abundance\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return {"status": "exported", "counts": dict(counts), "selected_column": selected, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument("--owner", default="zhanghaiyang")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", args.sample_id):
        raise ValueError("INVALID_SAMPLE_ID")
    target_root = args.export_dir.resolve()
    if not target_root.is_relative_to((ROOT / "tmp").resolve()):
        raise ValueError("EXPORT_MUST_BE_IN_PROJECT_TMP")
    target_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    output = {}
    for suffix in ["genefamilies_relab.tsv", "genefamilies.tsv"]:
        source = ROOT / "var/bioinformatics/profiles/humann" / f"{args.sample_id}_{suffix}"
        if not source.is_file():
            output[suffix] = {"status": "missing"}
            continue
        target = target_root / source.name
        result = export_profile(source, target, args.sample_id)
        output[suffix] = result
    artifact = ROOT / "var/bioinformatics/profiles/functional_modules" / f"{args.sample_id}.json"
    if artifact.is_file():
        value = json.loads(artifact.read_text())
        output["existing_annotation"] = {k: value.get(k) for k in ["status", "reason_code", "functional_annotation_schema"]}
    manifest = target_root / "preflight.json"
    manifest.write_text(json.dumps({"sample_id": args.sample_id, "inputs": output}, indent=2))
    owner = pwd.getpwnam(args.owner)
    if os.geteuid() == 0:
        for path in target_root.iterdir():
            os.chown(path, owner.pw_uid, owner.pw_gid)
            path.chmod(0o600)
        os.chown(target_root, owner.pw_uid, owner.pw_gid)
        target_root.chmod(0o700)
    print(json.dumps({"status": "completed", "sample_id": args.sample_id, "inputs": output}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        raise SystemExit(1)
