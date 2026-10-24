import copy
import json

import httpx
import pytest

from wgs_agent.tools.litkg_graphrag import GraphRAGParams, LitKGGraphRAGTool
from wgs_fmt_platform.knowledge.litkg_graphrag import (
    GraphRAGError, NativeGraphRetriever, compact_fact, connection_priority, graph_views,
    pack_graph, render_graph, resolve_entities,
)
from wgs_fmt_platform.knowledge.litkg_retrieval import LitkgRetrievalConfig


def entity(i, name, kind='MicrobialTaxon'):
    return {'id':i,'canonical_name':name,'entity_type':kind,'normalized_id':None,
            'aliases':['F. prausnitzii'] if i==1 else [],'identifiers':[]}


def relation(i, source, target, predicate, doc, claim, speculative=False, negated=False):
    return {'id':i,'subject':{'id':source,'text':f'node {source}','type':'MicrobialTaxon'},
        'object':{'id':target,'text':f'node {target}','type':'Metabolite'},
        'predicate':predicate,'negated':negated,'speculative':speculative,'qualifiers':{'population':'mice'},
        'evidence_samples':[{'document_id':doc,'claim_id':claim,'sentence':'Source quote.','semantic_status':'accepted'}]}


def fact(i, edge, doc, claim, *, speculative=False, negated=False):
    return {'id':i,'relation_id':edge,'claim_id':claim,'document_id':doc,'chunk_id':5,
        'predicate':'PRODUCES' if edge==101 else 'ASSOCIATED_WITH',
        'participants':[{'entity_id':1 if edge==101 else 2,'role':'subject','name':'A'},
                        {'entity_id':2 if edge==101 else 3,'role':'object','name':'B'},
                        {'entity_id':99,'role':'cohort','name':'mouse model'}],
        'qualifiers':{'population':'mice'},'negated':negated,'speculative':speculative,
        'claim_json':{'semantic_status':'accepted'},'confidence':.9,'title':'Original study',
        'doi':'10.1234/example','filename':'paper.pdf','reviews':[],
        'evidence':[{'sentence':f'Original quote for fact {i}.','page':2,'page_end':3,'section':'Results'}]}


class Fixture:
    def __init__(self):
        self.requests=[]
        self.entities=[entity(1,'Faecalibacterium prausnitzii')]
        self.edges=[relation(101,1,2,'PRODUCES',11,1001),relation(102,2,3,'ASSOCIATED_WITH',12,1002,True,True)]
        self.facts=[fact(201,101,11,1001),fact(202,102,12,1002,speculative=True,negated=True)]
        self.pages=False
        self.foreign=False

    def handler(self, request):
        self.requests.append(request)
        assert request.url.path.startswith('/knowledge-bases/26/')
        assert request.headers['Authorization']=='Bearer test-secret'
        if request.url.path.endswith('/entities'):
            return httpx.Response(200,json={'knowledge_base_id':25 if self.foreign else 26,'entities':self.entities})
        if request.url.path.endswith('/relations'):
            assert request.method=='GET'
            assert request.url.params['include_negated']=='true'
            assert request.url.params['include_speculative']=='true'
            node=int(request.url.params['entity_id'])
            rows=[edge for edge in self.edges if node in (edge['subject']['id'],edge['object']['id'])]
            return httpx.Response(200,json={'knowledge_base_id':26,'relations':rows,'total':len(rows)})
        if request.url.path.endswith('/facts'):
            doc=int(request.url.params['document_id'])
            if self.pages and doc==11 and request.url.params['offset']=='0':
                rows=[{**fact(3000+i,None,11,4000+i),'relation_id':None} for i in range(50)]
            else:
                rows=[row for row in self.facts if row['document_id']==doc]
            return httpx.Response(200,json={'facts':rows})
        if request.url.path.endswith('/ask'):
            assert request.method=='POST'
            assert json.loads(request.content)['generate'] is False
            return httpx.Response(200,json={'knowledge_base_id':25 if self.foreign else 26,
                'facts':[],'citations':[],'warnings':[],'status':'insufficient_evidence','retrieval':'text'})
        pytest.fail(str(request.url))

    async def run(self, **kwargs):
        retriever=NativeGraphRetriever(LitkgRetrievalConfig('http://litkg.test',26,token='test-secret'),
            transport=httpx.MockTransport(self.handler),max_requests=kwargs.pop('max_requests',24))
        return await retriever.retrieve('Faecalibacterium butyrate inflammation in mice',
            [{'name':'Faecalibacterium prausnitzii'}],**kwargs)


