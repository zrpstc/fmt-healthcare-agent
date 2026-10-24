"""Prepare and download an explicit pilot batch of healthy-labelled ENA WGS runs.

Selection is a metadata screen, not final cohort approval or sequencing QC.
prepare downloads only a small ENA index. download must be invoked separately.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRECTORY = ROOT / "var/reference-sources/healthy-ena-demo"
FIELDS = (
    "run_accession", "study_accession", "sample_accession", "experiment_accession",
    "library_strategy", "library_source", "library_layout", "instrument_platform",
    "fastq_ftp", "fastq_md5", "fastq_bytes",
)


def read_tsv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def tsv_bytes(rows: list[dict], columns: list[str] | tuple[str, ...]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "md5").hexdigest()


def candidate(row: dict, study: str) -> bool:
    try:
        age = float(row.get("age", ""))
    except ValueError:
        return False
    return (
        row.get("study_name") == study
        and row.get("body_site") == "stool"
        and row.get("study_condition") == "control"
        and row.get("disease") == "healthy"
        and math.isfinite(age) and age >= 18
        and row.get("antibiotics_current_use") == "no"
        and row.get("pregnant") != "yes" and row.get("lactating") != "yes"
        and bool(row.get("subject_id")) and bool(row.get("sample_id"))
        and bool(row.get("NCBI_accession"))
    )


def paired_files(row: dict) -> list[dict]:
    run = row["run_accession"]
    if not re.fullmatch(r"(?:ERR|SRR|DRR)\d+", run):
        raise ValueError("Invalid run accession")
    if any(row.get(k) != v for k, v in {
        "library_strategy": "WGS", "library_source": "METAGENOMIC",
        "library_layout": "PAIRED", "instrument_platform": "ILLUMINA",
    }.items()):
        raise ValueError(f"{run}: requires Illumina paired-end metagenomic WGS")
    urls, md5s, sizes = (row[k].split(";") for k in ("fastq_ftp", "fastq_md5", "fastq_bytes"))
    if not len(urls) == len(md5s) == len(sizes) == 2:
        raise ValueError(f"{run}: expected exactly two FASTQ files; review the ENA record")
    files = []
    for url, md5, size in zip(urls, md5s, sizes):
        url = url if "://" in url else "https://" + url
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "ftp.sra.ebi.ac.uk":
            raise ValueError(f"{run}: unexpected FASTQ host or scheme")
        filename = Path(parsed.path).name
        match = re.fullmatch(re.escape(run) + r"_([12])\.fastq\.gz", filename)
        if not match or not re.fullmatch(r"[a-fA-F0-9]{32}", md5) or not size.isdecimal() or int(size) <= 0:
            raise ValueError(f"{run}: invalid paired FASTQ name, checksum or size")
        files.append({"run_accession": run, "mate": "R" + match[1], "url": url,
                      "md5": md5.lower(), "bytes": int(size),
                      "relative_path": f"raw/{run}/{filename}"})
    if {f["mate"] for f in files} != {"R1", "R2"}:
        raise ValueError(f"{run}: both R1 and R2 are required")
    return sorted(files, key=lambda f: f["mate"])


def prepare(args: argparse.Namespace) -> None:
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if not re.fullmatch(r"PRJ(?:EB|NA|DB)\d+", args.ena_project):
        raise ValueError("Use an ENA/NCBI project accession such as PRJEB39223")
    cache = directory / "ena" / f"{args.ena_project}.tsv"
    if not cache.exists():
        query = urllib.parse.urlencode({"accession": args.ena_project, "result": "read_run",
                                       "fields": ",".join(FIELDS), "format": "tsv"})
        with urllib.request.urlopen("https://www.ebi.ac.uk/ena/portal/api/filereport?" + query,
                                    timeout=90) as response:
            payload = response.read()
        records = list(csv.DictReader(io.StringIO(payload.decode("utf-8")), delimiter="\t"))
        if not records or not set(FIELDS).issubset(records[0]):
            raise ValueError("ENA returned an empty or invalid file report")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(payload)
    ena = read_tsv(cache)
    by_run = {r["run_accession"]: r for r in ena}
    if len(by_run) != len(ena):
        raise ValueError("Duplicate run accessions in ENA report")
    source = read_tsv(args.metadata)
    selected, runs, files, groups, people, seen_runs = [], [], [], [], set(), set()
    for row in sorted(source, key=lambda r: (r.get("study_name", ""), r.get("sample_id", ""))):
        if not candidate(row, args.study):
            continue
        person = (row["study_name"], row["subject_id"])
        if person in people:
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", row["sample_id"]):
            raise ValueError("Selected sample has an unsupported sample_id")
        accessions = re.split(r"[;,\s]+", row["NCBI_accession"].strip())
        if not accessions or any(not re.fullmatch(r"(?:ERR|SRR|DRR)\d+", r) for r in accessions):
            raise ValueError(f"{row['sample_id']}: this pilot helper requires explicit run accessions")
        sample_rows = []
        for run in accessions:
            if run not in by_run:
                raise ValueError(f"{run}: not found in project {args.ena_project}")
            if run in seen_runs:
                raise ValueError(f"{run}: assigned to more than one selected metadata row")
            sample_rows.append(by_run[run])
        if len({r["sample_accession"] for r in sample_rows}) != 1:
            raise ValueError(f"{row['sample_id']}: runs refer to different ENA biological samples")
        sample_files = []
        for run_row in sample_rows:
            sample_files.extend({"sample_id": row["sample_id"], **f} for f in paired_files(run_row))
        selected.append({
            "sample_id": row["sample_id"], "subject_id": row["subject_id"],
            "study_id": row["study_name"], "age": row["age"], "sex": row.get("gender", ""),
            "country": row.get("country", ""), "source_runs": ";".join(accessions),
            "health_status": "candidate", "qc_pass": "", "body_site": "stool",
            "review_flags": ";".join(k + "_unknown" for k in ("pregnant", "lactating") if not row.get(k)),
        })
        group_runs = []
        for accession in accessions:
            pair = {f["mate"]: f for f in sample_files if f["run_accession"] == accession}
            group_runs.append({
                "run_accession": accession, "layout": "paired",
                "r1": str(directory / pair["R1"]["relative_path"]),
                "r2": str(directory / pair["R2"]["relative_path"]),
                "bytes": sum(int(f["bytes"]) for f in pair.values()),
            })
        groups.append({
            "sample_id": row["sample_id"], "project": args.ena_project,
            "sample_accession": sample_rows[0]["sample_accession"],
            "subject_id": row["subject_id"], "runs": group_runs,
            "run_count": len(group_runs), "total_bytes": sum(r["bytes"] for r in group_runs),
        })
        people.add(person)
        seen_runs.update(accessions)
        runs.extend(sample_rows)
        files.extend(sample_files)
        if len(selected) >= args.limit:
            break
    if len(selected) != args.limit:
        raise ValueError(f"Only {len(selected)} candidates meet this study/label screen; requested {args.limit}")
    total = sum(f["bytes"] for f in files)
    summary = {
        "study": args.study, "ena_project": args.ena_project,
        "status": "candidate_download_plan_only", "candidate_subjects": len(selected),
        "runs": len(runs), "fastq_files": len(files), "compressed_bytes": total,
        "compressed_GiB": round(total / 1024 ** 3, 2),
        "metadata_sha256": hashlib.sha256(args.metadata.read_bytes()).hexdigest(),
        "ena_report_sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
        "screen": "stool; control; healthy; age>=18; antibiotics_current_use=no; pregnancy/lactation not yes; one sample per study/subject",
        "limitations": "Original study eligibility review and sequencing QC are pending. This is not an activated healthy reference.",
    }
    artifacts = {
        "selected_samples.tsv": tsv_bytes(selected, list(selected[0])),
        "ena_runs.tsv": tsv_bytes(runs, FIELDS),
        "download_manifest.tsv": tsv_bytes(files, list(files[0])),
        "checksums.md5": "".join(f"{f['md5']}  {f['relative_path']}\n" for f in files).encode(),
        "selection.json": (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode(),
    }
    processing = []
    for group in groups:
        name = "groups/" + group["sample_id"] + ".json"
        artifacts[name] = (json.dumps(group, ensure_ascii=False, indent=2) + "\n").encode()
        processing.append({"sample_id": group["sample_id"], "project": args.ena_project,
                           "group_file": str(directory / name),
                           "run_count": group["run_count"], "total_bytes": group["total_bytes"]})
    artifacts["processing_manifest.tsv"] = tsv_bytes(processing, list(processing[0]))
    for name, payload in artifacts.items():
        target = directory / name
        if target.exists() and target.read_bytes() != payload:
            raise ValueError(f"Existing plan differs: {target}; choose a new --directory")
    for name, payload in artifacts.items():
        target = directory / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Plan ready; FASTQ files have not been downloaded.")


def planned_files(directory: Path, count: int) -> tuple[list[dict], list[str]]:
    rows = read_tsv(directory / "download_manifest.tsv")
    runs = list(dict.fromkeys(r["run_accession"] for r in rows))
    if count > len(runs):
        raise ValueError(f"The plan contains {len(runs)} runs, fewer than requested {count}")
    runs = runs[:count]
    result = [r for r in rows if r["run_accession"] in runs]
    if len({r["relative_path"] for r in result}) != len(result):
        raise ValueError("Duplicate FASTQ destinations in manifest")
    for row in result:
        run = row["run_accession"]
        relative = row["relative_path"]
        if not re.fullmatch(r"(?:ERR|SRR|DRR)\d+", run) or relative not in {
            f"raw/{run}/{run}_1.fastq.gz", f"raw/{run}/{run}_2.fastq.gz"
        } or not (directory / relative).resolve().is_relative_to(directory.resolve()):
            raise ValueError("Unsafe destination in download manifest")
        url = urllib.parse.urlsplit(row["url"])
        if url.scheme != "https" or url.hostname != "ftp.sra.ebi.ac.uk":
            raise ValueError("Unexpected download host")
        if not re.fullmatch(r"[a-f0-9]{32}", row["md5"]) or int(row["bytes"]) <= 0:
            raise ValueError("Invalid checksum or size in manifest")
    for run in runs:
        if {r["relative_path"] for r in result if r["run_accession"] == run} != {
            f"raw/{run}/{run}_1.fastq.gz", f"raw/{run}/{run}_2.fastq.gz"
        }:
            raise ValueError(f"{run}: incomplete R1/R2 pair in manifest")
    return result, runs


def verify_file(path: Path, row: dict) -> bool:
    return path.is_file() and path.stat().st_size == int(row["bytes"]) and checksum(path) == row["md5"]


def transfer(args: argparse.Namespace) -> None:
    directory = args.directory.resolve()
    rows, runs = planned_files(directory, args.runs)
    if args.action == "download" and not shutil.which("curl"):
        raise ValueError("curl is required")
    # Only the downloader mutates FASTQ files. The OS releases this lock on exit.
    with (directory / ".download.lock").open("a+") as lock:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for row in rows:
            path = directory / row["relative_path"]
            if args.action == "verify":
                continue
            if path.exists():
                if not verify_file(path, row):
                    raise ValueError(f"Existing file fails size/MD5 checks; preserved: {path}")
                print("Verified existing:", path.name, flush=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_name(path.name + ".part")
            have = partial.stat().st_size if partial.exists() else 0
            if have > int(row["bytes"]):
                raise ValueError(f"Partial file exceeds expected size; preserved: {partial}")
            if shutil.disk_usage(directory).free < int(row["bytes"]) - have:
                raise ValueError("Insufficient free space for the next compressed FASTQ")
            if have < int(row["bytes"]):
                print("Downloading:", row["url"], "->", path, flush=True)
                subprocess.run(["curl", "--fail", "--location", "--retry", "3",
                                "--retry-delay", "3", "--connect-timeout", "30",
                                "--continue-at", "-", "--output", str(partial), row["url"]], check=True)
            if not verify_file(partial, row):
                raise ValueError(f"Downloaded file fails size/MD5 checks; preserved: {partial}")
            partial.replace(path)
        results = []
        for row in rows:
            path = directory / row["relative_path"]
            state = "verified" if verify_file(path, row) else "invalid" if path.exists() else "missing"
            print(state.upper(), row["relative_path"], flush=True)
            results.append({"run_accession": row["run_accession"], "relative_path": row["relative_path"],
                            "status": state})
        status = directory / "download_status.tsv"
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
            stream.write(tsv_bytes(results, ("run_accession", "relative_path", "status")))
            temporary = Path(stream.name)
        temporary.replace(status)
        if any(r["status"] != "verified" for r in results):
            raise ValueError("Requested files are incomplete or invalid; see download_status.tsv")
    print(f"Verified {len(rows)} FASTQ files for the requested {len(runs)} run(s). This is not sequencing QC.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    preparation = commands.add_parser("prepare", help="Select candidates and fetch only the small ENA index")
    preparation.add_argument("--metadata", type=Path, default=ROOT / "var/reference-sources/cmd/sample_metadata.tsv")
    preparation.add_argument("--study", required=True)
    preparation.add_argument("--ena-project", required=True)
    preparation.add_argument("--limit", type=int, default=50)
    preparation.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    for action in ("download", "verify"):
        command = commands.add_parser(action)
        command.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
        command.add_argument("--runs", type=int, default=1, help="Operate on the first N runs in the prepared plan")
    args = parser.parse_args()
    if getattr(args, "limit", 1) < 1 or getattr(args, "runs", 1) < 1:
        parser.error("Counts must be positive")
    try:
        prepare(args) if args.action == "prepare" else transfer(args)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"ENA preparation/download failed: {error}\n")


if __name__ == "__main__":
    main()
