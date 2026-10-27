"""Chapter seven evidence, missingness, and bounded presentation regressions."""

from wgs_agent.reporting.chapter_seven import (
    cazy_payload,
    detected_genes,
    nutrition_payload,
    pathway_graph,
    render_figures,
    render_sections,
)
from wgs_agent.reporting.document import build_document, render_markdown


def document(rows=(), extra=None):
    return build_document(
        sample_id="CH7_TEST",
        species={},
        compare={},
        enterotype={},
        pathways={"pathways": list(rows)},
        metabolites={},
        drugs={},
        diseases={},
        knowledge={},
        context={"health_inputs": extra or {}},
    )


def pathway(name="L-valine biosynthesis", **kwargs):
    return {
        "id": "VALSYN-PWY",
        "name": name,
        "abundance": 0.004,
        "unit": "relative_abundance",
        **kwargs,
    }


def test_reference_bar_requires_real_comparable_reference_and_never_invents_median():
    doc = document([pathway(p5=0.001, p95=0.009, status="normal")])
    metric = nutrition_payload(doc)["categories"][0]["metrics"][0]
    assert metric["reference"]["interval"] == [0.001, 0.009]
    assert metric["reference"]["median"] is None
    doc = document(
        [
            pathway(
                p5=0.001,
                p95=0.009,
                status="normal",
                reference_median=0.003,
                reference_unit="copies/g",
            )
        ]
    )
    assert nutrition_payload(doc)["categories"][0]["metrics"][0]["reference"]["status"] == "missing"


def test_synthesis_and_degradation_are_distinct_and_ambiguous_records_not_reused():
    rows = [
        pathway(),
        pathway("L-valine degradation", id="VALDEG-PWY", abundance=0.001),
        pathway("L-valine biosynthesis and degradation", id="AMBIG", abundance=10),
    ]
    metrics = nutrition_payload(document(rows))["categories"][0]["metrics"]
    assert [m["pathway_id"] for m in metrics] == ["VALSYN-PWY", "VALDEG-PWY"]
    assert [m["value"] for m in metrics] == [0.004, 0.001]


def test_top_contributors_are_ranked_and_bounded_with_bilingual_names():
    taxa = [
        "Ruminococcus bromii",
        "Bifidobacterium longum",
        "Escherichia coli",
        "Blautia wexlerae",
        "Bacteroides eggerthii",
        "unclassified",
    ]
    row = pathway(
        contributors=[
            {"taxon": name, "abundance": i + 1, "unit": "relative_abundance"}
            for i, name in enumerate(taxa)
        ]
    )
    cat = nutrition_payload(document([row]))["categories"][0]
    assert len(cat["taxa"]) == 3
    assert [t["name"] for t in cat["taxa"]] == list(reversed(taxa[2:5]))
    assert all("（" in t["label"] for t in cat["taxa"])
    assert "unclassified" not in str(cat["taxa"])


def test_detected_genes_are_not_inferred_from_pathways_or_negative_records():
    assert detected_genes([pathway()]) == []
    assert (
        detected_genes(
            [{"gene": "not-positive", "value": 0}, {"gene": "negative", "detected": False}]
        )
        == []
    )
    assert detected_genes([{"detected_genes": ["a", "b", "c", "d", "e", "f"]}]) == [
        "a",
        "b",
        "c",
        "d",
        "e",
    ]
    assert detected_genes(
        [{"genes": [{"gene": "present", "detected": True}, {"gene": "absent", "detected": False}]}]
    ) == ["present"]


def test_cazy_requires_sequence_support_before_assigning_a_host():
    raw = {"family": "GH13", "gene": "gene-1", "detected": True, "host": "Escherichia coli"}
    chain = cazy_payload(document(extra={"cazy": {"families": [raw]}}))["chains"][0]
    assert chain["genes"] == ["gene-1"] and chain["linked"] is False
    raw.update(host_link_supported=True, host_link_evidence="contig-1")
    chain = cazy_payload(document(extra={"cazy": {"families": [raw]}}))["chains"][0]
    assert chain["linked"] is True and "大肠" in chain["taxon"]


