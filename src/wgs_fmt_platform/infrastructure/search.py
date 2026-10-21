from __future__ import annotations

from typing import Any

import httpx
from elasticsearch import Elasticsearch

from wgs_fmt_platform.config import get_settings
from wgs_fmt_platform.knowledge.litkg_catalog import normalize_knowledge_bases, select_knowledge_bases


class HybridKnowledgeSearch:
    def __init__(self, client: Elasticsearch | None = None) -> None:
        settings = get_settings()
        kwargs: dict[str, Any] = {}
        if settings.elasticsearch_api_key:
            kwargs["api_key"] = settings.elasticsearch_api_key
        self.client = client or Elasticsearch(settings.elasticsearch_url, **kwargs)
        self.index = settings.elasticsearch_index
        self.dimensions = settings.embedding_dimensions
        self.settings = settings

    def ensure_index(self) -> None:
        if self.client.indices.exists(index=self.index):
            return
        self.client.indices.create(index=self.index, mappings={"properties": {"title": {"type": "text"}, "content": {"type": "text"}, "source": {"type": "keyword"}, "document_id": {"type": "keyword"}, "metadata": {"type": "object", "enabled": False}, "embedding": {"type": "dense_vector", "dims": self.dimensions, "index": True, "similarity": "cosine"}}})

    def index_document(self, document_id: str, *, title: str, content: str, source: str, embedding: list[float] | None = None, metadata: dict[str, Any] | None = None) -> None:
        if embedding is not None and len(embedding) != self.dimensions:
            raise ValueError(f"embedding must contain {self.dimensions} values")
        body: dict[str, Any] = {"title": title, "content": content, "source": source, "document_id": document_id, "metadata": metadata or {}}
        if embedding is not None:
            body["embedding"] = embedding
        self.client.index(index=self.index, id=document_id, document=body, refresh=False)

    @staticmethod
    def _merge(rankings: list[list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for ranking in rankings:
            for rank, item in enumerate(ranking, 1):
                key = str(item.get("id"))
                row = merged.setdefault(key, {**item, "score": 0.0, "channels": []})
                row["score"] += 1.0 / (60 + rank)
                row["channels"].append(item.get("channel", "unknown"))
        return sorted(merged.values(), key=lambda row: row["score"], reverse=True)[:limit]

    def search(self, query: str, *, vector: list[float] | None = None, limit: int = 10) -> list[dict[str, Any]]:
        keyword = self.client.search(index=self.index, query={"multi_match": {"query": query, "fields": ["title^2", "content"]}}, size=limit)
        keyword_rows = [{"id": hit["_id"], **hit["_source"], "channel": "keyword", "raw_score": hit["_score"]} for hit in keyword["hits"]["hits"]]
        rankings = [keyword_rows]
        if vector is not None:
            if len(vector) != self.dimensions:
                raise ValueError(f"query vector must contain {self.dimensions} values")
            dense = self.client.search(index=self.index, knn={"field": "embedding", "query_vector": vector, "k": limit, "num_candidates": max(50, limit * 5)}, size=limit)
            rankings.append([{"id": hit["_id"], **hit["_source"], "channel": "vector", "raw_score": hit["_score"]} for hit in dense["hits"]["hits"]])
        return self._merge(rankings, limit)

    async def graph_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.settings.claim_api_token}"} if self.settings.claim_api_token else {}
        async with httpx.AsyncClient(base_url=self.settings.claim_api_url, headers=headers, timeout=self.settings.claim_api_timeout) as client:
            catalog_response = await client.get("/knowledge-bases")
            catalog_response.raise_for_status()
            selected = select_knowledge_bases(
                normalize_knowledge_bases(catalog_response.json()),
                configured_ids=self.settings.claim_api_knowledge_base_ids,
            )
            results: list[dict[str, Any]] = []
            for knowledge_base in selected:
                knowledge_base_id = int(knowledge_base["id"])
                path = self.settings.graph_text_search_path.format(knowledge_base_id=knowledge_base_id)
                response = await client.get(path, params={"query": query, "limit": limit})
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("relations", payload.get("claims", payload.get("items", payload if isinstance(payload, list) else [])))
                for index, row in enumerate(rows[:limit]):
                    subject = row.get("subject") if isinstance(row.get("subject"), dict) else {}
                    object_ = row.get("object") if isinstance(row.get("object"), dict) else {}
                    subject_text = subject.get("text") or row.get("subject_text", "")
                    object_text = object_.get("text") or row.get("object_text", "")
                    results.append({
                        "id": f"graph:{knowledge_base_id}:{row.get('id', index)}",
                        "title": f"{subject_text} → {object_text}",
                        "content": row.get("evidence", row.get("evidence_text", row.get("sentence", ""))),
                        "source": "knowledge-graph",
                        "channel": "graph",
                        "metadata": {**row, "knowledge_base_id": knowledge_base_id, "knowledge_base_name": knowledge_base["name"]},
                    })
        return results[:limit]

    async def fused_search(self, query: str, *, vector: list[float] | None = None, limit: int = 10) -> dict[str, Any]:
        errors: list[str] = []
        try:
            elastic = self.search(query, vector=vector, limit=limit)
        except Exception as exc:
            elastic = []
            errors.append(f"elasticsearch: {exc}")
        try:
            graph = await self.graph_search(query, limit)
        except Exception as exc:
            graph = []
            errors.append(f"knowledge_graph: {exc}")
        return {"results": self._merge([elastic, graph], limit), "errors": errors, "degraded": bool(errors)}
