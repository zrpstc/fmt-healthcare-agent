#!/usr/bin/env python3
"""
===============================================================================
FMT 配型预测模块 (独立) — 移植到 WGS-FMT-Agent
===============================================================================

完整 FMT 配型 pipeline 依赖 R（ZipPCA + Harmony），在报告生成时实时跑一遍
训练耗时很长（1000 epochs K-Fold）。因此采用分层策略：

  1. 如果已有预训练模型（outputs/contrastive_model.pt + mbDenoise 矩阵）
     → 直接加载，提取嵌入做匹配
  2. 如果没有则使用数据训练并保存模型调用匹配
  3. 如果失败 → 优雅降级，报告中显示「配型数据库不可用」

模块结构:
  run_fmt_pipeline()         # 主函数：完整 pipeline，返回匹配结果
  _load_or_run_mbdenoise()   # 加载/运行 ZipPCA+Harmony 去批次矩阵
  _train_or_load_model()     # 加载/训练对比学习模型
  compute_matching_scores()  # 对当前样本提取嵌入，计算 cosine 相似度
  generate_fmt_tsne_plot()   # t-SNE 散点图 + 配对连线
===============================================================================
"""


from wgs_fmt_platform.paths import fmt_matching_dir, resource_root
import os
import sys
import logging
import traceback
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from wgs_fmt_platform.paths import (
    PROJECT_ROOT,
    bioinformatics_root,
    project_path,
    runtime_path,
    workspace_root,
)

def _find_fmt_matching_dir() -> str:
    """Only use the configured local compatibility pipeline; never scan other projects."""
    return str(fmt_matching_dir())


# 将 WGS.FMT/new_FMT_Matching 加入 sys.path 以便导入其模块
_FMT_MATCHING_DIR = _find_fmt_matching_dir()
if os.path.isdir(_FMT_MATCHING_DIR) and _FMT_MATCHING_DIR not in sys.path:
    sys.path.insert(0, _FMT_MATCHING_DIR)

# 懒加载标记
_src_available = False
_src_import_error = ""
if os.path.isdir(_FMT_MATCHING_DIR):
    try:
        from src.pipeline import prepare_small_inputs  # noqa: F401
        from src.contrastive.datasets import build_paired_indices
        from src.contrastive.trainer import train_kfold
        from src.contrastive.evaluate import topk_recall, extract_embeddings  # noqa: F401
        from src.contrastive.model import ContrastiveEncoder
        from src.run_r_wrapper import run_zippca_analysis
        _src_available = True
    except Exception as exc:
        _src_available = False
        _src_import_error = f"{type(exc).__name__}: {exc}"

from wgs_agent.pipeline.report_common import setup_cn_font

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ============================================================================
# 路径常量
# ============================================================================
_FMT_DATA_DIR = os.path.join(_FMT_MATCHING_DIR, "data")
_FMT_OUTPUT_DIR = os.path.join(_FMT_MATCHING_DIR, "outputs")
_FMT_SCRIPT_DIR = os.path.join(_FMT_MATCHING_DIR, "scripts")

ABUNDANCE_FILE = os.path.join(_FMT_DATA_DIR, "species_abundance_train.csv")
META_FILE = os.path.join(_FMT_DATA_DIR, "match.xlsx")
MBDENOISE_CACHE = os.path.join(_FMT_OUTPUT_DIR, "mbDenoise_Harmony_corrected.csv")
MODEL_CACHE = os.path.join(_FMT_OUTPUT_DIR, "contrastive_model.pt")
R_SCRIPT = os.path.join(_FMT_SCRIPT_DIR, "run_zippca_mbdenoise.r")

# Current in-project triplet model.  The legacy R/PyTorch pipeline below remains
# available as a compatibility fallback, but online inference must prefer this
# self-contained artifact so reports do not silently lose donor ranking.
_AGENT_ROOT = PROJECT_ROOT
_FMT_ROOT = runtime_path("WGS_FMT_DATA_ROOT", "fmt")
_RESOURCE_ROOT = resource_root()


def _resource_path(env_name: str, portable: Path, local: Path) -> Path:
    configured = os.environ.get(env_name, "").strip()
    if configured:
        return project_path(configured)
    return portable if portable.exists() else local


