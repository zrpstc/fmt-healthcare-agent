"""Consumption of a complete KB; these selections do not change acquired data."""
import json
import re
from .knowledge_settings import eligible_for_use

def tokens(text):
    stop = {'the', 'and', 'for', 'with', 'what', 'which', 'does', 'how', 'are', 'from'}
    return set(re.findall(r'[a-z0-9_-]{2,}|[\u3400-\u9fff]', str(text).casefold())) - stop

def select_evidence(snapshot, question, limit, config):
    from .litkg_retrieval import pack_evidence
    words = tokens(question)
    candidates = []
    for row in snapshot['facts']:
        if not eligible_for_use(row):
            continue
        text = json.dumps([row.get('participants'), row.get('predicate'), row.get('qualifiers'), row.get('evidence')], ensure_ascii=False)
        score = len(words & tokens(text))
        if score:
            candidates.append((score, row))
    candidates.sort(key=lambda pair: (-pair[0], str(pair[1]['id'])))
    facts, citations = [], []
    for _, row in candidates:
        facts.append({key: row[key] for key in ('id', 'predicate', 'participants', 'qualifiers', 'negated', 'speculative', 'semantic_status', 'review_status', 'audit_pending') if key in row})
        for index, evidence in enumerate(row.get('evidence') or []):
            text = evidence.get('sentence')
            if not isinstance(text, str) or not text.strip():
                continue
            citations.append({**{key: row.get(key) for key in ('document_id', 'claim_id', 'chunk_id', 'filename', 'title', 'doi')},
                **evidence, 'id': f"full-{row['id']}-{index}", 'fact_id': row['id'], 'evidence_text': text})
    result = pack_evidence({'knowledge_base_id': config.knowledge_base_id, 'facts': facts, 'citations': citations,
        'warnings': [], 'retrieval': 'full-kb-local-ranking'}, question, limit, config, extra={
            'acquisition': {key: snapshot[key] for key in ('acquisition_scope', 'complete', 'counts', 'acquired_at')},
            'usage_policy': {'selection': 'query-ranked', 'max_results': limit, 'review_policy': 'WGS_KNOWLEDGE_USAGE_INCLUDE_PENDING'}})
    return result
