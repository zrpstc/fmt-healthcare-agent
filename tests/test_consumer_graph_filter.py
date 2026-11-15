import copy
import pytest
from wgs_agent.reporting.consumer_graph import consumer_graph_filter


def graph(nodes, pairs):
    values = [{'id':str(i), 'label':label, 'display_label':label, 'type':kind, 'display_type':kind}
              for i, (label,kind) in enumerate(nodes)]
    edges = [{'id':str(i),'source':str(a),'target':str(b),'subject':nodes[a][0],'object':nodes[b][0],
              'predicate':pred,'display_label':pred,'claim_id':str(i),'evidence_id':'K'+str(i),'confidence':.9}
             for i,(a,b,pred) in enumerate(pairs)]
    return {'nodes':values,'edges':edges,'display_status':'ready','body_presentation':True}


def test_filter_removes_groups_identifiers_structure_and_floating_components_without_mutation():
    raw=graph([('普拉梭菌','MicrobialTaxon'),('丁酸','Compound'),('乙酸','Compound'),
               ('研究甲组','StudyGroup'),('双歧杆菌探针一六四','Other'),('RiCBM23','Protein'),
               ('浮动菌','MicrobialTaxon'),('硫化氢','Compound')],
              [(0,1,'PRODUCES'),(0,2,'CONSUMES'),(0,3,'DIFFERS_BETWEEN'),(0,4,'TARGETS'),
               (0,5,'LOCATED_IN'),(6,7,'PRODUCES')])
    before=copy.deepcopy(raw);clean=consumer_graph_filter(raw,['普拉梭菌'])
    assert raw==before and len(clean['nodes'])==3 and len(clean['edges'])==2
    assert clean['display_status']=='ready'
    reasons=clean['filter_audit']['removed_reasons']
    assert reasons['study_group_nodes']==1 and reasons['identifier_nodes']==2
    assert reasons['structural_edges']==2 and reasons['unseeded_component_edges']==1
    assert {e['claim_id'] for e in clean['edges']} <= {e['claim_id'] for e in raw['edges']}


def test_other_nodes_beyond_one_hop_are_removed_and_sparse_graph_is_hidden():
    raw=graph([('种子菌','MicrobialTaxon'),('产物','Compound'),('未知实体','Other')],[(0,1,'PRODUCES'),(1,2,'AFFECTS')])
    clean=consumer_graph_filter(raw,['种子菌'])
    assert clean['filter_audit']['removed_reasons']['distant_other_nodes']==1
    assert clean['display_status']=='too_sparse' and len(clean['edges'])==1


def test_only_two_seeded_components_and_no_genus_to_species_inference():
    raw=graph([('甲菌','MicrobialTaxon'),('甲物质','Compound'),('乙菌','MicrobialTaxon'),('乙物质','Compound'),
               ('丙菌','MicrobialTaxon'),('丙物质','Compound')],[(0,1,'PRODUCES'),(2,3,'PRODUCES'),(4,5,'PRODUCES')])
    clean=consumer_graph_filter(raw,['甲菌','乙菌','丙菌'])
    assert len(clean['edges'])==2 and clean['filter_audit']['components']==2
    raw['nodes'][0]['label']='Roseburia';raw['nodes'][0]['display_label']='罗氏菌属'
    assert consumer_graph_filter(raw,['Roseburia hominis'])['display_status']=='too_sparse'


def test_pending_style_and_caption_are_consumer_specific(tmp_path,monkeypatch):
    from wgs_agent.reporting import knowledge_graph as kg
    from wgs_agent.reporting.graph_visual import property_caption,render_graph_figures
    raw=graph([('种子菌','MicrobialTaxon'),('丁酸','Compound'),('乙酸','Compound')],[(0,1,'PRODUCES'),(0,2,'CONSUMES')])
    for e in raw['edges']:e['display_label']='产生';e['review_status']='approved'
    raw['edges'][0]['review_status']='pending'
    clean=consumer_graph_filter(raw,['种子菌'])
    monkeypatch.setattr(kg,'prepare_subsection_graphs',lambda doc:None)
    doc={'sample_id':'G13_TEST','sections':[{'topics':[{'id':'test','title':'研究背景','knowledge_subgraph':clean}]}]}
    render_graph_figures(doc,tmp_path)
    assert clean['visual_style']['edge_line_styles']=={'0':'dashed','1':'solid'}
    assert '待审核' in property_caption(raw['edges'][0])
    assert '待审核' not in property_caption(raw['edges'][0],show_review=False)
    boxes=list(clean['visual_style']['body_node_boxes'].values())
    for label in clean['visual_style']['body_relation_boxes']:
        assert all(not(label[0]<box[2] and label[2]>box[0] and label[1]<box[3] and label[3]>box[1]) for box in boxes)
    legend=clean['visual_style']['body_pending_legend_box']
    assert 0 <= legend[1] < legend[3] < clean['visual_style']['canvas_height']


def test_untranslated_noise_is_removed_before_chinese_gate_and_sparse_omission_has_no_placeholder():
    from test_consumer_inline_subgraphs import graph_document
    from wgs_agent.reporting.knowledge_graph import subsection_graph,subsection_graph_markdown
    doc=graph_document({'composition.species':[(1,'种子菌','丁酸',.9),(2,'种子菌','乙酸',.9),(3,'种子菌','RiCBM23',.9)]})
    topic=doc['sections'][0]['topics'][0]
    for node in topic['knowledge_subgraph']['nodes']:
        if node['label']=='RiCBM23':node['display_label']='RiCBM23'
    raw=copy.deepcopy(topic['knowledge_subgraph'])
    clean=subsection_graph(doc,1,1,['种子菌'])
    assert len(clean['edges'])==2 and clean['filter_audit']['removed_reasons']['identifier_nodes']==1
    assert topic['knowledge_subgraph']==raw
    topic['allowed_narrative_ids']=['K1']
    topic['knowledge_subgraph']['edges']=topic['knowledge_subgraph']['edges'][:1]
    assert subsection_graph_markdown(doc,1,1,['种子菌'])==[]
    assert doc['consumer_omissions'][-1]['reason_code']=='subgraph_too_sparse'


def test_self_loop_labels_are_included_in_consumer_collision_check(tmp_path,monkeypatch):
    from wgs_agent.reporting import knowledge_graph as kg
    from wgs_agent.reporting.graph_visual import render_graph_figures
    raw=graph([('种子菌','MicrobialTaxon'),('丁酸','Compound')],[(0,0,'ASSOCIATED_WITH'),(0,1,'PRODUCES')])
    for edge in raw['edges']:edge.update(display_label='关联',display_attributes='观察研究',review_status='pending')
    clean=consumer_graph_filter(raw,['种子菌'])
    monkeypatch.setattr(kg,'prepare_subsection_graphs',lambda doc:None)
    doc={'sample_id':'SELF_LOOP_TEST','sections':[{'topics':[{'id':'test','title':'研究背景','knowledge_subgraph':clean}]}]}
    render_graph_figures(doc,tmp_path)
    style=clean['visual_style'];assert len(style['body_relation_boxes'])==2
    for label in style['body_relation_boxes']:
        assert all(not(label[0]<box[2] and label[2]>box[0] and label[1]<box[3] and label[3]>box[1]) for box in style['body_node_boxes'].values())
