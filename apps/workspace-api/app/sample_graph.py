"""Deterministic sample relevance ranking over attributable, direct LitKG claims."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata


def normal(value: object) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = re.sub(r"\b[dkpcofgs]__", "", value)
    return " ".join(re.sub(r"[^\w\u4e00-\u9fff]+", " ", value.replace("_", " ")).split())


def confidence(value: object) -> float:
    try:
        result = float(value or 0)
        return min(1.0, max(0.0, result)) if math.isfinite(result) else 0.0
    except (ValueError, TypeError):
        return 0.0


def sample_features(analysis: dict, report: dict) -> list[dict]:
    """Use biological identifying fields; never sample names, prose or filenames."""
    features: dict[str, dict] = {}
    names = ("species", "name", "chinese_name", "disease", "gene", "gene_family",
             "pathway", "feature_name", "feature_id", "normalized_id", "id")

    def visit(value):
        if isinstance(value, list):
            for row in value:
                visit(row)
        elif isinstance(value, dict):
            if value.get("kind") == "literature":
                return
            abundance = value.get("abundance")
            if abundance is None and value.get("feature_type") in {"microbe", "species", "pathway"}:
                abundance = value.get("value")
            try:
                if abundance is not None and float(abundance) <= 0:
                    return
            except (TypeError, ValueError):
                pass
            # Container nodes can hold nested comparison rows instead of scalar flags.
            abnormal = (
                value.get("status") in ("high", "low")
                or value.get("comparison") in ("above", "below")
            )
            for field in names:
                label = value.get(field)
                if not isinstance(label, str):
                    continue
                # Slash/parenthesis aliases and taxonomic rank names are explicit identifiers.
                aliases = re.split(r"[|/]", label)
                aliases += [re.split(r"[（(]", alias)[0] for alias in aliases]
                for alias in aliases:
                    key = normal(alias)
                    if len(key) < 3 or key in {"unknown", "unmapped", "unintegrated", "other"}:
                        continue
                    weight = 75 if abnormal else 50
                    if key not in features or weight > features[key]["weight"]:
                        features[key] = {"name": alias.strip(), "normalized": key, "weight": weight,
                                         "abnormal": abnormal}
            for child in value.values():
                if isinstance(child, (list, dict)):
                    visit(child)

    for key in ("species", "taxonomy", "compare", "pathways", "metabolites", "diseases", "drugs",
                "proteins", "health_inputs", "features"):
        visit(analysis.get(key))
    for row in (report.get("evidence") or {}).values():
        if isinstance(row, dict) and row.get("kind") != "literature":
            visit(row)
    return sorted(features.values(), key=lambda row: (-row["weight"], row["normalized"]))


def bound_references(analysis: dict, knowledge: dict, report: dict) -> tuple[list[dict], set[str]]:
    rows: list[dict] = []
    for source in (knowledge, analysis.get("knowledge") or {}, report.get("references") or {}):
        rows.extend(row for row in source.get("matched_docs", []) if isinstance(row, dict))
    evidence = report.get("evidence") or {}
    rows.extend(row for row in evidence.values() if isinstance(row, dict) and row.get("claim_id"))
    cited = {
        str(evidence[key].get("claim_id"))
        for section in report.get("sections", [])
        for topic in section.get("topics", [])
        for key in topic.get("narrative_evidence_ids", [])
        if isinstance(evidence.get(key), dict) and evidence[key].get("claim_id")
    }
    return rows, cited


def build_sample_graph(analysis: dict, knowledge: dict, report: dict, claims: list[dict], *,
                       sample_id: str, knowledge_base_id: int, limit: int = 40) -> dict:
    features = sample_features(analysis, report)
    feature_index = {row["normalized"]: row for row in features}

    def matches_for(label: str) -> list[dict]:
        tokens = normal(label).split()
        return [feature_index[prefix] for end in range(1, len(tokens) + 1)
                if (prefix := " ".join(tokens[:end])) in feature_index]
    bound, cited = bound_references(analysis, knowledge, report)
    by_claim: dict[tuple[str, str], dict] = {}
    bound_ids: set[tuple[str, str]] = set()
    # Remote rows enrich historical references without dropping their endpoint identities.
    for row in [*bound, *claims]:
        identifier = row.get("claim_id") or (f"litkg:claim:{row['id']}" if row.get("id") is not None else None)
        if not identifier:
            continue
        scope = str(row.get("knowledge_base_id") or knowledge_base_id)
        identity = (scope, str(identifier))
        by_claim[identity] = {**by_claim.get(identity, {}), **row, "claim_id": str(identifier),
                              "knowledge_base_id": scope}
    for row in bound:
        if row.get("claim_id"):
            bound_ids.add((str(row.get("knowledge_base_id") or knowledge_base_id), str(row["claim_id"])))

    ranked = []
    for identity, row in by_claim.items():
        subject = str(row.get("subject_text") or row.get("subject") or "").strip()
        obj = str(row.get("object_text") or row.get("object") or "").strip()
        if not subject or not obj or not row.get("predicate") or not row.get("evidence_text"):
            continue
        matches = sorted({row["normalized"]: row for label in (subject, obj)
                          for row in matches_for(label)}.values(),
                         key=lambda row: (-row["weight"], row["normalized"]))
        is_bound, is_cited = identity in bound_ids, identity[1] in cited
        if not matches and not is_bound and not is_cited:
            continue
        score = (30 if is_cited else 0) + (15 if is_bound else 0) + sum(m["weight"] for m in matches[:4])
        reasons = (["报告已引用"] if is_cited else []) + (["样本已保存证据"] if is_bound else [])
        reasons += [f"{'异常检测实体' if m['abnormal'] else '检测实体'}：{m['name']}" for m in matches[:4]]
        ranked.append({**row, "subject": subject, "object": obj, "relevance_score": score,
                       "match_reasons": reasons, "matched_features": [m["name"] for m in matches],
                       "cited_in_analysis": is_cited, "bound_to_sample": is_bound})
    ranked.sort(key=lambda r: (-r["relevance_score"], -confidence(r.get("confidence")), r["claim_id"]))

    nodes, edges = {}, []
    for row in ranked[:limit]:
        pair = []
        for role in ("subject", "object"):
            label = row[role]
            kind = str(row.get(role + "_type") or "Other")
            entity = row.get(role + "_entity_id")
            normalized_id = row.get(role + "_normalized_id")
            identity = (f"entity:{entity}" if entity is not None else f"{kind}:{normalized_id or normal(label)}")
            identifier = "n" + hashlib.sha256(f"{row['knowledge_base_id']}:{identity}".encode()).hexdigest()[:20]
            nodes.setdefault(identifier, {"id": identifier, "label": label, "type": kind,
                                           "normalized_id": normalized_id, "matched_features": []})
            matched = [f["name"] for f in matches_for(label)]
            nodes[identifier]["matched_features"] = matched
            pair.append(identifier)
        edges.append({
            **{key: row.get(key) for key in ("claim_id", "knowledge_base_id", "document_id", "filename",
                "predicate", "negated", "display_negated", "speculative", "review_status", "result_status",
                "qualifiers", "process", "page", "page_end", "source_url", "relevance_score", "match_reasons",
                "matched_features", "cited_in_analysis", "bound_to_sample")},
            "id": f"{row['knowledge_base_id']}:{row['claim_id']}", "source": pair[0], "target": pair[1],
            "label": row["predicate"], "confidence": confidence(row.get("confidence")),
            "evidence": row["evidence_text"], "evidence_count": 1,
            "document_count": int(row.get("document_id") is not None),
            "evidence_samples": [{"claim_id": row["claim_id"], "document_id": row.get("document_id"),
                "filename": row.get("filename"), "sentence": row["evidence_text"],
                "title": row.get("title"), "doi": row.get("doi"), "page": row.get("page")}],
        })
    documents = {str(r["document_id"]) for r in edges if r.get("document_id") is not None}
    return {"sample_id": sample_id, "knowledge_base_id": knowledge_base_id, "nodes": list(nodes.values()),
            "edges": edges, "summary": {"node_count": len(nodes), "relation_count": len(edges),
                "represented_document_count": len(documents)},
            "selection": {"method": "sample_entity_and_bound_evidence", "candidate_count": len(ranked),
                "feature_count": len(features), "truncated": len(ranked) > limit,
                "matched_feature_count": len({name for row in edges for name in row["matched_features"]}),
                "ranking": "优先匹配样本检测实体和异常项；报告引用与样本已保存证据加权，置信度用于同分排序。"}}
