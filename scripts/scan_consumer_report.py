"""Scan the consumer view model for the acceptance checks.

Usage: .venv/bin/python scripts/scan_consumer_report.py ZYMO_D6331
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from wgs_agent.consumer_web.format import business_number_violations, text_violations
from wgs_fmt_platform.paths import runtime_path


def body_texts(report: dict) -> list[str]:
    values: list[str] = []
    skip = {
        "graph", "evidence", "glossary", "references", "methods", "omissions",
        "downloads", "id", "type", "anchor", "status", "kind", "source_ids",
        "percentile", "tone", "latin", "topic_ids", "seeds", "first_in_report",
    }

    def walk(value):
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key in skip:
                    continue
                walk(item)

    walk(report.get("summary", {}))
    for section in report.get("sections", []):
        if section.get("id") == "learn":
            continue
        walk(section)
    walk(report.get("actions", []))
    walk(report.get("retest", {}))
    walk(report.get("red_flags", []))
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample")
    parser.add_argument("--results-dir", type=Path, default=None)
    args = parser.parse_args()
    root = args.results_dir or runtime_path("WGS_RESULTS_DIR", "results")
    path = root / f"{args.sample}_consumer_report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    texts = body_texts(report)
    forbidden = sum(len(text_violations(value)) for value in texts)
    digits = sum(len(business_number_violations(value)) for value in texts)
    p_values = sum(1 for value in texts if re.search(r"\bP\d", value))
    unsupported = sum(1 for value in texts if "未提供" in value)
    red = sum(1 for value in texts if re.search(r"#(?:F[0-9A-F]{5}|E[0-9A-F]{5}|D[0-9A-F]{5})", value, re.I))
    pending = sum(1 for entry in report.get("glossary", []) if entry.get("evidence_badge") == "待审")
    print(json.dumps({
        "sample": args.sample,
        "body_texts": len(texts),
        "forbidden_hits": forbidden,
        "over_three_significant_digit_hits": digits,
        "p_percentile_hits": p_values,
        "unsupported_phrase_hits": unsupported,
        "red_color_hits": red,
        "pending_glossary_entries": pending,
        "sections": [section.get("id") for section in report.get("sections", [])],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