TRIPLET_MODEL_DIR = _resource_path(
    "WGS_FMT_TRIPLET_MODEL_DIR",
    _RESOURCE_ROOT / "models/fmt-triplet-v1",
    runtime_path("WGS_FMT_TRIPLET_MODEL_DIR", "model-training", "fmt-triplet-v1"),
)
TRIPLET_PREDICTOR_SCRIPT = project_path(os.environ.get("WGS_FMT_TRIPLET_PREDICTOR") or _AGENT_ROOT / "scripts/predict_fmt_triplet_model.py")
TRIPLET_BASELINE_SPECIES = project_path(os.environ.get("WGS_FMT_BASELINE_SPECIES") or fmt_matching_dir() / "species_abundance_train.csv")
TRIPLET_MATCH_FILE = project_path(os.environ.get("WGS_FMT_MATCH_FILE") or fmt_matching_dir() / "match.xlsx")
TRIPLET_POST_SPECIES = project_path(os.environ.get("WGS_FMT_POST_SPECIES") or bioinformatics_root() / "matrices/species_relative_abundance_percent.tsv")
TRIPLET_PROFILE_DIR = project_path(os.environ.get("WGS_FMT_PROFILE_DIR") or bioinformatics_root() / "profiles/metaphlan")

_triplet_module = None


