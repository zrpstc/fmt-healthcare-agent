"""WGS_CMD_DATA_ROOT: one setting, background preparation, automatic switch-over."""
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tarfile

import pytest

from wgs_fmt_platform import cmd_data
from wgs_agent.reporting import cmd, cohort_insights

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


prepare = load("prepare_cmd_data_under_test", ROOT / "scripts/prepare_cmd_data.py")


def publish(path):
    path.mkdir(parents=True)
    (path / "manifest.json").write_text("{}")


def test_bundle_dirs_follow_data_root_only_when_complete(tmp_path, monkeypatch):
    monkeypatch.delenv("WGS_CMD_REFERENCE_DIR", raising=False)
    monkeypatch.delenv("WGS_CMD_COHORT_DIR", raising=False)
    monkeypatch.setenv("WGS_WORKSPACE", str(tmp_path / "var"))
    monkeypatch.setenv("WGS_CMD_DATA_ROOT", str(tmp_path / "dbs"))
    paths = cmd_data.layout(tmp_path / "dbs")
    # Not prepared yet: previous default locations stay in effect.
    assert cmd.reference_dir() == tmp_path / "var/reference/cmd/native-v3"
    assert cohort_insights.bundle_dir() == tmp_path / "var/reference/cmd/cohort-models-v1"
    publish(paths["healthy"]); publish(paths["cohort"])
    assert cmd.reference_dir() == paths["healthy"]
    assert cohort_insights.bundle_dir() == paths["cohort"]
    # The MR disease-risk bundle is the third prepared artifact; until it exists the state is not ready.
    assert cmd_data.summary()["state"] != "ready"
    assert paths["disease_risk"].name.startswith("disease-risk-v1-cmd")
    assert paths["disease_risk"].name.endswith(cmd_data.weights_tag())
    monkeypatch.delenv("WGS_CMD_DISEASE_RISK_DIR", raising=False)
    publish(paths["disease_risk"])
    from wgs_agent.reporting import disease_risk
    assert disease_risk.bundle_dir() == paths["disease_risk"]
    # An explicit setting always wins.
    monkeypatch.setenv("WGS_CMD_REFERENCE_DIR", str(tmp_path / "pinned"))
    assert cmd.reference_dir() == tmp_path / "pinned"
    assert cmd_data.summary()["state"] == "ready"


def test_prepare_runs_steps_in_order_and_records_state(tmp_path):
    calls = []
    steps = [(name, lambda paths, name=name: calls.append(name)) for name in ("a", "b")]
    result = prepare.prepare(tmp_path, steps=steps, log="x.log")
    assert result["state"] == "ready" and calls == ["a", "b"]
    state = json.loads(cmd_data.layout(tmp_path)["state"].read_text())
    assert state["state"] == "ready" and state["completed"] == ["a", "b"] and state["log"] == "x.log"


def test_prepare_records_failure_and_stops(tmp_path):
    def broken(paths):
        raise prepare.StepFailure("RSCRIPT_MISSING")
    calls = []
    result = prepare.prepare(tmp_path, steps=[("metadata", broken), ("later", lambda p: calls.append(1))])
    assert result["state"] == "failed" and result["error"] == "RSCRIPT_MISSING" and not calls
    summary = cmd_data.summary({"WGS_CMD_DATA_ROOT": str(tmp_path)})
    assert summary["state"] == "failed" and summary["error"] == "RSCRIPT_MISSING"