@pytest.mark.asyncio
async def test_native_two_hop_graph_has_complete_provenance_and_no_inferred_causal_edge():
    fixture=Fixture()
    result=await fixture.run()
    assert result['status']=='evidence_only'
    assert [edge['id'] for edge in result['subgraph']['edges']]==[101,102]
    assert all(row['pending_review_kinds']==[] for row in result['facts'])
    assert all(len(row['participants'])==3 for row in result['facts'])
    assert {c['id'] for c in result['citations']}=={'201:0','202:0'}
    path=next(path for path in result['paths'] if path['node_ids']==[1,2,3])
    assert path['relation_ids']==[101,102]
    assert path['speculative'] is True and path['negated'] is True
    assert path['cross_document'] is True
    assert path['interpretation']=='retrieved_chain_not_causal_proof'
    assert result['citations'][0]['page_end']==3
    assert 'test-secret' not in render_graph(result)
    assert all(request.method=='GET' for request in fixture.requests)


def test_resolution_uses_aliases_and_does_not_invent_standard_ids():
    rows=[entity(1,'Faecalibacterium prausnitzii')]
    result=resolve_entities({'name':'F. prausnitzii'},rows)
    assert result['selected_ids']==[1]
    assert result['candidates'][0]['normalized_id'] is None
    assert resolve_entities({'name':'Faecalibacterium'},rows)['status']=='unresolved'
    ambiguous=resolve_entities({'name':'Faecalibacterium prausnitzii'},rows+[entity(9,'Faecalibacterium prausnitzii')])
    assert ambiguous['status']=='ambiguous'
    assert ambiguous['selected_ids']==[1,9]


@pytest.mark.asyncio
async def test_first_hop_does_not_expand_second_hop():
    result=await Fixture().run(hops=1)
    assert [edge['id'] for edge in result['subgraph']['edges']]==[101]
    assert all(len(path['relation_ids'])==1 for path in result['paths'])


@pytest.mark.asyncio
async def test_complete_fact_requires_real_relation_and_matching_polarity():
    fixture=Fixture()
    fixture.facts[0]['relation_id']=None
    fixture.facts[1]['negated']=False
    result=await fixture.run()
    assert result['subgraph']['edges']==[] and result['paths']==[]
    assert result['facts']==[]
    assert any(request.url.path.endswith('/ask') for request in fixture.requests)


@pytest.mark.asyncio
async def test_paginated_complete_facts_are_not_limited_to_first_batch():
    fixture=Fixture()
    fixture.pages=True
    result=await fixture.run()
    assert 201 in [row['id'] for row in result['facts']]
    assert any(request.url.path.endswith('/facts') and request.url.params['offset']=='50' for request in fixture.requests)


@pytest.mark.asyncio
async def test_foreign_knowledge_base_is_rejected():
    fixture=Fixture()
    fixture.foreign=True
    with pytest.raises(GraphRAGError,match='知识库'):
        await fixture.run()


@pytest.mark.asyncio
async def test_request_budget_is_hard_and_failure_is_visible():
    fixture=Fixture()
    result=await fixture.run(max_requests=1)
    assert len(fixture.requests)==1
    assert result['status']=='unavailable'
    assert any('预算' in message for message in result['warnings'])


