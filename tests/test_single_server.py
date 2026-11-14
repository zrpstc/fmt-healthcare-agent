"""Regression coverage for local addressing and fresh, relocatable data."""

import os
import shutil
import sqlite3
import subprocess
import sys

import pytest

from wgs_fmt_platform.paths import PROJECT_ROOT, knowledge_db_path, runtime_path, workspace_root


@pytest.fixture
def clean_runtime_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith("WGS_"):
            monkeypatch.delenv(name)


def test_default_paths_do_not_follow_shell_directory(clean_runtime_env, monkeypatch, tmp_path):
    from wgs_agent.pipeline.upload_workflow import UploadWorkflowSettings
    from wgs_fmt_platform.config import Settings

    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None)
    uploads = UploadWorkflowSettings.from_env()
    assert workspace_root() == PROJECT_ROOT / "var"
    assert settings.workspace == uploads.workspace == workspace_root()
    assert uploads.output_root == workspace_root() / "bioinformatics"
    assert (
        uploads.worker
        == PROJECT_ROOT / "runtime/scripts/postfmt_pipeline/process_postfmt_sample.sh"
    )
    assert knowledge_db_path() == workspace_root() / "knowledge/kb.db"
    assert settings.artifact_root == workspace_root() / "artifacts"


def test_workspace_override_moves_all_default_data(clean_runtime_env, monkeypatch, tmp_path):
    from wgs_agent.pipeline.upload_workflow import UploadWorkflowSettings
    from wgs_fmt_platform.config import Settings

    root = tmp_path / "fresh"
    monkeypatch.setenv("WGS_WORKSPACE", str(root))
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None)
    uploads = UploadWorkflowSettings.from_env()
    assert uploads.upload_root == root / "uploads"
    assert uploads.job_root == root / "upload-jobs"
    assert uploads.output_root == root / "bioinformatics"
    assert settings.model_registry_root == root / "model-registry"
    assert settings.mproject_database == root / "databases/human-gut"
    assert settings.metadata_database_url == f"sqlite:///{root / 'metadata.db'}"
    assert knowledge_db_path() == root / "knowledge/kb.db"
    monkeypatch.setenv("WGS_RESULTS_DIR", "custom-results")
    assert runtime_path("WGS_RESULTS_DIR", "results") == PROJECT_ROOT / "custom-results"
    monkeypatch.setenv("WGS_KB_SQLITE_PATH", str(tmp_path / "custom-kb.db"))
    assert knowledge_db_path() == tmp_path / "custom-kb.db"


def test_init_and_api_use_empty_local_databases(clean_runtime_env, tmp_path):
    root = tmp_path / "runtime"
    env = {
        **os.environ,
        "WGS_WORKSPACE": str(root),
        "PYTHONPATH": f"{PROJECT_ROOT / 'src'}:{PROJECT_ROOT / 'apps/workspace-api'}",
    }
    command = [sys.executable, str(PROJECT_ROOT / "scripts/init_data.py")]
    subprocess.run(command, env=env, cwd=tmp_path, check=True, capture_output=True, text=True)
    with sqlite3.connect(root / "db/wgs_agent.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
    with sqlite3.connect(root / "knowledge/kb.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
    # In-process HTTP calls: no listening server, no deployment, no external API.
    source = """
from fastapi.testclient import TestClient
from app.main import app, KNOWLEDGE_DB, RESULTS_DIR, RUNNER_STATUS
from wgs_fmt_platform.paths import workspace_root
root = workspace_root()
assert KNOWLEDGE_DB == root / 'knowledge/kb.db'
assert RESULTS_DIR == root / 'results'
assert RUNNER_STATUS == root / 'bioinformatics/status/runner_status.tsv'
with TestClient(app) as client:
    assert client.get('/health').json()['status'] == 'ok'
    assert client.get('/api/samples').json()['count'] == 0
    assert client.get('/api/reports').json()['count'] == 0
    assert client.get('/api/knowledge/stats').json()['papers'] == 0
    settings = client.get('/api/settings').json()
    assert settings['knowledge_base_path'] == str(KNOWLEDGE_DB)
    assert settings['artifact_sandbox_root'] == str(root / 'sandboxes')
    assert client.put('/api/settings', json=settings).status_code == 200
    assert client.post('/api/settings/sandbox-test', json={'settings': settings}).json()['ok'] is True
"""
    subprocess.run(
        [sys.executable, "-c", source],
        env=env,
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert not list((root / "run").glob("*.pid"))
    # Re-running directory/schema initialization must preserve new records.
    with sqlite3.connect(root / "knowledge/kb.db") as connection:
        connection.execute("INSERT INTO papers (pmid, title) VALUES ('1', 'New local record')")
    subprocess.run(command, env=env, cwd=tmp_path, check=True, capture_output=True, text=True)
    with sqlite3.connect(root / "knowledge/kb.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1


def test_shell_config_matches_python_from_other_directory(clean_runtime_env, tmp_path):
    import json
    import shlex
    # Exercise the maintained shared core in an isolated checkout with no live .env.
    isolated_root = tmp_path / "project"
    shutil.copytree(PROJECT_ROOT / "deploy", isolated_root / "deploy")
    source = isolated_root / "src/wgs_fmt_platform"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("")
    shutil.copy2(PROJECT_ROOT / "src/wgs_fmt_platform/process_identity.py", source / "process_identity.py")
    interpreter = isolated_root / ".venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text('#!/bin/bash\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
    interpreter.chmod(0o700)
    (isolated_root / ".env").write_text(
        'WGS_WORKSPACE=var-relocated\nWGS_API_PORT=8604\n'
        'WGS_ELASTICSEARCH_MANAGED=false\nWGS_ELASTICSEARCH_URL=http://127.0.0.1:1\n')
    env = {**os.environ, "WGS_WORKSPACE": "stale-workspace", "WGS_API_PORT": "8603"}
    command = ["bash", str(isolated_root / "deploy/status.sh")]
    result = subprocess.run(command, env=env, cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert json.loads(result.stdout)['result']['ports']['api'] == 8604
    (isolated_root / ".env").write_text('WGS_API_PORT=invalid\n')
    result = subprocess.run(command, env=env, cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert json.loads(result.stdout)['error'] == 'INVALID_PORT'


def test_local_preparation_does_not_connect_to_external_database(clean_runtime_env, tmp_path):
    env = {
        **os.environ,
        "WGS_WORKSPACE": str(tmp_path),
        "WGS_DATABASE_URL": "mysql+pymysql://unused@127.0.0.1:1/unused",
    }
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts/init_data.py")],
        env=env, check=True, capture_output=True, text=True, timeout=10,
    )
    assert "External conversation database skipped" in result.stdout
    assert (tmp_path / "knowledge/kb.db").is_file()
    assert not (tmp_path / "db/wgs_agent.db").exists()
