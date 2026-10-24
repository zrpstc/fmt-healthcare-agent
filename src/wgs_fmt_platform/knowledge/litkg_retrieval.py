"""Retrieve evidence from the selected LitKG KB; answer generation stays in FMT."""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx


class LitkgRetrievalError(RuntimeError):
    pass


@dataclass(frozen=True)
class LitkgRetrievalConfig:
    base_url: str
    knowledge_base_id: int
    timeout: float = 20.0
    hops: int = 1
    token: str = ""
    local_fallback: bool = False

    @classmethod
    def from_env(cls) -> "LitkgRetrievalConfig":
        try:
            kb = int(os.environ.get("WGS_CLAIM_API_KNOWLEDGE_BASE_ID", "0"))
            hops = int(os.environ.get("WGS_CLAIM_API_ASK_HOPS", "1"))
            timeout = float(os.environ.get("WGS_CLAIM_API_TIMEOUT", "20"))
        except ValueError as exc:
            raise LitkgRetrievalError("LitKG KB ID、hops 或 timeout 配置无效") from exc
        if kb <= 0 or not 0 <= hops <= 2 or not 0 < timeout <= 180:
            raise LitkgRetrievalError("请配置实际 LitKG KB ID、hops=0..2 和 timeout=1..180")
        base = os.environ.get("WGS_CLAIM_API_URL", "http://127.0.0.1:8080").rstrip("/")
        if not base.startswith(("http://", "https://")):
            raise LitkgRetrievalError("LitKG API URL 未配置为 HTTP(S) 地址")
        return cls(base, kb, timeout, hops, os.environ.get("WGS_CLAIM_API_TOKEN", ""),
                   os.environ.get("WGS_CLAIM_API_LOCAL_FALLBACK", "false").lower() in {"true", "1"})


