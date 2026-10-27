"""Refresh saved health-report presentation using existing data and narratives."""
from __future__ import annotations
import argparse
import datetime
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample_id")
    parser.add_argument("--report-path", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", args.sample_id):
        parser.error("invalid sample identifier")
    sid = args.sample_id
    report = (args.report_path or ROOT / "var/results" / f"{sid}_report.json").resolve()
    if not report.is_relative_to(ROOT):
        parser.error("report must be inside the project")
    output = report.parent
    original = report.read_bytes()
    document = json.loads(original)
    if document.get("sample_id") != sid:
        parser.error("saved report identifier does not match")
    logging.disable(logging.CRITICAL)
    from wgs_agent.reporting.document import render_markdown
    from wgs_agent.reporting.knowledge_graph import attach_subgraphs, render_graph_figures
    from wgs_agent.reporting.word_figures import render_word_figures
    from wgs_agent.reporting.overview_chart import render_overview_figure
    from wgs_agent.tools.report_maker import _generate_fpdf_report

    names = {
        "markdown": f"{sid}_health_report.md",
        "pdf": f"{sid}_health_report.pdf",
        "structured": report.name,
        "evidence": f"{sid}_report_evidence.json",
    }
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = output / f".{sid}_presentation_backup_{stamp}"
    backup.mkdir(mode=0o700)
    for name in names.values():
        item = output / name
        if item.is_file():
            shutil.copy2(item, backup / name)

    with tempfile.TemporaryDirectory(prefix=f".{sid}_presentation_", dir=output) as folder:
        staging = Path(folder)
        attach_subgraphs(document)
        figures = render_graph_figures(document, staging)
        figures.update(render_word_figures(document, staging))
        figures.update(render_overview_figure(document, staging))
        markdown = render_markdown(document)
        if "无量纲" in markdown:
            raise ValueError("dimensionless display validation failed")
        (staging / names["markdown"]).write_text(markdown, encoding="utf-8")
        document.setdefault("audit", {})["presentation_refreshed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (staging / names["structured"]).write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        evidence_path = output / names["evidence"]
        evidence = json.loads(evidence_path.read_text()) if evidence_path.is_file() else {"sample_id": sid, "evidence": document["evidence"]}
        for key in ("word_figures", "presentation", "overview_chart", "chapter_two_results", "chapter_two_taxon_labels", "chapter_three_results", "chapter_three_backgrounds", "module_bibliographies"):
            if key in document:
                evidence[key] = document[key]
        evidence["knowledge_subgraphs"] = {t["id"]: t["knowledge_subgraph"] for s in document["sections"] for t in s["topics"]}
        (staging / names["evidence"]).write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        _generate_fpdf_report(markdown, sid, str(staging / names["pdf"]))
        if report.read_bytes() != original:
            raise RuntimeError("saved report changed during refresh; retry after generation finishes")
        for name in figures.values():
            target = (staging / name).resolve()
            if not target.is_relative_to(staging) or not target.is_file():
                raise ValueError("invalid generated figure path")
        for name in [*figures.values(), *names.values()]:
            os.chmod(staging / name, 0o600)
            os.replace(staging / name, output / name)
    print("REFRESH_OK")
    print("PDF=" + str(output / names["pdf"]))
    print("BACKUP=" + str(backup))

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("REFRESH_FAILED=" + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
