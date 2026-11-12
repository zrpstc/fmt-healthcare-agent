"""Build an immutable cMD healthy-control bundle from official native matrices."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import urllib.parse
import urllib.request

from wgs_agent.reporting import cmd
from wgs_agent.reporting.reference import species_key


def eligible(row):
    try:
        age = float(row.get("age", ""))
    except (ValueError, TypeError):
        return False
    return (math.isfinite(age) and age >= 18 and row.get("body_site") == "stool"
            and row.get("disease") == "healthy" and row.get("study_condition") == "control"
            and row.get("antibiotics_current_use") == "no"
            and row.get("subject_id") and row.get("study_name") and row.get("sample_id")
            and str(row.get("pregnant", "")).lower() not in {"yes", "true", "1"}
            and str(row.get("lactating", "")).lower() not in {"yes", "true", "1"})


def fetch(url, destination):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("public HTTPS source required")
    if parsed.hostname not in {"experimenthub.bioconductor.org", "mghp.osn.xsede.org",
                               "bioconductorhubs.blob.core.windows.net"}:
        raise ValueError("unrecognized official hub location")
    if destination.is_file():
        return
    temporary = destination.with_suffix(destination.suffix+".part")
    with urllib.request.urlopen(url, timeout=180) as response, temporary.open("wb") as output:
        expected = int(response.headers.get("Content-Length", 0))
        count = 0
        for block in iter(lambda: response.read(1024*1024), b""):
            output.write(block)
            count += len(block)
        output.flush()
        os.fsync(output.fileno())
    if not count or expected and count != expected:
        raise ValueError("incomplete hub download")
    temporary.replace(destination)


def resource_catalog(package, catalog_file, studies):
    with (package/"inst/extdata/metadata.csv").open() as handle:
        titles = {r["Title"] for r in csv.DictReader(handle)
                  if r["Title"].endswith(".relative_abundance")}
    connection = sqlite3.connect("file:"+str(catalog_file)+"?mode=ro&immutable=1", uri=True)
    rows = connection.execute("""select r.ah_id,r.title,l.location_prefix,p.rdatapath
        from resources r join location_prefixes l on l.id=r.location_prefix_id
        join rdatapaths p on p.resource_id=r.id where r.title like '%.relative_abundance'""")
    found = {}
    for rid, title, prefix, path in rows:
        if title not in titles:
            continue
        study = title.split(".")[1]
        if study not in studies:
            continue
        if study not in found or title > found[study]["title"]:
            found[study] = {"study": study, "resource_id": rid, "title": title, "url": prefix+path}
    connection.close()
    missing = studies-set(found)
    if missing:
        raise ValueError("healthy studies missing from official resource catalog")
    return found


R_EXPORT = r'''
args <- commandArgs(TRUE)
plan <- read.delim(args[1],check.names=FALSE,colClasses="character")
for(i in seq_len(nrow(plan))) {
 x <- tryCatch(readRDS(plan$input[i]),error=function(e) {
  env <- new.env(parent=baseenv());n <- load(plan$input[i],envir=env)
  if(length(n)!=1L)stop("unexpected R objects")
  get(n[1],env,inherits=FALSE)
 })
 if(!is.matrix(x)||!is.numeric(x)||is.null(rownames(x))||is.null(colnames(x))||anyDuplicated(colnames(x)))stop("invalid abundance matrix")
 keep <- vapply(strsplit(rownames(x),"|", fixed=TRUE),function(p)startsWith(tail(p,1),"s__"),logical(1))
 x <- x[keep,,drop=FALSE]
 if(!nrow(x)||any(!is.finite(x))||any(x<0)|any(x>100))stop("invalid species abundances")
 write.table(data.frame(taxonomy=rownames(x),x,check.names=FALSE),plan$output[i],sep="\t",row.names=FALSE,quote=TRUE,na="")
}
'''


def build(package, metadata, catalog, source_dir, output, r_library=None):
    if output.exists():
        cmd.load_bundle(output)
        return {"status": "already_built", "output": str(output)}
    source_dir.mkdir(parents=True, exist_ok=True)
    with metadata.open() as handle:
        candidates = [r for r in csv.DictReader(handle, delimiter="\t") if eligible(r)]
    if not candidates:
        raise ValueError("no eligible healthy controls")
    resources = resource_catalog(package, catalog, {r["study_name"] for r in candidates})
    matrix_dir = source_dir/"matrices"
    matrix_dir.mkdir(exist_ok=True)
    def download(item):
        destination = matrix_dir/(item["title"]+".rda")
        fetch(item["url"], destination)
        return {**item, "path": destination, "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                "bytes": destination.stat().st_size, "export": matrix_dir/(item["study"]+".species.tsv")}
    with ThreadPoolExecutor(max_workers=6) as pool:
        downloaded = list(pool.map(download, resources.values()))
    plan = source_dir/"matrix-export-plan.tsv"
    with plan.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["input", "output"])
        writer.writerows((str(r["path"]), str(r["export"])) for r in downloaded)
    env = dict(os.environ)
    if r_library:
        env["R_LIBS_USER"] = str(r_library)
    with (source_dir/"matrix-export.log").open("wb") as log:
        subprocess.run(["Rscript", "-e", R_EXPORT, str(plan)], env=env, stdout=log, stderr=log, check=True)
    by_study = {}
    for row in candidates:
        by_study.setdefault(row["study_name"], {})[row["sample_id"]] = row
    profiles = {}
    for resource in downloaded:
        wanted = by_study[resource["study"]]
        with resource["export"].open() as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            ids = set(wanted)&set(reader.fieldnames or [])
            data = {sid: {} for sid in ids}
            for row in reader:
                feature = species_key(row["taxonomy"])
                for sid in ids:
                    if feature in data[sid]:
                        raise ValueError("duplicate reference species")
                    data[sid][feature] = float(row[sid])
            for sid, values in data.items():
                try:
                    normalized, raw_sum = cmd.normalize(values)
                except ValueError:
                    continue
                profiles[(resource["study"], sid)] = (normalized, raw_sum)
    def priority(row):
        try:
            days = float(row.get("days_from_first_collection", ""))
            if not math.isfinite(days): days = math.inf
        except ValueError:
            days = math.inf
        return days, row["sample_id"]
    selected = {}
    for row in sorted(candidates, key=priority):
        key = row["study_name"], row["subject_id"]
        if key not in selected and (row["study_name"], row["sample_id"]) in profiles:
            selected[key] = row
    labels = []; matrix = {}; feature_set = set()
    for (study, person), row in sorted(selected.items()):
        sid = study+"::"+row["sample_id"]
        values, total = profiles[(study, row["sample_id"])]
        matrix[sid] = values
        feature_set.update(key for key, v in values.items() if v>0)
        labels.append({"sample_id": sid, "original_sample_id": row["sample_id"], "subject_id": person,
                       "study_id": study, "phenotype": cmd.PHENOTYPE, "source_runs": row.get("NCBI_accession", ""),
                       "age": row["age"], "sex": row.get("gender", ""), "country": row.get("country", ""),
                       "BMI": row.get("BMI", ""), "body_site": "stool", "raw_species_sum": total})
    if len(labels)<30:
        raise ValueError("insufficient eligible independent controls")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cmd-build-", dir=output.parent) as directory:
        stage = Path(directory)/"bundle";stage.mkdir(mode=0o750)
        with (stage/"metadata.tsv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(labels[0]), delimiter="\t")
            writer.writeheader();writer.writerows(labels)
        features = sorted(feature_set)
        with (stage/"species_abundance.tsv").open("w", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(["sample_id", *features])
            for sid, values in sorted(matrix.items()):
                writer.writerow([sid, *(format(values.get(f, 0), ".12g") for f in features)])
        version = next(line.split(":", 1)[1].strip() for line in (package/"DESCRIPTION").read_text().splitlines() if line.startswith("Version:"))
        manifest = {"schema_version": cmd.VERSION, "cohort_id": "curatedMetagenomicData-healthy-adult-stool",
                    "cohort_version": "package-"+version+"-"+hashlib.sha256(metadata.read_bytes()).hexdigest()[:12],
                    "source_package": "curatedMetagenomicData", "source_package_version": version,
                    "source_url": "https://github.com/waldronlab/curatedMetagenomicData",
                    "pipeline": cmd.PIPELINE, "source_profiler_minor_version": None,
                    "source_pipeline_evidence": "Official cMD3 documentation: MetaPhlAn3; native 2021-2022 resources. Per-profile minor versions not supplied.",
                    "target_profiler_version": cmd.TARGET_VERSION,
                    "normalization": cmd.NORMALIZATION, "unit": "%", "phenotype": cmd.PHENOTYPE,
                    "body_site": "stool", "complete_species_profiles": True, "feature_level": "species",
                    "minimum_subjects": 30, "stratify_by": [], "age_window_years": 10,
                    "selection_criteria": {"minimum_age": 18, "disease": "healthy", "study_condition": "control",
                        "antibiotics_current_use": "no", "exclude_known_pregnant_or_lactating": True,
                        "deduplicate_by": ["study_id", "subject_id"], "repeat_selection": "earliest eligible valid profile then sample_id"},
                    "n_subjects": len(labels), "n_species": len(features), "n_studies": len({r['study_id'] for r in labels}),
                    "n_candidate_records": len(candidates), "n_missing_or_invalid_candidate_profiles": len(candidates)-len(profiles),
                    "limitations": list(cmd.LIMITATIONS),
                    "source_resources": [{k:r[k] for k in ("study", "resource_id", "title", "url", "sha256", "bytes")} for r in downloaded],
                    "files": {name: cmd.digest((stage/name).read_bytes()) for name in ("metadata.tsv", "species_abundance.tsv")}}
        (stage/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        cmd.load_bundle(stage)
        for f in stage.iterdir():
            f.chmod(0o640)
        stage.rename(output)
    return {"status": "built", "n_subjects": len(labels), "n_species": len(features), "n_studies": manifest["n_studies"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--r-library", type=Path)
    args = parser.parse_args()
    result = build(args.package_dir, args.metadata, args.catalog, args.source_dir, args.output, args.r_library)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
