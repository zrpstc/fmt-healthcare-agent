"""Cohort eligibility, numerical correctness, invalidation and report publication."""

import copy
import csv
import importlib.util
import json
from pathlib import Path

import pytest

from wgs_agent.reporting import healthy, reference
from wgs_agent.reporting.document import build_document, render_markdown
from wgs_agent.reporting.inputs import load_existing_report_inputs

PIPELINE = {"profiler": "MetaPhlAn", "profiler_version": "4.2.2", "database_version": "mpa_test"}


@pytest.fixture
def cohort(tmp_path, monkeypatch):
    monkeypatch.setenv("WGS_WORKSPACE", str(tmp_path))
    base = tmp_path / "cohort"
    base.mkdir()
    monkeypatch.setenv("WGS_HEALTHY_REFERENCE_DIR", str(base))
    manifest = {
        "schema_version": healthy.VERSION, "cohort_id": "TEST_HEALTHY",
        "cohort_version": "2026-01", "source_url": "https://example.org/test-only",
        "inclusion_criteria": "Synthetic healthy adults; tests only",
        "body_site": "stool", "unit": "%", "complete_species_profiles": True,
        "pipeline": PIPELINE, "minimum_subjects": 30,
    }
    (base / "manifest.json").write_text(json.dumps(manifest))
    columns = ["sample_id", "subject_id", "study_id", "health_status", "qc_pass",
               "body_site", "age", "sex", "country"]
    labels = [[f"D{i:02}", f"P{i}", "S", "healthy", "true", "stool", 40, "female", "CHN"]
              for i in range(35)]
    labels.extend([
        ["TARGET", "TARGET_PERSON", "S", "healthy", "true", "stool", 40, "female", "CHN"],
        ["REPEAT", "P0", "S", "healthy", "true", "stool", 40, "female", "CHN"],
        ["PATIENT", "PATIENT", "S", "IBD", "true", "stool", 40, "female", "CHN"],
        ["FAILED", "FAILED", "S", "healthy", "false", "stool", 40, "female", "CHN"],
    ])
    with (base / "metadata.tsv").open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(columns)
        writer.writerows(labels)
    with (base / "species_abundance.tsv").open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["sample_id", "s__A", "s__B", "s__Rare"])
        writer.writerows([[r[0], 10 + i % 35, 90 - i % 35, 0] for i, r in enumerate(labels)])
    taxonomy = {
        "complete": True, "unit": "%", "pipeline": PIPELINE,
        "ranks": {"species": [{"name": "A", "abundance": 50, "unit": "%"},
                                {"name": "B", "abundance": 50, "unit": "%"}]},
    }
    data = {"sample_id": "TARGET", "species": {}, "taxonomy": taxonomy,
            "metadata": {"subject_id": "TARGET_PERSON", "study_id": "S", "age": 40,
                         "sex": "female", "country": "CHN"}}
    return base, data


def refresh(data):
    return reference.refresh_reference_comparisons(data, {
        k: data[k] for k in ("taxonomy", "diversity") if k in data
    })


def document(data):
    return build_document("TARGET", data.get("species", {}), data.get("compare", {}),
                          {}, {}, {}, {}, {}, {}, context={**data["metadata"], "health_inputs": data})


def alter_manifest(base, **updates):
    path = base / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest.update(updates)
    path.write_text(json.dumps(manifest))


def test_subject_filtering_zero_inclusion_percentile_and_idempotence(cohort):
    _, data = cohort
    original = copy.deepcopy(data)
    updated = refresh(data)
    assert data == original
    audit = updated["metadata"]["reference_comparison"]["healthy_population"]
    assert audit["status"] == "available" and audit["n_subjects"] == 35
    assert audit["exclusions"] == {"labels": 2, "self": 1, "matching": 0,
                                    "invalid_profile": 0, "repeat_subject": 1}
    a = updated["species"]["species_list"][0]
    assert a["p5"] == pytest.approx(11.7)
    assert a["p95"] == pytest.approx(42.3)
    assert a["reference_median"] == 27
    assert a["percentile"] == 100 and a["status"] == "high"
    assert a["n_subjects"] == 35 and "_distribution" not in a
    rare = updated["species"]["species_list"][-1]
    assert rare["abundance"] == 0 and rare["comparison_reason"] == "zero_width_reference_interval"
    assert len(updated["diversity"]["reference_comparisons"]) == 4
    assert refresh(updated) == updated
    doc = document(updated)
    text = render_markdown(doc)
    assert "健康人群对照：TEST_HEALTHY" in text and "参考独立个体 n=35" in text
    assert "健康人群经验百分位" in doc["evidence"]["S1"]["reference_text"]
    assert "健康筛选和分析数据库版本尚待核验" not in text


