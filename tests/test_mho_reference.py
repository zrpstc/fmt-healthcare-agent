"""MHO comparisons must be reproducible and isolated from the primary pipeline."""

import argparse
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from wgs_agent.reporting import mho, reference
from wgs_agent.reporting.document import build_document, render_markdown


def rewrite_manifest(base, **updates):
    path = base / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest.update(updates)
    manifest["files"] = {name: mho.digest((base / name).read_bytes())
                         for name in ("metadata.tsv", "species_abundance.tsv")}
    path.write_text(json.dumps(manifest))


@pytest.fixture
def cohort(tmp_path, monkeypatch):
    monkeypatch.setenv("WGS_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("WGS_HEALTHY_REFERENCE_PROVIDER", "mho")
    base, profiles = tmp_path / "reference", tmp_path / "profiles"
    base.mkdir()
    monkeypatch.setenv("WGS_HEALTHY_REFERENCE_DIR", str(base))
    monkeypatch.setenv("WGS_MHO_PROFILES_DIR", str(profiles))
    (base / "metadata.tsv").write_text(
        "sample_id\tsubject_id\tstudy_id\tphenotype\tsource_runs\tage\tsex\tcountry\n"
        + "".join(f"D{i}\tP{i}\tSTUDY\tMHNO\tERR{1000+i}\t40\tfemale\tCHN\n"
                  for i in range(35)))
    (base / "species_abundance.tsv").write_text(
        "sample_id\ts__A\ts__B\ts__Rare\n"
        + "".join(f"D{i}\t{10+i}\t{90-i}\t0\n" for i in range(35)))
    (base / "manifest.json").write_text(json.dumps({
        "schema_version": mho.VERSION, "cohort_id": "SYNTHETIC_MHNO",
        "cohort_version": "test-v1", "source_url": "https://example.org/test-only",
        "pipeline": mho.PIPELINE, "normalization": mho.NORMALIZATION,
        "unit": "%", "phenotype": "MHNO", "body_site": "stool",
        "complete_species_profiles": True, "feature_level": "species",
        "minimum_subjects": 30,
    }))
    rewrite_manifest(base)
    folder = profiles / "TARGET"
    folder.mkdir(parents=True)
    # Only species parents count, not the duplicate taxonomic levels or SGB leaves.
    raw = (f"#{mho.PIPELINE['database_version']}\n#MetaPhlAn version 4.2.2\n"
           "k__Bacteria\t2\t50\n"
           "k__Bacteria|s__A\t2|1\t25\n"
           "k__Bacteria|s__A|t__SGB1\t2|1|1\t25\n"
           "k__Bacteria|s__B\t2|2\t25\n").encode()
    (folder / "profile.tsv").write_bytes(raw)
    (folder / "provenance.json").write_text(json.dumps({
        "sample_id": "TARGET", "pipeline": mho.PIPELINE,
        "normalization": mho.NORMALIZATION, "profile_sha256": mho.digest(raw),
    }))
    data = {"sample_id": "TARGET", "metadata": {},
            "species": {"species_list": [{"species": "A", "abundance": 72,
                "p5": 10, "p95": 44, "percentile": 100, "status": "high"}], "unit": "%"},
            "compare": {"comparison": [{"species": "A", "abundance": 72}]},
            "taxonomy": {"pipeline": {**mho.PIPELINE, "profiler_version": "4.2.4"}},
            "diversity": {"shannon": 9.9, "longitudinal": [{"name": "previous", "value": 1}]},
            "pathways": {"marker": "unchanged"}, "diseases": {"marker": "unchanged"}}
    return base, folder, data


def refresh(data):
    return reference.refresh_reference_comparisons(data, {"taxonomy": data["taxonomy"]})


def test_independent_pipeline_normalization_and_reference_values(cohort):
    _, _, data = cohort
    original = copy.deepcopy(data)
    result = refresh(data)
    assert data == original
    for key in ("species", "compare", "taxonomy", "diversity", "pathways", "diseases"):
        assert result[key] == original[key]
    comparison = result["healthy_comparison"]
    assert comparison["audit"]["status"] == "available"
    assert comparison["audit"]["target_raw_species_sum"] == 50
    a = next(row for row in comparison["species"] if row["species"] == "a")
    assert a["abundance"] == 50
    assert a["p5"] == pytest.approx(11.7)
    assert a["p95"] == pytest.approx(42.3)
    assert a["percentile"] == 100 and a["n_subjects"] == 35
    rare = next(row for row in comparison["species"] if row["species"] == "rare")
    assert rare["abundance"] == 0 and rare["n_detected"] == 0
    assert rare["status"] == "unknown" and rare["percentile"] == 50
    assert len(comparison["diversity"]) == 4
    assert refresh(result) == result


@pytest.mark.parametrize(("change", "reason"), [
    ("version", "incompatible_pipeline"), ("header", "incompatible_pipeline"),
    ("profile_tampered", "invalid_target"), ("target_missing", "target_missing"),
    ("reference_tampered", "invalid_reference"), ("manifest_list", "invalid_reference"),
    ("provenance_list", "invalid_target"), ("qc", "target_qc_failed"),
    ("matching_missing", "missing_matching_metadata"), ("matching_small", "insufficient_subjects"),
    ("minimum", "invalid_reference"), ("duplicate_person", "invalid_reference"),
])
def test_unavailable_never_reuses_stale_comparison(cohort, change, reason):
    base, folder, data = cohort
    data = refresh(data)
    if change in {"version", "provenance_list"}:
        p = json.loads((folder / "provenance.json").read_text())
        p["pipeline"] = {**mho.PIPELINE, "profiler_version": "4.2.4"}
        (folder / "provenance.json").write_text(json.dumps([] if change == "provenance_list" else p))
    elif change in {"header", "profile_tampered"}:
        raw = (folder / "profile.tsv").read_bytes().replace(b"4.2.2", b"4.2.4")
        (folder / "profile.tsv").write_bytes(raw)
        if change == "header":
            p = json.loads((folder / "provenance.json").read_text())
            p["profile_sha256"] = mho.digest(raw)
            (folder / "provenance.json").write_text(json.dumps(p))
    elif change == "target_missing":
        (folder / "profile.tsv").unlink()
    elif change == "reference_tampered":
        with (base / "species_abundance.tsv").open("a") as stream:
            stream.write("TAMPERED\t10\t90\t0\n")
    elif change == "manifest_list":
        (base / "manifest.json").write_text("[]")
    elif change == "qc":
        data["metadata"]["qc_status"] = "failed"
    elif change in {"matching_missing", "matching_small"}:
        rewrite_manifest(base, stratify_by=["sex"])
        if change == "matching_small":
            data["metadata"]["sex"] = "male"
    elif change == "minimum":
        rewrite_manifest(base, minimum_subjects=1)
    elif change == "duplicate_person":
        path = base / "metadata.tsv"
        path.write_text(path.read_text().replace("\tP1\t", "\tP0\t"))
        rewrite_manifest(base)
    result = refresh(data)
    assert result["healthy_comparison"]["audit"]["reason"] == reason
    assert result["healthy_comparison"]["species"] == []
    assert result["healthy_comparison"]["diversity"] == []
    assert result["species"] == data["species"]


def test_matching_and_excluding_same_subject_or_run(cohort):
    base, _, data = cohort
    rewrite_manifest(base, stratify_by=["age", "sex", "country"], age_window_years="5")
    data["metadata"] = {"age": 42, "sex": "F", "country": "CHN",
                        "subject_id": "P0", "study_id": "STUDY", "source_runs": "ERR1001"}
    audit = refresh(data)["healthy_comparison"]["audit"]
    assert audit["status"] == "available" and audit["n_subjects"] == 33
    assert audit["exclusions"] == {"self": 2, "matching": 0}


def test_document_separates_primary_abundance_and_mho_evidence(cohort):
    data = refresh(cohort[2])
    doc = build_document("TARGET", data["species"], data["compare"], {}, {}, {}, {}, {}, {},
                         context={**data["metadata"], "health_inputs": data})
    assert doc["evidence"]["S1"]["value"] == 72
    assert doc["evidence"]["S1"]["comparison"] == "unknown"
    assert doc["evidence"]["HS1"]["value"] == 50
    assert "MHNO 参考队列经验百分位" in doc["evidence"]["HS1"]["reference_text"]
    assert len([r for r in doc["evidence"].values() if r["kind"] == "healthy_diversity"]) == 4
    text = render_markdown(doc)
    assert "MHOmicrobiome 对照：SYNTHETIC_MHNO" in text
    assert "已分类物种总和归一化至 100%" in text
    assert "供体子集经验百分位" not in text
    assert doc["template_inputs"]["healthy_comparison"] == data["healthy_comparison"]
    from wgs_agent.reporting.word_template import bind_table, contract
    species_table = next(b for b in contract()["chapters"][0]["blocks"] if b.get("id") == "1.4.t1")
    assert bind_table(doc, species_table)[0][1].startswith("50 ")
    alpha_table = next(b for b in contract()["chapters"][1]["blocks"] if b.get("id") == "2.1.t1")
    alpha = bind_table(doc, alpha_table)
    assert alpha[-4][0].startswith("MHNO 独立谱")
    assert "9.9" in alpha[3][1]  # The main Shannon estimate remains separate.
    from wgs_agent.reporting.word_figures import chart_data
    chart = chart_data(doc, {"id": "1.4.1", "kind": "barChart"})
    assert chart["series"][0]["name"] == "MHNO 独立谱"
    assert chart["series"][0]["values"][0] == 50
    alpha_chart = chart_data(doc, {"id": "2.1.1", "kind": "barChart"})
    assert all(label.startswith("MHNO") for label in alpha_chart["labels"])


def test_absolute_measurements_survive_mho_selection(cohort):
    data = refresh(cohort[2])
    data["absolute_abundance"] = {"measurements": [{"name": "total", "value": 123,
        "unit": "copies/g", "method": "qPCR", "data_type": "measured"}]}
    doc = build_document("TARGET", data["species"], data["compare"], {}, {}, {}, {}, {}, {},
                         context={**data["metadata"], "health_inputs": data})
    from wgs_agent.reporting.word_template import bind_table, contract
    block = next(b for b in contract()["chapters"][0]["blocks"] if b.get("id") == "1.4.t2")
    assert bind_table(doc, block) == [["total", "123 copies/g", "qPCR"]]


def test_complete_primary_taxonomy_still_recovers_historical_top_n_inputs(cohort):
    data = refresh(cohort[2])
    data["taxonomy"].update(complete=True, ranks={"species": [
        {"name": "A", "abundance": 72, "unit": "%"},
        {"name": "B", "abundance": 28, "unit": "%"}]})
    original = copy.deepcopy(data["species"])
    doc = build_document("TARGET", data["species"], data["compare"], {}, {}, {}, {}, {}, {},
                         context={**data["metadata"], "health_inputs": data})
    assert doc["evidence"]["S2"]["value"] == 28
    assert data["species"] == original


def test_switching_back_to_legacy_drops_mho_payload(cohort, monkeypatch):
    data = refresh(cohort[2])
    monkeypatch.delenv("WGS_HEALTHY_REFERENCE_PROVIDER")
    result = refresh(data)
    assert "healthy_comparison" not in result


def preparation_script():
    path = Path(__file__).resolve().parents[1] / "scripts/mho_reference.py"
    spec = importlib.util.spec_from_file_location("mho_preparation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_builder_aggregates_sgb_leaves_normalizes_both_species_and_maps_visits(tmp_path, monkeypatch):
    import csv

    module = preparation_script()
    source = tmp_path / "source"
    source.mkdir()
    ids = [f"D{i}" for i in range(102)] + ["A4F_77_V3"]
    with (source / "whole_cohort_data.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["taxa", *ids])
        for clade, value in [("s__A|t__SGB1", 5), ("s__A|t__SGB2", 10), ("s__B|t__SGB3", 35)]:
            writer.writerow(["k__Bacteria|" + clade, *([value] * 103)])
    (source / "phenotypes.xlsx").write_bytes(b"synthetic labels, not a real workbook")
    monkeypatch.setattr(module, "SOURCES", {name: ("https://example.org/test-only", mho.digest((source / name).read_bytes()))
                       for name in module.SOURCES})
    labels = [{"subject_id": sid, "run_accession": f"ERR{1000+i}", "study_name": "STUDY", "phenotype": "MHNO"}
              for i, sid in enumerate(ids[:-1])]
    labels.append({"subject_id": "77", "run_accession": "ERR9999", "study_name": "AI4Food", "phenotype": "MHNO"})
    monkeypatch.setattr(module, "read_phenotypes", lambda _: labels)
    output = tmp_path / "built"
    result = module.build(source, output)
    manifest, metadata, features, matrix, _ = mho.load_bundle(output)
    assert result["n_subjects"] == 103 and result["n_species"] == 2
    assert manifest["n_source_sgb_features"] == 3
    assert result["raw_species_sum_range"] == [50, 50]
    assert matrix["A4F_77_V3"] == {"a": 30, "b": 70}
    assert metadata[-1]["subject_id"] == "77" and metadata[-1]["study_id"] == "AI4Food"
    with pytest.raises(ValueError, match="exists"):
        module.build(source, output)
    (source / "phenotypes.xlsx").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        module.build(source, tmp_path / "other")


def test_download_reuses_only_exact_pinned_source_files(tmp_path, monkeypatch):
    module = preparation_script()
    data = {name: name.encode() for name in module.SOURCES}
    monkeypatch.setattr(module, "SOURCES", {name: ("https://example.org/" + name, mho.digest(raw))
                                         for name, raw in data.items()})
    for name, raw in data.items():
        (tmp_path / name).write_bytes(raw)

    def unexpected_network(*args, **kwargs):
        raise AssertionError("Validated cached files must not be downloaded again")

    monkeypatch.setattr(module.urllib.request, "urlopen", unexpected_network)
    module.download(tmp_path)
    (tmp_path / "whole_cohort_data.csv").write_bytes(b"wrong version")
    with pytest.raises(ValueError, match="checksum"):
        module.download(tmp_path)


def test_target_runner_checks_real_version_and_passes_exact_database(cohort, tmp_path, monkeypatch):
    _, fixture, _ = cohort
    module = preparation_script()
    executable, reads, database = tmp_path / "metaphlan", tmp_path / "reads.gz", tmp_path / "db"
    executable.touch()
    reads.write_bytes(b"synthetic only")
    database.mkdir()
    (database / (mho.PIPELINE["database_version"] + ".pkl")).touch()
    args = argparse.Namespace(sample_id="NEW", threads=2, metaphlan=executable, reads=reads,
        database=database, tool_bin=None, profiles_dir=tmp_path / "new-profiles", source_runs="ERR99")
    commands, version = [], ["4.2.4"]

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[-1] == "--version":
            return argparse.Namespace(stdout=f"MetaPhlAn version {version[0]}", stderr="")
        Path(command[command.index("--output_file") + 1]).write_bytes((fixture / "profile.tsv").read_bytes())

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="actual MetaPhlAn 4.2.2"):
        module.profile(args)
    assert len(commands) == 1 and not args.profiles_dir.exists()
    version[0] = "4.2.2"
    module.profile(args)
    command = commands[-1]
    assert command[command.index("--index") + 1] == mho.PIPELINE["database_version"]
    provenance = json.loads((args.profiles_dir / "NEW/provenance.json").read_text())
    assert provenance["pipeline"] == mho.PIPELINE and provenance["source_runs"] == "ERR99"
    with pytest.raises(ValueError, match="exists"):
        module.profile(args)


@pytest.mark.asyncio
async def test_mho_comparison_reaches_analysis_json_markdown_pdf_and_evidence(cohort, tmp_path, monkeypatch):
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
    analysis.write_text(json.dumps(cohort[2]))
    result = await ReportGeneratorTool().invoke({"sample_id": "TARGET", "analysis_json_path": str(analysis)})
    assert not result.is_error, result.content
    saved = json.loads(analysis.read_text())
    report = json.loads((tmp_path / "TARGET_report.json").read_text())
    evidence = json.loads((tmp_path / "TARGET_report_evidence.json").read_text())
    assert saved["healthy_comparison"]["audit"]["status"] == "available"
    assert report["template_inputs"]["healthy_comparison"] == saved["healthy_comparison"]
    assert evidence["context"]["reference_comparison"]["healthy_population"]["provider"] == "mho"
    assert report["evidence"]["HS1"]["value"] == 50
    assert "MHOmicrobiome 对照：SYNTHETIC_MHNO" in (tmp_path / "TARGET_health_report.md").read_text()
    assert (tmp_path / "TARGET_health_report.pdf").read_bytes().startswith(b"%PDF-")
