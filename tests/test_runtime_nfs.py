"""Model root-squashed NFS without sudo, Docker, service stops or real credentials."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from test_process_identity import identity_state
from test_project_runtime import config, runtime
from test_managed_elasticsearch import DockerDouble, managed


@pytest.fixture
def nfs(config, identity_state, monkeypatch):
    app_uid = config.uid
    originals = {name: getattr(Path, name) for name in ('stat', 'open', 'read_text', 'unlink')}
    def guard(path):
        if path.is_relative_to(config.workspace) and identity_state['uid'] != app_uid:
            raise PermissionError(13, 'simulated root-squashed NFS')
    for name, original in originals.items():
        def operation(path, *args, _original=original, **kwargs):
            guard(path)
            return _original(path, *args, **kwargs)
        monkeypatch.setattr(Path, name, operation)
    monkeypatch.setattr(runtime, 'application_owned_filesystem', lambda path: True)
    monkeypatch.setattr(managed, 'application_owned_filesystem', lambda path: True)
    return config, identity_state


def test_root_squashed_lock_state_and_logs_use_app_but_body_keeps_root(nfs):
    config, state = nfs
    with runtime.deployment_lock(config):
        assert state['uid'] == 0
        runtime.atomic_json(config.workspace/'run/project-processes.json', {'services': {}}, config)
        log = runtime.log_path(config, 'test')
        runtime.cleanup_state(config, runtime.ROLES)
        assert state['uid'] == 0
        with runtime.application_user(config):
            assert log.is_file()
            assert not (config.workspace/'run/project-processes.json').exists()
    assert state['uid'] == 0


def test_privileged_subprocess_gets_app_opened_log_descriptor(nfs, monkeypatch):
    config, state = nfs
    def run(args, **kwargs):
        assert state['uid'] == 0
        kwargs['stdout'].write(b'safe diagnostic\n')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runtime.subprocess, 'run', run)
    runtime.run_checked(config, ['docker-status-double'], 'test', as_user=False)
    assert state['uid'] == 0


def test_build_cache_is_read_and_verified_as_app(nfs):
    config, state = nfs
    dist = config.web/'.next-project-test'
    dist.mkdir()
    (dist/'BUILD_ID').write_text('test')
    (dist/'routes-manifest.json').write_text(json.dumps({'rewrites': [
        {'source': '/backend/:path*', 'destination': f'http://127.0.0.1:{config.api_port}/:path*'}]}))
    source = runtime.source_fingerprint(config)
    runtime.atomic_json(config.workspace/'run/project-build.json', {'source': source, 'dist': dist.name}, config)
    assert runtime.ensure_build(config) == (dist.name, False)
    assert state['uid'] == 0


def test_search_handoff_never_chowns_or_recursively_adopts_nfs(nfs, monkeypatch):
    config, state = nfs
    config.managed_search = True
    with runtime.application_user(config):
        directory = config.workspace/'elasticsearch'
        directory.mkdir(parents=True)
        (directory/'client-password').write_text('synthetic-unused-value')
    monkeypatch.setattr(runtime, 'run_checked', lambda *a, **kw: None)
    def forbidden(*args, **kwargs):
        raise AssertionError('root must not chown or recursively adopt NFS')
    monkeypatch.setattr(runtime.os, 'chown', forbidden)
    monkeypatch.setattr(runtime, 'repair_project_ownership', forbidden)
    assert runtime.managed_search(config, 'start') == 'started'
    assert config.env['WGS_ELASTICSEARCH_PASSWORD_FILE'] == str(directory/'client-password')
    assert state['uid'] == 0


def test_managed_search_files_are_app_owned_and_docker_is_privileged(nfs, monkeypatch):
    config, state = nfs
    monkeypatch.setenv('WGS_WORKSPACE', str(config.workspace))
    monkeypatch.setenv('WGS_RUN_USER', config.user)
    manager = managed.ManagedElasticsearch()
    double = DockerDouble(manager)
    monkeypatch.setattr(managed.socket, 'socket', MagicMock())
    def run(args, **kwargs):
        assert state['uid'] == 0
        docker_args = args[3:]
        if '--env-file' in docker_args:
            env_file = Path(docker_args[docker_args.index('--env-file')+1])
            assert not env_file.is_relative_to(config.workspace)
            assert env_file.stat().st_mode & 0o777 == 0o600
        output = double(*docker_args)
        if output is None:
            return SimpleNamespace(returncode=1, stdout='', stderr='No such object')
        return SimpleNamespace(returncode=0, stdout=output or '', stderr='')
    def request(*args, **kwargs):
        assert state['uid'] == config.uid
        return {'cluster_name': manager.name, 'status': 'yellow', 'timed_out': False}
    monkeypatch.setattr(managed.subprocess, 'run', run)
    monkeypatch.setattr(manager, '_request', request)
    manager.start()
    manager.status()
    manager.stop()
    assert state['uid'] == 0
    with runtime.application_user(config):
        assert (manager.directory/'client-password').stat().st_mode & 0o777 == 0o600


def test_permission_failure_reports_safe_stage_and_errno(config, monkeypatch, capsys):
    monkeypatch.setattr(runtime.Config, 'load', lambda: config)
    monkeypatch.setattr(config, 'require_privilege', lambda component: None)
    def denied(*args):
        raise PermissionError(13, 'must never be printed', '/private/unreported/path')
    monkeypatch.setattr(runtime, 'deployment_lock', denied)
    assert runtime.main(['restart']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result == {'ok': False, 'error': 'RUNTIME_FILESYSTEM_PERMISSION_DENIED', 'stage': 'runtime_lock', 'errno': 13}


def test_app_subprocess_drops_real_and_saved_root_even_inside_file_scope(nfs, monkeypatch):
    config, state = nfs
    def run(args, **kwargs):
        assert state['uid'] == config.uid and state['real'] == 0
        assert kwargs['preexec_fn'] == config.drop_privilege
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runtime.subprocess, 'run', run)
    with runtime.application_user(config):
        runtime.run_checked(config, ['application-build-double'], 'test', as_user=True)
    assert state['uid'] == 0


def test_child_privilege_drop_is_permanent(config, identity_state, monkeypatch):
    state = identity_state
    state.update(uid=config.uid, gid=config.gid)
    def setuid(value):
        assert state['uid'] == 0
        state.update(uid=value, real=value, saved=value)
    monkeypatch.setattr(runtime.os, 'setuid', setuid)
    monkeypatch.setattr(runtime.os, 'setgid', lambda value: state.update(gid=value))
    config.drop_privilege()
    assert state['uid'] == state['real'] == state['saved'] == config.uid
