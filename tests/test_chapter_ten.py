import math

import pytest

from wgs_agent.reporting import chapter_eight as ch8
from wgs_agent.reporting import chapter_ten as ch10
from wgs_agent.reporting import word_figures as wf
from wgs_agent.reporting import word_template as wt
from wgs_agent.reporting.document import build_document, render_markdown


def row(name, percentile=60, **extra):
    return {"name": name, "value": 1, "unit": "relative_abundance", "percentile": percentile,
            "p5": 0, "p95": 2, "status": "normal", **extra}


def document(rows):
    return build_document("chapter10-validation", {}, {}, {}, {}, {}, {}, {}, {},
                          context={"health_inputs": {"functional_modules": {"measurements": rows}}})


def test_layout_has_three_metabolic_panels_and_trait_panel():
    blocks = wt.contract()["chapters"][9]["blocks"]
    tables = [block for block in blocks if block["type"] == "table"]
    charts = [item for block in blocks for item in block.get("items", [])]
    assert len(tables) == len(charts) == 4
    assert [table["sub"] for table in tables] == [1, 2, 3, 4]
    assert all(table["rows"][0] == ch8.HEADERS for table in tables[:3])
    assert tables[3]["rows"][0] == ch10.TRAIT_HEADERS
    assert "量表背景与综合解读" not in str(blocks)


def test_specific_products_do_not_also_match_precursors_or_related_names():
    assert ch10._identities({"name": "5-hydroxytryptamine synthesis"}) == {"serotonin"}
    assert ch10._identities({"name": "5-羟色胺合成"}) == {"serotonin"}
    assert ch10._identities({"name": "tryptophan to indole-3-propionate synthesis"}) == {"ipa"}
    assert ch10._identities({"name": "β-氨基丁酸 synthesis"}) == set()


def test_actual_normalized_evidence_reaches_table_and_directional_chart():
    doc = document([
        row("GABA synthesis", 60, detected_genes=["gadA", "gadB", "gadC", "gabT", "gabD", "gltB"],
            contributors=[{"species": "Lactobacillus brevis", "abundance": 2}, {"species": "Bacteroides fragilis", "abundance": 1}]),
        row("GABA synthesis alternative", 80), row("GABA degradation", 20),
        row("histamine synthesis", 0), row("serotonin synthesis", 50),
    ])
    table = next(row for row in ch10.table_rows(doc, 1) if "GABA" in row[0])
    assert "合成" in table[1] and "分解" in table[1]
    assert "Lactobacillus brevis" in table[2]
    assert table[3].split("、") == ["gadA", "gadB", "gadC", "gabT", "gabD"]
    payload = wf.chart_data(doc, {"id": "10.1.chart"})
    index = next(i for i, label in enumerate(payload["labels"]) if "GABA" in label)
    assert next(s for s in payload["series"] if s["name"] == "合成")["values"][index] == 70
    assert next(s for s in payload["series"] if s["name"] == "分解")["values"][index] == 20
    assert next(s for s in payload["series"] if s["name"] == "合成")["values"][payload["labels"].index("组胺")] == 0


def test_aromatic_and_estrogen_targets_have_real_evidence():
    doc = document([
        row("indole-3-propionate synthesis", 75, detected_genes=["fldA", "fldB", "fldC"]),
        row("indole synthesis", 40, detected_genes=["tnaA"]),
        row("estradiol degradation", 25, detected_genes=["hsd17b"]),
    ])
    aromatic = ch10.table_rows(doc, 2)
    assert next(r for r in aromatic if "IPA" in r[0])[3] == "fldA、fldB、fldC"
    assert next(r for r in aromatic if r[0] == "吲哚")[3] == "tnaA"
    assert next(r for r in ch10.table_rows(doc, 3) if r[0] == "雌二醇")[3] == "hsd17b"
    for sub in (2, 3):
        assert wf.chart_data(doc, {"id": f"10.{sub}.chart"})["status"] == "available"


