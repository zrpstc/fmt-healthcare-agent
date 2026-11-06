import copy
import json
import httpx
import pytest
from wgs_fmt_platform.knowledge.litkg_acquisition import acquire_knowledge_base, KnowledgeAcquisitionError
from wgs_fmt_platform.knowledge.litkg_retrieval import LitkgRetrievalConfig
from wgs_fmt_platform.knowledge.knowledge_settings import refresh_knowledge_settings, eligible_for_use

def fixture_handler(*, broken=False, foreign=False):
    calls = []
    rows = {
        'entities': [{'id': i, 'canonical_name': str(i)} for i in range(1, 7)],
        'relations': [{'id': i, 'predicate': 'ANY_NEW_PREDICATE', 'review_status': 'pending'} for i in range(1, 8)],
        'claims': [{'id': i, 'semantic_status': 'pending'} for i in range(1, 6)],
        'facts': [{'id': i, 'predicate': 'UNLISTED_RELATION', 'participants': []} for i in range(1, 6)]}
    def handler(request):
        calls.append(request)
        path = request.url.path
        if path == '/knowledge-bases/30':
            return httpx.Response(200, json={'knowledge_base': {'id': 31 if foreign else 30}})
        kind = path.split('/')[3]
        if path.endswith('/export'):
            return httpx.Response(200, json={kind: rows[kind], 'total': len(rows[kind]) + int(broken), 'exported_count': len(rows[kind])})
        if kind == 'relations':
            assert request.url.params['include_pending'] == 'true'
            assert request.url.params['include_negated'] == 'true'
            assert request.url.params['include_speculative'] == 'true'
        offset = int(request.url.params['offset'])
        # Simulate a server cap smaller than the requested page size.
        page = rows[kind][offset:offset+2]
        return httpx.Response(200, json={kind: page, **({'total': len(rows[kind])} if kind == 'relations' else {}), 'knowledge_base_id': 30})
    return handler, calls, rows

@pytest.mark.asyncio
async def test_acquisition_drains_every_page_and_preserves_all_statuses_and_predicates(tmp_path):
    handler, calls, rows = fixture_handler()
    path = tmp_path / 'snapshot.json'
    result = await acquire_knowledge_base(LitkgRetrievalConfig('http://kb', 30), transport=httpx.MockTransport(handler), cache_path=path)
    assert result['complete'] is True
    for key in rows:
        assert result[key] == rows[key]
    assert json.loads(path.read_text())['counts'] == {key: len(value) for key, value in rows.items()}
    assert any(r.url.params.get('offset') == '6' for r in calls)
    assert all(r.method == 'GET' for r in calls)
    before = copy.deepcopy(result)
    assert eligible_for_use(result['claims'][0]) is False
    assert result == before

@pytest.mark.asyncio
@pytest.mark.parametrize('problem', ['broken', 'foreign'])
async def test_partial_or_foreign_snapshot_is_never_published(tmp_path, problem):
    handler, _, _ = fixture_handler(**{problem: True})
    path = tmp_path / 'snapshot.json'
    with pytest.raises(KnowledgeAcquisitionError):
        await acquire_knowledge_base(LitkgRetrievalConfig('http://kb', 30), transport=httpx.MockTransport(handler), cache_path=path)
    assert not path.exists()

