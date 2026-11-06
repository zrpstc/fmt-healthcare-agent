"""Project lifecycle guarantees, including legacy discovery and PID safety."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from unittest.mock import Mock
import pytest

spec = importlib.util.spec_from_file_location('project_runtime_under_test', Path(__file__).resolve().parents[1] / 'deploy/runtime.py')
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)

@pytest.fixture
def config(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    (root / '.env').write_text('WGS_WEB_PORT=18502\nWGS_API_PORT=18503\nWGS_ELASTICSEARCH_MANAGED=false\n')
    (root / 'apps/workspace-web').mkdir(parents=True)
    return runtime.Config.load(root, parent_env={'PATH': os.environ['PATH']})

def test_project_env_overrides_stale_launch_ports(config):
    (config.root / '.env').write_text('WGS_WEB_PORT=18502\nWGS_API_PORT=18503\nWGS_ELASTICSEARCH_MANAGED=true\n')
    loaded = runtime.Config.load(config.root, parent_env={'WGS_API_PORT': '8503', 'WGS_WEB_PORT': '8502'})
    assert (loaded.web_port, loaded.api_port) == (18502, 18503)
    assert loaded.managed_search
    assert loaded.env['WGS_ELASTICSEARCH_USERNAME'] == 'wgs-platform'
    assert loaded.env['WGS_ELASTICSEARCH_PASSWORD_FILE'] == str(loaded.workspace / 'elasticsearch/client-password')
    assert loaded.env['WGS_ELASTICSEARCH_API_KEY'] == ''

@pytest.mark.parametrize('text', ['WGS_WEB_PORT=18503\nWGS_API_PORT=18503', 'WGS_API_PORT=invalid', 'WGS_API_PORT=70000'])
def test_invalid_port_configuration_is_rejected(config, text):
    (config.root / '.env').write_text(text)
    with pytest.raises(runtime.RuntimeFailure):
        runtime.Config.load(config.root, parent_env={})

def test_privilege_failure_happens_before_any_shutdown(config, monkeypatch):
    config.managed_search = True
    monkeypatch.setattr(runtime.os, 'geteuid', lambda: 1030)
    signal_spy = Mock()
    monkeypatch.setattr(runtime, 'stop_processes', signal_spy)
    with pytest.raises(runtime.RuntimeFailure, match='ADMIN_REQUIRED'):
        runtime.stop(config)
    signal_spy.assert_not_called()

def test_dependency_preflight_happens_before_any_shutdown(config, monkeypatch):
    config.managed_search = True
    monkeypatch.setattr(config, 'require_privilege', lambda component: None)
    events = []
    def dependency(config, action):
        events.append(action)
        raise runtime.RuntimeFailure('ELASTICSEARCH_STATUS_FAILED')
    monkeypatch.setattr(runtime, 'managed_search', dependency)
    shutdown = Mock()
    monkeypatch.setattr(runtime, 'stop_processes', shutdown)
    with pytest.raises(runtime.RuntimeFailure):
        runtime.stop(config)
    assert events == ['status']
    shutdown.assert_not_called()

def test_foreign_projects_and_arbitrary_node_commands_are_not_adopted(config):
    r = {'cwd': str(config.root), 'args': ['python', '-m', 'uvicorn', 'app.main:app', '--app-dir', '/another/project/apps/workspace-api']}
    assert runtime.classify(r, config.root) is None
    r = {'cwd': str(config.web), 'args': ['node', 'some-other-job.js']}
    assert runtime.classify(r, config.root) is None
    r = {'cwd': str(config.root), 'args': ['python', '-m', 'uvicorn', 'app.main:app', '--app-dir', 'apps/workspace-api']}
    assert runtime.classify(r, config.root) == 'workspace-api'

def test_pid_reuse_is_checked_before_signalling(monkeypatch):
    monkeypatch.setattr(runtime, 'proc_record', lambda pid: {'start': 999, 'state': 'S'})
    kill = Mock()
    monkeypatch.setattr(runtime.os, 'kill', kill)
    runtime.signal_records({1: {'pid': 1, 'start': 123}}, signal.SIGTERM)
    kill.assert_not_called()

def test_old_preview_without_pid_file_and_its_detached_child_are_stopped(config):
    pidfile = config.root / 'child.pid'
    child_code = 'import time;time.sleep(120)'
    code = 'import subprocess,sys,time,pathlib;p=subprocess.Popen([sys.executable,"-c",'+repr(child_code)+'],start_new_session=True);pathlib.Path('+repr(str(pidfile))+').write_text(str(p.pid));time.sleep(120)'
    parent = subprocess.Popen([sys.executable, '-c', code, 'uvicorn', 'app.main:app', '--app-dir', str(config.root / 'apps/workspace-api'), '--port', '18503'], cwd=config.root, start_new_session=True)
    outsider = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(120)'], start_new_session=True)
    child_pid = None
    try:
        for _ in range(100):
            if pidfile.exists():
                break
            time.sleep(0.02)
        child_pid = int(pidfile.read_text())
        discovered = runtime.discover(config.root, ('workspace-api',))
        assert parent.pid in discovered and child_pid in discovered
        (config.workspace / 'run').mkdir(parents=True)
        # A forged PID file must never result in signalling the unrelated process.
        (config.workspace / 'run/workspace-api.pid').write_text(str(outsider.pid))
        stopped = runtime.stop_processes(config, ('workspace-api',), timeout=2)
        assert stopped >= 2
        assert outsider.poll() is None
        assert not runtime.discover(config.root, ('workspace-api',))
        assert not (config.workspace / 'run/workspace-api.pid').exists()
    finally:
        for proc in [parent, outsider]:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        if child_pid:
            try:os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:pass

def test_pid_symlink_is_unlinked_without_following_it(config):
    directory = config.workspace / 'run'
    directory.mkdir(parents=True)
    target = config.root / 'unrelated-data'
    target.write_text('keep')
    (directory / 'workspace-api-preview.pid').symlink_to(target)
    runtime.cleanup_state(config, ('workspace-api',))
    assert target.read_text() == 'keep'
    assert not (directory / 'workspace-api-preview.pid').is_symlink()

def test_wrong_compiled_proxy_is_rejected(config):
    p = config.web / '.next-project-test'
    p.mkdir()
    (p / 'BUILD_ID').write_text('ready')
    manifest = p / 'routes-manifest.json'
    manifest.write_text(json.dumps({'rewrites': [{'source': '/backend/:path*', 'destination': 'http://127.0.0.1:8503/:path*'}]}))
    assert not runtime.verify_build(config, p.name)
    manifest.write_text(json.dumps({'rewrites': [{'source': '/backend/:path*', 'destination': 'http://127.0.0.1:18503/:path*'}]}))
    assert runtime.verify_build(config, p.name)

def test_build_rechecks_source_and_proxy_inputs_but_ignores_generated_type_paths(config):
    p = config.web / 'app'
    p.mkdir()
    (p / 'page.tsx').write_text('page one')
    ts = config.web / 'tsconfig.json'
    ts.write_text(json.dumps({'include': ['app/**/*.tsx', '.next-old/types/**/*.ts']}))
    before = runtime.source_fingerprint(config)
    ts.write_text(json.dumps({'include': ['app/**/*.tsx', '.next-new/types/**/*.ts']}))
    assert runtime.source_fingerprint(config) == before
    (p / 'page.tsx').write_text('page two')
    assert runtime.source_fingerprint(config) != before
    before = runtime.source_fingerprint(config)
    config.api_port = 19003
    assert runtime.source_fingerprint(config) != before

def test_all_components_use_dependency_then_application_order(config, monkeypatch):
    config.managed_search = True
    config.agent_enabled = True
    monkeypatch.setattr(config, 'require_privilege', lambda component: None)
    monkeypatch.setattr(runtime, 'discover', lambda *a: {})
    monkeypatch.setattr(runtime, 'ensure_build', lambda *a: ('.next-project-test', True))
    events = []
    monkeypatch.setattr(runtime, 'managed_search', lambda cfg, action: events.append('search:'+action))
    monkeypatch.setattr(runtime, 'run_checked', lambda cfg, args, label, **kw: events.append(label))
    monkeypatch.setattr(runtime, 'start_process', lambda cfg, role, dist: events.append(role) or 123)
    runtime.start(config)
    assert events == ['search:status', 'search:start', 'initialize', 'search-index', *runtime.ROLES]

def test_partial_startup_is_cleaned_up(config, monkeypatch):
    monkeypatch.setattr(runtime, 'discover', lambda *a: {})
    monkeypatch.setattr(runtime, 'ensure_build', lambda *a: ('.next-project-test', False))
    monkeypatch.setattr(runtime, 'run_checked', lambda *a, **kw: None)
    monkeypatch.setattr(runtime, 'managed_search', lambda *a: 'external')
    def fail(cfg, role, dist):
        if role == 'workspace-web':
            raise runtime.RuntimeFailure('WEB_START_FAILED')
        return 123
    monkeypatch.setattr(runtime, 'start_process', fail)
    cleanup = Mock()
    monkeypatch.setattr(runtime, 'stop_processes', cleanup)
    with pytest.raises(runtime.RuntimeFailure):
        runtime.start(config)
    cleanup.assert_called_once_with(config, runtime.ROLES)

def test_shell_entrypoints_are_valid():
    directory = Path(__file__).resolve().parents[1] / 'deploy'
    for name in ['project.sh', 'start.sh', 'stop.sh', 'restart.sh', 'reload.sh', 'status.sh', 'restart-report-api.sh', 'restart-web.sh', 'restart-agent.sh', 'restart-elasticsearch.sh']:
        assert subprocess.run(['bash', '-n', str(directory / name)], capture_output=True).returncode == 0

@pytest.mark.parametrize('health,expected', [('green','running'),('yellow','running'),('red','unhealthy')])
def test_normal_account_can_read_search_status_without_docker(config, monkeypatch, health, expected):
    import io
    config.env['WGS_ELASTICSEARCH_URL'] = 'http://127.0.0.1:9200'
    directory = config.workspace / 'elasticsearch'
    directory.mkdir(parents=True)
    (directory / 'client-password').write_text('unused-test-value')
    monkeypatch.setattr(runtime.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(json.dumps({'status':health}).encode()))
    assert runtime.search_health(config) == {'state':expected,'health':health}

def test_legacy_sample_data_permissions_are_adopted_without_changing_data(config, monkeypatch):
    directory = config.workspace / 'sample-registry' / 'records'
    directory.mkdir(parents=True)
    record = directory / 'sample.json'
    original = b'{"sample_id":"existing-sample","name":"preserve"}'
    record.write_bytes(original)
    record.chmod(0o400)
    directory.chmod(0o500)
    monkeypatch.setattr(runtime.os, 'geteuid', lambda: 0)
    result = runtime.prepare_application_data(config)
    assert result['updated_files'] == 1
    assert record.read_bytes() == original
    assert record.stat().st_mode & 0o600 == 0o600
    assert directory.stat().st_mode & 0o700 == 0o700
    assert runtime.prepare_application_data(config)['updated_files'] == 0

def test_permission_migration_does_not_touch_search_admin_credentials_or_symlink_targets(config, monkeypatch):
    directory = config.workspace / 'sample-registry'
    directory.mkdir(parents=True)
    external = config.root / 'outside-data'
    external.write_text('preserve')
    external.chmod(0o400)
    (directory / 'link').symlink_to(external)
    search = config.workspace / 'elasticsearch'
    search.mkdir()
    admin = search / 'admin-password'
    admin.write_text('unused-test-value')
    admin.chmod(0o400)
    monkeypatch.setattr(runtime.os, 'geteuid', lambda: 0)
    result = runtime.prepare_application_data(config)
    assert result['skipped_symlinks'] == 1
    assert external.stat().st_mode & 0o777 == 0o400
    assert admin.stat().st_mode & 0o777 == 0o400

def test_data_endpoints_must_work_before_service_is_ready(config, monkeypatch):
    from urllib.error import HTTPError
    config.env['WGS_CLAIM_API_KNOWLEDGE_BASE_ID'] = '30'
    proc = Mock()
    proc.poll.return_value = None
    def endpoint(url):
        if 'knowledge-base/config' in url:
            return {'knowledge_base_id': 30}
        raise HTTPError(url, 500, 'test failure', {}, None)
    monkeypatch.setattr(runtime, 'read_json', endpoint)
    with pytest.raises(runtime.RuntimeFailure, match='DATA_ENDPOINT_FAILED_WORKSPACE_API'):
        runtime.wait_ready(config, 'workspace-api', proc, timeout=1)

def test_empty_but_valid_sample_and_report_lists_are_healthy(config, monkeypatch):
    monkeypatch.setattr(runtime, 'read_json', lambda url: {'samples': []} if '/samples' in url else {'reports': []})
    runtime.check_data_endpoints(config, 'workspace-api')
    runtime.check_data_endpoints(config, 'workspace-web')

def test_running_process_does_not_hide_broken_sample_and_report_interfaces(config, monkeypatch):
    monkeypatch.setattr(runtime, 'discover', lambda *a: {123: {'pid': 123, 'role': 'workspace-api'}})
    def fail(*args):
        raise runtime.RuntimeFailure('DATA_ENDPOINT_FAILED_WORKSPACE_API')
    monkeypatch.setattr(runtime, 'check_data_endpoints', fail)
    result = runtime.status(config)
    assert result['workspace-api']['state'] == 'degraded'
    assert result['workspace-api']['data_ready'] is False

def test_whole_project_ownership_preserves_content_private_modes_and_executable_bits(config, monkeypatch):
    binary = config.root / '.venv/bin/tool'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'#!/bin/sh\nexit 0\n')
    binary.chmod(0o555)
    profile = config.workspace / 'bioinformatics/profiles/metaphlan/profile.tsv'
    profile.parent.mkdir(parents=True)
    profile.write_bytes(b'taxon\tabundance\nexample\t1\n')
    profile.chmod(0o400)
    private = config.root / '.env'
    private.chmod(0o400)
    before = {p: p.read_bytes() for p in [binary, profile, private]}
    monkeypatch.setattr(runtime.os, 'geteuid', lambda: 0)
    runtime.repair_project_ownership(config)
    assert all(p.read_bytes() == data for p, data in before.items())
    assert binary.stat().st_mode & 0o777 == 0o755
    assert profile.stat().st_mode & 0o777 == 0o600
    assert private.stat().st_mode & 0o777 == 0o600
    assert runtime.repair_project_ownership(config)['ownership_updates'] == 0

def test_whole_project_repair_does_not_follow_external_symlinks(config, monkeypatch):
    target = config.root.parent / 'outside-file'
    target.write_text('outside')
    target.chmod(0o400)
    (config.root / 'external-link').symlink_to(target)
    monkeypatch.setattr(runtime.os, 'geteuid', lambda: 0)
    result = runtime.repair_project_ownership(config)
    assert result['symlinks_checked'] == 1
    assert target.stat().st_mode & 0o777 == 0o400

def test_external_hardlink_is_privatized_instead_of_changing_outside_permissions(config, monkeypatch):
    target = config.root.parent / 'shared-file'
    target.write_bytes(b'keep shared contents')
    target.chmod(0o444)
    inside = config.root / 'shared-link'
    os.link(target, inside)
    monkeypatch.setattr(runtime.os, 'geteuid', lambda: 0)
    result = runtime.repair_project_ownership(config)
    assert result['external_hardlinks_isolated'] == 1
    assert inside.read_bytes() == target.read_bytes()
    assert inside.stat().st_ino != target.stat().st_ino
    assert inside.stat().st_mode & 0o777 == 0o644
    assert target.stat().st_mode & 0o777 == 0o444

def test_hardlinks_entirely_inside_project_remain_linked(config, monkeypatch):
    first = config.root / 'first-file'
    second = config.root / 'second-file'
    first.write_bytes(b'internal shared contents')
    first.chmod(0o444)
    os.link(first, second)
    monkeypatch.setattr(runtime.os, 'geteuid', lambda: 0)
    result = runtime.repair_project_ownership(config)
    assert result['external_hardlinks_isolated'] == 0
    assert first.stat().st_ino == second.stat().st_ino
    assert first.stat().st_mode & 0o777 == 0o644
