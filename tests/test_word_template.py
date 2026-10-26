"""Contracts taken from the user's Word files, including data-free rendering."""

import json
import re


from wgs_agent.reporting.document import render_markdown
from wgs_agent.reporting.narrative import generate_narrative
from wgs_agent.reporting.word_figures import chart_data, render_word_figures
from wgs_agent.reporting.word_template import bind_table, contract, narrative_sections
from test_report_templates import build


def blocks(kind):
    return [b for c in contract()["chapters"] for b in c["blocks"] if b["type"] == kind]


def visual(key):
    return next(v for b in blocks("visuals") for v in b["items"] if v["id"] == key)


def table(key):
    return next(b for b in blocks("table") if b["id"] == key)


def test_complete_word_contract_without_example_measurements():
    c = contract()
    assert [ch["number"] for ch in c["chapters"]] == list(range(1, 15))
    assert len(blocks("heading")) == 58
    assert len(blocks("table")) == 51
    widgets = [v for b in blocks("visuals") for v in b["items"]]
    assert sum(v["type"] == "chart" for v in widgets) == 20
    assert sum(v["type"] == "flow" for v in widgets) == 12
    assert all(re.fullmatch(r"[a-f0-9]{64}", s["sha256"]) for s in c["sources"])
    assert '"values"' not in json.dumps(c)  # DOCX placeholder numbers never ship as results.
    assert c["style"]["chapter"] == "3465A4"
    assert c["style"]["subheading"] == "EA7500"
    assert table("3.1.t1")["rows"][0] == [
        "菌群范围",
        "具体物种",
        "功能背景",
        "检出状态",
        "相对丰度",
        "人群分位数",
    ]
    assert table("12.3.t1")["rows"][0] == ["模型信息", "填写内容"]
    assert visual("1.1.1")["legend"] is True
    assert visual("1.1.2")["legend"] is False


def test_every_word_field_and_visual_has_a_missing_data_state(tmp_path):
    doc = build()
    names = render_word_figures(doc, tmp_path)
    assert len(names) == 29  # 33 widgets, three pairs share one figure panel.
    for b in blocks("table"):
        rows = bind_table(doc, b)
        assert rows and all(len(r) == len(b["rows"][0]) for r in rows)
        assert "【" not in str(rows)
    for b in blocks("visuals"):
        for v in b["items"]:
            if v["type"] == "chart":
                assert chart_data(doc, v)["status"] == "missing"
    md = render_markdown(doc)
    assert len(re.findall(r"!\[.*模板图示\]", md)) == 29
    assert "图形仅作占位" not in md and "【" not in md
    assert not re.search(r"第(?:0\d|15|16)章|^### (?:15|16)\.", md, re.M)
    assert all((tmp_path / name).is_file() for name in names.values())


def test_measured_abundance_reference_and_reads_are_not_substituted():
    doc = build(
        species={
            "species_list": [
                {
                    "species": "Escherichia coli",
                    "abundance": 4,
                    "unit": "%",
                    "reads": 317,
                    "p5": 0,
                    "p95": 2,
                    "status": "high",
                }
            ]
        }
    )
    relative = chart_data(doc, visual("1.1.3"))
    assert relative["series"][0]["values"] == [4]
    ref = chart_data(doc, visual("1.4.1"))
    assert ref["series"][1]["values"] == [None]  # No midpoint inferred from P5/P95.
    reads = chart_data(doc, visual("3.3.1"))
    assert 317 in reads["series"][0]["values"]
    assert chart_data(doc, visual('2.2.1'))["status"] == "missing"  # No fake reference clouds.


def test_directions_and_contribution_denominators_remain_separate():
    doc = build(
        pathways={
            "pathways": [
                {
                    "name": "histamine generation",
                    "abundance": 0.2,
                    "unit": "RPK",
                    "reaction_direction": "generation",
                },
                {
                    "name": "histamine utilization",
                    "abundance": 0.7,
                    "unit": "RPK",
                    "reaction_direction": "utilization",
                },
                {
                    "name": "butyrate biosynthesis",
                    "abundance": 2,
                    "unit": "RPK",
                    "contributors": [{"taxon": "A", "abundance": 2, "unit": "RPK"}],
                },
            ]
        }
    )
    row = next(r for r in bind_table(doc, table("8.5.t1")) if r[0] == "组胺")
    assert "generation" in row[1] and "utilization" not in row[1]
    assert "utilization" in row[2] and "generation" not in row[2]
    assert chart_data(doc, visual("8.5.1"))["status"] == "missing"  # Abundance != percentile.
    assert chart_data(doc, visual("2.3.1"))["status"] == "missing"  # Incomplete contributor list.


