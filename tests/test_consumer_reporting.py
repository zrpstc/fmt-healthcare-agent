"""Consumer contracts: numeric fidelity, safe omissions, source gates and scoped prose."""
import copy
import json
import re
from decimal import Decimal
import httpx
import pytest
from wgs_agent.reporting.consumer_format import pct, count, tier, percentile_phrase
from wgs_agent.reporting.consumer_state import NameRegistry
from wgs_agent.reporting.taxon_labels import display_name
from wgs_agent.reporting.glossary import Glossary, VERSION
from wgs_agent.reporting.consumer_copy import FORBIDDEN
from wgs_agent.reporting.narrative import consumer_text_error, generate_narrative
from wgs_agent.reporting.document import render_markdown
from wgs_agent.reporting.word_figures import chart_data, draw_tier_scale, render_word_figures
from test_chapter_one import build


@pytest.mark.parametrize('value,expected',[(0,'<0.01%'),(.00999,'<0.01%'),(.01,'0.01%'),(.075,'0.075%'),(.0999,'0.1%'),(.1,'0.10%'),(.45,'0.45%'),(.999,'1.00%'),(1,'1.0%'),(24.777,'24.8%'),(99.999,'100%'),(100,'100%')])
def test_percentage_boundaries(value,expected):
    assert pct(value)==expected
    if value>=.01:assert len(Decimal(expected[:-1]).normalize().as_tuple().digits)<=3


@pytest.mark.parametrize('value',[None,True,-1,float('inf'),float('nan'),101])
def test_invalid_percentages_fail_closed(value):
    with pytest.raises((TypeError,ValueError)):pct(value)


def test_counts_and_percentile_phrases():
    assert count(3537)=='3,537'
    assert percentile_phrase(99)=='高于99%以上的参考人群'
    assert percentile_phrase(50)=='高于约50%的参考人群'
    assert percentile_phrase(25)=='低于约75%的参考人群'
    assert percentile_phrase(1)=='低于99%以上的参考人群'


@pytest.mark.parametrize('p,label',[(0,'明显偏低'),(5,'略低'),(25,'常见'),(75,'常见'),(95,'略高'),(100,'明显偏高')])
def test_tiers_and_borderline(p,label):
    assert tier(p)==label
    assert '明显' not in tier(p,True)


def test_names_and_report_order():
    row={'species':'Bacteroides_fragilis'}
    assert display_name(row,True)=='脆弱拟杆菌（*Bacteroides fragilis*）'
    assert display_name(row,False)=='脆弱拟杆菌'
    doc={};registry=NameRegistry(doc)
    assert '*' in registry.name(row)
    assert '*' not in registry.name(row)
    assert '*' in NameRegistry(doc).name(row)  # Rendering twice is deterministic.
    assert display_name({'species':'unclassified_SGB123','taxonomy_lineage':'k__Bacteria|g__Bacteroides|s__unclassified_SGB123'},True)=='未命名菌（拟杆菌属相关）'


def evidence(ident='paper-a'):
    return [{'type':'litkg','id_or_url':ident,'title':'A functional claim','year':2024,'text':'A species-level functional claim.','evidence_scope':'species'}]


def compression(name,rows):
    return {'one_liner':'能利用部分糖类参与发酵。','evidence_scope':'species','source_ids':[rows[0]['id_or_url']]}


def test_glossary_order_cache_and_review_gate(tmp_path,monkeypatch):
    dictionary=tmp_path/'dictionary.yaml';dictionary.write_text('{"entries":[]}',encoding='utf-8')
    calls=[]
    def first(name):calls.append('litkg');return []
    def second(name):calls.append('pubmed');return evidence()
    def forbidden(name):raise AssertionError('provider after hit must not run')
    doc={};monkeypatch.setenv('WGS_GLOSSARY_REQUIRE_REVIEW','1')
    service=Glossary(doc,dictionary=dictionary,runtime=tmp_path/'runtime',litkg=first,pubmed=second,web=forbidden,compress=compression)
    assert service.get('test species',latin='Test species') is None
    assert calls==['litkg','pubmed']
    entry=doc['consumer']['glossary']['test species'];assert entry['review_status']=='pending'
    assert doc['consumer_omissions'][0]['reason_code']=='glossary_pending_review'
    calls.clear();monkeypatch.setenv('WGS_GLOSSARY_REQUIRE_REVIEW','0')
    other=Glossary({},dictionary=dictionary,runtime=tmp_path/'runtime',litkg=forbidden,pubmed=forbidden,web=forbidden,compress=compression)
    assert other.get('test species',latin='Test species')['one_liner']==entry['one_liner']
    assert calls==[]
    queue=tmp_path/'runtime/glossary_review_queue.jsonl'
    assert len(queue.read_text().splitlines())==1
    approved={**entry,'review_status':'approved'}
    dictionary.write_text(json.dumps({'entries':[approved]}),encoding='utf-8')
    assert Glossary({},dictionary=dictionary,runtime=tmp_path/'runtime',litkg=forbidden,compress=compression).get('test species')['review_status']=='approved'


def test_glossary_rejects_scope_invention_and_stops_at_evidence(tmp_path):
    calls=[]
    service=Glossary({},dictionary=tmp_path/'missing.yaml',runtime=tmp_path,litkg=lambda n:evidence(),pubmed=lambda n:calls.append('pubmed'),compress=lambda n,r:{'one_liner':'导致疾病。','evidence_scope':'species','source_ids':['invented']})
    assert service.get('test') is None and calls==[]
    assert not list((tmp_path/'glossary').glob('*.json'))
    rows=[{**evidence()[0],'evidence_scope':'genus'}]
    assert service._entry('x','taxon','菌','X',rows,compression('X',rows)) is None


