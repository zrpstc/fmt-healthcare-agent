from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from wgs_agent.consumer_web.builder import build_report
from wgs_agent.consumer_web.sections.virulence_section import count_ticks

FIXTURES = Path(__file__).parent / "fixtures" / "consumer_web"
TOXIN_INDEX = {
    "VFG002287": {
        "id": "VFG002287",
        "symbol": "toxA",
        "vf_name": "TcdA",
        "vf_category": "Exotoxin",
        "host": "Clostridium difficile 630",
    }
}


def _build(monkeypatch, mutate=None) -> dict:
    monkeypatch.setattr("wgs_agent.consumer_web.sections.virulence.load_vfdb_index", lambda: TOXIN_INDEX)
    document = json.loads((FIXTURES / "sample_report.json").read_text(encoding="utf-8"))
    if mutate:
        mutate(document)
    with tempfile.TemporaryDirectory() as temporary:
        tmp = Path(temporary)
        (tmp / "CONSUMER_TEST_report.json").write_text(json.dumps(document), encoding="utf-8")
        shutil.copyfile(FIXTURES / "sample_analysis.json", tmp / "CONSUMER_TEST_analysis.json")
        return build_report("CONSUMER_TEST", results_dir=tmp, refresh=True)


def _subsection(report: dict, sub_id: str) -> dict:
    for section in report["sections"]:
        for subsection in section["subsections"]:
            if subsection["id"] == sub_id:
                return subsection
    raise AssertionError(sub_id)


def test_overview_has_pathogen_and_nutrition_assessments(monkeypatch):
    report = _build(monkeypatch)
    items = {item["id"]: item for item in report["summary"]["assessments"]}
    assert set(items) == {"pathogen", "nutrition"}
    # A high-concern toxin gene in the fixture drives the strongest verdict.
    assert items["pathogen"]["tone"] == "consult"
    assert any("艰难梭菌毒素A/B" in point for point in items["pathogen"]["points"])
    assert any(point.startswith("短链脂肪酸潜力评分") for point in items["nutrition"]["points"])
    assert items["nutrition"]["anchor"] == "#nutrition"


def test_shannon_row_is_labelled_and_falls_back_without_reference(monkeypatch):
    report = _build(monkeypatch)
    rows = _subsection(report, "diversity-diversity")["blocks"][0]["rows"]
    shannon = next(row for row in rows if row["label"].startswith("香农指数"))
    assert shannon["tier"]["key"] == "low"

    def drop_shannon_reference(document):
        rows = document["template_inputs"]["healthy_comparison"]["diversity"]
        document["template_inputs"]["healthy_comparison"]["diversity"] = [r for r in rows if r["metric"] != "shannon"]
        document["template_inputs"]["taxonomy"]["complete"] = True

    report = _build(monkeypatch, drop_shannon_reference)
    rows = _subsection(report, "diversity-diversity")["blocks"][0]["rows"]
    shannon = next(row for row in rows if row["label"].startswith("香农指数"))
    # Primary-profile Shannon (natural log) is shown without inventing a tier.
    assert shannon["tier"] is None
    assert shannon["value"]["display"] == "1.19"
    assert "参考人群比较" in shannon["note"]


def test_composition_uses_titled_donut(monkeypatch):
    blocks = _subsection(_build(monkeypatch), "composition-composition")["blocks"]
    donut = next(block for block in blocks if block["type"] == "donut")
    assert donut["title"] and donut["caption"]
    bars = next(block for block in blocks if block["type"] == "ranked_bars")
    assert bars["title"] and bars["axis"]["value_label"]


def test_division_adds_detected_taxa_with_known_roles(monkeypatch):
    def add_taxa(document):
        document["template_inputs"]["taxonomy"]["ranks"]["species"] += [
            {"name": "Veillonella parvula", "abundance": 1.5},
            {"name": "Akkermansia muciniphila", "abundance": 2.0},
        ]

    stages = _subsection(_build(monkeypatch, add_taxa), "diversity-division")["blocks"][0]["stages"]
    by_title = {stage["title"]: stage for stage in stages}
    assert "生成丙酸" in by_title
    lactate = by_title["转化中间产物（乳酸利用）"]["member_details"]
    assert lactate and all(member["basis"] == "taxonomy" for member in lactate)
    # Gene-stratified members keep their basis and come first.
    butyrate = by_title["生成丁酸"]["member_details"]
    assert butyrate[0]["basis"] == "gene"


def test_virulence_bars_have_title_axis_and_gene_unit(monkeypatch):
    blocks = _subsection(_build(monkeypatch), "virulence-genes")["blocks"]
    bars = next(block for block in blocks if block["type"] == "ranked_bars")
    assert bars["title"]
    assert bars["axis"]["value_label"] == "基因个数（个）"
    assert all(row["value"]["unit"] == "个" for row in bars["rows"])
    assert _subsection(_build(monkeypatch), "virulence-genes")["summary"]


def test_metabolite_cards_carry_score_and_details(monkeypatch):
    cards = _subsection(_build(monkeypatch), "metabolites-scfa")["blocks"][0]["cards"]
    butyrate = next(card for card in cards if card["title"] == "丁酸")
    assert 0 <= butyrate["score"]["value"] <= 100
    assert butyrate["score"]["unit"] == "分"
    assert butyrate["score_label"].startswith("潜力")
    assert {row["label"] for row in butyrate["details"]} >= {"评分怎么算", "怎么理解"}


@pytest.mark.parametrize("maximum,expected", [(1, ["0", "1"]), (4, ["0", "1", "2", "3", "4"]), (21, ["0", "10", "20", "30"])])
def test_count_ticks(maximum, expected):
    assert [tick["display"] for tick in count_ticks(maximum)] == expected