def test_trait_scores_are_derived_from_metabolites_not_questionnaires():
    doc = document([row("GABA synthesis", 80), row("serotonin synthesis", 50),
                    row("melatonin synthesis", 20), row("dopamine synthesis", 60),
                    row("kynurenine synthesis", 30), row("indole-3-propionate synthesis", 40)])
    payload = ch10.trait_payload(doc)
    traits = {item["id"]: item for item in payload["traits"]}
    assert traits["sleep"]["score"] == 50
    assert traits["stress"]["score"] == 50
    assert traits["mood"]["score"] == 55
    assert all(item["coverage"] == "完整" for item in payload["traits"])
    doc["template_inputs"]["psychological_scales"] = {"sleep": 99, "stress": 99, "mood": 99}
    assert ch10.trait_payload(doc)["traits"] == payload["traits"]
    chart = wf.chart_data(doc, {"id": "10.4.chart"})
    assert chart["series"][0]["values"] == [50, 50, 55]
    assert "50.0/100" in ch10.interpretation(doc, 4)
    assert "问卷" in ch10.TRAIT_NOTE


def test_missing_invalid_and_insufficient_scores_are_not_zero_or_fabricated():
    doc = document([row("GABA synthesis", 80), row("serotonin synthesis", 101), row("melatonin synthesis", -1)])
    assert all(item["score"] is None for item in ch10.trait_payload(doc)["traits"])
    assert ch10.trait_payload(doc)["status"] == "missing"
    assert all(item["observed"] == 1 for item in ch10.trait_payload(doc)["traits"])
    assert all(r[1] == "暂不评分" for r in ch10.trait_table_rows(doc))
    for sub in (1, 2, 3):
        assert all(r[3] == "未提供检出基因证据" for r in ch10.table_rows(doc, sub))


def test_partial_coverage_and_qc_failure_are_explicit():
    doc = document([row("GABA synthesis", 80), row("serotonin synthesis", 40)])
    traits = ch10.trait_payload(doc)["traits"]
    assert all(t["score"] == 60 and t["coverage"] == "部分" for t in traits)
    assert "不完整" in ch10.interpretation(doc, 4)
    doc["metadata"]["qc_status"] = "failed"
    assert ch10.trait_payload(doc)["status"] == "missing"
    for sub in (1, 2, 3, 4):
        payload = wf.chart_data(doc, {"id": f"10.{sub}.chart"})
        assert payload["status"] == "missing"
        assert all(value is None for series in payload["series"] for value in series["values"])


def test_unknown_direction_is_retained_and_gene_candidates_are_not_detection():
    doc = document([row("GABA pathway", 55, genes=["gadA", "gadB"]),
                    row("serotonin synthesis", 70, genes=[{"gene": "tph", "detected": False}])])
    payload = ch10.chart_payload(doc, {"id": "10.1.chart"})
    unknown = next(series for series in payload["series"] if series["name"] == ch8._direction({}))
    assert 55 in unknown["values"]
    assert all(r[3] == "未提供检出基因证据" for r in ch10.table_rows(doc, 1))


def test_full_markdown_and_all_four_chart_images(tmp_path):
    doc = document([row("GABA synthesis", 80, detected_genes=["gadA", "gadB", "gadC"]),
                    row("serotonin synthesis", 50), row("melatonin synthesis", 20),
                    row("indole-3-propionate synthesis", 40), row("estradiol degradation", 30)])
    for sub in (1, 2, 3, 4):
        spec = next(item for block in wt.contract()["chapters"][9]["blocks"] if block["sub"] == sub for item in block.get("items", []))
        image = wf.draw_chart(spec, wf.chart_data(doc, spec), 1600)
        assert image.width == 1600 and image.height >= 300
        image.save(tmp_path / f"chapter10-{sub}.png")
    from wgs_agent.reporting.template_body import prepare_presentation
    prepare_presentation(doc)
    rendered = "\n\n".join(wt.render_body(doc))
    chapter = rendered.split("## 10 ", 1)[1].split("## 11 ", 1)[0]
    assert "10.4 睡眠、压力与情绪相关代谢评分及解读" in chapter
    assert "纳入物质（评分）" in chapter and "gadA、gadB、gadC" in chapter
    assert "量表背景与综合解读" not in chapter
    assert chapter.count("结果解读：") == 4
