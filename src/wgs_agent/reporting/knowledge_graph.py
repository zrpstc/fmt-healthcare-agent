"""Bounded report subgraphs made only from retrieved, attributable LitKG claims."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path

import httpx

from .catalog import SECTIONS

MAX_EDGES = 6
MAX_NODES = 12
TOPIC_KEYWORDS = {f"{s.id}.{t.id}": t.keywords for s in SECTIONS for t in s.topics}


def _normal(value: object) -> str:
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
    if isinstance(explicit, list) and topic["id"] in explicit:
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
        for word in TOPIC_KEYWORDS.get(topic["id"], ())
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


def _topics(document: dict):
    return (t for s in document["sections"] for t in s["topics"] if t["status"] != "missing")


async def enrich_document(document: dict, *, transport=None) -> None:
    """Retrieve once per report and retain only topic-relevant claims, before narration.

    Existing bound evidence survives outages. The scan is bounded and audited;
    no whole-graph endpoint or patient measurements are sent to LitKG.
    """
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
            while len(raw) < limit:
                size = min(500, limit - len(raw))
                response = await client.get(
                    f"/knowledge-bases/{kb}/claims", params={"limit": size, "offset": len(raw)}
                )
                response.raise_for_status()
                payload = response.json()
                page = payload.get("claims") if isinstance(payload, dict) else None
                if not isinstance(page, list) or any(not isinstance(r, dict) for r in page):
                    raise ValueError("invalid Claim response")
                total = payload.get("total")
                raw.extend(page[:size])
                if len(page) < size or (isinstance(total, int) and len(raw) >= total):
                    break
        from wgs_agent.tools.knowledge_tools import claim_record_to_reference

        references = []
        for row in raw:
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
                "display_negated",
                "page",
                "page_end",
                "section_title",
                "title",
            ):
                if field in row:
                    item[field] = row[field]
            references.append(item)
        evidence = document["evidence"]
        document["references"] = copy.deepcopy(document.get("references") or {})
        supplied = document["references"].get("matched_docs", [])
        matched = (
            [row for row in supplied if isinstance(row, dict)] if isinstance(supplied, list) else []
        )
        document["references"]["matched_docs"] = matched
        by_claim = {str(r.get("claim_id")): key for key, r in evidence.items() if r.get("claim_id")}
        for topic in _topics(document):
            ranked = sorted(
                (r for r in references if _score(r, topic, evidence)),
                key=lambda r: (_score(r, topic, evidence), _confidence(r), str(r.get("claim_id"))),
                reverse=True,
            )
            for row in ranked[:8]:
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
            status="complete",
            scanned_claims=len(raw),
            total_claims=total,
            scan_truncated=isinstance(total, int) and total > len(raw),
            knowledge_base_id=kb,
        )
        audit["selected_sha256"] = hashlib.sha256(
            json.dumps(matched, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        audit.update(status="unavailable", error_type=type(exc).__name__)


def build_topic_graph(document: dict, topic: dict) -> dict:
    """A one-hop evidence subgraph; no inferred edges or background expansion."""
    graph = {
        "status": "no_match",
        "nodes": [],
        "edges": [],
        "candidate_count": 0,
        "truncated": False,
        "max_edges": MAX_EDGES,
        "max_nodes": MAX_NODES,
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
    keys = cited if cited else topic.get("allowed_narrative_ids", [])
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
    candidates.sort(key=lambda r: (-r[2], -_confidence(r[1]), r[0]))
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
            len(graph["edges"]) >= MAX_EDGES
            or len(set(nodes) | {n["id"] for n in pair}) > MAX_NODES
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


def graph_markdown(topic: dict) -> list[str]:
    from .document import text

    graph = topic.get("knowledge_subgraph", {})
    if not graph.get("edges"):
        return []
    if graph.get("display_status") != "ready":
        return []
    output = ["**相关知识子图**"]
    if graph.get("figure"):
        output.append(f"![{text(topic['title'])}相关知识子图]({graph['figure']})")
    return output
