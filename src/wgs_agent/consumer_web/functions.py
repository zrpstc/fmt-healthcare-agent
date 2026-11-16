"""Functional category aggregation and substrate/vitamin evidence.

The professional ``chapter_two`` implementation selected one representative
pathway per category.  That is wrong for categories whose signal is spread over
several MetaCyc pathways (notably butyrate).  This module aggregates every
observed pathway in the category and every recorded stratified contribution.
It also joins optional HUMAnN UniRef->EC utility mappings when available; EC
values are used only as supplementary contributor evidence and are never added
to pathway abundance or share denominators.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from wgs_agent.reporting.functional_metrics import contributor_summary, taxon_name
from wgs_agent.reporting.inputs import finite
from wgs_fmt_platform.paths import PROJECT_ROOT, bioinformatics_root, bioinformatics_database_root

CATEGORY_LABELS = {
    "butyrate": "丁酸合成",
    "lactate": "乳酸利用",
    "polysaccharide": "复杂多糖降解",
}
BUTYRATE_PATHWAYS = frozenset({"CENTFERM-PWY", "PWY-5676", "P162-PWY", "P163-PWY", "PWY-5022"})
LACTATE_PATHWAYS = frozenset({"PWY-8086"})
POLYSACCHARIDE_EXACT = frozenset({
    "PWY-6731", "GALACTUROCAT-PWY", "PWY-6507", "GALACT-GLUCUROCAT-PWY",
    "PWY-6901", "PWY-7294", "PWY-7456", "RHAMCAT-PWY", "FUCCAT-PWY",
})
CATEGORY_PATHWAYS = {
    "butyrate": BUTYRATE_PATHWAYS,
    "lactate": LACTATE_PATHWAYS,
    "polysaccharide": POLYSACCHARIDE_EXACT,
}


def _load_json_yaml(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except ValueError:
        import yaml  # optional
        value = yaml.safe_load(raw)
    if not isinstance(value, dict):
        raise ValueError("invalid_mapping_file")
    return value


def pathway_category(row: dict) -> str | None:
    ident = str(row.get("id") or "").split(":", 1)[0].strip()
    for category, ids in CATEGORY_PATHWAYS.items():
        if ident in ids:
            return CATEGORY_LABELS[category]
    name = str(row.get("name") or row.get("label") or "").strip().lower()
    if name.strip() == "4-aminobutanoate degradation v":
        return CATEGORY_LABELS["butyrate"]
    if re.search(r"\b(?:butyrate|butanoate)\b|丁酸", name):
        if not re.search(r"aminobutanoate|(?:butanoate|butyrate) (?:degradation|utilization|oxidation|consumption)|丁酸(?:降解|利用|氧化)", name):
            return CATEGORY_LABELS["butyrate"]
    if re.search(r"\blactate\s+(?:degradation|utilization|oxidation|consumption|fermentation to)", name) \
            or "乳酸利用" in name or "乳酸降解" in name:
        return CATEGORY_LABELS["lactate"]
    if any(word in name for word in ("lipopolysaccharide", "lipid a", "peptidoglycan", "脂多糖", "肽聚糖")):
        return None
    substrate = any(word in name for word in ("starch", "pectin", "xylan", "polysaccharide", "cellulose", "多糖", "淀粉", "木聚糖", "果胶", "纤维素"))
    degradation = any(word in name for word in ("degradation", "utilization", "hydrolysis", "降解", "利用"))
    return CATEGORY_LABELS["polysaccharide"] if substrate and degradation else None


def _pathway_rows(document: dict) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for row in document.get("evidence", {}).values():
        if not isinstance(row, dict) or row.get("kind") not in {"pathway", "function"}:
            continue
        if row.get("measurement_type") == "unverified":
            continue
        ident = str(row.get("id") or row.get("name") or row.get("label"))
        if not ident or ident in seen:
            continue
        amount = finite(row.get("value", row.get("abundance")))
        if amount is not None and amount > 0:
            rows.append(row)
            seen.add(ident)
    return rows


def aggregate_category(document: dict, category: str) -> dict:
    """Aggregate ALL observed pathways in one category, not one representative."""
    rows = [row for row in _pathway_rows(document) if pathway_category(row) == category]
    details = [{"pathway": row, "summary": contributor_summary(row)} for row in rows]
    usable = [item for item in details if item["summary"]["status"] == "available"]
    units = {str(item["pathway"].get("unit", "")).strip().lower() for item in details}
    unit_consistent = len(units) <= 1 and "" not in units
    members: dict[str, dict[str, Any]] = {}
    for item in usable:
        for member in item["summary"]["members"]:
            key = str(member["name"]).casefold()
            target = members.setdefault(key, {
                "name": member["name"],
                "values": [],
                "pathway_ids": [],
            })
            target["values"].append(member["value"])
            target["pathway_ids"].append(item["pathway"].get("id"))
    denominator = math.fsum(math.fsum(item["values"]) for item in members.values()) if unit_consistent else None
    result_members: list[dict[str, Any]] = []
    for item in members.values():
        value = math.fsum(item["values"]) if unit_consistent else None
        result_members.append({
            "name": item["name"],
            "value": value,
            "share": (100 * value / denominator) if denominator and value is not None else None,
            "pathway_ids": sorted(set(filter(None, item["pathway_ids"]))),
        })
    result_members.sort(key=lambda row: (row["share"] is None, -(row["share"] or 0), row["name"]))
    named = [row for row in result_members if row["name"] != "未分类贡献"]
    unknown = next((row["share"] for row in result_members if row["name"] == "未分类贡献"), 0.0 if denominator else None)
    return {
        "category": category,
        "status": "available" if rows else "missing",
        "pathways": rows,
        "pathway_ids": sorted({str(row.get("id")) for row in rows if row.get("id")}),
        "pathway_abundance_sum": math.fsum(finite(row.get("value", row.get("abundance"))) or 0 for row in rows),
        "per_pathway": details,
        "contributors": result_members,
        "named_count": len(named),
        "top_named_share": named[0]["share"] if named else None,
        "unknown_share": unknown,
        "denominator": denominator,
        "unit_consistent": unit_consistent,
        "complete": bool(rows) and all(item["summary"]["status"] == "available" and item["summary"]["complete"] for item in details),
        "incomplete_pathways": sum(1 for item in details if item["summary"]["status"] != "available"),
    }


def _genefamilies_path(document: dict) -> Path | None:
    pathways = document.get("template_inputs", {}).get("pathways") or {}
    source = pathways.get("source_file") if isinstance(pathways, dict) else None
    if source:
        candidate = Path(str(source)).with_name(Path(str(source)).name.replace("pathabundance", "genefamilies"))
        if candidate.is_file():
            return candidate
    analysis = document.get("_analysis") or {}
    source = ((analysis.get("pathways") or {}).get("source_file")) if isinstance(analysis.get("pathways"), dict) else None
    if source:
        candidate = Path(str(source)).with_name(Path(str(source)).name.replace("pathabundance", "genefamilies"))
        if candidate.is_file():
            return candidate
    root = bioinformatics_root()
    sample_id = document.get("sample_id", "")
    candidate = root / "profiles/humann" / f"{sample_id}_genefamilies_relab.tsv"
    return candidate if candidate.is_file() else None


def _ec_map(ec_numbers: set[str]) -> dict[str, set[str]]:
    path = bioinformatics_database_root() / "humann3" / "utility_mapping" / "map_level4ec_uniref90.txt.gz"
    if not path.is_file():
        return {}
    result: dict[str, set[str]] = defaultdict(set)
    with gzip.open(path, "rt", errors="replace") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if fields and fields[0] in ec_numbers:
                result[fields[0]].update(fields[1:])
    return result


def ec_contributors(document: dict, ec_numbers: list[str] | set[str]) -> dict[str, dict]:
    """Supplementary UniRef->EC contributor evidence, never added to pathway sums."""
    genefamilies = _genefamilies_path(document)
    if genefamilies is None:
        return {}
    mapping = _ec_map(set(ec_numbers))
    if not mapping:
        return {}
    result: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    with genefamilies.open(encoding="utf-8-sig") as handle:
        next(handle)
        for line in handle:
            key, _, value = line.rstrip("\n").partition("\t")
            base = key.split("|", 1)[0]
            for ec, unirefs in mapping.items():
                if base not in unirefs:
                    continue
                try:
                    amount = float(value)
                except ValueError:
                    continue
                if amount <= 0:
                    continue
                if "|" in key:
                    taxon = taxon_name(key.split("|", 1)[1])
                else:
                    taxon = "未分类贡献"
                result[ec][taxon] += amount
    return {ec: dict(values) for ec, values in result.items()}


def _named_totals(values: dict[str, float]) -> list[dict[str, Any]]:
    total = math.fsum(values.values())
    rows = []
    for name, value in values.items():
        if name == "未分类贡献" or name.lower() in {"unclassified", "unassigned", "unknown"}:
            continue
        rows.append({"name": name, "value": value, "share": (100 * value / total) if total else None})
    rows.sort(key=lambda row: -(row["value"] or 0))
    return rows


def _backup_label(named: int, top_share: float | None) -> str:
    return "多种菌分担" if named >= 3 and top_share is not None and top_share < 60 else "主要依赖少数菌"


def load_substrate_map() -> dict[str, Any]:
    return _load_json_yaml(PROJECT_ROOT / "knowledge_base" / "consumer_substrate_map.yaml")


def load_vitamin_map() -> dict[str, Any]:
    return _load_json_yaml(PROJECT_ROOT / "knowledge_base" / "consumer_vitamin_map.yaml")


def substrate_evidence(document: dict, substrate: dict) -> dict[str, Any]:
    """Return pathway + EC contributor evidence for one dietary substrate."""
    pathway_ids = {str(item["id"]) for item in substrate.get("pathways", []) if item.get("verified")}
    rows = [
        row for row in _pathway_rows(document)
        if str(row.get("id") or "").split(":", 1)[0] in pathway_ids
    ]
    contributions: dict[str, float] = defaultdict(float)
    strata_present = False
    for row in rows:
        summary = contributor_summary(row)
        if summary["status"] == "available":
            strata_present = True
            for member in summary["members"]:
                contributions[member["name"]] += member["value"]
    ec_numbers = {str(item["ec"]) for item in substrate.get("enzymes", []) if item.get("verified")}
    ec = ec_contributors(document, ec_numbers) if ec_numbers else {}
    ec_present = False
    for values in ec.values():
        for name, value in values.items():
            if name != "未分类贡献":
                contributions[name] += value
                ec_present = True
    named = _named_totals(contributions)
    top = named[0]["share"] if named else None
    has_signal = bool(rows) or ec_present
    if not has_signal:
        conclusion = "本次未检出相关基因"
    else:
        conclusion = "多种菌具备" if len(named) >= 3 and top is not None and top < 60 else "少数菌具备"
    return {
        "substrate": substrate,
        "pathway_ids": sorted(pathway_ids),
        "pathway_rows": rows,
        "named": named,
        "top_share": top,
        "has_signal": has_signal,
        "strata_present": strata_present,
        "ec_used": bool(ec_present),
        "conclusion": conclusion,
        "backup": _backup_label(len(named), top),
    }


def fiber_contributors(document: dict) -> dict[str, dict[str, Any]]:
    mapping = load_substrate_map()
    result = {}
    for substrate in mapping.get("substrates", []):
        result[str(substrate["id"])] = substrate_evidence(document, substrate)
    return result


def fiber_union(document: dict) -> dict[str, dict[str, Any]]:
    """Union of named contributors across all four dietary-fibre substrates.

    The diversity stage and the nutrition cards use this same function, so the
    two presentations cannot disagree about who contributes to fibre breakdown.
    """
    fibers = fiber_contributors(document)
    values: dict[str, float] = defaultdict(float)
    for item in fibers.values():
        for member in item["named"]:
            values[member["name"]] += member["value"]
    named = _named_totals(values)
    top = named[0]["share"] if named else None
    return {
        "substrates": fibers,
        "named": named,
        "top_share": top,
        "backup": _backup_label(len(named), top),
    }


def vitamin_evidence(document: dict, vitamin: dict) -> dict[str, Any]:
    pathway_ids = {str(item["id"]) for item in vitamin.get("pathways", []) if item.get("verified")}
    rows = [
        row for row in _pathway_rows(document)
        if str(row.get("id") or "").split(":", 1)[0] in pathway_ids
    ]
    contributions: dict[str, float] = defaultdict(float)
    for row in rows:
        summary = contributor_summary(row)
        if summary["status"] == "available":
            for member in summary["members"]:
                contributions[member["name"]] += member["value"]
    named = _named_totals(contributions)
    return {
        "vitamin": vitamin,
        "pathway_rows": rows,
        "pathway_ids": sorted(pathway_ids),
        "named": named,
        "has_signal": bool(rows),
        "status": "具备合成潜力" if rows else "未检出相关基因",
    }


def vitamin_table(document: dict) -> list[dict[str, Any]]:
    mapping = load_vitamin_map()
    return [vitamin_evidence(document, item) for item in mapping.get("vitamins", [])]


def metabolite_contributors(document: dict, pathway_ids: list[str], ec_numbers: list[str] | None = None) -> dict[str, Any]:
    ids = set(pathway_ids)
    rows = [row for row in _pathway_rows(document) if str(row.get("id") or "").split(":", 1)[0] in ids]
    contributions: dict[str, float] = defaultdict(float)
    for row in rows:
        summary = contributor_summary(row)
        if summary["status"] == "available":
            for member in summary["members"]:
                contributions[member["name"]] += member["value"]
    if ec_numbers:
        for values in ec_contributors(document, ec_numbers).values():
            for name, value in values.items():
                if name != "未分类贡献":
                    contributions[name] += value
    named = _named_totals(contributions)
    return {
        "rows": rows,
        "named": named,
        "has_signal": bool(rows or named),
        "has_strata": bool(contributions),
    }


def taxonomy_fallback_contributors(document: dict, genera: set[str]) -> list[dict[str, Any]]:
    """Named taxonomy members for a known functional trait where strata are absent.

    This is used for the lactate-utilization stage.  It is explicitly labelled as
    taxonomy-backed, not as a gene-stratified measurement.
    """
    rows = document.get("template_inputs", {}).get("taxonomy", {}).get("ranks", {}).get("species", [])
    result = []
    for row in rows:
        name = str(row.get("name") or row.get("species") or "")
        genus = name.split(" ")[0].casefold() if name else ""
        if genus in genera:
            amount = finite(row.get("abundance")) or 0
            if amount > 0:
                result.append({"name": name, "value": amount})
    result.sort(key=lambda item: -item["value"])
    return result
