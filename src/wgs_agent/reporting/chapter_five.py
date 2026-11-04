"""Report integration for explicitly qualified chapter 5 measurements."""
from __future__ import annotations
from wgs_agent.pipeline.resistome_mge import load_chapter5_inputs

STATUS_TEXT = {
    "not_run":"尚未运行该分析，不能据此解释为未检出。",
    "running":"分析正在运行，暂不输出检测结论。",
    "missing_input":"缺少可读的去宿主 FASTQ，尚未完成检测。",
    "missing_database":"专用参考数据库尚未就绪，尚未完成检测。",
    "missing_dependency":"比对程序尚未就绪，尚未完成检测。",
    "failed":"分析失败，尚无可用检测结论。",
    "invalid_output":"分析产物不可读或格式校验失败，暂不输出检测结论。",
    "locked":"该样本已有同类分析正在运行。",
}
LIMIT = "本节为获得性耐药基因及 IS/MITE 参考序列的 reads 筛查；不覆盖耐药点突变、完整质粒、整合子或所有转座子。耐药基因信号不等同于药敏表型；同一样本中共检出不证明基因与元件相连，也不确定宿主。"


def refresh_analysis_modules(path, sid, root=None):
    """Refresh chapter five without racing another chapter or a report writer."""
    from .module_refresh import refresh_module_fields
    if root is None:
        from wgs_fmt_platform.paths import bioinformatics_root
        root = bioinformatics_root()
    return refresh_module_fields(path, sid, load_chapter5_inputs(sid, root, include_missing=False))


def render_resistance(body, block):
    amr=body.inputs.get("resistance")
    mge=body.inputs.get("mobile_elements")
    target=amr if block in (1,2) else mge
    if not isinstance(target,dict) or target.get("schema_version")!=1:
        return False
    if body.qc_failed:
        body.out.append("样本质控未通过，暂不解释耐药组或可移动遗传元件结果。")
        return True
    if block==4:
        body.out.append(LIMIT)
        return True
    if target.get("status")!="completed":
        body.out.append(STATUS_TEXT.get(target.get("status"),"结果状态未确认，暂不输出检测结论。"))
        if block==3:
            body.out.append("宿主归属与耐药基因—元件物理连锁未评估；需要组装 contig 或长读长等证据。")
        return True
    key="genes" if block in (1,2) else "results"
    rows=target.get(key,[])
    summary=target.get("summary",{})
    body.out.append(f"已完成 {target.get('database','专用数据库')} 筛查：{summary.get('input_reads',0):,} 条去宿主 reads，{summary.get('reference_count',0):,} 个去重参考序列，{len(rows)} 个达到阈值的参考序列信号。")
    if block==1:
        body.emit(["耐药基因/等价参考组","支持 reads","参考覆盖广度 / 一致性","丰度 RPKM"],
            [[r.get("gene",r["name"]),r["mapped_reads"],f"{r['breadth_coverage']:.2f}% / {r['identity']:.2f}%",f"{r['abundance']:.3f}"] for r in rows],
            "在本次参考库和阈值范围内未检出达标获得性耐药基因；不代表样本不存在其他耐药机制。")
    elif block==2:
        body.emit(["药物类别注释","机制注释","耐药基因/等价参考组","证据类型"],
            [[r.get("drug_class","未注释"),r.get("mechanism","未注释"),r.get("gene",r["name"]),"参考序列 reads 信号；非药敏结果"] for r in rows],
            "本次无达标耐药基因可用于类别与机制汇总。")
    else:
        body.emit(["IS/MITE 参考组","元件类别","覆盖广度 / 支持 reads","丰度 RPKM"],
            [[r["name"],r.get("element_type","未分类"),f"{r['breadth_coverage']:.2f}% / {r['mapped_reads']}",f"{r['abundance']:.3f}"] for r in rows],
            "在本次 IS/MITE 参考库和阈值范围内未检出达标信号；完整质粒、整合子等未在本次筛查中评估。")
        body.out.append("宿主归属与耐药基因—元件物理连锁未评估；现有 reads 筛查不提供 contig 定位。")
    thresholds=target.get("thresholds",{})
    body.out.append(f"检测阈值：至少 {thresholds.get('min_reads',3)} 条支持 reads，参考覆盖广度 ≥{thresholds.get('min_breadth',80):g}%，比对一致性 ≥{thresholds.get('min_identity',90):g}%，MAPQ ≥{thresholds.get('min_mapq',20)}。RPKM 按参考长度与总输入 reads 归一化，不是细胞相对丰度。")
    return True


def has_results_schema(document):
    inputs=document.get('template_inputs',{})
    return any(isinstance(inputs.get(k),dict) and inputs[k].get('schema_version')==1 for k in ('resistance','mobile_elements'))


def render_chapter(document):
    from .template_body import Body
    body=Body(document)
    body.out.append('## 5 耐药组与可移动遗传元件')
    headings=('获得性耐药基因筛查','药物类别与耐药机制注释','IS/MITE 筛查与物理连锁证据','检测范围与结果解释')
    for block,title in enumerate(headings,1):
        body.out.append(f'### 5.{block} {title}')
        body.resistance(block)
    return body.out
