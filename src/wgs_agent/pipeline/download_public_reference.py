#!/usr/bin/env python3
"""从公开宏基因组数据集下载健康样本，计算物种和代谢物参考范围

数据来源:
  curatedMetagenomicData v3 (https://waldronlab.io/curatedMetagenomicData/)
  Zenodo record 7919439 — 预计算的 MetaPhlAn4 物种丰度矩阵

策略:
  1. 下载样本元数据 → 筛选健康成年人粪便样本
  2. 下载物种丰度 TSV（必须另行核验实际分析版本）
  3. 下载 HUMAnN 通路丰度 → 通过 AGORA 模型推算代谢物参考范围
  4. 计算 P5/P50/P95 并保存

用法:
  python3 src/wgs_agent/pipeline/download_public_reference.py
  # 或指定输出目录:
  python3 src/wgs_agent/pipeline/download_public_reference.py --out-dir /path/to/output
"""

from __future__ import annotations

import argparse
import gzip
import os
import sys
import time
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import numpy as np
import pandas as pd
import requests

# ── 路径配置 ──
from wgs_fmt_platform.paths import runtime_path

REF_DIR = runtime_path("WGS_REFERENCE_DIR", "reference")
CACHE_DIR = runtime_path("WGS_REFERENCE_CACHE_DIR", "cache", "public-reference")

# ── curatedMetagenomicData 资源 URL ──
# 样本元数据 (包含 health status)
METADATA_URL = (
    "https://zenodo.org/records/7919439/files/"
    "curatedMetagenomicData_sample_metadata_3.8.0.tsv.gz"
)

# 历史物种矩阵 URL；不能据文件名推断为 MetaPhlAn4，使用前核验来源和版本。
SPECIES_MATRIX_URL = (
    "https://zenodo.org/records/7919439/files/"
    "curatedMetagenomicData_metaphlan_bugs_species_3.8.0.tsv.gz"
)

# HUMAnN 通路丰度矩阵 (pathway × sample)
PATHWAY_MATRIX_URL = (
    "https://zenodo.org/records/7919439/files/"
    "curatedMetagenomicData_humann_pathabundance_3.8.0.tsv.gz"
)

# ── 工具函数 ──


def download_file(url: str, dest: Path, desc: str = "") -> Path:
    """下载文件，带进度条和断点续传检测"""
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        print(f"  [{desc}] 已存在: {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
        return dest

    print(f"  [{desc}] 下载中: {url}")
    start = time.time()
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))

    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as f:
        downloaded = 0
        for chunk in resp.iter_content(chunk_size=8192 * 16):
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = downloaded / total * 100
                mb = downloaded / 1e6
                print(f"\r    {pct:.0f}% ({mb:.1f} MB)", end="", flush=True)

    tmp.rename(dest)
    elapsed = time.time() - start
    print(f"\r  [{desc}] 完成: {dest.stat().st_size / 1e6:.1f} MB ({elapsed:.0f}s)")

    return dest


def filter_healthy_adult_stool(metadata_path: Path) -> pd.DataFrame:
    """从元数据中筛选健康成年人粪便样本

    筛选条件:
      - body_site == "stool"
      - age >= 18 (如果存在)
      - study_condition 包含 "control" 或 "healthy"
      - 排除 IBD/CRC/T2D/obesity 等疾病状态
    """
    print("\n[筛选] 健康成年人粪便样本...")

    # 读取 TSV (可能 gzip 压缩)
    if metadata_path.suffix == ".gz":
        df = pd.read_csv(metadata_path, sep="\t", compression="gzip", low_memory=False)
    else:
        df = pd.read_csv(metadata_path, sep="\t", low_memory=False)

    print(f"  总样本数: {len(df)}")

    # 过滤粪便样本
    stool = df[df["body_site"].str.lower() == "stool"]
    print(f"  粪便样本: {len(stool)}")

    # 过滤健康状态
    condition_col = "study_condition" if "study_condition" in stool.columns else "disease"
    if condition_col in stool.columns:
        mask = stool[condition_col].astype("string").str.strip().str.casefold().isin(
            {"control", "healthy"}
        )
        healthy = stool[mask]
        if condition_col != "disease" and "disease" in healthy:
            disease = healthy["disease"].astype("string").str.strip().str.casefold()
            healthy = healthy[disease.isna() | disease.isin({"control", "healthy", "none"})]
        print(f"  健康样本: {len(healthy)}")
    else:
        raise ValueError("缺少健康状态列，不能将全部样本作为健康对照")

    # 过滤成人 (age >= 18)
    if "age" in healthy.columns:
        healthy = healthy[pd.to_numeric(healthy["age"], errors="coerce").ge(18)]
        print(f"  成年健康样本: {len(healthy)}")
    else:
        raise ValueError("缺少年龄信息，不能建立健康成年人参考")
    if not {"study_name", "subject_id"}.issubset(healthy.columns):
        raise ValueError("缺少研究及个体标识，不能核验独立健康人数")
    healthy = healthy.dropna(subset=["study_name", "subject_id"]).copy()
    for column in ("study_name", "subject_id"):
        healthy = healthy[healthy[column].astype(str).str.strip().ne("")]
    healthy = healthy.sort_values("sample_id").drop_duplicates(["study_name", "subject_id"])

    # 去重按 study_name 均衡采样 (每研究最多取 500 样本)
    if "study_name" in healthy.columns:
        sampled = []
        for study, grp in healthy.groupby("study_name"):
            take = min(len(grp), 500)
            sampled.append(grp.sample(n=take, random_state=42) if take < len(grp) else grp)
        healthy = pd.concat(sampled, ignore_index=True) if sampled else healthy

    print(f"  最终健康样本: {len(healthy)} (来自 {healthy.get('study_name', pd.Series()).nunique()} 个研究)")
    return healthy


