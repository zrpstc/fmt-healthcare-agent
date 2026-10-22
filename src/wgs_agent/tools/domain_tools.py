"""WGS.FMT 宏基因组分析领域工具 — 结构化输出版本

所有工具返回的 ToolResult.content 为 JSON 字符串 + 可读文本双格式：
  JSON_KEY ::= "---JSON---"
  content = readable_text + "\n" + JSON_KEY + "\n" + json.dumps(structured_data)
Web 端通过检测 JSON_KEY 分割来提取结构化数据渲染图表。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from wgs_agent.core.tools.base import BaseTool, ToolResult
from wgs_agent.tools.fmt_matching_tool import FmtMatchingTool
from wgs_agent.tools.pipeline_runner import PipelineCheckTool, PipelineRunStepTool

JSON_KEY = "---JSON---"


def _make_result(text: str, data: dict[str, Any]) -> ToolResult:
    """生成同时包含可读文本和结构化 JSON 的工具结果"""
    return ToolResult(content=f"{text}\n{JSON_KEY}\n{json.dumps(data, ensure_ascii=False, default=str)}")


# ============================================================================
# Pydantic 参数模型
# ============================================================================


class SampleIdParams(BaseModel):
    sample_id: str = Field(..., description="样本 ID")


class SpeciesCompareParams(BaseModel):
    sample_id: str = Field(..., description="样本 ID")
    species_name: str | None = Field(None, description="可选：仅分析指定物种")


class ReportGenerateParams(BaseModel):
    sample_id: str = Field(..., description="样本 ID")
    analysis_json_path: str = Field(..., description="分析结果 JSON")
    knowledge_json_path: str = Field("", description="知识库结果 JSON（可选）")


# ============================================================================
# 通用辅助函数
# ============================================================================


def _get_cn_name(raw_name: str) -> str:
    """获取物种中文名称"""
    try:
        from wgs_agent.pipeline.report_common import metaphlan_name_to_species

        return metaphlan_name_to_species(raw_name) or ""
    except Exception:
        return ""


def _load_and_compare(
    sample_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """加载物种数据并完成参考对比（避免每个工具重复调用）"""
    from wgs_agent.pipeline.report_data import (
        compare_species_with_reference,
        load_species_data,
    )

    sample, ref_p5p95, ref_stats = load_species_data(sample_id)
    comparison = compare_species_with_reference(sample, ref_p5p95, ref_stats)
    return comparison, ref_stats, ref_p5p95


def _build_species_list(comparison: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将原始对比数据转为完整的物种列表（含中文名 + 定量偏差）"""
    result = []
    for r in comparison:
        result.append(
            {
                "species": r["species"],
                "chinese_name": _get_cn_name(r["species"]),
                "abundance": round(r.get("abundance", 0), 4),
                "status": r.get("status", "unknown"),
                "status_cn": r.get("status_cn", "未知"),
                "p5": round(r.get("p5", 0), 4),
                "p95": round(r.get("p95", 0), 4),
                "deviation": round(r.get("deviation", 0), 2),
            }
        )
    return result


def _build_stats(species_list: list[dict[str, Any]]) -> dict[str, int]:
    """从物种列表中计算统计摘要"""
    return {
        "n_total": len(species_list),
        "n_normal": sum(1 for s in species_list if s["status"] == "normal"),
        "n_high": sum(1 for s in species_list if s["status"] == "high"),
        "n_low": sum(1 for s in species_list if s["status"] == "low"),
        "n_unknown": sum(1 for s in species_list if s["status"] == "unknown"),
    }


def _simple_enterotype_label(marker_ratios: dict[str, float]) -> str:
    """按标志菌属占比给样本分配简化肠型标签。"""
    bact = marker_ratios.get("Bacteroides_ratio", 0.0)
    prev = marker_ratios.get("Prevotella_ratio", 0.0)
    faec = marker_ratios.get("Faecalibacterium_ratio", 0.0)
    if bact > max(prev, faec) and bact > 10:
        return "ET_B"
    if prev > max(bact, faec) and prev > 5:
        return "ET_P"
    return "ET_R"


def _enterotype_ratios_from_genus_row(row: Any, genus_names: list[str]) -> dict[str, float]:
    """从属水平丰度行计算肠型判定使用的标志菌属占比。"""
    total = float(row.sum() or 0)
    if total <= 0:
        return {"Bacteroides_ratio": 0.0, "Prevotella_ratio": 0.0, "Faecalibacterium_ratio": 0.0}

    genus_map: dict[str, float] = {}
    for genus, value in zip(genus_names, row, strict=False):
        genus_map[genus] = genus_map.get(genus, 0.0) + float(value or 0)

    bact = genus_map.get("Bacteroides", 0.0) + genus_map.get("Phocaeicola", 0.0)
    prev = genus_map.get("Prevotella", 0.0) + genus_map.get("Segatella", 0.0)
    faec = genus_map.get("Faecalibacterium", 0.0)
    return {
        "Bacteroides_ratio": round(bact / total * 100, 2),
        "Prevotella_ratio": round(prev / total * 100, 2),
        "Faecalibacterium_ratio": round(faec / total * 100, 2),
    }


