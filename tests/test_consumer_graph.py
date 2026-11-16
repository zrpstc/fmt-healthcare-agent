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
