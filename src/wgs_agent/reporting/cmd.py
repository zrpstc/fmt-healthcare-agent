"""Independent, audited comparisons against healthy cMD3 stool controls."""
from __future__ import annotations

import sys
from pathlib import Path

from wgs_fmt_platform.paths import runtime_path
from . import mho

PROVIDER = "cmd"
VERSION = "cmd-reference-v1"
NORMALIZATION = mho.NORMALIZATION
PIPELINE = {"profiler": "MetaPhlAn", "profiler_version": "3",
            "database_version": "mpa_v30_CHOCOPhlAn_201901"}
TARGET_VERSION = "3.0.14"
PHENOTYPE = "healthy_control"
SHORT_LABEL = "cMD"
POPULATION = "curatedMetagenomicData 健康标签成人粪便对照"
SCOPE = "published_cMD3_healthy_controls_exploratory"
METHOD = "MetaPhlAn 3 / v30；已分类物种内归一化；待测软件 3.0.14"
LIMITATIONS = (
    "参考人群按原研究 healthy/control 标签、成年和明确当前不用抗生素筛选；不等同于经完整临床筛查的正常人群或合格供体。",
    "参考仅纳入通过丰度矩阵格式及完整性检查的已发表物种谱，未重新审核全部原始测序质控；BMI未作额外限制。",
    "原发布资料未记录每份谱的MetaPhlAn3精确小版本；采用相同软件主版本和v30数据库，待测谱明确固定为3.0.14，比较为探索性。",
    "参考与待测均以已分类物种总和归一化；独立谱不与主分析Jan25百分数、SGB丰富度混算。",
    "研究间测序深度、提取方法及批次未统一校正；P5–P95和经验百分位不是疾病概率。",
)
REASONS = {**mho.REASONS,
    "reference_missing": "curatedMetagenomicData 健康参考文件尚未准备或不可读取",
    "invalid_reference": "cMD参考格式、校验和或版本不符合约定",
    "target_missing": "尚未生成该样本独立的MetaPhlAn3/v30对照谱",
    "incompatible_pipeline": "独立对照谱须使用MetaPhlAn3/v30；当前Jan25主分析谱不能直接比较",
}

valid_sample_id = mho.valid_sample_id
digest = mho.digest
read_target = mho.read_target
normalize = mho.normalize


def reference_dir() -> Path:
    return runtime_path("WGS_CMD_REFERENCE_DIR", "reference", "cmd", "native-v3")


def profiles_dir() -> Path:
    return runtime_path("WGS_CMD_PROFILES_DIR", "reference-targets", "cmd")


def pipeline_matches(pipeline: dict) -> bool:
    return (isinstance(pipeline, dict) and pipeline.get("profiler") == "MetaPhlAn"
            and str(pipeline.get("profiler_version", "")).split(".", 1)[0] == "3"
            and pipeline.get("database_version") == PIPELINE["database_version"])


def load_bundle(base: Path):
    result = mho.load_bundle(base, specification=sys.modules[__name__])
    manifest = result[0]
    criteria = manifest.get("selection_criteria", {})
    if (manifest.get("source_package") != "curatedMetagenomicData"
            or not manifest.get("source_package_version")
            or criteria.get("minimum_age") != 18
            or criteria.get("disease") != "healthy"
            or criteria.get("study_condition") != "control"
            or criteria.get("antibiotics_current_use") != "no"
            or criteria.get("deduplicate_by") != ["study_id", "subject_id"]):
        raise mho.MhoError("invalid_reference")
    return result


def compare(sample_id: str, metadata: dict) -> dict:
    return mho.compare(sample_id, metadata, specification=sys.modules[__name__])


def community_ordination(target, matrix, selected, **kwargs):
    """Only the visualization uses a bounded, reproducible reference subset."""
    from .ordination import community_ordination as calculate
    original_count = len(selected)
    if original_count > 300:
        version = str(kwargs.get("reference_version", ""))
        selected = sorted(selected, key=lambda sid: digest((version+"|"+sid).encode()))[:300]
    result = calculate(target, matrix, selected, **kwargs)
    result["n_reference_total"] = original_count
    if original_count > len(selected):
        result["reference_sampling"] = "deterministic_hash_subset_300"
        result.setdefault("limitations", []).append(
            f"此群落图使用全部{original_count}名参考中的固定300人子集；物种及多样性分位数仍使用全部合格参考。")
    return result