@pytest.mark.parametrize(("change", "reason"), [
    ("version", "incompatible_target_pipeline"),
    ("missing_version", "unknown_target_pipeline"),
    ("top_n", "incomplete_target_profile"),
    ("bad_total", "incomplete_target_profile"),
    ("matching", "insufficient_healthy_subjects"),
    ("missing_demographics", "missing_matching_metadata"),
    ("missing_file", "healthy_reference_unreadable"),
    ("bad_manifest", "invalid_healthy_manifest"),
    ("too_few", "insufficient_healthy_subjects"),
])
def test_explicit_cohort_never_silently_uses_legacy_or_stale_results(cohort, change, reason):
    base, data = cohort
    data = refresh(data)
    data["diversity"]["longitudinal"] = [{"name": "previous", "value": 1}]
    if change == "version":
        data["taxonomy"]["pipeline"] = {**PIPELINE, "database_version": "different"}
    elif change == "missing_version":
        data["taxonomy"]["pipeline"] = {}
    elif change == "top_n":
        data["taxonomy"]["complete"] = False
        data["species"]["is_complete_profile"] = False
    elif change == "bad_total":
        data["taxonomy"]["ranks"]["species"][0]["abundance"] = 1
    elif change == "matching":
        alter_manifest(base, stratify_by=["sex"])
        data["metadata"]["sex"] = "male"
    elif change == "missing_demographics":
        alter_manifest(base, stratify_by=["country"])
        data["sample_id"] = "NEW_TARGET"
        data["metadata"].pop("country")
    elif change == "missing_file":
        (base / "metadata.tsv").unlink()
    elif change == "bad_manifest":
        alter_manifest(base, minimum_subjects=2)
    elif change == "too_few":
        alter_manifest(base, minimum_subjects=100)
    updated = refresh(data)
    audit = updated["metadata"]["reference_comparison"]["healthy_population"]
    assert audit["reason"] == reason
    assert all(r["status"] == "unknown" and "percentile" not in r
               for r in updated["species"]["species_list"])
    assert updated["diversity"]["reference_comparisons"] == []
    assert updated["diversity"]["longitudinal"] == [{"name": "previous", "value": 1}]
    assert "健康人群对照：未建立" in render_markdown(document(updated))


def test_matching_zero_width_and_tie_percentile(cohort):
    base, data = cohort
    alter_manifest(base, stratify_by=["age", "sex", "country"], age_window_years=5)
    data["metadata"]["sex"] = "F"
    data["taxonomy"]["ranks"]["species"].append({"name": "Rare", "abundance": 0, "unit": "%"})
    updated = refresh(data)
    rare = updated["species"]["species_list"][-1]
    assert rare["status"] == "unknown" and rare["percentile"] == 50
    assert rare["n_detected"] == 0 and rare["detection_rate"] == 0
    assert healthy.percentile([0, 0, 1, 2], 0) == 25
    assert healthy.percentile([0, 0, 1, 2], 1) == 62.5
    assert healthy.quantile([0, 10], 0.05) == pytest.approx(0.5)


def test_absent_cohort_species_is_only_zero_filled_for_complete_profiles(cohort):
    _, data = cohort
    data["taxonomy"]["ranks"]["species"] = [{"name": "A", "abundance": 100, "unit": "%"}]
    updated = refresh(data)
    b = next(r for r in updated["species"]["species_list"] if reference.species_key(r["species"]) == "b")
    assert b["abundance"] == 0 and b["status"] == "absent" and b["percentile"] == 0
    assert any(r["label"] == "s__B" and r["comparison"] == "below"
               for r in document(updated)["evidence"].values())
    updated["taxonomy"]["complete"] = False
    # Even a previously cached complete flag cannot override a now-incomplete taxonomy.
    assert refresh(updated)["metadata"]["reference_comparison"]["healthy_population"]["reason"] == "incomplete_target_profile"


def test_duplicate_feature_aliases_and_duplicate_labels_fail_closed(cohort):
    base, data = cohort
    matrix = base / "species_abundance.tsv"
    matrix.write_text(matrix.read_text().replace("s__B", "A"))
    assert refresh(data)["metadata"]["reference_comparison"]["healthy_population"]["reason"] == "invalid_healthy_matrix"
    labels = base / "metadata.tsv"
    with labels.open("a") as handle:
        handle.write(labels.read_text().splitlines()[1] + "\n")
    assert refresh(data)["metadata"]["reference_comparison"]["healthy_population"]["reason"] == "invalid_healthy_metadata"


def test_profile_header_captures_versions_without_guessing(tmp_path):
    folder = tmp_path / "profiles/metaphlan"
    folder.mkdir(parents=True)
    profile = folder / "TARGET_profile.tsv"
    profile.write_text("#mpa_test\n#MetaPhlAn version 4.2.2 (date)\n"
                       "k__Bacteria|s__A\t2|1\t50\nk__Bacteria|s__B\t2|2\t50\n")
    assert load_existing_report_inputs("TARGET", tmp_path)["taxonomy"]["pipeline"] == PIPELINE
    profile.write_text(profile.read_text().replace("#MetaPhlAn version 4.2.2 (date)\n", ""))
    assert "profiler_version" not in load_existing_report_inputs("TARGET", tmp_path)["taxonomy"]["pipeline"]


