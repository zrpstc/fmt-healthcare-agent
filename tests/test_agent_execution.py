import json
from types import SimpleNamespace as NS

from app.agent_execution import run_agent_turn
from app.agent_prompts import MAIN_AGENT_ID, EVIDENCE_AGENT_ID, normalize_agents


class FakeClient:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        content, reason = item if isinstance(item, tuple) else (item, 'stop')
        return NS(choices=[NS(message=NS(content=content, tool_calls=None), finish_reason=reason)])


def call(name, **params):
    return '<tool_call>' + json.dumps({'name': name, 'arguments': params}) + '</tool_call>'


def run(client, **kwargs):
    return run_agent_turn(model='Qwen3.6-35B-A3B-FP8', history=[], prompt='测试问题', audit_enabled=False, _client=client, **kwargs)


def test_xml_tool_executes_then_final_answer(monkeypatch):
    seen = []
    monkeypatch.setattr('app.agent_chat._invoke_tool', lambda name, params, *a, **kw: seen.append((name, params)) or '{"state":"complete"}')
    client = FakeClient('hidden</think>' + call('get_sample_status', sample_id='test2'), '样本 test2 已完成分析。')
    result = run(client, allowed_tools=['get_sample_status'])
    assert seen == [('get_sample_status', {'sample_id': 'test2'})]
    assert result['answer'] == '样本 test2 已完成分析。'
    assert result['tool_call_count'] == 1
    assert client.requests[1]['messages'][-1]['role'] == 'tool'
    assert client.requests[0]['extra_body']['chat_template_kwargs']['enable_thinking'] is False


def test_real_subagent_runs_readonly_and_returns_to_primary(monkeypatch):
    seen = []
    monkeypatch.setattr('app.agent_chat._invoke_tool', lambda name, params, *a, **kw: seen.append(name) or '{"pmid":"123","finding":"association"}')
    client = FakeClient(call('delegate_evidence_review', task='核验维生素相关通路'), call('search_pubmed', query='microbiome vitamin'), '证据为观察性关联，PMID 123。', '综合样本与证据：不能确诊营养缺乏。')
    result = run(client, allowed_tools=[], subagent_config={'enabled': True})
    assert seen == ['search_pubmed']
    assert result['agent_id'] == MAIN_AGENT_ID
    assert result['tool_call_count'] == 2
    child_tools = {t['function']['name'] for t in client.requests[1]['tools']}
    assert child_tools == {'search_pubmed', 'search_knowledge_base'}
    assert any(t['agent_id'] == EVIDENCE_AGENT_ID for t in result['trace'])
    assert result['answer'].startswith('综合样本')


def test_shared_budget_stops_child_and_allows_final_synthesis():
    client = FakeClient(call('delegate_evidence_review', task='核验证据'), '子任务因预算不足，尚无证据。', '证据不足，需后续检索。')
    result = run(client, max_tool_calls=1, subagent_config={'enabled': True})
    assert result['tool_call_count'] == 1
    assert result['completion_status'] == 'partial'
    assert len(client.requests) == 3
    assert 'tools' not in client.requests[1]
    assert 'tools' not in client.requests[2]


def test_length_finish_reason_continues_instead_of_silent_success():
    client = FakeClient(('第一部分', 'length'), '余下结论')
    result = run(client, allowed_tools=[])
    assert result['answer'] == '第一部分\n\n余下结论'
    assert any(t['type'] == 'continuation' for t in result['trace'])


def test_truncated_tool_call_is_repaired_before_execution(monkeypatch):
    seen = []
    monkeypatch.setattr('app.agent_chat._invoke_tool', lambda name, params, *a, **kw: seen.append(name) or '{}')
    client = FakeClient((call('list_samples', limit=1), 'length'), call('list_samples', limit=1), '已查询样本。')
    result = run(client, allowed_tools=['list_samples'])
    assert seen == ['list_samples']
    assert result['completion_status'] == 'completed'


def test_failures_keep_successful_observations(monkeypatch):
    monkeypatch.setattr('app.agent_chat._invoke_tool', lambda *a, **kw: '{"sample_id":"test2","state":"complete"}')
    result = run(FakeClient(call('get_sample_status', sample_id='test2'), TimeoutError('model timed out')), allowed_tools=['get_sample_status'])
    assert result['completion_status'] == 'partial'
    assert 'test2' in result['answer'] and '未能完成' in result['answer']


def test_malformed_response_retries_without_showing_protocol():
    result = run(FakeClient('<tool_call>incomplete', '有效回答'), allowed_tools=[])
    assert result['answer'] == '有效回答'
    assert result['tool_call_count'] == 0


def test_catalog_has_one_primary_and_preserves_legacy_settings():
    rows = normalize_agents([{'id': MAIN_AGENT_ID, 'model': 'custom', 'enabled': False}, {'id': EVIDENCE_AGENT_ID, 'model': 'child'}])
    assert [row['id'] for row in rows if row['kind'] == 'agent'] == [MAIN_AGENT_ID]
    assert rows[0]['enabled'] is True
    assert rows[0]['model'] == 'custom'
    assert rows[1]['parent_agent_id'] == MAIN_AGENT_ID


def test_subagent_cannot_claim_evidence_without_retrieval(monkeypatch):
    monkeypatch.setattr('app.agent_chat._invoke_tool', lambda *a, **kw: '{"pmid":"123"}')
    client = FakeClient('未检索就给出的结论', call('search_pubmed', query='vitamin'), '检索证据 PMID 123。')
    result = run(client, agent_id=EVIDENCE_AGENT_ID, allowed_tools=['search_pubmed'])
    assert result['tool_call_count'] == 1
    assert len(client.requests) == 3
    assert any(row['type'] == 'protocol_recovery' for row in result['trace'])


def test_child_tool_quota_reserves_parent_budget(monkeypatch):
    seen = []
    monkeypatch.setattr('app.agent_chat._invoke_tool', lambda *a, **kw: seen.append(a[0]) or '{}')
    client = FakeClient(
        call('search_pubmed', query='one'), call('search_pubmed', query='two'),
        call('search_pubmed', query='three'), call('search_pubmed', query='four'), '已有证据及缺口。',
    )
    result = run(client, agent_id=EVIDENCE_AGENT_ID, allowed_tools=['search_pubmed'])
    assert len(seen) == 4
    assert result['completion_status'] == 'partial'
    assert 'tools' not in client.requests[-1]
