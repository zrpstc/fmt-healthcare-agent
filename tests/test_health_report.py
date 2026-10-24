"""Behavioral coverage for report evidence, model boundaries and artifact publication."""

import copy
import json
import math
import shutil
import subprocess

import pytest

from wgs_agent.reporting.catalog import SECTIONS, VERSION
from wgs_agent.reporting.document import build_document, render_markdown
from wgs_agent.reporting.inputs import diversity_metrics, load_existing_report_inputs
from wgs_agent.reporting.narrative import generate_narrative, validate_payload


def document(**overrides):
    values = dict(
        sample_id="TEST__001",
        species={},
        compare={},
        enterotype={},
        pathways={},
        metabolites={},
        drugs={},
        diseases={},
        knowledge={},
    )
    values.update(overrides)
    return build_document(**values)


def with_species():
    return document(
        species={
            "unit": "%",
            "species_list": [
                {
                    "species": "Bifidobacterium longum",
                    "abundance": 2,
                    "p5": 0.1,
                    "p95": 1,
                    "status": "high",
                },
            ],
        }
    )


def topic(doc, topic_id):
    return next(t for s in doc["sections"] for t in s["topics"] if t["id"] == topic_id)


def proposal(doc, topic_id="composition.species", **overrides):
    row = topic(doc, topic_id)
    key = row["evidence_ids"][0]
    value = {
        "id": topic_id,
        "mode": "observation",
        "interpretation": "本次已提供该菌群的丰度记录，可结合表内参考比较阅读。后续复测时宜保持采样背景和分析方法一致。",
        "advice": "记录近期饮食、排便和用药情况，便于后续比较。",
        "evidence_ids": [key],
        "support_quotes": [{"id": key, "quote": doc["evidence"][key]["finding"]}],
    }
    value.update(overrides)
    return {"sections": [{"id": topic_id.split(".")[0], "topics": [value]}]}


def test_fixed_outline_is_complete_even_without_inputs():
    doc = document()
    assert len(doc["sections"]) == 11
    assert [s["title"] for s in doc["sections"]] == [s.title for s in SECTIONS]
    assert all(s["status"] == "missing" for s in doc["sections"])
    markdown = render_markdown(doc)
    from wgs_agent.reporting.template_catalog import CHAPTERS
    assert all(f"## {n} {title}" in markdown for n, title, _, _ in CHAPTERS)
    assert "结果覆盖" not in markdown
    assert "综合健康评分" not in markdown
    assert "模型解释状态" not in markdown
    assert "analysis_sha256" not in markdown
    assert "TEST__001" in markdown


def test_alpha_diversity_uses_full_profile_and_explicit_definitions():
    values = [{"abundance": 50}, {"abundance": 50}, {"abundance": 0}]
    assert diversity_metrics(values, complete=False) == {}
    actual = diversity_metrics(values, complete=True)
    assert actual["richness"] == 2
    assert actual["shannon"] == pytest.approx(math.log(2))
    assert actual["simpson"] == pytest.approx(0.5)
    assert actual["evenness"] == pytest.approx(1)
    assert diversity_metrics([{"abundance": 100}], complete=True)["evenness"] is None
    for value in (-1, float("nan"), float("inf"), True):
        assert diversity_metrics([{"abundance": value}], complete=True) == {}
    # A named-species comparison is not assumed to contain every SGB.
    assert topic(with_species(), "diversity.shannon")["status"] == "missing"


