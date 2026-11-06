import os
import unittest
from unittest.mock import patch
from wgs_agent.reporting.knowledge_graph import build_topic_graph
from wgs_fmt_platform.knowledge.knowledge_settings import eligible_for_use


class PendingKnowledgeVisibilityTests(unittest.TestCase):
    def test_pending_is_visible_by_default_and_strict_mode_is_available(self):
        row = {'semantic_status': 'pending', 'review_status': 'pending', 'audit_pending': True}
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(eligible_for_use(row))
        with patch.dict(os.environ, {'WGS_KNOWLEDGE_USAGE_INCLUDE_PENDING': 'false'}):
            self.assertFalse(eligible_for_use(row))

    def test_cited_claim_does_not_hide_other_related_pending_claims(self):
        def record(claim_id):
            return {'kind': 'literature', 'claim_id': claim_id, 'knowledge_base_id': 30,
                    'subject': 'Bacteroides', 'predicate': 'PRODUCES', 'object': 'acetate',
                    'evidence_text': 'Bacteroides produces acetate.', 'topic_ids': ['composition.genera'],
                    'review_status': 'pending', 'confidence': 0.8}
        document = {'evidence': {'K1': record('claim-1'), 'K2': record('claim-2')}}
        topic = {'id': 'composition.genera', 'status': 'ready', 'evidence_ids': [],
                 'allowed_narrative_ids': ['K1', 'K2'], 'narrative_evidence_ids': ['K1']}
        graph = build_topic_graph(document, topic)
        self.assertEqual(len(graph['edges']), 2)
        self.assertEqual(graph['edges'][0]['claim_id'], 'claim-1')
        self.assertTrue(all(edge['review_status'] == 'pending' for edge in graph['edges']))
        self.assertFalse(graph['truncated'])
        from wgs_agent.reporting.graph_visual import property_caption
        self.assertIn('待审核', property_caption(graph['edges'][0]))


if __name__ == '__main__':
    unittest.main()
