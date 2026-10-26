"""Automatic preparation, reuse, invalidation and completed-worker recovery."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from wgs_agent.pipeline import mho_workflow as workflow
from wgs_agent.reporting import mho
from wgs_fmt_platform.paths import PROJECT_ROOT


@pytest.fixture
def automatic(tmp_path, monkeypatch):
    monkeypatch.setenv("WGS_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("WGS_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("WGS_HEALTHY_REFERENCE_PROVIDER", "mho")
    monkeypatch.setenv("WGS_MHO_AUTO_PROFILE", "true")
    monkeypatch.setenv("WGS_MHO_PROFILES_DIR", str(tmp_path / "targets"))
    base = tmp_path / "reference"
    base.mkdir()
    monkeypatch.setenv("WGS_HEALTHY_REFERENCE_DIR", str(base))
    labels = ("sample_id\tsubject_id\tstudy_id\tphenotype\tsource_runs\tsex\n"
              + "".join(f"R{i}\tP{i}\tS\tMHNO\tERR{1000+i}\tfemale\n" for i in range(35))).encode()
    matrix = ("sample_id\ts__A\ts__B\n" + "".join(f"R{i}\t{i+10}\t{90-i}\n" for i in range(35))).encode()
    (base / "metadata.tsv").write_bytes(labels)
    (base / "species_abundance.tsv").write_bytes(matrix)
    manifest = {"schema_version": mho.VERSION, "cohort_id": "SYNTHETIC",
        "cohort_version": "test", "source_url": "https://example.org/test",
        "pipeline": mho.PIPELINE, "normalization": mho.NORMALIZATION, "unit": "%",
        "phenotype": "MHNO", "body_site": "stool", "complete_species_profiles": True,
        "feature_level": "species", "minimum_subjects": 30,
        "files": {"metadata.tsv": mho.digest(labels), "species_abundance.tsv": mho.digest(matrix)}}
    (base / "manifest.json").write_text(json.dumps(manifest))
    env_root = tmp_path / "envs"
    executable = env_root / "mho-tax/bin/metaphlan"
    executable.parent.mkdir(parents=True)
    executable.write_text("synthetic executable; never run")
    (env_root / "fmt-tax/bin").mkdir(parents=True)
    monkeypatch.setenv("ENV_ROOT", str(env_root))
    db = tmp_path / "databases/metaphlan4"
    db.mkdir(parents=True)
    (db / (mho.PIPELINE["database_version"] + ".pkl")).write_bytes(b"synthetic index")
    monkeypatch.setenv("DB_ROOT", str(db.parent))
    for key in ("WGS_MHO_METAPHLAN", "WGS_MHO_TOOL_BIN", "WGS_MHO_DATABASE"):
        monkeypatch.delenv(key, raising=False)
    output = tmp_path / "bioinformatics"
    reads = output / "clean_merged/TARGET.dehosted.fastq.gz"
    reads.parent.mkdir(parents=True)
    reads.write_bytes(b"synthetic reads; no biological data")
    calls = []
    def profile(args):
        calls.append(args)
        folder = args.profiles_dir / args.sample_id
        folder.mkdir()
        raw = (f"#{mho.PIPELINE['database_version']}\n#MetaPhlAn version 4.2.2\n"
               "k__Bacteria|s__A\t2|1\t60\nk__Bacteria|s__B\t2|2\t40\n").encode()
        (folder / "profile.tsv").write_bytes(raw)
        stat = args.reads.stat()
        (folder / "provenance.json").write_text(json.dumps({
            "sample_id": args.sample_id, "pipeline": mho.PIPELINE,
            "normalization": mho.NORMALIZATION, "profile_sha256": mho.digest(raw),
            "reads": str(args.reads), "reads_bytes": stat.st_size,
            "reads_mtime_ns": stat.st_mtime_ns, "executable": str(args.metaphlan),
            "database_dir": str(args.database), "source_runs": args.source_runs}))
        (folder / "run.log").write_text("synthetic run")
    monkeypatch.setattr(workflow, "_profile", profile)
    monkeypatch.setattr(workflow, "_verify_version", lambda *_: True)
    return tmp_path, output, reads, base, calls


def test_automatic_preparation_publishes_profile_comparison_and_status(automatic):
    root, output, _, _, calls = automatic
    result = workflow.ensure_mho_profile("TARGET", output_root=output)
    assert result["state"] == "available" and result["n_subjects"] == 35
    assert len(calls) == 1 and not result["reused"]
    comparison = json.loads((root / "targets/TARGET/comparison.json").read_bytes())
    assert comparison["audit"]["status"] == "available"
    assert len(comparison["species"]) == 2 and len(comparison["diversity"]) == 4
    assert workflow.get_mho_status("TARGET")["ready"] is True


def test_repeat_comparison_reuses_target_without_new_profiling(automatic):
    _, output, _, _, calls = automatic
    workflow.ensure_mho_profile("TARGET", output_root=output)
    again = workflow.ensure_mho_profile("TARGET", output_root=output)
    assert again["state"] == "available" and again["reused"] is True
    assert len(calls) == 1


def test_input_content_change_reprofiles_and_archives_previous_result(automatic):
    root, output, reads, _, calls = automatic
    workflow.ensure_mho_profile("TARGET", output_root=output)
    reads.write_bytes(b"changed synthetic reads")
    result = workflow.ensure_mho_profile("TARGET", output_root=output)
    assert result["state"] == "available" and not result["reused"]
    assert len(calls) == 2
    assert len(list((root / "targets/.history/TARGET").iterdir())) == 1


def test_reference_and_matching_changes_only_recompute_comparison(automatic):
    root, output, _, reference, calls = automatic
    workflow.ensure_mho_profile("TARGET", output_root=output)
    path = reference / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest.update(cohort_version="next", stratify_by=["sex"])
    path.write_text(json.dumps(manifest))
    result = workflow.ensure_mho_profile("TARGET", output_root=output, metadata={"sex": "female"})
    assert result["state"] == "available" and result["reused"]
    result = workflow.ensure_mho_profile("TARGET", output_root=output, metadata={"sex": "male"})
    assert result["state"] == "failed" and result["reason"] == "insufficient_subjects"
    assert len(calls) == 1
    assert json.loads((root / "targets/TARGET/comparison.json").read_bytes())["species"] == []


def test_corrupt_cached_profile_is_rebuilt(automatic):
    root, output, _, _, calls = automatic
    workflow.ensure_mho_profile("TARGET", output_root=output)
    (root / "targets/TARGET/profile.tsv").write_text("invalid")
    assert workflow.ensure_mho_profile("TARGET", output_root=output)["state"] == "available"
    assert len(calls) == 2


def test_failed_profiler_does_not_publish_partial_profile(automatic, monkeypatch):
    root, output, _, _, _ = automatic
    def failure(args):
        raise subprocess.CalledProcessError(1, ["synthetic"])
    monkeypatch.setattr(workflow, "_profile", failure)
    result = workflow.ensure_mho_profile("TARGET", output_root=output)
    assert result["state"] == "failed" and result["reason"] == "profiling_failed"
    assert not (root / "targets/TARGET").exists()
    assert workflow.get_mho_status("TARGET")["ready"] is False


def test_explicit_failed_qc_does_not_run_profiler(automatic):
    _, output, _, _, calls = automatic
    result = workflow.ensure_mho_profile("TARGET", output_root=output, metadata={"qc_status": "failed"})
    assert result["state"] == "failed" and result["reason"] == "target_qc_failed"
    assert not calls


def test_disabled_branch_does_not_create_state(automatic, monkeypatch):
    root, output, _, _, calls = automatic
    monkeypatch.setenv("WGS_MHO_AUTO_PROFILE", "false")
    assert workflow.ensure_mho_profile("TARGET", output_root=output)["state"] == "disabled"
    assert not (root / "targets").exists() and not calls


def test_wrong_actual_profiler_version_rejects_even_a_cached_result(automatic, monkeypatch):
    _, output, _, _, calls = automatic
    workflow.ensure_mho_profile("TARGET", output_root=output)
    monkeypatch.setattr(workflow, "_verify_version", lambda *_: False)
    result = workflow.ensure_mho_profile("TARGET", output_root=output)
    assert result["state"] == "failed" and result["reason"] == "incompatible_pipeline"
    assert len(calls) == 1


def test_report_retains_prepared_identity_and_accepts_current_metadata(automatic):
    _, output, _, _, calls = automatic
    result = workflow.ensure_mho_profile("TARGET", output_root=output,
        metadata={"subject_id": "P0", "study_id": "S"})
    assert result["n_subjects"] == 34
    assert mho.compare("TARGET", {})["audit"]["n_subjects"] == 34
    assert mho.compare("TARGET", {"subject_id": "different"})["audit"]["n_subjects"] == 35
    assert len(calls) == 1


def test_missing_reads_is_recorded_without_launching_profiler(automatic):
    _, output, reads, _, calls = automatic
    reads.unlink()
    result = workflow.ensure_mho_profile("TARGET", output_root=output)
    assert result["state"] == "failed" and result["reason"] == "preparation_input_missing"
    assert not calls


def test_deleted_profile_is_no_longer_reported_ready(automatic):
    root, output, _, _, _ = automatic
    workflow.ensure_mho_profile("TARGET", output_root=output)
    (root / "targets/TARGET/profile.tsv").unlink()
    assert workflow.get_mho_status("TARGET")["ready"] is False


def test_parallel_request_cannot_run_a_second_profile(automatic):
    _, output, _, _, calls = automatic
    with workflow.sample_lock("TARGET"):
        result = workflow.ensure_mho_profile("TARGET", output_root=output)
    assert result["state"] == "failed" and not calls


def test_group_identity_is_retained_for_later_report_comparison(automatic):
    root, output, _, _, _ = automatic
    group = root / "group.json"
    group.write_text(json.dumps({"sample_id": "TARGET", "subject_id": "P0",
        "project": "S", "runs": [{"run_accession": "ERR1001"}]}))
    result = workflow.ensure_mho_profile("TARGET", output_root=output, group_json=group)
    assert result["n_subjects"] == 33
    assert mho.compare("TARGET", {})["audit"]["n_subjects"] == 33


def test_sample_deletion_catalog_includes_only_its_mho_files(automatic):
    root, _, _, _, _ = automatic
    from wgs_agent.pipeline.sample_management import _targets
    from wgs_agent.pipeline.upload_workflow import UploadWorkflowSettings
    settings = UploadWorkflowSettings.from_env()
    paths = {p for _, p in _targets("TARGET", settings, root / "results")}
    assert root / "targets/TARGET" in paths
    assert root / "targets/.workflow/TARGET.json" in paths
    assert root / "targets/.history/TARGET" in paths
    assert root / "targets/TARGET_OTHER" not in paths


def test_completed_worker_automatically_invokes_missing_healthy_branch(tmp_path):
    output = tmp_path / "outputs"
    for name in ("profiles/metaphlan/TARGET_profile.tsv",
                 "profiles/humann/TARGET_pathabundance_relab.tsv",
                 "profiles/humann/TARGET_genefamilies_relab.tsv",
                 "clean_merged/TARGET.dehosted.fastq.gz", "status/done/TARGET.done"):
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic completed artifact")
    group = tmp_path / "group.json"
    group.write_text(json.dumps({"sample_id": "TARGET"}))
    marker = tmp_path / "invocation.txt"
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{marker}'\n")
    fake_python.chmod(0o750)
    env = dict(os.environ, WGS_HEALTHY_REFERENCE_PROVIDER="mho",
               WGS_MHO_PYTHON=str(fake_python), PYTHON=sys.executable)
    result = subprocess.run(["bash", str(PROJECT_ROOT / "runtime/scripts/postfmt_pipeline/process_postfmt_sample.sh"),
        "--group-json", str(group), "--output-root", str(output)], env=env, capture_output=True)
    assert result.returncode == 0
    invocation = marker.read_text().splitlines()
    assert invocation[:3] == ["-m", "wgs_agent.pipeline.mho_workflow", "ensure"]
    assert invocation[invocation.index("--sample-id") + 1] == "TARGET"
