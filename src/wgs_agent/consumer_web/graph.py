"""Knowledge-subgraph selection and cleaning for the consumer report.

Only evidence-bound topic graphs from the saved structured report are used.  No
new node, edge or claim is invented.  The output is deliberately small (max 8
nodes, 6 edges) and is rendered interactively by vis-network in the browser.
"""

from __future__ import annotations

import copy
import html
import re
from collections import deque
from typing import Any

from .schema import GraphBlock, GraphEdge, GraphEvidence, GraphNode, Reference

PREDICATE_CN = {
    "PRODUCES": "产生",
    "CONSUMES": "利用",
    "UTILIZES": "利用",
    "DEGRADES": "分解",
    "FERMENTS": "发酵",
    "TRANSFORMS": "转化",
    "METABOLIZES": "代谢",
    "PROMOTES": "促进",
    "INHIBITS": "抑制",
    "ASSOCIATED_WITH": "相关",
    "CORRELATED_WITH": "相关",
    "INCREASES": "增加",
    "DECREASES": "减少",
    "ENRICHED_IN": "富集于",
    "DEPLETED_IN": "减少于",
    "SUBCLASS_OF": "属于",
    "PART_OF": "属于",
    "INTERACTS_WITH": "相互作用",
    "CAUSES": "影响",
    "PREVENTS": "减少",
    "TREATS": "用于研究",
}

REMOVED_PREDICATES = {"LOCATED_IN", "LOCALIZED_IN", "TARGETS", "TARGETS_TO", "MEASURED_BY", "ASSAYED_BY"}
REMOVED_EDGE_LABELS = {"位于", "定位于", "靶向", "测定方法为", "检测方法为"}
REMOVED_TYPES = {"StudyGroup", "Assay", "Biospecimen", "ExperimentalModel", "Instrument"}
REMOVED_TYPE_LABELS = {"研究分组", "研究对象", "检测方法", "实验模型", "生物样本", "仪器"}
IDENTIFIER_RE = re.compile(
    r"ARO[:_ -]?\d+|RiCBM\d+|VFG\d+|NC_\d+|PMID:?\s*\d+|DOI:?\s*10\.|"
    r"primer|probe|探针|引物|补充表|Table\s+S\d+|Fig(?:ure)?\.?\s*\d+|"
    r"\b(?:SGB|GGB)\d+|数据库编号|本体编号",
    re.I,
)
GROUP_WORDS = ("研究分组", "队列", "受试者", "病例组", "对照组", "健康组", "干预组")
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")


