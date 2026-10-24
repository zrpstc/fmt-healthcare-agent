"""Read-only, KB-scoped GraphRAG over LitKG's native relations and complete facts."""
from __future__ import annotations

import asyncio
import copy
import json
import re
import time
from dataclasses import replace
from typing import Any

import httpx

from wgs_fmt_platform.knowledge.litkg_retrieval import (
    LitkgRetrievalConfig, LitkgRetrievalError, retrieve_litkg,
)


class GraphRAGError(LitkgRetrievalError):
    pass


def _key(value: Any) -> str:
    return str(value).strip().casefold()


def _tokens(value: str) -> set[str]:
    stop = {'what', 'which', 'with', 'from', 'this', 'that', 'does', 'have', 'could', 'would', 'why', 'and', 'the', 'for', 'are'}
    return {word for word in re.findall(r'[a-z0-9]{3,}', value.casefold()) if word not in stop}


def resolve_entities(seed: dict, rows: list[dict]) -> dict:
    """Exact names/aliases/identifiers are accepted; substring hits remain candidates."""
    name = _key(seed['name'])
    matches = []
    for row in rows:
        identifiers = [_key(row.get('normalized_id') or ''), *map(_key, row.get('identifiers') or [])]
        score = 3 if name in identifiers else 2 if name == _key(row.get('canonical_name', '')) else 1 if name in map(_key, row.get('aliases') or []) else 0
        if score:
            matches.append((score, row))
    best = max((score for score, _ in matches), default=0)
    selected = [row for score, row in matches if score == best]
    return {
        'query': seed['name'], 'entity_type': seed.get('entity_type') or None,
        'status': 'resolved' if len(selected) == 1 else 'ambiguous' if selected else 'unresolved',
        'selected_ids': [row['id'] for row in selected[:2]],
        'candidates': [{k: row.get(k) for k in ('id', 'canonical_name', 'entity_type', 'normalized_id', 'identifiers', 'aliases')}
                       for row in (selected or rows)[:5]],
        'candidate_limit_reached': len(selected) > 2,
    }