def test_project_env_refresh_overrides_old_parent_kb_without_overriding_authentication(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('WGS_CLAIM_API_KNOWLEDGE_BASE_ID=30\n')
    monkeypatch.setenv('WGS_CLAIM_API_KNOWLEDGE_BASE_ID', '25')
    monkeypatch.delenv('WGS_KNOWLEDGE_CONFIG_SOURCE', raising=False)
    refresh_knowledge_settings(env)
    import os
    assert os.environ['WGS_CLAIM_API_KNOWLEDGE_BASE_ID'] == '30'
    env.write_text('WGS_CLAIM_API_KNOWLEDGE_BASE_ID=31\n')
    refresh_knowledge_settings(env)
    assert os.environ['WGS_CLAIM_API_KNOWLEDGE_BASE_ID'] == '31'
    monkeypatch.setenv('WGS_KNOWLEDGE_CONFIG_SOURCE', 'environment')
    monkeypatch.setenv('WGS_CLAIM_API_KNOWLEDGE_BASE_ID', '25')
    refresh_knowledge_settings(env)
    assert os.environ['WGS_CLAIM_API_KNOWLEDGE_BASE_ID'] == '25'

@pytest.mark.asyncio
async def test_full_graph_acquisition_precedes_separate_output_limit(monkeypatch):
    from wgs_fmt_platform.knowledge import litkg_acquisition
    from wgs_fmt_platform.knowledge.litkg_graphrag import NativeGraphRetriever
    entities = [{'id': 1, 'canonical_name': 'taxon', 'entity_type': 'MicrobialTaxon', 'aliases': []}]
    relations, facts = [], []
    for i in range(1, 46):
        entities.append({'id': i+1, 'canonical_name': f'product {i}', 'entity_type': 'Compound', 'aliases': []})
        relations.append({'id': i, 'subject': {'id': 1, 'text': 'taxon', 'type': 'MicrobialTaxon'},
            'object': {'id': i+1, 'text': f'product {i}', 'type': 'Compound'}, 'predicate': 'PRODUCES',
            'negated': False, 'speculative': False, 'review_status': 'reviewed',
            'evidence_samples': [{'document_id': 1, 'claim_id': i, 'semantic_status': 'reviewed'}]})
        facts.append({'id': i, 'claim_id': i, 'relation_id': i, 'document_id': 1, 'predicate': 'PRODUCES',
            'negated': False, 'speculative': False, 'participants': [{'entity_id': 1, 'role': 'subject', 'name': 'taxon'},
                {'entity_id': i+1, 'role': 'object', 'name': f'product {i}'}], 'claim_json': {'semantic_status': 'reviewed'},
            'evidence': [{'sentence': 'taxon produces product', 'page': 1}]})
    snapshot = {'entities': entities, 'relations': relations, 'facts': facts, 'acquisition_scope': 'full',
        'complete': True, 'counts': {'entities': 46, 'relations': 45, 'facts': 45}, 'acquired_at': 1}
    before = copy.deepcopy(snapshot)
    async def acquire(*args, **kwargs):
        return snapshot
    monkeypatch.setattr(litkg_acquisition, 'acquire_knowledge_base', acquire)
    def reject_request(request):
        pytest.fail('Full graph consumption must use the acquired snapshot')
    result = await NativeGraphRetriever(LitkgRetrievalConfig('http://kb', 30),
        transport=httpx.MockTransport(reject_request)).retrieve('taxon product', [{'name': 'taxon'}], hops=1, max_results=1)
    assert result['retrieval_scope']['candidate_relation_count'] == 45
    assert len(result['facts']) == 1
    assert result['retrieval_scope']['acquisition']['counts']['facts'] == 45
    assert snapshot == before

def test_full_search_metadata_respects_context_budget_without_cutting_citations():
    from wgs_fmt_platform.knowledge.litkg_full_usage import select_evidence
    from wgs_fmt_platform.knowledge.litkg_retrieval import render_evidence
    snapshot = {'acquisition_scope': 'full', 'complete': True, 'counts': {'facts': 40}, 'acquired_at': 1,
        'facts': [{'id': i, 'claim_id': i, 'document_id': 1, 'predicate': 'PRODUCES', 'participants': [],
            'evidence': [{'sentence': 'taxon ' + 'quoted evidence ' * 120}]} for i in range(40)]}
    before = copy.deepcopy(snapshot)
    result = select_evidence(snapshot, 'taxon', 30, LitkgRetrievalConfig('http://kb', 30))
    assert len(json.dumps({'is_error': False, 'content': render_evidence(result)}, ensure_ascii=False)) <= 17000
    ids = {str(row['id']) for row in result['facts']}
    assert all(str(row['fact_id']) in ids for row in result['citations'])
    assert snapshot == before
