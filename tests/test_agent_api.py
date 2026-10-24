"""API regressions run in a separate database/runtime, never production data."""
import os
from pathlib import Path
import subprocess
import sys


def test_single_entrypoint_and_legacy_conversations(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.update(WGS_WORKSPACE=str(tmp_path), WGS_AGENT_CONFIG_DIR=str(tmp_path / 'agent-config'),
               WGS_DATABASE_URL=f'sqlite:///{tmp_path / "db.sqlite"}',
               WGS_CONVERSATION_DB_FILE=str(tmp_path / 'db.sqlite'),
               PYTHONPATH=os.pathsep.join([str(root / 'apps/workspace-api'), str(root / 'src')]))
    source = '''
from fastapi.testclient import TestClient
from app import main

seen = []
def run(**kwargs):
    seen.append(kwargs)
    return dict(answer='完整结果', trace=[], pending_actions=[], canvas_items=[],
                model=kwargs['model'], run_id='test-run', tool_call_count=0, completion_status='completed')
main.run_agent_turn = run
main.list_models = lambda: ['test-model']
with TestClient(main.app) as client:
    agents = client.get('/api/agents').json()
    assert [row['id'] for row in agents] == ['fmt-researcher']
    all_agents = client.get('/api/agents?include_subagents=true').json()
    evidence = next(row for row in all_agents if row['id'] == 'evidence-curator')
    assert evidence['kind'] == 'subagent'
    assert client.delete('/api/agents/fmt-researcher').status_code == 422
    assert client.post('/api/agents', json={'id':'second-primary', 'name':'Other', 'kind':'agent'}).status_code == 422
    assert client.put('/api/agents/fmt-researcher', json={**agents[0], 'enabled':False}).status_code == 422
    response = client.post('/api/chat', json={'agent_id':'evidence-curator','message':'继续历史会话'})
    assert response.status_code == 200, response.text
    assert response.json()['answer'] == '完整结果'
    assert seen[0]['subagent_config']['allowed_tools'] == ['litkg_graph_rag','search_knowledge_base','search_pubmed']
    assert '唯一面向用户' in seen[0]['system_prompt']
    assert client.post('/api/chat', json={'agent_id':'unknown-subagent','message':'x'}).status_code == 422
    stored = client.get('/api/backend/conversations/' + response.json()['conversation_id']).json()
    assert stored['agent_id'] == 'fmt-researcher'
'''
    result = subprocess.run([sys.executable, '-c', source], env=env, cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
