#!/usr/bin/env python3
"""Import gut-microbiome -> dietary-nutrient Mendelian-randomisation (MR) results.

Inputs (spreadsheets supplied by the product team):

* ``菌_膳食营养_评分.xlsx``: one row per (microbiome trait, UK Biobank nutrient) with
  columns exposure, 分类, 肠道菌群/功能通路, outcome, nsnp, IVW_beta, IVW_pval,
  lg(pval), 负lg(pval); outcomes look like ``100009_Englyst_dietary_fibre.v1.1``;
* ``膳食营养表型清单.xlsx``: UK Biobank field ID -> English and Chinese name.

Output: ``knowledge_base/diet_mr/diet_mr_weights.json``, the only file the runtime
reads.  Selection follows the disease MR import (IVW P below ``--p-threshold``,
abundance traits only).  Each nutrient also carries its display group and its
direction in the overall score (``encourage`` / ``limit`` / ``neutral``, see
``NUTRIENT_ROLES``); both live here so that changing them changes the weights
hash and the reference bundle is rebuilt.

    python scripts/import_diet_mr.py --mr 菌_膳食营养_评分.xlsx --nutrients 膳食营养表型清单.xlsx
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from import_disease_mr import ALPHA_KEYS, CATEGORY_KIND

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "knowledge_base" / "diet_mr" / "diet_mr_weights.json"
SCHEMA = "diet-mr-weights-v1"

# UK Biobank field -> (display group, direction in the overall score).
#   encourage: a higher intake tendency raises the overall score;
#   limit:     a higher intake tendency lowers it (dietary-guideline "limit" items);
#   neutral:   shown, but not part of the overall score (amount says little about quality,
#              or both too little and too much are a problem).
GROUPS = ("能量与宏量营养素", "脂肪构成", "膳食纤维", "维生素", "矿物质", "酒精")
NUTRIENT_ROLES: dict[str, tuple[str, str]] = {
    "100002": ("能量与宏量营养素", "neutral"),   # Energy
    "100003": ("能量与宏量营养素", "neutral"),   # Protein
    "100004": ("能量与宏量营养素", "neutral"),   # Fat
    "100005": ("能量与宏量营养素", "neutral"),   # Carbohydrate
    "100023": ("能量与宏量营养素", "neutral"),   # Starch
    "100008": ("能量与宏量营养素", "limit"),     # Total sugars
    "100006": ("脂肪构成", "limit"),             # Saturated fat
    "100007": ("脂肪构成", "encourage"),         # Polyunsaturated fat
    "100009": ("膳食纤维", "encourage"),         # Englyst dietary fibre
    "100012": ("维生素", "encourage"),           # Vitamin B6
    "100013": ("维生素", "encourage"),           # Vitamin B12
    "100014": ("维生素", "encourage"),           # Folate
    "100015": ("维生素", "encourage"),           # Vitamin C
    "100018": ("维生素", "neutral"),             # Retinol (preformed vitamin A: excess is harmful)
    "100019": ("维生素", "encourage"),           # Carotene
    "100021": ("维生素", "encourage"),           # Vitamin D
    "100025": ("维生素", "encourage"),           # Vitamin E
    "100011": ("矿物质", "encourage"),           # Iron
    "100016": ("矿物质", "encourage"),           # Potassium
    "100017": ("矿物质", "encourage"),           # Magnesium
    "100024": ("矿物质", "encourage"),           # Calcium
    "100022": ("酒精", "limit"),                 # Alcohol
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def field_of(outcome: str) -> str:
    """'100009_Englyst_dietary_fibre.v1.1' -> '100009'."""
    return str(outcome).split("_", 1)[0].strip()


def load(mr_path: Path, nutrient_path: Path, p_threshold: float, categories: list[str]) -> dict:
    import pandas as pd

    mr = pd.read_excel(mr_path)
    mr = mr.iloc[:, :7]
    mr.columns = ["exposure", "category", "trait", "outcome", "nsnp", "beta", "p"]
    nutrients = pd.read_excel(nutrient_path, dtype=str).iloc[:, :3]
    nutrients.columns = ["field", "name_en", "name_cn"]
    nutrients = nutrients.dropna(subset=["field"])
    nutrients["field"] = nutrients["field"].str.strip()
    nutrients = nutrients[nutrients["field"] != ""]
    meta = {row.field: row for row in nutrients.itertuples(index=False)}
    unknown = sorted(set(meta) - set(NUTRIENT_ROLES))
    if unknown:
        raise ValueError(f"no group/direction for nutrient fields {unknown}; add them to NUTRIENT_ROLES")
    total_rows = len(mr)
    mr = mr.assign(beta=pd.to_numeric(mr.beta, errors="coerce"), p=pd.to_numeric(mr.p, errors="coerce"))
    mr = mr.dropna(subset=["beta", "p"])
    tested = mr[mr.category.isin(categories)]
    tested_per_field = tested.outcome.map(field_of).value_counts().to_dict()
    kept = tested[tested.p < p_threshold]
    out: dict[str, list[dict]] = {}
    for row in kept.itertuples(index=False):
        field = field_of(row.outcome)
        if field not in meta:
            raise ValueError(f"outcome {row.outcome} missing from the nutrient table")
        p = float(row.p)
        if not (0 < p <= 1) or not math.isfinite(float(row.beta)):
            continue
        kind = CATEGORY_KIND[row.category]
        trait = str(row.trait).strip()
        if kind == "alpha":
            name = ALPHA_KEYS.get(trait.casefold())
            if name is None:
                continue
        else:
            name = trait.split(",")[0].strip()
        out.setdefault(field, []).append({
            "kind": kind,
            "name": name,
            "trait": trait,
            "exposure": str(row.exposure),
            "nsnp": int(row.nsnp) if pd.notna(row.nsnp) else None,
            "beta": round(float(row.beta), 8),
            "p": float(f"{p:.6g}"),
            "neg_lg_p": round(-math.log10(p), 6),
        })
    outcomes = {field_of(o): str(o) for o in sorted(mr.outcome.unique())}
    result = []
    for field, row in meta.items():
        group, direction = NUTRIENT_ROLES[field]
        traits = sorted(out.get(field, []), key=lambda t: (t["p"], t["kind"], t["name"]))
        result.append({
            "id": field,
            "outcome": outcomes.get(field, field),
            "name_en": str(row.name_en).strip(),
            "name_cn": str(row.name_cn).strip(),
            "group": group,
            "direction": direction,
            "tested": int(tested_per_field.get(field, 0)),
            "traits": traits,
        })
    result.sort(key=lambda d: (GROUPS.index(d["group"]), d["id"]))
    return {
        "schema_version": SCHEMA,
        "source": {
            "mr_file": mr_path.name,
            "mr_sha256": _sha256(mr_path),
            "mr_rows": total_rows,
            "nutrient_file": nutrient_path.name,
            "nutrient_sha256": _sha256(nutrient_path),
            "outcome_source": "UK Biobank 24-hour dietary recall (Oxford WebQ) nutrient estimates",
            "method": "inverse-variance weighted (IVW) two-sample MR",
        },
        "selection": {"p_threshold": p_threshold, "categories": categories},
        "formula": "score = sum(beta * (-log10 P) * z); z = standardised log10 relative abundance",
        "groups": list(GROUPS),
        "nutrients": result,
    }


def write(payload: dict, output: Path) -> None:
    # Deterministic bytes: the runtime bundle directory is named after this file's hash,
    # so re-importing unchanged inputs must not force a rebuild.  One nutrient per line.
    head = {k: v for k, v in payload.items() if k != "nutrients"}
    lines = [json.dumps(d, ensure_ascii=False, separators=(",", ":")) for d in payload["nutrients"]]
    text = json.dumps(head, ensure_ascii=False, indent=1)[:-2] + ',\n "nutrients": [\n' + ",\n".join(lines) + "\n ]\n}\n"
    json.loads(text)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mr", type=Path, required=True)
    parser.add_argument("--nutrients", type=Path, required=True)
    parser.add_argument("--p-threshold", type=float, default=0.05)
    parser.add_argument("--categories", nargs="+", default=list(CATEGORY_KIND), choices=list(CATEGORY_KIND))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = load(args.mr, args.nutrients, args.p_threshold, args.categories)
    write(payload, args.output)
    summary = {d["id"]: {"traits": len(d["traits"]), "tested": d["tested"],
                         "expected_by_chance": round(d["tested"] * args.p_threshold, 1)}
               for d in payload["nutrients"]}
    kept = sum(len(d["traits"]) for d in payload["nutrients"])
    print(json.dumps({"output": str(args.output), "nutrients": len(payload["nutrients"]), "traits": kept,
                      "per_nutrient": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
