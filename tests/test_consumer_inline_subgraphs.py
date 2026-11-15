"""One bounded, evidence-faithful Chinese subgraph per consumer subsection."""
import copy
import re

import pytest

from wgs_agent.reporting import knowledge_graph as kg
from wgs_agent.reporting.consumer_copy import GRAPH_TOPICS


def graph_document(topic_claims):
    doc = {"sample_id": "INLINE_TEST", "sections": [{"topics": []}], "evidence": {}, "consumer": {}}
    for tid, claims in topic_claims.items():
        topic = {"id": tid, "title": "研究背景", "status": "available", "evidence_ids": [],
                 "allowed_narrative_ids": [], "narrative_evidence_ids": []}
        for number, subject, target, confidence in claims:
            key = f"K{number}"
            row = doc["evidence"].setdefault(key, {"kind": "literature", "claim_id": f"claim:{number}",
                "subject": subject, "object": target, "predicate": "ASSOCIATED_WITH", "topic_ids": [],
                "subject_type": "MicrobialTaxon", "object_type": "Compound",
                "evidence_text": "An attributable, already bound study claim.", "confidence": confidence})
            row["topic_ids"].append(tid)
            topic["allowed_narrative_ids"].append(key)
        doc["sections"][0]["topics"].append(topic)
    for topic in doc["sections"][0]["topics"]:
        graph = kg.build_topic_graph(doc, topic)
        for node in graph["nodes"]:
            node.update(display_label=node["label"] if re.search(r"[\u4e00-\u9fff]", node["label"]) else "研究实体" + node["id"][-2:].translate(str.maketrans('abcdef', '甲乙丙丁戊己')),
                        display_type="菌群" if node["type"] == "MicrobialTaxon" else "物质")
        for edge in graph["edges"]:
            edge.update(display_label="关联", display_attributes="")
        graph["display_status"] = "ready"
        topic["knowledge_subgraph"] = graph
    return doc


def test_extra_topic_mapping_uses_existing_keyword_catalog():
    assert GRAPH_TOPICS[1, 4] == ("composition.species", "composition.dominance")
    assert set(GRAPH_TOPICS[2, 3]) == {"metabolites.scfa", "nutrient_metabolism.fiber", "metabolites.intermediates"}
    assert all(tid in kg.TOPIC_KEYWORDS for tid in GRAPH_TOPICS[2, 3])
    assert "butyrate" in kg.TOPIC_KEYWORDS["metabolites.scfa"]
    assert "纤维" in kg.TOPIC_KEYWORDS["nutrient_metabolism.fiber"]
    assert "lactate" in kg.TOPIC_KEYWORDS["metabolites.intermediates"]


def test_seed_bonus_changes_bounded_edge_selection_without_changing_evidence():
    rows = [(i, "背景菌" + str(i), "背景物质" + str(i), .99) for i in range(1, 7)]
    doc = graph_document({"composition.species": rows})
    topic = doc["sections"][0]["topics"][0]
    # The extra bound claim is deliberately beyond the old topic's six-edge cap.
    doc["evidence"]["K7"] = {**doc["evidence"]["K1"], "claim_id": "claim:7", "subject": "展示菌", "object": "丁酸", "confidence": .5}
    topic["allowed_narrative_ids"].append("K7")
    raw = copy.deepcopy(doc["evidence"])
    graph = kg.build_topic_graph(doc, topic, max_nodes=8, max_edges=6, seeds=["展示菌", "丁酸"])
    assert graph["edges"][0]["claim_id"] == "claim:7"
    assert len(graph["nodes"]) <= 8 and len(graph["edges"]) <= 6
    assert doc["evidence"] == raw
    topic["allowed_narrative_ids"].remove("K7")
    assert "claim:7" not in {e["claim_id"] for e in kg.build_topic_graph(doc, topic, seeds=["展示菌"])["edges"]}


