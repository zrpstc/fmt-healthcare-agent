"""Word-authored body, shared by the PDF and online preview.

word_contract.json is compiled from the four supplied DOCX files. Their prose,
table columns, column proportions, chart types, palette and flow geometry are
the presentation authority. Evidence topics remain stable for KG/references.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .inputs import finite
from .template_body import Body, _contributors, _linked, _pick, _sequence
from .template_catalog import CHAPTERS, TOPIC_PLACEMENT


@lru_cache(maxsize=1)
def contract():
    return json.loads(Path(__file__).with_name("word_contract.json").read_text(encoding="utf-8"))


def clean(value):
    return re.sub(r"【[^】]*】", "未提供", str(value)).replace("**", "")


class Data(Body):
    """Reuse validated assay adapters, without reusing the previous report prose."""

    def __init__(self, document):
        super().__init__(document)
        self.tables = []

    def emit(self, headers, rows, missing="本次未提供对应数据，无法判断。", limit=8):
        self.tables.append(
            {"headers": list(headers), "rows": [list(r) for r in rows], "missing": missing}
        )

    def load(self, chapter, sub):
        self.tables, self.out = [], []
        ids = CHAPTERS[chapter - 1][3][sub - 1][1]
        method = (
            self.composition,
            self.diversity,
            self.key_taxa,
            self.strains,
            self.resistance,
            self.other_microbes,
            self.nutrients,
            self.metabolism,
            self.ecology,
            self.brain,
            self.symptoms,
            self.diseases,
            self.specialized,
            self.synthesis,
        )[chapter - 1]
        method(sub, ids) if chapter in {8, 9, 10, 11, 12} else method(sub)
        return self


def _rows(data, headers):
    return next((t["rows"] for t in data.tables if t["headers"] == headers), [])


def _extra(data, name, *keys):
    return data.raw(name, *keys)


def _function_rows(data, chapter, sub):
    ids = CHAPTERS[chapter - 1][3][sub - 1][1]
    rows = data.topic_rows(*ids)
    words = {
        (7, 1): ("starch", "pectin", "inulin", "xylan", "淀粉", "果胶", "菊粉", "木聚糖"),
        (8, 1): ("acetate", "propionate", "butyrate", "乙酸", "丙酸", "丁酸"),
        (8, 2): ("lactate", "succinate", "乳酸", "琥珀酸"),
        (8, 3): ("bsh", "bai", "bile salt", "胆汁酸", "脱结合", "脱羟基"),
        (8, 4): ("indole", "tryptophan", "吲哚", "色氨酸"),
        (8, 5): (
            "cresol",
            "histamine",
            "putrescine",
            "cadaverine",
            "对甲酚",
            "组胺",
            "腐胺",
            "尸胺",
        ),
        (8, 6): (
            "hydrogen",
            "methanogenesis",
            "sulfate reduction",
            "产氢",
            "耗氢",
            "甲烷",
            "硫化氢",
        ),
        (8, 7): ("cutc", "cnta", "trimethylamine", "tma", "胆碱", "肉碱"),
        (8, 8): ("lipopolysaccharide", "lipid a", "peptidoglycan", "脂多糖", "肽聚糖"),
        (10, 1): ("gaba", "gabap", "glutamate decarboxylase", "catecholamine", "多巴胺"),
    }.get((chapter, sub), ())
    rows = list({id(r): r for r in rows + data.functions(words)}.values())
    if chapter == 8 and sub in {1, 2}:
        rows = [
            r
            for r in rows
            if not any(
                w in str(r.get("name", r.get("label", ""))).lower()
                for w in ("indole", "phenyl", "imidazole", "吲哚", "苯基", "咪唑")
            )
        ]
    return [r for r in rows if r.get("measurement_type") == "functional_potential"]


def _direction(row):
    value = str(row.get("reaction_direction", row.get("direction", ""))).lower()
    # Pathway names identify a reaction only when explicit, not by target name alone.
    value += " " + str(row.get("name", row.get("label", ""))).lower()
    generation = any(
        w in value for w in ("generation", "biosynthesis", "production", "生成", "合成")
    )
    use = any(
        w in value for w in ("utilization", "consumption", "degradation", "利用", "消耗", "降解")
    )
    return (
        "both"
        if generation and use
        else "generation"
        if generation
        else "use"
        if use
        else "unknown"
    )


def _join(rows, field):
    return "；".join(dict.fromkeys(str(field(r)) for r in rows)) or "未提供"


TARGETS = {
    "乙酸": ("acetate", "乙酸"),
    "丙酸": ("propionate", "丙酸"),
    "丁酸": ("butyrate", "丁酸"),
    "乳酸": ("lactate", "乳酸"),
    "琥珀酸": ("succinate", "琥珀酸"),
    "吲哚": ("indole", "吲哚"),
    "吲哚乳酸": ("indole lactate", "indolelactate", "吲哚乳酸"),
    "吲哚丙酸": ("indole propionate", "indolepropionate", "吲哚丙酸"),
    "对甲酚": ("cresol", "对甲酚"),
    "组胺": ("histamine", "组胺"),
    "腐胺": ("putrescine", "腐胺"),
    "尸胺": ("cadaverine", "尸胺"),
    "脱结合": ("bsh", "deconjugation", "脱结合"),
    "7α脱羟基": ("bai", "7 alpha", "7α", "dehydroxylation"),
    "抗性淀粉": ("resistant starch", "抗性淀粉"),
    "果胶": ("pectin", "果胶"),
    "菊粉": ("inulin", "菊粉"),
    "木聚糖": ("xylan", "木聚糖"),
    "产氢": ("hydrogen production", "hydrogen generation", "产氢"),
    "耗氢": ("hydrogen utilization", "hydrogen consumption", "耗氢"),
    "产甲烷": ("methanogenesis", "methane production", "产甲烷"),
    "硫化氢生成": ("sulfate reduction", "hydrogen sulfide", "硫化氢"),
    "胆碱相关路径": ("cutc", "choline", "胆碱"),
    "肉碱相关路径": ("cnta", "carnitine", "肉碱"),
    "脂多糖相关合成": ("lipopolysaccharide", "lipid a", "脂多糖"),
}


def matching(rows, label):
    terms = TARGETS.get(label, (label.lower(),))
    selected = []
    for row in rows:
        s = " ".join(
            str(row.get(k, "")) for k in ("name", "label", "annotation", "substrate")
        ).lower()
        if any(t in s for t in terms):
            if label == "吲哚" and any(t in s for t in ("lactate", "propionate", "乳酸", "丙酸")):
                continue
            selected.append(row)
    return selected


def redundancy_category(name):
    text = str(name).lower()
    if "butyrate" in text or "丁酸" in text:
        return "丁酸合成"
    if "lactate utilization" in text or "乳酸利用" in text:
        return "乳酸利用"
    # Cell-envelope polysaccharide synthesis is not dietary polysaccharide degradation.
    if any(
        w in text for w in ("lipopolysaccharide", "lipid a", "peptidoglycan", "脂多糖", "肽聚糖")
    ):
        return None
    substrate = any(
        w in text
        for w in ("starch", "pectin", "xylan", "polysaccharide", "多糖", "淀粉", "木聚糖", "果胶")
    )
    degradation = any(
        w in text for w in ("degradation", "utilization", "hydrolysis", "降解", "利用")
    )
    return "复杂多糖降解" if substrate and degradation else None


def bind_table(document, block, data=None):
    """Return exact Word columns, binding assays by meaning rather than column order."""
    chapter, sub = map(int, block["id"].split(".")[:2])
    data = data or Data(document).load(chapter, sub)
    headers = block["rows"][0]
    direct = _rows(data, headers)
    if direct and ident_not_special(block["id"]):
        return [[clean(v) for v in row] for row in direct]
    ident = block["id"]
    if ident == "14.2.t1":
        word = next(
            (
                t
                for s in document.get("word_sections", [])
                for t in s["topics"]
                if t["id"] == "word.14.2"
            ),
            {},
        )
        if word.get("advice"):
            sources = set(word.get("narrative_evidence_ids", []))
            refs = [
                "第" + TOPIC_PLACEMENT[t["id"]] + "节"
                for s in document["sections"]
                for t in s["topics"]
                if sources.intersection(t["evidence_ids"])
            ]
            return [
                [
                    "与本次发现对应的日常观察",
                    word["advice"],
                    "、".join(dict.fromkeys(refs)) or "本节已引用的检测证据",
                    "记录执行情况、症状及耐受变化",
                ]
            ]
    if ident == "1.1.t1":
        return [
            [label, r["label"], r["result_text"]]
            for label, kind in (
                ("门", "tax_phylum"),
                ("纲", "tax_class"),
                ("目", "tax_order"),
                ("科", "tax_family"),
                ("属", "tax_genus"),
                ("种", "species"),
            )
            for r in sorted(data.group(kind), key=lambda r: -(r.get("value") or 0))[:1]
        ] or [[r[0], "未提供", "未提供"] for r in block["rows"][1:]]
    if ident == "1.2.t1":
        top = sorted(
            [
                r
                for r in data.group("species")
                if finite(r.get("value")) is not None and r["value"] > 0
            ],
            key=lambda r: -r["value"],
        )
        values = {r[0]: r[1] for r in direct}
        if top and all(r.get("unit") == "%" for r in top):
            values["前五位物种合计占比"] = f"{sum(r['value'] for r in top[:5]):.5g}%"
        core = data.raw("core_microbiome", "members")
        parent = data.inputs.get("core_microbiome") or {}
        names = {r["label"].casefold(): r for r in top}
        corevals = [
            finite(
                r.get(
                    "value",
                    r.get(
                        "abundance",
                        names.get(str(_pick(r, "species", "name")).casefold(), {}).get("value"),
                    ),
                )
            )
            for r in core
        ]
        if (
            parent.get("definition")
            and core
            and all(v is not None for v in corevals)
            and len({str(_pick(r, "species", "name")).casefold() for r in core}) == len(core)
        ):
            values["核心成员检出数 / 参考成员数"] = f"{sum(v > 0 for v in corevals)} / {len(core)}"
            if all(
                r.get(
                    "unit",
                    parent.get(
                        "unit",
                        names.get(str(_pick(r, "species", "name")).casefold(), {}).get("unit"),
                    ),
                )
                == "%"
                for r in core
            ):
                values["检出核心成员的合计相对丰度"] = f"{sum(corevals):.5g}%"
        return [[seed[0], values.get(seed[0], "未提供")] for seed in block["rows"][1:]]
    if ident == "2.1.t1":
        observed = data.group("div_richness")
        even = data.group("div_evenness")
        shannon = data.group("div_shannon")
        parent = data.inputs.get("diversity") or {}
        refs = data.group("div_reference")
        result = []
        for label, key, items in (
            ("观测物种数", "richness", observed),
            ("丰富度估计", "richness_estimate", []),
            ("均匀度", "evenness", even),
            ("Shannon指数", "shannon", shannon),
        ):
            row = items[0] if items else {}
            ref = next((r for r in refs if r.get("metric") == key), row)
            value = row.get("result_text", "未提供")
            if (
                key == "richness_estimate"
                and finite(parent.get(key)) is not None
                and not data.qc_failed
            ):
                value = str(parent[key])
            result.append(
                [label, value, ref.get("reference_text", "未提供"), _pick(ref, "percentile")]
            )
        return result
    if ident == "2.3.t1":
        rows = []
        for label in ("丁酸合成", "乳酸利用", "复杂多糖降解"):
            found = [r for r in direct if redundancy_category(r[0]) == label]
            if found:
                rows.extend([[label + "（" + str(r[0]) + "）", *r[1:]] for r in found])
            else:
                rows.append([label, "未提供", "未提供", "未提供"])
        return rows
    if ident in {"3.1.t1", "3.2.t1"}:
        old = _rows(data, ["微生物名称", "功能或关注背景", "检出状态", "相对丰度", "人群分位数"])
        topics = data.topics

        def category(name):
            if "roseburia" in name.casefold():
                return "其他产丁酸相关菌"
            for tid, label in (
                ("key_taxa.bifidobacteria", "双歧杆菌相关"),
                ("key_taxa.lactic_acid", "乳杆菌相关属"),
                ("key_taxa.butyrate", "粪杆菌及产丁酸菌相关"),
                ("key_taxa.mucin", "阿克曼菌及黏液相关"),
                ("key_taxa.pathogens", "食源性致病菌"),
                ("key_taxa.opportunists", "条件致病菌"),
            ):
                if any(data.evidence[k]["label"] == name for k in topics[tid]["evidence_ids"]):
                    return label
            return "其他关注微生物"

        return [
            [category(r[0]), r[0], r[1], *r[2:]]
            if chapter == 3 and sub == 1
            else [category(r[0]), r[0], *r[2:], r[1]]
            for r in old
        ] or _missing_rows(block, data)
    if chapter == 6 and sub in {1, 2}:
        old = _rows(data, ["重点成员", "检出状态", "相对丰度", "功能或检测能力说明"])
        return [[r[0], f"{r[1]}；{r[2]}", r[3]] for r in old] or _missing_rows(block, data)
    if chapter in {7, 8} and sub != 4 or ident == "8.4.t1":
        if ident == "7.3.t1":
            result = []
            for seed, tid in zip(block["rows"][1:], CHAPTERS[6][3][2][1]):
                fs = data.topic_rows(tid)
                gen = [r for r in fs if _direction(r) in {"generation", "both"}]
                use = [r for r in fs if _direction(r) in {"use", "both"}]
                result.append(
                    [
                        seed[0],
                        _join(gen, lambda r: r["label"] + "：" + r["result_text"])
                        if gen
                        else "未单独判定",
                        _join(use, lambda r: r["label"] + "：" + r["result_text"])
                        if use
                        else "未单独判定",
                        _join(fs, _contributors),
                    ]
                )
            return result
        if ident == "7.1.t1" or chapter == 8:
            functions = _function_rows(data, chapter, sub)
            result = []
            for seed in block["rows"][1:]:
                label = seed[0]
                if "【" in label:
                    if not functions:
                        continue
                    label = "其他已提供功能"
                    rows = [
                        r
                        for r in functions
                        if not any(
                            matching([r], s[0]) for s in block["rows"][1:] if "【" not in s[0]
                        )
                    ]
                else:
                    rows = matching(functions, label)

                def get(rs):
                    return _join(rs, lambda r: r["result_text"])

                def path(rs):
                    return _join(rs, lambda r: r["label"])

                contributor = _join(rows, _contributors)
                evidence = _join(
                    rows, lambda r: f"{r['label']}：{r['result_text']}；{_sequence(r)}"
                )
                gen = [r for r in rows if _direction(r) in {"generation", "both"}]
                use = [r for r in rows if _direction(r) in {"use", "both"}]
                if ident == "7.1.t1":
                    values = [
                        label,
                        get(rows),
                        contributor,
                        path(rows) + "；" + _join(rows, _sequence),
                    ]
                elif sub == 1:
                    values = [
                        label,
                        path(gen) if gen else ("方向未确认：" + path(rows) if rows else "未提供"),
                        contributor,
                        evidence,
                    ]
                elif sub == 2:
                    values = [
                        label,
                        get(gen),
                        get(use),
                        _join(
                            rows,
                            lambda r: (
                                r["label"]
                                + "；"
                                + _pick(r, "link_evidence", default="未提供衔接证据")
                            ),
                        ),
                    ]
                elif sub == 3:
                    values = [
                        label,
                        seed[1],
                        get(rows),
                        contributor + "；" + _join(rows, _sequence),
                    ]
                elif sub == 4:
                    values = [label, path(rows), contributor, evidence]
                elif sub == 5:
                    values = [label, path(gen), path(use), contributor + "；" + evidence]
                elif sub == 6:
                    values = [label, path(rows), contributor, evidence]
                elif sub == 7:
                    values = [
                        label,
                        _join(rows, lambda r: r["label"] + "：" + r["result_text"]),
                        contributor,
                        _join(rows, lambda r: _pick(r, "evidence_level")),
                    ]
                else:
                    values = [label, path(rows), get(rows), _join(rows, _sequence)]
                result.append(values)
            return result or _missing_rows(block, data)
    if ident == "10.1.t1":
        return [
            [r["label"], r["result_text"], _contributors(r), _pick(r, "evidence_level")]
            for r in _function_rows(data, chapter, sub)
        ] or _missing_rows(block, data)
    if ident == "10.2.t1":
        rows = data.topic_rows(*CHAPTERS[9][3][1][1])
        return [
            [
                "第8章色氨酸结果",
                _pick(r, "association_direction", "feature_summary", default="未提供关联方向"),
                _pick(
                    r,
                    "study_population",
                    "association_evidence_level",
                    default="未提供适用背景与证据",
                ),
            ]
            for r in rows
        ] or _missing_rows(block, data)
    if ident == "11.1.t1":
        rows = data.group("symptom")
        return [
            [
                s[0],
                _join(
                    [
                        r
                        for r in rows
                        if any(
                            w in str(r.get("name", r["label"])).lower()
                            for w in (
                                ("bristol", "粪便类型")
                                if "Bristol" in s[0]
                                else ("frequency", "频率")
                            )
                        )
                    ],
                    lambda r: r["result_text"],
                ),
                _join(rows, lambda r: _pick(r, "source", "questionnaire")),
            ]
            for s in block["rows"][1:]
        ]
    if ident == "11.1.t2":
        rows = data.group("symptom")
        return [
            [
                "本次记录",
                *[
                    _join(
                        [r for r in rows if label in str(r.get("name", r["label"]))],
                        lambda r: r["result_text"],
                    )
                    for label in headers[1:]
                ],
            ]
        ]
    if ident == "12.2.t1":
        return [
            [
                r["label"],
                _pick(v, "species", "name", "feature"),
                _pick(v, "direction"),
                _pick(v, "evidence_level", default=_pick(r, "evidence_level")),
            ]
            for r in data.group("disease")
            for v in data.records(r, "details", "key_species")
        ] or _missing_rows(block, data)
    if ident == "12.3.t1":
        models = data.group("prediction")
        fields = (
            ("intended_use", "endpoint"),
            ("target_population", "exclusion_criteria"),
            ("input_compatibility", "required_features"),
            ("external_validation",),
            ("performance", "uncertainty"),
            ("applicability", "output_definition"),
        )
        return [
            [
                seed[0],
                _join(models, lambda r: _pick(r, *f, default="未提供"))
                if models
                else "未启用：缺少适用验证",
            ]
            for seed, f in zip(block["rows"][1:], fields)
        ]
    if ident == "12.4.t1":
        return [
            [
                r["label"],
                r["result_text"],
                f"{_pick(r, 'output_definition', 'score_definition')}；{_pick(r, 'time_window')}",
            ]
            for r in data.group("prediction")
        ] or [[s[0], "未启用", clean(s[2])] for s in block["rows"][1:]]
    if ident.startswith("14.4."):
        models = valid_composites(data)
        by_name = {r["name"]: r for r in models}
        if ident == "14.4.t1":
            return [
                [
                    str(by_name[n]["value"]) + ("岁" if n == "模型肠龄" else "")
                    if n in by_name
                    else "未启用"
                    for n in headers
                ]
            ]
        fields = {
            "量尺与方向": ("scale_definition",),
            "参考人群与位置": ("reference_population", "percentile"),
            "主要输入": ("inputs", "features"),
            "验证与适用性": ("validation_evidence", "applicability"),
        }
        return [
            [
                s[0],
                *[
                    _pick(by_name[n], *fields[s[0]]) if n in by_name else "未启用"
                    for n in headers[1:]
                ],
            ]
            for s in block["rows"][1:]
        ]
    return _missing_rows(block, data)


def _missing_rows(block, data):
    state = "质控未通过，暂不解读" if data.qc_failed else "未提供"
    # Retain named template dimensions; discard example A/B/C records.
    seeds = [row for row in block["rows"][1:] if row and "【" not in row[0]]
    return [[clean(row[0]), *[state for _ in block["rows"][0][1:]]] for row in seeds] or [
        [state] * len(block["rows"][0])
    ]


def ident_not_special(ident):
    return ident not in {"1.1.t1", "1.2.t1", "2.1.t1", "2.3.t1", "14.2.t1"}


def valid_composites(data):
    return [
        r
        for r in data.raw("composite_models", "models")
        if r.get("externally_validated") is True
        and r.get("applicable") is True
        and r.get("model_version")
        and r.get("scale_definition")
        and r.get("validation_evidence")
        and finite(r.get("value")) is not None
    ]


def tables_for(document, chapter, sub):
    data = Data(document).load(chapter, sub)
    return [
        (b, bind_table(document, b, data))
        for b in contract()["chapters"][chapter - 1]["blocks"]
        if b["type"] == "table" and b["sub"] == sub
    ]


def narrative_sections(document):
    """New model contract: the Word subsections, including newly supported assays."""
    from .document import table
    from .template_body import prepare_presentation

    prepare_presentation(document)
    sections = []
    for chapter, title, _, blocks in CHAPTERS:
        topics = []
        for sub, (heading, ids) in enumerate(blocks, 1):
            data = Data(document).load(chapter, sub)
            scopes = {
                (2, 2): (1, 2),
                (3, 2): (1, 2),
                (3, 4): (1, 2, 3, 4),
                (4, 4): (1, 2, 3, 4),
                (5, 4): (1, 2, 3, 4),
                (6, 4): (1, 2, 3, 4),
                (7, 4): (1, 2, 3, 4),
                (8, 3): (1, 2, 3),
                (8, 8): (6, 7, 8),
                (9, 4): (1, 2, 3, 4),
                (10, 4): (1, 2, 3, 4),
                (11, 3): (1, 2, 3),
                (12, 4): (3, 4),
                (13, 3): (1, 2, 3),
                (14, 3): (1, 2, 3),
            }
            scope = scopes.get((chapter, sub), (sub,))
            ids = tuple(dict.fromkeys(tid for i in scope for tid in blocks[i - 1][1]))
            sample_ids = list(
                dict.fromkeys(
                    k
                    for tid in ids
                    for k in data.topics[tid]["evidence_ids"]
                    if data.evidence[k].get("kind") != "literature"
                )
            )
            allowed = list(
                dict.fromkeys(k for tid in ids for k in data.topics[tid]["allowed_narrative_ids"])
            )
            # Tables from optional assays (strain, virome etc.) need traceable sample observations too.
            observed = []
            for i in scope:
                word_tables = [
                    b
                    for b in contract()["chapters"][chapter - 1]["blocks"]
                    if b["type"] == "table" and b["sub"] == i
                ]
                if word_tables:
                    for b in word_tables:
                        if b["rows"][0][0] in {"解读层次", "引用结果"}:
                            continue
                        rows = bind_table(document, b)

                        def actual(v, index):
                            seed_values = {
                                r[index]
                                for r in b["rows"][1:]
                                if len(r) > index and "【" not in r[index]
                            }
                            return (
                                str(v) not in seed_values
                                and bool(str(v).strip())
                                and not re.search(
                                    r"未提供|未启用|未单独判定|无法判断|质控未通过|缺少适用验证",
                                    str(v),
                                )
                            )

                        if any(
                            any(actual(v, index) for index, v in enumerate(row) if index)
                            for row in rows
                        ):
                            observed.append({"headers": b["rows"][0], "rows": rows})
                else:
                    observed.extend(t for t in Data(document).load(chapter, i).tables if t["rows"])
            if chapter == 14 and sub in {1, 2, 3}:
                sample_ids.extend(r["evidence_id"] for r in document.get("overview_findings", []))
                sample_ids = list(dict.fromkeys(sample_ids))
            if observed and not data.qc_failed:
                key = f"word-observation-{chapter}-{sub}"
                finding = "；".join(table(t["headers"], t["rows"]) for t in observed)
                document["evidence"][key] = {
                    "kind": "word_observation",
                    "measurement_type": "observation",
                    "label": heading,
                    "finding": finding,
                    "comparison": "unknown",
                }
                sample_ids.append(key)
                allowed.append(key)
            focus = [
                b["text"]
                for b in contract()["chapters"][chapter - 1]["blocks"]
                if b["type"] == "paragraph" and b["sub"] == sub and "【" in b["text"]
            ]
            topics.append(
                {
                    "id": f"word.{chapter}.{sub}",
                    "title": heading,
                    "status": "available" if sample_ids and not data.qc_failed else "missing",
                    "evidence_ids": sample_ids,
                    "allowed_narrative_ids": list(dict.fromkeys(sample_ids + allowed)),
                    "finding": "；".join(
                        document["evidence"][k]["finding"] for k in sample_ids[:8]
                    ),
                    "note": "按Word模板的小节结果与证据解读，保留各反应方向和不确定性。",
                    "writing_focus": focus,
                    "interpretation": "",
                    "advice": "",
                    "narrative_source": "rule",
                    "source_subsections": [f"{chapter}.{i}" for i in scope],
                }
            )
        sections.append({"id": f"word.{chapter}", "title": f"{chapter} {title}", "topics": topics})
    return sections


def _narrative(document, chapter, sub):
    key = f"word.{chapter}.{sub}"
    topic = next(
        (t for s in document.get("word_sections", []) for t in s["topics"] if t["id"] == key), None
    )
    if topic and topic.get("interpretation"):
        return topic["interpretation"]
    data = Data(document).load(chapter, sub)
    if data.qc_failed:
        return "本次样本质控未通过，暂不进行健康解读。"
    rows = [r for t in data.tables for r in t["rows"]]
    if not rows and sub == len(CHAPTERS[chapter - 1][3]):
        rows = [
            r
            for i in range(1, sub)
            for t in Data(document).load(chapter, i).tables
            for r in t["rows"]
        ]
    if rows:
        first = rows[0]
        summary = "；".join(str(v) for v in first[:3])
        return f"本次已记录{summary}。其余结果及证据见本节图表；缺少参考或连接支持的项目暂无法进一步判断。"
    return "本次未提供可用于本节解读的对应结果，暂无法判断。"


def paragraph(document, block, chapter):
    s = block["text"].replace("图中位置仅用于版式展示。", "")
    sub = block["sub"]
    if "【" not in s and not s.startswith(("意义解读：", "指标介绍与解读")):
        return s
    if any(s.startswith(p) for p in ("结果解读", "综合解读", "综合指标解读", "所选模块的主要线索")):
        return re.split(r"[ 　]", s, maxsplit=1)[0] + "  " + _narrative(document, chapter, sub)
    if s.startswith("指标介绍与解读"):
        return "指标介绍与解读：Shannon指数同时反映物种丰富度与分布均匀程度。"
    if s.startswith("意义解读"):
        return "意义解读：结合本次物种数和均匀度阅读。参考区间解读：以表中实际采用的人群与方法为准，未建立比较时不判定高低。"
    data = Data(document).load(chapter, sub)
    # Source labels are retained, with explicit per-field bindings (never model-filled numbers).
    bindings = {}
    if chapter == 1 and sub == 2:
        top = sorted(data.group("species"), key=lambda r: -(r.get("value") or 0))
        bindings = {
            "优势物种": top[0]["label"] if top else "未提供",
            "参考核心菌群定义": _pick(data.inputs.get("core_microbiome") or {}, "definition"),
        }
    if chapter == 1 and sub == 3:
        rows = data.group("enterotype")
        s = re.sub(
            r"本次群落组成倾向\s*【[^】]*】",
            lambda m: "本次群落组成倾向  " + _join(rows, lambda r: r["result_text"]),
            s,
        )
    if chapter == 2 and sub == 3:
        block_spec = next(b for b in contract()["chapters"][1]["blocks"] if b.get("id") == "2.3.t1")
        rows = bind_table(document, block_spec, data)
        if s.startswith("功能冗余"):
            return "功能冗余  " + (
                "；".join(f"{r[0]}：贡献菌数{r[1]}" for r in rows[:3])
                if rows
                else "未提供可用分层贡献，无法判断"
            )
        if s.startswith("贡献集中度"):
            return "贡献集中度  " + (
                "；".join(f"{r[0]}：首位贡献菌占比{r[2]}" for r in rows[:3])
                if rows
                else "未提供可用分层贡献，无法判断"
            )
    if (chapter, sub) in {(1, 4), (2, 2)}:
        beta = (data.inputs.get("diversity") or {}).get("community_difference") or {}
        ref = document.get("audit", {}).get("reference_comparison", {}).get("species", {})
        bindings = {
            "参考人群": _pick(
                beta, "reference_population", default=_pick(ref, "reference_population", "source")
            ),
            "样本量": _pick(ref, "n_reference"),
            "匹配条件": _pick(ref, "matching_criteria"),
            "群落差异指标": _pick(beta, "metric"),
            "本次结果": _pick(beta, "result"),
            "分析流程与参考版本": _pick(ref, "reference_version", "reference_file"),
        }
    if chapter == 4 and sub == 3:
        rows = data.raw("virulence", "markers", "genes")
        bindings = {
            "重点致病型": _join(rows, lambda r: _pick(r, "pathotype")),
            "连接依据": _join(rows, lambda r: _linked(r, "host")[1]),
        }
    if chapter == 5 and sub == 3:
        bindings = {
            "连接证据": _join(
                data.group("amr"),
                lambda r: _linked(r, "host")[1] + "；" + _linked(r, "mobile_element")[1],
            )
        }
    if chapter == 7 and sub == 2:
        rows = data.raw("cazy", "families", "clusters")
        bindings = {
            "代表酶家族": _join(rows, lambda r: _pick(r, "family", "name")),
            "相关基因簇": _join(rows, lambda r: _pick(r, "gene_cluster")),
            "底物注释可信度": _join(
                rows, lambda r: _pick(r, "annotation_confidence", "evidence_level")
            ),
        }
    if chapter == 7 and sub == 4:
        rows = data.group("function", "pathway")[:3]
        bindings = {
            "所选功能": _join(rows, lambda r: r["label"]),
            "关键基因与覆盖": _join(rows, _sequence),
            "标准化丰度": _join(rows, lambda r: r["result_text"]),
        }
    if chapter == 9 and sub == 3:
        rows = data.topic_rows(*CHAPTERS[8][3][2][1])
        bindings = {
            "黏蛋白相关酶": _join(rows, lambda r: _pick(r, "gene", "enzyme")),
            "相关通路": _join(rows, lambda r: r["label"]),
            "主要贡献菌": _join(rows, _contributors),
        }
    if chapter == 10 and sub == 3:
        rows = data.topic_rows(*CHAPTERS[9][3][2][1])
        bindings = {
            "去结合等相关功能": _join(rows, lambda r: r["result_text"]),
            "关键标记": _join(rows, lambda r: _pick(r, "gene", "id")),
            "贡献菌": _join(rows, _contributors),
            "证据等级": _join(rows, lambda r: _pick(r, "evidence_level")),
        }
    if chapter == 12 and sub == 3:
        models = data.group("prediction")
        bindings = {
            "所选模型": _join(models, lambda r: r["label"] + "／" + r["model_version"]),
            "本次状态": "已启用" if models else "未启用",
        }
    if chapter == 14 and sub == 4:
        models = valid_composites(data)
        bindings = {
            "综合指标状态": "已验证用途" if models else "未启用",
            "评分与模型版本": _join(models, lambda r: r["model_version"]),
        }
    if data.qc_failed:
        bindings = {k: "质控未通过" for k in bindings}
    for label, value in bindings.items():
        s = re.sub(re.escape(label) + r"\s*【[^】]*】", lambda m: label + str(value), s)
    s = re.sub(r"【[^】]*】(?:%|岁|\[单位/g\])?", "未提供", s)
    # Drop template-only filling directives, retain their substantive explanation.
    s = s.replace("完整分类清单见附录未提供", "完整分类清单见结构化报告").replace(
        "完整序列信息见附录未提供", "完整序列信息见结构化报告"
    )
    s = s.replace("图中位置仅用于版式展示。", "").replace(
        "填写统一的展示口径未提供", "展示口径以已提供的参考分布为准"
    )
    return s


def render_body(document):
    from .document import table
    from .knowledge_graph import graph_markdown

    output = []
    word_figures = document.get("word_figures", {})
    for chapter in contract()["chapters"]:
        n = chapter["number"]
        output.append(f"## {n} {chapter['title']}")
        sub = 0

        def finish(index):
            if not index:
                return
            # A generated subsection interpretation has one visible placement.
            has_slot = any(
                b["type"] == "paragraph"
                and b["sub"] == index
                and b["text"].startswith(
                    ("结果解读", "综合解读", "综合指标解读", "所选模块的主要线索")
                )
                for b in chapter["blocks"]
            )
            topic = next(
                (
                    t
                    for s in document.get("word_sections", [])
                    for t in s["topics"]
                    if t["id"] == f"word.{n}.{index}"
                ),
                {},
            )
            if topic.get("interpretation") and not has_slot:
                output.append("结果解读  " + topic["interpretation"])
            empty_graphs = set()
            for tid in CHAPTERS[n - 1][3][index - 1][1]:
                topic = next(t for s in document["sections"] for t in s["topics"] if t["id"] == tid)
                if topic["status"] != "missing":
                    for part in graph_markdown(topic):
                        if topic.get("knowledge_subgraph", {}).get("status") == "no_match":
                            if part in empty_graphs:
                                continue
                            empty_graphs.add(part)
                        output.append(part)

        for block in chapter["blocks"]:
            kind = block["type"]
            if kind == "heading":
                finish(sub)
                sub = block["sub"]
                output.append("### " + block["text"])
            elif kind == "paragraph":
                # Optional quantitative panel is removed exactly as instructed in the Word.
                if (
                    n == 1
                    and sub == 4
                    and block["text"]
                    in {
                        "绝对丰度补充结果",
                        "仅在具有总菌量实测或其他经验证的定量结果时启用；无对应数据时删除本栏。",
                    }
                ):
                    if not _rows(
                        Data(document).load(1, 4), ["定量项目", "本次结果", "测量或估算依据"]
                    ):
                        continue
                output.append(paragraph(document, block, n))
            elif kind == "table":
                rows = bind_table(document, block)
                if block["id"] == "1.4.t2" and not _rows(
                    Data(document).load(1, 4), block["rows"][0]
                ):
                    continue
                output.append(table(block["rows"][0], rows))
                if n == 8:
                    data = Data(document).load(n, sub)
                    measured = [
                        t
                        for t in data.tables
                        if t["headers"] == ["项目", "本次结果", "来源类型", "参考比较"]
                    ]
                    for t in measured:
                        output.extend(
                            ["**已有代谢物检测或模型记录**", table(t["headers"], t["rows"])]
                        )
            elif kind == "visuals":
                key = "+".join(v["id"] for v in block["items"])
                image = word_figures.get(key)
                if image:
                    output.append(f"![{n}.{block['sub']} 模板图示]({image['filename']})")
                else:
                    output.append("图示数据状态：本次尚未渲染，图表布局见PDF报告。")
        finish(sub)
    return output
