"""Audited curatedMetagenomicData v3 healthy-control provider."""
from __future__ import annotations

from pathlib import Path
from wgs_fmt_platform.paths import runtime_path
from . import population_reference as population
from .population_reference import digest, normalize, read_target, valid_sample_id

PROVIDER = "cmd"
VERSION = "cmd-reference-v1"
NORMALIZATION = "species_classified_sum_100_v1"
# cMD3 publishes MetaPhlAn 3 / v30, but not a per-profile minor version.
PIPELINE = {"profiler": "MetaPhlAn", "profiler_version": "3",
            "database_version": "mpa_v30_CHOCOPhlAn_201901"}
SOURCE_PROFILER_MINOR_VERSION = None
TARGET_VERSION = "3.0.14"
PHENOTYPE = "healthy_control"
SHORT_LABEL = "cMD"
POPULATION = "curatedMetagenomicData 健康标签成人粪便对照"
SCOPE = "published_cmd3_healthy_control_exploratory"
METHOD = "MetaPhlAn 3 / v30；已分类物种内归一化；待测软件3.0.14；来源小版本未公布"
LIMITATIONS = (
    "参考人群按原研究healthy/control标签、成年和明确当前不用抗生素筛选；不等同于经完整临床筛查的正常人群或合格供体。",
    "参考仅纳入通过丰度矩阵格式及完整性检查的已发表物种谱，未重新审核全部原始测序质控；BMI未作额外限制。",
    "原发布资料未记录每份谱的MetaPhlAn3精确小版本，保持未公布；待测软件精确固定为3.0.14，数据库精确匹配v30，比较为探索性。",
    "参考与待测均以已分类物种总和归一化；独立谱不与主分析Jan25百分数、SGB丰富度混算。",
    "研究间测序深度、提取方法及批次未统一校正；P5–P95和经验百分位不是疾病概率。",
)
REASONS = {**population.REASONS,
    "reference_missing": "curatedMetagenomicData健康参考文件尚未准备或不可读取",
    "invalid_reference": "cMD参考格式、校验和或版本不符合约定",
    "target_missing": "尚未生成该样本独立的MetaPhlAn3/v30对照谱",
    "incompatible_pipeline": "独立对照谱须精确使用MetaPhlAn3.0.14/v30；当前Jan25主分析谱不能直接比较",
}


# "no" is the original strict contract; "no_or_unrecorded" also keeps subjects whose
# study did not record current antibiotic use (explicit users are still excluded).
ANTIBIOTICS_POLICIES = ("no", "no_or_unrecorded")
UNRECORDED_ANTIBIOTICS_LIMITATION = (
    "参考人群按原研究healthy/control标签和成年筛选；当前使用抗生素者已排除，"
    "部分原研究未记录抗生素使用情况的个体也被纳入。不等同于经完整临床筛查的正常人群或合格供体。")


def reference_dir() -> Path:
    return runtime_path("WGS_CMD_REFERENCE_DIR", "reference", "cmd", "native-v3")


def profiles_dir() -> Path:
    return runtime_path("WGS_CMD_PROFILES_DIR", "reference-targets", "cmd")


SPEC = population.ProviderSpec(provider=PROVIDER, version=VERSION, pipeline=PIPELINE,
    target_pipeline={**PIPELINE, "profiler_version": TARGET_VERSION}, normalization=NORMALIZATION,
    phenotype=PHENOTYPE, population=POPULATION, scope=SCOPE, method=METHOD,
    reference_dir=reference_dir, profiles_dir=profiles_dir, limitations=LIMITATIONS)


def pipeline_matches(pipeline: dict) -> bool:
    return isinstance(pipeline, dict) and pipeline == dict(SPEC.target_pipeline)


def load_bundle(base: Path):
    result = population.load_bundle(base, SPEC)
    manifest = result[0]
    criteria = manifest.get("selection_criteria", {})
    if (not isinstance(criteria, dict) or manifest.get("source_package") != "curatedMetagenomicData"
            or not population.present(manifest.get("source_package_version"))
            or criteria.get("minimum_age") != 18 or criteria.get("disease") != "healthy"
            or criteria.get("study_condition") != "control"
            or criteria.get("antibiotics_current_use") not in ANTIBIOTICS_POLICIES
            or criteria.get("deduplicate_by") != ["study_id", "subject_id"]):
        raise population.PopulationReferenceError("invalid_reference")
    return result


def compare(sample_id: str, metadata: dict) -> dict:
    result = population.compare(sample_id, metadata, spec=SPEC, loader=load_bundle,
                                ordination=community_ordination, reasons=REASONS)
    audit = result.get("audit", {})
    try:
        criteria = load_bundle(reference_dir())[0].get("selection_criteria", {})
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        criteria = {}
    policy = criteria.get("antibiotics_current_use", "no")
    audit["antibiotics_policy"] = policy
    if policy == "no_or_unrecorded" and isinstance(audit.get("limitations"), list) and audit["limitations"]:
        audit["limitations"][0] = UNRECORDED_ANTIBIOTICS_LIMITATION
    return result


def community_ordination(target, matrix, selected, **kwargs):
    """Only visualization uses a bounded, reproducible reference subset."""
    from .ordination import community_ordination as calculate
    original_count = len(selected)
    if original_count > 300:
        version = str(kwargs.get("reference_version", ""))
        selected = sorted(selected, key=lambda sid: digest((version + "|" + str(sid)).encode()))[:300]
    result = calculate(target, matrix, selected, **kwargs)
    result["n_reference_total"] = original_count
    if original_count > len(selected):
        result["reference_sampling"] = "deterministic_hash_subset_300"
        result.setdefault("limitations", []).append(
            f"此群落图使用全部{original_count}名参考中的固定300人子集；物种及多样性分位数仍使用全部合格参考。")
    return result