def build_species_reference_from_matrix(
    species_matrix_path: Path,
    sample_ids: set[str],
    output_path: Path,
    min_detection_rate: float = 0.02,
    min_median: float = 0.0001,
) -> Path:
    """从公开物种矩阵计算参考范围"""
    print("\n[物种参考] 读取矩阵...")

    # 读取矩阵 (可能 gzip)
    if species_matrix_path.suffix == ".gz":
        matrix = pd.read_csv(species_matrix_path, sep="\t", index_col=0, compression="gzip")
    else:
        matrix = pd.read_csv(species_matrix_path, sep="\t", index_col=0)

    print(f"  矩阵: {matrix.shape[0]} 物种 × {matrix.shape[1]} 样本")

    # 匹配样本列
    avaliable = [c for c in matrix.columns if c in sample_ids]
    print(f"  匹配到 {len(avaliable)} 个目标样本")

    if len(avaliable) < 30:
        raise ValueError("匹配健康参考样本不足 30，禁止回退到包含疾病样本的全量矩阵")

    sub = matrix[avaliable]
    sub = sub.loc[sub.sum(axis=1) > 0]  # 移除全零行
    print(f"  有效物种: {len(sub)}")

    # 计算百分位数
    n = len(avaliable)
    results = []
    for species, row in sub.iterrows():
        vals = row.values.astype(float)
        detection_rate = (vals > 0).sum() / n
        p5 = float(np.percentile(vals, 5))
        p25 = float(np.percentile(vals, 25))
        p50 = float(np.percentile(vals, 50))
        p75 = float(np.percentile(vals, 75))
        p95 = float(np.percentile(vals, 95))

        results.append({
            "species": species,
            "p5": round(p5, 6),
            "p25": round(p25, 6),
            "p50": round(p50, 6),
            "p75": round(p75, 6),
            "p95": round(p95, 6),
            "detection_rate": round(detection_rate, 4),
            "n_detected": int((vals > 0).sum()),
            "mean": round(float(np.mean(vals)), 6),
            "max": round(float(np.max(vals)), 6),
        })

    ref = pd.DataFrame(results)
    mask = (ref["detection_rate"] >= min_detection_rate) | (ref["p50"] >= min_median)
    ref = ref[mask].sort_values("p50", ascending=False)

    print(f"  过滤后保留物种: {len(ref)}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ref.to_csv(output_path, sep="\t", index=False)
    print(f"  已保存: {output_path}")

    return output_path


def build_pathway_reference_from_matrix(
    pathway_matrix_path: Path,
    sample_ids: set[str],
    output_path: Path,
    min_detection_rate: float = 0.10,
) -> Optional[Path]:
    """从公开通路丰度矩阵计算通路参考范围"""
    print("\n[代谢通路参考] 读取矩阵...")

    if pathway_matrix_path.suffix == ".gz":
        matrix = pd.read_csv(pathway_matrix_path, sep="\t", index_col=0, compression="gzip")
    else:
        matrix = pd.read_csv(pathway_matrix_path, sep="\t", index_col=0)

    print(f"  矩阵: {matrix.shape[0]} 通路 × {matrix.shape[1]} 样本")

    avaliable = [c for c in matrix.columns if c in sample_ids]
    print(f"  匹配到 {len(avaliable)} 个目标样本")

    if len(avaliable) < 30:
        raise ValueError("匹配健康参考样本不足 30，禁止回退到包含疾病样本的全量矩阵")

    sub = matrix[avaliable]
    sub = sub.loc[sub.sum(axis=1) > 0]
    print(f"  有效通路: {len(sub)}")

    n = len(avaliable)
    results = []
    for pathway, row in sub.iterrows():
        vals = row.values.astype(float)
        detection_rate = (vals > 0).sum() / n
        p5 = float(np.percentile(vals, 5))
        p25 = float(np.percentile(vals, 25))
        p50 = float(np.percentile(vals, 50))
        p75 = float(np.percentile(vals, 75))
        p95 = float(np.percentile(vals, 95))

        results.append({
            "pathway": pathway,
            "p5": round(p5, 6),
            "p25": round(p5, 6),
            "p50": round(p50, 6),
            "p75": round(p75, 6),
            "p95": round(p95, 6),
            "detection_rate": round(detection_rate, 4),
            "n_detected": int((vals > 0).sum()),
            "mean": round(float(np.mean(vals)), 6),
        })

    ref = pd.DataFrame(results)
    mask = ref["detection_rate"] >= min_detection_rate
    ref = ref[mask].sort_values("p50", ascending=False)

    print(f"  过滤后保留通路: {len(ref)}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ref.to_csv(output_path, sep="\t", index=False)
    print(f"  已保存: {output_path}")

    return output_path


def main():
    parser = argparse.ArgumentParser(description="下载公开数据集并计算参考范围")
    parser.add_argument("--out-dir", default=str(REF_DIR), help="输出目录")
    parser.add_argument("--cache-dir", default=str(CACHE_DIR), help="缓存目录")
    parser.add_argument("--max-samples", type=int, default=5000, help="最多使用的健康样本数")
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="跳过下载（使用已缓存的文件）",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("curatedMetagenomicData 公开参考数据库构建")
    print(f"  输出目录: {out_dir}")
    print(f"  缓存目录: {cache}")
    print("=" * 60)

    # ── Step 1: 下载元数据 ──
    meta_path = cache / "sample_metadata.tsv.gz"
    if not args.skip_download:
        download_file(METADATA_URL, meta_path, "样本元数据")

    if not meta_path.exists():
        raise ValueError("缺少健康队列元数据，不能构建健康参考库")
    else:
        # ── Step 2: 筛选健康样本 ──
        healthy = filter_healthy_adult_stool(meta_path)
        healthy.to_csv(
            out_dir / "public_healthy_samples.tsv", sep="\t", index=False
        )

        sample_ids = set(healthy["sample_id"].astype(str))
        print(f"  样本ID列表已保存: {out_dir / 'public_healthy_samples.tsv'}")

        if len(sample_ids) > args.max_samples:
            sample_ids = set(sorted(sample_ids)[: args.max_samples])
            print(f"  限制样本数至: {len(sample_ids)}")

    # ── Step 3: 下载物种丰度矩阵 ──
    species_cache = cache / "metaphlan_species.tsv.gz"
    if not args.skip_download:
        download_file(SPECIES_MATRIX_URL, species_cache, "物种丰度矩阵")

    if species_cache.exists():
        build_species_reference_from_matrix(
            species_matrix_path=species_cache,
            sample_ids=sample_ids if sample_ids else set(),
            output_path=out_dir / "species_p5_p95_public.tsv",
            min_detection_rate=0.02,
            min_median=0.0001,
        )

    # ── Step 4: 下载通路丰度矩阵 ──
    pathway_cache = cache / "humann_pathabundance.tsv.gz"
    if not args.skip_download:
        try:
            download_file(PATHWAY_MATRIX_URL, pathway_cache, "通路丰度矩阵")
        except Exception as e:
            print(f"  [跳过] 通路矩阵下载失败: {e}")
            pathway_cache = None

    if pathway_cache and pathway_cache.exists():
        build_pathway_reference_from_matrix(
            pathway_matrix_path=pathway_cache,
            sample_ids=sample_ids if sample_ids else set(),
            output_path=out_dir / "pathway_reference_public.tsv",
            min_detection_rate=0.10,
        )

    # ── Step 5: 生成融合参考库说明 ──
    readme = []
    readme.append("# 公开参考数据库说明\n")
    readme.append(f"数据来源: curatedMetagenomicData v3.8.0")
    readme.append(f"Zenodo: https://zenodo.org/records/7919439")
    readme.append(f"生成时间: {pd.Timestamp.now()}")
    if sample_ids:
        readme.append(f"健康样本数: {len(sample_ids)}")
    readme.append(f"\n## 文件说明")
    readme.append(f"- `species_p5_p95_public.tsv`: 物种 P5/P50/P95 参考范围")
    readme.append(f"- `pathway_reference_public.tsv`: 代谢通路 P5/P50/P95 参考范围")
    readme.append(f"- `public_healthy_samples.tsv`: 使用的健康样本列表")

    (out_dir / "README_public_reference.md").write_text("\n".join(readme))

    print("\n" + "=" * 60)
    print("完成！公开参考数据库已保存至:")
    print(f"  {out_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
