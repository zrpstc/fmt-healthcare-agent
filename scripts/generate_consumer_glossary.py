"""Draft glossary texts for one sample's unexplained taxa and queue them for review.

Run ``scripts/build_consumer_report.py SAMPLE`` first: the build records which
displayed taxa lack text.  Drafts are always *pending*; approve them in
``/reports/review`` before they can appear in a report.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wgs_fmt_platform.infrastructure.database import create_schema
from wgs_agent.consumer_web.glossary_candidates import generate_for_sample


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", help="sample id, e.g. ZYMO_D6331")
    parser.add_argument("--limit", type=int, default=20, help="maximum taxa to process (default 20)")
    parser.add_argument("--no-llm", action="store_true", help="queue evidence only; reviewers write the text")
    parser.add_argument("--results-dir", type=Path, default=None)
    args = parser.parse_args()
    create_schema()
    summary = generate_for_sample(
        args.sample, limit=args.limit, use_llm=not args.no_llm, results_dir=args.results_dir,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