def test_validated_score_ring_needs_explicit_scale_bounds():
    model = {
        "name": "综合健康分",
        "value": 35,
        "scale_min": 0,
        "scale_max": 100,
        "model_version": "v1",
        "externally_validated": True,
        "applicable": True,
        "validation_evidence": "test independent cohort",
        "scale_definition": "0 to 100",
    }
    doc = build(context={"health_inputs": {"composite_models": {"models": [model]}}})
    payload = chart_data(doc, visual("14.4.1"))
    assert payload["series"][0]["values"] == [35, 65]
    doc["template_inputs"]["composite_models"]["models"][0].pop("scale_max")
    assert chart_data(doc, visual("14.4.1"))["status"] == "missing"


def test_qc_blocks_all_word_figures_and_optional_observations(tmp_path):
    doc = build(
        species={"species_list": [{"species": "SECRET_TEST", "abundance": 5, "unit": "%"}]},
        context={
            "qc_status": "failed",
            "health_inputs": {"virulence": {"markers": [{"gene": "SECRET_VF", "detected": True}]}},
        },
    )
    sections = narrative_sections(doc)
    assert not any(t["status"] != "missing" for s in sections for t in s["topics"])
    render_word_figures(doc, tmp_path)
    md = render_markdown(doc)
    assert "SECRET_TEST" not in md and "SECRET_VF" not in md
    assert "质控未通过" in md


def test_model_uses_word_subsections_instead_of_legacy_topics():
    from test_health_report import fake_response

    doc = build(
        context={
            "health_inputs": {
                "strains": {
                    "items": [
                        {"name": "test strain", "result": "lineage A", "analysis_level": "谱系"}
                    ]
                }
            }
        }
    )
    calls = []

    def post(url, **kwargs):
        calls.append(kwargs["json"])
        return fake_response(kwargs["json"])

    result = generate_narrative(doc, {"base_url": "http://local/v1", "model": "test"}, post=post)
    assert result["audit"]["llm_status"] == "generated"
    assert result["audit"]["narrative_contract"] == "word-subsections-1-14-v2"
    for payload in calls:
        data = json.loads(payload["messages"][1]["content"].split("固定分析目录与证据：\n")[1])
        assert all(s["id"].startswith("word.") for s in data["outline"])
        assert all("writing_focus" in t for s in data["outline"] for t in s["topics"])
    assert "本项已记录对应的检测线索" in render_markdown(result)
    assert doc.get("word_sections") is None


def test_empty_template_does_not_request_model_for_fixed_explanatory_rows():
    def forbidden(*args, **kwargs):
        raise AssertionError("no observations")

    result = generate_narrative(build(), {"model": "test"}, post=forbidden)
    assert result["audit"]["llm_status"] == "no_eligible_data"


def test_identical_word_placeholder_paragraphs_use_their_own_chapter():
    doc = build(
        context={
            "health_inputs": {
                "virulence": {"markers": [{"gene": "UNIQUE_VF", "detected": True}]},
                "scales": {"observations": [{"name": "睡眠", "result": "UNIQUE_SLEEP"}]},
            }
        }
    )
    md = render_markdown(doc)
    from test_report_templates import block

    assert "UNIQUE_VF" in block(md, "4.4")
    assert "UNIQUE_VF" not in block(md, "7.4")
    assert "UNIQUE_VF" not in block(md, "10.4")
    assert "UNIQUE_SLEEP" in block(md, "10.4")


def test_cell_component_synthesis_is_not_dietary_polysaccharide_degradation():
    doc = build(
        pathways={
            "pathways": [
                {
                    "name": "lipopolysaccharide biosynthesis",
                    "abundance": 1,
                    "unit": "RPK",
                    "contributors_complete": True,
                    "contributors": [{"taxon": "A", "abundance": 1, "unit": "RPK"}],
                }
            ]
        }
    )
    assert "lipopolysaccharide" not in str(bind_table(doc, table("2.3.t1")))
    assert chart_data(doc, visual("2.3.1"))["status"] == "missing"
    assert "lipopolysaccharide" in str(bind_table(doc, table("8.8.t1")))


def test_subunit_abundance_is_visible_and_labels_have_space():
    from wgs_agent.reporting.word_figures import draw_chart

    payload = {
        "labels": ["A long scientific species label with spaces", "Another long scientific label"],
        "series": [{"name": "功能丰度", "values": [0.001, 0.0005]}],
        "unit": "RPK",
        "status": "available",
    }
    im = draw_chart(visual("8.6.1"), payload, 1800)
    teal = sum(count for count, rgb in im.getcolors(im.width * im.height) if rgb == (36, 106, 115))
    assert teal > im.width * im.height * 0.05