def test_reads_all_pathways_and_preserves_species_contributions(tmp_path):
    profile = tmp_path / "profiles/metaphlan/TEST_profile.tsv"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        "# clade\ttaxid\tabundance\nk__Bacteria|p__A\t2|10\t100\nk__Bacteria|g__A\t2|11\t100\nk__Bacteria|s__Named_species\t2|12\t50\nk__Bacteria|s__SGB999\t2|13\t50\n"
    )
    pathways = tmp_path / "profiles/humann/TEST_pathabundance_relab.tsv"
    pathways.parent.mkdir(parents=True)
    pathways.write_text(
        "# Pathway\tsample\nUNMAPPED\t0.2\nUNINTEGRATED\t0.3\n"
        + "".join(f"PWY{i}: test pathway {i}\t0.001\n" for i in range(30))
        + "PWY29: test pathway 29|g__A.s__Named_species\t0.0008\n"
    )
    result = load_existing_report_inputs("TEST", tmp_path)
    assert result["diversity"]["richness"] == 2
    assert len(result["pathways"]["pathways"]) == 30
    assert result["pathways"]["special_rows"]["UNMAPPED"] == 0.2
    assert result["pathways"]["pathways"][-1]["contributors"][0]["abundance"] == 0.0008
    assert result["pathways"]["pathways"][-1]["unit"] == "relative_abundance"
    with pytest.raises(ValueError):
        load_existing_report_inputs("../OTHER", tmp_path)


def test_pipeline_preserves_real_zero_without_turning_missing_into_zero():
    import pandas as pd
    from wgs_agent.pipeline.report_data import _finite_nonnegative_profile

    actual = _finite_nonnegative_profile(
        pd.Series(
            {"zero": 0, "positive": 1, "missing": None, "invalid": float("inf"), "negative": -1}
        )
    )
    assert actual.to_dict() == {"positive": 1, "zero": 0}


@pytest.mark.asyncio
async def test_pathway_tool_keeps_full_records_and_stable_ids(monkeypatch):
    import pandas as pd
    from wgs_agent.pipeline import report_data
    from wgs_agent.reporting import inputs
    from wgs_agent.tools.domain_tools import PathwayAnalyzerTool

    values = pd.Series({f"PWY-{i}: test pathway {i}": i * 1e-8 for i in range(35)})
    values["UNMAPPED"] = 0.7
    monkeypatch.setattr(report_data, "load_pathway_data", lambda _: (values, None))
    monkeypatch.setattr(inputs, "load_existing_report_inputs", lambda _: {})
    result = await PathwayAnalyzerTool().invoke({"sample_id": "TEST"})
    assert not result.is_error
    payload = json.loads(result.content.split("---JSON---\n", 1)[1])
    assert payload["n_total_pathways"] == 35
    assert payload["pathways"][1]["abundance"] == 1e-8
    assert payload["pathways"][0]["id"] == "PWY-0"
    assert payload["is_complete"] is True


def test_observations_keep_zero_and_separate_potential_from_concentrations():
    doc = document(
        pathways={
            "pathways": [
                {"id": "UNMAPPED", "abundance": 1},
                {"name": "butyrate biosynthesis", "abundance": 0.01, "unit": "relative_abundance"},
            ]
        },
        metabolites={
            "data_type": "measured",
            "method": "GC-MS",
            "unit": "mmol/kg",
            "metabolites": [{"name": "butyrate", "value": 0}],
        },
        drugs={"drugs": [{"drug": "tetracycline", "score": 999999}]},
    )
    rows = doc["evidence"]
    assert not any(r.get("id") == "UNMAPPED" for r in rows.values())
    assert rows["M1"]["result_text"] == "0 mmol/kg"
    assert rows["M1"]["measurement_type"] == "measured"
    assert topic(doc, "resistance.tetracycline")["status"] == "missing"
    assert topic(doc, "nutrition.minerals")["status"] == "missing"
    potential_only = document(
        pathways={"pathways": [{"name": "butyrate biosynthesis", "abundance": 1}]}
    )
    assert topic(potential_only, "metabolites.scfa")["status"] == "partial"
    assert "仅呈现测序支持的功能潜力" in render_markdown(potential_only)


def test_only_validated_applicable_models_appear_as_predictions():
    doc = document(
        context={
            "health_inputs": {
                "disease_models": {
                    "predictions": [
                        {
                            "name": "A",
                            "value": 0.1,
                            "model_version": "v1",
                            "externally_validated": True,
                            "applicable": True,
                        },
                        {"name": "B", "value": 0.99, "model_version": "v1"},
                    ]
                }
            }
        }
    )
    assert len(topic(doc, "diseases.models")["evidence_ids"]) == 1
    assert doc["audit"]["omitted_unvalidated_predictions"] == 1