def _build_enterotype_tsne_plot(sample_id: str, output_dir: str | None = None) -> dict[str, Any]:
    """绘制属水平丰度 t-SNE 图，并高亮当前样本。依赖缺失时返回错误说明。"""
    try:
        import os

        import numpy as np
        import pandas as pd
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from sklearn.manifold import TSNE
        from sklearn.preprocessing import StandardScaler

        from wgs_agent.pipeline.report_common import METAPHLAN_GENUS_FILE, OUTPUT_DIR, metaphlan_name_to_genus
        from wgs_agent.pipeline.report_data import _best_col

        genus = pd.read_csv(METAPHLAN_GENUS_FILE, sep="\t", index_col=0)
        current_col = _best_col(genus, sample_id)
        if current_col is None:
            return {"error": f"样本 {sample_id} 不在属水平丰度矩阵中"}

        genus = genus.loc[genus.sum(axis=1) > 0]
        genus_names = [metaphlan_name_to_genus(str(idx)) or str(idx).split("|")[-1] for idx in genus.index]
        matrix = genus.T.fillna(0).astype(float)
        sample_ids = [str(idx) for idx in matrix.index]
        X = matrix.to_numpy(dtype=float)
        row_sum = X.sum(axis=1, keepdims=True)
        X_prob = X / np.where(row_sum == 0, 1, row_sum)

        variances = X_prob.var(axis=0)
        keep_count = min(80, max(2, X_prob.shape[1]))
        keep_idx = np.argsort(variances)[-keep_count:]
        X_use = X_prob[:, keep_idx]
        X_scaled = StandardScaler().fit_transform(X_use)
        n_samples = X_scaled.shape[0]
        if n_samples < 3:
            return {"error": "样本数量不足，至少需要 3 个样本才能绘制 t-SNE 肠型图"}
        perplexity = min(30, max(2, (n_samples - 1) // 3))
        coords = TSNE(
            n_components=2,
            perplexity=perplexity,
            init="pca",
            learning_rate="auto",
            random_state=42,
        ).fit_transform(X_scaled)

        labels = []
        for row in X:
            ratios = _enterotype_ratios_from_genus_row(row, genus_names)
            labels.append(_simple_enterotype_label(ratios))

        distribution = []
        total_n = len(labels)
        for label in ("ET_B", "ET_P", "ET_R"):
            count = labels.count(label)
            distribution.append({"label": label, "count": count, "percent": f"{count / max(total_n, 1) * 100:.1f}%"})

        current_idx = sample_ids.index(current_col)
        colors = {"ET_B": "#22c55e", "ET_P": "#f59e0b", "ET_R": "#8b5cf6"}
        names = {"ET_B": "Bacteroides", "ET_P": "Prevotella", "ET_R": "Ruminococcus"}

        fig, ax = plt.subplots(figsize=(8.8, 6.2), dpi=180)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("#f8fafc")
        for label in ("ET_B", "ET_P", "ET_R"):
            mask = np.array(labels) == label
            if mask.any():
                ax.scatter(
                    coords[mask, 0], coords[mask, 1],
                    s=42, c=colors[label], label=names[label], alpha=0.78,
                    edgecolors="white", linewidths=0.5,
                )

        ax.scatter(
            coords[current_idx, 0], coords[current_idx, 1],
            s=210, c="#ef4444", marker="*", label="Current sample",
            edgecolors="#111827", linewidths=1.0, zorder=5,
        )
        ax.annotate(
            current_col,
            xy=(coords[current_idx, 0], coords[current_idx, 1]),
            xytext=(8, 8), textcoords="offset points",
            fontsize=8, color="#111827",
            bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "#ef4444", "alpha": 0.88},
        )
        ax.set_xlabel("t-SNE 1")
        ax.set_ylabel("t-SNE 2")
        ax.set_title("Enterotype t-SNE clustering by genus abundance")
        ax.grid(True, alpha=0.22)
        ax.legend(frameon=True, fontsize=8)
        for spine in ax.spines.values():
            spine.set_color("#cbd5e1")

        figure_dir = output_dir or os.path.join(OUTPUT_DIR, "figures")
        os.makedirs(figure_dir, exist_ok=True)
        plot_path = os.path.join(figure_dir, f"{sample_id}_enterotype_tsne.png")
        fig.tight_layout()
        fig.savefig(plot_path, bbox_inches="tight")
        plt.close(fig)

        return {
            "cluster_plot_path": plot_path,
            "distribution": distribution,
            "plot_method": "t-SNE",
            "tsne_perplexity": perplexity,
            "current_sample_label": labels[current_idx],
            "n_cluster_samples": total_n,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _build_enterotype_pca_plot(sample_id: str, output_dir: str | None = None) -> dict[str, Any]:
    """兼容旧调用名，实际生成 t-SNE 肠型图。"""
    return _build_enterotype_tsne_plot(sample_id, output_dir=output_dir)


def _pipeline_gap_hint(error_msg: str, sample_id: str) -> str:
    """当样本不在矩阵中时，检测 Pipeline 缺口并返回友好提示"""
    try:
        from wgs_agent.tools.pipeline_runner import _detect_pipeline_gap, _readable_gap_report

        gap = _detect_pipeline_gap(sample_id)
        return _readable_gap_report(gap)
    except Exception:
        return (
            f"错误详情: {error_msg}\n"
            f"该样本可能未被 Pipeline 处理，请使用 pipeline_check 工具检测缺口。"
        )


# ============================================================================
# Tool 1: 加载物种丰度数据（结构化输出）
# ============================================================================


class LoadSpeciesDataTool(BaseTool):
    name = "load_species_data"
    description = "加载样本的 MetaPhlAn4 物种丰度数据，返回完整物种列表和统计摘要。"
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {"sample_id": {"type": "string", "description": "样本 ID"}},
        "required": ["sample_id"],
    }
    params_model = SampleIdParams

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        sid = str(params["sample_id"])
        try:
            comparison, _, _ = _load_and_compare(sid)
            species_list = _build_species_list(comparison)
            stats = _build_stats(species_list)

            # 可读摘要
            text = (
                f"样本 {sid}: 共检测 {stats['n_total']} 种物种\n"
                f"  正常: {stats['n_normal']} 种 | "
                f"偏高: {stats['n_high']} 种 | "
                f"偏低: {stats['n_low']} 种\n\n"
                f"Top 10 丰度物种:\n"
                + "\n".join(
                    f"  {s['species']} ({s['chinese_name']}) "
                    f": {s['abundance']:.4f}% [{s['status_cn']}]"
                    for s in species_list[:10]
                )
            )

            return _make_result(
                text,
                {
                    "sample_id": sid,
                    **stats,
                    "species_list": species_list,
                    "abnormal_species": [
                        s for s in species_list if s["status"] in ("high", "low")
                    ],
                },
            )

        except KeyError as ke:
            # 样本不在矩阵中 → 自动检测 Pipeline 缺口
            gap_info = _pipeline_gap_hint(str(ke), sid)
            return ToolResult(
                content=(
                    f"样本 {sid} 不在当前丰度矩阵中。\n\n"
                    f"### 建议操作\n"
                    f"1. 使用 `pipeline_check` 检测缺口 → 参数: sample_id=\"{sid}\"\n"
                    f"2. 使用 `pipeline_run_step` 触发执行 → 参数: sample_id=\"{sid}\", start_step=从缺口起点开始\n"
                    f"3. 完成后重新调用 `load_species_data`\n\n"
                    f"{gap_info}"
                ),
                is_error=False,
            )

        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            return ToolResult(
                content=(
                    f"物种数据加载失败 — 样本 {sid}\n"
                    f"错误类型: {type(exc).__name__}\n"
                    f"错误信息: {exc}\n\n"
                    f"### 诊断\n"
                    f"可能原因: 矩阵文件损坏、参考范围文件缺失、或数据格式异常\n"
                    f"详细堆栈:\n```\n{tb[-1200:]}\n```"
                ),
                is_error=True,
                error_type="runtime_error",
            )


# ============================================================================
# Tool 2: 物种-健康参考对比（结构化输出）
# ============================================================================


class CompareReferenceTool(BaseTool):
    name = "compare_reference"
    description = "将样本物种丰度与健康人群参考范围对比，返回所有异常物种及偏差值。"
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "sample_id": {"type": "string", "description": "样本 ID"},
            "species_name": {"type": "string", "description": "可选：仅查询特定物种"},
        },
        "required": ["sample_id"],
    }
    params_model = SpeciesCompareParams

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        try:
            sid = str(params["sample_id"])
            species_filter = params.get("species_name")

            comparison, _, _ = _load_and_compare(sid)
            species_list = _build_species_list(comparison)

            if species_filter:
                species_list = [
                    s
                    for s in species_list
                    if str(species_filter).lower() in s["species"].lower()
                ]
                if not species_list:
                    return ToolResult(content=f"未找到物种: {species_filter}", is_error=True)

            abnormal = [s for s in species_list if s["status"] in ("high", "low")]
            text = (
                f"样本 {sid} 异常物种 ({len(abnormal)}/{len(species_list)}):\n\n"
                + "\n".join(
                    f"  {s['species']} ({s['chinese_name']}) "
                    f": {s['abundance']:.4f}% [{s['status_cn']}], "
                    f"参考 P5-P95: {s['p5']:.4f}-{s['p95']:.4f}, "
                    f"偏差: {s['deviation']}"
                    for s in abnormal[:20]
                )
            )

            return _make_result(
                text,
                {
                    "sample_id": sid,
                    "abnormal_species": abnormal,
                    "total_species": len(species_list),
                    "n_abnormal": len(abnormal),
                },
            )

        except Exception as exc:
            return ToolResult(content=f"物种对比失败: {exc}", is_error=True, error_type="runtime_error")