async def retrieve_litkg(
    question: str, limit: int = 12, *, config: LitkgRetrievalConfig | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    config = config or LitkgRetrievalConfig.from_env()
    question = question.strip()
    if not 1 <= len(question) <= 2000:
        raise LitkgRetrievalError("知识检索问题长度必须为 1..2000 字符")
    limit = max(1, min(int(limit), 30))
    path = f"/knowledge-bases/{config.knowledge_base_id}/ask"
    headers = {"Accept": "application/json"}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"
    try:
        async with httpx.AsyncClient(base_url=config.base_url, headers=headers,
                                     timeout=config.timeout, transport=transport) as client:
            response = await client.post(path, json={"question": question, "limit": limit,
                                                     "hops": config.hops, "generate": False})
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise LitkgRetrievalError(f"LitKG /ask 返回 HTTP {exc.response.status_code}；未回退到首批 /claims 扫描") from exc
    except (httpx.HTTPError, ValueError) as exc:
        # Never include an Authorization header, token, or raw upstream error body.
        raise LitkgRetrievalError(f"LitKG /ask 检索失败（{type(exc).__name__}）；不能据此判断知识库无相关证据") from exc
    if not isinstance(data, dict) or any(not isinstance(data.get(key), list) for key in ("facts", "citations", "warnings")):
        raise LitkgRetrievalError("LitKG /ask 响应缺少 facts/citations/warnings 数组")
    if data.get("knowledge_base_id") != config.knowledge_base_id:
        raise LitkgRetrievalError("LitKG 返回了不同知识库的检索结果，已拒绝使用")
    return pack_evidence(data, question, limit, config)


def _render(data: dict) -> str:
    return "LitKG 正式知识库检索（原文证据，由 FMT 模型整合回答）\n---JSON---\n" + json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _envelope_size(data: dict) -> int:
    # agent_chat embeds ToolResult.content in JSON. Budget the real envelope,
    # keeping facts and citations intact instead of cutting its JSON mid-string.
    return len(json.dumps({"is_error": False, "content": _render(data)}, ensure_ascii=False))


def pack_evidence(data: dict, question: str, limit: int, config: LitkgRetrievalConfig,
                  max_chars: int = 17000) -> dict:
    warnings = list(dict.fromkeys(str(value) for value in data["warnings"]))
    if len(warnings) > 20 or any(len(value) > 500 for value in warnings):
        warnings = [value[:500] for value in warnings[:20]] + ["部分上游告警过长，显示已限制"]
    citations: dict[str, list[dict]] = {}
    seen_citations = set()
    keys = {"id", "fact_id", "claim_id", "document_id", "chunk_id", "filename", "title", "doi",
            "page", "page_end", "section", "table_or_figure", "sentence", "context", "negated", "speculative", "qualifiers"}
    for raw in data["citations"]:
        if not isinstance(raw, dict) or raw.get("id") is None or raw.get("fact_id") is None or not isinstance(raw.get("sentence"), str) or not raw["sentence"].strip():
            raise LitkgRetrievalError("LitKG 返回的 citation 缺少 id/fact_id/原文 sentence")
        if str(raw["id"]) in seen_citations:
            continue
        seen_citations.add(str(raw["id"]))
        citations.setdefault(str(raw["fact_id"]), []).append({k: v for k, v in raw.items() if k in keys})
    result = {
        "source": {"kind": "litkg-ask", "primary": True, "endpoint": config.base_url,
                   "knowledge_base_id": config.knowledge_base_id, "path": f"/knowledge-bases/{config.knowledge_base_id}/ask"},
        "question": question, "generate": False, "hops": config.hops,
        "status": data.get("status", "evidence_only"), "retrieval": data.get("retrieval", "unknown"),
        "facts": [], "citations": [], "warnings": warnings,
        "received_fact_count": len(data["facts"]), "received_citation_count": len(data["citations"]),
        "omitted_fact_count": 0, "context_budget_remaining": data.get("context_budget_remaining"),
    }
    seen_facts = set()
    for raw in data["facts"]:
        if not isinstance(raw, dict) or raw.get("id") is None or not isinstance(raw.get("participants"), list):
            raise LitkgRetrievalError("LitKG 返回的 fact 缺少 id/participants")
        fact_id = str(raw["id"])
        if fact_id in seen_facts:
            continue
        seen_facts.add(fact_id)
        refs = copy.deepcopy(citations.get(fact_id, []))
        if not refs:
            result["omitted_fact_count"] += 1
            result["warnings"].append(f"fact {fact_id} 缺少可追溯引用，未用于回答")
            continue
        if len(result["facts"]) >= limit:
            result["omitted_fact_count"] += 1
            continue
        fact = {k: raw[k] for k in ("id", "predicate", "participants", "qualifiers", "negated", "speculative") if k in raw}
        fact["citation_ids"] = [ref["id"] for ref in refs]
        result["facts"].append(fact)
        result["citations"].extend(refs)
        if _envelope_size(result) > max_chars-800:
            # Context is supplementary; verbatim sentences and source anchors stay.
            for ref in result["citations"]:
                if ref.pop("context", None):
                    ref["context_omitted"] = True
            if _envelope_size(result) > max_chars-800:
                result["facts"].pop()
                del result["citations"][-len(refs):]
                result["omitted_fact_count"] += 1
    if result["omitted_fact_count"]:
        result["warnings"].append(f"输出条数或上下文预算限制：{result['omitted_fact_count']} 条事实未纳入；不代表证据不存在")
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    if not result["facts"]:
        result["status"] = "context_limited" if data["facts"] else "insufficient_evidence"
        result["query_hint"] = "本次未取得可用原文证据；英文科研术语/同义词重述问题后重试。不要据此断言没有相关研究。"
    # Reserve headroom for tool envelopes and final warning fields.
    if _envelope_size(result) > max_chars:
        raise LitkgRetrievalError("LitKG 元数据超过输出预算，未返回不完整的证据 JSON")
    return result


def render_evidence(result: dict) -> str:
    return _render(result)


def evidence_references(result: dict) -> list[dict]:
    """Keep legacy report callers compatible while using /ask, never /claims scans."""
    by_id = {str(row["id"]): row for row in result["facts"]}
    refs = []
    for citation in result["citations"]:
        fact = by_id[str(citation["fact_id"])]
        participants = fact.get("participants", [])
        claim_id = citation.get("claim_id")
        document_id = citation.get("document_id")
        refs.append({
            **citation, "citation_id": citation["id"], "fact_id": fact["id"],
            "claim_id": f"litkg:claim:{claim_id}" if claim_id is not None else f"litkg:fact:{fact['id']}",
            "raw_claim_id": claim_id, "knowledge_base_id": result["source"]["knowledge_base_id"],
            "predicate": fact.get("predicate", ""), "participants": participants,
            "subject": "; ".join(p.get("name", "") for p in participants if p.get("role") == "subject"),
            "object": "; ".join(p.get("name", "") for p in participants if p.get("role") == "object"),
            "qualifiers": fact.get("qualifiers", {}), "negated": fact.get("negated", False),
            "speculative": fact.get("speculative", False), "evidence_text": citation["sentence"],
            "source_type": "litkg_fact", "source_id": f"document:{document_id}" if document_id is not None else "unknown",
            "source_url": f"{result['source']['endpoint']}/knowledge-bases/{result['source']['knowledge_base_id']}/facts?document_id={document_id}" if document_id is not None else "",
            "knowledge_version": f"litkg:kb-{result['source']['knowledge_base_id']}",
            "query": result["question"], "retrieval": result["retrieval"],
        })
    return refs
