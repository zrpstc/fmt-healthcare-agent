"""Reference comparisons must reach all report artifacts without corrupting input."""

import copy
import hashlib
import json

import pandas as pd
import pytest

from wgs_agent.reporting import reference
from wgs_agent.reporting.document import build_document, render_markdown
from wgs_fmt_platform import paths


@pytest.fixture
def resource(tmp_path, monkeypatch):
    monkeypatch.setenv("WGS_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("WGS_REFERENCE_DIR", raising=False)
    monkeypatch.delenv("WGS_FMT_MATCHING_DIR", raising=False)
    path = tmp_path / "species.csv"
    path.write_text(
        "species,p5,p95,median,n_samples,cond_n,detection_rate,stratum\n"
        "Bifidobacterium longum,0.1,3,1,200,150,0.75,overall\n"
        "Bifidobacterium breve,0.2,4,1,200,100,0.5,overall\n"
        "Rare species,0,0,0,200,1,0.005,overall\n"
    )
    monkeypatch.setenv("WGS_SPECIES_REFERENCE_FILE", str(path))
    return path


def sample():
    return {
        "sample_id": "TARGET",
        "custom": {"preserve": True},
        "species": {
            "unit": "%",
            "species_list": [
                {"species": "s__Bifidobacterium_longum", "abundance": 5},
                {"species": "Bifidobacterium breve", "abundance": 0},
                {"species": "Rare species", "abundance": 1},
                {"species": "SGB999", "abundance": 2},
            ],
        },
    }


def build(data, inputs=None):
    return build_document(
        "TARGET",
        data.get("species", {}),
        data.get("compare", {}),
        {},
        {},
        {},
        {},
        {},
        {},
        context={**data.get("metadata", {}), "health_inputs": inputs or {}},
    )


def test_paths_fallback_only_for_default_workspace(resource, tmp_path, monkeypatch):
    monkeypatch.delenv("WGS_SPECIES_REFERENCE_FILE")
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    legacy = tmp_path / "data/reference/species_reference_overall.csv"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy")
    monkeypatch.setenv("WGS_WORKSPACE", str(tmp_path / "var"))
    assert paths.species_reference_path() == legacy
    configured = tmp_path / "missing.csv"
    monkeypatch.setenv("WGS_SPECIES_REFERENCE_FILE", str(configured))
    assert paths.species_reference_path() == configured
    monkeypatch.delenv("WGS_SPECIES_REFERENCE_FILE")
    monkeypatch.setenv("WGS_REFERENCE_DIR", str(tmp_path / "explicit"))
    assert paths.species_reference_path() == tmp_path / "explicit/species_reference_overall.csv"
    monkeypatch.delenv("WGS_REFERENCE_DIR")
    monkeypatch.setenv("WGS_WORKSPACE", str(tmp_path / "isolated"))
    assert (
        paths.species_reference_path()
        == tmp_path / "isolated/reference/species_reference_overall.csv"
    )


def test_existing_analysis_recompared_without_losing_zero_unknown_or_custom_fields(resource):
    original = sample()
    before = copy.deepcopy(original)
    updated = reference.refresh_reference_comparisons(original, {})
    assert original == before
    rows = updated["species"]["species_list"]
    assert [r["status"] for r in rows] == ["high", "absent", "unknown", "unknown"]
    assert rows[0]["n_reference"] == 200 and rows[0]["n_detected"] == 150
    assert rows[2]["comparison_reason"] == "zero_width_reference_interval"
    assert rows[3]["comparison_reason"] == "species_not_in_reference"
    assert updated["species"]["n_absent"] == 1
    assert updated["custom"] == before["custom"]
    assert reference.refresh_reference_comparisons(updated, {}) == updated
    doc = build(updated)
    assert doc["evidence"]["S2"]["comparison"] == "below"
    assert "n=200" in doc["evidence"]["S1"]["reference_text"]
    assert "零宽区间" in doc["evidence"]["S3"]["reference_text"]
    assert "参考库未覆盖" in doc["evidence"]["S4"]["reference_text"]
    assert doc["audit"]["reference_comparison"]["version"] == reference.VERSION


def test_complete_profile_recovers_top_n_and_retains_sgb_for_diversity(resource):
    data = sample()
    full = [
        {"name": "Bifidobacterium longum", "abundance": 70, "unit": "%"},
        {"name": "SGB999", "abundance": 30, "unit": "%"},
    ]
    updated = reference.refresh_reference_comparisons(
        data,
        {
            "taxonomy": {
                "complete": True,
                "ranks": {"species": full},
            }
        },
    )
    assert [r["abundance"] for r in updated["species"]["species_list"]] == [70, 30]
    assert updated["species"]["n_total"] == 2
    assert updated["species"]["is_complete_profile"] is True
    assert updated["diversity"]["richness"] == 2


def test_fraction_unit_and_incompatible_unit(resource):
    data = sample()
    data["species"]["species_list"] = [
        {"species": "Bifidobacterium longum", "abundance": 0.05, "unit": "fraction"},
        {"species": "Bifidobacterium longum", "abundance": 5, "unit": "copies/g"},
    ]
    rows = reference.refresh_reference_comparisons(data, {})["species"]["species_list"]
    assert rows[0]["p95"] == 0.03 and rows[0]["status"] == "high"
    assert rows[0]["abundance"] == 0.05
    assert rows[1]["status"] == "unknown" and "p95" not in rows[1]


def test_bad_and_duplicate_reference_rows_are_not_compared(resource):
    resource.write_text(
        "species,p5,p95\nBifidobacterium longum,0,2\n"
        "s__Bifidobacterium_longum,0,4\nWrong species,8,2\nNaN species,nan,2\n"
    )
    rows, audit = reference.load_species_reference()
    assert rows == {}
    assert audit["duplicate_names"] == 1 and audit["invalid_rows"] == 2
    resource.write_text("name,min,max\nA,0,2\n")
    assert reference.load_species_reference()[1]["reason"] == "invalid_reference_columns"


def test_missing_reference_preserves_input_comparisons_and_provides_audit(resource):
    data = sample()
    data["species"]["species_list"][0].update(status="high", p5=0, p95=1)
    resource.unlink()
    updated = reference.refresh_reference_comparisons(data, {})
    assert updated["species"] == data["species"]
    assert (
        updated["metadata"]["reference_comparison"]["species"]["reason"] == "reference_file_missing"
    )
    assert "输入中已有比较予以保留" in render_markdown(build(updated))


def donor_resources(tmp_path):
    base = tmp_path / "data/fmt-matching"
    base.mkdir(parents=True)
    ids = ["TARGET", *(f"DONOR{i}" for i in range(32)), "RECIPIENT"]
    pd.DataFrame(
        {
            "sample_id": ids,
            "group": ["donor"] * 33 + ["recipient"],
            "disease": ["healthy"] * 33 + ["disease"],
        }
    ).to_excel(base / "match.xlsx", index=False)
    pd.DataFrame(
        {"s__A": [20 + i for i in range(34)], "s__B": [80 - i for i in range(34)]}, index=ids
    ).to_csv(base / "species_abundance_train.csv")
    return base


def test_diversity_uses_only_healthy_donors_excludes_self_and_keeps_longitudinal(
    resource, tmp_path
):
    donor_resources(tmp_path)
    inputs = {
        "taxonomy": {
            "complete": True,
            "ranks": {
                "species": [
                    {"name": "A", "abundance": 50},
                    {"name": "B", "abundance": 50},
                ]
            },
        },
        "diversity": {"longitudinal": [{"name": "历史检测变化", "value": 0.1, "unit": "无量纲"}]},
    }
    updated = reference.refresh_reference_comparisons(sample(), inputs)
    rows = updated["diversity"]["reference_comparisons"]
    assert len(rows) == 4 and all(row["n_reference"] == 32 for row in rows)
    assert all(0 <= row["percentile"] <= 100 for row in rows)
    assert all(row["reference_population"].endswith("（探索性）") for row in rows)
    assert updated["metadata"]["reference_comparison"]["diversity"]["n_reference"] == 32
    inputs["diversity"] = updated["diversity"]
    assert reference.refresh_reference_comparisons(updated, inputs) == updated
    doc = build(updated, {**inputs, "diversity": updated["diversity"]})
    assert len([r for r in doc["evidence"].values() if r["kind"] == "div_reference"]) == 5
    assert "未按年龄、性别和地区匹配" in render_markdown(doc)


@pytest.mark.asyncio
async def test_regeneration_saves_comparisons_and_matching_hash_to_all_artifacts(
    resource, tmp_path, monkeypatch
):
    from wgs_agent.reporting import inputs, knowledge_graph
    from wgs_agent.tools import detailed_report
    from wgs_agent.tools.domain_tools import ReportGeneratorTool

    monkeypatch.setattr(inputs, "load_existing_report_inputs", lambda _: {})
    monkeypatch.setattr(detailed_report, "resolve_report_model", lambda: None)
    monkeypatch.setattr(detailed_report, "load_gene_family_evidence", lambda _: {})

    async def no_enrichment(_):
        return None

    monkeypatch.setattr(knowledge_graph, "enrich_document", no_enrichment)
    path = tmp_path / "TARGET_analysis.json"
    path.write_text(json.dumps(sample()))
    tool = ReportGeneratorTool()
    params = {"sample_id": "TARGET", "analysis_json_path": str(path)}
    response = await tool.invoke(params)
    assert not response.is_error, response.content
    saved = json.loads(path.read_text())
    assert saved["species"]["species_list"][0]["p95"] == 3
    assert saved["custom"] == {"preserve": True}
    doc = json.loads((tmp_path / "TARGET_report.json").read_text())
    evidence = json.loads((tmp_path / "TARGET_report_evidence.json").read_text())
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert doc["audit"]["analysis_sha256"] == evidence["context"]["analysis_sha256"] == expected
    assert doc["evidence"]["S1"]["comparison"] == "above"
    assert "参考样本 n=200" in (tmp_path / "TARGET_health_report.md").read_text()
    assert (tmp_path / "TARGET_health_report.pdf").read_bytes().startswith(b"%PDF-")
    assert path.stat().st_mode & 0o777 == 0o600
    before = path.read_bytes()
    assert not (await tool.invoke(params)).is_error
    assert path.read_bytes() == before
    resource.write_text(
        resource.read_text().replace(
            "Bifidobacterium longum,0.1,3,1,",
            "Bifidobacterium longum,0.1,8,1,",
        )
    )
    assert not (await tool.invoke(params)).is_error
    assert json.loads(path.read_text())["species"]["species_list"][0]["status"] == "normal"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["renderer", "concurrent_analysis"])