# ============================================================================
# Tool 3: 肠型分析（结构化输出）
# ============================================================================


class EnterotypeAnalyzerTool(BaseTool):
    name = "analyze_enterotype"
    description = "分析样本的肠型，返回肠型、置信度和驱动物种。"
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {"sample_id": {"type": "string", "description": "样本 ID"}},
        "required": ["sample_id"],
    }
    params_model = SampleIdParams

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        try:
            from wgs_agent.pipeline.report_data import determine_enterotype

            sid = str(params["sample_id"])
            ent = determine_enterotype(sid)
            ent_type = ent.get("type", "未知")
            confidence = float(ent.get("confidence", 0))
            pca_result = _build_enterotype_tsne_plot(sid)

            basis_lines = [
                f"  Bacteroides/Phocaeicola: {ent.get('Bacteroides_ratio', 0):.2f}%",
                f"  Prevotella/Segatella: {ent.get('Prevotella_ratio', 0):.2f}%",
                f"  Faecalibacterium: {ent.get('Faecalibacterium_ratio', 0):.2f}%",
            ]
            top_genus = ent.get("top_genus") or []
            if top_genus:
                basis_lines.append("  丰度靠前菌属: " + ", ".join(f"{g}={v:.4f}%" for g, v in top_genus[:5]))

            plot_line = ""
            if pca_result.get("cluster_plot_path"):
                plot_line = f"\n  t-SNE聚类图: {pca_result['cluster_plot_path']}"
            elif pca_result.get("error"):
                plot_line = f"\n  t-SNE聚类图生成失败: {pca_result['error']}"

            text = (
                f"样本 {sid} 肠型分析:\n"
                f"  肠型: {ent_type}\n"
                f"  置信度: {confidence:.1f}%\n"
                f"分类依据:\n" + "\n".join(basis_lines) + plot_line
            )

            result_data = {
                "sample_id": sid,
                "enterotype": ent_type,
                "confidence": confidence,
                "classification_basis": ent,
                "details": ent,
            }
            result_data.update({k: v for k, v in pca_result.items() if k != "error"})
            if pca_result.get("error"):
                result_data["plot_error"] = pca_result["error"]

            return _make_result(
                text,
                result_data,
            )

        except Exception as exc:
            return ToolResult(content=f"肠型分析失败: {exc}", is_error=True, error_type="runtime_error")


# ============================================================================
# Tool 4: 代谢通路分析（结构化输出）
# ============================================================================


