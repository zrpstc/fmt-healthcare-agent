"""Overview comparisons, model labels and unchanged report-body contracts."""
import copy
import json

import pytest

from wgs_agent.reporting.document import build_document, render_markdown
from wgs_agent.reporting.overview_chart import (
    FALLBACK, overview_items, render_overview_figure, translate_overview_taxa,
)


def document(rows):
    return build_document("OVERVIEW_TEST", {"species_list": rows}, {}, {}, {}, {}, {}, {}, {})


def species(name="Escherichia coli", value=8, median=1):
    return {"species": name, "abundance": value, "reference_median": median,
            "unit": "%", "p5": 0.1, "p95": 2, "status": "high"}


def test_llm_translates_only_names_and_cannot_change_measurements(monkeypatch):
    doc = document([species()])
    original = copy.deepcopy(doc["evidence"])
    received = []

    def request(config, messages, schema, post):
        payload = json.loads(messages[1]["content"])
        received.append(payload)
        assert list(payload) == ["items"]
        assert set(payload["items"][0]) == {"id", "name"}
        return json.dumps({"items": [{"id": item["id"], "label": "大肠埃希菌"} for item in payload["items"]]})

    monkeypatch.setattr("wgs_agent.reporting.narrative._request", request)
    translate_overview_taxa(doc, {"base_url": "https://example.invalid", "model": "test"}, post=object())
    assert received and doc["evidence"] == original
    assert overview_items(doc)[0]["label"] == "大肠埃希菌"
    assert doc["audit"]["overview_taxon_translation"]["model_translated"] == 1


@pytest.mark.parametrize("response", [
    '{"items":[{"id":"escherichia coli","label":"<script>"}]}',
    '{"items":[{"id":"escherichia coli","label":"错误"},{"id":"escherichia coli","label":"重复"}]}',
    '{"items":[{"id":"other species","label":"错误"}]}',
    '{"items":null}', 'invalid',
])
def test_invalid_translation_falls_back_without_losing_identity(monkeypatch, response):
    doc = document([species()])
    monkeypatch.setattr("wgs_agent.reporting.narrative._request", lambda *args: response)
    translate_overview_taxa(doc, {"model": "test"}, post=object())
    item = overview_items(doc)[0]
    assert item["label"] == FALLBACK["escherichia coli"]
    assert item["original"] == "Escherichia coli" and item["value"] == 8


def test_unnamed_ids_are_never_invented_by_model(monkeypatch):
    doc = document([species("ggb38744_sgb14842")])
    def unexpected(*args):
        raise AssertionError("SGB identifiers must not be translated into named species")
    monkeypatch.setattr("wgs_agent.reporting.narrative._request", unexpected)
    translate_overview_taxa(doc, {"model": "test"}, post=object())
    item = overview_items(doc)[0]
    assert item["label"] == "未定种（SGB14842）" and item["original"] == "ggb38744_sgb14842"


@pytest.mark.parametrize("value,median,comparable,expected", [
    (8, 1, True, "高于"), (0, 1, True, "低于"), (8, 0, True, "不计算倍数"),
    (8, None, False, "未提供"), (8, -1, False, "未提供"), (8, float("nan"), False, "未提供"),
])
def test_missing_median_and_zero_are_distinguished(value, median, comparable, expected):
    doc = document([species(value=value, median=median)])
    item = overview_items(doc)[0]
    assert item["comparable"] is comparable
    assert expected in item["comparison"]


def test_chart_keeps_matched_normalization_colors_and_body(tmp_path):
    doc = document([species(), species("Bifidobacterium bifidum", 3, 0)])
    before = render_markdown(doc)
    rows = copy.deepcopy(doc["evidence"])
    translate_overview_taxa(doc, None)
    files = render_overview_figure(doc, tmp_path)
    after = render_markdown(doc)
    assert (tmp_path / files["overview"]).read_bytes().startswith(b"\x89PNG")
    chart = doc["overview_chart"]
    assert chart["sample_color"] != chart["reference_color"]
    assert len(chart["items"]) == 2
    assert chart["items"][0]["value"] == 8 and chart["items"][0]["reference_median"] == 1
    assert doc["evidence"] == rows
    assert before.split("## 1 ", 1)[1] == after.split("## 1 ", 1)[1]
    overview = after.split("## 检测结果总览", 1)[1].split("## 1 ", 1)[0]
    assert "![检测结果总览" in overview and "| 关注顺序" not in overview


def test_empty_and_qc_failed_reports_never_draw_fabricated_results(tmp_path):
    doc = document([])
    assert render_overview_figure(doc, tmp_path) == {}
    doc = document([species()])
    doc["metadata"]["qc_status"] = "failed"
    assert render_overview_figure(doc, tmp_path) == {}


def test_mho_bars_use_independent_comparison_profile_instead_of_primary_abundance():
    primary = species(value=72, median=99)
    comparison = {**species(value=50, median=27), "p5": 11.7, "p95": 42.3}
    doc = build_document("OVERVIEW_MHO", {"species_list": [primary]}, {}, {}, {}, {}, {}, {}, {},
                         context={"health_inputs": {"healthy_comparison": {"species": [comparison]}}})
    items = overview_items(doc)
    assert len(items) == 1 and items[0]["evidence_id"].startswith("HS")
    assert items[0]["value"] == 50 and items[0]["reference_median"] == 27
    assert doc["evidence"]["S1"]["value"] == 72


def test_exact_requested_mho_control_copy_preserves_audit():
    doc = document([species()])
    reference = {"status": "available", "provider": "mho", "cohort_id": "TEST_COHORT",
                 "cohort_version": "test-version", "n_subjects": 103, "limitations": ["旧版冗长文案"]}
    doc["audit"]["reference_comparison"] = {"healthy_population": reference}
    text = render_markdown(doc)
    expected = ("对照组信息：MHOmicrobiome 对照，对照人群为原研究定义的代谢健康非肥胖人群，不是通用临床正常值。 "
                "P5–P95 和经验百分位描述该参考队列，不代表疾病概率。对照组使用人群总体，未按年龄、性别或地区匹配。")
    assert expected in text
    assert "旧版冗长文案" not in text
    assert doc["audit"]["reference_comparison"]["healthy_population"] == reference
