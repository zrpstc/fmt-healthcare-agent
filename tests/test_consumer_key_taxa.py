import copy
import json
import pytest
from wgs_agent.reporting.consumer_key_taxa import load_panel,matches,build_panel,category_totals,function_tag_entries,reliability
from wgs_agent.reporting.consumer_badges import research_badge
from wgs_agent.reporting.glossary import Glossary


def document(rows=(), *, qc='passed',complete=True):
    return {'metadata':{'qc_status':qc},'template_inputs':{'taxonomy':{'complete':complete,'unit':'%',
            'ranks':{'species':[{'name':name,'abundance':value,**extra} for name,value,extra in rows]}}},'evidence':{}}


def test_panel_matches_exact_species_aliases_and_genus_without_double_counting():
    panel=load_panel();by_id={row['id']:row for row in panel['categories']}
    assert matches('Eubacterium_rectale',{'rank':'species','name':'Agathobacter rectalis','aliases':['Eubacterium rectale']})
    assert not matches('Roseburia hominis',{'rank':'species','name':'Roseburia intestinalis'})
    data=category_totals({'Lactobacillus fermentum':2,'Limosilactobacillus fermentum':3,'Roseburia hominis':4,'Faecalibacterium prausnitzii':5},panel)
    assert data['helpful.lactobacilli']==5 and data['helpful.butyrate']==9
    doc=document([('Roseburia hominis',4,{}),('Faecalibacterium prausnitzii',5,{})])
    tagged=function_tag_entries(doc,panel)
    assert {row['latin'] for row in tagged}=={'Roseburia hominis','Faecalibacterium prausnitzii'}
    assert all('butyrate_producer' in row['tags'] for row in tagged)


@pytest.mark.parametrize('qc,complete,absent',[('passed',True,True),('passed',False,False),('',True,False),('failed',True,False)])
def test_absence_requires_passed_qc_complete_profile_and_no_member(qc,complete,absent):
    doc=document(qc=qc,complete=complete)
    cards=build_panel(doc,references={})['cards']
    card=next((row for row in cards if row['id']=='helpful.bifidobacteria'),None)
    assert bool(card and card['status']=='not_detected')==absent
    if not absent: assert doc['consumer_omissions']
    doc=document([('Bifidobacterium longum',0,{})],qc=qc,complete=complete)
    assert not any(row['id']=='helpful.bifidobacteria' for row in build_panel(doc)['cards'])


@pytest.mark.parametrize('reads,label',[(0,'低'),(99,'低'),(100,'中'),(999,'中'),(1000,'高')])
def test_reliability_uses_only_estimated_read_fields(reads,label):
    assert reliability({'estimated_reads':reads})['label']==label
    assert reliability({'reads':5000,'coverage':99}) is None


def test_missing_reliability_does_not_hide_detected_member_and_conditional_species_requires_chapter_one_high():
    doc=document([('Bacteroides fragilis',13.6,{}),('Escherichia coli',11,{})])
    cards=build_panel(doc)['cards']
    assert not any(row['id']=='watch.conditional_commensal' for row in cards)
    assert any(row['reason_code']=='estimated_reads_missing' for row in doc['consumer_omissions'])
    doc.setdefault('consumer',{})['chapters']={'1':{'reference_rows':[{'species':'Bacteroides fragilis','tier_label':'明显偏高'}]}}
    card=next(row for row in build_panel(doc)['cards'] if row['id']=='watch.conditional_commensal')
    assert card['members'][0]['panel_note'] and card['total']==13.6


def test_evidence_badges_count_independent_species_sources_and_never_claims_per_paper():
    def entry(sources,scope='species'):return {'one_liner':'参与发酵。','review_status':'approved','evidence_scope':scope,'sources':sources}
    sources=[{'type':'pubmed','id_or_url':str(i)} for i in range(3)]
    assert research_badge(entry(sources))=='多项研究'
    assert research_badge(entry(sources[:2]))=='少量研究'
    assert research_badge(entry(sources,'genus'))=='同属研究推断'
    same=[{'type':'litkg','id_or_url':str(i),'document_id':2} for i in range(4)]
    assert research_badge(entry(same))=='少量研究'
    assert research_badge({**entry(sources),'one_liner':''}) is None
    assert research_badge(entry([{'type':'curated','id_or_url':'editorial'}])) is None


def test_watch_note_validation_review_and_shared_cache(tmp_path,monkeypatch):
    dictionary=tmp_path/'empty.yaml';dictionary.write_text('{"entries":[]}')
    evidence=[{'type':'pubmed','id_or_url':'1','title':'Study one','year':2020,'text':'A study association.','evidence_scope':'species'}]
    calls=[]
    def first(name):calls.append('litkg');return evidence
    def later(name):raise AssertionError('provider after first evidence must not run')
    note={'watch_note':'研究中与肠道炎症相关，偏多只提示关联，具体请看第4章。','evidence_scope':'species','source_ids':['1']}
    service=Glossary({},dictionary=dictionary,runtime=tmp_path,litkg=first,pubmed=later,compress_watch=lambda *a:note)
    assert service.get_watch_note('test species',latin='Test species') is None
    entry=service.document['consumer']['glossary']['test species']
    assert entry['watch_review_status']=='pending' and entry['watch_sources'][0]['id_or_url']=='1'
    assert calls==['litkg']
    monkeypatch.setenv('WGS_GLOSSARY_REQUIRE_REVIEW','0')
    cached=Glossary({},dictionary=dictionary,runtime=tmp_path,litkg=later)
    assert cached.get_watch_note('test species')['watch_note']==note['watch_note']
    assert service._watch_entry(evidence,{**note,'source_ids':['invented']}) is None
    assert service._watch_entry(evidence,{**note,'watch_note':'感染了，会导致疾病。'}) is None
    assert service._watch_entry(evidence,{**note,'watch_note':''}) is None
    assert service._watch_entry(evidence,{**note,'extra':'not permitted'}) is None


def test_category_reference_uses_offline_values_and_rejects_stale_panel_without_runtime_fit(monkeypatch):
    from wgs_agent.reporting import consumer_reference as ref,cmd_derived
    from wgs_agent.reporting.population_reference import comparison
    panel=load_panel();ids=[str(i) for i in range(30)]
    asset={'schema_version':'consumer-key-taxa-reference-v1','panel_sha256':panel['sha256'],
           'panel_version':panel['schema_version'],'ids':ids,
           'categories':{row['id']:list(range(30)) for row in panel['categories']}}
    payload={'ids':ids,'key_taxa':asset,'_asset_sha256':'validated-summary'}
    class ForbiddenMatrix:
        def selected(self,*a):raise AssertionError('reference categories must not be fitted at runtime')
    context={'manifest':{},'hashes':{},'selected':ids,'reference_version':'validated-cohort','matrix':ForbiddenMatrix(),
             'species':[{'species':'Faecalibacterium prausnitzii','abundance':1},{'species':'Roseburia hominis','abundance':2}]}
    monkeypatch.setattr(ref,'validated_selection',lambda doc:context)
    monkeypatch.setattr(cmd_derived,'load_derived',lambda *a:(payload,None))
    result=ref.key_taxa_reference({},panel)
    assert result['helpful.butyrate']['value']==3
    assert result['helpful.butyrate']['percentile']==comparison(3,list(range(30)))['percentile']
    asset['panel_sha256']='stale'
    assert ref.key_taxa_reference({},panel) is None