def test_merge_uses_union_of_allowed_claims_and_preserves_original_graphs():
    doc = graph_document({"composition.species": [(1, "展示菌", "丁酸", .8)],
                          "composition.dominance": [(2, "其他菌", "乳酸", .9)]})
    original = copy.deepcopy(doc["sections"])
    graph = kg.subsection_graph(doc, 1, 4, ["展示菌"])
    assert {e["claim_id"] for e in graph["edges"]} == {"claim:1", "claim:2"}
    assert doc["consumer"]["subsection_graphs"]["1.4"]["selected_source"] == "merged"
    assert doc["sections"] == original
    assert graph["edges"][0]["subject"] == "展示菌"
    assert kg.subsection_graph(doc, 1, 4, ["展示菌"])["signature"] == graph["signature"]


def test_ready_gate_and_chinese_gate_and_no_placeholder():
    doc = graph_document({"composition.species": [(1, "展示菌", "丁酸", .8)]})
    topic = doc["sections"][0]["topics"][0]
    topic["knowledge_subgraph"]["display_status"] = "unavailable"
    assert kg.subsection_graph_markdown(doc, 1, 1, ["展示菌"]) == []
    assert doc["consumer_omissions"][-1]["reason_code"] == "no_ready_subgraph"
    topic["knowledge_subgraph"]["display_status"] = "ready"
    topic["knowledge_subgraph"]["nodes"][0]["display_label"] = "Unknown English taxon"
    assert kg.subsection_graph(doc, 1, 1, ["展示菌"]) is None
    assert "未匹配" not in "\n".join(kg.subsection_graph_markdown(doc, 1, 1, []))


def test_duplicate_merged_graph_chooses_next_candidate_then_omits():
    doc = graph_document({"composition.phyla": [(1, "甲菌", "丁酸", .8)],
                          "composition.genera": [(2, "乙菌", "乳酸", .9)],
                          "composition.species": [(1, "甲菌", "丁酸", .8)],
                          "composition.dominance": [(2, "乙菌", "乳酸", .9)]})
    first = kg.subsection_graph(doc, 1, 1, ["甲菌"])
    second = kg.subsection_graph(doc, 1, 2, ["乙菌"])
    third = kg.subsection_graph(doc, 1, 4, ["甲菌"])
    assert len({g["signature"] for g in [first, second, third]}) == 3
    assert doc["consumer"]["subsection_graphs"]["1.4"]["selected_source"] == "composition.species"
    # A later section with only an already used graph has no replacement.
    doc["sections"][0]["topics"] = [doc["sections"][0]["topics"][-1]]
    assert kg.subsection_graph(doc, 1, 4, ["乙菌"]) is None


def test_adjacent_chapters_do_not_repeat_the_same_graph():
    doc = graph_document({"composition.species": [(1, "甲菌", "丁酸", .8)],
                          "diversity.richness": [(1, "甲菌", "丁酸", .8)]})
    assert kg.subsection_graph(doc, 1, 4, ["甲菌"])
    assert kg.subsection_graph(doc, 2, 1, ["甲菌"]) is None


def test_genus_endpoint_does_not_count_as_displayed_species():
    assert kg._seed_matches({'subject': 'Roseburia', 'object': 'butyrate'}, ['Roseburia hominis']) == []


def test_existing_analyte_names_rescue_seed_weighted_merged_claims():
    doc = graph_document({'composition.species': [(1, '展示菌', 'acetylcholine', .9)]})
    topic = doc['sections'][0]['topics'][0]
    for node in topic['knowledge_subgraph']['nodes']:
        if node['label'] == 'acetylcholine':
            node['display_label'] = 'acetylcholine'
    graph = kg.subsection_graph(doc, 1, 1, ['展示菌'])
    assert graph and any(n['display_label'] == '乙酰胆碱' for n in graph['nodes'])
    assert doc['consumer']['subsection_graphs']['1.1']['selected_source'] == 'merged'


def test_new_consumer_chapter_automatically_uses_shared_subsection_outlet(tmp_path, monkeypatch):
    from wgs_agent.reporting import consumer_copy
    from wgs_agent.reporting.document import render_markdown
    from wgs_agent.reporting.graph_labels import translate_graph_labels
    from wgs_agent.reporting.graph_visual import render_graph_figures
    from test_report_knowledge_graph import document, claim
    monkeypatch.setattr(consumer_copy, 'CONSUMER_CHAPTERS', {1, 2, 3})
    doc = document([claim()])
    translate_graph_labels(doc, None)
    render_graph_figures(doc, tmp_path)
    md = render_markdown(doc)
    # Chapter three uses the ordinary Word renderer, without a new chapter hook.
    section = re.split(r'\n#{2,3} ', md.split('### 3.1 ', 1)[1], maxsplit=1)[0]
    assert section.count('![图 3-1k  与本节相关的研究知识]') == 1