class NativeGraphRetriever:
    def __init__(self, config: LitkgRetrievalConfig, *, transport=None, max_requests=24, timeout_s=90):
        self.config = config
        self.transport = transport
        self.max_requests = max_requests
        self.deadline = time.monotonic() + timeout_s
        self.requests: list[dict] = []
        self.warnings: list[str] = []
        self.failures: list[str] = []
        self.prefix = f'/knowledge-bases/{config.knowledge_base_id}'

    async def _get(self, suffix: str, params: dict) -> dict:
        if len(self.requests) >= self.max_requests or time.monotonic() >= self.deadline:
            raise GraphRAGError('GraphRAG HTTP 请求或总时间预算已用尽')
        path = self.prefix + suffix
        self.requests.append({'method': 'GET', 'path': path, 'params': params})
        try:
            response = await self.client.get(path, params=params,
                timeout=min(self.config.timeout, max(0.1, self.deadline-time.monotonic())))
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            raise GraphRAGError(f'{suffix} 返回 HTTP {exc.response.status_code}') from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise GraphRAGError(f'{suffix} 读取失败（{type(exc).__name__}）') from exc
        if not isinstance(data, dict) or ('knowledge_base_id' in data and data['knowledge_base_id'] != self.config.knowledge_base_id):
            raise GraphRAGError('LitKG 图谱响应格式错误或知识库不匹配')
        return data

    async def _resolve(self, seed):
        params = {'query': seed['name'], 'limit': 30, 'offset': 0}
        if seed.get('entity_type'):
            params['entity_type'] = seed['entity_type']
        data = await self._get('/entities', params)
        if not isinstance(data.get('entities'), list):
            raise GraphRAGError('/entities 缺少 entities 数组')
        result = resolve_entities(seed, data['entities'])
        if len(data['entities']) == 30 or result['candidate_limit_reached']:
            self.warnings.append(f"实体 {seed['name']} 的候选受到数量限制，需进一步限定类型或标识")
        return result

    async def _relations(self, entity_id):
        data = await self._get('/relations', {'entity_id': entity_id, 'direction': 'both',
            'include_negated': True, 'include_speculative': True, 'evidence_limit': 3, 'limit': 40, 'offset': 0})
        if not isinstance(data.get('relations'), list):
            raise GraphRAGError('/relations 缺少 relations 数组')
        if data.get('total', len(data['relations'])) > len(data['relations']):
            self.warnings.append(f'实体 {entity_id} 的关系只读取前 40 条，不代表已遍历全部邻居')
        return data['relations']

    async def _facts(self, pair):
        document_id, entity_id = pair
        rows = []
        for offset in (0, 50):
            data = await self._get('/facts', {'document_id':document_id, 'entity_id':entity_id, 'limit':50, 'offset':offset})
            page = data.get('facts')
            if not isinstance(page, list):
                raise GraphRAGError('/facts 缺少 facts 数组')
            for row in page:
                if not isinstance(row, dict) or row.get('document_id') != document_id:
                    raise GraphRAGError('/facts 返回了不匹配的文档')
            rows.extend(page)
            if len(page) < 50:
                break
        else:
            self.warnings.append(f'文档 {document_id} / 实体 {entity_id} 的完整事实分页达到 100 条上限')
        return rows

    async def _gather(self, tasks):
        values = await asyncio.gather(*tasks, return_exceptions=True)
        result = []
        for value in values:
            if isinstance(value, Exception):
                self.failures.append(str(value))
            else:
                result.append(value)
        return result

    async def retrieve(self, question: str, entities: list[dict], hops=2, max_results=8) -> dict:
        headers = {'Accept':'application/json'}
        if self.config.token:
            headers['Authorization'] = f'Bearer {self.config.token}'
        async with httpx.AsyncClient(base_url=self.config.base_url, headers=headers,
                                     transport=self.transport, limits=httpx.Limits(max_connections=4)) as client:
            self.client = client
            resolutions = await self._gather([self._resolve(seed) for seed in entities])
            resolved_ids = list(dict.fromkeys(entity_id for resolution in resolutions for entity_id in resolution['selected_ids']))
            roots = resolved_ids[:6]
            if len(resolved_ids)>6:
                self.warnings.append('解析实体超过 6 个起始节点上限，部分歧义候选未展开')
            if any(row['status'] == 'ambiguous' for row in resolutions):
                self.warnings.append('存在歧义实体，候选节点分别保留，未合并为一个实体')
            nodes, edges, expanded = {}, {}, set()
            for resolution in resolutions:
                for candidate in resolution['candidates']:
                    if candidate['id'] in roots:
                        nodes[candidate['id']] = {'id':candidate['id'], 'label':candidate['canonical_name'],
                            'type':candidate['entity_type'], 'normalized_id':candidate['normalized_id'],
                            'identifiers':candidate.get('identifiers') or []}
            frontier = roots
            query_words = _tokens(question)
            for depth in range(hops):
                if not frontier:
                    break
                # A native relation is a directed, sourced assertion. No edges are
                # created from participant co-occurrence or from an LLM hypothesis.
                batches = await self._gather([self._relations(value) for value in frontier])
                expanded.update(frontier)
                for batch in batches:
                    for edge in batch:
                        if not valid_relation(edge):
                            self.warnings.append('忽略缺少原生关系 ID/端点/有效证据或待审核的关系')
                            continue
                        edges[edge['id']] = edge
                        for name in ('subject', 'object'):
                            node = edge[name]
                            nodes.setdefault(node['id'], {'id':node['id'], 'label':node['text'],
                                'type':node.get('type','Unknown'), 'normalized_id':node.get('normalized_id')})
                candidates = {edge[side]['id'] for edge in edges.values() for side in ('subject','object')} - expanded
                frontier = sorted(candidates, key=lambda value: (
                    -len(query_words & _tokens(nodes[value]['label'])),
                    nodes[value].get('type') not in {'Metabolite','Disease','BiologicalProcess','Pathway','MicrobialTaxon'}, value))[:4]
                if len(candidates) > 4 and depth + 1 < hops:
                    self.warnings.append('二跳扩展最多选择 4 个相关邻居，其他分支未穷尽')
            connector_ids = connection_priority(edges, roots, hops, query_words)
            ranked = sorted(edges.values(), key=lambda edge: (
                edge['id'] not in connector_ids, connector_ids.index(edge['id']) if edge['id'] in connector_ids else 99,
                -relation_score(edge, query_words, set(roots))))[:max_results*3]
            pairs = list(dict.fromkeys((sample['document_id'], edge['subject']['id'])
                for edge in ranked for sample in edge.get('evidence_samples', []) if sample.get('document_id') is not None))
            if len(pairs) > 8:
                self.warnings.append('原文事实回溯最多读取 8 组文档/实体，其他关系不作为已核验路径')
            groups = await self._gather([self._facts(pair) for pair in pairs[:8]])
            raw_facts = {row['id']: row for group in groups for row in group if row.get('id') is not None}
            supported = []
            for row in raw_facts.values():
                edge = edges.get(row.get('relation_id'))
                if edge and fact_supports_relation(row, edge):
                    supported.append(compact_fact(row))
            verified_edges = {row['relation_id']:edges[row['relation_id']] for row in supported}
            verified_connectors = connection_priority(verified_edges, roots, hops, query_words)
            supported.sort(key=lambda item: (
                item['relation_id'] not in verified_connectors,
                verified_connectors.index(item['relation_id']) if item['relation_id'] in verified_connectors else 99,
                -fact_score(item, query_words, set(roots)), item['id']))
            # Reserve coverage for distinct native relations before adding
            # repeated evidence for the same edge.
            first, extra, seen = [], [], set()
            for fact in supported:
                (extra if fact['relation_id'] in seen else first).append(fact)
                seen.add(fact['relation_id'])
            supported = first + extra
            supplemental = None
            # /ask is a secondary retrieval route, never a fabricated replacement
            # for a missing native edge. Generated upstream answers are discarded.
            if not supported and len(self.requests) < self.max_requests and time.monotonic() < self.deadline:
                try:
                    self.requests.append({'method':'POST','path':self.prefix+'/ask','generate':False,'hops':hops})
                    config = replace(self.config, hops=hops, timeout=min(self.config.timeout, max(.1, self.deadline-time.monotonic())))
                    supplemental = await retrieve_litkg(question, min(max_results, 8), config=config, transport=self.transport)
                except LitkgRetrievalError as exc:
                    self.failures.append(str(exc))
        if not roots and self.failures and not supplemental:
            raise GraphRAGError('; '.join(dict.fromkeys(self.failures)))
        result = pack_graph(question, resolutions, roots, nodes, edges, supported, max_results,
            self.config, hops, self.requests, self.warnings + self.failures, supplemental)
        if self.failures:
            result['status'] = 'partial' if result['facts'] else 'unavailable'
        return result


