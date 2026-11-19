#!/usr/bin/env python3
"""Import gut-microbiome -> disease Mendelian-randomisation (MR) results.

Inputs (spreadsheets supplied by the product team):

* ``菌_MR_评分.xlsx``: one row per (microbiome trait, FinnGen R13 endpoint) with
  columns exposure, 分类, 肠道菌群/功能通路, outcome, IVW_beta, IVW_pval, lg(pval);
* ``疾病分类表_已注释.xlsx``: FinnGen endpoint -> official English name, Chinese
  name and organ-system class.

Output: ``knowledge_base/disease_mr/disease_mr_weights.json``, the only file the
runtime reads.  Kept rows: IVW P below ``--p-threshold`` and a trait category in
``--categories`` (abundance traits only by default: the score multiplies by a
standardised abundance, which presence/absence traits do not have).  Every kept
row keeps its raw trait text, beta and P so the score stays auditable.

    python scripts/import_disease_mr.py --mr 菌_MR_评分.xlsx --diseases 疾病分类表_已注释.xlsx
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "knowledge_base" / "disease_mr" / "disease_mr_weights.json"
CATEGORY_KIND = {
    "species abundance": "species",
    "genus abundance": "genus",
    "alpha diversity abundance": "alpha",
}
ALPHA_KEYS = {
    "shannon diversity": "shannon",
    "richness": "richness",
    "inverse simpson diversity": "inverse_simpson",
}
SCHEMA = "disease-mr-weights-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(mr_path: Path, disease_path: Path, p_threshold: float, categories: list[str]) -> dict:
    import pandas as pd

    mr = pd.read_excel(mr_path)
    mr.columns = ["exposure", "category", "trait", "outcome", "beta", "p", "lg_p"]
    diseases = pd.read_excel(disease_path)
    diseases.columns = ["outcome", "code", "name_en", "name_cn", "system", "finngen_class"]
    meta = {row.outcome: row for row in diseases.itertuples(index=False)}
    total_rows = len(mr)
    mr = mr.dropna(subset=["beta", "p"])
    kept = mr[(mr.p < p_threshold) & mr.category.isin(categories)]
    out: dict[str, dict] = {}
    for row in kept.itertuples(index=False):
        if row.outcome not in meta:
            raise ValueError(f"outcome {row.outcome} missing from the disease table")
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
        entry = out.setdefault(row.outcome, {"traits": []})
        entry["traits"].append({
            "kind": kind,
            "name": name,
            "trait": trait,
            "exposure": str(row.exposure),
            "beta": round(float(row.beta), 8),
            "p": float(f"{p:.6g}"),
            "neg_lg_p": round(-math.log10(p), 6),
        })
    result = []
    for outcome, row in meta.items():
        traits = sorted(out.get(outcome, {}).get("traits", []), key=lambda t: (t["p"], t["kind"], t["name"]))
        result.append({
            "id": str(row.code),
            "outcome": outcome,
            "name_en": str(row.name_en),
            "name_cn": str(row.name_cn),
            "system": str(row.system),
            "finngen_class": str(row.finngen_class),
            "traits": traits,
        })
    result.sort(key=lambda d: (d["system"], d["id"]))
    return {
        "schema_version": SCHEMA,
        "source": {
            "mr_file": mr_path.name,
            "mr_sha256": _sha256(mr_path),
            "mr_rows": total_rows,
            "disease_file": disease_path.name,
            "disease_sha256": _sha256(disease_path),
            "outcome_source": "FinnGen R13",
            "method": "inverse-variance weighted (IVW) two-sample MR",
        },
        "selection": {"p_threshold": p_threshold, "categories": categories},
        "formula": "score = sum(beta * (-log10 P) * z); z = standardised log10 relative abundance",
        "diseases": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mr", type=Path, required=True)
    parser.add_argument("--diseases", type=Path, required=True)
    parser.add_argument("--p-threshold", type=float, default=0.05)
    parser.add_argument("--categories", nargs="+", default=list(CATEGORY_KIND), choices=list(CATEGORY_KIND))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = load(args.mr, args.diseases, args.p_threshold, args.categories)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Deterministic bytes: the runtime bundle directory is named after this file's hash,
    # so re-importing unchanged inputs must not force a rebuild.  One disease per line.
    head = {k: v for k, v in payload.items() if k != "diseases"}
    lines = [json.dumps(d, ensure_ascii=False, separators=(",", ":")) for d in payload["diseases"]]
    text = json.dumps(head, ensure_ascii=False, indent=1)[:-2] + ',\n "diseases": [\n' + ",\n".join(lines) + "\n ]\n}\n"
    json.loads(text)
    args.output.write_text(text, encoding="utf-8")
    kept = sum(len(d["traits"]) for d in payload["diseases"])
    print(json.dumps({"output": str(args.output), "diseases": len(payload["diseases"]), "traits": kept}, ensure_ascii=False))


if __name__ == "__main__":
    main()
