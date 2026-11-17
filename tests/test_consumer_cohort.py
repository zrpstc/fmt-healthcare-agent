"""Consumer report: overall health score, gut age / enterotype and disease-cohort reference."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from wgs_agent.consumer_web.builder import build_report
from wgs_agent.consumer_web.format import business_number_violations, text_violations
from wgs_agent.reporting import cohort_insights
from wgs_agent.reporting.cohort_models import train_all
from test_cohort_models import synthetic_cohort, write_bundle, write_target
from test_consumer_builder import _body_texts

FIXTURES = Path(__file__).parent / "fixtures" / "consumer_web"


@pytest.fixture(scope="module")
def models():
    return train_all(synthetic_cohort(), ["CRC"])


def _insights(tmp_path, monkeypatch, models, age=45):
    base = write_bundle(tmp_path, models)
    profiles = write_target(tmp_path, "T1", {
        "bacteroides vulgatus": 40, "faecalibacterium prausnitzii": 12, "bifidobacterium longum": 3,
        "fusobacterium nucleatum": 4, "parvimonas micra": 2, "eubacterium rectale": 39}, age=age)
    monkeypatch.setenv("WGS_CMD_COHORT_DIR", str(base))
    monkeypatch.setenv("WGS_CMD_PROFILES_DIR", str(profiles))
    result = cohort_insights.analyze("T1", {}, extra_species=["Escherichia coli"])
    assert result["audit"]["status"] == "available"
    # Mark the synthetic disease as informative so the table renders.
    for row in result["diseases"]:
        row["informative"] = True
    return result


def _build(tmp_path, insights, sample="ZYMO_D6331"):
    results = tmp_path / "results"
    results.mkdir()
    report = json.loads((FIXTURES / "sample_report.json").read_text(encoding="utf-8"))
    if insights is not None:
        report["template_inputs"]["cohort_insights"] = insights
    (results / f"{sample}_report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    shutil.copyfile(FIXTURES / "sample_analysis.json", results / f"{sample}_analysis.json")
    return build_report(sample, results_dir=results, refresh=True)


def test_report_with_cohort_models(tmp_path, monkeypatch, models):
    payload = _build(tmp_path, _insights(tmp_path, monkeypatch, models))
    score = payload["summary"]["health_score"]
    assert score is not None
    assert 0 <= score["score"]["value"] <= 100 and score["score"]["unit"] == "分"
    ids = [c["id"] for c in score["components"]]
    assert {"diversity", "similarity", "gut_age"} <= set(ids)
    assert sum(c["weight"] for c in score["components"]) <= 100
    cards = {card["id"] for card in payload["summary"]["status_cards"]}
    assert {"gut_age", "enterotype"} <= cards
    sections = {s["id"]: s for s in payload["sections"]}
    gut = sections["gut-profile"]
    sub = {s["id"]: s for s in gut["subsections"]}
    age_scatter = next(b for b in sub["gut-age"]["blocks"] if b["type"] == "scatter")
    assert age_scatter["diagonal"] is True and age_scatter["you"][0] == 45
    entero_scatter = next(b for b in sub["enterotype"]["blocks"] if b["type"] == "scatter")
    assert len(entero_scatter["groups"]) == 3
    assert len(entero_scatter["point_groups"]) == len(entero_scatter["points"])
    virulence = {s["id"]: s for s in sections["virulence"]["subsections"]}
    reference = virulence["virulence-disease-reference"]
    table = next(b for b in reference["blocks"] if b["type"] == "table")
    assert table["rows"][0][0] == "结直肠癌"
    pathogen = next(a for a in payload["summary"]["assessments"] if a["id"] == "pathogen")
    assert any(point.startswith("患病人群参考") for point in pathogen["points"])
    omitted = {(row["section"], row["item"]) for row in payload["omissions"]}
    assert ("overview", "综合健康分与肠龄") not in omitted
    for text in _body_texts(payload):
        assert not text_violations(text), text
        assert not business_number_violations(text), text
    method_titles = {m["title"] for m in payload["methods"]}
    assert {"肠道年龄", "肠型", "总体健康得分", "患病人群参考"} <= method_titles


def test_unknown_age_shows_prediction_without_comparison(tmp_path, monkeypatch, models):
    insights = _insights(tmp_path, monkeypatch, models, age=None)
    payload = _build(tmp_path, insights)
    gut = next(s for s in payload["sections"] if s["id"] == "gut-profile")
    scatter = next(b for s in gut["subsections"] if s["id"] == "gut-age" for b in s["blocks"] if b["type"] == "scatter")
    assert scatter["you"] is None
    score = payload["summary"]["health_score"]
    assert "gut_age" not in [c["id"] for c in score["components"]]


def test_without_cohort_bundle_section_is_hidden_and_reason_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("WGS_CMD_COHORT_DIR", str(tmp_path / "missing"))
    payload = _build(tmp_path, None)
    assert "gut-profile" not in {s["id"] for s in payload["sections"]}
    omitted = {(row["section"], row["item"]) for row in payload["omissions"]}
    assert ("gut-profile", "肠道年龄与肠型") in omitted
    # The overall score still works from the healthy comparison and other modules.
    score = payload["summary"]["health_score"]
    assert score is None or score["components"]