def test_legacy_downloader_never_promotes_unhealthy_unknown_or_repeat_subjects(tmp_path):
    import pandas as pd
    from wgs_agent.pipeline.download_public_reference import filter_healthy_adult_stool

    path = tmp_path / "metadata.tsv"
    pd.DataFrame({
        "sample_id": ["A", "B", "C", "D", "E", "F", "G"],
        "body_site": ["stool"] * 7,
        "study_condition": ["healthy", "unhealthy", "control", "healthy", "healthy", "healthy", "healthy"],
        "disease": ["healthy", "IBD", "IBD", "healthy", "healthy", "healthy", "healthy"],
        "age": [40, 40, 40, None, 40, 40, 8],
        "subject_id": ["P1", "P2", "P3", "P4", "P1", None, "P7"],
        "study_name": ["S"] * 7,
    }).to_csv(path, sep="\t", index=False)
    assert filter_healthy_adult_stool(path).sample_id.tolist() == ["A"]
    pd.DataFrame({"sample_id": ["A"], "body_site": ["stool"]}).to_csv(path, sep="\t", index=False)
    with pytest.raises(ValueError, match="健康状态"):
        filter_healthy_adult_stool(path)


@pytest.mark.parametrize("kind", ["species", "pathway"])
def test_legacy_reference_matrix_refuses_all_sample_fallback(tmp_path, kind):
    import pandas as pd
    from wgs_agent.pipeline import download_public_reference as download

    matrix = tmp_path / "matrix.tsv"
    pd.DataFrame([[1] * 40], index=["A"], columns=[f"S{i}" for i in range(40)]).to_csv(matrix, sep="\t")
    build = (download.build_species_reference_from_matrix if kind == "species"
             else download.build_pathway_reference_from_matrix)
    output = tmp_path / "reference.tsv"
    with pytest.raises(ValueError, match="禁止回退"):
        build(matrix, {"S0"}, output)
    assert not output.exists()


@pytest.mark.asyncio
async def test_healthy_comparison_reaches_all_report_artifacts(cohort, tmp_path, monkeypatch):
    _, data = cohort
    from wgs_agent.reporting import inputs, knowledge_graph
    from wgs_agent.tools import detailed_report
    from wgs_agent.tools.domain_tools import ReportGeneratorTool

    monkeypatch.setattr(inputs, "load_existing_report_inputs", lambda _: {})
    monkeypatch.setattr(detailed_report, "resolve_report_model", lambda: None)
    monkeypatch.setattr(detailed_report, "load_gene_family_evidence", lambda _: {})
    async def no_enrichment(_):
        return None
    monkeypatch.setattr(knowledge_graph, "enrich_document", no_enrichment)
    analysis = tmp_path / "TARGET_analysis.json"
    analysis.write_text(json.dumps(data))
    result = await ReportGeneratorTool().invoke({"sample_id": "TARGET", "analysis_json_path": str(analysis)})
    assert not result.is_error, result.content
    report = json.loads((tmp_path / "TARGET_report.json").read_text())
    evidence = json.loads((tmp_path / "TARGET_report_evidence.json").read_text())
    saved = json.loads(analysis.read_text())
    audit = saved["metadata"]["reference_comparison"]["healthy_population"]
    assert audit == report["audit"]["reference_comparison"]["healthy_population"]
    assert audit == evidence["context"]["reference_comparison"]["healthy_population"]
    assert "健康人群对照：TEST_HEALTHY" in (tmp_path / "TARGET_health_report.md").read_text()
    assert (tmp_path / "TARGET_health_report.pdf").read_bytes().startswith(b"%PDF-")
    assert report["evidence"]["S1"]["percentile"] == 100


def test_bundle_builder_preserves_all_species_and_refuses_overwrite(cohort, tmp_path):
    base, _ = cohort
    script = Path(__file__).resolve().parents[1] / "scripts/build_healthy_reference.py"
    spec = importlib.util.spec_from_file_location("build_healthy", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "completed"
    folder = root / "profiles/metaphlan"
    folder.mkdir(parents=True)
    _, matrix = healthy._table((base / "species_abundance.tsv").read_bytes())
    for row in matrix:
        (folder / f"{row['sample_id']}_profile.tsv").write_text(
            "#mpa_test\n#MetaPhlAn version 4.2.2\n"
            + "".join(f"k__Bacteria|s__{key}\t2|{i}\t{row['s__' + key]}\n"
                      for i, key in enumerate(("A", "B", "Rare")))
        )
    output = tmp_path / "built"
    audit = module.build(base / "manifest.json", base / "metadata.tsv", root, output)
    assert audit["n_subjects"] == 36
    assert (output / "species_abundance.tsv").read_text().splitlines()[0] == "sample_id\ta\tb\trare"
    with pytest.raises(ValueError, match="already exists"):
        module.build(base / "manifest.json", base / "metadata.tsv", root, output)
