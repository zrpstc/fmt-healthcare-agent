"""Regression coverage for multiline graph labels and report publication."""

import copy
import json

import pytest
from PIL import Image, ImageDraw, ImageFont

from wgs_agent.reporting.fonts import resolve_cjk_fonts
from wgs_agent.reporting.graph_labels import translate_graph_labels
from wgs_agent.reporting.graph_visual import _wrap, render_graph_figures
from test_report_knowledge_graph import claim, document, reference, topic


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\r", "\u2028"])
def test_wrap_respects_explicit_breaks_and_applies_one_total_line_limit(separator):
    draw = ImageDraw.Draw(Image.new("RGB", (400, 200)))
    font = ImageFont.truetype(resolve_cjk_fonts()[0], 24)
    assert _wrap(draw, f"第一行{separator}第二行", font, 300) == "第一行\n第二行"
    wrapped = _wrap(draw, separator.join(("第一行", "第二行", "第三行")), font, 300, 2)
    assert len(wrapped.splitlines()) == 2
    assert wrapped.endswith("…")


@pytest.mark.parametrize("self_loop", [False, True])
def test_multiline_node_relation_and_attributes_render_without_changing_evidence(
    tmp_path, self_loop
):
    row = (
        claim(object="Bifidobacterium longum", object_type="MicrobialTaxon")
        if self_loop
        else claim()
    )
    doc = document([row])
    translate_graph_labels(doc, None)
    graph = topic(doc)["knowledge_subgraph"]
    graph["nodes"][0]["display_label"] = "长双歧杆菌\r\n研究成员"
    graph["edges"][0]["display_attributes"] = "相对丰度升高\n观察研究"
    before = copy.deepcopy(graph)
    figures = render_graph_figures(doc, tmp_path)
    assert figures
    assert graph["nodes"] == before["nodes"]
    assert graph["edges"] == before["edges"]
    with Image.open(tmp_path / figures[topic(doc)["id"]]) as image:
        assert image.format == "PNG"
        assert image.width > 0 and image.height > 0


@pytest.mark.asyncio
async def test_self_loop_with_attribute_caption_publishes_complete_report(tmp_path, monkeypatch):
    from wgs_agent.reporting import graph_labels, inputs
    from wgs_agent.tools import detailed_report
    from wgs_agent.tools.domain_tools import ReportGeneratorTool

    monkeypatch.setenv("WGS_REPORT_GRAPH_RETRIEVAL_DISABLED", "1")
    monkeypatch.setenv("WGS_REPORT_GRAPH_LLM_DISABLED", "1")
    monkeypatch.setattr(detailed_report, "resolve_report_model", lambda: None)
    monkeypatch.setattr(detailed_report, "load_gene_family_evidence", lambda _: {})
    monkeypatch.setattr(inputs, "load_existing_report_inputs", lambda _: {})

    def translate_with_caption(doc, config):
        translate_graph_labels(doc, None)
        for section in doc["sections"]:
            for entry in section["topics"]:
                for edge in entry["knowledge_subgraph"]["edges"]:
                    edge["display_attributes"] = "相对丰度升高，观察研究"

    monkeypatch.setattr(graph_labels, "translate_graph_labels", translate_with_caption)
    path = tmp_path / "TEST__001_analysis.json"
    path.write_text(
        json.dumps(
            {
                "sample_id": "TEST__001",
                "species": {
                    "species_list": [
                        {"species": "Bifidobacterium longum", "abundance": 2, "unit": "%"}
                    ]
                },
                "knowledge": {
                    "matched_docs": [
                        reference(
                            claim(object="Bifidobacterium longum", object_type="MicrobialTaxon")
                        )
                    ]
                },
            }
        )
    )
    result = await ReportGeneratorTool().invoke(
        {"sample_id": "TEST__001", "analysis_json_path": str(path)}
    )
    assert not result.is_error, result.content
    doc = json.loads((tmp_path / "TEST__001_report.json").read_text())
    figure = topic(doc)["knowledge_subgraph"]["figure"]
    assert (tmp_path / figure).read_bytes().startswith(b"\x89PNG")
    assert figure in (tmp_path / "TEST__001_health_report.md").read_text()
    pdf = (tmp_path / "TEST__001_health_report.pdf").read_bytes()
    assert pdf.startswith(b"%PDF-") and b"/Subtype /Image" in pdf
    assert (tmp_path / "TEST__001_report_evidence.json").is_file()
