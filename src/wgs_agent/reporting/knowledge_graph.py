"""Bounded report subgraphs made only from retrieved, attributable LitKG claims."""

from __future__ import annotations

import copy
from functools import lru_cache
import hashlib
import json
import math
import os
import re
from pathlib import Path

import httpx

from wgs_fmt_platform.knowledge.knowledge_settings import is_pending_review

from .catalog import SECTIONS

MAX_EDGES = 6
MAX_NODES = 12
TOPIC_KEYWORDS = {f"{s.id}.{t.id}": t.keywords for s in SECTIONS for t in s.topics}


def _normal(value: object) -> str:
    return _normal_text(str(value or ""))


@lru_cache(maxsize=32768)
def _normal_text(value: str) -> str:
    return " ".join(
        re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(value or "").casefold().replace("_", " ")).split()
    )


def _contains(needle: object, haystack: object) -> bool:
    needle, haystack = _normal(needle), _normal(haystack)
    if len(needle) < 3 and not re.search(r"[\u4e00-\u9fff]{2}", needle):
        return False
    # A descriptor may follow the entity, e.g. "butyrate production". Internal
    # name tokens do not identify the same entity (e.g. imidazole propionate).
    return haystack == needle or haystack.startswith(needle + " ")


def _score(row: dict, topic: dict, evidence: dict) -> int:
    """Endpoint/explicit-topic matches, never a match on filename or generic prose."""
    endpoints = [str(row.get(k) or "") for k in ("subject", "object")]
    if not all(
        isinstance(row.get(k), str) and row[k].strip()
        for k in ("subject", "predicate", "object", "evidence_text")
    ):
        return 0
    explicit = row.get("topic_ids")
    topic_ids = topic.get("graph_source_topic_ids", [topic["id"]])
    if isinstance(explicit, list) and set(topic_ids).intersection(explicit):
        return 100
    score = 0
    for key in topic.get("evidence_ids", [])[:24]:
        record = evidence.get(key, {})
        for field in ("species", "name", "disease", "gene", "gene_family", "id"):
            aliases = re.split(r"[/（(]", str(record.get(field) or ""))
            if any(_contains(alias, endpoint) for alias in aliases for endpoint in endpoints):
                score = max(score, 40)
    if any(
        _contains(word, endpoint)
        for tid in topic_ids for word in TOPIC_KEYWORDS.get(tid, ())
        for endpoint in endpoints
    ):
        score = max(score, 20)
    return score


def _confidence(row: dict) -> float:
    try:
        value = float(row.get("confidence") or 0)
        return value if math.isfinite(value) else 0
    except (TypeError, ValueError):
        return 0


def _claim_quality(row: dict) -> tuple[bool, float]:
    return is_pending_review(row), -_confidence(row)


def _topics(document: dict):
    return (t for s in document["sections"] for t in s["topics"] if t["status"] != "missing")