class PathwayAnalyzerTool(BaseTool):
    name = "analyze_pathways"
    description = "分析样本的代谢通路丰度，返回所有通路数据。"
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {"sample_id": {"type": "string", "description": "样本 ID"}},
        "required": ["sample_id"],
    }
    params_model = SampleIdParams

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        try:
            from wgs_agent.pipeline.report_data import load_pathway_data
            from wgs_agent.pipeline.report_common import format_pathway_name

            sid = str(params["sample_id"])
            pathway_data, _ = load_pathway_data(sid)

            if pathway_data is None or len(pathway_data) == 0:
                return ToolResult(content=f"样本 {sid} 无代谢通路数据")

            top20 = pathway_data.head(20)
            path_list = [
                {"name": format_pathway_name(str(pw)), "abundance": round(float(ab), 4)}
                for pw, ab in top20.items()
            ]

            text = (
                f"样本 {sid} Top 20 代谢通路:\n"
                + "\n".join(f"  {p['name']}: {p['abundance']:.4f}" for p in path_list[:10])
                + f"\n  ... 共 {len(pathway_data)} 条通路"
            )

            return _make_result(
                text,
                {
                    "sample_id": sid,
                    "pathways": path_list,
                    "n_total_pathways": len(pathway_data),
                },
            )

        except Exception as exc:
            return ToolResult(content=f"代谢通路分析失败: {exc}", is_error=True, error_type="runtime_error")


# ============================================================================
# Tool 5: 代谢物含量分析（结构化输出）
# ============================================================================


class MetaboliteAnalyzerTool(BaseTool):
    name = "analyze_metabolites"
    description = "分析样本的代谢物含量，返回所有代谢物数据。"
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {"sample_id": {"type": "string", "description": "样本 ID"}},
        "required": ["sample_id"],
    }
    params_model = SampleIdParams

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        try:
            from wgs_agent.pipeline.report_data import load_metabolite_data

            sid = str(params["sample_id"])
            met_values, _, _ = load_metabolite_data(sid)

            if met_values is None or len(met_values) == 0:
                return _make_result(
                    f"样本 {sid} 尚无可量化代谢物数据。HUMAnN 通路只能表示代谢潜能，"
                    "不能替代粪便代谢组实测浓度。",
                    {
                        "sample_id": sid,
                        "status": "not_quantified",
                        "analysis_type": "functional_potential_only",
                        "metabolites": [],
                        "n_total_metabolites": 0,
                        "message": (
                            "当前仅可结合物种、HUMAnN 通路和文献 Claim 给出代谢潜能；"
                            "定量结果需要 LC-MS/GC-MS，或经验证的 AGORA/MICOM 模型。"
                        ),
                    },
                )

            top20 = met_values.head(20)
            met_list = [
                {"name": str(m), "abundance": round(float(v), 4)}
                for m, v in top20.items()
            ]

            text = (
                f"样本 {sid} Top 20 代谢物:\n"
                + "\n".join(f"  {m['name']}: {m['abundance']:.4f} CPM" for m in met_list[:10])
                + f"\n  ... 共 {len(met_values)} 种代谢物"
            )

            return _make_result(
                text,
                {
                    "sample_id": sid,
                    "status": "model_inferred",
                    "analysis_type": "microbiome_model_inference_not_direct_measurement",
                    "metabolites": met_list,
                    "n_total_metabolites": len(met_values),
                },
            )

        except Exception as exc:
            return ToolResult(content=f"代谢物分析失败: {exc}", is_error=True, error_type="runtime_error")


# ============================================================================
# Tool 6: 药物-微生物组交互分析（结构化输出）
# ============================================================================


class DrugAnalyzerTool(BaseTool):
    name = "analyze_drugs"
    description = "分析药物-微生物组交互风险，返回所有药物详情。"
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {"sample_id": {"type": "string", "description": "样本 ID"}},
        "required": ["sample_id"],
    }
    params_model = SampleIdParams

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        try:
            from wgs_agent.pipeline.report_data import load_drug_data

            sid = str(params["sample_id"])
            drug_df = load_drug_data(sid)

            if drug_df is None or len(drug_df) == 0:
                return ToolResult(content=f"样本 {sid} 无药物交互数据")

            df = drug_df.sort_values("combined_score", ascending=False)
            high_risk_df = df[df["combined_score"] > 50000]

            drug_list = []
            for _, row in df.head(30).iterrows():
                drug_list.append(
                    {
                        "drug": str(row.get("drug", "")),
                        "score": round(float(row.get("combined_score", 0)), 1),
                        "is_high_risk": float(row.get("combined_score", 0)) > 50000,
                    }
                )

            high_risk_list = [d for d in drug_list if d["is_high_risk"]]

            text = (
                f"样本 {sid} 药物交互分析:\n"
                f"  总药物数: {len(drug_df)}\n"
                f"  高风险药物数 (score>50000): {len(high_risk_df)}\n\n"
                + ("高风险药物 Top 5:\n"
                   + "\n".join(f"  [高风险] {d['drug']}: score={d['score']:.1f}" for d in high_risk_list[:5])
                   if high_risk_list
                   else "未发现高风险药物")
            )

            return _make_result(
                text,
                {
                    "sample_id": sid,
                    "drugs": drug_list,
                    "high_risk_drugs": high_risk_list,
                    "n_total": len(drug_df),
                    "n_high_risk": len(high_risk_df),
                },
            )

        except Exception as exc:
            return ToolResult(content=f"药物分析失败: {exc}", is_error=True, error_type="runtime_error")


# ============================================================================
# Tool 7: 物种-疾病关联分析（结构化输出）
# ============================================================================


