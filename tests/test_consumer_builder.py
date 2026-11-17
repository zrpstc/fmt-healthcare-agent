from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


from wgs_agent.consumer_web.builder import build_report
from wgs_agent.consumer_web.format import business_number_violations, text_violations


FIXTURES = Path(__file__).parent / "fixtures" / "consumer_web"


def _install(tmp: Path, sample: str) -> None:
    shutil.copyfile(FIXTURES / "sample_report.json", tmp / f"{sample}_report.json")
    shutil.copyfile(FIXTURES / "sample_analysis.json", tmp / f"{sample}_analysis.json")


def _body_texts(report: dict) -> list[str]:
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

    walk(report["summary"])
    for section in report["sections"]:
        if section["id"] == "learn":
            continue
        walk(section)
    walk(report["actions"])
    walk(report["retest"])
    walk(report["red_flags"])
    return values


def test_builder_contract_and_forbidden_scan(monkeypatch):
    monkeypatch.setattr(
        "wgs_agent.consumer_web.sections.virulence.load_vfdb_index",
        lambda: {
            "VFG002287": {
                "id": "VFG002287",
                "symbol": "toxA",
                "vf_name": "TcdA",
                "vf_category": "Exotoxin",
                "host": "Clostridium difficile 630",
            }
        },
    )
    with tempfile.TemporaryDirectory() as temporary:
        tmp = Path(temporary)
        _install(tmp, "CONSUMER_TEST")
        report = build_report("CONSUMER_TEST", results_dir=tmp, refresh=True)
        assert report["schema_version"] == "consumer-report/1"
        assert report["sample"]["alias"] == "样本 TEST"
        assert report["sample"]["source_report_sha256"]
        assert [section["id"] for section in report["sections"]][-1] == "learn"
        assert report["summary"]["status_cards"]
        assert report["summary"]["key_findings"]
        assert all(not text_violations(value) for value in _body_texts(report))
        assert all(not business_number_violations(value) for value in _body_texts(report))
        assert report["downloads"]
        # Public-facing output must not contain pending glossary entries.
        assert all(entry["evidence_badge"] != "待审" for entry in report["glossary"])
        assert any(entry["term_id"] == "relative_abundance" for entry in report["glossary"])


def test_builder_cache_is_keyed_by_source_hash(monkeypatch):
    monkeypatch.setattr(
        "wgs_agent.consumer_web.sections.virulence.load_vfdb_index",
        lambda: {},
    )
    with tempfile.TemporaryDirectory() as temporary:
        tmp = Path(temporary)
        _install(tmp, "CONSUMER_TEST")
        first = build_report("CONSUMER_TEST", results_dir=tmp, refresh=True)
        second = build_report("CONSUMER_TEST", results_dir=tmp, refresh=False)
        assert first["sample"]["generated_at"] == second["sample"]["generated_at"]
        assert second["sample"]["source_report_sha256"] == first["sample"]["source_report_sha256"]
        assert (tmp / "CONSUMER_TEST_consumer_report.cache.json").is_file()
