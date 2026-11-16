"""Offline rebuild of one consumer web report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wgs_agent.consumer_web.builder import build_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", help="sample id, e.g. ZYMO_D6331")
    parser.add_argument("--report-path", type=Path, default=None)
    parser.add_argument("--analysis-path", type=Path, default=None)
    parser.add_argument("--results-dir", type=Path, default=None)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    try:
        report = build_report(
            args.sample,
            report_path=args.report_path,
            analysis_path=args.analysis_path,
            results_dir=args.results_dir,
            refresh=args.refresh,
        )
    except Exception:
        print("CONSUMER_BUILD_FAILED")
        return 2
    print(json.dumps({
        "status": "ok",
        "sample_id": report["sample"]["sample_id"],
        "alias": report["sample"]["alias"],
        "sections": [section["id"] for section in report["sections"]],
        "actions": len(report["actions"]),
        "glossary": len(report["glossary"]),
        "references": len(report["references"]),
        "omissions": len(report["omissions"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
