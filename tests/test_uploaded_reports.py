"""Completed uploads must be able to create their first report without an analysis JSON."""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from wgs_agent.reporting.analysis import ensure_analysis_input
from wgs_agent.tools import detailed_report, report_maker


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    for key, value in {
        "WGS_WORKSPACE": tmp_path,
        "WGS_RESULTS_DIR": tmp_path / "results",
        "WGS_UPLOAD_ROOT": tmp_path / "uploads",
        "WGS_UPLOAD_JOB_ROOT": tmp_path / "upload-jobs",
        "WGS_BIOINFORMATICS_OUTPUT_ROOT": tmp_path / "bioinformatics",
        "WGS_AGENT_AUDIT_DIR": tmp_path / "audit",
    }.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.setattr(main, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(detailed_report, "resolve_report_model", lambda: None)
    monkeypatch.setattr(detailed_report, "load_gene_family_evidence", lambda _: {})
    return tmp_path


def upload(root: Path, sid="SYNTHETIC", state="complete"):
    jobs = root / "upload-jobs/jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    (jobs / f"{sid}.json").write_text(json.dumps({
        "sample_id": sid, "state": "running", "pid": os.getpid() if state == "running" else None,
        "files": [{}], "submitted_at": "2026-01-01T00:00:00+00:00",
    }))
    if state == "complete":
        done = root / f"bioinformatics/status/done/{sid}.done"
        done.parent.mkdir(parents=True, exist_ok=True)
        done.write_text("synthetic completion marker")


def profiles(root: Path, sid="SYNTHETIC"):
    taxonomy = root / f"bioinformatics/profiles/metaphlan/{sid}_profile.tsv"
    taxonomy.parent.mkdir(parents=True, exist_ok=True)
    taxonomy.write_text(
        "#clade_name\tNCBI_tax_id\trelative_abundance\n"
        "k__Bacteria|p__Actinomycetota\t2|201174\t100\n"
        "k__Bacteria|g__Bifidobacterium\t2|1678\t100\n"
        "k__Bacteria|g__Bifidobacterium|s__Bifidobacterium_longum\t2|1678|216816\t60\n"
        "k__Bacteria|g__Bifidobacterium|s__Bifidobacterium_breve\t2|1678|1685\t40\n"
    )
    pathways = root / f"bioinformatics/profiles/humann/{sid}_pathabundance_relab.tsv"
    pathways.parent.mkdir(parents=True, exist_ok=True)
    pathways.write_text(
        "# Pathway\tSYNTHETIC_Abundance\n"
        "UNMAPPED\t0.2\nPWY-TEST: Synthetic carbohydrate pathway\t0.8\n"
    )
    return taxonomy, pathways


def test_report_index_includes_completed_upload_without_writing(runtime):
    upload(runtime)
    upload(runtime, "RUNNING", "running")
    upload(runtime, "FAILED", "failed")
    with TestClient(main.app, raise_server_exceptions=True) as client:
        # Startup may create config/database directories, but must not generate analyses.
        response = client.get("/api/reports?q=SYNTHETIC")
        assert response.status_code == 200
        result = response.json()
        assert result["count"] == 1
        assert result["pdf_count"] == result["markdown_count"] == 0
        row = result["reports"][0]
        assert row["status"] == "bioinformatics_complete"
        assert row["updated_at"] == "2026-01-01T00:00:00+00:00"
        assert not any(value["exists"] for value in row["artifacts"].values())
        assert client.get("/api/reports").json()["count"] == 1
        assert client.post("/api/reports/SYNTHETIC/generate", json={}).status_code == 409
    assert not list((runtime / "results").glob("*_analysis.json"))