def test_web_provider_default_allowlist_and_redirect_bounds(monkeypatch):
    from wgs_agent.reporting.web_search import search,allowed_url
    monkeypatch.delenv('WGS_WEB_SEARCH_PROVIDER',raising=False)
    assert search('test')==[]
    assert allowed_url('https://pmc.ncbi.nlm.nih.gov/articles/test')
    assert not allowed_url('https://pmc.ncbi.nlm.nih.gov.evil.example/test')
    monkeypatch.setenv('WGS_WEB_SEARCH_PROVIDER','searxng');monkeypatch.setenv('WGS_SEARXNG_URL','http://search.local')
    visited=[]
    def transport(request):
        visited.append(str(request.url))
        if request.url.host=='search.local':
            return httpx.Response(200,json={'results':[{'url':'https://evil.example/','title':'bad'},{'url':'https://pmc.ncbi.nlm.nih.gov/test','title':'paper'}]})
        return httpx.Response(302,headers={'location':'https://evil.example/redirect'})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:assert search('test',client=client)==[]
    assert len(visited)==2 and all('evil.example' not in url for url in visited)


def chapter_one(markdown):
    return markdown.split('## 1 ',1)[1].split('## 2 ',1)[0]


def test_consumer_body_has_no_forbidden_terms_or_raw_percentages(tmp_path):
    doc=build(healthy=True);before=copy.deepcopy(doc['evidence'])
    render_word_figures(doc,tmp_path);body=chapter_one(render_markdown(doc))
    assert all(term not in body for term in FORBIDDEN)
    for match in re.findall(r'\d+(?:\.\d+)?%',body):
        assert len(Decimal(match[:-1]).normalize().as_tuple().digits)<=3
    assert '### 1.3 ' not in body and '相关知识子图' not in body
    assert doc['evidence']==before
    assert sum(r['value'] for r in chart_data(doc,{'id':'1.2.1','kind':'barChart'})['rows'])==pytest.approx(100)
    phylum=chart_data(doc,{'id':'1.1.1','kind':'barChart'})
    assert phylum['total']==pytest.approx(100)


def test_unclassified_fraction_and_empty_states(tmp_path):
    doc=build()
    first=next(r for r in doc['evidence'].values() if r.get('kind')=='tax_phylum');first['value']-=8.8
    payload=chart_data(doc,{'id':'1.1.1','kind':'barChart'})
    assert payload['rows'][-1]['display_label']=='未能归类'
    assert payload['rows'][-1]['value']==pytest.approx(8.8)
    doc=build();doc['metadata']['qc_status']='failed'
    figures=render_word_figures(doc,tmp_path)
    assert not any(key.startswith('1.') for key in figures)
    body=chapter_one(render_markdown(doc));assert body.count('本次检测未覆盖这部分内容。')==3
    assert all(term not in body for term in FORBIDDEN)
    assert any(r['reason_code']=='reference_genus_profile_missing' for r in doc['consumer_omissions'])


def test_narrative_numbers_and_natural_fallback():
    assert consumer_text_error('您的优势菌约占24.8%。',['24.8%']) is None
    assert consumer_text_error('您的优势菌约占24.9%。',['24.8%'])=='consumer_numeric_mismatch'
    assert consumer_text_error('您的优势菌约占24.777%。',['24.8%'])=='consumer_numeric_mismatch'
    from wgs_agent.reporting.consumer_chapter import interpretation
    doc=build();doc['word_sections']=[{'topics':[{'id':'word.1.1','interpretation':'本次已记录原始结果。'}]}]
    assert interpretation(doc,1).startswith('您的菌群以厚壁菌门为主')
    assert '；' not in interpretation(doc,1)


def test_tier_image_uses_no_red_and_borderline_is_not_strong():
    rows=[{'display_label':'测试菌','value':2,'percentile':99,'borderline':True}]
    image=draw_tier_scale(rows,1800)
    assert tier(99,True)=='略高'
    colors=[color for _,color in image.getcolors(image.width*image.height)]
    assert (180,122,36) in colors
    assert not any(r>180 and g<80 and b<80 for r,g,b in colors)


def test_existing_chapters_keep_exact_body_output(tmp_path):
    from wgs_agent.reporting.word_template import render_body
    doc=build(healthy=True)
    from wgs_agent.reporting.template_body import prepare_presentation
    prepare_presentation(doc)
    before='\n\n'.join(render_body(doc)).split('## 2 ',1)[1]
    from wgs_agent.reporting.chapter_one import prepare_chapter_one
    prepare_chapter_one(doc,None)
    after='\n\n'.join(render_body(doc)).split('## 2 ',1)[1]
    assert before==after


def test_preserving_other_chapter_figures_reuses_exact_bytes(tmp_path):
    doc=build(healthy=True)
    source=tmp_path/'source'
    destination=tmp_path/'destination'
    render_word_figures(doc,source)
    previous=copy.deepcopy(doc['word_figures'])
    render_word_figures(doc,destination,preserve_existing_from=source)
    for key,item in previous.items():
        if key.startswith('1.'):continue
        assert doc['word_figures'][key]==item
        assert (source/item['filename']).read_bytes()==(destination/item['filename']).read_bytes()


def test_concentration_rejects_a_different_reference_package(monkeypatch):
    from wgs_agent.reporting.consumer_reference import concentration
    monkeypatch.setattr('wgs_agent.reporting.cmd.load_bundle',lambda p:({},[],[],None,{'metadata.tsv':'different-reference'}))
    doc={'sample_id':'TEST','template_inputs':{'healthy_comparison':{'audit':{'status':'available','file_sha256':{'metadata.tsv':'original-reference'}}}}}
    assert concentration(doc) is None
