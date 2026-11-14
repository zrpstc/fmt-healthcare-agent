"""Display labels come from the actual comparison provider, never a stale template."""

def short(inputs):
    return "cMD"


def title(inputs):
    audit = ((inputs.get("healthy_comparison") or {}).get("audit") or {})
    return audit.get("reference_population", "curatedMetagenomicData健康标签成人粪便对照")


def profile(inputs):
    return short(inputs) + " 独立谱"


def method(inputs):
    return "MetaPhlAn 3 / v30（待测3.0.14；来源小版本未公布）"


def audit_summary(inputs):
    """Shared wording for Markdown/PDF and Word population sections."""
    comparison = inputs.get("healthy_comparison") or {}
    audit = comparison.get("audit") or {}
    if audit.get("status") != "available":
        return ["未建立健康对照：" + str(audit.get("reason_cn", "缺少有效参考或待测谱"))
                + "；原因码：" + str(audit.get("reason", "unavailable")) + "。"]
    rows = []
    bootstrap = audit.get("bootstrap", {})
    if bootstrap:
        rows.append(f"分位数不确定性：固定种子{bootstrap['seed']}，bootstrap {bootstrap['iterations']}次；"
                    "P5、P95和目标百分位均给出95%置信区间。边界重叠标为borderline，不判高低。")
    baseline = comparison.get("outlier_baseline")
    if baseline:
        approximation = "全参考集分位数近似留一法" if baseline['method'].startswith('full_cohort') else "逐个体留一法"
        rows.append(f"多重比较基线：目标有{baseline['target_outside_count']}个物种越出P5–P95，"
                    f"处于参考者越界物种数分布的第{baseline['target_percentile']:.4g}百分位；"
                    f"参考计数P5–P95为{baseline['p5']:.4g}–{baseline['p95']:.4g}（{approximation}）。"
                    f"排除边界不确定后的确认越界数为{comparison.get('n_abnormal', 0)}，"
                    f"边界不确定数为{comparison.get('n_borderline', 0)}。此基线不是校正后的显著性检验。")
    depth = audit.get("sequencing_depth", {})
    for key, summary in depth.get("reference", {}).items():
        value = depth.get("target", {}).get(key)
        target_text = f"{value:.6g}" if value is not None else "未记录"
        rows.append(f"测序深度：{key}待测{target_text}；所选参考P5–P95为"
                    f"{summary['p5']:.6g}–{summary['p95']:.6g}（有记录{summary['n_reference']}人）。")
    rows.extend(depth.get("warnings", []))
    batch = audit.get("study_batch", {})
    if batch:
        r, s = batch['richness_median_range'], batch['shannon_median_range']
        rows.append(f"研究间批次：所选参考涉及{batch['n_studies']}项研究；研究内丰富度中位数范围"
                    f"{r[0]:.5g}–{r[1]:.5g}，Shannon中位数范围{s[0]:.5g}–{s[1]:.5g}。")
        rows.append("各研究人数及中位数：" + "；".join(
            f"{r['study_id']}：{r['n_subjects']}人，丰富度{r['richness_median']:.5g}，Shannon {r['shannon_median']:.5g}"
            for r in batch['studies']) + "。")
    return rows
