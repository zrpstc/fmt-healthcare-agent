import copy
import json

import httpx
import pytest

from wgs_fmt_platform.knowledge.litkg_retrieval import (
    LitkgRetrievalConfig, LitkgRetrievalError, evidence_references,
    pack_evidence, render_evidence, retrieve_litkg,
)
from wgs_agent.tools import knowledge_tools


def payload(fact_id=5001):
    return {
        'knowledge_base_id': 26, 'status': 'evidence_only', 'retrieval': 'text',
        'answer': 'NEVER USE THIS UPSTREAM ANSWER',
        'warnings': ['Semantic retrieval unavailable; used text retrieval'],
        'facts': [{'id': fact_id, 'predicate': 'ASSOCIATED_WITH',
                   'participants': [{'role':'subject', 'name':'F. prausnitzii', 'type':'MicrobialTaxon'},
                                    {'role':'object', 'name':'inflammation', 'type':'Process'},
                                    {'role':'cohort', 'name':'mouse model', 'type':'Cohort'}],
                   'negated': True, 'speculative': True, 'qualifiers': {'population':'mice'}}],
        'citations': [{'id':f'{fact_id}:0', 'fact_id':fact_id, 'claim_id':6001,
                       'document_id':137, 'chunk_id':5, 'filename':'paper.pdf', 'doi':'10.1234/example',
                       'page':7, 'page_end':8, 'sentence':'No causal link was established in mice.',
                       'context':'Long source context.', 'negated':True, 'speculative':True}],
    }


@pytest.mark.asyncio
async def test_agent_uses_ask_not_first_thousand_claims_and_never_generates():
    def handler(request):
        assert request.method == 'POST'
        assert request.url.path == '/knowledge-bases/26/ask'
        assert request.headers['Authorization'] == 'Bearer test-token'
        assert json.loads(request.content) == {
            'question':'butyrate inflammation', 'limit':12, 'hops':1, 'generate':False,
        }
        return httpx.Response(200, json=payload())
    config = LitkgRetrievalConfig('http://litkg.test', 26, token='test-token')
    result = await retrieve_litkg('butyrate inflammation', config=config, transport=httpx.MockTransport(handler))
    assert result['facts'][0]['id'] == 5001
    assert result['facts'][0]['negated'] is True
    assert len(result['facts'][0]['participants']) == 3
    assert result['facts'][0]['citation_ids'] == ['5001:0']
    assert result['citations'][0]['page'] == 7
    assert result['citations'][0]['page_end'] == 8
    assert result['retrieval'] == 'text'
    assert result['warnings'] == payload()['warnings']
    assert 'answer' not in result and 'test-token' not in render_evidence(result)


@pytest.mark.parametrize('mutation', ['foreign_kb', 'bad_shape', 'bad_citation'])
@pytest.mark.asyncio
async def test_invalid_contract_is_rejected(mutation):
    data = payload()
    if mutation == 'foreign_kb':
        data['knowledge_base_id'] = 25
    elif mutation == 'bad_shape':
        data['facts'] = 'invalid'
    else:
        data['citations'][0].pop('sentence')
    with pytest.raises(LitkgRetrievalError):
        await retrieve_litkg('butyrate', config=LitkgRetrievalConfig('http://litkg.test',26),
                             transport=httpx.MockTransport(lambda r: httpx.Response(200,json=data)))


@pytest.mark.asyncio
async def test_unsupported_ask_does_not_silently_scan_claims():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(404)
    with pytest.raises(LitkgRetrievalError, match='HTTP 404'):
        await retrieve_litkg('butyrate', config=LitkgRetrievalConfig('http://litkg.test',26),
                             transport=httpx.MockTransport(handler))
    assert paths == ['/knowledge-bases/26/ask']


def test_context_budget_keeps_complete_citations_and_warns_about_omissions():
    data = payload()
    for number in range(5002,5020):
        row = payload(number)
        row['citations'][0]['context'] = 'context' * 2000
        row['citations'][0]['sentence'] = 'Original evidence sentence. ' * 25
        data['facts'].extend(row['facts'])
        data['citations'].extend(row['citations'])
    before = copy.deepcopy(data)
    result = pack_evidence(data,'butyrate',12,LitkgRetrievalConfig('http://litkg.test',26))
    text = render_evidence(result)
    envelope = json.dumps({'is_error':False,'content':text},ensure_ascii=False)
    assert len(envelope) <= 17000
    assert result['omitted_fact_count'] > 0
    parsed = json.loads(text.split('---JSON---\n')[1])
    ids = {str(f['id']) for f in parsed['facts']}
    assert all(str(c['fact_id']) in ids for c in parsed['citations'])
    assert all(f['citation_ids'] for f in parsed['facts'])
    assert all(c['sentence'] == next(r['sentence'] for r in before['citations'] if r['id']==c['id']) for c in parsed['citations'])
    assert any(c.get('context_omitted') for c in parsed['citations'])
    assert data == before


def test_legacy_references_keep_claim_fact_and_original_page():
    refs = evidence_references(pack_evidence(payload(),'butyrate',5,LitkgRetrievalConfig('http://litkg.test',26)))
    assert refs[0]['claim_id'] == 'litkg:claim:6001'
    assert refs[0]['citation_id'] == '5001:0'
    assert refs[0]['fact_id'] == 5001
    assert refs[0]['page'] == 7
    assert refs[0]['evidence_text'] == payload()['citations'][0]['sentence']


@pytest.mark.asyncio
async def test_no_hit_stays_litkg_no_silent_local_fallback(monkeypatch):
    async def retrieve(*args):
        return {'source':{'kind':'litkg-ask'},'status':'insufficient_evidence','facts':[],'citations':[],'warnings':[]}
    monkeypatch.setattr(knowledge_tools,'retrieve_litkg',retrieve)
    monkeypatch.setattr(knowledge_tools,'_sql_search',lambda *a: pytest.fail('local fallback must not run'))
    result = await knowledge_tools.KnowledgeSearchTool().invoke({'query':'不存在的术语'})
    assert result.is_error is False
    assert 'insufficient_evidence' in result.content
    assert 'litkg-ask' in result.content


@pytest.mark.asyncio
async def test_unavailable_default_is_error_and_explicit_local_fallback_is_labelled(monkeypatch):
    async def failed(*args):
        raise LitkgRetrievalError('LitKG /ask 返回 HTTP 503')
    monkeypatch.setattr(knowledge_tools,'retrieve_litkg',failed)
    monkeypatch.setenv('WGS_CLAIM_API_LOCAL_FALLBACK','false')
    result = await knowledge_tools.KnowledgeSearchTool().invoke({'query':'butyrate'})
    assert result.is_error is True
    assert json.loads(result.content)['status'] == 'unavailable'
    monkeypatch.setenv('WGS_CLAIM_API_LOCAL_FALLBACK','true')
    monkeypatch.setattr(knowledge_tools,'_grep_search',lambda *a: [])
    monkeypatch.setattr(knowledge_tools.os.path,'isfile',lambda *a: False)
    result = await knowledge_tools.KnowledgeSearchTool().invoke({'query':'butyrate'})
    data = json.loads(result.content)
    assert data['source'] == {'kind':'local-fallback','primary':False}
    assert data['status'] == 'degraded'