async def enrich_document(document: dict, *, transport=None) -> None:
    """Retrieve once per report and retain only topic-relevant claims, before narration.

    Existing bound evidence survives outages. The scan is bounded and audited;
    no whole-graph endpoint or patient measurements are sent to LitKG.
    """
    from wgs_fmt_platform.knowledge.knowledge_settings import refresh_knowledge_settings
    refresh_knowledge_settings()
    audit = {"status": "not_configured", "scanned_claims": 0, "added_claims": 0}
    document["audit"]["knowledge_graph_retrieval"] = audit
    if not list(_topics(document)):
        audit["status"] = "no_eligible_data"
        return
    base = os.environ.get("WGS_CLAIM_API_URL", "").rstrip("/")
    if not base or os.environ.get("WGS_REPORT_GRAPH_RETRIEVAL_DISABLED", "0") == "1":
        return
    try:
        kb = int(os.environ.get("WGS_CLAIM_API_KNOWLEDGE_BASE_ID", "7"))
        limit = min(10000, max(1, int(os.environ.get("WGS_REPORT_GRAPH_SCAN_LIMIT", "10000"))))
        timeout = min(30.0, max(1.0, float(os.environ.get("WGS_CLAIM_API_TIMEOUT", "20"))))
        headers = {"Accept": "application/json"}
        token = os.environ.get("WGS_CLAIM_API_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        raw, total = [], None
        async with httpx.AsyncClient(
            base_url=base, headers=headers, timeout=timeout, transport=transport
        ) as client:
            from .litkg_claims import load_claims
            if transport is None:
                from .litkg_targeted import retrieve_report_references
                try:
                    raw, fetch_meta = await retrieve_report_references(client, kb, document, limit)
                except httpx.HTTPStatusError as error:
                    if error.response.status_code not in {404, 405}:
                        raise
                    raw, fetch_meta = await load_claims(client, kb, limit)
            else:
                raw, fetch_meta = await load_claims(client, kb, limit, cache_dir=False)
            total = fetch_meta.get("total_claims")
            audit.update(fetch_meta)
        from wgs_agent.tools.knowledge_tools import claim_record_to_reference

        if fetch_meta.get("reference_rows"):
            references = raw
        else:
            references = []
            from wgs_fmt_platform.knowledge.knowledge_settings import eligible_for_use
            for row in raw:
                if not eligible_for_use(row):
                    continue
                if row.get("id") is None:
                    continue
                item = claim_record_to_reference(row, base_url=base, knowledge_base_id=kb)
                # Keep endpoint identities and qualifiers that are absent in the legacy contract.
                for field in (
                    "subject_entity_id",
                    "object_entity_id",
                    "subject_normalized_id",
                    "object_normalized_id",
                    "qualifiers",
                    "process",
                    "result_status",
                    "review_status",
                    "semantic_status",
                    "audit_pending",
                    "review_reasons",
                    "display_negated",
                    "page",
                    "page_end",
                    "section_title",
                    "title",
                ):
                    if field in row:
                        item[field] = row[field]
                references.append(item)
        audit["usage_candidate_count"] = len(references)
        evidence = document["evidence"]
        document["references"] = copy.deepcopy(document.get("references") or {})
        supplied = document["references"].get("matched_docs", [])
        matched = (
            [row for row in supplied if isinstance(row, dict)] if isinstance(supplied, list) else []
        )
        document["references"]["matched_docs"] = matched
        by_claim = {str(r.get("claim_id")): key for key, r in evidence.items() if r.get("claim_id")}
        for topic in _topics(document):
            ranked = [
                (row, score)
                for row in references
                if (score := _score(row, topic, evidence))
            ]
            ranked.sort(key=lambda item: (*_claim_quality(item[0]), -item[1], str(item[0].get("claim_id"))))
            for row, _ in ranked[:8]:
                claim_id = str(row["claim_id"])
                key = by_claim.get(claim_id)
                if key is None:
                    matched.append(row)
                    key = f"K{len(matched)}"
                    evidence[key] = {**row, "kind": "literature"}
                    by_claim[claim_id] = key
                    audit["added_claims"] += 1
                if key not in topic["allowed_narrative_ids"]:
                    topic["allowed_narrative_ids"].append(key)
        from .chapter_three import integrate_knowledge
        integrate_knowledge(document, references)
        audit.update(
            status=fetch_meta.get("status", "complete"),
            scanned_claims=len(raw),
            total_claims=total,
            scan_truncated=fetch_meta.get("scan_truncated", isinstance(total, int) and total > len(raw)),
            knowledge_base_id=kb,
        )
        audit["selected_sha256"] = hashlib.sha256(
            json.dumps(matched, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        audit.update(status="unavailable", error_type=type(exc).__name__)


def build_topic_graph(document: dict, topic: dict, *, max_nodes=MAX_NODES,
                      max_edges=MAX_EDGES, seeds=()) -> dict:
    """A one-hop evidence subgraph; no inferred edges or background expansion."""
    graph = {
        "status": "no_match",
        "nodes": [],
        "edges": [],
        "candidate_count": 0,
        "truncated": False,
        "max_edges": max_edges,
        "max_nodes": max_nodes,
    }
    if topic["status"] == "missing":
        graph["status"] = "not_assessed"
        return graph
    evidence = document["evidence"]
    cited = {
        key
        for key in topic.get("narrative_evidence_ids", [])
        if evidence.get(key, {}).get("kind") == "literature"
    }
    # Citation-bound graphs cannot silently replace a cited claim with a nearby one.
    keys = sorted(cited | set(topic.get('allowed_narrative_ids', [])))
    candidates = []
    for key in keys:
        row = evidence.get(key, {})
        score = _score(row, topic, evidence)
        if (
            row.get("kind") == "literature"
            and (score or key in cited)
            and all(row.get(k) for k in ("subject", "predicate", "object", "evidence_text"))
            and (row.get("claim_id") or row.get("raw_claim_id"))
        ):
            candidates.append((key, row, score))
    if seeds:
        candidates.sort(key=lambda item: (
            is_pending_review(item[1]),
            -(item[2] + 60 * bool(_seed_matches(item[1], seeds)) + 10 * _confidence(item[1])),
            item[0] not in cited, item[0]))
    else:
        candidates.sort(
            key=lambda item: (*_claim_quality(item[1]), item[0] not in cited, -item[2], item[0])
        )
    graph["candidate_count"] = len(candidates)
    nodes, seen = {}, set()
    for key, row, _ in candidates:
        claim_id = str(row.get("claim_id") or row["raw_claim_id"])
        identity = (row.get("knowledge_base_id"), claim_id)
        if identity in seen:
            continue
        pair = []
        for role in ("subject", "object"):
            label, kind = str(row[role]), str(row.get(role + "_type") or "Other")
            scope = str(
                row.get("knowledge_base_id")
                or row.get("knowledge_version")
                or row.get("source_url")
                or "bound"
            )
            entity_id = row.get(role + "_entity_id")
            normalized_id = row.get(role + "_normalized_id")
            identity_text = (
                f"{scope}:entity:{entity_id}"
                if entity_id is not None
                else f"{scope}:{kind}:{normalized_id or _normal(label)}"
            )
            node_id = "n" + hashlib.sha256(identity_text.encode()).hexdigest()[:16]
            pair.append(
                {
                    "id": node_id,
                    "label": label,
                    "type": kind,
                    "entity_id": entity_id,
                    "normalized_id": normalized_id,
                }
            )
        if (
            len(graph["edges"]) >= max_edges
            or len(set(nodes) | {n["id"] for n in pair}) > max_nodes
        ):
            graph["truncated"] = True
            continue
        seen.add(identity)
        for node in pair:
            nodes.setdefault(node["id"], node)
        graph["edges"].append(
            {
                "id": f"e{len(graph['edges']) + 1}",
                "source": pair[0]["id"],
                "target": pair[1]["id"],
                "subject": pair[0]["label"],
                "object": pair[1]["label"],
                "predicate": row["predicate"],
                "evidence_id": key,
                "claim_id": claim_id,
                **{
                    field: row.get(field)
                    for field in (
                        "document_id",
                        "knowledge_base_id",
                        "filename",
                        "source_url",
                        "evidence_text",
                        "confidence",
                        "negated",
                        "speculative",
                        "display_negated",
                        "qualifiers",
                        "process",
                        "result_status",
                        "review_status",
                    "semantic_status",
                    "audit_pending",
                    "review_reasons",
                        "page",
                        "page_end",
                    )
                },
                "cited_in_analysis": key in cited,
            }
        )
    graph["nodes"] = list(nodes.values())
    if graph["edges"]:
        graph["status"] = "available"
    graph["selection"] = "cited_claims" if cited else "related_claims"
    return graph


def relation_label(edge: dict) -> str:
    flags = []
    if edge.get("negated") or edge.get("display_negated"):
        flags.append("否定")
    if edge.get("speculative"):
        flags.append("推测")
    status = {"no_effect_reported": "未报告效应", "not_significant": "不显著"}.get(
        edge.get("result_status")
    )
    if status:
        flags.append(status)
    return str(edge.get("display_label") or edge["predicate"]) + (
        "（" + "、".join(flags) + "）" if flags else ""
    )


def attach_subgraphs(document: dict) -> None:
    for section in document["sections"]:
        for topic in section["topics"]:
            previous = topic.get("knowledge_subgraph", {})
            graph = build_topic_graph(document, topic)
            signature = hashlib.sha256(
                json.dumps(graph, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            if previous.get("source_signature") == signature:
                continue
            graph["source_signature"] = signature
            topic["knowledge_subgraph"] = graph


def render_graph_figures(document: dict, directory: Path) -> dict[str, str]:
    from .graph_visual import render_graph_figures as render

    return render(document, directory)


def graph_mode() -> str:
    value = os.environ.get("WGS_REPORT_KNOWLEDGE_GRAPHS", "inline").strip().lower()
    return value if value in {"inline", "appendix", "off"} else "inline"


def graph_signature(graph: dict) -> str:
    """Graph identity is independent of topic title, layout and image filename."""
    rows = sorted((str(e.get("knowledge_base_id") or ""), str(e.get("claim_id") or ""),
                   e["source"], e["target"], e["predicate"]) for e in graph.get("edges", []))
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def _seed_matches(row: dict, seeds, nodes=()) -> list[str]:
    labels = [row.get("subject", ""), row.get("object", "")]
    labels += [n.get("display_label", "") for n in nodes
               if n["id"] in {row.get("source"), row.get("target")}]
    return sorted({str(seed) for seed in seeds if seed and any(
        _contains(seed, label) for label in labels if label)})


def subsection_topics(chapter: int, sub: int) -> list[str]:
    from .template_catalog import CHAPTERS
    from .consumer_copy import GRAPH_TOPICS
    mapped = CHAPTERS[chapter - 1][3][sub - 1][1] if 0 < chapter <= len(CHAPTERS) and 0 < sub <= len(CHAPTERS[chapter - 1][3]) else ()
    return list(dict.fromkeys([*mapped, *GRAPH_TOPICS.get((chapter, sub), ())]))


def subsection_seeds(document: dict, chapter: int, sub: int) -> list[str]:
    """Custom consumer renderers expose the entities they actually show.

    Future opt-in chapters can publish consumer.graph_seeds[chapter][sub];
    ordinary Word sections default to their bound, displayed evidence names.
    """
    if chapter == 1:
        from .consumer_chapter import graph_seeds
        return graph_seeds(document, sub)
    if chapter == 2:
        from .consumer_chapter_two import graph_seeds
        return graph_seeds(document, sub)
    if chapter == 3:
        from .consumer_chapter_three import graph_seeds
        return graph_seeds(document, sub)
    configured = document.get("consumer", {}).get("graph_seeds", {}).get(str(chapter), {}).get(str(sub))
    if configured is not None:
        return configured
    ids = set(subsection_topics(chapter, sub))
    return sorted({str(row[field]) for section in document.get("sections", []) for topic in section["topics"]
                   if topic["id"] in ids for key in topic.get("evidence_ids", [])
                   for row in [document.get("evidence", {}).get(key, {})]
                   for field in ("species", "name", "label") if row.get(field)})


def _body_node_limit() -> int:
    try:
        return max(2, min(MAX_NODES, int(os.environ.get("WGS_REPORT_GRAPH_BODY_MAX_NODES", "8"))))
    except ValueError:
        return 8


def _chinese_nodes(graph: dict) -> bool:
    return bool(graph.get("edges")) and all(
        re.search(r"[\u4e00-\u9fff]", n.get("display_label", ""))
        and not re.search(r"[A-Za-z]", n.get("display_label", "") + n.get("display_type", ""))
        for n in graph.get("nodes", []))


def _graph_metrics(graph: dict, seeds) -> dict:
    edges = graph.get("edges", [])
    matches = [_seed_matches(edge, seeds, graph.get("nodes", [])) for edge in edges]
    return {"seed_hit_edges": sum(bool(hit) for hit in matches), "edge_count": len(edges),
            "average_confidence": sum(_confidence(edge) for edge in edges) / max(1, len(edges)),
            "matched_seeds": sorted({seed for hit in matches for seed in hit})}


def _display_from_candidates(graph: dict, candidates: list[dict], translations=None) -> dict | None:
    from .graph_labels import _id, _attributes, TYPE_LABELS, RELATION_LABELS, ENTITY_LABELS
    translations = translations or {}
    nodes = {n["id"]: n for t in candidates for n in t["knowledge_subgraph"].get("nodes", [])}
    edges = {(e.get("knowledge_base_id"), e["claim_id"]): e for t in candidates
             for e in t["knowledge_subgraph"].get("edges", [])}
    for node in graph.get("nodes", []):
        node.update({k: v for k, v in nodes.get(node["id"], {}).items() if k.startswith("display_")})
        label = translations.get(_id("entity", json.dumps([node["label"], node["type"]], ensure_ascii=False)), {})
        kind = translations.get(_id("type", node["type"]), {})
        node.setdefault("display_label", label.get("label", node["label"]))
        node.setdefault("display_type", kind.get("label", TYPE_LABELS.get(node["type"], "其他")))
        if re.search(r"[A-Za-z]", node["display_label"]) and node["label"] in ENTITY_LABELS:
            node["display_label"] = ENTITY_LABELS[node["label"]]
    for edge in graph.get("edges", []):
        edge.update({k: v for k, v in edges.get((edge.get("knowledge_base_id"), edge["claim_id"]), {}).items() if k.startswith("display_")})
        label = translations.get(_id("relation", edge["predicate"]), {})
        edge.setdefault("display_label", label.get("label", RELATION_LABELS.get(edge["predicate"], "")))
        properties = _attributes(edge)
        if properties and "display_attributes" not in edge:
            attribute = translations.get(_id("attribute", json.dumps(properties, sort_keys=True, ensure_ascii=False)), {})
            if attribute:
                edge["display_attributes"] = attribute["label"]
            else:
                edge['consumer_missing_attributes']=True
    # Identifiers and research groups may be untranslated but removable by G13.
    # Validate the surviving display only AFTER filtering, never discard a whole
    # otherwise usable graph merely because a removable RiCBM/probe has no label.
    graph["display_status"] = "pending_consumer_filter"
    return graph


def _bounded_candidate(topic: dict, seeds, evidence: dict) -> dict | None:
    graph = copy.deepcopy(topic["knowledge_subgraph"])
    edges = sorted(graph["edges"], key=lambda edge: (
        is_pending_review(edge), -(_score(evidence.get(edge["evidence_id"], {}), topic, evidence)
        + 60 * bool(_seed_matches(edge, seeds, graph["nodes"])) + 10 * _confidence(edge)), edge["evidence_id"]))
    selected, node_ids = [], set()
    for edge in edges:
        pair = {edge["source"], edge["target"]}
        if len(selected) < 6 and len(node_ids | pair) <= _body_node_limit():
            selected.append(edge)
            node_ids.update(pair)
    graph["edges"] = selected
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] in node_ids]
    graph.pop("figure", None)
    graph.pop("visual_style", None)
    graph.update(max_nodes=_body_node_limit(), max_edges=6, truncated=len(selected) < len(edges))
    return graph if graph['edges'] else None


def subsection_graph(document: dict, chapter: int, sub: int, seeds) -> dict | None:
    """Select one Chinese, citation-bound body graph without modifying topic graphs.

    Eligible topics must already be display-ready. Their allowed/cited claim IDs
    are unioned into a display-only pseudo topic. Relevance, confidence and a
    60-point endpoint seed bonus rank its edges; evidence eligibility is unchanged.
    A duplicate merged graph falls back to individual candidates, ordered by
    seed-hit edge count, edge count, then mean confidence. Selection and omissions
    are report-scoped and deterministic across preparation and repeated rendering.
    """
    from .consumer_state import consumer, omit
    state = consumer(document)
    selections = state.setdefault("subsection_graphs", {})
    key = f"{chapter}.{sub}"
    previous = selections.get(key, {}).get("graph") or {}
    seeds = sorted({str(seed) for seed in seeds if seed})
    ids = subsection_topics(chapter, sub)
    topics = {t["id"]: t for s in document.get("sections", []) for t in s["topics"]}
    candidates = [topics[tid] for tid in ids if tid in topics and topics[tid].get("status") != "missing"
                  and topics[tid].get("knowledge_subgraph", {}).get("display_status") == "ready"
                  and topics[tid]["knowledge_subgraph"].get("edges")]
    entry = {"chapter": chapter, "subsection": sub, "seeds": seeds, "candidate_topics": ids,
             "ready_topics": [t["id"] for t in candidates], "candidates": [], "graph": None}
    entry["topic_candidates"] = [{"id": tid, "status": topics.get(tid, {}).get("status", "absent"),
        "display_status": topics.get(tid, {}).get("knowledge_subgraph", {}).get("display_status"),
        "edge_count": len(topics.get(tid, {}).get("knowledge_subgraph", {}).get("edges", []))} for tid in ids]
    earlier = [(tuple(map(int, k.split('.'))), record) for k, record in selections.items()
               if tuple(map(int, k.split('.'))) < (chapter, sub)]
    forbidden = {record["graph"]["signature"] for position, record in earlier if position[0] == chapter and record.get("graph")}
    if earlier:
        adjacent = max(earlier, key=lambda item: item[0])[1].get("graph")
        if adjacent:
            forbidden.add(adjacent["signature"])
    options = []
    if candidates:
        pseudo = {"id": f"consumer.{key}", "status": "available", "graph_source_topic_ids": [t["id"] for t in candidates],
                  "evidence_ids": sorted({i for t in candidates for i in t.get("evidence_ids", [])}),
                  "allowed_narrative_ids": sorted({i for t in candidates for i in t.get("allowed_narrative_ids", [])}),
                  "narrative_evidence_ids": sorted({i for t in candidates for i in t.get("narrative_evidence_ids", [])})}
        merged = _display_from_candidates(build_topic_graph(document, pseudo, max_nodes=_body_node_limit(), max_edges=6, seeds=seeds), candidates, document.get("graph_label_translations"))
        entry["merge_status"] = "ready" if merged else "no_complete_chinese_display"
        if merged:
            options.append(("merged", merged))
        fallback = [(t["id"], g) for t in candidates if (g := _bounded_candidate(t, seeds, document["evidence"]))]
        fallback.sort(key=lambda item: (-_graph_metrics(item[1], seeds)["seed_hit_edges"],
                                      -len(item[1]["edges"]), -_graph_metrics(item[1], seeds)["average_confidence"], item[0]))
        options.extend(fallback)
    selected = None
    filter_attempts = []
    for source, graph in options:
        from .consumer_graph import consumer_graph_filter
        graph = consumer_graph_filter(graph, seeds)
        if graph['display_status']=='ready' and (not _chinese_nodes(graph) or any(not edge.get('display_label') or edge.get('consumer_missing_attributes') for edge in graph['edges'])):
            graph['display_status']='unavailable'
            graph['filter_audit']['status']='unavailable'
        filter_attempts.append({'source': source, **graph['filter_audit']})
        if graph['display_status'] != 'ready':
            continue
        signature = graph_signature(graph)
        metrics = _graph_metrics(graph, seeds)
        ranking_topic = pseudo if source == "merged" else topics[source]
        metrics["edge_scores"] = [{"evidence_id": edge["evidence_id"],
            "relevance": _score(document["evidence"].get(edge["evidence_id"], {}), ranking_topic, document["evidence"]),
            "confidence": _confidence(edge), "matched_seeds": _seed_matches(edge, seeds, graph["nodes"])} for edge in graph["edges"]]
        for row in metrics["edge_scores"]:
            row["score"] = row["relevance"] + 60 * bool(row["matched_seeds"]) + 10 * row["confidence"]
        metrics["score"] = sum(row["score"] for row in metrics["edge_scores"])
        entry["candidates"].append({"source": source, "signature": signature, "duplicate": signature in forbidden, **metrics})
        if selected is None and signature not in forbidden:
            graph.update(signature=signature, body_presentation=True, source_topic_ids=entry["ready_topics"] if source == "merged" else [source],
                         caption=f"图 {chapter}-{sub}k  与本节相关的研究知识")
            if previous.get("signature") == signature and previous.get("figure"):
                graph["figure"] = previous["figure"]
                if previous.get("visual_style"):
                    graph["visual_style"] = previous["visual_style"]
            selected = graph
            entry["selected_source"] = source
            entry["selected_metrics"] = metrics
    entry["graph"] = selected
    entry['graph_filter_attempts'] = filter_attempts
    state.setdefault('graph_filter_audit', {})[key] = (
        selected['filter_audit'] if selected else filter_attempts[0] if filter_attempts else
        {'before_nodes': 0, 'before_edges': 0, 'after_nodes': 0, 'after_edges': 0, 'removed_reasons': {}, 'status': 'no_ready_subgraph'})
    selections[key] = entry
    item = f"{key} 知识子图"
    if selected is None:
        sparse = bool(filter_attempts) and all(attempt['after_edges'] < 2 for attempt in filter_attempts)
        reason = 'subgraph_too_sparse' if sparse else 'no_ready_subgraph'
        document['consumer_omissions'] = [row for row in document.get('consumer_omissions', [])
            if not (row['chapter'] == chapter and row['item'] == item and row['reason_code'] != reason)]
        omit(document, chapter, item, "subgraph_too_sparse" if sparse else "no_ready_subgraph",
             "清洗后的知识子图不足两条关系" if sparse else "没有可用于正文且不重复的已就绪知识子图")
    elif selected.get("figure"):
        document["consumer_omissions"] = [r for r in document.get("consumer_omissions", [])
                                         if not (r["chapter"] == chapter and r["item"] == item)]
    return selected


def prepare_subsection_graphs(document: dict) -> None:
    from .consumer_copy import CONSUMER_CHAPTERS, CHAPTERS as COPY, GRAPH_HIDDEN_SUBSECTIONS
    from .template_catalog import CHAPTERS
    if graph_mode() != "inline":
        return
    for chapter in sorted(CONSUMER_CHAPTERS):
        subs = COPY.get(chapter, {}).get("subsections", {}) or range(1, len(CHAPTERS[chapter - 1][3]) + 1)
        presentation = next((c for c in document.get("presentation", {}).get("chapters", [])
                             if c["number"] == chapter), {})
        visible = [int(match.group(1)) for title in presentation.get("subsections", [])
                   if (match := re.match(rf"^{chapter}\.(\d+)\s", title))]
        if visible:
            subs = visible
        for sub in subs:
            if (chapter, sub) not in GRAPH_HIDDEN_SUBSECTIONS:
                subsection_graph(document, chapter, sub, subsection_seeds(document, chapter, sub))


def _reading_note(document: dict) -> list[str]:
    state = document.setdefault("consumer", {})
    if state.get("graph_reading_note_shown"):
        return []
    from .glossary import Glossary
    entry = Glossary(document).get("knowledge_subgraph", kind="concept")
    if entry and entry["review_status"] == "approved":
        state["graph_reading_note_shown"] = True
        return ["> " + entry["detail"]]
    return []


def _mark_displayed(document: dict, graph: dict) -> None:
    state = document.setdefault("consumer", {})
    rows = state.setdefault("displayed_subgraphs", [])
    signature = graph_signature(graph)
    if not any(row["signature"] == signature for row in rows):
        rows.append({"signature": signature, "claims": sorted(graph_claim_keys(graph))})


def graph_claim_keys(graph: dict) -> set[str]:
    return {json.dumps([e.get("knowledge_base_id"), str(e["claim_id"])]) for e in graph.get("edges", [])}


def subsection_graph_markdown(document: dict, chapter: int, sub: int, seeds=None) -> list[str]:
    if graph_mode() != "inline":
        return []
    graph = subsection_graph(document, chapter, sub, seeds if seeds is not None else subsection_seeds(document, chapter, sub))
    if not graph or not graph.get("figure"):
        if graph:
            from .consumer_state import omit
            omit(document, chapter, f"{chapter}.{sub} 知识子图", "no_ready_subgraph", "正文知识子图尚无可用的已渲染图片")
        return []
    _mark_displayed(document, graph)
    return [graph["caption"], f"![{graph['caption']}]({graph['figure']})", *_reading_note(document)]


def graph_markdown(topic: dict, *, document=None, placement="inline") -> list[str]:
    from .document import text

    if graph_mode() == "off" or placement == "inline" and graph_mode() != "inline":
        return []
    graph = topic.get("knowledge_subgraph", {})
    if not graph.get("edges"):
        return []
    if graph.get("display_status") != "ready":
        return []
    output = ["**相关知识子图**"]
    if graph.get("figure"):
        output.append(f"![{text(topic['title'])}相关知识子图]({graph['figure']})")
        if document is not None:
            if placement == "inline":
                _mark_displayed(document, graph)
            output.extend(_reading_note(document))
    else:
        return []
    return output
