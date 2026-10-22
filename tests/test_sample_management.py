"""Sample edits and irreversible per-sample deletion use synthetic runtime data."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main
from app.agent_chat import _invoke_tool, _list_samples
from wgs_agent.pipeline import sample_management as management
from wgs_agent.pipeline.sample_registry import read_record, sample_lock
from wgs_agent.pipeline.upload_workflow import submit_uploaded_sample


AUTH = {"Authorization": "Bearer synthetic-test-token"}
CONFIRM = {"confirmed": True, "confirm_sample_id": "p2"}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    for key, value in {
        "WGS_WORKSPACE": tmp_path,
        "WGS_RESULTS_DIR": tmp_path / "results",
        "WGS_UPLOAD_ROOT": tmp_path / "uploads",
        "WGS_UPLOAD_JOB_ROOT": tmp_path / "upload-jobs",
        "WGS_BIOINFORMATICS_OUTPUT_ROOT": tmp_path / "bioinformatics",
        "WGS_RUNNER_STATUS": tmp_path / "bioinformatics/status/runner_status.tsv",
        "WGS_AGENT_AUDIT_DIR": tmp_path / "audit",
        "WGS_SAMPLE_REGISTRY_DIR": tmp_path / "sample-registry",
    }.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.setattr(main, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(main, "RUNNER_STATUS", tmp_path / "bioinformatics/status/runner_status.tsv")

    def authenticate(value):
        if value != AUTH["Authorization"]:
            raise HTTPException(401, "请先登录。")
        return SimpleNamespace(id="test-user", role="researcher")

    monkeypatch.setattr(main, "_authenticated_user", authenticate)
    return tmp_path


def write(root, relative, content="synthetic content"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def create_sample(root, sid="p2", *, running=False, full=False):
    write(root, f"upload-jobs/jobs/{sid}.json", json.dumps({
        "sample_id": sid, "state": "running", "pid": os.getpid() if running else 99999999,
        "files": [{}], "submitted_at": "2026-01-01T00:00:00+00:00",
    }))
    if not running:
        write(root, f"bioinformatics/status/done/{sid}.done")
    paths = [
        f"uploads/{sid}/{sid}_R1.fastq.gz", f"uploads/{sid}/{sid}_R2.fastq.gz",
        f"upload-jobs/groups/{sid}.json", f"upload-jobs/launcher-logs/{sid}.log",
        f"bioinformatics/qc/{sid}/{sid}_fastp.json", f"bioinformatics/work/{sid}/work.txt",
        f"bioinformatics/clean_merged/{sid}.dehosted.fastq.gz", f"bioinformatics/logs/{sid}.log",
        f"bioinformatics/profiles/metaphlan/{sid}_profile.tsv",
        f"bioinformatics/profiles/metaphlan_humann_vJun23/{sid}_profile.tsv",
    ]
    if full:
        for name in ("pathabundance", "genefamilies", "pathcoverage"):
            paths += [f"bioinformatics/profiles/humann/{sid}_{name}{ending}" for ending in (".tsv", "_relab.tsv")]
        paths += [f"results/{sid}{suffix}" for suffix in management.RESULT_SUFFIXES]
        paths += [f"results/figures/{sid}{suffix}" for suffix in management.RESULT_SUFFIXES if suffix.endswith(".png")]
        paths += [f"results/.{sid}.report.lock"]
    for path in paths:
        write(root, path)
    if full:
        write(root, f"results/{sid}_analysis.json", '{"sample_id":"' + sid + '"}')
    return [root / path for path in paths]


def test_edit_uploaded_sample_without_analysis_preserves_id_and_files(runtime):
    paths = create_sample(runtime)
    before = {path: path.read_bytes() for path in paths}
    with TestClient(main.app) as client:
        response = client.patch("/api/samples/p2", headers=AUTH, json={"name": " Test name ", "notes": " 16S test\nDo not rerun "})
        assert response.status_code == 200, response.text
        assert response.json()["sample_id"] == "p2"
        assert response.json()["name"] == "Test name"
        row = client.get("/api/samples?q=test name").json()["samples"][0]
        assert row["name"] == "Test name" and row["notes"] == "16S test\nDo not rerun"
        assert row["artifacts"]["analysis"]["exists"] is False
        report = client.get("/api/reports?q=test name").json()["reports"][0]
        assert report["sample_id"] == "p2" and report["name"] == "Test name"
        assert client.patch("/api/samples/p2", headers=AUTH, json={"name": "Renamed"}).status_code == 200
        assert read_record("p2")["notes"] == "16S test\nDo not rerun"
    assert before == {path: path.read_bytes() for path in paths}


def test_mutations_require_login_and_write_role(runtime, monkeypatch):
    create_sample(runtime)
    with TestClient(main.app) as client:
        assert client.patch("/api/samples/p2", json={"name": "new"}).status_code == 401
        assert client.request("DELETE", "/api/samples/p2", json=CONFIRM).status_code == 401
        monkeypatch.setattr(main, "_authenticated_user", lambda _: SimpleNamespace(id="viewer", role="viewer"))
        assert client.patch("/api/samples/p2", headers=AUTH, json={"name": "new"}).status_code == 403
        assert client.request("DELETE", "/api/samples/p2", headers=AUTH, json=CONFIRM).status_code == 403
    assert (runtime / "uploads/p2").is_dir()


@pytest.mark.parametrize("payload", [{}, {"confirmed": True}, {"confirmed": True, "confirm_sample_id": "p2_other"}])
def test_delete_requires_confirmation_and_exact_id(runtime, payload):
    create_sample(runtime)
    with TestClient(main.app) as client:
        assert client.request("DELETE", "/api/samples/p2", headers=AUTH, json=payload).status_code == 409
    assert (runtime / "uploads/p2").is_dir()
    assert not read_record("p2")


def test_delete_permanently_removes_owned_files_and_preserves_other_samples(runtime):
    targets = create_sample(runtime, full=True)
    neighbours = create_sample(runtime, "p2_other", full=True)
    shared = write(runtime, "reference/cohort.tsv", "shared reference")
    runner = write(runtime, "bioinformatics/status/runner_status.tsv", "sample_id\tstate\np2\tcomplete\np2_other\tcomplete\n")
    with TestClient(main.app) as client:
        client.patch("/api/samples/p2", headers=AUTH, json={"name": "private name", "notes": "private note"})
        response = client.request("DELETE", "/api/samples/p2", headers=AUTH, json=CONFIRM)
        assert response.status_code == 200, response.text
        assert response.json()["removed_paths"] > 0
        assert all(not path.exists() for path in targets)
        assert not (runtime / "upload-jobs/jobs/p2.json").exists()
        assert not (runtime / "uploads/p2").exists()
        assert all(path.exists() for path in neighbours) and shared.read_text() == "shared reference"
        assert "p2\tcomplete" in runner.read_text()  # Shared runner history is filtered, not erased.
        assert [row["sample_id"] for row in client.get("/api/samples").json()["samples"]] == ["p2_other"]
        assert [row["sample_id"] for row in client.get("/api/reports").json()["reports"]] == ["p2_other"]
        for url in ["/api/samples/p2", "/api/samples/p2/workflow", "/api/samples/p2/plot", "/api/reports/p2/pdf", "/api/reports/p2/figures/p2_report_species.png"]:
            assert client.get(url).status_code == 410, url
        assert client.post("/api/reports/p2/generate", json={"confirmed": True}).status_code == 410
        assert client.request("DELETE", "/api/samples/p2", headers=AUTH, json=CONFIRM).status_code == 200
    assert read_record("p2")["deletion_status"] == "deleted"
    assert "name" not in read_record("p2") and "notes" not in read_record("p2")
    assert [row["sample_id"] for row in _list_samples()["samples"]] == ["p2_other"]
    with pytest.raises(RuntimeError, match="删除"):
        _invoke_tool("get_sample_status", {"sample_id": "p2"}, [])
    with pytest.raises(RuntimeError, match="删除"):
        submit_uploaded_sample("p2", "paired", None, "r1.fastq", None, "r2.fastq")


@pytest.mark.parametrize("mode", ["worker", "worker_lock", "sample_lock", "report_lock", "runner"])
def test_active_jobs_and_report_generation_block_deletion(runtime, mode):
    import fcntl

    create_sample(runtime, running=mode == "worker", full=True)
    if mode == "worker_lock":
        (runtime / "bioinformatics/status/locks/p2.lock").mkdir(parents=True)
    if mode == "runner":
        write(runtime, "bioinformatics/status/runner_status.tsv", "sample_id\tstate\np2\trunning\n")
    lock = None
    handle = None
    if mode == "sample_lock":
        lock = sample_lock("p2")
        lock.__enter__()
    if mode == "report_lock":
        handle = (runtime / "results/.p2.report.lock").open("r+")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with TestClient(main.app) as client:
            response = client.request("DELETE", "/api/samples/p2", headers=AUTH, json=CONFIRM)
            assert response.status_code == 409, response.text
        assert (runtime / "uploads/p2").is_dir()
        assert not read_record("p2")
    finally:
        if handle:
            handle.close()
        if lock:
            lock.__exit__(None, None, None)


def test_partial_delete_failure_remains_visible_and_is_retryable(runtime, monkeypatch):
    create_sample(runtime, full=True)
    original = management._remove_path

    def fail_after_upload(root, path):
        if path.name == "p2.json":
            raise PermissionError("synthetic failure")
        return original(root, path)

    monkeypatch.setattr(management, "_remove_path", fail_after_upload)
    with TestClient(main.app) as client:
        response = client.request("DELETE", "/api/samples/p2", headers=AUTH, json=CONFIRM)
        assert response.status_code == 500
        assert not (runtime / "uploads/p2").exists()
        assert read_record("p2")["deletion_status"] == "failed"
        assert client.get("/api/samples").json()["samples"][0]["status"] == "delete_failed"
        monkeypatch.setattr(management, "_remove_path", original)
        assert client.request("DELETE", "/api/samples/p2", headers=AUTH, json=CONFIRM).status_code == 200
        assert client.get("/api/samples").json()["count"] == 0


def test_sample_symlink_is_unlinked_without_following_its_target(runtime, tmp_path_factory):
    create_sample(runtime)
    outside = tmp_path_factory.mktemp("outside-sample")
    valuable = write(outside, "keep.txt", "keep")
    shutil = __import__("shutil")
    shutil.rmtree(runtime / "uploads/p2")
    (runtime / "uploads/p2").symlink_to(outside, target_is_directory=True)
    with TestClient(main.app) as client:
        response = client.request("DELETE", "/api/samples/p2", headers=AUTH, json=CONFIRM)
        assert response.status_code == 200, response.text
    assert valuable.read_text() == "keep"


def test_redirected_parent_directory_is_rejected_before_any_deletion(runtime, tmp_path_factory):
    create_sample(runtime)
    outside = tmp_path_factory.mktemp("outside-profile")
    target = write(outside, "p2_profile.tsv", "keep")
    (runtime / "bioinformatics/profiles/metaphlan/p2_profile.tsv").unlink()
    (runtime / "bioinformatics/profiles/metaphlan").rmdir()
    (runtime / "bioinformatics/profiles/metaphlan").symlink_to(outside, target_is_directory=True)
    with TestClient(main.app) as client:
        response = client.request("DELETE", "/api/samples/p2", headers=AUTH, json=CONFIRM)
        assert response.status_code == 422
    assert (runtime / "uploads/p2").exists() and target.read_text() == "keep"


def test_edit_validation_and_unknown_sample_errors(runtime):
    create_sample(runtime)
    with TestClient(main.app) as client:
        assert client.patch("/api/samples/p2", headers=AUTH, json={"sample_id": "new-id"}).status_code == 422
        assert client.patch("/api/samples/p2", headers=AUTH, json={"name": "x" * 101}).status_code == 422
        assert client.patch("/api/samples/missing", headers=AUTH, json={"name": "new"}).status_code == 404
        assert client.request("DELETE", "/api/samples/missing", headers=AUTH, json={"confirmed": True, "confirm_sample_id": "missing"}).status_code == 404


def test_sample_lock_blocks_upload_and_report_generation(runtime):
    create_sample(runtime, full=True)
    with sample_lock("p2"), TestClient(main.app) as client:
        response = client.post("/api/reports/p2/generate", json={"confirmed": True})
        assert response.status_code == 409
        response = client.post("/api/samples/upload", data={"sample_id": "p2", "layout": "single"}, files={
            "read1": ("reads.fastq", b"@test\nACGT\n+\nIIII\n", "application/octet-stream"),
        })
        assert response.status_code == 409
    assert (runtime / "uploads/p2/p2_R1.fastq.gz").exists()


def test_changed_storage_configuration_blocks_delete_before_touching_files(runtime):
    create_sample(runtime)
    job = runtime / "upload-jobs/jobs/p2.json"
    data = json.loads(job.read_text())
    data["settings"] = {"output_root": str(runtime / "previous-location")}
    job.write_text(json.dumps(data))
    with TestClient(main.app) as client:
        response = client.request("DELETE", "/api/samples/p2", headers=AUTH, json=CONFIRM)
        assert response.status_code == 409
    assert (runtime / "uploads/p2").exists() and not read_record("p2")


def test_completed_zombie_worker_is_not_treated_as_running():
    from wgs_agent.pipeline.upload_workflow import _pid_alive

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        stat = Path(f"/proc/{child.pid}/stat")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if stat.read_text().rsplit(")", 1)[1].split()[0] == "Z":
                break
            time.sleep(0.01)
        else:
            pytest.fail("Synthetic worker did not reach exited/zombie state")
        assert _pid_alive(child.pid) is False
    finally:
        child.wait(timeout=5)
