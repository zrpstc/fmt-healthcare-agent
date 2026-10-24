from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, Field

from wgs_agent.core.tools.base import BaseTool, ToolResult
from wgs_fmt_platform.paths import knowledge_db_path, runtime_path
from wgs_fmt_platform.knowledge.litkg_retrieval import (
    LitkgRetrievalError, evidence_references, render_evidence, retrieve_litkg,
)


class KnowledgeSearchParams(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="具体科研问题，优先英文专业术语")
    max_results: int = Field(10, ge=1, le=50, description="最大返回结果数")


class PubmedSearchParams(BaseModel):
    query: str = Field(..., description="PubMed 搜索查询词")
    max_results: int = Field(5, ge=1, le=20, description="最大返回文献数")


# ============================================================================
# Tool 9: 本地知识库搜索
# ============================================================================


class KnowledgeSearchTool(BaseTool):
    name = "search_knowledge_base"
    description = (
        "检索正式 LitKG 知识库的 /ask 接口（generate=false），返回关联事实、原文引用、"
        "页码、条件和检索告警。优先用英文科研问题/术语；不生成最终答案、不扫描首批 Claim。"
    )
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 2000, "description": "具体科研问题，优先英文术语/同义词"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 30, "description": "最多返回的事实条数", "default": 12},
        },
        "required": ["query"],
    }
    params_model = KnowledgeSearchParams

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        try:
            values = self.params_model.model_validate(params)
            result = await retrieve_litkg(values.query, values.max_results)
            # An empty /ask result is authoritative for this query. Never silently
            # replace it with a different local knowledge base.
            return ToolResult(content=render_evidence(result))
        except Exception as exc:
            message = str(exc) if isinstance(exc, LitkgRetrievalError) else f"知识库检索异常（{type(exc).__name__}）"
            if os.environ.get("WGS_CLAIM_API_LOCAL_FALLBACK", "false").lower() not in {"true", "1"}:
                return ToolResult(content=json.dumps({"source": "litkg-ask", "status": "unavailable", "error": message,
                    "warnings": ["未取得 LitKG 证据；不能据此判断没有相关研究。可重试或使用 PubMed 补充。"]}, ensure_ascii=False), is_error=True, error_type="runtime_error")
            return self._local_fallback(params, message)

    @staticmethod
    def _local_fallback(params: dict[str, object], error: str) -> ToolResult:
        """An explicit offline option, always labelled as a different source."""
        try:
            query = str(params.get("query", ""))
            limit = max(1, min(int(params.get("max_results", 12)), 30))
            db_path = str(knowledge_db_path())
            content = _sql_search(db_path, query, limit) if os.path.isfile(db_path) else ""
            if not content:
                rows = _grep_search(_get_kb_dir(), query, limit)
                content = "\n\n".join(f"{r['title']}\n{r['path']}\n{r['snippet'][:500]}" for r in rows)
            return ToolResult(content=json.dumps({"source": {"kind": "local-fallback", "primary": False},
                "status": "degraded", "warnings": [error, "当前使用本地 SQLite/Markdown 降级结果，不是 LitKG /ask 召回。"],
                "content": content or "本地降级检索也未命中"}, ensure_ascii=False))
        except Exception as exc:
            return ToolResult(content=f"LitKG 与本地降级检索均失败（{type(exc).__name__}）", is_error=True, error_type="runtime_error")


# ============================================================================
# Tool 10: PubMed 外源文献搜索
# ============================================================================