def test_graph_uses_observed_stratified_edges_not_cooccurring_species():
    row = pathway(
        contributors=[
            {"taxon": "Ruminococcus bromii", "abundance": 0.002, "unit": "relative_abundance"},
            {"taxon": "unclassified", "abundance": 0.001, "unit": "relative_abundance"},
        ]
    )
    doc = document([row])
    graph = pathway_graph(doc)
    assert len(graph["edges"]) == 1 and graph["edges"][0]["target"] == "VALSYN-PWY"
    assert graph["edges"][0]["source"] == "Ruminococcus bromii"
    assert pathway_graph(document([pathway()]))["edges"] == []


def test_figures_and_markdown_include_all_three_changes(tmp_path):
    doc = document([pathway(reference_median=0.003, p5=0.001, p95=0.009, status="normal")])
    manifest = {}
    files = render_figures(doc, tmp_path, manifest)
    doc["word_figures"] = manifest
    assert set(files) == {"7.2.flow", "7.3.1", "7.4.graph"}
    assert all((tmp_path / name).is_file() for name in files.values())
    text = "\n".join(render_sections(doc))
    assert text.index("![图 7-3") < text.index("| 营养物质")
    assert "主要贡献菌（前 3 种）" in text and "7.4 菌群与代谢通路关系图谱" in text
    assert "未提供基因检出明细" in text
    assert "### 7.4 菌群与代谢通路关系图谱" in render_markdown(doc)


def test_qc_failure_cannot_leak_cazy_genes_or_edges():
    doc = document(
        [pathway()],
        extra={"cazy": {"families": [{"family": "SECRET_ASSAY_NAME", "detected": True}]}},
    )
    doc["metadata"]["qc_status"] = "failed"
    text = "\n".join(render_sections(doc))
    assert "SECRET_ASSAY_NAME" not in text and "质控未通过" in text


def test_missing_reference_is_not_displayed_as_zero():
    metric = nutrition_payload(document([pathway()]))["categories"][0]["metrics"][0]
    assert metric["reference"]["median"] is None
    assert metric["reference"]["interval"] is None
    assert metric["reference"]["status"] == "missing"


def _refresh_module():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts/refresh_chapter_seven.py"
    spec = importlib.util.spec_from_file_location("refresh_chapter_seven", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scoped_refresh_preserves_every_character_outside_requested_sections():
    module = _refresh_module()
    before = "## 3 菌群\n原有第三章\n## 7 营养\n### 7.1 原有底物\n保留此处\n### 7.2 酶\n旧正文\n### 7.4 摘要\n旧结尾\n## 8 代谢物\n保留第八章\n"
    result = module.replace_sections(before, ["### 7.2 新链路图", "新内容", "### 7.4 新图谱"])
    assert result.startswith(before.split("### 7.2 ")[0])
    assert result.endswith("## 8 代谢物\n保留第八章\n")
    assert "旧正文" not in result and "原有第三章" in result


def test_concurrent_report_edit_aborts_before_publication(tmp_path, monkeypatch):
    import json
    import sys
    import pytest
    from pathlib import Path
    from wgs_agent.tools import report_maker

    module = _refresh_module()
    module.ROOT = tmp_path
    report = tmp_path / "CH7_TEST_report.json"
    report.write_text(json.dumps(document()))
    md = tmp_path / "CH7_TEST_health_report.md"
    md.write_text("## 7 营养\n### 7.2 酶\n旧内容\n## 8 代谢物\n原有内容\n")
    original = report.read_bytes()

    def concurrent(markdown, sid, pdf):
        Path(pdf).write_bytes(b"test-pdf")
        md.write_text(md.read_text() + "另一进程刚写入\n")

    monkeypatch.setattr(report_maker, "_generate_fpdf_report", concurrent)
    monkeypatch.setattr(
        sys, "argv", ["refresh_chapter_seven.py", "CH7_TEST", "--report-path", str(report)]
    )
    with pytest.raises(RuntimeError, match="concurrently"):
        module.main()
    assert report.read_bytes() == original
    assert md.read_text().endswith("另一进程刚写入\n")
    assert not (tmp_path / "CH7_TEST_health_report.pdf").exists()