class DiseaseAnalyzerTool(BaseTool):
    name = "analyze_diseases"
    description = "分析物种-疾病关联风险，返回所有疾病详情（含关键物种、一致性统计）。"
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {"sample_id": {"type": "string", "description": "样本 ID"}},
        "required": ["sample_id"],
    }
    params_model = SampleIdParams

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        try:
            from wgs_agent.pipeline.report_data import (
                compare_species_with_reference,
                load_species_data,
            )
            from wgs_agent.pipeline.report_disease_species import get_disease_analysis

            sid = str(params["sample_id"])
            sample, ref_p5p95, ref_stats = load_species_data(sid)
            comparison = compare_species_with_reference(sample, ref_p5p95, ref_stats)
            disease_results = get_disease_analysis(comparison)

            if not disease_results:
                return ToolResult(content=f"样本 {sid} 未匹配到已知疾病关联")

            diseases = []
            for d in disease_results:
                key_sp = [
                    {
                        "species": s["species"],
                        "direction": s["direction"],
                        "status": s["status"],
                        "role": s.get("role", ""),
                        "evidence": s.get("evidence", ""),
                        "evidence_source": "curated_association_library",
                    }
                    for s in d.get("details", [])[:5]
                ]
                diseases.append(
                    {
                        "disease": d["disease"],
                        "risk_score": float(d["risk_score"]),
                        "matched_species": int(d.get("matched_species", 0)),
                        "association_score": float(d["risk_score"]),
                        "score_type": "microbiome_association_not_disease_probability",
                        "agree_count": int(d.get("agree_count", 0)),
                        "conflict_count": int(d.get("conflict_count", 0)),
                        "key_species": key_sp,
                        "details": d.get("details", []),
                        "risk_level": (
                            "high"
                            if d["risk_score"] >= 75
                            else "medium"
                            if d["risk_score"] >= 25
                            else "low"
                        ),
                    }
                )

            high_risk = [d for d in diseases if d["risk_level"] == "high"]
            mid_risk = [d for d in diseases if d["risk_level"] == "medium"]

            text = (
                f"样本 {sid} 疾病关联证据分析（评分不是患病概率）:\n"
                f"  总匹配疾病数: {len(diseases)}\n"
                f"  高风险 (≥75): {len(high_risk)} 项\n"
                f"  中风险 (25-74): {len(mid_risk)} 项\n\n"
                + ("高风险疾病:\n" + "\n".join(
                    f"  [高风险] {d['disease']}: 评分={d['risk_score']}/100, "
                    f"匹配 {d['matched_species']} 种, 一致 {d['agree_count']} 种"
                    for d in high_risk[:5]
                ) if high_risk else "")
                + ("\n中风险疾病:\n" + "\n".join(
                    f"  [中风险] {d['disease']}: 评分={d['risk_score']}/100"
                    for d in mid_risk[:5]
                ) if mid_risk else "")
            )

            return _make_result(
                text,
                {
                    "sample_id": sid,
                    "status": "association_only",
                    "score_type": "microbiome_association_not_disease_probability",
                    "methodology": (
                        "依据异常物种与文献报道方向的一致性计算关联分数；"
                        "建议再按物种×疾病检索 LitKG Claim/PubMed，并按独立文档数、"
                        "研究设计和方向一致性给出单独的证据等级。"
                    ),
                    "disclaimer": "该分数不包含宿主症状、检验和病史，不能用于诊断或预测患病概率。",
                    "diseases": diseases,
                    "n_total": len(diseases),
                    "n_high_risk": len(high_risk),
                    "n_mid_risk": len(mid_risk),
                },
            )

        except Exception as exc:
            return ToolResult(content=f"疾病关联分析失败: {exc}", is_error=True, error_type="runtime_error")


# ============================================================================
# Tool 8: 报告生成（含知识片段自动注入）
# ============================================================================


