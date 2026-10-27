"""Refresh only chapter 7 from saved evidence; preserve all other Markdown chapters."""

from __future__ import annotations

import argparse
import datetime
import fcntl
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


def replace_sections(markdown, replacement):
    start = re.search(r"^### 7\.2 .+$", markdown, re.M)
    end = re.search(r"^## 8 .+$", markdown, re.M)
    if not start or not end or start.start() >= end.start():
        raise ValueError("chapter seven boundaries not found")
    return markdown[: start.start()] + "\n\n".join(replacement) + "\n\n" + markdown[end.start() :]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample_id")
    parser.add_argument("--report-path", type=Path)
    args = parser.parse_args()
    sid = args.sample_id
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", sid):
        parser.error("invalid sample identifier")
    report = (args.report_path or ROOT / "var/results" / f"{sid}_report.json").resolve()
    if not report.is_relative_to(ROOT) or report.name != f"{sid}_report.json":
        parser.error("report must use its sample filename inside the project")
    output = report.parent
    with (output / f".{sid}.report.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        names = [
            f"{sid}_report.json",
            f"{sid}_health_report.md",
            f"{sid}_health_report.pdf",
            f"{sid}_report_evidence.json",
        ]
        originals = {
            name: (output / name).read_bytes() if (output / name).exists() else None
            for name in names
        }
        if originals[names[0]] is None or originals[names[1]] is None:
            raise ValueError("saved report and markdown required")
        document = json.loads(originals[names[0]])
        if document.get("sample_id") != sid:
            raise ValueError("sample mismatch")
        markdown = originals[names[1]].decode("utf-8")
        logging.disable(logging.CRITICAL)
        from wgs_agent.reporting.chapter_seven import render_figures, render_sections
        from wgs_agent.tools.report_maker import _generate_fpdf_report

        with tempfile.TemporaryDirectory(prefix=f".{sid}_chapter7_", dir=output) as folder:
            staging = Path(folder)
            for name in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown):
                path = Path(name)
                if path.name != name or not re.fullmatch(
                    re.escape(sid) + r"_[A-Za-z0-9_-]+\.png", name
                ):
                    raise ValueError("unexpected saved image path")
                shutil.copy2(output / name, staging / name)
            document.setdefault("presentation", {})
            manifest = document.setdefault("word_figures", {})
            figures = render_figures(document, staging, manifest)
            revised = replace_sections(markdown, render_sections(document))
            # Exact byte preservation outside 7.2–7.4, including chapter 3.
            before = markdown.split("### 7.2 ", 1)[0]
            after = markdown[re.search(r"^## 8 .+$", markdown, re.M).start() :]
            if not revised.startswith(before) or not revised.endswith(after):
                raise ValueError("unrelated chapter changed")
            stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            document.setdefault("audit", {})["chapter_seven_presentation_refreshed_at"] = stamp
            evidence = (
                json.loads(originals[names[3]])
                if originals[names[3]] is not None
                else {"sample_id": sid}
            )
            for key in ("chapter_seven_results", "word_figures", "presentation"):
                evidence[key] = document[key]
            evidence.setdefault("audit", {})["chapter_seven_presentation_refreshed_at"] = stamp
            (staging / names[0]).write_text(
                json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False),
                encoding="utf-8",
            )
            (staging / names[1]).write_text(revised, encoding="utf-8")
            (staging / names[3]).write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False),
                encoding="utf-8",
            )
            _generate_fpdf_report(revised, sid, str(staging / names[2]))
            for name, original in originals.items():
                current = (output / name).read_bytes() if (output / name).exists() else None
                if current != original:
                    raise RuntimeError("report changed concurrently; nothing published")
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = output / f".{sid}_chapter7_backup_{stamp}"
            backup.mkdir(mode=0o700)
            for name, original in originals.items():
                if original is not None:
                    (backup / name).write_bytes(original)
                    (backup / name).chmod(0o600)
            for name in [*figures.values(), *names]:
                (staging / name).chmod(0o600)
                os.replace(staging / name, output / name)
        print("CHAPTER7_REFRESH_OK", str(report))
        print("BACKUP", str(backup))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("CHAPTER7_REFRESH_FAILED", type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
