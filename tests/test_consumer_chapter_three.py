import copy
import re
import pytest
from wgs_agent.reporting.document import build_document,render_markdown
from wgs_agent.reporting.consumer_chapter_three import prepare,render,category_tier,WARNING,refresh_word_section
from wgs_agent.reporting.consumer_copy import FORBIDDEN


def build():
    rows=[{'species':name,'abundance':value,'unit':'%'} for name,value in [
        ('Faecalibacterium prausnitzii',13.3),('Roseburia hominis',3.5),('Bifidobacterium adolescentis',1.5),
        ('Limosilactobacillus fermentum',4.6),('Akkermansia muciniphila',1.9),('Escherichia coli',11.1),
        ('Clostridioides difficile',1.4),('Bacteroides fragilis',13.6)]]
    inputs={'taxonomy':{'complete':True,'unit':'%','ranks':{'species':rows}}}
    doc=build_document('CH3_TEST',{'species_list':rows},{},{},{},{},{},{},{},context={'qc_status':'passed','health_inputs':inputs})
    from wgs_agent.reporting.word_template import narrative_sections
    doc['word_sections']=narrative_sections(doc)
    return doc


@pytest.mark.parametrize('section,p,borderline,expected',[
    ('helpful',1,False,'偏少'),('helpful',50,False,'常见'),('helpful',99,False,'很多'),('helpful',99,True,'较多'),
    ('watch',1,False,'较少'),('watch',99,False,'明显偏多'),('watch',99,True,'略多')])
def test_directional_labels(section,p,borderline,expected):
    assert category_tier(section,p,borderline)==expected


def test_cards_preserve_evidence_and_shared_explanations_and_hide_old_sections():
    from wgs_agent.reporting.consumer_chapter import prepare as prepare_one
    doc=build();before=copy.deepcopy(doc['evidence']);ids={topic['id'] for section in doc['sections'] for topic in section['topics']}
    first=prepare_one(doc);third=prepare(doc,force=True)
    member=next(member for card in third['cards'] for member in card['members'] if member['species']=='Faecalibacterium prausnitzii')
    original=next(row for row in first['species'] if row['species']=='Faecalibacterium prausnitzii')
    assert member['one_liner']==original['explanation'].split('[')[0]
    body='\n'.join(render(doc));scan=re.sub(r'图 3-\dk  与本节相关的研究知识','',body)
    assert all(word not in scan for word in FORBIDDEN)
    assert not re.search(r'LitKG|分类编号|原始分类谱|读段数|覆盖度|主分析|对照谱|（检出）|\bP\d+(?:\.\d)?|### 3\.[34]',body)
    assert body.count(WARNING)==1
    assert doc['evidence']==before and {topic['id'] for section in doc['sections'] for topic in section['topics']}==ids
    assert any(card['id']=='watch.sulfide' and card['status']=='not_detected' for card in third['cards'])
    assert all(member['reliability'] is None for card in third['cards'] for member in card['members'])


def test_refresh_only_chapter_three_word_view_and_keep_original_topic_ids():
    doc=build();others=copy.deepcopy([section for section in doc['word_sections'] if section['id']!='word.3'])
    original_ids={topic['id'] for section in doc['word_sections'] for topic in section['topics']};evidence=copy.deepcopy(doc['evidence'])
    refresh_word_section(doc)
    assert [section for section in doc['word_sections'] if section['id']!='word.3']==others
    assert {topic['id'] for section in doc['word_sections'] for topic in section['topics']}==original_ids
    assert doc['evidence']==evidence
    section=next(section for section in doc['word_sections'] if section['id']=='word.3')
    assert all(topic.get('consumer_hidden') for topic in section['topics'] if topic['id'].endswith(('.3','.4')))


def test_chapter_four_reference_is_allowed_only_as_cross_reference_not_an_extra_number():
    from wgs_agent.reporting.consumer_chapter_three import interpretation
    doc=build();topic=next(topic for section in doc['word_sections'] for topic in section['topics'] if topic['id']=='word.3.2')
    topic['interpretation']='这类菌在健康人中也常见，检出不等于感染，具体请看第4章。'
    assert interpretation(doc,2)==topic['interpretation']
    topic['interpretation']='本次检出了4种需要留意的菌，请看第4章。'
    assert interpretation(doc,2)!=topic['interpretation']


def test_repeated_card_render_keeps_images_and_whole_report_stable(tmp_path):
    from wgs_agent.reporting.word_figures import render_word_figures
    doc=build();render_word_figures(doc,tmp_path);first=render_markdown(doc)
    figures={key:value['filename'] for key,value in doc['word_figures'].items() if key.startswith('3.cards.')}
    assert set(figures)=={'3.cards.helpful','3.cards.watch'}
    render_word_figures(doc,tmp_path)
    assert {key:value['filename'] for key,value in doc['word_figures'].items() if key.startswith('3.cards.')}==figures
    assert render_markdown(doc)==first
