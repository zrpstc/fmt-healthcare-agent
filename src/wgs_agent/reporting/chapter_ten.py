"""Chapter 10: measured metabolic potential, evidence, and derived trait indices."""
from __future__ import annotations

import math
import re

from .chapter_eight import HEADERS, _contributors, _direction, _paths, detected_genes

SCORE_NOTE = (
    "代谢能力相对评分采用具有有效参照比较的通路百分位（0～100），同一产物、同一代谢方向的多条通路取等权均值。"
    "合成、分解和未注明方向分别展示；缺失评分不按0分处理。"
    "表中只列本样本有检出支持的基因，优先展示3～5种；不足3种时据实列出，不补入文献候选基因。"
)
TRAIT_NOTE = (
    "下列指标为本报告的探索性代谢关联评分（0～100），来源于10.1～10.3的物质代谢评分，"
    "不是睡眠、压力或情绪问卷的实测分数。每种物质先对有效通路百分位取等权均值，"
    "再对指标所纳入物质等权平均；至少2种物质有有效评分才计算，缺失项不计0分。"
    "分值越高表示所覆盖相关代谢路径的相对潜能越强，不表示睡眠更好、压力更低或情绪更佳；"
    "合成与分解方向需结合前三节分别查看。25和75分仅作展示分层，不是临床界值。"
)

# Each entry: canonical identity, report label, aliases, always show when evidence is missing.
TARGETS = {
    1: (
        ("gaba", "γ-氨基丁酸（GABA）", ("gaba", "gamma-aminobutyr", "γ-aminobutyr", "γ-氨基丁酸", "4-氨基丁酸"), True),
        ("serotonin", "5-羟色胺（血清素）", ("serotonin", "5-hydroxytryptamine", "5-ht", "5-羟色胺", "血清素"), True),
        ("dopamine", "多巴胺", ("dopamine", "多巴胺"), True),
        ("histamine", "组胺", ("histamine", "组胺"), True),
        ("acetylcholine", "乙酰胆碱", ("acetylcholine", "乙酰胆碱"), True),
        ("melatonin", "褪黑素", ("melatonin", "褪黑素"), True),
        ("norepinephrine", "去甲肾上腺素", ("norepinephrine", "noradrenaline", "去甲肾上腺素"), False),
    ),
    2: (
        ("tryptophan", "色氨酸", ("tryptophan", "色氨酸"), True),
        ("indole", "吲哚", ("indole", "吲哚"), True),
        ("ipa", "吲哚-3-丙酸（IPA）", ("indole-3-propionic", "indole-3-propionate", "indolepropionic", "indolepropionate", "吲哚-3-丙酸", "吲哚丙酸", "ipa"), True),
        ("iaa", "吲哚-3-乙酸（IAA）", ("indole-3-acetic", "indole-3-acetate", "indoleacetic", "indoleacetate", "吲哚-3-乙酸", "吲哚乙酸", "iaa"), True),
        ("ila", "吲哚-3-乳酸（ILA）", ("indole-3-lactic", "indole-3-lactate", "indolelactic", "indolelactate", "吲哚-3-乳酸", "吲哚乳酸", "ila"), True),
        ("kynurenine", "犬尿氨酸", ("kynurenine", "犬尿氨酸"), True),
        ("tryptamine", "色胺", ("tryptamine", "色胺"), False),
        ("phenylacetate", "苯乙酸", ("phenylacetate", "phenylacetic", "苯乙酸"), False),
        ("phenylpropionate", "苯丙酸", ("phenylpropionate", "phenylpropionic", "苯丙酸"), False),
        ("cresol", "对甲酚", ("p-cresol", "para-cresol", "对甲酚"), False),
    ),
    3: (
        ("estrogen", "雌激素（去结合/再活化）", ("estrogen", "oestrogen", "雌激素"), True),
        ("estradiol", "雌二醇", ("estradiol", "oestradiol", "雌二醇"), True),
        ("estrone", "雌酮", ("estrone", "oestrone", "雌酮"), True),
        ("estriol", "雌三醇", ("estriol", "oestriol", "雌三醇"), True),
        ("equol", "雌马酚", ("equol", "雌马酚"), False),
    ),
}

