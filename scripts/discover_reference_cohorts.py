#!/usr/bin/env python3
"""Discover candidate fecal WGS reference cohorts from the canonical cMD manifest."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from urllib.request import urlopen


SOURCE = "https://raw.githubusercontent.com/waldronlab/curatedMetagenomicDataCuration/master/inst/extdata/studies_status.csv"


def candidates(text: str, healthy_only: bool) -> list[dict[str, object]]:
    found = []
    for row in csv.DictReader(io.StringIO(text)):
        diseases = row.get("primary_disease", "")
        if "feces" not in row.get("body_site", "").lower():
            continue
        if row.get("curation_available") != "TRUE":
            continue
        if healthy_only and "healthy" not in diseases.lower():
            continue
        found.append({
            "study_name": row.get("study_name"),
            "bioproject": row.get("study_id") or None,
            "study_samples_total": int(row.get("n_samples") or 0),
            "phenotypes": diseases.split(";") if diseases else [],
            "body_site": row.get("body_site"),
            "countries": row.get("country", "").split(";") if row.get("country") else [],
            "sequencing_platform": row.get("sequencing_platform"),
            "pmid": row.get("pmid") or None,
            "curation_status": row.get("processing_status"),
        })
    return sorted(found, key=lambda item: (-int(item["study_samples_total"]), str(item["study_name"])))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-phenotypes", action="store_true", help="include cohorts without healthy controls")
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    args = parser.parse_args()
    with urlopen(SOURCE, timeout=30) as response:
        text = response.read().decode("utf-8")
    result = {
        "source": SOURCE,
        "selection": "curated fecal cohorts" + ("" if args.all_phenotypes else " containing healthy samples"),
        "cohort_count": 0,
        "cohorts": candidates(text, healthy_only=not args.all_phenotypes),
    }
    result["cohort_count"] = len(result["cohorts"])
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
