"""User-facing template contracts and result-priority regression cases."""

import copy
import json
import re
from collections import Counter

import pytest

from wgs_agent.reporting.bibliography import render_bibliographies
from wgs_agent.reporting.catalog import TOPICS
from wgs_agent.reporting.document import build_document, render_markdown
from wgs_agent.reporting.knowledge_graph import graph_markdown
from wgs_agent.reporting.overview import select_findings
from wgs_agent.reporting.template_body import _linked
from wgs_agent.reporting.template_catalog import CHAPTERS, TOPIC_PLACEMENT


def build(**kwargs):
    values = dict(
        sample_id="TEMPLATE_TEST",
        species={},
        compare={},
        enterotype={},
        pathways={},
        metabolites={},
        drugs={},
        diseases={},
        knowledge={},
    )
    values.update(kwargs)
    return build_document(**values)


def overview(markdown):
    return markdown.split("## 检测结果总览\n", 1)[1].split("## 1 ", 1)[0]


def block(markdown, number):
    return re.split(r"\n#{2,3} ", markdown.split(f"### {number} ", 1)[1], maxsplit=1)[0]


def test_template_chapters_replace_the_old_body_and_keep_a_complete_toc():
    doc = build()
    md = render_markdown(doc)
    headings = re.findall(r"^## (\d+) (.+)$", md, re.M)
    assert [int(n) for n, _ in headings] == list(range(1, 15))
    assert headings[0][1] == "菌群组成与群落结构"
    assert headings[1][1] == "菌群多样性与生态功能结构"
    assert headings[-1][1] == "综合解读与行动建议"
    assert "### 8.8 脂多糖与其他细胞组分合成特征" in md
    assert md.index("## 目录") < md.index("## 检测结果总览") < md.index("## 1 ")
    assert "[5 耐药组与可移动遗传元件](#5-耐药组与可移动遗传元件)" in md
    assert "【" not in md and "图中位置仅用于版式展示" not in md
    assert "其余固定分析方向" not in md
    assert "未启用" in block(md, "14.4")


def test_each_existing_graph_topic_has_exactly_one_body_placement():
    occurrences = Counter(tid for _, _, _, blocks in CHAPTERS for _, ids in blocks for tid in ids)
    assert set(occurrences) == set(TOPICS) == set(TOPIC_PLACEMENT)
    assert all(count == 1 for count in occurrences.values())


def test_empty_or_ordinary_results_do_not_fill_overview_with_coverage():
    for doc in (
        build(),
        build(
            species={
                "species_list": [
                    {"species": "Ordinary dominant species", "abundance": 85, "unit": "%"}
                ]
            }
        ),
    ):
        md = render_markdown(doc)
        front = overview(md)
        assert "结果覆盖" not in front
        assert "暂未评估" not in front
        assert "Ordinary dominant species" not in front
        assert "古菌" not in front and "耐药组" not in front
        assert doc["overview_findings"] == []


def test_overview_prioritizes_direct_findings_deduplicates_and_is_bounded():
    rows = [
        {
            "species": f"Bifidobacterium test{i}",
            "abundance": 2 + i,
            "unit": "%",
            "p5": 0,
            "p95": 1,
            "status": "high",
        }
        for i in range(9)
    ]
    doc = build(
        species={"species_list": rows},
        context={
            "health_inputs": {
                "resistance": {
                    "genes": [{"gene": "tetQ", "result": "检出", "drug_class": "tetracycline"}]
                },
                "virulence": {
                    "markers": [{"marker": "toxin-test", "detected": True, "coverage": 98}]
                },
            }
        },
    )
    findings = select_findings(doc)
    assert len(findings) == 5
    assert "toxin-test" in findings[0]["finding"]
    assert "tetQ" in findings[1]["finding"]
    assert len({r["evidence_id"] for r in findings}) == 5
    assert select_findings(doc, 0) == []
    md = render_markdown(doc)
    assert "toxin-test" in overview(md)
    assert "第4.2节" in overview(md)