def test_second_instance_exits_while_first_holds_lock(tmp_path):
    paths = cmd_data.layout(tmp_path)
    paths["base"].mkdir(parents=True)
    fd = os.open(paths["lock"], os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert prepare.prepare(tmp_path, steps=[])["state"] == "already_running"
        paths["state"].write_text(json.dumps({"state": "running", "step": "healthy"}))
        assert cmd_data.summary({"WGS_CMD_DATA_ROOT": str(tmp_path)})["state"] == "running"
    finally:
        os.close(fd)
    # Lock released without a final record: shown as interrupted, resumed at next start.
    assert cmd_data.summary({"WGS_CMD_DATA_ROOT": str(tmp_path)})["state"] == "interrupted"


def test_catalog_is_verified_before_publishing(tmp_path):
    paths = cmd_data.layout(tmp_path)

    def fetch(url, destination, rows=1):
        connection = sqlite3.connect(destination)
        connection.execute("create table resources (title text)")
        connection.executemany("insert into resources values (?)", [("2021.X.relative_abundance",)] * rows)
        connection.commit(); connection.close()

    with pytest.raises(prepare.StepFailure) as error:
        prepare.step_catalog(paths, fetch=lambda u, d: fetch(u, d, rows=0))
    assert error.value.code == "CATALOG_INVALID" and not paths["catalog"].exists()
    prepare.step_catalog(paths, fetch=fetch)
    assert paths["catalog"].is_file()


def test_metadata_requires_rscript(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare.shutil, "which", lambda name: None)
    with pytest.raises(prepare.StepFailure) as error:
        prepare.step_metadata(cmd_data.layout(tmp_path))
    assert error.value.code == "RSCRIPT_MISSING"


def test_metadata_export_uses_pinned_release(tmp_path, monkeypatch):
    paths = cmd_data.layout(tmp_path)
    seen = {}
    monkeypatch.setattr(prepare.shutil, "which", lambda name: "/usr/bin/Rscript")

    def run(args, **kwargs):
        seen["args"] = args
        paths["archive"].parent.mkdir(parents=True)
        paths["archive"].write_bytes(b"x"); paths["metadata"].write_text("sample_id\n")
        return type("R", (), {"returncode": 0})()
    prepare.step_metadata(paths, run=run)
    assert seen["args"][-2:] == ["--bioc-release", cmd_data.BIOC_RELEASE]
    assert str(paths["metadata_dir"]) in seen["args"]


def make_archive(path, version):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as archive:
        for name, text in (("curatedMetagenomicData/DESCRIPTION", f"Package: curatedMetagenomicData\nVersion: {version}\n"),
                           ("curatedMetagenomicData/inst/extdata/metadata.csv", "Title\n")):
            data = text.encode()
            info = tarfile.TarInfo(name); info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def test_package_is_unpacked_and_version_checked(tmp_path):
    paths = cmd_data.layout(tmp_path)
    make_archive(paths["archive"], "3.14.0")
    with pytest.raises(prepare.StepFailure) as error:
        prepare.step_package(paths)
    assert error.value.code == "SOURCE_VERSION_MISMATCH" and not paths["package"].exists()
    make_archive(paths["archive"], cmd_data.CMD_VERSION)
    prepare.step_package(paths)
    assert (paths["package"] / "inst/extdata/metadata.csv").is_file()


@pytest.fixture
def runtime_config(tmp_path):
    runtime = load("runtime_cmd_data_under_test", ROOT / "deploy/lib/runtime.py")
    root = tmp_path / "project"
    (root / "apps/workspace-web").mkdir(parents=True)
    (root / ".env").write_text(f"WGS_ELASTICSEARCH_MANAGED=false\nWGS_CMD_DATA_ROOT={tmp_path / 'dbs'}\n")
    return runtime, runtime.Config.load(root, parent_env={"PATH": os.environ["PATH"]})


def test_start_launches_background_preparation_once_until_ready(runtime_config, monkeypatch, tmp_path):
    runtime, config = runtime_config
    launched = []

    class Proc:
        pid = 4242

    def popen(args, **kwargs):
        launched.append((args, kwargs))
        return Proc()
    monkeypatch.setattr(runtime.subprocess, "Popen", popen)
    result = runtime.launch_cmd_preparation(config)
    assert result["state"] == "preparing" and result["pid"] == 4242
    args, kwargs = launched[0]
    assert args[1].endswith("scripts/prepare_cmd_data.py") and kwargs["start_new_session"] is True
    paths = cmd_data.layout(tmp_path / "dbs")
    publish(paths["healthy"]); publish(paths["cohort"])
    # Still missing the disease-risk bundle: preparation is launched again (it skips finished steps).
    assert runtime.launch_cmd_preparation(config)["state"] == "preparing" and len(launched) == 2
    publish(paths["disease_risk"])
    assert runtime.launch_cmd_preparation(config)["state"] == "ready" and len(launched) == 2


def test_start_without_data_root_is_unchanged(runtime_config, monkeypatch):
    runtime, config = runtime_config
    config.env.pop("WGS_CMD_DATA_ROOT")
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch"))
    assert runtime.launch_cmd_preparation(config) == {"state": "disabled"}
