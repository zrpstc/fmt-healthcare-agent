"""Module-grouped bibliographies derived from sources actually used in the report."""

from __future__ import annotations

import re
import html
from pathlib import PurePath


def _clean(value) -> str:
    value = re.sub(r"<[^>]*>", "", html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", value).strip().replace("|", "／")


def _identity(row: dict) -> str:
    for field in ("doi", "pmid", "title", "document_id", "filename", "url"):
        if row.get(field):
            return field + ":" + _clean(row[field]).casefold().removeprefix("https://doi.org/")
    return ""


def citation(row: dict) -> str:
    """Paper-style citation; absent bibliographic fields are omitted, never guessed."""
    authors = row.get("authors", row.get("author"))
    if isinstance(authors, list):
        authors = ", ".join(
            _clean(r.get("name") or " ".join(str(v) for v in r.values()))
            if isinstance(r, dict)
            else _clean(r)
            for r in authors[:3]
        ) + (", et al" if len(authors) > 3 else "")
    title = _clean(row.get("title"))
    if not title and row.get("filename"):
        title = PurePath(str(row["filename"])).stem.replace("_", " ")
    title = title or "题名未提供的知识库文献"
    parts = [_clean(authors), title]
    journal = _clean(row.get("journal") or row.get("journal_name"))
    year = _clean(row.get("publication_year") or row.get("year"))
    volume = _clean(row.get("volume"))
    if row.get("issue"):
        volume += f"({_clean(row['issue'])})"
    if row.get("pages"):
        volume += ": " + _clean(row["pages"])
    publication = ", ".join(v for v in (journal, year, volume) if v)
    parts.append(publication)
    doi = _clean(row.get("doi")).removeprefix("https://doi.org/")
    if doi:
        parts.append("DOI: " + doi)
    elif row.get("pmid"):
        parts.append("PMID: " + _clean(row["pmid"]))
    elif row.get("url"):
        parts.append(_clean(row["url"]))
    return ". ".join(part.rstrip(".。 ") for part in parts if part) + "."


def module_bibliographies(document: dict) -> list[dict]:
    evidence = document["evidence"]
    result = []
    methods = {
        "composition": ("R1",),
        "diversity": ("R1",),
        "key_taxa": ("R1",),
        "ecology": ("R1", "R4"),
        "nutrient_metabolism": ("R1", "R4"),
        "metabolites": ("R1", "R4"),
        "gut_brain": ("R1", "R4"),
    }
    for section in document["sections"]:
        keys = []
        available = [t for t in section["topics"] if t["status"] != "missing"]
        for topic in available:
            keys.extend(topic.get("narrative_evidence_ids", []))
            keys.extend(
                e["evidence_id"] for e in topic.get("knowledge_subgraph", {}).get("edges", [])
            )
        if available:
            keys.extend(methods.get(section["id"], ()))
        papers = {}
        for key in dict.fromkeys(keys):
            row = evidence.get(key, {})
            if row.get("kind") not in {"literature", "method_reference"}:
                continue
            identity = _identity(row)
            if not identity:
                continue
            if identity not in papers:
                papers[identity] = {"citation": citation(row), "evidence_ids": [], "source": row}
            papers[identity]["evidence_ids"].append(key)
        if papers:
            result.append(
                {
                    "id": section["id"],
                    "title": section["title"],
                    "references": list(papers.values()),
                }
            )
    return result


def render_bibliographies(document: dict) -> list[str]:
    modules = module_bibliographies(document)
    document["module_bibliographies"] = modules
    output = ["### 分模块参考文献"]
    for module in modules:
        output.append(f"#### {module['title']}")
        output.extend(f"[{i}] {row['citation']}" for i, row in enumerate(module["references"], 1))
    return output