def _clean_title(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", str(value or ""))
    return html.unescape(value).strip()


class ReferenceIndex:
    """Assign compact R1.. ids to literature used by body copy and graphs."""

    def __init__(self, document: dict) -> None:
        self.by_claim: dict[str, str] = {}
        self.references: list[Reference] = []
        self._by_key: dict[str, str] = {}
        self.claim_index: dict[str, dict] = {}
        references = document.get("references") if isinstance(document.get("references"), dict) else {}
        for row in references.get("matched_docs", []) if isinstance(references, dict) else []:
            if not isinstance(row, dict):
                continue
            claim_id = str(row.get("claim_id") or "")
            if claim_id:
                self.claim_index.setdefault(claim_id, row)
        for bibliography in document.get("module_bibliographies", []) if isinstance(document.get("module_bibliographies"), list) else []:
            for row in bibliography.get("references", []) if isinstance(bibliography, dict) else []:
                source = row.get("source") if isinstance(row, dict) else None
                if isinstance(source, dict) and source.get("claim_id"):
                    self.claim_index.setdefault(str(source["claim_id"]), source)

    def add_claim(self, claim: dict) -> str:
        claim_id = str(claim.get("claim_id") or "")
        known = self.claim_index.get(claim_id) or claim
        key = claim_id or f"{known.get('document_id')}|{known.get('title')}"
        if key in self.by_claim:
            return self.by_claim[key]
        title = _clean_title(str(known.get("title") or claim.get("title") or ""))
        doi = str(known.get("doi") or claim.get("doi") or "").strip() or None
        dedupe_key = f"{title}|{doi}"
        if dedupe_key in self._by_key:
            existing = self._by_key[dedupe_key]
            self.by_claim[key] = existing
            return existing
        url = f"https://doi.org/{doi}" if doi else None
        year = None
        match = re.search(r"\b(19|20)\d{2}\b", title)
        if match:
            year = int(match.group(0))
        ref_id = f"R{len(self.references) + 1}"
        ref = Reference(id=ref_id, title=title or "研究文献", year=year, doi=doi, url=url)
        self.references.append(ref)
        self.by_claim[key] = ref_id
        self._by_key[dedupe_key] = ref_id
        return ref_id

    def add_topic_graph_sources(self, topic: dict) -> None:
        for edge in topic.get("knowledge_subgraph", {}).get("edges", []):
            self.add_claim(edge)

    def add_method(self, row: dict) -> str:
        title = _clean_title(str(row.get("title") or row.get("label") or "方法参考"))
        key = f"method|{title}"
        if key in self._by_key:
            return self._by_key[key]
        ref_id = f"R{len(self.references) + 1}"
        url = str(row.get("url") or "").strip() or None
        self.references.append(Reference(id=ref_id, title=title, year=None, doi=None, url=url))
        self._by_key[key] = ref_id
        return ref_id


def _node_label(node: dict) -> str:
    for field in ("display_label", "label"):
        value = str(node.get(field) or "").strip()
        if value and CHINESE_RE.search(value):
            return value
    return ""


def _edge_label(edge: dict) -> str:
    display = str(edge.get("display_label") or "").strip()
    if display and CHINESE_RE.search(display):
        return display
    predicate = str(edge.get("predicate") or "").upper()
    return PREDICATE_CN.get(predicate, "相关")


def _edge_approved(edge: dict) -> bool:
    status = str(edge.get("review_status") or "").lower()
    return status in {"approved", "reviewed", "accepted", "validated", "curated"}


def _contains_seed(node: dict, seeds: set[str]) -> bool:
    labels = [str(node.get("display_label") or ""), str(node.get("label") or ""), str(node.get("display_detail") or "")]
    low = " ".join(labels).casefold()
    return any(seed.casefold() in low for seed in seeds if seed)


def _clean_nodes(nodes: list[dict]) -> tuple[dict[str, dict], set[str], dict[str, int]]:
    keep: dict[str, dict] = {}
    removed: set[str] = set()
    reasons: dict[str, int] = {}
    for node in nodes:
        key = str(node.get("id"))
        label = str(node.get("display_label") or node.get("label") or "")
        raw = " ".join(str(node.get(field) or "") for field in ("label", "id", "normalized_id", "entity_id"))
        type_name = str(node.get("type") or "")
        type_label = str(node.get("display_type") or "")
        if type_name in REMOVED_TYPES or type_label in REMOVED_TYPE_LABELS:
            removed.add(key)
            reasons["study_or_assay_nodes"] = reasons.get("study_or_assay_nodes", 0) + 1
            continue
        if IDENTIFIER_RE.search(raw) or any(word in label for word in GROUP_WORDS):
            removed.add(key)
            reasons["identifier_or_group_nodes"] = reasons.get("identifier_or_group_nodes", 0) + 1
            continue
        if not _node_label(node):
            removed.add(key)
            reasons["non_chinese_nodes"] = reasons.get("non_chinese_nodes", 0) + 1
            continue
        keep[key] = node
    return keep, removed, reasons


def _merge_topics(topics: list[dict]) -> dict:
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    for topic in topics:
        graph = topic.get("knowledge_subgraph") or {}
        for node in graph.get("nodes", []):
            nodes.setdefault(str(node["id"]), node)
        for edge in graph.get("edges", []):
            key = "|".join(str(edge.get(field) or "") for field in ("source", "target", "predicate", "claim_id"))
            edges.setdefault(key, edge)
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


def _bounded_components(nodes: dict[str, dict], edges: list[dict], seeds: set[str], max_nodes: int = 8, max_edges: int = 6) -> tuple[dict[str, dict], list[dict]]:
    adjacency: dict[str, set[str]] = {key: set() for key in nodes}
    for edge in edges:
        source, target = str(edge["source"]), str(edge["target"])
        if source in adjacency and target in adjacency:
            adjacency[source].add(target)
            adjacency[target].add(source)
    remaining = set(adjacency)
    components = []
    while remaining:
        start = min(remaining)
        queue = [start]
        component = set()
        while queue:
            key = queue.pop()
            if key in component:
                continue
            component.add(key)
            queue.extend(adjacency[key] - component)
        remaining -= component
        component_edges = [edge for edge in edges if str(edge["source"]) in component and str(edge["target"]) in component]
        if component & {key for key, node in nodes.items() if _contains_seed(node, seeds)} and component_edges:
            components.append((component, component_edges))
    components.sort(key=lambda item: (-len(item[0]), -len(item[1]), sorted(item[0])))
    if len(components) > 2:
        components = components[:2]
    keep = set().union(*(component for component, _ in components)) if components else set()
    kept_edges = [edge for component, values in components for edge in values]
    # Keep seed nodes first, then highest-degree nodes, within the node ceiling.
    seed_keys = {key for key in keep if _contains_seed(nodes[key], seeds)}
    ordered = sorted(keep, key=lambda key: (key not in seed_keys, -len(adjacency[key]), key))
    keep = set(ordered[:max_nodes])
    kept_edges = [edge for edge in kept_edges if str(edge["source"]) in keep and str(edge["target"]) in keep]
    kept_edges.sort(key=lambda edge: (-(1 if str(edge["source"]) in seed_keys or str(edge["target"]) in seed_keys else 0), -float(edge.get("confidence") or 0), str(edge.get("id"))))
    kept_edges = kept_edges[:max_edges]
    return {key: nodes[key] for key in keep}, kept_edges


class GraphBuilder:
    def __init__(self, document: dict, refs: ReferenceIndex) -> None:
        self.document = document
        self.refs = refs
        self.topics = {
            str(topic.get("id")): topic
            for section in document.get("sections", [])
            for topic in section.get("topics", [])
        }
        self.shown: set[str] = set()

    def _candidate(self, topic_ids: list[str]) -> list[dict]:
        return [
            self.topics[tid] for tid in topic_ids
            if tid in self.topics
            and self.topics[tid].get("status") != "missing"
            and self.topics[tid].get("knowledge_subgraph", {}).get("edges")
        ]

    def choose(self, topic_ids: list[str], seeds: list[str]) -> tuple[GraphBlock | None, list[str]]:
        candidates = self._candidate(topic_ids)
        if not candidates:
            return None, topic_ids
        seed_set = {seed for seed in seeds if seed}
        graphs: list[list[dict]] = []
        merged = _merge_topics(candidates)
        graphs.append(merged)
        graphs.extend([_merge_topics([topic]) for topic in candidates])
        best: GraphBlock | None = None
        best_signature = ""
        for graph in graphs:
            nodes, removed, reasons = _clean_nodes(graph["nodes"])
            edges = []
            for edge in graph["edges"]:
                predicate = str(edge.get("predicate") or "").upper()
                label = str(edge.get("display_label") or "")
                if predicate in REMOVED_PREDICATES or label in REMOVED_EDGE_LABELS:
                    continue
                if str(edge["source"]) not in nodes or str(edge["target"]) not in nodes:
                    continue
                edges.append(edge)
            keep, edges = _bounded_components(nodes, edges, seed_set)
            if len(edges) < 2 or not keep:
                continue
            signature = "|".join(sorted(str(edge.get("claim_id") or edge.get("id")) for edge in edges))
            if signature in self.shown:
                continue
            node_rows = [
                GraphNode(
                    id=str(node["id"]),
                    label=_node_label(node),
                    type=str(node.get("type") or "Other"),
                )
                for node in keep.values()
            ]
            edge_rows: list[GraphEdge] = []
            for edge in edges:
                claim = dict(edge)
                ref_id = self.refs.add_claim(claim)
                sentence = re.sub(r"\s+", " ", str(edge.get("evidence_text") or "")).strip()
                if not sentence:
                    sentence = _edge_label(edge) + "；证据句未收录"
                edge_rows.append(GraphEdge(
                    id=str(edge.get("id") or f"e{len(edge_rows)+1}"),
                    from_=str(edge["source"]),
                    to=str(edge["target"]),
                    label=_edge_label(edge),
                    status="approved" if _edge_approved(edge) else "pending",
                    evidence=[GraphEvidence(sentence=sentence[:600], ref_id=ref_id)],
                ))
            block = GraphBlock(
                nodes=node_rows,
                edges=edge_rows,
                seeds=sorted(seed_set),
                topic_ids=[str(topic["id"]) for topic in candidates],
                first_in_report=False,
            )
            score = (len(keep), len(edge_rows), sum(float(edge.get("confidence") or 0) for edge in edges))
            if best is None or score > (len(best.nodes), len(best.edges), 0):
                best = block
                best_signature = signature
        if best is None:
            return None, topic_ids
        self.shown.add(best_signature)
        return best, [str(topic["id"]) for topic in candidates]