def test_failed_qc_gates_model_interpretation_and_metadata_stays_out_of_prompt():
    from wgs_agent.reporting.narrative import build_prompt

    doc = document(
        species={"species_list": [{"species": "A", "abundance": 1}]},
        context={"qc_status": "failed", "name": "PRIVATE NAME"},
    )
    assert all(section["status"] == "missing" for section in doc["sections"])
    assert "质控未通过" in render_markdown(doc)
    assert "PRIVATE NAME" not in build_prompt(doc, doc["sections"])
    assert generate_narrative(doc, {"model": "test"})["audit"]["llm_status"] == "no_eligible_data"


def test_measured_zero_precedes_unrelated_units_and_nonfinite_json_is_clean():
    doc = document(
        pathways={
            "pathways": [
                {"name": "butyrate biosynthesis", "abundance": 0.02, "unit": "relative_abundance"}
            ]
        },
        metabolites={
            "data_type": "measured",
            "method": "GC-MS",
            "unit": "mmol/kg",
            "metabolites": [{"name": "butyrate", "value": 0, "optional_field": float("nan")}],
        },
    )
    assert topic(doc, "metabolites.scfa")["evidence_ids"][0] == "M1"
    assert "0 mmol/kg" in topic(doc, "metabolites.scfa")["finding"]
    json.dumps(doc, allow_nan=False)


def test_symptom_association_binds_reported_symptom_and_observed_taxon():
    doc = document(
        species={"species_list": [{"species": "Species A", "abundance": 1}]},
        context={
            "health_inputs": {
                "symptoms": {
                    "observations": [
                        {"name": "腹胀", "answer": "偶发", "related_species": ["Species A"]}
                    ]
                }
            }
        },
    )
    assert set(topic(doc, "symptoms.bloating")["evidence_ids"]) == {"Y1", "S1"}


@pytest.mark.parametrize(
    "change,error",
    [
        ({"evidence_ids": ["M999"]}, "invalid_evidence_ids"),
        ({"mode": "association"}, "missing_literature_binding"),
        ({"mode": []}, "missing_sample_binding"),
        ({"interpretation": "您的患病概率为90%，需要采取措施。"}, "numeric_claim"),
        ({"interpretation": "根据本次检测可以确诊为缺铁，需要治疗。"}, "unsupported_clinical"),
        ({"interpretation": "建议服用益生菌来改善本次检测结果。"}, "unsupported_clinical"),
        ({"interpretation": "本次结果正常，可以放心无需进一步关注。"}, "unsupported_normal"),
        (
            {"support_quotes": [{"id": "S1", "quote": "这是不存在于任何记录中的伪造证据"}]},
            "unsupported_quote",
        ),
    ],
)
def test_model_rejects_unsupported_or_unsafe_prose(change, error):
    doc = with_species()
    raw = json.dumps(proposal(doc, **change), ensure_ascii=False)
    result = validate_payload(raw, doc, doc["sections"])
    assert not result["accepted"]
    assert any(error in item for item in result["errors"])


def test_citation_is_scoped_to_topic_and_title_is_not_support():
    doc = with_species()
    doc["evidence"]["K1"] = {"kind": "literature", "title": "a title without study conclusions"}
    row = topic(doc, "composition.species")
    row["allowed_narrative_ids"].append("K1")
    value = proposal(
        doc,
        mode="association",
        evidence_ids=["S1", "K1"],
        support_quotes=[
            {"id": "S1", "quote": doc["evidence"]["S1"]["finding"]},
            {"id": "K1", "quote": "a title without study conclusions"},
        ],
    )
    assert not validate_payload(json.dumps(value), doc, doc["sections"])["accepted"]
    value = proposal(doc)
    value["sections"][0]["topics"].append(copy.deepcopy(value["sections"][0]["topics"][0]))
    assert not validate_payload(json.dumps(value), doc, doc["sections"])["accepted"]
    value = proposal(doc)
    value["sections"][0]["id"] = "nutrition"
    assert not validate_payload(json.dumps(value), doc, doc["sections"])["accepted"]