def _load_triplet_module():
    global _triplet_module
    if _triplet_module is not None:
        return _triplet_module
    if not TRIPLET_PREDICTOR_SCRIPT.is_file():
        raise FileNotFoundError(f"三元组推理脚本不存在: {TRIPLET_PREDICTOR_SCRIPT}")
    spec = importlib.util.spec_from_file_location("wgs_fmt_triplet_predictor", TRIPLET_PREDICTOR_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载三元组推理模块")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _triplet_module = module
    return module


def _read_metaphlan_species_profile(path: Path, sample_id: str) -> Optional[pd.DataFrame]:
    values: dict[str, float] = {}
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip() or line.startswith("#"):
                    continue
                fields = line.rstrip("\n").split("\t")
                if len(fields) < 3:
                    continue
                leaf = fields[0].rsplit("|", 1)[-1]
                if leaf.startswith("s__"):
                    values[fields[0]] = float(fields[2])
    except (OSError, ValueError, IndexError):
        return None
    return pd.DataFrame([values], index=[sample_id]) if values else None


def _load_triplet_query(sample_id: str) -> tuple[Optional[pd.DataFrame], str]:
    """Load one query in priority order: baseline, processed matrix, raw profile."""
    if TRIPLET_BASELINE_SPECIES.is_file():
        baseline = pd.read_csv(TRIPLET_BASELINE_SPECIES, index_col=0)
        baseline.index = baseline.index.astype(str)
        if sample_id in baseline.index:
            return baseline.loc[[sample_id]], "baseline_species"
    if TRIPLET_POST_SPECIES.is_file():
        post = pd.read_csv(TRIPLET_POST_SPECIES, sep="\t", index_col=0)
        post.index = post.index.astype(str)
        if sample_id in post.index:
            return post.loc[[sample_id]], "post_species_matrix"
    profile = TRIPLET_PROFILE_DIR / f"{sample_id}_profile.tsv"
    if profile.is_file():
        query = _read_metaphlan_species_profile(profile, sample_id)
        if query is not None:
            return query, "metaphlan_profile"
    return None, ""


def _donor_outcome_summary(meta: pd.DataFrame) -> dict[str, dict]:
    summaries: dict[str, dict] = {}
    recipients = meta[meta.get("group", "").astype(str).str.lower().eq("recipient")].copy()
    for donor_id, group in recipients.dropna(subset=["donor"]).groupby("donor"):
        labels = group["label"].astype(str)
        known = labels.isin(["Res", "NoRes"])
        responders = int(labels.eq("Res").sum())
        nonresponders = int(labels.eq("NoRes").sum())
        summaries[str(donor_id)] = {
            "historical_recipient_count": int(len(group)),
            "known_outcome_count": int(known.sum()),
            "responder_count": responders,
            "nonresponder_count": nonresponders,
            "historical_response_rate": round(responders / int(known.sum()), 4) if known.any() else None,
        }
    return summaries


def _generate_triplet_projection(
    query_id: str,
    query_embedding: np.ndarray,
    donor_ids: list[str],
    donor_embeddings: np.ndarray,
    top_ids: set[str],
    output_path: Path,
) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.decomposition import PCA

    all_embeddings = np.vstack([donor_embeddings, query_embedding])
    coordinates = PCA(n_components=2, random_state=42).fit_transform(all_embeddings)
    donor_xy, query_xy = coordinates[:-1], coordinates[-1]
    fig, ax = plt.subplots(figsize=(10, 7.5))
    ax.scatter(donor_xy[:, 0], donor_xy[:, 1], c="#87B9B3", s=58, alpha=0.72, label="Candidate donors")
    for index, donor_id in enumerate(donor_ids):
        if donor_id in top_ids:
            ax.scatter(donor_xy[index, 0], donor_xy[index, 1], c="#EF8354", s=82, edgecolors="white", linewidth=0.7)
            ax.annotate(donor_id, donor_xy[index], xytext=(5, 5), textcoords="offset points", fontsize=7)
    ax.scatter(query_xy[0], query_xy[1], marker="*", c="#FFD166", edgecolors="#202B33", s=280, linewidth=1.1, label=f"Query: {query_id}", zorder=5)
    ax.set(title="FMT triplet-model embedding projection", xlabel="PCA 1", ylabel="PCA 2")
    ax.legend(frameon=False)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _run_triplet_pipeline(sample_id: str, output_dir: Optional[str], top_k: int) -> Dict:
    required = [
        TRIPLET_MODEL_DIR / "feature_schema.json",
        TRIPLET_MODEL_DIR / "fmt_triplet_contrastive_model.npz",
        TRIPLET_BASELINE_SPECIES,
        TRIPLET_MATCH_FILE,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        return {"status": "unavailable", "message": f"三元组模型文件缺失: {missing[0]}", "top_k_matches": [], "tsne_plot_path": None}
    query, query_source = _load_triplet_query(sample_id)
    if query is None:
        return {"status": "unavailable", "message": f"未找到样本 {sample_id} 的物种丰度谱", "top_k_matches": [], "tsne_plot_path": None}
    module = _load_triplet_module()
    predictor = module.FMTTripletPredictor(TRIPLET_MODEL_DIR)
    baseline = pd.read_csv(TRIPLET_BASELINE_SPECIES, index_col=0)
    baseline.index = baseline.index.astype(str)
    meta = pd.read_excel(TRIPLET_MATCH_FILE)
    donor_ids = meta.loc[meta["group"].astype(str).str.lower().eq("donor"), "sample_id"].dropna().astype(str).drop_duplicates().tolist()
    donor_ids = [donor_id for donor_id in donor_ids if donor_id in baseline.index and donor_id != sample_id]
    if not donor_ids:
        return {"status": "unavailable", "message": "排除自匹配后无有效候选供体", "top_k_matches": []}
    donors = baseline.loc[donor_ids]
    query_batch = predictor.align(query, "percent")
    donor_batch = predictor.align(donors, "percent")
    audit = query_batch.audit.iloc[0].to_dict()
    if float(audit.get("feature_name_coverage", 0)) < 0.5:
        return {
            "status": "degraded",
            "message": f"样本物种特征覆盖不足: {float(audit.get('feature_name_coverage', 0)):.1%}",
            "top_k_matches": [], "tsne_plot_path": None, "feature_audit": audit,
        }
    distances = np.sum((donor_batch.embedding - query_batch.embedding[0]) ** 2, axis=1)
    order = np.argsort(distances)
    outcomes = _donor_outcome_summary(meta)
    matches: list[dict] = []
    candidate_count = len(donor_ids)
    distance_scale = max(float(np.median(distances)), 1e-9)
    for rank, index in enumerate(order[: min(top_k, candidate_count)], start=1):
        donor_id = donor_ids[int(index)]
        distance = float(distances[int(index)])
        matches.append({
            "rank": rank,
            "donor_id": donor_id,
            "score": round(float(np.exp(-distance / distance_scale)), 4),
            "score_type": "relative_embedding_similarity",
            "distance": round(distance, 6),
            "label": "historical_donor",
            **outcomes.get(donor_id, {}),
        })
    plot_path = None
    if output_dir and candidate_count >= 2:
        plot_path = Path(output_dir) / f"{sample_id}_fmt_tsne.png"
        _generate_triplet_projection(
            sample_id, query_batch.embedding, donor_batch.sample_ids, donor_batch.embedding,
            {item["donor_id"] for item in matches[:5]}, plot_path,
        )
    warnings = []
    if float(audit.get("abundance_coverage", 0)) < 0.2:
        warnings.append("模型特征覆盖的总丰度低于20%，排名稳定性可能下降")
    return {
        "status": "ok",
        "message": f"三元组对比模型完成 {candidate_count} 个候选供体排序，返回 Top {len(matches)}",
        "top_k_matches": matches,
        "tsne_plot_path": str(plot_path) if plot_path else None,
        "plot_method": "PCA",
        "sample_embedding": query_batch.embedding[0].tolist(),
        "feature_audit": audit,
        "candidate_count": candidate_count,
        "query_source": query_source,
        "model_name": "fmt-triplet-contrastive",
        "model_version": "1.0.0",
        "method": "CLR + train-fold scaling + triplet projection + squared embedding distance",
        "warnings": warnings,
    }


# ============================================================================
# 主入口
# ============================================================================

def run_fmt_pipeline(
    sample_id: str,
    genus_file: str,
    output_dir: Optional[str] = None,
    top_k: int = 10,
    device_str: str = "cpu",
) -> Dict:
    """
    执行完整的 FMT 配型 pipeline，返回匹配结果。

    Parameters
    ----------
    sample_id : str
        当前样本 ID（受体）。
    genus_file : str
        属水平丰度文件路径（用于提取查询样本的物种丰度）。
    output_dir : str or None
        t-SNE 图片输出目录。
    top_k : int
        返回 Top-K 候选供体数量。
    device_str : str
        训练/推理设备 ("cpu" 或 "cuda")。

    Returns
    -------
    dict:
        'status': 'ok' | 'degraded' | 'unavailable'
        'top_k_matches' : List[dict] 每个元素 {"donor_id": str, "score": float, "label": str}
        'tsne_plot_path' : str or None
        'message' : str
        'sample_embedding' : np.ndarray or None
    """
    result = {
        "status": "unavailable",
        "top_k_matches": [],
        "tsne_plot_path": None,
        "message": "",
        "sample_embedding": None,
    }

    # Preferred path: the in-project, versioned triplet artifact has no R or
    # sibling-repository dependency and supports genuinely unseen samples.
    try:
        triplet_result = _run_triplet_pipeline(sample_id, output_dir, top_k)
        if triplet_result.get("status") in {"ok", "degraded"}:
            return triplet_result
        result["triplet_fallback_reason"] = triplet_result.get("message", "")
    except Exception as exc:
        result["triplet_fallback_reason"] = f"三元组模型异常: {type(exc).__name__}: {str(exc)[:180]}"

    if not os.path.isdir(_FMT_MATCHING_DIR):
        result["message"] = "FMT 配型模块目录不存在"
        return result

    if not os.path.exists(ABUNDANCE_FILE):
        result["message"] = f"训练丰度库不存在: {ABUNDANCE_FILE}"
        return result

    if not os.path.exists(META_FILE):
        result["message"] = f"配对元数据不存在: {META_FILE}"
        return result

    if not _src_available:
        detail = f"，具体原因: {_src_import_error}" if _src_import_error else ""
        result["message"] = f"FMT 配型核心模块导入失败（缺少 src/ 依赖{detail}）"
        return result

    try:
        # ---- Step 1: 加载或运行 mbDenoise ----
        print("[FMT] Step 1/4: 加载/运行 mbDenoise 去批次矩阵...")
        mbdenoise_df, mbdenoise_message = _load_or_run_mbdenoise()
        if mbdenoise_df is None:
            result["status"] = "degraded"
            result["message"] = f"mbDenoise 不可用: {mbdenoise_message}"
            return result
        print(f"       mbDenoise 矩阵形状: {mbdenoise_df.shape}")

        # ---- Step 2: 加载或训练对比学习模型 ----
        print("[FMT] Step 2/4: 加载/训练对比学习模型...")
        meta_df = pd.read_excel(META_FILE)

        # 构建配对索引
        paired_indices = build_paired_indices(meta_df, mbdenoise_df.index)
        if len(paired_indices) == 0:
            result["status"] = "degraded"
            result["message"] = "未找到有效的供体-受体配对数据"
            return result

        print(f"       配对样本数: {len(paired_indices)}")

        model, model_message = _train_or_load_model(
            mbdenoise_df, paired_indices, device_str
        )
        if model is None:
            result["status"] = "degraded"
            result["message"] = f"模型不可用: {model_message}"
            return result
        print(f"       模型状态: {model_message}")

        # ---- Step 3: 提取查询样本丰度 ----
        print(f"[FMT] Step 3/4: 提取样本 {sample_id} 的物种丰度...")
        query_vector = _extract_query_abundance(sample_id, genus_file, mbdenoise_df)
        if query_vector is None:
            result["status"] = "degraded"
            result["message"] = f"无法提取样本 {sample_id} 的物种丰度（可能样本不在训练数据中）"
            return result

        # ---- Step 4: 计算匹配分数 ----
        print("[FMT] Step 4/4: 计算匹配分数...")
        top_matches, sample_emb = compute_matching_scores(
            model, mbdenoise_df, query_vector, meta_df,
            sample_id=sample_id,
            top_k=top_k, device_str=device_str,
        )
        result["top_k_matches"] = top_matches
        result["sample_embedding"] = sample_emb

        # ---- Step 5: 生成 t-SNE 图 ----
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            tsne_path = os.path.join(output_dir, f"{sample_id}_fmt_tsne.png")
            try:
                generate_fmt_tsne_plot(
                    model, mbdenoise_df, meta_df, paired_indices,
                    sample_id, query_vector,
                    output_path=tsne_path,
                    device_str=device_str,
                )
                result["tsne_plot_path"] = tsne_path
            except Exception as e:
                print(f"       [FMT] t-SNE 图生成失败: {e}")

        result["status"] = "ok"
        result["message"] = f"成功匹配 {len(top_matches)} 个候选供体"
        return result

    except Exception as e:
        traceback.print_exc()
        result["status"] = "degraded"
        result["message"] = f"FMT 配型 pipeline 异常: {str(e)[:200]}"
        return result


# ============================================================================
# 内部函数
# ============================================================================

def _load_or_run_mbdenoise() -> Tuple[Optional[pd.DataFrame], str]:
    """
    加载缓存的 mbDenoise 矩阵，或运行 R ZipPCA+Harmony。

    Returns
    -------
    (DataFrame or None, message)
    """
    if os.path.exists(MBDENOISE_CACHE):
        try:
            df = pd.read_csv(MBDENOISE_CACHE, index_col=0)
            return df, "已加载缓存矩阵"
        except Exception as e:
            print(f"       [FMT] 缓存读取失败: {e}")

    # 尝试运行 R 脚本
    if not os.path.exists(R_SCRIPT):
        return None, f"R 脚本不存在: {R_SCRIPT}"

    if not os.path.exists(ABUNDANCE_FILE):
        return None, f"训练数据不存在: {ABUNDANCE_FILE}"

    if not os.path.exists(META_FILE):
        return None, f"元数据不存在: {META_FILE}"

    try:
        print("       [FMT] 运行 R ZipPCA + Harmony (可能需要几分钟)...")
        os.makedirs(_FMT_OUTPUT_DIR, exist_ok=True)
        results = run_zippca_analysis(
            input_csv=ABUNDANCE_FILE,
            meta_xlsx=META_FILE,
            output_dir=_FMT_OUTPUT_DIR,
            r_script_path=R_SCRIPT,
        )
        if "denoised_matrix" in results:
            df = results["denoised_matrix"]
            return df, "R ZipPCA+Harmony 完成"
        else:
            return None, "R 脚本返回结果中缺少 denoised_matrix"
    except Exception as e:
        print(f"       [FMT] R 脚本执行失败: {e}")
        return None, f"R 运行失败: {str(e)[:100]}"


def _train_or_load_model(
    mbdenoise_df: pd.DataFrame,
    paired_indices: list,
    device_str: str = "cpu",
) -> Tuple[Optional[object], str]:
    """
    加载缓存的对比学习模型，或从头训练。

    Returns
    -------
    (model or None, message)
    """
    import torch

    device = torch.device(device_str if torch.cuda.is_available() else "cpu")
    input_dim = mbdenoise_df.shape[1]

    # 尝试加载缓存
    if os.path.exists(MODEL_CACHE):
        try:
            model = ContrastiveEncoder(
                input_dim=input_dim, hidden_dim=256, proj_dim=64, dropout=0.2
            ).to(device)
            model.load_state_dict(torch.load(MODEL_CACHE, map_location=device))
            model.eval()
            return model, "已加载缓存模型"
        except Exception as e:
            print(f"       [FMT] 模型缓存加载失败: {e}，重新训练...")

    # 从头训练
    try:
        X_tensor = torch.FloatTensor(mbdenoise_df.values).to(device)
        print("       [FMT] 开始 K-Fold 训练对比学习模型 (可能需要较长时间)...")
        model, loss_history = train_kfold(
            X_tensor=X_tensor,
            paired_indices=paired_indices,
            input_dim=input_dim,
            device=device,
            n_splits=8,
            epochs=1000,
            lr=5e-3,
            weight_decay=1e-3,
            temperature=0.001,
            batch_size=16,
            use_negatives=False,
        )
        # 保存模型
        os.makedirs(_FMT_OUTPUT_DIR, exist_ok=True)
        torch.save(model.state_dict(), MODEL_CACHE)
        print(f"       [FMT] 模型已保存至: {MODEL_CACHE}")
        return model, "训练并缓存完成"
    except Exception as e:
        traceback.print_exc()
        return None, f"训练失败: {str(e)[:100]}"


def _extract_query_abundance(
    sample_id: str,
    genus_file: str,
    mbdenoise_df: pd.DataFrame,
) -> Optional[np.ndarray]:
    """
    从训练丰度矩阵中提取查询样本的行。

    如果查询样本不在 mbDenoise 矩阵中（即不在训练集），则尝试从
    属水平丰度文件中提取并通过公共物种列对齐。
    """
    # 1. 先尝试直接匹配 mbDenoise 索引
    if sample_id in mbdenoise_df.index:
        return mbdenoise_df.loc[sample_id].values.astype(np.float32)

    # 2. 从属水平文件提取，尝试对齐
    if not os.path.exists(genus_file):
        return None

    try:
        genus = pd.read_csv(genus_file, sep='\t', index_col=0)
    except Exception:
        return None

    # 转置使样本为行
    if sample_id in genus.columns:
        row = genus[sample_id]
        from wgs_agent.pipeline.report_common import metaphlan_name_to_genus

        # 聚合到属水平
        genus_dict = {}
        for idx, val in row.items():
            g = metaphlan_name_to_genus(idx)
            if g:
                genus_dict[g] = genus_dict.get(g, 0) + val

        # 尝试匹配 mbdenoise_df 的列
        query_vec = np.zeros(mbdenoise_df.shape[1], dtype=np.float32)
        matched = 0
        for i, col in enumerate(mbdenoise_df.columns):
            col_clean = col.replace("g__", "").replace("s__", "")
            if col_clean in genus_dict:
                query_vec[i] = genus_dict[col_clean]
                matched += 1

        if matched > 0:
            return query_vec
        return None

    return None


def compute_matching_scores(
    model,
    mbdenoise_df: pd.DataFrame,
    query_vector: np.ndarray,
    meta_df: pd.DataFrame,
    sample_id: str = "",
    top_k: int = 10,
    device_str: str = "cpu",
) -> Tuple[List[Dict], Optional[np.ndarray]]:
    """
    使用对比学习模型提取所有样本嵌入，计算 cosine 相似度。

    Parameters
    ----------
    model : ContrastiveEncoder
        已训练的对比学习模型。
    mbdenoise_df : pd.DataFrame
        去批次丰度矩阵 (样本 x 物种)。
    query_vector : np.ndarray
        查询样本的物种丰度向量。
    meta_df : pd.DataFrame
        元数据（含 sample_id, label 列）。
    sample_id : str
        查询样本 ID，用于在匹配时排除自身。
    top_k : int
        返回的候选供体数量。
    device_str : str
        计算设备。

    Returns
    -------
    (top_matches: List[dict], sample_embedding: np.ndarray or None)
    """
    import torch
    import torch.nn.functional as F  # noqa

    device = torch.device(device_str if torch.cuda.is_available() else "cpu")
    model.eval()
    model.to(device)

    # 1. 提取所有训练样本的嵌入
    X_tensor = torch.FloatTensor(mbdenoise_df.values).to(device)
    with torch.no_grad():
        _, Z_all = model(X_tensor)  # (N, proj_dim)
    Z_all_np = Z_all.cpu().numpy()

    # 2. 提取查询样本的嵌入
    x_query = torch.FloatTensor(query_vector).unsqueeze(0).to(device)
    with torch.no_grad():
        _, z_query = model(x_query)
    z_query_np = z_query.cpu().numpy().flatten()

    # 3. 归一化后计算 cosine 相似度
    z_query_norm = z_query_np / (np.linalg.norm(z_query_np) + 1e-12)
    Z_all_norm = Z_all_np / (np.linalg.norm(Z_all_np, axis=1, keepdims=True) + 1e-12)
    similarities = Z_all_norm @ z_query_norm  # (N,)

    # 4. 排序取 Top-K（排除自己）
    sample_ids = list(mbdenoise_df.index)
    scored = list(zip(sample_ids, similarities))
    scored.sort(key=lambda x: -x[1])

    # 构建 meta 查找: sample_id -> label
    label_map = {}
    if "sample_id" in meta_df.columns and "label" in meta_df.columns:
        for _, row in meta_df.iterrows():
            label_map[str(row["sample_id"])] = str(row.get("label", ""))

    top_matches = []
    for sid, score in scored[:top_k + 5]:
        if sample_id and sid == sample_id:
            continue
        top_matches.append({
            "donor_id": sid,
            "score": round(float(score), 4),
            "label": label_map.get(sid, ""),
        })
        if len(top_matches) >= top_k:
            break

    return top_matches, z_query_np


def generate_fmt_tsne_plot(
    model,
    mbdenoise_df: pd.DataFrame,
    meta_df: pd.DataFrame,
    paired_indices: list,
    sample_id: str,
    query_vector: np.ndarray,
    output_path: str,
    device_str: str = "cpu",
    perplexity: int = 30,
):
    """
    生成 FMT 配型 t-SNE 散点图：
    - 供体（健康）用一种颜色，受体（疾病）用另一种颜色
    - 当前样本用星形高亮标出
    - 供体-受体配对连线

    Parameters
    ----------
    model : ContrastiveEncoder
    mbdenoise_df : pd.DataFrame
    meta_df : pd.DataFrame
    paired_indices : list
    sample_id : str
    query_vector : np.ndarray
    output_path : str
    device_str : str
    perplexity : int
    """
    import torch
    try:
        setup_cn_font()
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from sklearn.manifold import TSNE
    except ImportError as exc:
        raise RuntimeError(f"t-SNE 绘图依赖缺失: {exc}") from exc

    device = torch.device(device_str if torch.cuda.is_available() else "cpu")
    model.eval()
    model.to(device)

    # 1. 提取所有嵌入
    X_tensor = torch.FloatTensor(mbdenoise_df.values).to(device)
    with torch.no_grad():
        _, Z_all = model(X_tensor)
    Z_all_np = Z_all.cpu().numpy()

    # 2. 提取查询样本嵌入
    x_query = torch.FloatTensor(query_vector).unsqueeze(0).to(device)
    with torch.no_grad():
        _, z_query = model(x_query)
    z_query_np = z_query.cpu().numpy()

    # 3. 合并所有嵌入
    all_embeddings = np.vstack([Z_all_np, z_query_np])
    n_train = Z_all_np.shape[0]
    query_idx = n_train

    # 4. t-SNE 降维
    tsne = TSNE(
        n_components=2,
        perplexity=min(perplexity, n_train - 1),
        random_state=42,
        init="pca",
        learning_rate="auto",
    )
    all_tsne = tsne.fit_transform(all_embeddings)
    train_tsne = all_tsne[:n_train]
    query_tsne = all_tsne[query_idx]

    # 5. 构建颜色标签
    sample_ids = list(mbdenoise_df.index)

    donor_set = set()
    recipient_set = set()
    label_map = {}
    if "label" in meta_df.columns:
        for _, row in meta_df.iterrows():
            sid = str(row.get("sample_id", ""))
            lbl = str(row.get("label", ""))
            label_map[sid] = lbl
            if lbl == "Res":
                recipient_set.add(sid)
            elif lbl == "NonRes":
                recipient_set.add(sid)
            if "donor" in row.index and pd.notna(row.get("donor")):
                donor_set.add(str(row["donor"]))

    group_labels = []
    for sid in sample_ids:
        if sid in donor_set:
            group_labels.append("Donor")
        elif sid in recipient_set:
            group_labels.append("Recipient")
        else:
            lbl = label_map.get(sid, "")
            if lbl in ("Res", "NonRes"):
                group_labels.append("Recipient")
            elif lbl == "donor":
                group_labels.append("Donor")
            else:
                group_labels.append("Unknown")

    group_series = pd.Series(group_labels)
    donor_mask = group_series == "Donor"
    recipient_mask = group_series == "Recipient"
    unknown_mask = ~(donor_mask | recipient_mask)

    # 6. 绘图
    fig, ax = plt.subplots(figsize=(12, 10))

    if unknown_mask.any():
        ax.scatter(
            train_tsne[unknown_mask, 0], train_tsne[unknown_mask, 1],
            c="#9E9E9E", s=40, alpha=0.5, label="Unknown", edgecolors="none"
        )
    if recipient_mask.any():
        ax.scatter(
            train_tsne[recipient_mask, 0], train_tsne[recipient_mask, 1],
            c="#d62728", s=60, alpha=0.7, label="Recipient (Disease)",
            edgecolors="white", linewidth=0.3
        )
    if donor_mask.any():
        ax.scatter(
            train_tsne[donor_mask, 0], train_tsne[donor_mask, 1],
            c="#2ca02c", s=60, alpha=0.7, label="Donor (Healthy)",
            edgecolors="white", linewidth=0.3
        )

    for a, b in paired_indices[:300]:  # 限制连线数量避免过密
        ax.plot(
            [train_tsne[a, 0], train_tsne[b, 0]],
            [train_tsne[a, 1], train_tsne[b, 1]],
            color="#333333", alpha=0.15, lw=0.6, ls="--"
        )

    ax.scatter(
        query_tsne[0], query_tsne[1],
        c="#FFD700", s=300, marker="*", edgecolors="black",
        linewidth=1.5, label=f"Query: {sample_id}", zorder=10
    )
    ax.annotate(
        sample_id,
        (query_tsne[0], query_tsne[1]),
        xytext=(8, 8), textcoords="offset points",
        fontsize=9, fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.3", fc="yellow", alpha=0.7)
    )

    ax.set_title(
        f"FMT Donor Matching — t-SNE Projection\nQuery Sample: {sample_id}",
        fontsize=13, fontweight="bold"
    )
    ax.set_xlabel("t-SNE 1")
    ax.set_ylabel("t-SNE 2")
    ax.legend(loc="upper right", framealpha=0.9, fontsize=9)
    ax.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"       [FMT] t-SNE 图保存: {os.path.basename(output_path)}")


def enrich_matching_report(sample_id: str, result: dict) -> dict:
    """Attach reproducible library/validation context without claiming causality."""
    import json
    import hashlib
    enriched = dict(result)
    enriched["report_context_version"] = "2"
    if result.get("status") != "ok" or result.get("model_name") != "fmt-triplet-contrastive":
        return enriched
    warnings = list(result.get("warnings") or [])
    try:
        baseline = pd.read_csv(TRIPLET_BASELINE_SPECIES, index_col=0)
        baseline.index = baseline.index.astype(str)
        meta = pd.read_excel(TRIPLET_MATCH_FILE)
        query, _ = _load_triplet_query(sample_id)
        if query is None:
            raise ValueError("当前样本丰度缺失")
        donor_meta = meta[meta["group"].astype(str).str.lower().eq("donor")]
        enriched["library_audit"] = {
            "metadata_rows": len(meta), "abundance_samples": len(baseline),
            "donor_ids_in_metadata": int(donor_meta["sample_id"].nunique()),
            "candidate_donors_with_profiles": result.get("candidate_count"),
            "reference_feature_count": len(baseline.columns),
            "query_in_baseline_library": sample_id in baseline.index,
            "clinical_screening_status": "not_available",
            "metadata_sha256": hashlib.sha256(TRIPLET_MATCH_FILE.read_bytes()).hexdigest(),
            "abundance_sha256": hashlib.sha256(TRIPLET_BASELINE_SPECIES.read_bytes()).hexdigest(),
        }
        recipients = meta[meta["group"].astype(str).str.lower().eq("recipient")]
        matches = []
        for item in result.get("top_k_matches", []):
            item = dict(item)
            donor_id = str(item["donor_id"])
            history = recipients[recipients["donor"].astype(str).eq(donor_id)]
            item["historical_context"] = {"counting_unit": "metadata_rows", "patient_deduplicated": False}
            for col in ("project", "project_id", "bioproject", "disease", "phenotype", "Disease", "Project"):
                if col in history:
                    item["historical_context"][col] = {str(k): int(v) for k,v in history[col].dropna().astype(str).value_counts().items()}
            if donor_id in baseline.index:
                shared = query.columns.intersection(baseline.columns)
                q = pd.to_numeric(query.iloc[0].reindex(shared), errors="coerce")
                d = pd.to_numeric(baseline.loc[donor_id].reindex(shared), errors="coerce")
                diff = (d-q).dropna()
                chosen = diff.abs().sort_values(ascending=False).head(10).index
                item["species_comparison"] = [{"species": str(k).rsplit("|",1)[-1].removeprefix("s__").replace("_"," "), "query": float(q[k]), "donor": float(d[k]), "difference": float(diff[k]), "unit": "percent", "interpretation": "descriptive_not_model_attribution"} for k in chosen]
            matches.append(item)
        enriched["top_k_matches"] = matches
        manifest_path = TRIPLET_MODEL_DIR / "model_manifest.json"
        summary_path = TRIPLET_MODEL_DIR / "metrics_summary.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text())
            if str(manifest.get("version")) == str(result.get("model_version")) and manifest.get("name") == result.get("model_name"):
                enriched["validation_summary"] = {
                    "scheme": manifest.get("validation"),
                    "training_dataset_version": manifest.get("training_dataset_version"),
                    "metrics": manifest.get("metrics", {}),
                    "model_sha256": hashlib.sha256((TRIPLET_MODEL_DIR / "fmt_triplet_contrastive_model.npz").read_bytes()).hexdigest(),
                }
                if summary_path.is_file():
                    summary = json.loads(summary_path.read_text())
                    enriched["validation_summary"]["training_audit"] = summary.get("audit", {})
                    enriched["validation_summary"]["reported_cv_intervals"] = summary.get("cross_validation", {})
        if sample_id in baseline.index:
            warnings.append("查询样本已存在于基础样本库，本次结果不能称为独立外部验证；是否参加模型训练需核对训练清单")
        warnings.append("历史响应率按元数据记录汇总，未验证为独立患者，不能作为本受体成功概率")
    except Exception as exc:
        warnings.append(f"配对报告背景补充未完成：{type(exc).__name__}: {str(exc)[:160]}")
    enriched["warnings"] = list(dict.fromkeys(warnings))
    return enriched
