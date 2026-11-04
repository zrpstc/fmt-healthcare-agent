import re

from wgs_agent.reporting.document import build_document, render_markdown
from wgs_agent.reporting.report_outline import display_references
from wgs_agent.reporting.word_template import narrative_sections
from wgs_agent.pipeline.disease_features import analyze_disease_features


def build(inputs=None, **overrides):
    values = dict(sample_id="DISEASE_TEST", species={}, compare={}, enterotype={}, pathways={},
                  metabolites={}, drugs={}, diseases={}, knowledge={}, context={"health_inputs": inputs or {}})
    values.update(overrides)
    return build_document(**values)


def test_removed_symptom_chapter_and_all_later_headings_toc_and_sections_shift():
    document = build()
    document["word_sections"] = narrative_sections(document)
    markdown = render_markdown(document)
    headings = re.findall(r"^## (\d+) (.+)$", markdown, re.M)
    assert [int(n) for n, _ in headings] == list(range(1, 14))
    assert headings[10][1] == "疾病相关特征与经验证模型"
    assert headings[11][1] == "专项代谢转化功能"
    assert headings[12][1] == "综合解读与行动建议"
    assert "症状相关特征与问卷对照" not in markdown
    assert "### 11.1 疾病关联模块" in markdown
    assert "图 11-1" in markdown and "图 12-1" in markdown and "图 13-1" in markdown
    assert [c["number"] for c in document["presentation"]["chapters"]] == list(range(1, 14))
    assert not any(s["id"] == "word.11" for s in document["word_sections"])


def test_numbering_does_not_change_measurements_or_ids():
    text = "## 12 疾病\n### 12.2 特征\n图 14-1\n第13章\n| 12.3 | 14 | 13% |\nword.12.2"
    mapped = display_references(text)
    assert "## 11 疾病" in mapped and "### 11.2 特征" in mapped
    assert "图 13-1" in mapped and "第12章" in mapped
    assert "| 12.3 | 14 | 13% |" in mapped and "word.12.2" in mapped


def test_real_disease_abundances_and_provenance_render_without_risk_scores():
    module = analyze_disease_features({"complete": True, "unit": "%", "ranks": {"species": [
        {"name": "Faecalibacterium prausnitzii", "abundance": 2.5}]}})
    document = build({"diseases": module})
    markdown = render_markdown(document)
    assert "Faecalibacterium prausnitzii：2.5%" in markdown
    assert "10.1038/s41586-019-1237-9" in markdown
    assert "原研究组间方向" in markdown
    assert "物种谱未报告" in markdown or "未在物种谱报告" in markdown
    assert "模型未启用" in markdown
    assert not any(r.get("kind") == "prediction" for r in document["evidence"].values())


def test_qc_failure_hides_disease_abundances():
    module = analyze_disease_features({"complete": True, "unit": "%", "ranks": {"species": [
        {"name": "Faecalibacterium prausnitzii", "abundance": 2.5}]}})
    document = build({"diseases": module}, context={"qc_status": "failed", "health_inputs": {"diseases": module}})
    markdown = render_markdown(document)
    disease = markdown.split("## 11 疾病", 1)[1].split("## 12 ", 1)[0]
    assert "2.5%" not in disease


def test_image_alternative_text_uses_public_chapter_numbers():
    text = "![12.1 模板图示](sample.png) 图 14-1"
    assert display_references(text) == "![11.1 模板图示](sample.png) 图 13-1"
