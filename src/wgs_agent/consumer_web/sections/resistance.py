"""Drug-class and mobile-element helpers for the resistance section."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from wgs_fmt_platform.paths import PROJECT_ROOT

from .context import Context

CLASS_PATH = PROJECT_ROOT / "knowledge_base" / "consumer_drug_classes.yaml"

MECHANISM_CN = {
    "target protection": "保护细菌的作用靶点，使药物无法起效",
    "antibiotic inactivation": "直接破坏或改造药物",
    "efflux": "把药物排出细菌",
    "target alteration": "改变药物作用的靶点",
    "target replacement": "替换药物作用的靶点",
    "target alteration / replacement": "改变药物作用的靶点",
}


def load_classes(path: Path | None = None) -> dict[str, Any]:
    raw = Path(path or CLASS_PATH).read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except ValueError:
        import yaml
        value = yaml.safe_load(raw)
    if not isinstance(value, dict) or not isinstance(value.get("classes"), list):
        raise ValueError("invalid_consumer_drug_classes")
    return value


def class_for(english: str) -> dict | None:
    needle = str(english or "").strip().casefold()
    for item in load_classes().get("classes", []):
        if needle in {str(alias).casefold() for alias in item.get("aliases", [])} or needle == str(item.get("english", "")).casefold():
            return item
    return None


def mechanism_cn(value: str) -> str:
    return MECHANISM_CN.get(str(value or "").strip().casefold(), "改变细菌与药物的相互作用")


def resistance_genes(ctx: Context) -> list[dict]:
    module = ctx.module("resistance")
    if module.get("status") != "completed" or ctx.qc_failed:
        return []
    rows = module.get("genes", [])
    return [row for row in rows if isinstance(row, dict) and row.get("detected", True)]


def high_concern_resistance(ctx: Context) -> list[dict]:
    patterns = (
        r"KPC", r"NDM", r"OXA-?48", r"VIM", r"IMP", r"mcr", r"vanA", r"vanB", r"CTX-M",
    )
    result = []
    for row in resistance_genes(ctx):
        name = str(row.get("gene") or row.get("name") or "")
        alias = " ".join(str(item) for item in row.get("gene_aliases", []))
        if any(re.search(pattern, name + " " + alias, re.I) for pattern in patterns):
            result.append(row)
    return result


def grouped_resistance(ctx: Context) -> list[dict]:
    groups: dict[str, dict] = {}
    for row in resistance_genes(ctx):
        cls = class_for(str(row.get("drug_class") or "")) or {
            "english": "Other", "name": "其他类别", "examples": [], "mechanism": ""
        }
        key = str(cls.get("name"))
        target = groups.setdefault(key, {
            "title": key,
            "examples": cls.get("examples") or [],
            "mechanism": mechanism_cn(str(row.get("mechanism") or cls.get("mechanism") or "")),
            "genes": [],
        })
        target["genes"].append(str(row.get("gene") or row.get("name") or ""))
    return sorted(groups.values(), key=lambda item: (-len(item["genes"]), item["title"]))


def mobile_elements(ctx: Context) -> list[dict]:
    module = ctx.module("mobile_elements")
    if module.get("status") != "completed" or ctx.qc_failed:
        return []
    return [row for row in module.get("results", []) if isinstance(row, dict) and row.get("detected", True)]
