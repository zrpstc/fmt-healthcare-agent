"""Render the measured scope and status of chapter six without invented taxa."""
from wgs_agent.pipeline.non_bacterial import load_chapter6_inputs


def _payload(module, data, qc_failed):
    labels = {'archaea': '古菌标记物筛查', 'fungi': '真菌标记物筛查',
              'dna_viruses': '病毒序列簇（VSC）筛查'}
    states = {'detected': '已完成，检出候选信号', 'not_detected': '已完成，本参考库与阈值内未检出',
              'not_analyzed': '尚未完成分析或缺少上游结果', 'invalid_input': '上游结果不完整或格式异常'}
    viral = module == 'dna_viruses'
    headers = (['病毒序列簇/检测范围', '检出状态', '覆盖广度', '平均覆盖深度', 'DNA类型与注释'] if viral
               else ['物种/检测范围', '检出状态', '相对丰度', '分析范围与依据'])
    if qc_failed:
        return headers, [[labels[module], '样本质控未通过，暂不作结果判读', *(['未提供'] * (len(headers) - 2))]]
    status = states.get(data.get('status'), '结果状态待核实')
    count = data.get('detected_clusters' if viral else 'detected_species')
    if count is not None:
        status += f'；检出数量 {count}'
    rows = []
    if viral:
        rows.append([labels[module], status, '—', '—',
                     '未提供基因组类型注释的 VSC 仅作为病毒候选，不能据此确认为 DNA 病毒。'])
        for r in data.get('records', []):
            annotation = (r.get('genome_type') if r.get('dna_confirmed') else 'DNA类型未核实')
            if r.get('reference_genome'):
                annotation += '；参考基因组：' + str(r['reference_genome'])
            rows.append([r['name'], '检出', f"{r['breadth_of_coverage'] * 100:.2f}%",
                         f"{r['depth_of_coverage_mean']:.4g}×", annotation])
        rows.append(['检测边界', '覆盖指标是序列比对证据，不是相对丰度', '—', '—',
                     '不依据 VSC 名称推断宿主、致病风险或确认 DNA 类型。'])
    else:
        rows.append([labels[module], status, '—',
                     'MetaPhlAn 标记物参考库筛查；未检出不代表样本完全不存在该类微生物。'])
        rows.extend([[r['name'], '检出', f"{r['abundance']:.6g}%", r['lineage']] for r in data.get('records', [])])
        rows.append(['检测边界', '限于本参考库与阈值', '—',
                     '真核生物仅在谱系明确属于真菌时纳入。相对丰度沿用完整细胞微生物谱分母，未在本类内重新归一化。'])
    return headers, rows


def render_other_microbes(body, block, module):
    if module not in ('archaea', 'fungi', 'dna_viruses'):
        return False
    data = body.inputs.get(module)
    if not isinstance(data, dict) or data.get('chapter_six_schema') != 1:
        return False  # Retain compatibility with supplied historical assays.
    body.chapter_six_module = module
    headers, rows = _payload(module, data, body.qc_failed)
    body.emit(headers, rows, '')
    return True


def table_payload(document, sub, data=None):
    if data is None:
        from .word_template import Data
        data = Data(document).load(6, sub)
    module = getattr(data, 'chapter_six_module', None)
    if module is None:
        return None
    value = data.inputs.get(module)
    if not isinstance(value, dict) or value.get('chapter_six_schema') != 1:
        return None
    headers, rows = _payload(module, value, data.qc_failed)
    return {'headers': headers, 'rows': rows}


def bound_headers(document, block):
    result = table_payload(document, int(block['id'].split('.')[1]))
    return result['headers'] if result is not None else None


