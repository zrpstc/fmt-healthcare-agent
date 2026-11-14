import copy
import re

import pytest

from test_chapter_two import build, path, member
from wgs_agent.reporting.consumer_chapter_two import metric_tier, prepare, render, fallback, appendix
from wgs_agent.reporting.consumer_basis import comparison_basis_note, NOTE


@pytest.mark.parametrize('metric,p,label',[
 ('richness',1,'偏少'),('richness',10,'略少'),('richness',50,'常见'),('richness',90,'较丰富'),('richness',99,'很丰富'),
 ('evenness',1,'较集中'),('evenness',10,'略集中'),('evenness',50,'常见'),('evenness',90,'较均衡'),('evenness',99,'很均衡'),
 ('typicality',1,'典型'),('typicality',10,'较典型'),('typicality',50,'略少见'),('typicality',90,'少见'),('typicality',99,'很少见')])
def test_directional_tiers(metric,p,label):
 assert metric_tier(metric,p)==label


def test_borderline_uses_shared_G2_downgrade():
 assert metric_tier('richness',1,True)=='略少'
 assert metric_tier('evenness',99,True)=='较均衡'
 assert metric_tier('typicality',99,True)=='少见'


def test_consumer_body_uses_one_profile_three_metrics_and_no_old_section_or_technical_words():
 doc=build(healthy=True)
 doc['word_figures']={'2.1.1':{'filename':'diversity.png'},'2.2.1':{'filename':'scatter.png'}}
 doc['template_inputs']['healthy_comparison']['typicality']={'status':'available','median_distance':.9,'percentile':92,'n_reference':103,'borderline':False,'reference_version':'test'}
 before=copy.deepcopy(doc['evidence'])
 body='\n'.join(render(doc))
 assert '### 2.4' not in body
 assert all(x not in body for x in ['PCoA','Bray-Curtis','Lingoes','PWY-','P163','CENTFERM','通路丰度','分层','已注释分类单元','未建立功能参考分布','Simpson','Pielou','e-05','P5','P95','未提供'])
 assert body.count('Shannon')==1 and '综合多样性（Shannon 指数）' in body
 assert body.count(NOTE)==1 and len(prepare(doc)['diversity'])==3
 assert doc['evidence']==before
 assert doc['consumer']['typicality']['tier']=='少见'


@pytest.mark.parametrize('missing',['丁酸合成','乳酸利用','复杂多糖降解'])
def test_any_missing_function_stage_is_hidden_and_audited(missing):
 paths={
  '丁酸合成':path('PWY-5676','acetyl-CoA fermentation to butanoate II',1,[member('A one',1)]),
  '乳酸利用':path('PWY-8086','(S)-lactate fermentation to propanoate, acetate and hydrogen',1,[member('B two',1)]),
  '复杂多糖降解':path('PWY-6731','starch degradation III',1,[member('C three',1)]),
 }
 doc=build([row for key,row in paths.items() if key!=missing])
 result=prepare(doc)
 assert len(result['stages'])==2 and missing not in [r['category'] for r in result['stages']]
 assert any(r['item']=='stage:'+missing for r in doc['consumer_omissions'])


def test_empty_function_section_is_one_sentence_and_unknown_typicality_is_omitted():
 doc=build()
 body='\n'.join(render(doc))
 section=body.split('### 2.3 ',1)[1].split('\n',1)[1]
 assert section=='本次检测未覆盖这部分内容。'
 assert 'typicality' not in doc['consumer']
 assert any(r['item']=='typicality' for r in doc['consumer_omissions'])


def test_backup_thresholds_and_enzyme_only_evidence_do_not_invent_concentration():
 shared=path('PWY-5676','x',1,[member('A one',.4),member('B two',.3),member('C three',.3)])
 assert prepare(build([shared]))['stages'][0]['backup']=='多种菌分担'
 shared['contributors'][0]['abundance']=.6
 shared['contributors'][1]['abundance']=.2
 shared['contributors'][2]['abundance']=.2
 assert prepare(build([shared]))['stages'][0]['backup']=='主要依赖少数菌'


def test_G12_is_pure_and_requires_an_independent_profile():
 doc=build(healthy=True)
 first=comparison_basis_note(doc,2)
 assert first==NOTE and comparison_basis_note(doc,2)==NOTE
 assert comparison_basis_note(build(),2) is None


def test_coverage_gap_is_visible_only_in_appendix_and_raw_fields_remain():
 doc=build([path('P163-PWY','L-lysine fermentation to acetate and butanoate',1,[member('Fusobacterium nucleatum',1)])])
 doc['template_inputs']['taxonomy']={'ranks':{'species':[{'name':'Faecalibacterium prausnitzii','abundance':13.3}]}}
 body='\n'.join(render(doc));details='\n'.join(appendix(doc))
 assert 'coverage_gap' not in body and 'coverage_gap' in details
 assert '基因注释可能遗漏部分菌。' in details
 assert '仅由' not in body and '只由' not in body


def test_merged_topic_id_is_retained_and_directory_uses_three_visible_subsections():
 from wgs_agent.reporting.word_template import narrative_sections
 from wgs_agent.reporting.document import render_markdown
 doc=build([path('PWY-5676','acetyl-CoA fermentation to butanoate II',1,[member('A one',1)])])
 sections=narrative_sections(doc)
 topics={t['id']:t for s in sections if s['id']=='word.2' for t in s['topics']}
 assert set(topics)=={'word.2.1','word.2.2','word.2.3','word.2.4'}
 assert topics['word.2.4']['consumer_hidden'] and topics['word.2.4']['consumer_merged_into']=='word.2.3'
 assert set(topics['word.2.4']['allowed_narrative_ids']) <= set(topics['word.2.3']['allowed_narrative_ids'])
 md=render_markdown(doc)
 assert '[2 菌群的多样性与分工]' in md and '### 2.4 ' not in md
 assert len(doc['presentation']['chapters'][1]['subsections'])==3


def test_shared_scale_supports_integer_counts_above_100_and_neutral_evenness():
 from wgs_agent.reporting.word_figures import draw_tier_scale
 doc=build(healthy=True)
 next(r for r in doc['evidence'].values() if r.get('kind')=='healthy_diversity' and r.get('metric')=='richness')['value']=201
 rows=prepare(doc)['diversity']
 assert rows[0]['formatted_value']=='201种'
 assert next(r for r in rows if r['metric']=='evenness')['color']=='#66737C'
 image=draw_tier_scale(rows)
 assert image.height<500
 assert any(rgb==(102,115,124) for _,rgb in image.getcolors(image.width*image.height))


def test_appendix_preserves_parent_totals_and_mixed_unit_contributors():
 doc=build([path('PWY-5676','acetyl-CoA fermentation to butanoate II',7,[member('A one',2)])])
 doc['evidence']['P1']['contributors'][0]['unit']='CPM'
 details='\n'.join(appendix(doc))
 assert '群落通路总量' in details and '| 7.0 |' in details
 assert 'CPM' in details and 'A one' in details and '未合并计算' in details