@pytest.mark.parametrize(
    "gene",
    [
        {"gene": "negative", "value": 10, "result": "未检出"},
        {"gene": "zero", "value": 0},
        {"gene": "unknown", "value": 10, "detection_status": "insufficient_coverage"},
    ],
)
def test_negative_zero_or_insufficient_results_are_not_priority_alerts(gene):
    doc = build(context={"health_inputs": {"resistance": {"genes": [gene]}}})
    assert select_findings(doc) == []


def test_qc_failure_hides_all_health_findings_including_optional_modules():
    doc = build(
        context={
            "qc_status": "failed",
            "health_inputs": {
                "virulence": {"markers": [{"gene": "TEST_TOXIN", "result": "检出"}]},
                "strains": {"items": [{"name": "TEST_STRAIN", "result": "a strain"}]},
            },
        }
    )
    md = render_markdown(doc)
    assert select_findings(doc) == []
    assert "TEST_TOXIN" not in md and "TEST_STRAIN" not in md
    assert "质控未通过" in md


def test_sequence_host_and_mobile_element_links_require_separate_support():
    row = {
        "host": "E. coli",
        "mobile_element": "plasmid-1",
        "host_link_supported": True,
        "host_link_evidence": "contig-01",
    }
    assert _linked(row, "host") == ("E. coli", "contig-01")
    assert "未确定" in _linked(row, "mobile_element")[0]
    assert (
        "未确定"
        in _linked(
            {"host": "E. coli", "sequence_link_supported": True, "link_evidence": "generic"}, "host"
        )[0]
    )


def test_potential_zero_measurement_and_specific_metabolic_branches_stay_separate():
    doc = build(
        pathways={
            "pathways": [
                {"name": "BSH bile salt deconjugation", "abundance": 0.4},
                {"name": "cutC TMA generation", "abundance": 0.2},
            ]
        },
        metabolites={
            "data_type": "measured",
            "method": "GC-MS",
            "unit": "mmol/kg",
            "metabolites": [{"name": "butyrate", "value": 0}],
        },
    )
    md = render_markdown(doc)
    assert "0 mmol/kg" in block(md, "8.1")
    assert "已有代谢物检测或模型记录" in block(md, "8.1")
    assert "BSH bile salt deconjugation" in block(md, "8.3")
    assert "cutC TMA generation" in block(md, "8.7")
    assert "butyrate" not in overview(md)


def test_absolute_quantities_and_composite_scores_need_validated_inputs():
    doc = build(
        context={
            "health_inputs": {
                "absolute_abundance": {
                    "measurements": [
                        {"name": "UNSUPPORTED_QUANTITY", "value": 123, "unit": "copies/g"}
                    ]
                },
                "composite_models": {"models": [{"name": "综合健康分", "value": 99}]},
            }
        }
    )
    md = render_markdown(doc)
    assert "UNSUPPORTED_QUANTITY" not in md
    assert "99" not in block(md, "14.4")
    assert "未启用" in block(md, "14.4")


def test_core_members_use_defined_reference_and_actual_detection_without_zero_filling():
    doc = build(
        species={"species_list": [{"species": "Core A", "abundance": 5, "unit": "%"}]},
        context={
            "health_inputs": {
                "core_microbiome": {
                    "definition": "test-reference-v1",
                    "members": [
                        {"species": "Core A"},
                        {"species": "Core B"},
                    ],
                }
            }
        },
    )
    body = block(render_markdown(doc), "1.2")
    assert "Core A" in body and "5 %" in body
    from wgs_agent.reporting.word_figures import chart_data
    assert doc["template_inputs"]["core_microbiome"]["members"][1]["species"] == "Core B"
    assert chart_data(doc, {"id": "1.2.2", "kind": "doughnutChart"})["status"] == "missing"
    assert "1 / 2" not in body


def test_contribution_concentration_requires_complete_consistent_units():
    doc = build(
        pathways={
            "pathways": [
                {
                    "name": "butyrate pathway",
                    "abundance": 1,
                    "contributors": [
                        {"taxon": "A", "abundance": 0.8, "unit": "relative_abundance"},
                        {"taxon": "B", "abundance": 0.2, "unit": "relative_abundance"},
                    ],
                }
            ]
        }
    )
    assert "暂不计算" in block(render_markdown(doc), "2.3")
    doc["evidence"]["P1"]["contributors_complete"] = True
    assert "80%" in block(render_markdown(doc), "2.3")