async def test_failed_generation_does_not_publish_refreshed_analysis_or_partial_report(
    resource, tmp_path, monkeypatch, failure
):
    from wgs_agent.reporting import inputs, knowledge_graph
    from wgs_agent.tools import detailed_report, report_maker
    from wgs_agent.tools.domain_tools import ReportGeneratorTool

    monkeypatch.setattr(inputs, "load_existing_report_inputs", lambda _: {})
    monkeypatch.setattr(detailed_report, "resolve_report_model", lambda: None)
    monkeypatch.setattr(detailed_report, "load_gene_family_evidence", lambda _: {})

    async def no_enrichment(_):
        return None

    monkeypatch.setattr(knowledge_graph, "enrich_document", no_enrichment)
    path = tmp_path / "TARGET_analysis.json"
    path.write_text(json.dumps(sample()))
    original = path.read_bytes()
    for suffix in ("health_report.md", "health_report.pdf", "report.json", "report_evidence.json"):
        (tmp_path / f"TARGET_{suffix}").write_text("previous")
    renderer = report_maker._generate_fpdf_report

    def fail_or_update(*args):
        if failure == "renderer":
            raise RuntimeError("synthetic PDF failure")
        path.write_text('{"sample_id":"TARGET","concurrent":true}')
        renderer(*args)

    monkeypatch.setattr(report_maker, "_generate_fpdf_report", fail_or_update)
    response = await ReportGeneratorTool().invoke(
        {"sample_id": "TARGET", "analysis_json_path": str(path)}
    )
    assert response.is_error
    assert (
        path.read_bytes() == original
        if failure == "renderer"
        else json.loads(path.read_text())["concurrent"]
    )
    for suffix in ("health_report.md", "health_report.pdf", "report.json", "report_evidence.json"):
        assert (tmp_path / f"TARGET_{suffix}").read_text() == "previous"
