#!/usr/bin/env python3
"""扩充物种参考范围 + 建立代谢物参考范围

输入:
  - 物种: WGS.FMT/new_FMT_Matching/data/species_abundance_train.csv (132 样本 × 1973 物种)
  - 代谢物: 通过 step_metabolite_matrix 的输出矩阵（如已存在）
输出:
  - data/reference/species_p5_p95_extended.tsv
  - data/reference/metabolite_p5_p95.tsv (如代谢物矩阵存在)

用法:
  python3 src/wgs_agent/pipeline/build_extended_reference.py
"""

from __future__ import annotations


from wgs_fmt_platform.paths import fmt_matching_dir
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from wgs_fmt_platform.paths import runtime_path

WGS_FMT_ROOT = fmt_matching_dir()
REF_DIR = runtime_path("WGS_REFERENCE_DIR", "reference")


def build_species_reference(
    matrix_path: str | Path,
    output_path: str | Path,
    min_detection_rate: float = 0.05,
    min_median_abundance: float = 0.001,
) -> Path:
    """从物种×样本矩阵计算 P5/P50/P95 参考范围

    Args:
        matrix_path: CSV 文件，行=样本ID，列=物种名，值为相对丰度(%)
        output_path: 输出 TSV 路径
        min_detection_rate: 最低检出率（至少在此比例的样本中丰度>0）
        min_median_abundance: 最低中位数丰度(%)，低于此值的物种被过滤

    Returns:
        输出文件路径
    """
    print(f"读取物种矩阵: {matrix_path}")
    df = pd.read_csv(matrix_path, index_col=0)

    print(f"  -> 样本数: {df.shape[0]}, 物种数: {df.shape[1]}")

    # 为每个物种计算统计量
    n_samples = df.shape[0]
    results = []

    for species in df.columns:
        values = df[species].values.astype(float)

        # 检出率（丰度 > 0 的样本比例）
        detection_rate = (values > 0).sum() / n_samples

        # 非零丰度的百分位数
        nonzero = values[values > 0]

        p5 = float(np.percentile(values, 5))  # 全量 P5
        p25 = float(np.percentile(values, 25))
        p50 = float(np.percentile(values, 50))
        p75 = float(np.percentile(values, 75))
        p95 = float(np.percentile(values, 95))

        nonzero_p50 = float(np.median(nonzero)) if len(nonzero) > 0 else 0.0

        results.append(
            {
                "species": species,
                "p5": round(p5, 6),
                "p25": round(p25, 6),
                "p50": round(p50, 6),
                "p75": round(p75, 6),
                "p95": round(p95, 6),
                "nonzero_p50": round(nonzero_p50, 6),
                "detection_rate": round(detection_rate, 4),
                "n_detected": int((values > 0).sum()),
                "mean": round(float(np.mean(values)), 6),
                "max": round(float(np.max(values)), 6),
            }
        )

    ref_df = pd.DataFrame(results)

    # 过滤：检出率 ≥ min_detection_rate 或 中位数 ≥ min_median_abundance
    mask = (ref_df["detection_rate"] >= min_detection_rate) | (
        ref_df["p50"] >= min_median_abundance
    )
    ref_df = ref_df[mask].sort_values("p50", ascending=False)

    print(f"  -> 过滤后保留物种数: {len(ref_df)}")
    print(f"  -> 检出率分布: min={ref_df['detection_rate'].min():.2%}, "
          f"median={ref_df['detection_rate'].median():.2%}, max={ref_df['detection_rate'].max():.2%}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ref_df.to_csv(output_path, sep="\t", index=False)
    print(f"  -> 已保存: {output_path}")

    return output_path


def build_metabolite_reference(
    metabolite_matrix_path: str | Path,
    output_path: str | Path,
    min_detection_rate: float = 0.30,
) -> Path | None:
    """从代谢物×样本矩阵计算 P5/P50/P95 参考范围

    代谢物数据来自 HUMAnN3 + AGORA 模型推测，稀疏性比物种数据高。
    因此最低检出率阈值设置为 30%（vs 物种的 5%）。

    Args:
        metabolite_matrix_path: CSV 文件
        output_path: 输出 TSV 路径
        min_detection_rate: 最低检出率

    Returns:
        输出文件路径，如果输入文件不存在则返回 None
    """
    import_path = Path(metabolite_matrix_path)
    if not import_path.exists():
        print(f"代谢物矩阵不存在: {import_path}，跳过")
        return None

    print(f"读取代谢物矩阵: {metabolite_matrix_path}")
    df = pd.read_csv(import_path, index_col=0)
    print(f"  -> 样本数: {df.shape[0]}, 代谢物数: {df.shape[1]}")

    n_samples = df.shape[0]
    results = []

    for met in df.columns:
        values = df[met].values.astype(float)
        detection_rate = (values > 0).sum() / n_samples
        nonzero = values[values > 0]

        p5 = float(np.percentile(values, 5))
        p25 = float(np.percentile(values, 25))
        p50 = float(np.percentile(values, 50))
        p75 = float(np.percentile(values, 75))
        p95 = float(np.percentile(values, 95))
        nonzero_p50 = float(np.median(nonzero)) if len(nonzero) > 0 else 0.0

        results.append(
            {
                "metabolite": met,
                "p5": round(p5, 6),
                "p25": round(p25, 6),
                "p50": round(p50, 6),
                "p75": round(p75, 6),
                "p95": round(p95, 6),
                "nonzero_p50": round(nonzero_p50, 6),
                "detection_rate": round(detection_rate, 4),
                "n_detected": int((values > 0).sum()),
                "mean": round(float(np.mean(values)), 6),
                "max": round(float(np.max(values)), 6),
            }
        )

    ref_df = pd.DataFrame(results)
    mask = ref_df["detection_rate"] >= min_detection_rate
    ref_df = ref_df[mask].sort_values("p50", ascending=False)

    print(f"  -> 过滤后保留代谢物数: {len(ref_df)}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ref_df.to_csv(output_path, sep="\t", index=False)
    print(f"  -> 已保存: {output_path}")

    return output_path


def main():
    print("=" * 60)
    print("WGS.FMT 扩充参考数据库")
    print("=" * 60)

    # ── 物种参考范围 ──
    species_matrix = runtime_path("WGS_FMT_DATA_ROOT", "fmt") / "species_abundance_train.csv"
    species_output = REF_DIR / "species_p5_p95_extended.tsv"

    if not species_matrix.exists():
        print(f"\n错误: 物种矩阵不存在 {species_matrix}")
        print("请确认路径后再运行")
        sys.exit(1)

    print(f"\n[1/2] 生成物种参考范围...")
    build_species_reference(
        matrix_path=species_matrix,
        output_path=species_output,
        min_detection_rate=0.05,
        min_median_abundance=0.001,
    )

    # ── 代谢物参考范围 ──
    # 尝试查找代谢物矩阵
    # 常见位置: data/metabolite_matrix.csv, pipeline/output/metabolite_matrix.tsv
    candidate_paths = [
        runtime_path("WGS_DATA_DIR") / "metabolite_matrix.csv",
        WGS_FMT_ROOT / "pipeline" / "metabolite_matrix.tsv",
        WGS_FMT_ROOT / "data" / "metabolite_matrix.csv",
    ]

    met_output = REF_DIR / "metabolite_p5_p95.tsv"
    met_found = False

    print(f"\n[2/2] 生成代谢物参考范围...")
    for candidate in candidate_paths:
        if candidate.exists():
            build_metabolite_reference(
                metabolite_matrix_path=str(candidate),
                output_path=met_output,
                min_detection_rate=0.30,
            )
            met_found = True
            break

    if not met_found:
        print("\n[提示] 未找到代谢物矩阵，已跳过代谢物参考库生成。")
        print("  如需生成，请先运行 step_metabolite_matrix.py 生成代谢物矩阵，")
        print("  然后将文件路径传递给 build_metabolite_reference()")

    print(f"\n{'=' * 60}")
    print("完成！")
    print(f"  物种参考: {species_output}")
    if met_found:
        print(f"  代谢物参考: {met_output}")
    print("请将 report_data.py 中的引用从 species_p5_p95.tsv 切换到")
    print("  species_p5_p95_extended.tsv")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
