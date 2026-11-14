#!/usr/bin/env python3
"""建立代谢物描述性统计；不构建健康人群物种参考

输入:
  - 代谢物: 通过 step_metabolite_matrix 的输出矩阵（如已存在）
输出:
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
    if met_found:
        print(f"  代谢物参考: {met_output}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
