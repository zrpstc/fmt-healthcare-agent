"""Consumer key-taxa cards; original topic, assay and support records survive."""
from __future__ import annotations
import copy
import hashlib
import io
import json
from pathlib import Path
import re

from PIL import Image,ImageDraw
from .consumer_state import consumer,omit,NameRegistry
from .consumer_format import pct,percentile_phrase,tier
from .consumer_key_taxa import load_panel,build_panel,taxon_key

TIERS = {'helpful':('偏少','略少','常见','较多','很多'), 'watch':('较少','略少','常见','略多','明显偏多')}
BASE_TIERS = ('明显偏低','略低','常见','略高','明显偏高')
WARNING = '无症状人群中也可检出这类菌；若有持续腹泻、发热或便血，请就医并带上本报告。'


def category_tier(section,percentile,borderline=False):
    return TIERS[section][BASE_TIERS.index(tier(percentile,borderline))]


def _concept(service,term,*,detail=False):
    entry=service.get(term,kind='concept',chapter=3)
    return (entry.get('detail') if detail and entry.get('detail') else entry['one_liner']) if entry else ''


def prepare(document,*,config=None,force=False):
    from .consumer_reference import key_taxa_reference
    from .glossary import Glossary,citation_numbers
    from .consumer_badges import research_badge
    from .chapter_one import name as display_name
    panel=load_panel();state=consumer(document);previous=state.get('chapter_three',{})
    glossary_path=Path(__file__).resolve().parents[3]/'knowledge_base/consumer_glossary.yaml'
    inputs=document.get('template_inputs',{});population=inputs.get('healthy_comparison') or {}
    signature=hashlib.sha256(json.dumps({'version':'consumer-ch3-v1','taxonomy':inputs.get('taxonomy'),
        'reference':population,'qc':document.get('metadata',{}).get('qc_status'),'panel':panel['sha256'],
        'glossary':hashlib.sha256(glossary_path.read_bytes()).hexdigest(),'model_enabled':bool(config) or previous.get('_model_prepared',False)},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if not force and previous.get('_preparation_signature')==signature:
        return previous
    service=Glossary(document,config=config)
    references=key_taxa_reference(document,panel)
    data=build_panel(document,panel=panel,references=references)
    definitions={key:_concept(service,key,detail=True) for key in ['opportunists','butyrate_producers','detection_reliability','research_evidence_strength']}
    for card in data['cards']:
        card['explanation']=_concept(service,card['concept_term_id']) if card['status']=='detected' else ''
        concept=state.get('glossary',{}).get(card['concept_term_id']) or {}
        card['absence_note']=concept.get('absence_note','') if concept.get('absence_review_status')=='approved' else ''
        if card.get('reference'):
            ref=card['reference'];card['tier']=category_tier(card['section'],ref['percentile'],ref.get('borderline',False))
            card['percentile_phrase']=percentile_phrase(ref['percentile'])
            card['color']=('#B47A24' if card['tier'] in ({'偏少','略少'} if card['section']=='helpful' else {'略多','明显偏多'}) else '#276F6A')
        else:
            card['tier']='';card['percentile_phrase']=''
            if card['status']=='detected':omit(document,3,'category_reference:'+card['id'],'key_taxa_reference_unavailable','重点菌类别参考资产缺失、过期或不可比较')
        for member in card['members']:
            key=taxon_key(member['species'])
            label=display_name(document,member)
            member['display_label']=label
            entry=service.get(key,kind='taxon',display_name=label,latin=member['species'],chapter=3)
            member['glossary_term']=key
            member['one_liner']=entry['one_liner'] if entry else ''
            member['one_liner_display']=member['one_liner']+(citation_numbers(document,entry) if entry else '')
            member['evidence_badge']=research_badge(entry)
            member['watch_note']='';member['watch_badge']=None
            if card['section']=='watch':
                watch=service.get_watch_note(key,display_name=label,latin=member['species'],chapter=3)
                if watch:
                    note=watch['watch_note'].replace('具体需看第4章毒力检测','请看第4章').replace('见第4章','请看第4章')
                    member['watch_note']=note+ citation_numbers(document,{'sources':watch.get('watch_sources',[])})
                    member['watch_badge']=research_badge({**(entry or {}),**watch},field='watch_note')
    detected_watch=[member for card in data['cards'] if card['section']=='watch' for member in card['members']]
    data['show_diarrhea_warning']=any(taxon_key(row['species']) in {'clostridioides difficile','clostridium difficile','clostridium perfringens'} for row in detected_watch)
    from .chapter_three import support_table,table_payload
    raw=previous.get('raw_legacy_tables') or {str(sub):copy.deepcopy(table_payload(document,sub)) for sub in (1,2,3)}
    source_figures=previous.get('source_word_figures')
    if source_figures is None:source_figures={key:copy.deepcopy(value) for key,value in document.get('word_figures',{}).items() if key.startswith('3.')}
    data.update(definitions=definitions,raw_legacy_tables=raw,source_word_figures=source_figures,
                topic_mapping={'word.3.1':['word.3.1'],'word.3.2':['word.3.2','word.3.3']},
                _preparation_signature=signature,_model_prepared=bool(config) or previous.get('_model_prepared',False))
    state['chapter_three']={**previous,**data}
    return state['chapter_three']


def graph_seeds(document,subsection):
    section='helpful' if subsection==1 else 'watch'
    return sorted({name for card in prepare(document)['cards'] if card['section']==section
                   for member in card['members'] for name in (member['species'],member['display_label'])})


def displayed_values(document,subsection):
    section='helpful' if subsection==1 else 'watch'
    values=[]
    for card in prepare(document)['cards']:
        if card['section']!=section or card['status']!='detected':continue
        values.extend([pct(card['total']),card['percentile_phrase']])
        values.extend(pct(row['value']) for row in card['members'])
    return [value for value in values if value]


def text_error(text,subsection):
    if re.search(r'LitKG|分类编号|原始分类谱|读段数|覆盖度|主分析|对照谱|未建立同物种对照|证据等级未单独标注|（检出）|\bP\d+(?:\.\d)?|3\.[34]|第4章.{0,6}(?:检出|阳性|阴性|发现)',text,re.I):
        return 'consumer_ch3_technical_or_unmeasured_claim'
    return None


def fallback(document,subsection):
    cards=[card for card in prepare(document)['cards'] if card['section']==('helpful' if subsection==1 else 'watch')]
    if subsection==1:
        selected=[card for card in cards if card['status']=='not_detected' or card.get('reference')]
        selected.sort(key=lambda card:(card['status']!='not_detected',card.get('tier')=='常见'))
        if selected:
            phrases=[card['display_name']+('本次未检出' if card['status']=='not_detected' else '合计'+card['tier']) for card in selected[:2]]
            return ('与健康人相比，' if any(card.get('reference') for card in selected[:2]) else '')+'；'.join(phrases)+'。'
        return '本次检出的健康相关菌包括'+ '、'.join(card['display_name'] for card in cards[:2])+'。' if cards else ''
    high=[card for card in cards if card.get('tier') in {'略多','明显偏多'}]
    if high:
        return '、'.join(card['display_name'] for card in high[:2])+'合计偏多；检出不等于感染，是否携带相关基因请看第4章。'
    comparable=[card for card in cards if card['status']=='detected' and card.get('reference')]
    if comparable and all(card['tier']=='常见' for card in comparable):return '需要留意的几类菌都在健康人的常见范围内；检出不等于感染。'
    return '本次检出部分需要留意的菌，检出不等于感染；具体请看第4章。' if any(card['members'] for card in cards) else ''


def interpretation(document,subsection):
    from .narrative import consumer_text_error
    topic=next((topic for section in document.get('word_sections',[]) for topic in section['topics'] if topic['id']==f'word.3.{subsection}'),{})
    value=topic.get('interpretation','')
    plain=value.replace('第4章','')
    if topic.get('consumer_presentation_version')=='consumer-ch3-v1' and value and consumer_text_error(plain,displayed_values(document,subsection)) is None and text_error(value,subsection) is None:return value
    return fallback(document,subsection)


def refresh_word_section(document):
    """Refresh only the consumer chapter-three view; preserve every original ID."""
    from .word_template import narrative_sections
    data=prepare(document)
    previous=next((section for section in document.get('word_sections',[]) if section['id']=='word.3'),None)
    if previous is not None:data.setdefault('source_word_section',copy.deepcopy(previous))
    clone=copy.deepcopy(document)
    fresh=next((section for section in narrative_sections(clone) if section['id']=='word.3'),None)
    if not fresh:return
    if any(key not in document['evidence'] for topic in fresh['topics'] for key in topic.get('allowed_narrative_ids',[])):
        omit(document,3,'word_section_refresh','stable_evidence_ids_unavailable','既有报告缺少可保持身份的正文观测');return
    for topic in fresh['topics']:
        topic['interpretation']='';topic['advice']='';topic['narrative_source']='rule'
    document['word_sections']=[fresh if section['id']=='word.3' else section for section in document.get('word_sections',[])]


def _member_lines(member,section,registry):
    name=registry.name(member)
    main,latin=(name.split('（*',1)[0],name.split('（*',1)[1].removesuffix('*）')) if '（*' in name else (name,'')
    explanation=member['one_liner_display'] if section=='helpful' else member['watch_note']
    note=member.get('panel_note','').replace('见第4章','请看第4章')
    if note and note not in explanation:explanation=(explanation+' ' if explanation else '')+note
    badge=member['evidence_badge'] if section=='helpful' else member['watch_badge']
    badges=([badge] if badge else [])+(['检出可靠度：'+member['reliability']['label']] if member.get('reliability') else [])
    return main+'  '+pct(member['value']),latin,explanation,'；'.join(badges)


def draw_cards(document,cards,registry,width=1800):
    from .word_figures import _font,_wrap,_text,draw_tier_scale
    from .consumer_chapter import _latin
    gap=30;card_width=(width-gap*3)//2;inside=card_width-48
    scratch=ImageDraw.Draw(Image.new('RGB',(width,10),'white'))
    layouts=[]
    for card in cards:
        parts=[('text',card['display_name'],36,'#205D63')]
        if card['status']=='not_detected':
            parts.append(('text','本次未检出',36,'#53666C'))
            if card['absence_note']:parts.append(('text',card['absence_note'],32,'#46565B'))
        else:
            if card['explanation']:parts.append(('text',card['explanation'],32,'#46565B'))
            parts.append(('text','合计占比 '+pct(card['total']),36,'#205D63'))
            if card.get('reference'):
                ref=card['reference'];bar=draw_tier_scale([{'value':ref['value'],'percentile':ref['percentile'],
                    'tier_label':card['tier'],'color':card['color'],'borderline':ref.get('borderline',False)}],inside,compact=True)
                parts.append(('image',bar,0,''))
            for member in card['members']:
                title,latin,explanation,badges=_member_lines(member,card['section'],registry)
                parts.append(('text',title,34,'#253E45'))
                if latin:parts.append(('latin',latin,26,'#657279'))
                if explanation:parts.append(('text',explanation,31,'#344B50'))
                if badges:parts.append(('text',badges,29,'#62787B'))
        measured=[];height=28
        for kind,value,size,color in parts:
            if kind=='image':needed=value.height
            elif kind=='latin':needed=36
            else:needed=len(_wrap(scratch,value,_font(size),inside,100))*size*1.25
            measured.append((kind,value,size,color,height,needed));height+=needed+12
        layouts.append((card,measured,int(height+20)))
    row_heights=[max(layout[2] for layout in layouts[index:index+2]) for index in range(0,len(layouts),2)]
    image=Image.new('RGB',(width,sum(row_heights)+gap*(len(row_heights)+1)),'white');draw=ImageDraw.Draw(image)
    for index,(card,parts,_) in enumerate(layouts):
        x=gap+(index%2)*(card_width+gap);y=gap+sum(row_heights[:index//2])+gap*(index//2)
        height=row_heights[index//2]
        draw.rounded_rectangle((x,y,x+card_width,y+height),radius=20,fill='#F0F7F5' if card['section']=='helpful' else '#F3F6F7',outline='#CADDD8',width=2)
        for kind,value,size,color,offset,needed in parts:
            if kind=='image':image.paste(value,(x+24,int(y+offset)))
            elif kind=='latin':_latin(draw,(x+24,y+offset),value,size,inside)
            else:_text(draw,(x+24,y+offset),value,_font(size),fill=color,width=inside,max_lines=100)
    return image


def _registry(document):
    registry=NameRegistry(document)
    registry.seen.update(consumer(document).get('names_seen', []))
    first=document.get('consumer',{}).get('chapters',{}).get('1',{})
    registry.mark([row for kind in ('phyla','genera','species','reference_rows') for row in first.get(kind,[])])
    return registry


def render_figures(document,output,manifest):
    data=prepare(document);figures={};registry=_registry(document)
    for sub,section in [(1,'helpful'),(2,'watch')]:
        cards=[card for card in data['cards'] if card['section']==section]
        if not cards:continue
        image=draw_cards(document,cards,registry);buffer=io.BytesIO();image.save(buffer,format='PNG',optimize=True);raw=buffer.getvalue()
        filename=f"{document['sample_id']}_consumer_3_{sub}_cards_{hashlib.sha256(raw).hexdigest()[:16]}.png"
        (Path(output)/filename).write_bytes(raw);key=f'3.cards.{section}'
        manifest[key]={'filename':filename,'width':image.width,'height':image.height,'cards':copy.deepcopy(cards),'mode':'consumer_key_taxa'}
        figures[key]=filename
    return figures


def render(document):
    from .consumer_copy import CHAPTERS,EMPTY_SECTION
    from .consumer_basis import comparison_basis_note
    from .knowledge_graph import subsection_graph_markdown
    from .consumer_state import table
    data=prepare(document);text=CHAPTERS[3];out=['## 3 '+text['title'],text['intro']]
    labels={'opportunists':'条件致病菌','butyrate_producers':'产丁酸菌','detection_reliability':'检出可靠度','research_evidence_strength':'研究证据强度'}
    for key,label in labels.items():
        if data['definitions'][key]:out.append('> '+label+'：'+data['definitions'][key])
    registry=_registry(document)
    for sub,section in [(1,'helpful'),(2,'watch')]:
        out.append(f"### 3.{sub} "+text['subsections'][sub]);cards=[card for card in data['cards'] if card['section']==section]
        figure=document.get('word_figures',{}).get('3.cards.'+section)
        if cards and figure:out.append('![重点菌卡片]('+figure['filename']+')')
        elif cards:
            for card in cards:
                out.append('**'+card['display_name']+'**')
                if card['status']=='not_detected':out.append('本次未检出。'+card['absence_note']);continue
                out.append(card['explanation']);out.append('合计占比 '+pct(card['total'])+('；'+card['tier']+'，'+card['percentile_phrase'] if card.get('reference') else '')+'。')
                out.append(table(['菌名','占比','说明'],[[registry.name(member),pct(member['value']),member['one_liner_display'] if section=='helpful' else member['watch_note'] or member['panel_note'].replace('见第4章','请看第4章')] for member in card['members']]))
        else:out.append(EMPTY_SECTION)
        if sub==1:
            note=comparison_basis_note(document,3)
            if note:out.append('> '+note)
        if sub==2 and data['show_diarrhea_warning']:out.append(WARNING)
        summary=interpretation(document,sub)
        if summary:out.append(summary)
        out.extend(subsection_graph_markdown(document,3,sub,graph_seeds(document,sub)))
    return [line for line in out if line]


def appendix(document):
    from .document import table
    from .chapter_three import reference_for
    data=prepare(document);out=['#### 重点菌明细']
    rows=[]
    for card in data['cards']:
        ref=card.get('reference') or {}
        rows.append([card['display_name'],'类别合计',str(card['total']),str(ref.get('value','')),str(ref.get('percentile','')),str(ref.get('n_reference','')),card['status']])
        for member in card['members']:
            individual=reference_for(document,member) or {}
            rows.append([card['display_name'],member['species'],str(member['value']),str(individual.get('value','')),str(individual.get('percentile','')),str(individual.get('n_reference','')),
                         str(member.get('reliability') or '')])
    out.append(table(['类别','对象','主分析占比%','独立比较占比%','参考百分位','参考人数','状态/可靠度'],rows))
    out.append('未检出只在质控明确通过、taxonomy.complete为True且所有面板成员均不在完整谱中时发布。分类方法的数值检测下限若没有随输入给出，不补造阈值；未检出不等于绝对不存在。')
    out.append('本样本若需检出可靠度徽标，后续流程需开启MetaPhlAn rel_ab_w_read_stats的估算读段字段；本次未重跑MetaPhlAn。')
    out.append('重点菌面板版本：'+data['panel_version']+'；SHA256：'+data['panel_sha256']+'。')
    out.append('#### 检出与证据明细')
    for sub in (1,2,3):
        raw=data['raw_legacy_tables'][str(sub)];out.append(table(raw['headers'],raw['rows']))
        if raw.get('note'):out.append(raw['note'])
    return out
