import copy
from wgs_agent.reporting import chapter_nine as c9


def row(name, ident="PWY-TEST", value=0.002, **extra):
    return {"id": ident, "name": name, "kind": "pathway", "measurement_type": "functional_potential", "value": value, "unit": "relative_abundance", **extra}


def document(*rows):
    return {"metadata": {}, "evidence": {f"P{i}": r for i, r in enumerate(rows)}, "template_inputs": {}, "sections": [{"id": "ecology", "topics": [{"id": key, "status": "missing", "evidence_ids": [], "allowed_narrative_ids": []} for key in c9.TOPIC_FEATURES]}]}


def test_real_metacyc_glycan_and_lipid_a_annotations_are_recovered():
    d = document(row("superpathway of N-acetylneuraminate degradation", "P441-PWY"), row("superpathway of fucose and rhamnose degradation", "FUC-RHAMCAT-PWY"), row("superpathway of (Kdo)2-lipid A biosynthesis", "KDO-NAGLIPASYN-PWY"))
    result = c9.prepare_document(d)
    assert result["features"]["host_glycan"]["evidence_ids"] == ["P0", "P1"]
    assert result["features"]["lipid_a"]["evidence_ids"] == ["P2"]
    assert result["features"]["mucin_enzyme"]["status"] == "missing"
    assert next(t for t in d["sections"][0]["topics"] if t["id"] == "ecology.mucin")["evidence_ids"] == ["P0", "P1"]


def test_synthesis_is_not_substrate_degradation_or_inflammation_measurement():
    d = document(row("fucose biosynthesis"), row("glycogen biosynthesis", "PWY2"), row("lipid A degradation", "PWY3"))
    r = c9.extract(d)
    assert not r["features"]["host_glycan"]["evidence_ids"]
    assert not r["features"]["substrate"]["evidence_ids"]
    assert not r["features"]["lipid_a"]["evidence_ids"]


def test_species_and_literature_are_not_functional_observations():
    d = document(row("fucose degradation", kind="species", measurement_type="relative_abundance"), row("lipid A biosynthesis", "P2", kind="reference"))
    assert c9.extract(d)["status"] == "missing"


def test_nonpositive_and_invalid_numbers_do_not_become_positive_evidence():
    for value in [None, 0, -1, float("nan"), float("inf"), True, "bad"]:
        assert c9.extract(document(row("fucose degradation", value=value)))["status"] == "missing"


def test_stratification_special_rows_and_duplicates_are_not_counted_twice():
    r = row("fucose degradation", "FUCCAT-PWY")
    d = document(r, copy.deepcopy(r), row("fucose degradation", "FUCCAT-PWY|s__X"), row("fucose degradation", "UNMAPPED"))
    assert c9.extract(d)["features"]["host_glycan"]["evidence_ids"] == ["P0"]


def test_qc_failure_blocks_tables_paragraphs_and_flow():
    for status in ["failed", "fail", "不通过", "未通过"]:
        d = document(row("fucose degradation"))
        d["metadata"]["qc_status"] = status
        assert c9.extract(d)["status"] == "qc_failed"
        assert not c9._rows(d, ("host_glycan",))
        assert "质控未通过" in c9.interpretation(d, 3)
        assert "质控未通过" in str(c9.table_rows(d, 3))


def test_taxonomy_predictions_are_not_observed_gene_annotations():
    d = document(row("sialidase", kind="function", data_type="taxonomic_estimate"))
    assert not c9.extract(d)["features"]["mucin_enzyme"]["evidence_ids"]


def test_downstream_sugars_do_not_imply_mucin_cleavage_but_annotated_enzyme_can():
    d = document(row("N-acetylneuraminate degradation"), row("sialidase", "UniRef90_TEST", kind="function", measurement_type="sequence_detection"))
    f = c9.extract(d)["features"]
    assert f["host_glycan"]["evidence_ids"] == ["P0"]
    assert f["mucin_enzyme"]["evidence_ids"] == ["P1"]
    assert "不能证明黏蛋白切割" in c9.interpretation(d, 3)


def test_fermentation_direction_and_irrelevant_engineered_paths():
    d = document(row("pyruvate fermentation to acetate and lactate II"), row("pyruvate fermentation to isobutanol (engineered)", "P2"), row("superpathway of fermentation (Chlamydomonas reinhardtii)", "P3"))
    assert c9.extract(d)["features"]["fermentation"]["evidence_ids"] == ["P0"]


def test_units_and_contributors_are_traced_without_aggregation():
    d = document(row("fucose degradation", contributors=[{"taxon": "g__Bacteroides.s__Bacteroides_vulgatus", "abundance": 0.001, "unit": "relative_abundance"}]), row("N-acetylneuraminate degradation", "P2", value=12, unit="RPK"))
    text = c9.interpretation(d, 3)
    assert "0.2%" in text and "12 RPK" in text
    assert "Bacteroides vulgatus" in text
    assert "[P0]" in text and "[P1]" in text
    assert d["evidence"]["P0"]["value"] == 0.002


def test_empty_input_is_missing_rather_than_absence_or_zero_capacity():
    d = document()
    assert c9.extract(d)["status"] == "missing"
    assert "不能据此判定该功能不存在" in c9.interpretation(d, 3)
    assert "无法评价" in str(c9.table_rows(d, 1))


def test_preparation_is_idempotent_and_retains_other_topics():
    d = document(row("fucose degradation"))
    d["sections"][0]["topics"].append({"id": "ecology.gas", "status": "available", "evidence_ids": ["G1"]})
    c9.prepare_document(d)
    first = copy.deepcopy(d)
    c9.prepare_document(d)
    assert d == first
    assert d["sections"][0]["topics"][-1]["evidence_ids"] == ["G1"]


def test_production_table_paragraph_flow_and_body_bindings():
    from wgs_agent.reporting.word_template import Data, bind_table, contract, paragraph
    from wgs_agent.reporting.word_figures import flow_labels
    d = document(row("fucose degradation"), row("pyruvate fermentation to acetate and lactate II", "P2"))
    chapter = next(c for c in contract()["chapters"] if c["number"] == 9)
    for block in chapter["blocks"]:
        if block["type"] == "table":
            rows = bind_table(d, block)
            assert rows and all(len(r) == len(block["rows"][0]) for r in rows)
        elif block["type"] == "paragraph":
            assert "【待填】" not in paragraph(d, block, 9)
        elif block["type"] == "visuals":
            for spec in block["items"]:
                labels = flow_labels(d, spec)
                assert len(labels) == len(spec["shapes"])
                assert "效果未验证" in str(labels)
    for sub in range(1, 5):
        data = Data(d).load(9, sub)
        assert data.tables and "待填" not in str(data.tables)


def test_document_builder_exposes_recovered_topic_evidence(monkeypatch):
    from wgs_agent.reporting.document import build_document
    monkeypatch.setattr("wgs_agent.reporting.knowledge_graph.attach_subgraphs", lambda d: None)
    d = build_document("c9-unit", {}, {}, {}, {"pathways": [{"id": "FUCCAT-PWY", "name": "fucose degradation", "abundance": 0.002, "unit": "relative_abundance"}]}, {}, {}, {}, {}, context={})
    assert d["chapter_nine_results"]["features"]["host_glycan"]["status"] == "available"
    assert next(t for s in d["sections"] if s["id"] == "ecology" for t in s["topics"] if t["id"] == "ecology.mucin")["status"] == "available"