def test_incoming_traversal_keeps_original_relation_direction():
    edge=relation(101,1,2,'PRODUCES',11,1001)
    nodes={1:{'id':1},2:{'id':2}}
    _,paths=graph_views([compact_fact(fact(201,101,11,1001))],nodes,{101:edge},[2])
    assert paths[0]['steps'][0]['traversal']=='incoming'
    assert paths[0]['steps'][0]['source']==1 and paths[0]['steps'][0]['target']==2


def test_one_hop_with_multiple_roots_cannot_create_two_hop_paths():
    edges={101:relation(101,1,2,'PRODUCES',11,1001),102:relation(102,2,3,'ASSOCIATED_WITH',12,1002,True,True)}
    facts=[compact_fact(fact(201,101,11,1001)),compact_fact(fact(202,102,12,1002,speculative=True,negated=True))]
    _,paths=graph_views(facts,{i:{'id':i} for i in range(1,4)},edges,[1,3],max_hops=1)
    assert all(len(path['relation_ids'])==1 for path in paths)


def test_requested_seed_connection_is_preserved_without_naming_intermediate_in_question():
    edges={101:relation(101,1,2,'PRODUCES',11,1001),102:relation(102,2,3,'ASSOCIATED_WITH',12,1002,True,True),
           105:relation(105,1,5,'ASSOCIATED_WITH',15,1005)}
    edges[105]['evidence_samples'][0]['sentence']='inflammation '*50
    assert set(connection_priority(edges,[1,3],2,{'inflammation'}))=={101,102}
    assert connection_priority(edges,[1,3],1,{'inflammation'})==[]


def test_output_budget_never_cuts_quotes_or_leaves_dangling_paths():
    edges={101:relation(101,1,2,'PRODUCES',11,1001),102:relation(102,2,3,'ASSOCIATED_WITH',12,1002,True,True)}
    facts=[compact_fact(fact(201,101,11,1001)),compact_fact(fact(202,102,12,1002,speculative=True,negated=True))]
    facts[0]['citations'][0]['sentence']='Original quote. '*2000
    before=copy.deepcopy(facts)
    result=pack_graph('question',[],[1],{i:{'id':i} for i in range(1,4)},edges,facts,8,
        LitkgRetrievalConfig('http://litkg.test',26),2,[],[],None)
    assert [row['id'] for row in result['facts']]==[202]
    assert result['omitted_fact_count']==1
    assert [edge['id'] for edge in result['subgraph']['edges']]==[102]
    assert result['paths']==[]
    assert result['citations'][0]['sentence']==before[1]['citations'][0]['sentence']
    assert len(json.dumps({'is_error':False,'content':render_graph(result)},ensure_ascii=False))<=17000


@pytest.mark.parametrize('values',[{'hops':3},{'max_results':50},{'entities':[]},{'shell':'id'},{'entities':[{'name':'  '}]}])
def test_tool_schema_rejects_unbounded_or_unavailable_parameters(values):
    with pytest.raises(ValueError):
        GraphRAGParams.model_validate({'question':'q','entities':[{'name':'A'}],**values})


def test_tool_registered_readonly_for_main_and_subagent():
    from app.agent_chat import TOOLS, _READ_TOOLS
    from app.agent_prompts import EVIDENCE_TOOL_NAMES
    from wgs_agent.tools.knowledge_tools import KNOWLEDGE_TOOLS, KNOWLEDGE_TOOL_POLICIES
    assert _READ_TOOLS['litkg_graph_rag'] is LitKGGraphRAGTool
    assert 'litkg_graph_rag' in EVIDENCE_TOOL_NAMES
    assert LitKGGraphRAGTool in KNOWLEDGE_TOOLS
    assert KNOWLEDGE_TOOL_POLICIES['litkg_graph_rag']['default']=='allow'
    assert next(item for item in TOOLS if item['function']['name']=='litkg_graph_rag')['function']['parameters']['required']==['question','entities']