def valid_relation(edge):
    return (isinstance(edge, dict) and isinstance(edge.get('id'), int)
        and all(isinstance(edge.get(side), dict) and isinstance(edge[side].get('id'), int) and isinstance(edge[side].get('text'), str) for side in ('subject','object'))
        and isinstance(edge.get('predicate'), str) and bool(edge.get('evidence_samples'))
        and edge.get('review_status') != 'pending'
        and any(sample.get('semantic_status') != 'pending' for sample in edge.get('evidence_samples', [])))


def connection_priority(edges, roots, hops, words):
    """Preserve native paths between requested seeds before isolated lexical hits.

    This only chooses evidence to inspect; complete-fact validation still decides
    whether a candidate edge can appear in the returned graph or path.
    """
    paths={}
    for root in roots:
        for edge in edges.values():
            endpoints={edge['subject']['id'],edge['object']['id']}
            if root not in endpoints:
                continue
            neighbor=edge['object']['id'] if edge['subject']['id']==root else edge['subject']['id']
            if neighbor in roots and neighbor != root:
                paths[(edge['id'],)]=[edge]
            if hops<2:
                continue
            for other in edges.values():
                ends={other['subject']['id'],other['object']['id']}
                if other['id']==edge['id'] or neighbor not in ends:
                    continue
                target=other['object']['id'] if other['subject']['id']==neighbor else other['subject']['id']
                if target in roots and target != root:
                    paths.setdefault(tuple(sorted([edge['id'],other['id']])),[edge,other])
    ordered=sorted(paths.values(),key=lambda chain:-sum(relation_score(edge,words,set(roots)) for edge in chain))[:3]
    return list(dict.fromkeys(edge['id'] for chain in ordered for edge in chain))


