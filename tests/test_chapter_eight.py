from wgs_agent.reporting import chapter_eight as ch8
from wgs_agent.reporting import word_template, word_figures


class SampleData:
    qc_failed = False

    def __init__(self, rows):
        self.rows = rows

    def topic_rows(self, *ids):
        return self.rows

    def functions(self, words):
        return []


def pathway(name, percentile=None, **fields):
    row = {"name": name, "label": name, "measurement_type": "functional_potential", **fields}
    if percentile is not None:
        row["percentile"] = percentile
    return row


def test_every_metabolism_section_has_a_capacity_chart_and_the_same_evidence_headers():
    chapter = word_template.contract()["chapters"][7]
    charts = [item for block in chapter["blocks"] for item in block.get("items", [])]
    assert {item["id"] for item in charts} == {f"8.{n}.1" for n in range(1, 9)}
    assert all(item["type"] == "chart" and item["kind"] == "barChart" and item["grouping"] == "clustered" for item in charts)
    tables = [block for block in chapter["blocks"] if block["type"] == "table"]
    assert len(tables) == 8
    assert all(block["rows"][0] == ch8.HEADERS for block in tables)


def test_table_binds_target_paths_contributors_and_only_detected_genes():
    rows = [pathway("butyrate biosynthesis", 72, detected_genes=["but", "buk", "ptb", "hbd", "crt", "bcd"],
                    contributors=[{"species": "Species A", "abundance": 2}, {"species": "Species B", "abundance": 4}]),
            pathway("butyrate biosynthesis II", 88, genes=[{"gene": "absentGene", "detected": False}, {"gene": "zeroGene", "reads": 0}])]
    data = SampleData(rows)
    block = next(b for b in word_template.contract()["chapters"][7]["blocks"] if b.get("id") == "8.1.t1")
    table = word_template.bind_table({}, block, data)
    row = next(r for r in table if r[0] == "丁酸")
    assert "butyrate biosynthesis" in row[1] and "合成" in row[1]
    assert row[2].index("Species B") < row[2].index("Species A")
    assert row[3].split("、") == ["but", "buk", "ptb", "hbd", "crt"]
    assert len(row) == 4


def test_score_uses_reference_percentiles_by_direction_and_preserves_zero(monkeypatch):
    data = SampleData([pathway("butyrate biosynthesis", 60), pathway("butyrate biosynthesis II", 80),
                       pathway("butyrate degradation", 20), pathway("acetate biosynthesis", 0),
                       pathway("propionate biosynthesis", abundance=1000000)])
    monkeypatch.setattr(word_template, "Data", lambda document: data)
    spec = {"id": "8.1.1"}
    payload = word_figures.chart_data({}, spec)
    synthesis = next(s for s in payload["series"] if s["name"] == "合成")
    degradation = next(s for s in payload["series"] if s["name"] == "分解")
    assert synthesis["values"][payload["labels"].index("丁酸")] == 70
    assert degradation["values"][payload["labels"].index("丁酸")] == 20
    assert synthesis["values"][payload["labels"].index("乙酸")] == 0
    assert synthesis["values"][payload["labels"].index("丙酸")] is None
    assert payload["scale_min"] == 0 and payload["scale_max"] == 100
    image = word_figures.draw_chart({"id": "8.1.1"}, payload, 1200)
    assert image.width == 1200 and image.height >= 400


def test_missing_gene_support_is_not_filled_from_expected_pathway_markers():
    rows = [pathway("butyrate biosynthesis", 75, genes=["but", "buk"], gene_evidence=[{"gene": "hbd", "detected": False}])]
    result = ch8.table_rows({}, 1, SampleData(rows))
    assert next(row for row in result if row[0] == "丁酸")[3] == "未提供检出基因证据"
    assert ch8.detected_genes([{"detected_genes": ["but", "buk"]}]) == ["but", "buk"]


def test_invalid_percentiles_and_qc_failure_do_not_become_scores(monkeypatch):
    data = SampleData([pathway("butyrate biosynthesis", -1), pathway("acetate biosynthesis", 101), pathway("propionate biosynthesis", 50, comparison="unknown")])
    monkeypatch.setattr(word_template, "Data", lambda document: data)
    payload = ch8.chart_payload({}, {"id": "8.1.1"})
    assert payload["status"] == "missing"
    assert all(v is None for s in payload["series"] for v in s["values"])
    data.rows = [pathway("butyrate biosynthesis", 90)]
    data.qc_failed = True
    payload = ch8.chart_payload({}, {"id": "8.1.1"})
    assert payload["status"] == "missing"
    assert payload["reason"] == "质控未通过"