class PubmedSearchTool(BaseTool):
    name = "search_pubmed"
    description = (
        "通过 PubMed E-utilities API 搜索生物医学文献。"
        "返回文献标题、摘要、作者、期刊、PMID 等信息。需要网络连接。"
    )
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "PubMed 搜索查询词"},
            "max_results": {"type": "integer", "description": "最大返回数", "default": 5},
        },
        "required": ["query"],
    }
    params_model = PubmedSearchParams

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        try:
            import time
            import urllib.parse
            import urllib.request
            import xml.etree.ElementTree as ET

            query = str(params["query"])
            max_results = int(params.get("max_results", 5))

            email = os.environ.get("PUBMED_EMAIL", "user@example.com")
            api_key = os.environ.get("PUBMED_API_KEY", "")

            # Step 1: ESearch — 获取 PMID 列表
            esearch_params = {
                "db": "pubmed",
                "term": query,
                "retmax": str(min(max_results, 20)),
                "retmode": "json",
                "sort": "relevance",
                "tool": "wgs-agent",
                "email": email,
            }
            if api_key:
                esearch_params["api_key"] = api_key

            esearch_url = (
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
                + urllib.parse.urlencode(esearch_params)
            )

            with urllib.request.urlopen(esearch_url, timeout=10) as resp:
                esearch_data = json.loads(resp.read())

            id_list = esearch_data.get("esearchresult", {}).get("idlist", [])
            if not id_list:
                return ToolResult(content=f"PubMed 未找到与 '{query}' 相关的结果")

            # 速率限制
            time.sleep(0.35)

            # Step 2: EFetch — 获取摘要
            efetch_params = {
                "db": "pubmed",
                "id": ",".join(id_list[:max_results]),
                "retmode": "xml",
                "tool": "wgs-agent",
                "email": email,
            }
            if api_key:
                efetch_params["api_key"] = api_key

            efetch_url = (
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"
                + urllib.parse.urlencode(efetch_params)
            )

            with urllib.request.urlopen(efetch_url, timeout=15) as resp:
                xml_data = resp.read()

            root = ET.fromstring(xml_data)
            articles = []
            for article in root.findall(".//PubmedArticle"):
                title_elem = article.find(".//ArticleTitle")
                pmid_elem = article.find(".//PMID")

                title = "".join(title_elem.itertext()).strip() if title_elem is not None else "无标题"
                sections = []
                for section in article.findall(".//Abstract/AbstractText"):
                    text = "".join(section.itertext()).strip()
                    if text:
                        label = section.get("Label", "")
                        sections.append(f"{label}: {text}" if label else text)
                abstract = "\n".join(sections) or "无摘要"
                pmid = (pmid_elem.text or "") if pmid_elem is not None else ""

                # 作者
                authors = []
                for author in article.findall(".//Author"):
                    last = author.find("LastName")
                    first = author.find("ForeName")
                    if last is not None:
                        name = last.text or ""
                        if first is not None and first.text:
                            name += " " + first.text
                        authors.append(name)
                authors_str = ", ".join(authors[:5])

                # 期刊
                journal = article.find(".//Journal/Title")
                year = article.find(".//PubDate/Year")
                volume = article.find(".//Journal/JournalIssue/Volume")
                issue = article.find(".//Journal/JournalIssue/Issue")
                pagination = article.find(".//Pagination/MedlinePgn")

                # DOI
                doi = ""
                for eid in article.findall(".//ELocationID"):
                    if eid.get("EIdType") == "doi":
                        doi = eid.text or ""
                        break
                if not doi:
                    for aid in article.findall(".//ArticleId"):
                        if aid.get("IdType") == "doi":
                            doi = aid.text or ""
                            break

                articles.append({
                    "pmid": pmid,
                    "title": title,
                    "abstract": abstract[:2000],
                    "abstract_truncated": len(abstract) > 2000,
                    "publication_types": ["".join(item.itertext()).strip() for item in article.findall(".//PublicationType")],
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                    "authors": authors_str,
                    "journal": journal.text if journal is not None else "",
                    "year": year.text if year is not None else "",
                    "volume": volume.text if volume is not None else "",
                    "issue": issue.text if issue is not None else "",
                    "pages": pagination.text if pagination is not None else "",
                    "doi": doi,
                })

            lines = [f"PubMed 搜索结果 ({len(articles)} 篇, 查询: '{query}'):\n"]
            for i, a in enumerate(articles, 1):
                lines.append(
                    f"---\n"
                    f"[{i}] PMID: {a['pmid']}\n"
                    f"标题: {a['title']}\n"
                    f"作者: {a['authors']}\n"
                    f"期刊: {a['journal']} ({a['year']})\n"
                    f"摘要: {a['abstract'][:400]}..."
                )

            content = "\n".join(lines)
            json_key = "---JSON---"
            structured = [{
                "pmid": a["pmid"],
                "title": a["title"],
                "authors": a["authors"],
                "journal": a["journal"],
                "year": a["year"],
                "volume": a["volume"],
                "issue": a["issue"],
                "pages": a["pages"],
                "doi": a["doi"],
                "abstract": a["abstract"],
                "abstract_truncated": a["abstract_truncated"],
                "publication_types": a["publication_types"],
                "url": a["url"],
            } for a in articles]
            content = content + "\n" + json_key + "\n" + json.dumps(structured, ensure_ascii=False, default=str)
            return ToolResult(content=content)

        except Exception as exc:
            return ToolResult(
                content=f"PubMed 搜索失败: {exc}",
                is_error=True,
                error_type="runtime_error",
            )