def fact_supports_relation(fact, edge):
    participants = {p.get('entity_id') for p in fact.get('participants') or []}
    return (fact.get('relation_id') == edge['id'] and fact.get('predicate') == edge['predicate']
        and {edge['subject']['id'],edge['object']['id']} <= participants
        and fact.get('negated') == edge.get('negated') and fact.get('speculative') == edge.get('speculative')
        and (fact.get('claim_json') or {}).get('semantic_status') != 'pending'
        and any(isinstance(e.get('sentence'), str) and e['sentence'].strip() for e in fact.get('evidence') or []))


def compact_fact(row):
    fact = {key: copy.deepcopy(row[key]) for key in ('id','claim_id','relation_id','predicate','participants',
        'qualifiers','negated','speculative','document_id') if key in row}
    fact['extraction_confidence'] = row.get('confidence')
    claim = row.get('claim_json') or {}
    fact['semantic_status'] = claim.get('semantic_status', 'unknown')
    fact['evidence_type'] = (row.get('qualifiers') or {}).get('evidence_type', claim.get('source_kind','unknown'))
    fact['pending_review_kinds'] = sorted({r.get('kind','unknown') for r in row.get('reviews') or [] if r.get('status') == 'pending'})[:8]
    fact['citations'] = []
    for index, evidence in enumerate(row.get('evidence') or []):
        if not isinstance(evidence.get('sentence'),str) or not evidence['sentence'].strip():
            continue
        fact['citations'].append({
            'id':f"{row['id']}:{index}", 'fact_id':row['id'], 'claim_id':row['claim_id'],
            'document_id':row['document_id'], 'chunk_id':row.get('chunk_id'),
            **{k:row.get(k) for k in ('filename','title','doi')},
            **{k:evidence.get(k) for k in ('page','page_end','section','table_or_figure','sentence')},
        })
    return fact


def relation_score(edge, words, roots):
    text = json.dumps([edge['subject']['text'],edge['object']['text'],edge.get('qualifiers',{}),
                       [s.get('sentence','') for s in edge.get('evidence_samples',[])]],ensure_ascii=False)
    return 4*len(words & _tokens(text)) + 3*len(roots & {edge['subject']['id'],edge['object']['id']})


def fact_score(fact, words, roots):
    text=json.dumps([fact.get('participants'),fact.get('qualifiers'),[c['sentence'] for c in fact['citations']]],ensure_ascii=False)
    return (4*len(words & _tokens(text)) + 3*len(roots & {p.get('entity_id') for p in fact.get('participants',[])})
            + (not fact['pending_review_kinds']))


def graph_views(selected, nodes, edges, roots, max_hops=2):
    by_relation = {}
    for fact in selected:
        by_relation.setdefault(fact['relation_id'], []).append(fact)
    output_edges=[]
    for relation_id, facts in by_relation.items():
        native=edges[relation_id]
        output_edges.append({
            'id':relation_id, 'source':native['subject']['id'], 'target':native['object']['id'],
            'predicate':native['predicate'], 'label':native['predicate'],
            **{k:native.get(k) for k in ('qualifiers','negated','display_negated','speculative','result_status')},
            'fact_ids':[f['id'] for f in facts], 'citation_ids':[c['id'] for f in facts for c in f['citations']],
            'document_ids':sorted({f['document_id'] for f in facts}),
        })
    used={edge[k] for edge in output_edges for k in ('source','target')}
    paths=[]
    for root in roots:
        for edge in output_edges:
            if root not in (edge['source'],edge['target']):
                continue
            neighbor=edge['target'] if edge['source']==root else edge['source']
            paths.append(make_path([root,neighbor],[edge]))
            if max_hops < 2:
                continue
            for other in output_edges:
                if other['id']==edge['id'] or neighbor not in (other['source'],other['target']):
                    continue
                target=other['target'] if other['source']==neighbor else other['source']
                if target != root:
                    paths.append(make_path([root,neighbor,target],[edge,other]))
    unique={}
    for path in paths:
        key=(min(tuple(path['node_ids']),tuple(reversed(path['node_ids']))),
             min(tuple(path['relation_ids']),tuple(reversed(path['relation_ids']))))
        unique.setdefault(key,path)
    paths=sorted(unique.values(),key=lambda p:(-len(set(p['node_ids']) & set(roots)), -len(p['relation_ids']),p['relation_ids']))[:6]
    return {'nodes':[nodes[value] for value in sorted(used)],'edges':output_edges}, paths


