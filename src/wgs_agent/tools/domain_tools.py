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
                "unit": "%",
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
            from wgs_agent.reporting.inputs import load_existing_report_inputs
            profile_inputs = load_existing_report_inputs(sid)

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
                    "unit": "%",
                    # Named-species comparison may exclude uncharacterized SGBs;
                    # diversity is computed from the complete original profile.
                    "is_complete_profile": False,
                    "taxonomy": profile_inputs.get("taxonomy", {}),
                    "diversity": profile_inputs.get("diversity", {}),
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

            from wgs_agent.reporting.inputs import load_existing_report_inputs
            from html import unescape

            complete = load_existing_report_inputs(sid).get("pathways")
            path_list = [
                {"id": str(pw).split(":", 1)[0], "name": unescape(format_pathway_name(str(pw))),
                 "abundance": float(ab), "data_type": "functional_potential"}
                for pw, ab in pathway_data.items()
                if str(pw).split("|")[0] not in {"UNMAPPED", "UNINTEGRATED"}
                and "|" not in str(pw)
            ]
            if complete:
                path_list = complete["pathways"]

            text = (
                f"样本 {sid} 代谢通路摘要（完整明细保存在结构化结果）:\n"
                + "\n".join(f"  {p['name']}: {p['abundance']:.4f}" for p in path_list[:10])
                + f"\n  ... 共 {len(pathway_data)} 条通路"
            )

            return _make_result(
                text,
                {
                    "sample_id": sid,
                    "pathways": path_list,
                    "n_total_pathways": len(path_list),
                    "is_complete": True,
                    "data_type": "functional_potential",
                    **({k: v for k, v in complete.items() if k != "pathways"} if complete else {}),
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

            met_list = [
                {"name": str(m), "abundance": float(v), "data_type": "model_inferred"}
                for m, v in met_values.items()
            ]

            text = (
                f"样本 {sid} 代谢物模型推算摘要（非实测，单位需核对）:\n"
                + "\n".join(f"  {m['name']}: {m['abundance']:.4g}" for m in met_list[:10])
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
                    "is_complete": True,
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
        import fcntl
        import hashlib
        import os
        import re
        import tempfile
        import uuid
        from pathlib import Path

        from wgs_agent.reporting.catalog import VERSION
        from wgs_agent.reporting.document import build_document
        from wgs_agent.reporting.inputs import load_existing_report_inputs
        from wgs_agent.reporting.reference import refresh_reference_comparisons
        from wgs_agent.reporting.narrative import generate_narrative
        from wgs_agent.reporting.graph_labels import resolve_graph_model, translate_graph_labels
        from wgs_agent.reporting.knowledge_graph import enrich_document, attach_subgraphs, render_graph_figures
        from wgs_agent.tools.detailed_report import load_gene_family_evidence, resolve_report_model
        from wgs_agent.tools.report_maker import _generate_fpdf_report, build_full_report

        lock = None
        try:
            sid = str(params["sample_id"])
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", sid) or sid in {".", ".."}:
                raise ValueError("样本编号格式无效")
            analysis_path = Path(str(params["analysis_json_path"])).resolve()
            output_dir = analysis_path.parent
            filenames = {
                "markdown": f"{sid}_health_report.md", "pdf": f"{sid}_health_report.pdf",
                "structured": f"{sid}_report.json", "evidence": f"{sid}_report_evidence.json",
            }
            reserved = {output_dir / name for name in filenames.values()}
            if analysis_path in reserved:
                raise ValueError("分析输入不能使用报告输出文件名")
            lock_path = output_dir / f".{sid}.report.lock"
            lock = os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600), "a+")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return ToolResult(content="该样本的报告正在生成，请稍后查看。", is_error=True)

            original_analysis = analysis_path.read_bytes()
            data = json.loads(original_analysis)
            if not isinstance(data, dict):
                raise ValueError("分析结果必须是 JSON 对象")
            if data.get("sample_id") not in (None, "", sid):
                raise ValueError("分析文件中的样本编号与请求不一致")

            def module(key: str) -> dict:
                value = data.get(key)
                return value if isinstance(value, dict) else {}

            knowledge = module("knowledge")
            knowledge_path = str(params.get("knowledge_json_path", ""))
            if knowledge_path:
                if Path(knowledge_path).resolve() in reserved:
                    raise ValueError("知识输入不能使用报告输出文件名")
                supplied = json.loads(Path(knowledge_path).read_text(encoding="utf-8"))
                if not isinstance(supplied, dict):
                    raise ValueError("知识结果必须是 JSON 对象")
                knowledge = supplied
            # Read existing canonical artifacts to recover complete taxonomy and
            # pathways from historical analysis JSONs that only retained Top N.
            inputs = load_existing_report_inputs(sid)
            from wgs_agent.reporting.template_catalog import TEMPLATE_INPUT_KEYS
            for key in dict.fromkeys(("taxonomy", "diversity", "functional_modules", "nutrition", "diet", "symptoms", "gut_brain", "resistance", "pathogens", "disease_models", *TEMPLATE_INPUT_KEYS)):
                if isinstance(data.get(key), (dict, list)):
                    inputs[key] = data[key]
            refreshed = refresh_reference_comparisons(data, inputs)
            analysis_payload = (
                json.dumps(refreshed, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
                if refreshed != data else original_analysis
            )
            data = refreshed
            if isinstance(data.get("diversity"), dict):
                inputs["diversity"] = data["diversity"]
            context = dict(module("metadata"))
            context.update({
                "analysis_sha256": hashlib.sha256(analysis_payload).hexdigest(),
                "knowledge_sha256": hashlib.sha256(json.dumps(knowledge, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                "report_version": VERSION,
            })
            context["health_inputs"] = inputs
            pathways = module("pathways")
            if inputs.get("pathways") and pathways.get("is_complete") is not True:
                pathways = inputs["pathways"]
            proteins = module("proteins") or module("protein") or module("gene_families")
            if not proteins:
                proteins = load_gene_family_evidence(sid)
            # Routine report generation never launches FMT matching or a new
            # projection. Existing optional FMT results remain in an appendix.
            document = build_document(
                sid, module("species"), module("compare"), module("enterotype"), pathways,
                module("metabolites"), module("drugs"), module("diseases"), knowledge,
                proteins, module("fmt_matching"), context,
            )
            await enrich_document(document)
            document = generate_narrative(document, resolve_report_model())
            attach_subgraphs(document)
            translate_graph_labels(document, resolve_graph_model())
            document["audit"]["generation_id"] = uuid.uuid4().hex
            context["report_document"] = document
            evidence_manifest = {
                "sample_id": sid, "report_version": VERSION,
                "context": document["audit"], "evidence": document["evidence"],
                "fmt_matching": document["fmt_matching"],
                "knowledge_subgraphs": {t["id"]: t["knowledge_subgraph"] for s in document["sections"] for t in s["topics"]},
            }
            # Stage all artifacts first. A renderer failure preserves the last
            # complete report instead of publishing new Markdown with an old PDF.
            with tempfile.TemporaryDirectory(prefix=f".{sid}-report-", dir=output_dir) as temporary:
                staging = Path(temporary)
                figure_names = render_graph_figures(document, staging)
                from wgs_agent.reporting.word_figures import render_word_figures
                figure_names.update(render_word_figures(document, staging))
                markdown = build_full_report(
                    sid, module("species"), module("compare"), module("enterotype"), pathways,
                    module("metabolites"), module("drugs"), module("diseases"), knowledge,
                    protein_data=proteins, report_context=context,
                )
                evidence_manifest["module_bibliographies"] = document.get("module_bibliographies", [])
                evidence_manifest["graph_label_translations"] = document.get("graph_label_translations", {})
                evidence_manifest["presentation"] = document.get("presentation", {})
                evidence_manifest["overview_findings"] = document.get("overview_findings", [])
                evidence_manifest["word_figures"] = document.get("word_figures", {})
                evidence_manifest["word_sections"] = document.get("word_sections", [])
                (staging / filenames["markdown"]).write_text(markdown, encoding="utf-8")
                (staging / filenames["structured"]).write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
                (staging / filenames["evidence"]).write_text(json.dumps(evidence_manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
                _generate_fpdf_report(markdown, sid, str(staging / filenames["pdf"]))
                if analysis_path.read_bytes() != original_analysis:
                    raise ValueError("报告生成期间分析文件已更新，请重新生成。")
                staged_analysis = staging / "analysis.json"
                if analysis_payload != original_analysis:
                    staged_analysis.write_bytes(analysis_payload)
                    os.chmod(staged_analysis, 0o600)
                # Content-addressed figures are published only after PDF succeeds.
                # An interrupted publication leaves the previous report figures valid.
                for name in figure_names.values():
                    os.replace(staging / name, output_dir / name)
                for name in filenames.values():
                    os.chmod(staging / name, 0o600)
                    os.replace(staging / name, output_dir / name)
                if staged_analysis.is_file():
                    os.replace(staged_analysis, analysis_path)
            result = {
                "markdown": markdown, "markdown_path": str(output_dir / filenames["markdown"]),
                "pdf_path": str(output_dir / filenames["pdf"]), "sample_id": sid,
                "structured_path": str(output_dir / filenames["structured"]),
                "evidence_path": str(output_dir / filenames["evidence"]),
                "renderer_used": "health_markdown_fpdf", "template_path": VERSION,
                "llm_status": document["audit"]["llm_status"],
                "llm_accepted_topics": document["audit"].get("accepted_topics", 0),
                "reference_comparison": document["audit"].get("reference_comparison", {}),
                "figure_paths": {key: str(output_dir / name) for key, name in figure_names.items()}, "pdf_error": "",
            }
            return _make_result(f"报告已生成: {result['pdf_path']}\n报告版本: {VERSION}", result)
        except Exception as exc:
            return ToolResult(content=f"报告生成失败（{type(exc).__name__}）: {exc}", is_error=True, error_type="runtime_error")
        finally:
            if lock is not None:
                lock.close()


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