TRAITS = (
    ("sleep", "睡眠相关代谢", ("gaba", "serotonin", "melatonin")),
    ("stress", "压力相关代谢", ("gaba", "serotonin", "ipa", "kynurenine")),
    ("mood", "情绪相关代谢", ("gaba", "serotonin", "dopamine", "kynurenine")),
)
TRAIT_HEADERS = ["指标", "关联代谢评分（0～100）", "评分状况", "纳入物质（评分）", "证据覆盖"]
_LABELS = {key: label for entries in TARGETS.values() for key, label, _, _ in entries}
_SPECIFIC = {"indole": {"ipa", "iaa", "ila"}, "tryptamine": {"serotonin"}, "tryptophan": {"serotonin", "melatonin", "indole", "ipa", "iaa", "ila", "kynurenine", "tryptamine"}, "estrogen": {"estradiol", "estrone", "estriol"}}


def search_terms(sub):
    return tuple(dict.fromkeys(alias for _, _, aliases, _ in TARGETS.get(sub, ()) for alias in aliases))


def _contains(text, term):
    if term.isascii() and len(term) <= 5:
        return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None
    return term in text


def _identities(row):
    product = row.get("target_product") or row.get("product") or row.get("metabolite")
    fields = [product] if isinstance(product, str) and product.strip() else [row.get(k, "") for k in ("name", "label", "pathway_name", "annotation", "function")]
    text = " ".join(str(value) for value in fields).casefold().replace("_", " ")
    matches = {key for entries in TARGETS.values() for key, _, aliases, _ in entries if any(_contains(text, alias.casefold()) for alias in aliases)}
    # A specific indole derivative or end product must not be counted again as its precursor.
    return {key for key in matches if not (_SPECIFIC.get(key, set()) & matches)}


def target_groups(data, sub):
    from .word_template import _function_rows
    rows = [] if data.qc_failed else _function_rows(data, 10, sub)
    selected = {key: [] for key, _, _, _ in TARGETS.get(sub, ())}
    for row in rows:
        for key in _identities(row) & selected.keys():
            if not any(row is old for old in selected[key]):
                selected[key].append(row)
    return [(key, label, selected[key]) for key, label, _, always in TARGETS.get(sub, ()) if always or selected[key]]


def table_rows(document, sub, data=None):
    from .word_template import Data
    data = data or Data(document)
    if sub == 4:
        return trait_table_rows(document, data)
    return [[label, _paths(rows), _contributors(rows), "、".join(detected_genes(rows)) or "未提供检出基因证据"] for _, label, rows in target_groups(data, sub)]


def chart_payload(document, spec):
    from .word_figures import _percentile
    from .word_template import Data
    sub = int(spec["id"].split(".")[1])
    if sub == 4:
        payload = trait_payload(document)
        return {**payload, "chapter_eight_mode": True, "labels": [row["label"] for row in payload["traits"]],
                "series": [{"name": "代谢关联评分", "values": [row["score"] for row in payload["traits"]]}], "unit": "代谢关联评分（0～100）"}
    data = Data(document)
    groups = target_groups(data, sub)
    series = []
    for mode in ("合成", "分解", _direction({})):
        values = []
        for _, _, rows in groups:
            valid = [_percentile(row) for row in rows if _direction(row) == mode]
            valid = [value for value in valid if value is not None]
            values.append(math.fsum(valid) / len(valid) if valid else None)
        if any(value is not None for value in values):
            series.append({"name": mode, "values": values})
    if not series:
        series = [{"name": "代谢能力", "values": [None] * len(groups)}]
    return {"chapter_eight_mode": True, "chapter_ten_mode": True, "labels": [label for _, label, _ in groups],
            "series": series, "unit": "代谢能力相对评分（0～100）", "scale_min": 0, "scale_max": 100,
            "status": "available" if any(value is not None for item in series for value in item["values"]) else "missing",
            "reason": "质控未通过，暂不展示代谢评分" if data.qc_failed else "缺少有效参照评分，暂不评分", "note": SCORE_NOTE}