def test_structured_gene_hits_need_positive_detection_and_are_deduplicated():
    row = {"genes": [{"gene": "but", "reads": 10}, {"gene": "BUT", "detected": True},
                     {"gene": "buk", "abundance": 0}, {"gene": "ptb", "status": "negative"},
                     {"gene": "hbd", "coverage": 0.9}]}
    assert ch8.detected_genes([row]) == ["but", "hbd"]


def test_every_subsection_binds_only_its_target_rows_and_renders_missing_scores(monkeypatch):
    data = SampleData([])
    monkeypatch.setattr(word_template, "Data", lambda document: data)
    for sub in range(1, 9):
        tables = [block for block in word_template.contract()["chapters"][7]["blocks"] if block["type"] == "table" and block["sub"] == sub]
        for block in tables:
            rows = word_template.bind_table({}, block, data)
            assert all(len(row) == 4 and row[0] in [seed[0] for seed in block["rows"][1:]] for row in rows)
            assert all(row[3] == "未提供检出基因证据" for row in rows)
        payload = word_figures.chart_data({}, {"id": f"8.{sub}.1"})
        assert payload["status"] == "missing"
        assert all(v is None for series in payload["series"] for v in series["values"])
        image = word_figures.draw_chart({"id": f"8.{sub}.1"}, payload, 1200)
        assert image.width == 1200


def test_existing_direct_contributor_fields_and_read_supported_genes_are_preserved():
    row = pathway("butyrate biosynthesis", 70, contributing_taxa="Species A；Species B", reads=15, gene="but")
    result = next(row for row in ch8.table_rows({}, 1, SampleData([row])) if row[0] == "丁酸")
    assert result[2] == "Species A；Species B"
    assert result[3] == "but"


def test_actual_report_input_reaches_both_the_evidence_table_and_score_chart():
    from wgs_agent.reporting.document import build_document
    row = {"name": "butyrate biosynthesis", "value": 1, "unit": "relative_abundance", "percentile": 80,
           "p5": 0, "p95": 2, "status": "normal", "detected_genes": ["but", "buk", "ptb"],
           "contributors": [{"species": "Example species", "abundance": 1}]}
    document = build_document("chapter8-test", {}, {}, {}, {}, {}, {}, {}, {}, context={"health_inputs": {"functional_modules": {"measurements": [row]}}})
    block = next(b for b in word_template.contract()["chapters"][7]["blocks"] if b.get("id") == "8.1.t1")
    result = next(row for row in word_template.bind_table(document, block) if row[0] == "丁酸")
    assert result[3] == "but、buk、ptb"
    assert result[2] == "Example species"
    payload = word_figures.chart_data(document, {"id": "8.1.1"})
    assert payload["status"] == "available"
    assert next(s for s in payload["series"] if s["name"] == "合成")["values"][payload["labels"].index("丁酸")] == 80


def test_additional_detected_targets_are_not_dropped_by_the_other_seed():
    block = next(b for b in word_template.contract()["chapters"][7]["blocks"] if b["type"] == "table" and any("其他" in seed[0] for seed in b["rows"][1:]))
    rows = [pathway("novel detected pathway biosynthesis", 70, target_product="additional target", detected_genes=["abc"]),
            pathway("novel detected pathway biosynthesis II", 90, target_product="additional target", detected_genes=["def"])]
    data = SampleData(rows)
    result = word_template.bind_table({}, block, data)
    selected = [row for row in result if row[0] == "additional target"]
    assert len(selected) == 1
    assert selected[0][3] == "abc、def"


def test_structured_pathways_are_displayed_instead_of_the_capacity_metric_label():
    row = pathway("butyrate biosynthesis capacity", 70, main_pathways=[{"name": "acetyl-CoA to butyrate biosynthesis"}], detected_genes=["but"])
    result = next(row for row in ch8.table_rows({}, 1, SampleData([row])) if row[0] == "丁酸")
    assert "acetyl-CoA to butyrate biosynthesis（合成）" == result[1]
    assert "capacity" not in result[1]
