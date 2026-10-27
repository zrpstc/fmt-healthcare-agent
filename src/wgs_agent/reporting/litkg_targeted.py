"""Retrieve report-specific LitKG facts without scanning the whole library."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time

import httpx

from wgs_fmt_platform.knowledge.litkg_retrieval import LitkgRetrievalConfig, LitkgRetrievalError, pack_evidence, evidence_references
from .litkg_claims import _cache_file

SCHEMA = "litkg-report-query-v1"


def report_queries(document):
    from .chapter_three import selected_rows
    from .knowledge_graph import _topics, TOPIC_KEYWORDS
    queries = []
    for row in selected_rows(document, 1) + selected_rows(document, 2):
        value = row.get("species") or row.get("name") or row.get("label")
        if value:
            queries.append(str(value))
    for topic in _topics(document):
        keywords = TOPIC_KEYWORDS.get(topic["id"], ())
        if not keywords:
            continue
        english = [str(w) for w in keywords if str(w).isascii()]
        queries.append(" ".join((english or list(map(str, keywords)))[:2]))
    result, seen = [], set()
    for query in queries:
        query = " ".join(query.split())[:180]
        if query and query.casefold() not in seen:
            result.append(query)
            seen.add(query.casefold())
    return result[:48]


def _path(client, kb, query, cache_dir):
    path, identity = _cache_file(client, kb, cache_dir)
    if path is None:
        return None, None
    key = hashlib.sha256(query.casefold().encode()).hexdigest()[:20]
    return path.with_name(path.stem + "-q-" + key + ".json"), identity


def _read(path, identity, query):
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA or data.get("identity") != identity or data.get("query") != query:
            return None
        rows = data.get("references")
        kb = json.loads(identity)[-1]
        if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get("claim_id"), str) or not r.get("claim_id") or not isinstance(r.get("evidence_text"), str) or not r.get("evidence_text") or r.get("knowledge_base_id") != kb for r in rows):
            return None
        if not 0 <= time.time() - data["fetched_at"] <= 86400:
            return None
        return data
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _save(path, identity, query, rows):
    if path is None:
        return
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".query-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"schema": SCHEMA, "identity": identity, "query": query, "fetched_at": time.time(), "references": rows}, handle, ensure_ascii=False, allow_nan=False)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError):
        pass
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _types(row):
    row = dict(row)
    for role in ("subject", "object"):
        entities = [p for p in row.get("participants", []) if p.get("role") == role]
        if len(entities) == 1:
            for source, target in [("type", role + "_type"), ("entity_id", role + "_entity_id"), ("normalized_id", role + "_normalized_id")]:
                if entities[0].get(source) is not None:
                    row[target] = entities[0][source]
    return row


async def retrieve_report_references(client, knowledge_base_id, document, limit, *, cache_dir=None):
    queries = report_queries(document)
    if not queries:
        return [], {"status": "complete", "source": "targeted", "search_scope": "report_entities_and_topics", "reference_rows": True, "knowledge_base_id": knowledge_base_id, "query_count": 0, "total_claims": None, "scan_truncated": False}
    public_base = httpx.URL(scheme=client.base_url.scheme, host=client.base_url.host, port=client.base_url.port, path=client.base_url.path)
    config = LitkgRetrievalConfig(str(public_base).rstrip("/"), knowledge_base_id, hops=1)
    semaphore = asyncio.Semaphore(3)

    async def query_once(query):
        path, identity = _path(client, knowledge_base_id, query, cache_dir)
        snapshot = _read(path, identity, query)
        async with semaphore:
            for attempt in range(2):
                try:
                    response = await client.post(f"/knowledge-bases/{knowledge_base_id}/ask", json={"question": query, "limit": 30, "hops": 1, "generate": False})
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict) or payload.get("knowledge_base_id") != knowledge_base_id:
                        raise ValueError("invalid_litkg_query_scope")
                    packed = pack_evidence(payload, query, 30, config)
                    rows = [_types(r) for r in evidence_references(packed)]
                    _save(path, identity, query, rows)
                    return {"references": rows, "source": "live", "retry_count": attempt}
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in {429, 500, 502, 503, 504}:
                        raise
                    error = exc
                except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, ValueError, LitkgRetrievalError) as exc:
                    error = exc
                if attempt == 0:
                    await asyncio.sleep(.2)
            if snapshot:
                return {"references": snapshot["references"], "source": "snapshot", "error_type": type(error).__name__, "fetched_at": snapshot["fetched_at"], "retry_count": 1}
            return {"references": [], "source": "failed", "error_type": type(error).__name__, "retry_count": 1}

    # Verify the endpoint before launching the remaining bounded requests.
    first = await query_once(queries[0])
    if first["source"] == "live":
        results = [first, *await asyncio.gather(*(query_once(q) for q in queries[1:]))]
    else:
        # A failing service probe must not trigger dozens of repeated timeouts.
        results = [first]
        for query in queries[1:]:
            path, identity = _path(client, knowledge_base_id, query, cache_dir)
            snapshot = _read(path, identity, query)
            results.append({"references": snapshot["references"] if snapshot else [], "source": "snapshot" if snapshot else "failed", "error_type": first["error_type"], "fetched_at": snapshot["fetched_at"] if snapshot else None})
    merged = {}
    functional = {"PRODUCES", "CONSUMES", "DEGRADES", "UTILIZES", "TRANSFORMS", "FERMENTS"}
    for result in results:
        for row in result["references"]:
            identity = (row.get("knowledge_base_id"), str(row["claim_id"]))
            previous = merged.get(identity)
            rank = (row.get("predicate") in functional, len(str(row.get("evidence_text", ""))))
            if previous is None or rank > (previous.get("predicate") in functional, len(str(previous.get("evidence_text", "")))):
                merged[identity] = row
    rows = list(merged.values())[:limit]
    failures = [r for r in results if r["source"] == "failed"]
    snapshots = [r for r in results if r["source"] == "snapshot"]
    status = "partial" if failures else "cached" if snapshots else "complete"
    if len(failures) == len(results):
        status = "unavailable"
    metadata = {"status": status, "source": "targeted_with_snapshot" if snapshots else "targeted", "search_scope": "report_entities_and_topics", "reference_rows": True, "knowledge_base_id": knowledge_base_id, "query_count": len(queries), "successful_queries": len(results) - len(failures), "failed_queries": len(failures), "snapshot_queries": len(snapshots), "retry_count": sum(r.get("retry_count", 0) for r in results), "total_claims": None, "scan_truncated": bool(failures) or len(merged) > limit, "retrieved_reference_count": len(rows)}
    if failures or snapshots:
        metadata["refresh_error_type"] = (failures or snapshots)[0]["error_type"]
    if snapshots:
        metadata["cache_fetched_at"] = min(r["fetched_at"] for r in snapshots)
        metadata["cache_age_seconds"] = round(time.time() - metadata["cache_fetched_at"])
    if status == "unavailable":
        metadata["error_type"] = metadata["refresh_error_type"]
    return rows, metadata
