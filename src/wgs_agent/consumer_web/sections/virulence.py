"""VFDB metadata parsing and the consumer toxin-marker panel."""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any

from wgs_fmt_platform.paths import PROJECT_ROOT, bioinformatics_database_root

from .context import Context
from ..names import canonical

PANEL_PATH = PROJECT_ROOT / "knowledge_base" / "consumer_virulence_panel.yaml"
_CACHE: dict[str, dict] | None = None


def load_panel(path: Path | None = None) -> list[dict[str, Any]]:
    raw = Path(path or PANEL_PATH).read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except ValueError:
        import yaml
        value = yaml.safe_load(raw)
    if not isinstance(value, dict) or not isinstance(value.get("markers"), list):
        raise ValueError("invalid_consumer_virulence_panel")
    return value["markers"]


def _parse_header(header: str) -> dict[str, str]:
    vid = header.split("(", 1)[0].strip()
    rest = header[len(vid):]
    symbol = ""
    match = re.search(r"\((?:gb|dbj|emb|ref)\|[^)]+\)\s*\(([^)]+)\)", rest)
    if match:
        symbol = match.group(1).strip()
    else:
        match = re.search(r"^\s*\((?!gb|dbj|emb|ref)([^()]+)\)", rest)
        if match:
            symbol = match.group(1).strip()
    brackets = re.findall(r"\[([^\]]+)\]", header)
    vf_name = ""
    vf_category = ""
    host = ""
    for item in brackets:
        if " - " in item and "(VF" in item:
            left, right = item.split(" - ", 1)
            vf_name = left.strip()
            vf_category = right.split("(")[0].strip()
        elif not host and " - " not in item:
            host = item.strip()
    return {"id": vid, "symbol": symbol, "vf_name": vf_name, "vf_category": vf_category, "host": host}


def load_vfdb_index() -> dict[str, dict]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = bioinformatics_database_root() / "vfdb" / "VFDB_setA_nt.fas.gz"
    result: dict[str, dict] = {}
    if not path.is_file():
        _CACHE = result
        return result
    with gzip.open(path, "rt", errors="replace") as handle:
        for line in handle:
            if not line.startswith(">"):
                continue
            header = line[1:].rstrip()
            if not header.startswith("VFG"):
                continue
            row = _parse_header(header)
            result[row["id"]] = row
    _CACHE = result
    return result


def _host_species(host: str) -> str:
    parts = str(host).split()
    if len(parts) >= 2:
        return canonical(" ".join(parts[:2]))
    return canonical(host)


def panel_results(ctx: Context) -> list[dict[str, Any]]:
    panel = load_panel()
    index = load_vfdb_index()
    module = ctx.module("virulence")
    completed = module.get("status") == "completed" and not ctx.qc_failed
    markers = module.get("markers", []) if isinstance(module.get("markers"), list) else []
    sample_keys = {canonical(row["name"]) for row in ctx.species_rows}
    results = []
    for entry in panel:
        symbols = {str(item).casefold() for item in entry.get("genes", [])}
        aliases = {str(item).casefold() for item in entry.get("aliases", [])}
        reference_present = any(
            row.get("symbol", "").casefold() in symbols | aliases
            for row in index.values()
        )
        detected_rows = []
        for marker in markers:
            meta = index.get(str(marker.get("gene"))) or {}
            symbol = str(meta.get("symbol") or "").casefold()
            if symbol in symbols | aliases:
                detected_rows.append({**marker, "symbol": meta.get("symbol", ""), "host": meta.get("host", ""), "vf_category": meta.get("vf_category", "")})
        source = None
        if detected_rows:
            hosts = [_host_species(row.get("host", "")) for row in detected_rows]
            for host in hosts:
                if host in sample_keys:
                    source = host
                    break
        if not completed:
            result = "本次筛查尚未完成"
        elif detected_rows:
            result = "检出"
        elif reference_present:
            result = "未检出"
        else:
            result = "本次筛查未覆盖该基因"
        results.append({
            **entry,
            "detected": bool(detected_rows),
            "reference_present": reference_present,
            "result": result,
            "source": source,
            "markers": detected_rows,
        })
    return results


def high_concern_results(ctx: Context) -> list[dict]:
    return [row for row in panel_results(ctx) if row.get("level") == "high" and row.get("detected")]


def severity_badge(ctx: Context, name: str) -> str | None:
    # Reuse the key-taxa evidence badge for functional claims.
    from .panel import evidence_badge
    return evidence_badge(ctx, name)


def virulence_gene_groups(ctx: Context) -> list[tuple[str, int]]:
    index = load_vfdb_index()
    module = ctx.module("virulence")
    markers = module.get("markers", []) if isinstance(module.get("markers"), list) else []
    counts: dict[str, int] = {}
    for marker in markers:
        meta = index.get(str(marker.get("gene"))) or {}
        category = str(meta.get("vf_category") or "")
        name = str(meta.get("vf_name") or "")
        if "Adherence" in category or "adherence" in name:
            group = "黏附与定植"
        elif "Invasion" in category or "invasion" in name:
            group = "侵袭"
        elif "Immune modulation" in category or "immune" in name:
            group = "免疫逃逸"
        elif "Effector delivery" in category or "secretion" in name or "T6SS" in name or "T2SS" in name or "TTSS" in name:
            group = "分泌系统"
        elif "Exotoxin" in category or "toxin" in name.lower():
            group = "毒素"
        elif any(word in name.lower() for word in ("enterobactin", "aerobactin", "salmochelin", "siderophore", "iron")):
            group = "铁获取"
        else:
            group = "其他"
        counts[group] = counts.get(group, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))