# ============================================================================
# 工具注册清单
# ============================================================================

KNOWLEDGE_TOOLS: list[type[BaseTool]] = [
    KnowledgeSearchTool,
    PubmedSearchTool,
]

KNOWLEDGE_TOOL_POLICIES: dict[str, dict[str, object]] = {
    "search_knowledge_base": {
        "default": "allow",
        "reason": "本地只读搜索，无副作用",
    },
    "search_pubmed": {
        "default": "allow",
        "reason": "外部 API 只读检索",
    },
}


# ============================================================================
# 本地 grep 搜索实现 (备用)
# ============================================================================


def _get_kb_dir() -> str:
    """获取知识库目录"""
    return str(runtime_path("WGS_KB_DIR", "knowledge", "documents"))


async def search_claim_references(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Legacy report references now come from evidence-only LitKG /ask retrieval."""
    return evidence_references(await retrieve_litkg(query, max_results))


def claim_record_to_reference(
    claim: dict[str, Any],
    *,
    base_url: str,
    knowledge_base_id: int,
    query: str = "",
    retrieval_score: int = 0,
) -> dict[str, Any]:
    """Normalize a raw LitKG Claim into the stable legacy-report reference contract."""
    claim_id = claim.get("id")
    document_id = claim.get("document_id")
    return {
        "claim_id": f"litkg:claim:{claim_id}",
        "raw_claim_id": claim_id,
        "knowledge_base_id": knowledge_base_id,
        "document_id": document_id,
        "filename": claim.get("filename") or "",
        **{key: claim[key] for key in ("title", "authors", "author", "journal", "journal_name", "year", "publication_year", "volume", "issue", "pages", "doi", "pmid") if claim.get(key)},
        "section_title": claim.get("section_title") or "",
        "subject": claim.get("subject_text") or "",
        "subject_type": claim.get("subject_type") or "",
        "predicate": claim.get("predicate") or "",
        "object": claim.get("object_text") or "",
        "object_type": claim.get("object_type") or "",
        "evidence_text": claim.get("evidence_text") or "",
        "confidence": claim.get("confidence"),
        "negated": bool(claim.get("negated", False)),
        "speculative": bool(claim.get("speculative", False)),
        "retrieval_score": retrieval_score,
        "query": query,
        "source_type": "litkg_claim",
        "source_id": f"document:{document_id}" if document_id is not None else "unknown",
        "source_url": (
            f"{base_url.rstrip('/')}/documents/{document_id}/claims"
            if document_id is not None
            else f"{base_url.rstrip('/')}/knowledge-bases/{knowledge_base_id}/claims"
        ),
        "knowledge_version": f"litkg:kb-{knowledge_base_id}",
    }


def _format_claim_results(query: str, matches: list[dict[str, Any]]) -> str:
    """Render Claim results for humans and append a machine-readable payload."""
    knowledge_base_id = matches[0].get("knowledge_base_id", "") if matches else ""

    lines = [
        f"LitKG Claim 搜索结果 ({len(matches)} 条, KB={knowledge_base_id}, 查询: '{query}'):\n"
    ]
    for index, claim in enumerate(matches, 1):
        lines.extend(
            [
                "---",
                f"[{index}] Claim ID: {claim.get('claim_id', 'N/A')}",
                (
                    f"{claim.get('subject', '')} "
                    f"--{claim.get('predicate', '')}--> "
                    f"{claim.get('object', '')}"
                ),
                f"证据: {claim.get('evidence_text', '')}",
                (
                    f"来源: document:{claim.get('document_id', 'N/A')} "
                    f"| {claim.get('filename', '')} | 置信度: {claim.get('confidence', 'N/A')}"
                ),
            ]
        )
    return "\n".join(lines) + "\n---JSON---\n" + json.dumps(matches, ensure_ascii=False)


async def _claim_api_search(query: str, max_results: int) -> str:
    """Backward-compatible text wrapper using the official evidence contract."""
    return render_evidence(await retrieve_litkg(query, max_results))


def _sql_search(db_path: str, query: str, max_results: int) -> str:
    """使用 SQLite 结构化数据库搜索文献"""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    kw = f"%{query}%"

    # 多字段模糊搜索：title, abstract, target_disease_name, 关联微生物等
    sql = """
        SELECT DISTINCT p.*,
            (SELECT GROUP_CONCAT(DISTINCT km.scientific_name)
             FROM key_microbes km WHERE km.paper_id = p.id) AS microbes,
            (SELECT GROUP_CONCAT(DISTINCT fp.pathway_name)
             FROM functional_pathways fp WHERE fp.paper_id = p.id) AS pathways
        FROM papers p
        LEFT JOIN key_microbes km ON p.id = km.paper_id
        WHERE p.title LIKE ?1
           OR p.abstract LIKE ?1
           OR p.target_disease_name LIKE ?1
           OR km.scientific_name LIKE ?1
           OR km.chinese_name LIKE ?1
        ORDER BY p.impact_factor DESC, p.publication_year DESC
        LIMIT ?
    """
    rows = conn.execute(sql, (kw, max_results)).fetchall()

    if not rows:
        conn.close()
        return ""

    lines = [
        f"\U0001F4DA 知识库结构化搜索结果 ({len(rows)} 篇, 查询: '{query}'):\n"
    ]
    for i, r in enumerate(rows, 1):
        d = dict(r)
        lines.append("---")
        lines.append(f"[{i}] PMID: {d.get('pmid', 'N/A')} | 年份: {d.get('publication_year', 'N/A')}")
        lines.append(f"标题: {d.get('title', 'N/A')[:120]}")
        if d.get('journal_name'):
            lines.append(f"期刊: {d.get('journal_name')}  (IF={d.get('impact_factor', 'N/A')})")
        if d.get('target_disease_name'):
            lines.append(f"疾病: {d.get('target_disease_name')}")
        if d.get('microbes'):
            lines.append(f"关键菌: {d['microbes'][:200]}")
        if d.get('abstract'):
            lines.append(f"摘要: {(d['abstract'] or '')[:400]}...")
    lines.append("")

    conn.close()
    return "\n".join(lines)


def _grep_search(kb_dir: str, query: str, max_results: int) -> list[dict[str, Any]]:
    """在知识库 Markdown 文件中进行关键词搜索（备用降级方案）"""
    results = []
    kb_path = os.path.abspath(kb_dir)

    if not os.path.isdir(kb_path):
        return results

    # 分词搜索（简单实现，每词都必须命中）
    terms = query.lower().split()

    for root, _, files in os.walk(kb_path):
        for fname in files:
            if not fname.endswith((".md", ".txt", ".mdx")):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    text = f.read()
            except Exception:
                continue

            text_lower = text.lower()
            match_count = sum(1 for t in terms if t in text_lower)

            if match_count > 0:
                # 提取包含第一个词的前后 300 字符作为片段
                first_pos = text_lower.find(terms[0])
                start = max(0, first_pos - 150)
                end = min(len(text), first_pos + 450)
                snippet = text[start:end].strip()

                # 标题用文件名去掉扩展名
                title = os.path.splitext(fname)[0].replace("_", " ").replace("-", " ")

                results.append({
                    "title": title,
                    "path": fpath,
                    "snippet": snippet,
                    "match_count": match_count,
                })

    results.sort(key=lambda r: -r["match_count"])
    return results[:max_results]