class Response:
    status_code = 200
    text = ""

    def __init__(self, content, finish_reason="stop"):
        self.content = content
        self.finish_reason = finish_reason

    def raise_for_status(self):
        pass

    def json(self):
        return {
            "choices": [
                {
                    "message": {"content": self.content, "reasoning_content": "not report text"},
                    "finish_reason": self.finish_reason,
                }
            ]
        }


def fake_response(payload):
    packet = json.loads(payload["messages"][1]["content"].split("固定分析目录与证据：\n", 1)[1])
    sections = []
    for section in packet["outline"]:
        topics = []
        for t in section["topics"]:
            key = next(
                key
                for key in t["allowed_evidence_ids"]
                if packet["evidence"][key]["kind"] != "literature"
            )
            topics.append(
                {
                    "id": t["id"],
                    "mode": "observation",
                    "interpretation": "本项已记录对应的检测线索，可与本次同类结果一起阅读。后续比较时请保持采样背景和分析方法一致。",
                    "advice": "",
                    "evidence_ids": [key],
                    "support_quotes": [
                        {"id": key, "quote": packet["evidence"][key]["support_texts"][0]}
                    ],
                }
            )
        sections.append({"id": section["id"], "topics": topics})
    return Response(json.dumps({"sections": sections}, ensure_ascii=False))


def test_standard_chat_api_generates_topic_text_and_keeps_outline(monkeypatch):
    monkeypatch.setenv("WGS_REPORT_RESPONSE_FORMAT", "json_object")
    doc = with_species()
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return fake_response(kwargs["json"])

    result = generate_narrative(
        doc, {"base_url": "http://127.0.0.1:30000/v1", "model": "sglang-test"}, post=post
    )
    assert result["audit"]["llm_status"] == "generated"
    assert all(url == "http://127.0.0.1:30000/v1/chat/completions" for url, _ in calls)
    assert calls[0][1]["json"]["response_format"] == {"type": "json_object"}
    assert "thinking" not in calls[0][1]["json"]
    assert result["word_sections"][0]["topics"][0]["narrative_source"] == "llm"
    assert topic(doc, "composition.species")["narrative_source"] == "rule"
    assert "结果解读  本项已记录" in render_markdown(result)
    assert "reasoning_content" not in render_markdown(result)


def test_compatible_backend_format_fallback_and_bounded_repair(monkeypatch):
    monkeypatch.setenv("WGS_REPORT_LLM_CONCURRENCY", "1")
    calls = []

    def post(url, **kwargs):
        calls.append(copy.deepcopy(kwargs["json"]))
        if len(calls) == 1:
            response = Response("")
            response.status_code, response.text = 400, "unsupported response_format"
            return response
        if len(calls) == 2:
            return Response("broken JSON")
        return fake_response(kwargs["json"])

    result = generate_narrative(
        with_species(), {"base_url": "http://local/v1", "model": "test"}, post=post
    )
    assert result["audit"]["llm_status"] == "generated"
    # The Word contract adds a synthesis batch; each batch is bounded.
    assert 3 <= len(calls) <= 6
    assert "response_format" not in calls[1]
    assert len(calls[2]["messages"]) == 3


def test_missing_data_and_service_failure_remain_readable_without_model():
    def unavailable(*args, **kwargs):
        raise TimeoutError("unavailable")

    result = generate_narrative(
        with_species(), {"base_url": "http://local/v1", "model": "test"}, post=unavailable
    )
    assert result["audit"]["llm_status"] == "fallback"
    assert "TimeoutError" not in render_markdown(result)
    assert generate_narrative(document(), None)["audit"]["llm_status"] == "not_configured"
    assert (
        generate_narrative(document(), {"model": "test"}, post=unavailable)["audit"]["llm_status"]
        == "no_eligible_data"
    )


