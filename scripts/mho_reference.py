"""Download/build MHOmicrobiome and explicitly prepare isolated target profiles."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from wgs_agent.reporting import mho
from wgs_agent.reporting.reference import species_key

COMMIT = "825084dcc8ebb73efb9f4282a35f15920729eac4"
PAPER = "https://doi.org/10.1038/s41467-026-72588-1"
SOURCES = {
    "whole_cohort_data.csv": (
        f"https://raw.githubusercontent.com/blacruz17/MHOmicrobiome/{COMMIT}/data/whole_cohort_data.csv",
        "5a7bc4b93ad1786ef3cdeac4a23d2bd73c2565115008dc3244a792745302f462"),
    "phenotypes.xlsx": (
        "https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41467-026-72588-1/MediaObjects/41467_2026_72588_MOESM5_ESM.xlsx",
        "ef2948ec098de917142bfcb59c04605495a53f1663c27326e02eb4cdc2aa4b98"),
}


def download(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in SOURCES.items():
        target = directory / name
        if target.exists():
            if mho.digest(target.read_bytes()) != expected:
                raise ValueError(f"Existing source checksum differs: {target}; use a new directory")
            continue
        request = urllib.request.Request(url, headers={"User-Agent": "fmt-healthcare-agent/MHO-reference"})
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read(20_000_001)
        if len(raw) > 20_000_000 or mho.digest(raw) != expected:
            raise ValueError(f"Source size/checksum mismatch: {url}")
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".mho-", delete=False) as handle:
            handle.write(raw)
            staging = Path(handle.name)
        try:
            os.chmod(staging, 0o600)
            # A competing downloader must not replace a different snapshot.
            if target.exists():
                if target.read_bytes() != raw:
                    raise ValueError(f"Destination appeared with different contents: {target}")
            else:
                staging.rename(target)
        finally:
            staging.unlink(missing_ok=True)
    return {"source_dir": str(directory.resolve()), "commit": COMMIT,
            "sha256": {name: value[1] for name, value in SOURCES.items()}}


def read_phenotypes(path: Path) -> list[dict]:
    try:
        import openpyxl
    except ImportError as error:
        raise ValueError("Install openpyxl>=3.1,<4 in the project Python environment") from error

    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(book["SuppData3"].iter_rows(values_only=True))
    finally:
        book.close()
    if tuple(rows[1][:4]) != ("subject_id", "run_accession", "study_name", "phenotype"):
        raise ValueError("Unexpected Supplementary Data 3 header")
    labels = [dict(zip(rows[1], row)) for row in rows[2:] if row[0] is not None]
    for row in labels:
        row["subject_id"] = str(row["subject_id"]).strip()
    return labels


def build(source_dir: Path, output: Path, *, minimum: int = 30,
          matching: list[str] | None = None, age_window: float = 10,
          demographics: Path | None = None) -> dict:
    if output.exists():
        raise ValueError("Output already exists; build a new version directory")
    for name, (_, expected) in SOURCES.items():
        if mho.digest((source_dir / name).read_bytes()) != expected:
            raise ValueError(f"Source checksum mismatch: {name}")
    labels = [row for row in read_phenotypes(source_dir / "phenotypes.xlsx")
              if row["phenotype"] == "MHNO"]
    with (source_dir / "whole_cohort_data.csv").open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream)
        columns = next(reader)
        source_rows = list(reader)
    if columns[0] != "taxa" or len(columns[1:]) != len(set(columns[1:])):
        raise ValueError("Invalid source matrix columns")
    index = {sample: i + 1 for i, sample in enumerate(columns[1:])}
    selected, identities = [], set()
    for label in labels:
        subject = label["subject_id"]
        candidates = [subject] if subject in index else [sample for sample in index
            if label["study_name"] == "AI4Food" and sample.startswith(f"A4F_{subject}_V")]
        identity = (label["study_name"], subject)
        if len(candidates) != 1 or identity in identities:
            raise ValueError("Ambiguous matrix/subject join or duplicate subject")
        identities.add(identity)
        selected.append({"sample_id": candidates[0], "subject_id": subject,
            "study_id": label["study_name"], "phenotype": "MHNO",
            "source_runs": label["run_accession"], "body_site": "stool"})
    if len(selected) != 103:
        raise ValueError("Pinned source must contain exactly 103 MHNO candidates")
    profiles = {row["sample_id"]: {} for row in selected}
    source_clades = set()
    for row in source_rows:
        if len(row) != len(columns) or row[0] in source_clades or not any(
                part.startswith("s__") for part in row[0].split("|")):
            raise ValueError("Invalid or duplicate source feature")
        source_clades.add(row[0])
        key = species_key(row[0])
        for sid, profile in profiles.items():
            value = mho.finite(row[index[sid]])
            if value is None or not 0 <= value <= 100:
                raise ValueError("Invalid source abundance")
            profile[key] = profile.get(key, 0) + value  # Aggregate leaf SGBs to species.
    raw_totals = {}
    for sid in profiles:
        profiles[sid], raw_totals[sid] = mho.normalize(profiles[sid])
    if demographics:
        _, extra = mho.read_table(demographics.read_bytes())
        by_id = {row["sample_id"]: row for row in extra}
        if len(by_id) != len(extra):
            raise ValueError("Duplicate demographics sample_id")
        for label in selected:
            label.update({key: by_id.get(label["sample_id"], {}).get(key, "")
                          for key in ("age", "sex", "country")})
    for label in selected:
        label["raw_species_sum"] = raw_totals[label["sample_id"]]
    features = sorted({key for profile in profiles.values() for key in profile})
    matrix = io.StringIO(newline="")
    writer = csv.writer(matrix, delimiter="\t", lineterminator="\n")
    writer.writerow(["sample_id", *features])
    for label in selected:
        sid = label["sample_id"]
        writer.writerow([sid, *(format(profiles[sid].get(key, 0), ".15g") for key in features)])
    metadata = io.StringIO(newline="")
    writer = csv.DictWriter(metadata, fieldnames=list(selected[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(selected)
    payloads = {"metadata.tsv": metadata.getvalue().encode(),
                "species_abundance.tsv": matrix.getvalue().encode()}
    manifest = {"schema_version": mho.VERSION, "cohort_id": "MHOmicrobiome-MHNO-Jan25",
        "cohort_version": COMMIT, "source_url": PAPER, "source_commit": COMMIT,
        "source_files": {name: {"url": url, "sha256": sha} for name, (url, sha) in SOURCES.items()},
        "pipeline": mho.PIPELINE, "normalization": mho.NORMALIZATION, "unit": "%",
        "feature_level": "species", "complete_species_profiles": True,
        "phenotype": "MHNO", "body_site": "stool", "minimum_subjects": minimum,
        "stratify_by": matching or [], "age_window_years": age_window,
        "source_processing_scope": "as_published; reference read depths not harmonized",
        "qc_scope": "published processed profiles plus local identity/numeric/integrity validation",
        "n_source_sgb_features": len(source_clades), "n_species_features": len(features),
        "raw_species_sum_range": [min(raw_totals.values()), max(raw_totals.values())],
        "files": {name: mho.digest(raw) for name, raw in payloads.items()}}
    payloads["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".mho-build-", dir=output.parent) as directory:
        staging = Path(directory) / "bundle"
        staging.mkdir(mode=0o750)
        for name, raw in payloads.items():
            (staging / name).write_bytes(raw)
            (staging / name).chmod(0o640)
        mho.load_bundle(staging)
        staging.rename(output)
    return {"output": str(output.resolve()), "n_subjects": len(selected),
            "n_species": len(features), "raw_species_sum_range": manifest["raw_species_sum_range"],
            "normalization": mho.NORMALIZATION, "status": "built_not_activated"}


def profile(args: argparse.Namespace) -> dict:
    if not mho.valid_sample_id(args.sample_id) or args.threads < 1:
        raise ValueError("Invalid sample ID or thread count")
    executable = args.metaphlan.resolve(strict=True)
    reads = args.reads.resolve(strict=True)
    database = args.database.resolve(strict=True)
    if not (database / (mho.PIPELINE["database_version"] + ".pkl")).is_file():
        raise ValueError("The exact Jan25 database .pkl is missing")
    environment = dict(os.environ)
    if args.tool_bin:
        environment["PATH"] = str(args.tool_bin.resolve()) + os.pathsep + environment.get("PATH", "")
    version = subprocess.run([str(executable), "--version"], capture_output=True,
                             text=True, check=True, env=environment, timeout=60)
    match = re.search(r"MetaPhlAn(?: version)?\s+(\d+\.\d+\.\d+)", version.stdout + version.stderr, re.I)
    if not match or match[1] != mho.PIPELINE["profiler_version"]:
        raise ValueError("This branch requires actual MetaPhlAn 4.2.2; do not relabel a 4.2.4 profile")
    output = args.profiles_dir.resolve() / args.sample_id
    if output.exists():
        raise ValueError("Target directory exists; use another --profiles-dir for a new run")
    output.parent.mkdir(parents=True, exist_ok=True)
    input_stat = reads.stat()
    with tempfile.TemporaryDirectory(prefix=".mho-profile-", dir=output.parent) as directory:
        staging = Path(directory) / "sample"
        staging.mkdir(mode=0o750)
        target = staging / "profile.tsv"
        command = [str(executable), str(reads), "--input_type", "fastq", "--output_file", str(target),
                   "--db_dir", str(database), "--index", mho.PIPELINE["database_version"],
                   "--nproc", str(args.threads), "--offline", "--mapout", str(staging / "alignment.bz2")]
        with (staging / "run.log").open("w") as log:
            subprocess.run(command, check=True, env=environment, stdout=log, stderr=subprocess.STDOUT)
        raw = target.read_bytes()
        _, recorded = mho.read_target(raw)
        if recorded.get("database_version") != mho.PIPELINE["database_version"] or any(
                mho.PIPELINE.get(key) != value for key, value in recorded.items()):
            raise ValueError("Generated profile headers disagree with the requested pipeline")
        after = reads.stat()
        if (input_stat.st_size, input_stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("Input reads changed during profiling")
        provenance = {"sample_id": args.sample_id, "pipeline": mho.PIPELINE,
            "normalization": mho.NORMALIZATION, "profile_sha256": mho.digest(raw),
            "software_version_output": (version.stdout + version.stderr).strip(),
            "executable": str(executable), "database_dir": str(database),
            "reads": str(reads), "reads_bytes": input_stat.st_size,
            "reads_mtime_ns": input_stat.st_mtime_ns, "source_runs": args.source_runs,
            "sampling": "all supplied reads; reference sampling depth not harmonized",
            "command": command}
        (staging / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
        (staging / "alignment.bz2").unlink(missing_ok=True)
        for path in staging.iterdir():
            path.chmod(0o640)
        staging.rename(output)
    return {"output": str(output), "pipeline": mho.PIPELINE, "profile_sha256": provenance["profile_sha256"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    source = commands.add_parser("download", help="Download only the pinned ~9.1 MB published sources")
    source.add_argument("--source-dir", type=Path, required=True)
    bundle = commands.add_parser("build", help="Build an immutable, species-normalized MHNO reference")
    bundle.add_argument("--source-dir", type=Path, required=True)
    bundle.add_argument("--output", type=Path, required=True)
    bundle.add_argument("--minimum-subjects", type=int, default=30)
    bundle.add_argument("--stratify-by", nargs="*", choices=["age", "sex", "country"], default=[])
    bundle.add_argument("--age-window-years", type=float, default=10)
    bundle.add_argument("--demographics", type=Path)
    target = commands.add_parser("profile", help="Explicitly run the isolated target branch, never during reporting")
    target.add_argument("--sample-id", required=True)
    target.add_argument("--reads", type=Path, required=True, help="Existing merged, quality-controlled host-depleted FASTQ(.gz)")
    target.add_argument("--metaphlan", type=Path, required=True)
    target.add_argument("--database", type=Path, required=True)
    target.add_argument("--profiles-dir", type=Path, default=mho.profiles_dir())
    target.add_argument("--tool-bin", type=Path, help="Existing fmt-tax/bin for bowtie2 and other external tools")
    target.add_argument("--threads", type=int, default=8)
    target.add_argument("--source-runs", default="")
    check = commands.add_parser("check", help="Read-only validation of the complete reference + target comparison")
    check.add_argument("--sample-id", required=True)
    check.add_argument("--metadata-json", type=Path, help="Object containing subject_id/study_id or demographic matching fields")
    args = parser.parse_args()
    try:
        if args.command == "download":
            result = download(args.source_dir)
        elif args.command == "build":
            result = build(args.source_dir, args.output, minimum=args.minimum_subjects,
                           matching=args.stratify_by, age_window=args.age_window_years,
                           demographics=args.demographics)
        elif args.command == "profile":
            result = profile(args)
        else:
            metadata = json.loads(args.metadata_json.read_bytes()) if args.metadata_json else {}
            if not isinstance(metadata, dict):
                raise ValueError("--metadata-json must contain an object")
            comparison = mho.compare(args.sample_id, metadata)
            result = {"audit": comparison["audit"], "species_count": len(comparison["species"]),
                      "diversity": comparison["diversity"]}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result["audit"]["status"] != "available":
                raise SystemExit(1)
            return
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"MHO preparation failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
