"""deploy/restart-elasticsearch.sh: restart only the Elasticsearch the project uses."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy/lib'))
spec = importlib.util.spec_from_file_location('restart_elasticsearch_under_test', ROOT / 'deploy/lib/restart_elasticsearch.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


@pytest.fixture
def config(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    (root / '.env').write_text('WGS_ELASTICSEARCH_MANAGED=false\nWGS_ELASTICSEARCH_URL=http://127.0.0.1:9200\n')
    (root / 'apps/workspace-web').mkdir(parents=True)
    return helper.runtime.Config.load(root, parent_env={'PATH': os.environ['PATH']})


def fake_docker(containers):
    """containers: name -> (host port, running)."""
    calls = []
    def docker(*arguments, timeout=60):
        calls.append(arguments)
        if arguments[:2] == ('container', 'ls'):
            return '\n'.join(containers) + '\n'
        if arguments[:2] == ('container', 'inspect'):
            missing = [n for n in arguments[2:] if n not in containers]
            if missing:
                raise helper.RuntimeFailure('ELASTICSEARCH_DOCKER_FAILED')
            return json.dumps([{'Name': '/' + n, 'State': {'Running': containers[n][1]},
                                'HostConfig': {'PortBindings': {'9200/tcp': [{'HostIp': '127.0.0.1', 'HostPort': containers[n][0]}]}}}
                               for n in arguments[2:]])
        return ''
    return docker, calls


def actions(calls):
    return [c[:2] for c in calls if c[1] in {'restart', 'start'}]


def test_finds_container_by_configured_port_and_waits_until_healthy(config, monkeypatch):
    docker, calls = fake_docker({'other-db': ('5432', True), 'wgs-elasticsearch-old': ('9200', True)})
    states = iter([{'state': 'unhealthy', 'health': 'red'}, {'state': 'running', 'health': 'yellow'}])
    monkeypatch.setattr(helper.time, 'sleep', lambda s: None)
    result = helper.restart(config, timeout=60, docker=docker, health=lambda c: next(states))
    assert result == {'container': 'wgs-elasticsearch-old', 'action': 'restarted',
                      'elasticsearch': {'state': 'running', 'health': 'yellow'}}
    assert ('container', 'restart', '--time', '30', 'wgs-elasticsearch-old') in calls


def test_stopped_container_is_started(config):
    docker, calls = fake_docker({'es': ('9200', False)})
    result = helper.restart(config, timeout=1, docker=docker, health=lambda c: {'state': 'running', 'health': 'green'})
    assert result['action'] == 'started'
    assert actions(calls) == [('container', 'start')]


def test_still_unhealthy_is_reported_not_hidden(config, monkeypatch):
    docker, _ = fake_docker({'es': ('9200', True)})
    monkeypatch.setattr(helper.time, 'monotonic', iter([0, 0, 999]).__next__)
    monkeypatch.setattr(helper.time, 'sleep', lambda s: None)
    result = helper.restart(config, timeout=5, docker=docker, health=lambda c: {'state': 'unhealthy', 'health': 'red'})
    assert result['error'] == 'ELASTICSEARCH_UNHEALTHY_AFTER_RESTART'
    assert result['elasticsearch']['health'] == 'red'


@pytest.mark.parametrize('containers, name, error', [
    ({'es': ('9201', True)}, None, 'ELASTICSEARCH_CONTAINER_NOT_FOUND'),
    ({'a': ('9200', True), 'b': ('9200', False)}, None, 'ELASTICSEARCH_CONTAINER_AMBIGUOUS'),
    ({'es': ('9201', True)}, 'es', 'ELASTICSEARCH_CONTAINER_PORT_MISMATCH'),
    ({'es': ('9200', True)}, 'typo', 'ELASTICSEARCH_CONTAINER_NOT_FOUND'),
])
def test_never_restarts_a_container_that_does_not_serve_the_configured_port(config, containers, name, error):
    docker, calls = fake_docker(containers)
    with pytest.raises(helper.RuntimeFailure, match=error):
        helper.restart(config, container=name, timeout=1, docker=docker, health=lambda c: pytest.fail('no wait'))
    assert actions(calls) == []


def test_remote_elasticsearch_is_refused(config):
    config.env['WGS_ELASTICSEARCH_URL'] = 'http://search.example.org:9200'
    with pytest.raises(helper.RuntimeFailure, match='ELASTICSEARCH_NOT_ON_THIS_HOST'):
        helper.restart(config, timeout=1, docker=lambda *a, **k: pytest.fail('no docker'))


def test_inaccessible_docker_socket_asks_for_sudo(config, monkeypatch, capsys):
    monkeypatch.setattr(helper.runtime.Config, 'load', lambda: config)
    config.env['WGS_ELASTICSEARCH_DOCKER_SOCKET'] = str(config.root / 'missing.sock')
    monkeypatch.setattr(helper.os, 'geteuid', lambda: 1000)
    assert helper.main([]) == 77
    assert json.loads(capsys.readouterr().out)['error'] == 'ADMIN_REQUIRED'


def test_managed_mode_uses_project_lifecycle(config, monkeypatch):
    config.managed_search = True
    monkeypatch.setattr(helper.runtime.Config, 'load', lambda: config)
    seen = []
    monkeypatch.setattr(helper.runtime, 'main', lambda argv: seen.append(argv) or 0)
    assert helper.main([]) == 0
    assert seen == [['restart', '--component', 'elasticsearch']]


@pytest.mark.parametrize('outside_project', [False, True])
def test_wrapper_routes_to_helper_from_any_directory(tmp_path, outside_project):
    root = tmp_path / 'checkout with spaces'
    shutil.copytree(ROOT / 'deploy', root / 'deploy')
    interpreter = root / '.venv/bin/python'
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n')
    interpreter.chmod(0o700)
    result = subprocess.run(['bash', str(root / 'deploy/restart-elasticsearch.sh'), '--container', 'es'],
                            cwd=tmp_path if outside_project else root, capture_output=True, text=True,
                            env={'PATH': os.environ['PATH']})
    assert result.returncode == 0
    assert result.stdout.splitlines() == [str(root / 'deploy/lib/restart_elasticsearch.py'), '--container', 'es']
