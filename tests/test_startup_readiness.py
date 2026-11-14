"""Initialization and delayed readiness use temporary data and simulated clocks only."""
import importlib.util
import sqlite3
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from test_project_runtime import config, runtime


@pytest.fixture
def clock(monkeypatch):
    state = {'now':0.0,'sleeps':[]}
    monkeypatch.setattr(runtime.time,'monotonic',lambda:state['now'])
    def sleep(seconds):
        state['sleeps'].append(seconds)
        state['now'] += seconds
    monkeypatch.setattr(runtime.time,'sleep',sleep)
    return state


@pytest.mark.parametrize('role',['workspace-api','workspace-web'])
def test_wait_retries_delayed_config_and_data_endpoints_until_all_ready(config, monkeypatch, clock, role):
    config.env['WGS_CLAIM_API_KNOWLEDGE_BASE_ID'] = '30'
    calls = {'config':0,'samples':0,'reports':0,'root':0}
    def endpoint(url):
        if url.endswith('/api/knowledge-base/config'):
            calls['config'] += 1
            if calls['config'] == 1:
                raise ConnectionRefusedError('synthetic startup delay')
            return {'knowledge_base_id':30}
        if '/api/samples' in url:
            calls['samples'] += 1
            if calls['samples'] == 1:
                raise HTTPError(url,503,'synthetic startup delay',None,None)
            return {'samples':[]}
        calls['reports'] += 1
        if calls['reports'] == 1:
            raise HTTPError(url,500,'synthetic startup delay',None,None)
        return {'reports':[]}
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self,*args): pass
    def page(*args,**kwargs):
        calls['root'] += 1
        return Response()
    monkeypatch.setattr(runtime,'read_json',endpoint)
    monkeypatch.setattr(runtime.urllib.request,'urlopen',page)
    runtime.wait_ready(config,role,SimpleNamespace(poll=lambda:None),timeout=2)
    assert calls['config'] == 4 and calls['samples'] == 3 and calls['reports'] == 2
    assert len(clock['sleeps']) == 3
    assert calls['root'] == (1 if role == 'workspace-web' else 0)


def test_wait_times_out_if_data_never_ready(config, monkeypatch, clock):
    monkeypatch.setattr(runtime,'read_json',lambda url:{} if 'knowledge-base/config' in url else (_ for _ in ()).throw(ConnectionRefusedError()))
    config.env.pop('WGS_CLAIM_API_KNOWLEDGE_BASE_ID',None)
    with pytest.raises(runtime.RuntimeFailure,match='READINESS_TIMEOUT_WORKSPACE_API'):
        runtime.wait_ready(config,'workspace-api',SimpleNamespace(poll=lambda:None),timeout=1)
    assert clock['now'] >= 1 and len(clock['sleeps']) >= 5


def test_wrong_knowledge_base_and_exited_process_do_not_report_ready(config, monkeypatch, clock):
    config.env['WGS_CLAIM_API_KNOWLEDGE_BASE_ID'] = '30'
    monkeypatch.setattr(runtime,'read_json',lambda url:{'knowledge_base_id':25})
    with pytest.raises(runtime.RuntimeFailure,match='WRONG_KNOWLEDGE_BASE'):
        runtime.wait_ready(config,'workspace-api',SimpleNamespace(poll=lambda:None))
    with pytest.raises(runtime.RuntimeFailure,match='SERVICE_EXITED_WORKSPACE_API'):
        runtime.wait_ready(config,'workspace-api',SimpleNamespace(poll=lambda:1))
    assert not clock['sleeps']


def test_start_process_returns_success_only_after_readiness(config, monkeypatch, clock):
    polls = []
    process = SimpleNamespace(pid=12345,poll=lambda:None)
    monkeypatch.setattr(runtime.subprocess,'Popen',lambda *args,**kwargs:process)
    monkeypatch.setattr(runtime,'proc_record',lambda pid:{'pid':pid,'start':1,'pgid':pid,'uid':config.uid})
    def check(cfg,role):
        polls.append(role)
        if len(polls) < 3:
            raise runtime.RuntimeFailure('DATA_ENDPOINT_FAILED_WORKSPACE_API')
    monkeypatch.setattr(runtime,'read_json',lambda url:{})
    monkeypatch.setattr(runtime,'check_data_endpoints',check)
    config.env.pop('WGS_CLAIM_API_KNOWLEDGE_BASE_ID',None)
    assert runtime.start_process(config,'workspace-api','') == process.pid
    assert len(polls) == 3 and len(clock['sleeps']) == 2


@pytest.mark.parametrize('dangling',[True,False])
def test_initialize_preserves_legacy_resource_link_and_existing_records(tmp_path, monkeypatch, dangling):
    spec = importlib.util.spec_from_file_location('init_data_under_test',runtime.ROOT/'scripts/init_data.py')
    initializer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(initializer)
    root = tmp_path/'workspace'
    root.mkdir()
    target = tmp_path/'resource-databases'
    if not dangling:
        target.mkdir()
        (target/'preserve').write_text('synthetic resource sentinel')
    link = root/'databases'
    link.symlink_to(target,target_is_directory=True)
    link_inode = link.lstat().st_ino
    monkeypatch.setattr(initializer,'workspace_root',lambda:root)
    monkeypatch.setattr(initializer,'runtime_path',lambda key,*parts:root.joinpath(*parts))
    monkeypatch.setattr(initializer,'bioinformatics_root',lambda:root/'bioinformatics')
    monkeypatch.setattr(initializer,'knowledge_db_path',lambda:root/'knowledge/kb.db')
    monkeypatch.setenv('WGS_DATABASE_URL','postgresql://unused@127.0.0.1:1/unused')
    monkeypatch.setattr(initializer.os,'umask',lambda value:0o077)
    initializer.init_data()
    with sqlite3.connect(root/'knowledge/kb.db') as connection:
        connection.execute("INSERT INTO papers (pmid,title) VALUES ('1','synthetic existing record')")
    initializer.init_data()
    with sqlite3.connect(root/'knowledge/kb.db') as connection:
        assert connection.execute('SELECT COUNT(*) FROM papers').fetchone()[0] == 1
    assert link.is_symlink() and link.lstat().st_ino == link_inode
    assert target.exists() is (not dangling)
    if not dangling:
        assert (target/'preserve').read_text() == 'synthetic resource sentinel'
