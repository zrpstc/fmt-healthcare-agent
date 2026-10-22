#!/usr/bin/env python3
"""Create three-layer artifacts from reports generated before the v1 layer split."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from wgs_agent.tools.report_layers import build_report_layers


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _atomic_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def backfill(results: Path, sample_id: str, dry_run: bool = False) -> dict[str, Any]:
    analysis_path = results / f"{sample_id}_analysis.json"
    evidence_path = results / f"{sample_id}_report_evidence.json"
    main_path = results / f"{sample_id}_health_report.md"
    technical_path = results / f"{sample_id}_technical_appendix.md"
    interactive_path = results / f"{sample_id}_interactive_report.json"
    if not analysis_path.is_file() or not main_path.is_file():
        return {"sample_id": sample_id, "status": "skipped", "reason": "analysis or markdown missing"}
    analysis = _object(analysis_path)
    manifest = _object(evidence_path)
    detailed = technical_path.read_text(encoding="utf-8") if technical_path.is_file() else main_path.read_text(encoding="utf-8")
    layers = build_report_layers(
        sample_id=sample_id,
        full_report=detailed,
        evidence=manifest.get("evidence") if isinstance(manifest.get("evidence"), dict) else {},
        species_data=analysis.get("species") if isinstance(analysis.get("species"), dict) else {},
        enterotype_data=analysis.get("enterotype") if isinstance(analysis.get("enterotype"), dict) else {},
        pathway_data=analysis.get("pathways") if isinstance(analysis.get("pathways"), dict) else {},
        disease_data=analysis.get("diseases") if isinstance(analysis.get("diseases"), dict) else {},
        matching_data=(manifest.get("fmt_matching") if isinstance(manifest.get("fmt_matching"), dict) else analysis.get("fmt_matching") if isinstance(analysis.get("fmt_matching"), dict) else {}),
        context=manifest.get("context") if isinstance(manifest.get("context"), dict) else analysis.get("metadata") if isinstance(analysis.get("metadata"), dict) else {},
    )
    if not dry_run:
        _atomic_text(main_path, layers["main_markdown"])
        _atomic_text(technical_path, layers["technical_markdown"])
        _atomic_json(interactive_path, layers["interactive"])
    return {"sample_id": sample_id, "status": "planned" if dry_run else "complete", "technical": str(technical_path), "interactive": str(interactive_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sample_ids = args.sample_id or sorted(path.name.removesuffix("_analysis.json") for path in args.results_dir.glob("*_analysis.json"))
    print(json.dumps([backfill(args.results_dir, sample_id, args.dry_run) for sample_id in sample_ids], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