@pytest.mark.asyncio
async def test_generator_publishes_pdf_markdown_and_structured_artifacts(tmp_path, monkeypatch):
    from wgs_agent.tools import detailed_report
    from wgs_agent.tools.domain_tools import ReportGeneratorTool
    from wgs_agent.reporting import inputs

    monkeypatch.setattr(detailed_report, "resolve_report_model", lambda: None)
    monkeypatch.setattr(detailed_report, "load_gene_family_evidence", lambda _: {})
    monkeypatch.setattr(inputs, "load_existing_report_inputs", lambda _: {})
    analysis = tmp_path / "TEST__001_analysis.json"
    analysis.write_text(
        json.dumps(
            {
                "sample_id": "TEST__001",
                "species": {
                    "species_list": [
                        {"species": "Bifidobacterium longum", "abundance": 2, "unit": "%"}
                    ]
                },
            }
        )
    )
    result = await ReportGeneratorTool().invoke(
        {"sample_id": "TEST__001", "analysis_json_path": str(analysis)}
    )
    assert not result.is_error, result.content
    doc = json.loads((tmp_path / "TEST__001_report.json").read_text())
    markdown = (tmp_path / "TEST__001_health_report.md").read_text()
    assert doc["schema_version"] == VERSION
    assert render_markdown(doc) == markdown
    assert (tmp_path / "TEST__001_health_report.pdf").read_bytes().startswith(b"%PDF-")
    assert (tmp_path / "TEST__001_report_evidence.json").stat().st_mode & 0o777 == 0o600
    if shutil.which("gs"):
        extracted = tmp_path / "extracted.txt"
        subprocess.run(
            [
                "gs",
                "-q",
                "-dSAFER",
                "-dBATCH",
                "-dNOPAUSE",
                "-sDEVICE=txtwrite",
                f"-sOutputFile={extracted}",
                str(tmp_path / "TEST__001_health_report.pdf"),
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )
        content = extracted.read_text()
        assert "TEST__001" in content
        assert "*检测结果" not in content
        assert all(chapter["title"] in content for chapter in doc["presentation"]["chapters"])


@pytest.mark.asyncio
async def test_pdf_failure_preserves_previous_artifacts(tmp_path, monkeypatch):
    from wgs_agent.reporting import inputs
    from wgs_agent.tools import detailed_report, report_maker
    from wgs_agent.tools.domain_tools import ReportGeneratorTool

    monkeypatch.setattr(detailed_report, "resolve_report_model", lambda: None)
    monkeypatch.setattr(detailed_report, "load_gene_family_evidence", lambda _: {})
    monkeypatch.setattr(inputs, "load_existing_report_inputs", lambda _: {})

    def fail(*args):
        raise RuntimeError("renderer failed")

    monkeypatch.setattr(report_maker, "_generate_fpdf_report", fail)
    analysis = tmp_path / "TEST_analysis.json"
    analysis.write_text("{}")
    for name in ("TEST_health_report.md", "TEST_health_report.pdf", "TEST_report.json"):
        (tmp_path / name).write_text("previous")
    result = await ReportGeneratorTool().invoke(
        {"sample_id": "TEST", "analysis_json_path": str(analysis)}
    )
    assert result.is_error
    assert all(
        (tmp_path / name).read_text() == "previous"
        for name in ("TEST_health_report.md", "TEST_health_report.pdf", "TEST_report.json")
    )
    assert not list(tmp_path.glob(".TEST-report-*"))


@pytest.mark.asyncio
async def test_report_cannot_overwrite_its_analysis_input(tmp_path):
    from wgs_agent.tools.domain_tools import ReportGeneratorTool

    path = tmp_path / "TEST_report.json"
    path.write_text("{}")
    result = await ReportGeneratorTool().invoke({"sample_id": "TEST", "analysis_json_path": str(path)})
    assert result.is_error
    assert path.read_text() == "{}"