def _material_scores(data):
    from .word_figures import _percentile
    values = {}
    for sub in (1, 2, 3):
        for key, _, rows in target_groups(data, sub):
            valid = [_percentile(row) for row in rows]
            valid = [value for value in valid if value is not None]
            if valid:
                values[key] = math.fsum(valid) / len(valid)
    return values


def trait_payload(document, data=None):
    from .word_template import Data
    data = data or Data(document)
    values = _material_scores(data)
    traits = []
    for key, label, expected in TRAITS:
        inputs = [{"id": name, "label": _LABELS[name], "score": values[name]} for name in expected if name in values]
        score = math.fsum(item["score"] for item in inputs) / len(inputs) if len(inputs) >= 2 else None
        band = "证据不足，暂不评分" if score is None else "相对偏低" if score < 25 else "相对偏高" if score >= 75 else "中等水平"
        traits.append({"id": key, "label": label, "score": score, "band": band, "inputs": inputs,
                       "observed": len(inputs), "expected": len(expected), "missing": [_LABELS[name] for name in expected if name not in values],
                       "coverage": "完整" if len(inputs) == len(expected) else "部分" if score is not None else "不足"})
    return {"traits": traits, "status": "available" if any(row["score"] is not None for row in traits) else "missing",
            "scale_min": 0, "scale_max": 100, "method": "chapter10_neuroactive_equal_weight_v1", "minimum_metabolites": 2,
            "reason": "质控未通过，暂不评分" if data.qc_failed else "至少需要2种相关物质的有效代谢评分", "note": TRAIT_NOTE}


def trait_table_rows(document, data=None):
    rows = []
    for trait in trait_payload(document, data)["traits"]:
        inputs = "；".join(f'{item["label"]} {item["score"]:.1f}' for item in trait["inputs"]) or "未提供有效物质评分"
        coverage = f'{trait["observed"]}/{trait["expected"]}（{trait["coverage"]}）'
        if trait["missing"]:
            coverage += "；缺少：" + "、".join(trait["missing"])
        rows.append([trait["label"], f'{trait["score"]:.1f}' if trait["score"] is not None else "暂不评分", trait["band"], inputs, coverage])
    return rows


def interpretation(document, sub):
    from .word_template import Data
    if sub == 4:
        payload = trait_payload(document)
        parts = []
        for trait in payload["traits"]:
            if trait["score"] is None:
                parts.append(f'{trait["label"]}：当前仅{trait["observed"]}种物质有有效评分，证据不足，暂不计算该指标。')
                continue
            inputs = "、".join(f'{item["label"]}（{item["score"]:.1f}）' for item in trait["inputs"])
            parts.append(f'{trait["label"]}为{trait["score"]:.1f}/100，{trait["band"]}；依据{inputs}计算，证据覆盖{trait["observed"]}/{trait["expected"]}。')
        if any(trait["coverage"] == "部分" for trait in payload["traits"]):
            parts.append("部分指标使用的物质证据不完整，分值只代表已覆盖的代谢路径；不同证据覆盖度的结果不作直接健康优劣排序。")
        parts.append("这些结果描述菌群的相关代谢潜能，不能据此推断体内神经递质或激素浓度，也不能直接判断睡眠、压力或情绪症状；结果解读需结合实际状态与独立测量。")
        return " ".join(parts)
    data = Data(document)
    groups = target_groups(data, sub)
    available = [(label, rows) for _, label, rows in groups if rows]
    if data.qc_failed:
        return "样本质控未通过，本节不展示代谢评分、贡献菌或检出基因结论。"
    if not available:
        return "本节尚无可匹配的样本代谢证据；条形图保留待评分状态，表格不填入推测的通路、贡献菌或候选基因。"
    evidence = sum(bool(detected_genes(rows)) for _, rows in available)
    return f'本节有{len(available)}种目标产物匹配到样本代谢通路，其中{evidence}种具有可列出的检出基因支持。条形图比较合成、分解及未注明方向的相对潜能；表格可追溯主要路径、贡献菌和最多5种检出基因。高相对评分表示相关路径潜能较强，不等同于该产物的实测浓度。'
