"""Verify public shell routing and dependency preflight without real service changes."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import Mock

import pytest

from test_project_runtime import config, runtime


@pytest.mark.parametrize('action', ['start', 'stop', 'restart', 'status'])
@pytest.mark.parametrize('outside_project', [False, True])
def test_four_entrypoints_route_to_same_core_from_any_directory(tmp_path, action, outside_project):
    root = tmp_path/'checkout with spaces'
    shutil.copytree(runtime.ROOT/'deploy',root/'deploy')
    interpreter = root/'.venv/bin/python'
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n')
    interpreter.chmod(0o700)
    result = subprocess.run(['bash',str(root/f'deploy/{action}.sh')],cwd=tmp_path if outside_project else root,
                            capture_output=True,text=True,env={'PATH':os.environ['PATH']})
    assert result.returncode == 0
    assert result.stdout.splitlines() == [str(root/'deploy/lib/runtime.py'),action]


def test_wrapper_propagates_failure_and_missing_interpreter_is_explicit(tmp_path):
    root = tmp_path/'checkout'
    shutil.copytree(runtime.ROOT/'deploy',root/'deploy')
    command = ['bash',str(root/'deploy/start.sh')]
    result = subprocess.run(command,capture_output=True,text=True)
    assert result.returncode == 1
    assert json.loads(result.stderr)['error'] == 'PROJECT_PYTHON_MISSING'
    interpreter = root/'.venv/bin/python'
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text('#!/bin/bash\nexit 23\n')
    interpreter.chmod(0o700)
    assert subprocess.run(command,capture_output=True).returncode == 23


def test_external_dependency_failure_prevents_restart_shutdown(config, monkeypatch, capsys):
    config.managed_search = False
    monkeypatch.setattr(runtime.Config,'load',lambda:config)
    monkeypatch.setattr(runtime,'deployment_lock',lambda config:contextlib.nullcontext())
    monkeypatch.setattr(runtime,'search_health',lambda config:{'state':'unavailable'})
    shutdown = Mock()
    startup = Mock()
    monkeypatch.setattr(runtime,'stop',shutdown)
    monkeypatch.setattr(runtime,'start',startup)
    assert runtime.main(['restart']) == 1
    assert json.loads(capsys.readouterr().out)['error'] == 'EXTERNAL_ELASTICSEARCH_UNAVAILABLE'
    shutdown.assert_not_called()
    startup.assert_not_called()


def test_external_start_checks_health_and_never_controls_docker(config, monkeypatch):
    config.managed_search = False
    config.agent_enabled = False
    monkeypatch.setattr(runtime,'search_health',lambda config:{'state':'running','health':'yellow'})
    monkeypatch.setattr(runtime,'discover',lambda *args:{})
    monkeypatch.setattr(runtime,'repair_project_ownership',lambda *args:None)
    monkeypatch.setattr(runtime,'prepare_application_data',lambda *args:None)
    monkeypatch.setattr(runtime,'ensure_build',lambda *args:('.next-test',False))
    operations = []
    monkeypatch.setattr(runtime,'run_checked',lambda config,args,label,**kw:operations.append(label))
    monkeypatch.setattr(runtime,'start_process',lambda config,role,dist:operations.append(role) or 100)
    # Application start preflight itself is permitted; managed_search must return before requiring admin.
    config.require_privilege = lambda component: None if component == 'all' else pytest.fail('unexpected Docker privilege request')
    runtime.start(config)
    assert operations == ['initialize','workspace-api','workspace-web']


def test_external_stop_cleans_application_without_dependency_command(config, monkeypatch):
    config.managed_search = False
    monkeypatch.setattr(runtime,'stop_processes',lambda config,roles:2)
    monkeypatch.setattr(runtime,'discover',lambda *args:{})
    docker = Mock(side_effect=AssertionError('external dependency must remain running'))
    monkeypatch.setattr(runtime,'run_checked',docker)
    assert runtime.stop(config)['elasticsearch'] == 'external'
    docker.assert_not_called()


def test_status_reports_external_health_and_overall_readiness(config, monkeypatch):
    config.managed_search = False
    config.agent_enabled = False
    monkeypatch.setattr(runtime,'discover',lambda *args:{1:{'pid':1,'role':'workspace-api'},2:{'pid':2,'role':'workspace-web'}})
    monkeypatch.setattr(runtime,'check_data_endpoints',lambda *args:None)
    monkeypatch.setattr(runtime,'search_health',lambda config:{'state':'running','health':'yellow'})
    state = runtime.status(config)
    assert state['ready'] is True
    assert state['elasticsearch'] == {'state':'running','health':'yellow','mode':'external'}
    monkeypatch.setattr(runtime,'search_health',lambda config:{'state':'authentication_failed','http_status':401})
    assert runtime.status(config)['ready'] is False


def test_health_supports_external_api_key_without_reading_password(config, monkeypatch):
    config.env['WGS_ELASTICSEARCH_API_KEY'] = 'synthetic-unused-test-key'
    config.env['WGS_ELASTICSEARCH_PASSWORD_FILE'] = '/missing/file'
    def request(req, **kwargs):
        assert req.get_header('Authorization') == 'ApiKey synthetic-unused-test-key'
        return io.BytesIO(b'{"status":"yellow"}')
    monkeypatch.setattr(runtime.urllib.request,'urlopen',request)
    assert runtime.search_health(config)['state'] == 'running'


@pytest.mark.parametrize("outside_project", [False, True])
@pytest.mark.parametrize("extra_args", [[], ["--json"], ["--component", "all"], ["--component=elasticsearch"]])
def test_report_restart_keeps_api_scope_from_any_directory(tmp_path, outside_project, extra_args):
    root = tmp_path / "project"
    shutil.copytree(runtime.ROOT / "deploy", root / "deploy")
    interpreter = root / '.venv/bin/python'
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    interpreter.chmod(0o755)
    result = subprocess.run(
        ["bash", str(root / "deploy/restart-report-api.sh"), *extra_args],
        cwd=tmp_path if outside_project else root,
        capture_output=True, text=True, env={"PATH": os.environ["PATH"]},
    )
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        str(root / "deploy/lib/runtime.py"), "restart", *extra_args,
        "--component", "workspace-api",
    ]


def test_report_restart_reloads_configuration_and_does_not_broaden_scope(config, monkeypatch, capsys):
    env_path = config.root / ".env"
    original = env_path.read_text()
    env_path.write_text(original + "\nWGS_CLAIM_API_KNOWLEDGE_BASE_ID=30\n")
    original_load = runtime.Config.load
    loaded = []
    events = []

    def load():
        value = original_load(config.root, parent_env={"PATH": os.environ["PATH"]})
        loaded.append(value)
        return value

    def stop(value, component):
        events.append(("stop", component, value.env["WGS_CLAIM_API_KNOWLEDGE_BASE_ID"]))
        env_path.write_text(original + "\nWGS_CLAIM_API_KNOWLEDGE_BASE_ID=31\n")

    def start(value, component, force_build):
        events.append(("start", component, value.env["WGS_CLAIM_API_KNOWLEDGE_BASE_ID"]))
        assert force_build is False
        return {"services": {"workspace-api": 123}}

    monkeypatch.setattr(runtime.Config, "load", load)
    monkeypatch.setattr(runtime, "deployment_lock", lambda value: contextlib.nullcontext())
    monkeypatch.setattr(runtime, "external_search_preflight", lambda value: None)
    monkeypatch.setattr(runtime, "stop", stop)
    monkeypatch.setattr(runtime, "start", start)
    assert runtime.main(["restart", "--component", "all", "--component", "workspace-api"]) == 0
    assert len(loaded) == 2 and loaded[0] is not loaded[1]
    assert events == [("stop", "workspace-api", "30"), ("start", "workspace-api", "31")]
    assert json.loads(capsys.readouterr().out)["component"] == "workspace-api"