def make_path(node_ids, edges):
    common=set(edges[0]['document_ids'])
    for edge in edges[1:]:
        common &= set(edge['document_ids'])
    return {
        'node_ids':node_ids, 'relation_ids':[e['id'] for e in edges],
        'steps':[{'relation_id':e['id'], 'source':e['source'], 'target':e['target'],
                  'traversal':'outgoing' if e['source']==node_ids[i] else 'incoming',
                  'fact_ids':e['fact_ids'], 'citation_ids':e['citation_ids']} for i,e in enumerate(edges)],
        'negated':any(e.get('negated') for e in edges), 'speculative':any(e.get('speculative') for e in edges),
        'shared_document_ids':sorted(common), 'cross_document':not bool(common),
        'interpretation':'retrieved_chain_not_causal_proof',
    }


def render_graph(result):
    return 'LitKG 原生图谱 GraphRAG（只读证据，不是因果结论）\n---JSON---\n'+json.dumps(result,ensure_ascii=False,separators=(',',':'))


def pack_graph(question, resolutions, roots, nodes, edges, facts, max_results, config, hops, requests, warnings, supplemental):
    selected=[]
    result={
        'source':{'kind':'litkg-native-graphrag','knowledge_base_id':config.knowledge_base_id,'read_only':True},
        'question':question, 'entity_resolution':resolutions, 'requested_hops':hops,
        'ranking':'native seed-connecting paths, then question/entity/condition lexical overlap and pending-review flag; not clinical evidence grading',
        'retrieval_scope':{'http_request_count':len(requests),'expanded_entity_ids':sorted({r['params']['entity_id'] for r in requests if r.get('path','').endswith('/relations')}),
                           'candidate_relation_count':len(edges),'verified_fact_count':len(facts)},
        'warnings':list(dict.fromkeys(warnings))[:16],
        'path_caveat':'路径每段均需原文依据；方向不可倒置。跨文档、不同对象/条件或相关性路径不证明传递因果。',
    }
    # Skip a single oversized evidence group without discarding smaller, useful
    # groups that follow it in the ranking. Quotes themselves are never sliced.
    for fact in copy.deepcopy(facts):
        if len(selected) >= max_results:
            break
        trial=selected+[fact]
        graph, paths=graph_views(trial,nodes,edges,roots,hops)
        draft={**result,'subgraph':graph,'paths':paths,
            'facts':[{**{k:v for k,v in f.items() if k!='citations'},'citation_ids':[c['id'] for c in f['citations']]} for f in trial],
            'citations':[c for f in trial for c in f['citations']]}
        if len(json.dumps({'is_error':False,'content':render_graph(draft)},ensure_ascii=False)) <= 16000:
            selected.append(fact)
    while True:
        graph, paths=graph_views(selected,nodes,edges,roots,hops)
        citations=[c for fact in selected for c in fact['citations']]
        public_facts=[{**{k:v for k,v in f.items() if k!='citations'},'citation_ids':[c['id'] for c in f['citations']]} for f in selected]
        omitted=len(facts)-len(selected)
        result.update(status='evidence_only' if selected else 'insufficient_graph_evidence',
            subgraph=graph, paths=paths, facts=public_facts, citations=citations, omitted_fact_count=omitted)
        result['warnings']=[w for w in result['warnings'] if not w.startswith('输出预算：')]
        if omitted:
            result['warnings'].append(f'输出预算：{omitted} 条完整事实未纳入，相关边/路径同步省略；未穷尽知识库')
        if not selected and supplemental:
            # Supplemental evidence never becomes a graph path without native edge verification.
            result['supplemental_evidence']={'status':supplemental['status'],'retrieval':supplemental['retrieval'],
                'facts':supplemental['facts'][:2],'citations':[c for c in supplemental['citations'] if c['fact_id'] in {f['id'] for f in supplemental['facts'][:2]}],
                'warnings':supplemental['warnings'],'generate':False}
        if len(json.dumps({'is_error':False,'content':render_graph(result)},ensure_ascii=False)) <= 17000:
            return result
        if selected:
            selected.pop()
            continue
        if result.pop('supplemental_evidence',None):
            result['warnings'].append('补充 /ask 证据超过输出预算，未显示；未构造图路径')
            supplemental=None
            continue
        raise GraphRAGError('GraphRAG 元数据超过输出预算，请减少实体或缩短问题')
