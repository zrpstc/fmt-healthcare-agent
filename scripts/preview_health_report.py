#!/usr/bin/env python3
"""Generate an isolated preview; no model API is called without --use-llm."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path


def demonstration() -> dict:
    species = [
        {"species": "Bacteroides vulgatus", "abundance": 40},
        {"species": "Faecalibacterium prausnitzii", "abundance": 25},
        {"species": "Roseburia intestinalis", "abundance": 15},
        {"species": "Bifidobacterium longum", "abundance": 5},
        {"species": "Akkermansia muciniphila", "abundance": 3},
        {"species": "Escherichia coli", "abundance": 2},
        {"species": "unclassified SGB demonstration", "abundance": 10},
    ]
    for row in species:
        row.update({"unit": "%", "status": "unknown"})
    pathways = [
        ("碳水化合物代谢 / glycolysis", 0.015),
        ("膳食纤维利用 / xylan degradation", 0.009),
        ("丁酸相关通路 / butyrate biosynthesis", 0.008),
        ("丙酸相关通路 / propionate metabolism", 0.007),
        ("色氨酸相关通路 / tryptophan metabolism", 0.006),
        ("叶酸相关通路 / folate biosynthesis", 0.005),
        ("脂质代谢 / fatty acid biosynthesis", 0.004),
        ("嘌呤代谢 / purine metabolism", 0.003),
        ("组胺相关通路 / histamine metabolism", 0.002),
        ("乳酸相关通路 / lactate metabolism", 0.001),
    ]
    return {
        "sample_id": "DEMO__001",
        "metadata": {"name": "版式演示（非真实受检者）", "demonstration": True},
        "species": {"species_list": species, "unit": "%", "is_complete_profile": True},
        "taxonomy": {
            "complete": True,
            "unit": "%",
            "ranks": {
                "species": species,
                "phylum": [
                    {"name": name, "abundance": value}
                    for name, value in (
                        ("Bacteroidota", 40),
                        ("Bacillota", 50),
                        ("Actinomycetota", 5),
                        ("Verrucomicrobiota", 3),
                        ("Pseudomonadota", 2),
                    )
                ],
                "genus": [
                    {"name": row["species"].split()[0], "abundance": row["abundance"]}
                    for row in species
                ],
            },
        },
        "enterotype": {"type": "演示优势菌属：Bacteroides"},
        "pathways": {
            "is_complete": True,
            "unit": "relative_abundance",
            "pathways": [
                {"id": f"DEMO-PATHWAY-{i}", "name": name, "abundance": value}
                for i, (name, value) in enumerate(pathways, 1)
            ],
        },
        "metabolites": {
            "data_type": "measured",
            "method": "合成示例，非实际检测",
            "unit": "mmol/kg",
            "metabolites": [
                {"name": "丁酸 / butyrate（演示）", "value": 0},
                {"name": "乙酸 / acetate（演示）", "value": 12},
            ],
        },
        "functional_modules": {
            "observations": [
                {"name": "定植抵抗相关基因集合（演示）", "value": 0.003, "unit": "相对丰度"},
                {"name": "氧化应激相关基因集合（演示）", "value": 0.002, "unit": "相对丰度"},
            ]
        },
        "diet": {
            "observations": [
                {
                    "name": "膳食纤维摄入（演示）",
                    "value": 18,
                    "unit": "g/day",
                    "method": "合成饮食问卷",
                },
                {"name": "食物结构记录（演示）", "answer": "含谷物、蔬菜与乳制品"},
            ]
        },
        "nutrition": {
            "observations": [
                {
                    "name": "蛋白质摄入（演示）",
                    "value": 65,
                    "unit": "g/day",
                    "method": "合成饮食问卷",
                },
            ]
        },
        "symptoms": {
            "observations": [
                {"name": "腹胀（演示）", "answer": "偶发，未提供病程与诱因"},
                {"name": "排便性状（演示）", "answer": "问卷记录为成形便"},
            ]
        },
        "diseases": {
            "diseases": [
                {
                    "disease": "肠易激综合征研究关联（演示）",
                    "risk_score": 25,
                    "score_type": "synthetic_association_not_probability",
                    "details": [
                        {
                            "species": "Bacteroides vulgatus",
                            "status": "unknown",
                            "direction": "变化",
                        }
                    ],
                }
            ]
        },
        "resistance": {
            "method": "合成示例，非实际耐药检测",
            "genes": [
                {
                    "gene": "tetQ（演示）",
                    "drug_class": "tetracycline",
                    "mechanism": "ribosomal protection",
                    "value": 2,
                    "unit": "copies/million reads",
                    "result": "合成检出示例",
                }
            ],
        },
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--analysis",
        type=Path,
        help="An existing analysis JSON; defaults to clearly labelled synthetic data",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/health-report-preview"))
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use the configured model service; sends selected sample evidence",
    )
    parser.add_argument(
        "--use-knowledge-graph",
        action="store_true",
        help="Retrieve related claims from the configured LitKG service",
    )
    parser.add_argument(
        "--use-graph-llm",
        action="store_true",
        help="Translate graph labels with the environment-configured model, independently of report narration",
    )
    args = parser.parse_args()
    if not (args.use_graph_llm or args.use_llm):
        os.environ["WGS_REPORT_GRAPH_LLM_DISABLED"] = "1"
    if not args.use_knowledge_graph:
        os.environ["WGS_REPORT_GRAPH_RETRIEVAL_DISABLED"] = "1"
    if not args.use_llm:
        os.environ["WGS_REPORT_LLM_DISABLED"] = "1"
    else:
        from wgs_agent.tools.detailed_report import resolve_report_model

        if resolve_report_model() is None:
            raise SystemExit(
                "尚未配置报告模型，请设置工作区模型或 WGS_REPORT_LLM_BASE_URL/WGS_REPORT_LLM_MODEL。"
            )
    data = (
        json.loads(args.analysis.read_text(encoding="utf-8")) if args.analysis else demonstration()
    )
    sid = data.get("sample_id") or (
        args.analysis.stem.removesuffix("_analysis") if args.analysis else "DEMO__001"
    )
    data["sample_id"] = sid
    from wgs_agent.pipeline.upload_workflow import validate_sample_id
    from wgs_agent.tools.domain_tools import ReportGeneratorTool

    validate_sample_id(sid)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    analysis_path = output / f"{sid}_analysis.json"
    if analysis_path.exists():
        raise SystemExit("预览目录已有同名输入，请选择新的 --output-dir。")
    analysis_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    analysis_path.chmod(0o600)
    result = await ReportGeneratorTool().invoke(
        {"sample_id": sid, "analysis_json_path": str(analysis_path)}
    )
    if result.is_error:
        raise SystemExit(result.content)
    print(f"预览已生成：{output / (sid + '_health_report.pdf')}")
    generated = json.loads((output / f"{sid}_report.json").read_text(encoding="utf-8"))
    print("模型生成状态：" + generated["audit"]["llm_status"])


if __name__ == "__main__":
    asyncio.run(main())
