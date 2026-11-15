"""G13: remove presentation noise from an evidence-bound consumer graph."""
from __future__ import annotations

from collections import Counter, deque
import copy
import re


def consumer_graph_filter(graph, seeds):
    """Return a filtered COPY with an audit; never add nodes, edges or claims.

    ``display_status=too_sparse`` means the caller must omit the figure. Raw
    topic graphs are untouched. Two retained edges may belong to up to two
    seed-containing components. Review status is preserved for dashed rendering.
    """
    from .knowledge_graph import _contains, _confidence
    from .graph_visual import node_category, edge_category
    result = copy.deepcopy(graph)
    nodes = {node['id']: node for node in result.get('nodes', [])}
    original_edges = result.get('edges', [])
    reasons = Counter()
    concepts = {'多样性', '丰富度', '均衡度', '菌群组成', '丁酸', '乳酸', '膳食纤维'}
    seed_nodes = {key for key, node in nodes.items() if any(
        _contains(seed, label) or seed in concepts and seed in label
        for seed in seeds if seed for label in (str(node.get('label', '')), str(node.get('display_label', ''))))}
    remove = set()
    for key, node in nodes.items():
        label = str(node.get('display_label') or node.get('label') or '')
        raw = ' '.join(str(node.get(field) or '') for field in ('label', 'id', 'normalized_id', 'entity_id'))
        group_word = any(word in label for word in ('应答者', '队列', '受试者')) or '组' in label and not any(word in label for word in ('基因组', '组成', '组织'))
        if node_category(str(node.get('type', ''))) == '研究对象' or node.get('display_type') in {'研究对象', '研究分组'} or group_word:
            remove.add(key); reasons['study_group_nodes'] += 1
        elif re.search(r'ARO[:_ -]?\d+|RiCBM\d+|primer|probe|探针|引物|本体编号|数据库编号', raw, re.I) or re.search(r'[零〇一二三四五六七八九十百千万]{3,}', label):
            remove.add(key); reasons['identifier_nodes'] += 1
    edges = []
    for edge in original_edges:
        predicate = str(edge.get('predicate', '')).upper()
        label = str(edge.get('display_label', ''))
        if predicate in {'LOCATED_IN', 'LOCALIZED_IN', 'TARGETS', 'TARGETS_TO'} or label in {'位于', '定位于', '靶向'}:
            reasons['structural_edges'] += 1
        elif edge['source'] in remove or edge['target'] in remove:
            reasons['dangling_edges'] += 1
        elif edge_category(predicate) == '组间差异' and any(nodes[k].get('display_type') in {'研究分组', '研究对象'} for k in (edge['source'], edge['target'])):
            reasons['study_difference_edges'] += 1
        else:
            edges.append(edge)
    adjacency = {key: set() for key in nodes if key not in remove}
    for edge in edges:
        if edge['source'] in adjacency and edge['target'] in adjacency:
            adjacency[edge['source']].add(edge['target']); adjacency[edge['target']].add(edge['source'])
    distance = {key: 0 for key in seed_nodes if key in adjacency}
    queue = deque(distance)
    while queue:
        key = queue.popleft()
        for other in adjacency[key]:
            if other not in distance:
                distance[other] = distance[key] + 1; queue.append(other)
    for key in adjacency:
        if node_category(str(nodes[key].get('type', ''))) == '其他' and distance.get(key, float('inf')) > 1:
            remove.add(key); reasons['distant_other_nodes'] += 1
    active = set(adjacency) - remove
    connected_edges = []
    for edge in edges:
        if edge['source'] in active and edge['target'] in active:
            connected_edges.append(edge)
        else:
            reasons['dangling_edges'] += 1
    adjacency = {key: set() for key in active}
    for edge in connected_edges:
        adjacency[edge['source']].add(edge['target']); adjacency[edge['target']].add(edge['source'])
    components = []
    remaining = set(active)
    while remaining:
        stack = [min(remaining)]; component = set()
        while stack:
            key = stack.pop()
            if key in component: continue
            component.add(key); stack.extend(adjacency[key] - component)
        remaining -= component
        component_edges = [edge for edge in connected_edges if edge['source'] in component]
        components.append((component, component_edges))
    eligible = [(component, values) for component, values in components if component & seed_nodes and values]
    eligible.sort(key=lambda item: (-len(item[0] & seed_nodes), -len(item[1]), -sum(_confidence(e) for e in item[1]), sorted(item[0])))
    keep = set().union(*(component for component, _ in eligible[:2])) if eligible else set()
    for component, values in components:
        if not component <= keep:
            reason = 'unseeded_component' if not component & seed_nodes else 'extra_component'
            reasons[reason + '_nodes'] += len(component)
            reasons[reason + '_edges'] += len(values)
    result['nodes'] = [node for node in result.get('nodes', []) if node['id'] in keep]
    result['edges'] = [edge for edge in connected_edges if edge['source'] in keep and edge['target'] in keep]
    result['display_status'] = 'ready' if len(result['edges']) >= 2 else 'too_sparse'
    result['filter_audit'] = {'before_nodes': len(nodes), 'before_edges': len(original_edges),
        'after_nodes': len(result['nodes']), 'after_edges': len(result['edges']),
        'components': len(eligible[:2]), 'removed_reasons': dict(reasons),
        'status': result['display_status']}
    result.pop('figure', None); result.pop('visual_style', None)
    return result
