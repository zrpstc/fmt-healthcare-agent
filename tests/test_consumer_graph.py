from __future__ import annotations

from wgs_agent.consumer_web.graph import GraphBuilder, ReferenceIndex


def test_graph_filter_removes_study_groups_probes_and_non_chinese_labels():
    document = {
        "references": {"matched_docs": []},
        "module_bibliographies": [],
        "sections": [
            {
                "id": "composition",
                "title": "composition",
                "topics": [
                    {
                        "id": "composition.phyla",
                        "status": "available",
                        "knowledge_subgraph": {
                            "display_status": "ready",
                            "nodes": [
                                {"id": "a", "label": "Firmicutes", "display_label": "厚壁菌门", "type": "MicrobialTaxon"},
                                {"id": "b", "label": "Eubacterium rectale", "display_label": "直肠真杆菌", "type": "MicrobialTaxon"},
                                {"id": "f", "label": "butyrate", "display_label": "丁酸", "type": "Metabolite"},
                                {"id": "c", "label": "study group", "display_label": "研究分组", "type": "StudyGroup"},
                                {"id": "d", "label": "probe D", "display_label": "探针丁", "type": "Other"},
                                {"id": "e", "label": "English only", "type": "MicrobialTaxon"},
                            ],
                            "edges": [
                                {"id": "e1", "source": "b", "target": "a", "predicate": "SUBCLASS_OF", "display_label": "是子类", "evidence_text": "Eubacterium rectale is a Firmicutes.", "claim_id": "c1", "review_status": "reviewed"},
                                {"id": "e2", "source": "b", "target": "c", "predicate": "ASSOCIATED_WITH", "display_label": "相关", "evidence_text": "group association", "claim_id": "c2"},
                                {"id": "e3", "source": "d", "target": "a", "predicate": "TARGETS", "display_label": "靶向", "evidence_text": "probe targets", "claim_id": "c3"},
                                {"id": "e4", "source": "b", "target": "f", "predicate": "PRODUCES", "display_label": "产生", "evidence_text": "Eubacterium rectale produces butyrate.", "claim_id": "c4", "review_status": "approved"},
                            ],
                        },
                    }
                ],
            }
        ],
    }
    refs = ReferenceIndex(document)
    graph, topics = GraphBuilder(document, refs).choose(["composition.phyla"], ["厚壁菌门", "Firmicutes"])
    assert graph is not None
    assert topics == ["composition.phyla"]
    labels = {node.label for node in graph.nodes}
    assert "研究分组" not in labels
    assert "探针丁" not in labels
    assert "English only" not in labels
    assert all(edge.label not in {"靶向", "位于"} for edge in graph.edges)
    assert len(graph.edges) >= 2
    assert graph.edges[0].status in {"approved", "pending"}


def _topic(topic_id: str, nodes: list[dict], edges: list[dict]) -> dict:
    return {"id": topic_id, "status": "available", "knowledge_subgraph": {"display_status": "ready", "nodes": nodes, "edges": edges}}


def _doc(*topics: dict) -> dict:
    return {
        "references": {"matched_docs": []},
        "module_bibliographies": [],
        "sections": [{"id": "s", "title": "s", "topics": list(topics)}],
    }


def test_merged_topics_get_unique_edge_ids():
    # Professional-report topic graphs number edges per topic (e1, e2...), so a
    # merged consumer graph used to repeat ids and the browser drew nothing.
    nodes = [
        {"id": "n_fp", "label": "Faecalibacterium prausnitzii", "display_label": "普拉梭菌", "type": "MicrobialTaxon"},
        {"id": "n_but", "label": "butyrate", "display_label": "丁酸", "type": "Metabolite"},
        {"id": "n_fib", "label": "fiber", "display_label": "膳食纤维", "type": "DietaryComponent"},
        {"id": "n_ibd", "label": "IBD", "display_label": "炎症性肠病", "type": "Disease"},
    ]
    first = _topic("t.a", nodes[:3], [
        {"id": "e1", "source": "n_fp", "target": "n_but", "predicate": "PRODUCES", "evidence_text": "x", "claim_id": "c1"},
        {"id": "e2", "source": "n_fp", "target": "n_fib", "predicate": "UTILIZES", "evidence_text": "y", "claim_id": "c2"},
    ])
    second = _topic("t.b", [nodes[0], nodes[1], nodes[3]], [
        {"id": "e1", "source": "n_fp", "target": "n_ibd", "predicate": "DEPLETED_IN", "evidence_text": "z", "claim_id": "c3"},
        {"id": "e2", "source": "n_but", "target": "n_ibd", "predicate": "ASSOCIATED_WITH", "evidence_text": "w", "claim_id": "c4"},
    ])
    document = _doc(first, second)
    graph, topics = GraphBuilder(document, ReferenceIndex(document)).choose(["t.a", "t.b"], ["普拉梭菌"])
    assert graph is not None and topics == ["t.a", "t.b"]
    ids = [edge.id for edge in graph.edges]
    assert len(ids) == 4
    assert len(set(ids)) == len(ids)
    node_ids = {node.id for node in graph.nodes}
    assert all(edge.from_ in node_ids and edge.to in node_ids for edge in graph.edges)


def test_latin_only_taxon_nodes_use_known_chinese_names():
    # Graph translation sometimes leaves taxa in Latin; a known exact Chinese
    # name keeps those relations instead of emptying the subgraph.
    document = _doc(_topic("t.a", [
        {"id": "n1", "label": "Faecalibacterium prausnitzii", "type": "MicrobialTaxon"},
        {"id": "n2", "label": "Bacteroides", "type": "MicrobialTaxon"},
        {"id": "n3", "label": "butyrate", "display_label": "丁酸", "type": "Metabolite"},
        {"id": "n4", "label": "Some unnamed bug", "type": "MicrobialTaxon"},
    ], [
        {"id": "e1", "source": "n1", "target": "n3", "predicate": "PRODUCES", "evidence_text": "x", "claim_id": "c1"},
        {"id": "e2", "source": "n2", "target": "n3", "predicate": "PRODUCES", "evidence_text": "y", "claim_id": "c2"},
        {"id": "e3", "source": "n4", "target": "n3", "predicate": "PRODUCES", "evidence_text": "z", "claim_id": "c3"},
    ]))
    graph, _ = GraphBuilder(document, ReferenceIndex(document)).choose(["t.a"], ["丁酸"])
    assert graph is not None
    labels = {node.label for node in graph.nodes}
    assert {"普拉梭菌", "拟杆菌属", "丁酸"} <= labels
    assert not any("unnamed" in label for label in labels)
    assert len(graph.edges) == 2
