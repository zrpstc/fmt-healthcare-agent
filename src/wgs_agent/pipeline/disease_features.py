"""Traceable disease-associated species features from existing taxonomy.

This is an annotation workflow, not a classifier or a case/control comparison.
It neither reruns sequencing tools nor assigns risk scores or missing abundances.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

VERSION = "disease-species-features-v1"
CATALOG = Path(__file__).with_name("disease_associations.json")


def _key(value):
    name = str(value or "").strip()
    for part in name.split("|"):
        if part.startswith("s__"):
            name = part[3:]
            break
    return name.replace("_", " ").casefold().strip()


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and 0 <= value <= 100 else None
    except (ValueError, TypeError, OverflowError):
        return None


def load_catalog(path=CATALOG):
    raw = Path(path).read_bytes()
    catalog = json.loads(raw)
    if not isinstance(catalog, dict) or not catalog.get("version") or not isinstance(catalog.get("modules"), list):
        raise ValueError("INVALID_DISEASE_REFERENCE")
    ids = set()
    for module in catalog["modules"]:
        reference = module.get("reference", {})
        if (not module.get("id") or module["id"] in ids or not module.get("disease")
                or not reference.get("doi") or not reference.get("url") or not reference.get("locator")
                or not module.get("features")):
            raise ValueError("INVALID_DISEASE_REFERENCE")
        ids.add(module["id"])
        names = set()
        for feature in module["features"]:
            key = _key(feature.get("species"))
            if not key or key in names or not feature.get("direction"):
                raise ValueError("INVALID_DISEASE_FEATURE")
            names.add(key)
    return catalog, hashlib.sha256(raw).hexdigest()


def analyze_disease_features(taxonomy, *, catalog_path=CATALOG):
    """Match explicitly reported species. An unreported taxon stays unquantified."""
    reference_error = None
    try:
        catalog, digest = load_catalog(catalog_path)
    except (OSError, UnicodeError):
        catalog, digest, reference_error = {"version": None, "modules": []}, None, "DISEASE_REFERENCE_UNAVAILABLE"
    except (ValueError, TypeError, KeyError, AttributeError):
        catalog, digest, reference_error = {"version": None, "modules": []}, None, "DISEASE_REFERENCE_INVALID"
    result = {
        "status": "not_assessed", "reason_code": "TAXONOMY_UNAVAILABLE",
        "generated_by": VERSION, "reference_version": catalog["version"],
        "reference_sha256": digest, "diseases": [],
        "result_type": "literature_species_annotation",
        "case_control_reference_available": False,
        "limitations": [
            "仅呈现样本物种丰度与原研究关联方向，不计算个体疾病概率或病例相似度。",
            "未在物种谱报告的物种不补零；不以缺失或未检出推断病例组减少。",
            "尚无同版本疾病病例/对照参考矩阵，不能判断样本是否符合文献变化方向。",
            "当前参考仅覆盖结直肠癌和克罗恩病；其他疾病类别未评估。",
        ],
        "model_assessment": {
            "status": "not_enabled", "reason_code": "VALIDATED_MODEL_NOT_CONFIGURED",
            "missing_requirements": ["可执行模型及特征/预处理定义", "独立外部验证证据", "样本与人群适用性核验"],
        },
    }
    if reference_error:
        return {**result, "reason_code": reference_error}
    if not isinstance(taxonomy, dict) or taxonomy.get("complete") is not True:
        return result
    if taxonomy.get("unit") not in {"%", "percent", "percentage"}:
        return {**result, "reason_code": "TAXONOMY_UNIT_INCOMPATIBLE"}
    ranks = taxonomy.get("ranks")
    if not isinstance(ranks, dict):
        return {**result, "reason_code": "INVALID_TAXONOMY"}
    rows = ranks.get("species", [])
    if not isinstance(rows, list) or not rows:
        return result
    lookup = {}
    for row in rows:
        if not isinstance(row, dict):
            return {**result, "reason_code": "INVALID_TAXONOMY"}
        key = _key(row.get("name", row.get("species")))
        value = _number(row.get("abundance", row.get("value")))
        if (not key or key in lookup or value is None
                or row.get("unit", taxonomy["unit"]) not in {"%", "percent", "percentage"}):
            return {**result, "reason_code": "INVALID_OR_AMBIGUOUS_TAXONOMY"}
        lookup[key] = (row, value)
    for module in catalog["modules"]:
        details = []
        for feature in module["features"]:
            match = lookup.get(_key(feature["species"]))
            detail = {
                **feature, "abundance": match[1] if match else None, "unit": "%",
                "status": "reported" if match else "not_reported",
                "status_cn": "物种谱已报告" if match else "物种谱未报告，未定量",
                "sample_direction": "未判定（缺少同口径病例/对照参考）",
                "evidence_level": module["evidence_level"],
                "doi": module["reference"]["doi"], "source": module["reference"]["url"],
            }
            if match:
                detail["source_taxon"] = match[0].get("name", match[0].get("species"))
            details.append(detail)
        matched = sum(row["status"] == "reported" for row in details)
        result["diseases"].append({
            "id": module["id"], "disease": module["disease"], "category": module.get("category"),
            "result": f"已核对 {len(details)} 个文献物种，物种谱报告其中 {matched} 个；未判定疾病方向",
            "matched_species": matched, "reference_feature_count": len(details),
            "target_population": module.get("target_population"),
            "evidence_level": module["evidence_level"], "details": details,
            "references": [copy.deepcopy(module["reference"])],
            "limitations": module.get("limitations"), "generated_by": VERSION,
        })
    result.update(status="completed", reason_code="LITERATURE_FEATURES_ANNOTATED",
                  input_pipeline=copy.deepcopy(taxonomy.get("pipeline", {})),
                  input_species_count=len(lookup), source_file=taxonomy.get("source_file"))
    return result


def merge_disease_features(generated, existing):
    """Keep manually supplied modules and enrich only this workflow's own output."""
    previous = existing.get("diseases")
    if generated.get("status") != "completed" and previous is None:
        return {}
    if isinstance(previous, dict) and previous.get("diseases") and previous.get("generated_by") != VERSION:
        return {"diseases": previous}
    if generated.get("status") != "completed" and isinstance(previous, dict) and previous.get("diseases"):
        return {"diseases": previous}
    return {"diseases": generated}