def test_fallback_ranks_seed_hit_edges_before_edge_count_and_confidence(monkeypatch):
    doc = graph_document({"metabolites.scfa": [(1, "展示菌", "丁酸", .5)],
                          "metabolites.intermediates": [(2, "甲菌", "乳酸", .99), (3, "乙菌", "乳酸", .99)]})
    monkeypatch.setattr(kg, "_display_from_candidates", lambda *a: None)
    graph = kg.subsection_graph(doc, 2, 3, ["展示菌"])
    assert graph["edges"][0]["claim_id"] == "claim:1"
    assert doc["consumer"]["subsection_graphs"]["2.3"]["selected_source"] == "metabolites.scfa"


def test_body_node_setting_does_not_limit_topic_json(monkeypatch):
    doc = graph_document({"composition.species": [(i, "菌" + str(i), "物质" + str(i), .9) for i in range(1, 7)]})
    original = copy.deepcopy(doc["sections"][0]["topics"][0]["knowledge_subgraph"])
    monkeypatch.setenv("WGS_REPORT_GRAPH_BODY_MAX_NODES", "4")
    graph = kg.subsection_graph(doc, 1, 1, ["菌1"])
    assert len(graph["nodes"]) <= 4
    assert doc["sections"][0]["topics"][0]["knowledge_subgraph"] == original
    assert len(original["nodes"]) == 12


def test_inline_placement_first_note_once_and_repeat_render_is_stable(tmp_path):
    from test_chapter_one import build
    from wgs_agent.reporting.document import render_markdown
    from wgs_agent.reporting.graph_visual import render_graph_figures
    from wgs_agent.reporting.glossary import Glossary
    doc = build(healthy=True)
    fixture = graph_document({"composition.species": [(1, "展示菌", "丁酸", .8)],
                              "composition.dominance": [(2, "优势菌", "乳酸", .9)],
                              "diversity.richness": [(3, "多样性", "研究结果", .8)],
                              "diversity.reference": [(4, "菌群组成", "健康人群", .8)],
                              "metabolites.scfa": [(5, "参与菌", "丁酸", .8)]})
    by_id = {t["id"]: t for t in fixture["sections"][0]["topics"]}
    doc["evidence"].update(fixture["evidence"])
    for section in doc["sections"]:
        for topic in section["topics"]:
            if topic["id"] in by_id:
                topic.update(by_id[topic["id"]])
    # Keep synthetic translated graphs through render_markdown's idempotent attach.
    for section in doc["sections"]:
        for topic in section["topics"]:
            graph = topic.get("knowledge_subgraph", {})
            if topic["id"] in by_id:
                raw = kg.build_topic_graph(doc, topic)
                import hashlib, json
                graph["source_signature"] = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    render_graph_figures(doc, tmp_path)
    md = render_markdown(doc)
    for key, record in doc["consumer"]["subsection_graphs"].items():
        if not record["graph"]:
            continue
        section = re.split(r"\n#{2,3} ", md.split("### " + key + " ", 1)[1], maxsplit=1)[0]
        assert section.count("_consumer_" + key.replace('.', '_') + "_kg_") == 1
        assert section.rfind("与本节相关的研究知识") > section.find("\n")
    assert "### 1.3 " not in md and "consumer_1_3_kg" not in md
    note = Glossary({}).get("knowledge_subgraph", kind="concept")["detail"]
    assert md.count(note) == 1
    assert render_markdown(doc) == md
    for record in doc["consumer"]["subsection_graphs"].values():
        if record.get("graph"):
            style = record["graph"]["visual_style"]
            assert style["body_min_node_font_px"] * 480 / style["canvas_width"] >= 9
            boxes = list(style['body_node_boxes'].values())
            def overlap(a, b):
                return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]
            assert all(not overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:])
            assert all(not overlap(label, node) for label in style['body_relation_boxes'] for node in boxes)