def test_first_report_bootstraps_real_artifacts_from_uploaded_profiles(runtime):
    upload(runtime)
    taxonomy, pathways = profiles(runtime)
    before = (taxonomy.read_bytes(), pathways.read_bytes())
    with TestClient(main.app) as client:
        response = client.post("/api/reports/SYNTHETIC/generate", json={"confirmed": True})
        assert response.status_code == 200, response.text
        assert response.json()["llm_status"] == "not_configured"
        assert all(response.json()["artifacts"][kind]["exists"] for kind in (
            "analysis", "markdown", "pdf", "structured", "evidence",
        ))
        assert client.get("/api/samples/SYNTHETIC").status_code == 200
        result = client.get("/api/reports").json()
        assert result["pdf_count"] == result["markdown_count"] == 1
        assert result["reports"][0]["status"] == "report_ready"
        assert client.get("/api/reports/SYNTHETIC/pdf").content.startswith(b"%PDF-")
    analysis_path = runtime / "results/SYNTHETIC_analysis.json"
    analysis = json.loads(analysis_path.read_text())
    assert analysis["sample_id"] == "SYNTHETIC"
    assert [row["abundance"] for row in analysis["species"]["species_list"]] == [60, 40]
    assert analysis["species"]["n_total"] == 2
    assert analysis["species"]["n_unknown"] == 2
    assert "diseases" not in analysis and "metabolites" not in analysis
    assert analysis["diversity"]["richness"] == 2
    assert analysis["pathways"]["n_total_pathways"] == 1
    assert analysis_path.stat().st_mode & 0o777 == 0o600
    assert before == (taxonomy.read_bytes(), pathways.read_bytes())


@pytest.mark.parametrize("problem", ["running", "missing", "invalid_taxonomy", "empty_functions"])
def test_incomplete_or_invalid_profiles_do_not_publish_placeholder_analysis(runtime, problem):
    upload(runtime, state="running" if problem == "running" else "complete")
    taxonomy, pathways = profiles(runtime)
    if problem == "missing":
        pathways.unlink()
    elif problem == "invalid_taxonomy":
        taxonomy.write_text("k__Bacteria|s__Synthetic_species\t2|1\tnan\n")
    elif problem == "empty_functions":
        pathways.write_text("# header only\n")
    with TestClient(main.app) as client:
        response = client.post("/api/reports/SYNTHETIC/generate", json={"confirmed": True})
        assert response.status_code == 422
    assert not (runtime / "results/SYNTHETIC_analysis.json").exists()
    assert not list((runtime / "results").glob("*_health_report.*"))


def test_existing_rich_analysis_is_preserved(runtime, monkeypatch):
    from wgs_agent.reporting import analysis

    output = runtime / "results"
    output.mkdir()
    target = output / "SYNTHETIC_analysis.json"
    target.write_text('{"sample_id":"SYNTHETIC","custom":"preserve exactly"}')
    original = target.read_bytes()

    def unexpected_read(_):
        pytest.fail("Existing analysis must not be rebuilt from profiles")

    monkeypatch.setattr(analysis, "load_existing_report_inputs", unexpected_read)
    assert ensure_analysis_input("SYNTHETIC", output) == target
    assert target.read_bytes() == original


def test_analysis_publication_does_not_overwrite_a_concurrent_writer(runtime, monkeypatch):
    from wgs_agent.reporting import analysis

    profiles(runtime)
    real_link = analysis.os.link

    def competing_writer(source, target):
        target.write_text('{"sample_id":"SYNTHETIC","custom":"concurrent"}')
        real_link(source, target)

    monkeypatch.setattr(analysis.os, "link", competing_writer)
    target = ensure_analysis_input("SYNTHETIC", runtime / "results")
    assert json.loads(target.read_text())["custom"] == "concurrent"
    assert not list(target.parent.glob(".SYNTHETIC-analysis-*"))


def test_pdf_failure_can_be_retried_without_rerunning_bioinformatics(runtime, monkeypatch):
    upload(runtime)
    profiles(runtime)
    renderer = report_maker._generate_fpdf_report

    def fail(*args):
        raise RuntimeError("synthetic renderer failure")

    monkeypatch.setattr(report_maker, "_generate_fpdf_report", fail)
    with TestClient(main.app) as client:
        response = client.post("/api/reports/SYNTHETIC/generate", json={"confirmed": True})
        assert response.status_code == 502
        target = runtime / "results/SYNTHETIC_analysis.json"
        original = target.read_bytes()
        assert not (runtime / "results/SYNTHETIC_health_report.md").exists()
        assert client.get("/api/reports").json()["reports"][0]["status"] == "analysis_ready"
        monkeypatch.setattr(report_maker, "_generate_fpdf_report", renderer)
        retry = client.post("/api/reports/SYNTHETIC/generate", json={"confirmed": True})
        assert retry.status_code == 200, retry.text
        assert target.read_bytes() == original