class ReportGeneratorTool(BaseTool):
    name = "generate_report"
    description = "生成 WGS.FMT 完整健康评估报告（Markdown + PDF）。"
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "sample_id": {"type": "string", "description": "样本 ID"},
            "analysis_json_path": {"type": "string", "description": "分析结果 JSON"},
            "knowledge_json_path": {"type": "string", "description": "知识库结果 JSON（可选）"},
        },
        "required": ["sample_id", "analysis_json_path"],
    }
    params_model = ReportGenerateParams

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        try:
            import os
            import json as _json

            sid = str(params["sample_id"])
            analysis_path = str(params["analysis_json_path"])
            knowledge_path = str(params.get("knowledge_json_path", ""))

            if not os.path.exists(analysis_path):
                return ToolResult(content=f"分析结果文件不存在: {analysis_path}", is_error=True)

            with open(analysis_path, "r", encoding="utf-8") as f:
                data = _json.load(f)

            # 从嵌套 JSON 中提取各模块数据
            species = data.get("species", {}) if isinstance(data.get("species"), dict) else {}
            compare = data.get("compare", {}) if isinstance(data.get("compare"), dict) else {}
            enterotype = data.get("enterotype", {}) if isinstance(data.get("enterotype"), dict) else {}
            pathways = data.get("pathways", {}) if isinstance(data.get("pathways"), dict) else {}
            metabolites = data.get("metabolites", {}) if isinstance(data.get("metabolites"), dict) else {}
            drugs = data.get("drugs", {}) if isinstance(data.get("drugs"), dict) else {}
            diseases = data.get("diseases", {}) if isinstance(data.get("diseases"), dict) else {}
            fmt_matching = data.get("fmt_matching", {}) if isinstance(data.get("fmt_matching"), dict) else {}
            knowledge = data.get("knowledge", {}) if isinstance(data.get("knowledge"), dict) else {}
            if knowledge_path and os.path.exists(knowledge_path):
                with open(knowledge_path, "r", encoding="utf-8") as f:
                    knowledge = _json.load(f)

            output_dir = os.path.dirname(analysis_path)
            figure_dir = os.path.join(output_dir, "figures")
            os.makedirs(figure_dir, exist_ok=True)

            # 报告链路自身补齐肠型 t-SNE 图。不能依赖 analyze_enterotype 工具被单独调用。
            cluster_source = enterotype.get("cluster_plot_path") or enterotype.get("cluster_plot")
            if not cluster_source or not os.path.isfile(cluster_source):
                pca_result = _build_enterotype_tsne_plot(sid, output_dir=figure_dir)
                if pca_result.get("cluster_plot_path"):
                    enterotype.update({k: v for k, v in pca_result.items() if k != "error"})
                elif pca_result.get("error"):
                    enterotype["plot_error"] = pca_result["error"]

            # 报告链路自身补齐 FMT 配型。若已有 analysis JSON 中的结果，则直接复用。
            # Older analyses may contain an unavailable/degraded placeholder from
            # the retired ZipPCA/Harmony service. Re-run those records with the
            # in-project triplet model when a report is regenerated.
            if not fmt_matching or fmt_matching.get("status") != "ok" or not fmt_matching.get("model_name") or any(str(m.get("donor_id")) == sid for m in fmt_matching.get("top_k_matches", [])):
                try:
                    from wgs_agent.pipeline.report_common import METAPHLAN_GENUS_FILE
                    from wgs_agent.pipeline.report_fmt_matching import run_fmt_pipeline

                    fmt_matching = run_fmt_pipeline(
                        sample_id=sid,
                        genus_file=METAPHLAN_GENUS_FILE,
                        output_dir=figure_dir,
                        top_k=10,
                        device_str="cpu",
                    )
                except Exception as fmt_exc:
                    fmt_matching = {
                        "status": "unavailable",
                        "message": f"FMT 配型生成失败: {str(fmt_exc)[:200]}",
                        "top_k_matches": [],
                        "tsne_plot_path": None,
                    }

            # Keep cached images inside the report artifact tree for PDF and web delivery.
            import shutil
            for record, keys, suffix in (
                (enterotype, ("cluster_plot_path", "cluster_plot"), "enterotype"),
                (fmt_matching, ("tsne_plot_path", "plot_path"), "matching_projection"),
            ):
                source = next((record.get(k) for k in keys if record.get(k) and os.path.isfile(record[k])), None)
                if source:
                    target = os.path.join(figure_dir, f"{sid}_{suffix}.png")
                    if os.path.realpath(source) != os.path.realpath(target):
                        shutil.copy2(source, target)
                    record[keys[0]] = target
                else:
                    for key in keys:
                        record.pop(key, None)

            from wgs_agent.pipeline.report_fmt_matching import enrich_matching_report
            fmt_matching = enrich_matching_report(sid, fmt_matching)

            # Build the evidence manifest before asking the model for interpretation.
            import hashlib
            from wgs_agent.tools.detailed_report import (
                collect_evidence, generate_figures, build_reasoning_prompt,
                validate_reasoning, load_gene_family_evidence, resolve_report_model, VERSION,
            )
            from wgs_agent.tools.report_maker import build_full_report, _generate_fpdf_report
            proteins = data.get("proteins") or data.get("protein") or data.get("gene_families") or {}
            if not isinstance(proteins, dict):
                proteins = {}
            if not proteins:
                proteins = load_gene_family_evidence(sid)
            context = dict(data.get("metadata") or {})
            context.update({
                "analysis_sha256": hashlib.sha256(open(analysis_path, "rb").read()).hexdigest(),
                "knowledge_sha256": hashlib.sha256(_json.dumps(knowledge, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                "report_version": VERSION,
            })
            evidence = collect_evidence(species, compare, pathways, metabolites, proteins, diseases, fmt_matching, knowledge)
            try:
                context["figures"] = generate_figures(figure_dir, sid, evidence)
            except Exception as figure_exc:
                context["figures"] = {}
                context["figure_error"] = str(figure_exc)[:200]
            llm_advice = ""
            model_config = resolve_report_model()
            context["llm_status"] = "not_configured"
            if model_config:
                try:
                    import requests
                    api_base = model_config["base_url"]
                    model = model_config["model"]
                    api_key = model_config["api_key"]
                    resp = requests.post(
                        f"{api_base.rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"model": model, "messages": [
                            {"role": "system", "content": "你是受证据约束的科研报告解释助手。只输出有引用依据的解释摘要JSON，不作诊断和治疗建议。"},
                            {"role": "user", "content": build_reasoning_prompt(evidence)},
                        ], "temperature": 0.1, "max_tokens": 4800, "stream": False,
                        **({"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}} if model.startswith("deepseek") else {})},
                        timeout=60,
                    )
                    resp.raise_for_status()
                    choice = resp.json()["choices"][0]
                    llm_advice = choice["message"].get("content") or ""
                    context["llm_finish_reason"] = choice.get("finish_reason")
                    context["llm_status"] = "generated" if llm_advice else "empty_response"
                    if choice.get("finish_reason") == "length":
                        llm_advice = ""
                        context["llm_status"] = "truncated"
                    context["llm_model"] = model
                except Exception as llm_exc:
                    context["llm_status"] = "unavailable"
                    context["llm_error_type"] = type(llm_exc).__name__
            context["llm_candidate_text"] = llm_advice
            context["reasoning_check"] = validate_reasoning(llm_advice, evidence)
            evidence_path = os.path.join(output_dir, f"{sid}_report_evidence.json")
            with open(evidence_path + ".tmp", "w", encoding="utf-8") as handle:
                _json.dump({"sample_id": sid, "context": context, "evidence": evidence, "fmt_matching": fmt_matching}, handle, ensure_ascii=False, indent=2, default=str)
            os.replace(evidence_path + ".tmp", evidence_path)
            detailed_markdown = build_full_report(
                sample_id=sid, species_data=species, compare_data=compare,
                enterotype_data=enterotype, pathway_data=pathways,
                metabolite_data=metabolites, drug_data=drugs,
                disease_data=diseases, knowledge_data=knowledge,
                llm_advice=llm_advice, fmt_matching_data=fmt_matching,
                protein_data=proteins, report_context=context,
            )
            from wgs_agent.tools.report_layers import build_report_layers
            layers = build_report_layers(
                sample_id=sid,
                full_report=detailed_markdown,
                evidence=evidence,
                species_data=species,
                enterotype_data=enterotype,
                pathway_data=pathways,
                disease_data=diseases,
                matching_data=fmt_matching,
                context=context,
            )
            markdown = layers["main_markdown"]
            technical_markdown = layers["technical_markdown"]
            interactive_payload = layers["interactive"]
            # The historical health_report names remain the user-facing layer so
            # existing URLs keep working. The complete report is now a separate
            # technical appendix and the browser receives a stable JSON view model.
            markdown_path = os.path.join(output_dir, f"{sid}_health_report.md")
            markdown_tmp = f"{markdown_path}.tmp"
            with open(markdown_tmp, "w", encoding="utf-8") as markdown_file:
                markdown_file.write(markdown)
            os.replace(markdown_tmp, markdown_path)

            technical_path = os.path.join(output_dir, f"{sid}_technical_appendix.md")
            with open(technical_path + ".tmp", "w", encoding="utf-8") as technical_file:
                technical_file.write(technical_markdown)
            os.replace(technical_path + ".tmp", technical_path)

            interactive_path = os.path.join(output_dir, f"{sid}_interactive_report.json")
            with open(interactive_path + ".tmp", "w", encoding="utf-8") as interactive_file:
                _json.dump(interactive_payload, interactive_file, ensure_ascii=False, indent=2, default=str)
            os.replace(interactive_path + ".tmp", interactive_path)

            # PDF consumes exactly the same Markdown, including evidence and figures.
            pdf_path = os.path.join(output_dir, f"{sid}_health_report.pdf")
            renderer_used = "evidence_markdown_fpdf"
            pdf_error = ""
            try:
                _generate_fpdf_report(markdown, sid, pdf_path)
            except Exception as pdf_exc:
                pdf_error = str(pdf_exc)
                renderer_used = "markdown_only"
                pdf_path = ""

            result = {
                "markdown": markdown,
                "markdown_path": markdown_path,
                "technical_appendix_path": technical_path,
                "interactive_report_path": interactive_path,
                "pdf_path": pdf_path,
                "sample_id": sid,
                "renderer_used": renderer_used,
                "template_path": "evidence-report-v2",
                "evidence_path": evidence_path,
                "figure_paths": context.get("figures", {}),
                "llm_status": context.get("llm_status"),
                "pdf_error": pdf_error,
                "enterotype_cluster_plot": enterotype.get("cluster_plot_path") or enterotype.get("cluster_plot"),
                "fmt_tsne_plot": fmt_matching.get("tsne_plot_path") if isinstance(fmt_matching, dict) else None,
                "fmt_status": fmt_matching.get("status") if isinstance(fmt_matching, dict) else None,
            }
            return _make_result(
                f"报告已生成: {pdf_path}\n"
                f"PDF 渲染链路: {renderer_used}\n"
                f"报告版本: {VERSION}\n"
                f"(Markdown 内容见下方 JSON)",
                result,
            )

        except Exception as exc:
            import traceback
            return ToolResult(
                content=f"报告生成失败: {exc}\n{traceback.format_exc()}",
                is_error=True,
                error_type="runtime_error",
            )


def _build_advice_prompt(
    sid: str,
    species: dict[str, Any],
    enterotype: dict[str, Any],
    drugs: dict[str, Any],
    diseases: dict[str, Any],
    knowledge: dict[str, Any],
) -> str:
    """生成短 prompt：只让 LLM 输出综合建议段落"""
    n_total = species.get("n_total", 0)
    n_high = species.get("n_high", 0)
    n_low = species.get("n_low", 0)
    ent_type = enterotype.get("enterotype", "未知")
    high_drugs = drugs.get("high_risk_drugs", [])
    diseases_list = diseases.get("diseases", [])[:3]
    disease_names = ", ".join(d.get("disease", "?") for d in diseases_list)

    return f"""你是一位肠道微生物组临床分析专家。请基于以下数据摘要撰写一段 200-300 字的综合健康建议，包含：关键发现、风险提示、膳食/益生菌建议、随访建议。

样本: {sid}
物种: {n_total} 种（偏高 {n_high}，偏低 {n_low}）
肠型: {ent_type}
高风险药物: {len(high_drugs)} 种
Top 疾病关联: {disease_names}

要求：不要编号列表，连贯段落，专业但易懂。"""


# ============================================================================
# Prompt 与 Markdown 构建（增强版）
# ============================================================================


def _build_report_prompt(
    sample_id: str,
    analysis: dict[str, Any],
    knowledge: dict[str, Any],
) -> str:
    # 兼容嵌套格式 (species.*) 和扁平格式 (*)
    def _get(key: str, default: Any = None) -> Any:
        if key in analysis:
            return analysis[key]
        for sub_key in ("species", "compare"):
            sub = analysis.get(sub_key, {})
            if isinstance(sub, dict) and key in sub:
                return sub[key]
        return default

    n_species = _get("n_total", _get("n_species", 0))
    n_high = _get("n_high", 0)
    n_low = _get("n_low", 0)
    n_normal = _get("n_normal", 0)
    enterotype = _get("enterotype", {})
    if isinstance(enterotype, dict):
        ent_type = enterotype.get("type", enterotype.get("enterotype", "未知"))
        ent_conf = enterotype.get("confidence", 0)
    else:
        ent_type = str(enterotype)
        ent_conf = 0

    abnormal_raw = _get("abnormal_species", [])
    if isinstance(abnormal_raw, list):
        abnormal = abnormal_raw[:8]
    else:
        abnormal = []
    abnormal_lines = [
        f"  - {s.get('species', '?')} ({s.get('chinese_name', '')})"
        f": {s.get('abundance', 0):.4f}% [{s.get('status_cn', '?')}]"
        f", 偏差 {s.get('deviation', 0):+.2f}"
        for s in abnormal
    ]

    diseases_raw = _get("diseases", _get("disease_results", []))
    if isinstance(diseases_raw, list):
        diseases = diseases_raw[:8]
    else:
        diseases = []
    disease_lines = []
    for d in diseases:
        score = d.get("risk_score", 0)
        key_sp = [s.get("species", "") for s in d.get("key_species", [])[:3]]
        disease_lines.append(
            f"  - {d.get('disease', '?')} (评分 {score}/100)"
            + (f", 关键菌: {', '.join(key_sp)}" if key_sp else "")
        )

    drugs_raw = _get("high_risk_drugs") or _get("drugs", [])
    if isinstance(drugs_raw, list):
        drugs = drugs_raw[:5]
    else:
        drugs = []
    drug_lines = [f"  - {d.get('drug', '?')} (score {d.get('score', 0):.0f})" for d in drugs]

    metabolites_raw = _get("metabolites", [])
    if isinstance(metabolites_raw, list):
        metabolites = metabolites_raw[:5]
    else:
        metabolites = []
    met_lines = [f"  - {m.get('name', '?')}: {m.get('abundance', 0):.2f} CPM" for m in metabolites]

    knowledge_text = ""
    pubmed_results = knowledge.get("pubmed_results", [])
    local_docs = knowledge.get("matched_docs", [])
    all_snippets = []

    for p in pubmed_results[:3]:
        all_snippets.append(
            f"[PMID:{p.get('pmid', '')}] {p.get('title', '')}\n"
            f"{p.get('abstract', '')[:400]}"
        )
    for d in local_docs[:3]:
        if d.get("claim_id"):
            all_snippets.append(
                f"[{d.get('claim_id')}] {d.get('subject', '')} "
                f"--{d.get('predicate', '')}--> {d.get('object', '')}\n"
                f"证据原句: {d.get('evidence_text', '')[:500]}\n"
                f"来源: {d.get('filename', '')}; document:{d.get('document_id', '')}"
            )
        else:
            all_snippets.append(
                f"[{d.get('title', '')}] {d.get('snippet', '')[:400]}"
            )

    if all_snippets:
        knowledge_text = "\n\n".join(all_snippets)

    return f"""你是一位**顶级肠道微生态临床研究专家**，请基于以下多组学数据生成专业健康评估报告。

## 检测数据
样本: {sample_id}
物种总数: {n_species} (偏高 {n_high} 种, 偏低 {n_low} 种)
肠型: {ent_type} (置信度 {ent_conf:.1f}%)

异常物种:
{chr(10).join(abnormal_lines) if abnormal_lines else '  无显著异常'}

疾病关联风险:
{chr(10).join(disease_lines) if disease_lines else '  无显著关联'}

高风险药物:
{chr(10).join(drug_lines) if drug_lines else '  未发现高风险药物交互'}

代谢物含量 Top 5:
{chr(10).join(met_lines) if met_lines else '  无可用的代谢物数据'}

## 参考文献证据
{knowledge_text if knowledge_text else '（请基于检测数据本身给出建议）'}

## 撰写要求
1. **关键发现** — 指出最值得关注的 2-3 个异常指标，包含定量数据
2. **健康风险分析** — 基于疾病关联数据和文献证据分析潜在风险，引用文献标注 [PMID]
3. **精准干预建议** — 针对异常菌群给出科学的膳食/益生菌/益生元建议
4. **临床随访建议** — 是否需要进一步检查、复查时间等
5. **不确定性声明** — 说明数据局限性，如参考范围适用人群、文献证据强度

要求:
- 语言专业但不晦涩，可供临床医生和患者阅读
- 物种使用中文名称
- 引用文献时标注 [PMID: xxx] 或 [来源]
- 控制在 500-800 字"""


def _build_markdown(
    sample_id: str,
    analysis: dict[str, Any],
    knowledge: dict[str, Any],
    advice_text: str,
) -> str:
    from datetime import datetime as _dt

    n_species = analysis.get("n_total", analysis.get("n_species", 0))
    n_high = analysis.get("n_high", 0)
    n_low = analysis.get("n_low", 0)
    n_normal = analysis.get("n_normal", 0)

    lines = [
        f"# WGS.FMT 肠道菌群健康评估报告\n",
        f"**样本编号**: {sample_id}",
        f"**报告日期**: {_dt.now().strftime('%Y-%m-%d %H:%M')}\n",
        "---\n",
        "## 综合健康评估\n",
        advice_text,
        "\n## 物种统计\n",
        f"- 检测物种: {n_species} 种",
        f"- 正常范围: {n_normal} 种",
        f"- 偏高: {n_high} 种",
        f"- 偏低: {n_low} 种\n",
    ]

    refs = []
    for p in knowledge.get("pubmed_results", [])[:5]:
        refs.append(f"- [{p.get('year', '')}] {p.get('title', '')}. {p.get('journal', '')}. PMID: {p.get('pmid', '')}")
    for claim in knowledge.get("matched_docs", [])[:8]:
        if isinstance(claim, dict) and claim.get("claim_id"):
            refs.append(
                f"- [{claim['claim_id']}] {claim.get('subject', '')} "
                f"—{claim.get('predicate', '')}→ {claim.get('object', '')}. "
                f"来源: {claim.get('filename') or claim.get('source_id', '')}; "
                f"document:{claim.get('document_id', '')}"
            )
    if refs:
        lines.append("## 参考文献\n")
        lines.extend(refs)
        lines.append("")

    lines.append("---\n")
    lines.append("*本报告基于高通量宏基因组学分析，参考范围为健康人群大型队列数据。仅供科研与健康管理参考。*\n")
    return "\n".join(lines)


# ============================================================================
# 工具注册清单
# ============================================================================

DOMAIN_TOOLS: list[type[BaseTool]] = [
    LoadSpeciesDataTool,
    CompareReferenceTool,
    EnterotypeAnalyzerTool,
    PathwayAnalyzerTool,
    MetaboliteAnalyzerTool,
    DrugAnalyzerTool,
    DiseaseAnalyzerTool,
    FmtMatchingTool,
    PipelineCheckTool,
    PipelineRunStepTool,
    ReportGeneratorTool,
]

DOMAIN_TOOL_POLICIES: dict[str, dict[str, object]] = {
    "load_species_data": {"default": "allow", "reason": "只读"},
    "compare_reference": {"default": "allow", "reason": "只读"},
    "analyze_enterotype": {"default": "allow", "reason": "只读"},
    "analyze_pathways": {"default": "allow", "reason": "只读"},
    "analyze_metabolites": {"default": "allow", "reason": "只读"},
    "analyze_drugs": {"default": "ask", "reason": "药物分析结果可能影响临床决策"},
    "analyze_diseases": {"default": "ask", "reason": "疾病风险分析结果敏感"},
    "fmt_matching": {"default": "ask", "reason": "FMT 配型可能需要训练模型，耗时较长"},
    "pipeline_check": {"default": "allow", "reason": "只读文件系统检查"},
    "pipeline_run_step": {"default": "ask", "reason": "执行耗时计算任务，可能需数小时"},
    "generate_report": {"default": "ask", "reason": "LLM 报告生成消耗 API tokens"},
}