def test_rendering_preserves_graph_objects_figures_and_bibliography_content():
    from test_report_knowledge_graph import document, claim
    from wgs_agent.reporting.graph_labels import translate_graph_labels

    doc = document([claim()])
    translate_graph_labels(doc, None)
    graphs = {
        t["id"]: copy.deepcopy(t["knowledge_subgraph"])
        for s in doc["sections"]
        for t in s["topics"]
    }
    refs = render_bibliographies(doc)
    md = render_markdown(doc)
    assert md.endswith("\n\n".join(refs) + "\n")
    for section in doc["sections"]:
        for topic in section["topics"]:
            assert topic["knowledge_subgraph"] == graphs[topic["id"]]
            if topic["status"] != "missing":
                for part in graph_markdown(topic):
                    assert part in md
    assert render_markdown(doc) == md


def test_template_inputs_exclude_nested_credentials():
    doc = build(
        context={
            "health_inputs": {
                "strains": {
                    "items": [{"name": "test", "password": "SECRET_VALUE"}],
                    "token": "TOKEN_VALUE",
                }
            }
        }
    )
    assert doc["template_inputs"]["strains"] == {"items": [{"name": "test"}]}


@pytest.mark.asyncio
async def test_generator_retains_optional_modules_and_publishes_the_same_priority_audit(
    tmp_path, monkeypatch
):
    from wgs_agent.reporting import inputs
    from wgs_agent.tools import detailed_report
    from wgs_agent.tools.domain_tools import ReportGeneratorTool

    monkeypatch.setattr(inputs, "load_existing_report_inputs", lambda _: {})
    monkeypatch.setattr(detailed_report, "resolve_report_model", lambda: None)
    monkeypatch.setattr(detailed_report, "load_gene_family_evidence", lambda _: {})
    path = tmp_path / "TEMPLATE_TEST_analysis.json"
    path.write_text(
        json.dumps(
            {
                "sample_id": "TEMPLATE_TEST",
                "virulence": {"markers": [{"gene": "VF_DEMO", "detected": True}]},
                "dna_viruses": {"members": [{"name": "DNA_DEMO", "detected": False}]},
                "cazy": {"families": [{"family": "GH_DEMO", "annotation_confidence": "test"}]},
            }
        )
    )
    result = await ReportGeneratorTool().invoke(
        {"sample_id": "TEMPLATE_TEST", "analysis_json_path": str(path)}
    )
    assert not result.is_error, result.content
    doc = json.loads((tmp_path / "TEMPLATE_TEST_report.json").read_text())
    audit = json.loads((tmp_path / "TEMPLATE_TEST_report_evidence.json").read_text())
    md = (tmp_path / "TEMPLATE_TEST_health_report.md").read_text()
    assert "VF_DEMO" in block(md, "4.2") and "DNA_DEMO" in block(md, "6.3")
    assert "GH_DEMO" in block(md, "7.2")
    assert audit["presentation"] == doc["presentation"]
    assert audit["overview_findings"] == doc["overview_findings"]


def test_symptom_records_do_not_become_fabricated_functional_comparisons():
    doc = build(
        context={
            "health_inputs": {"symptoms": {"observations": [{"name": "腹胀", "answer": "偶发"}]}}
        }
    )
    content = block(render_markdown(doc), "11.2")
    assert "未提供" in content
    assert "偶发" not in content
    assert "测序结果摘要" in content


def test_aromatic_derivatives_are_not_relabelled_as_plain_metabolite_targets():
    doc = build(
        pathways={
            "pathways": [
                {"name": "indole lactate pathway", "abundance": 0.1},
                {"name": "imidazole propionate pathway", "abundance": 0.2},
                {"name": "lactate utilization", "abundance": 0.3},
            ]
        }
    )
    md = render_markdown(doc)
    assert "indole lactate pathway" not in block(md, "8.2")
    assert "imidazole propionate pathway" not in block(md, "8.1")
    assert "indole lactate pathway" in block(md, "8.4")
    assert "lactate utilization" in block(md, "8.2")
