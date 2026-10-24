"""Data-backed body for the supplied chapter 03–16 templates.

No template placeholders, invented reference distributions, inferred gene hosts,
or synthetic illustrations are emitted. Legacy subgraphs are rendered unchanged.
"""

from __future__ import annotations

import math
import re

from .inputs import finite
from .overview import RULE_VERSION, select_findings
from .template_catalog import CHAPTERS, TEMPLATE_VERSION, TOPIC_PLACEMENT


def _pick(row: dict, *keys, default="未提供"):
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            if isinstance(value, (list, tuple)):
                return "；".join(str(v) for v in value)
            if isinstance(value, dict):
                return "；".join(f"{k}：{v}" for k, v in value.items())
            return {True: "是", False: "否"}.get(value, value) if isinstance(value, bool) else value
    return default


def _sequence(row):
    fields = (
        ("reads", "支持读段"),
        ("read_count", "支持读段"),
        ("coverage", "覆盖"),
        ("breadth", "覆盖广度"),
        ("identity", "相似性"),
        ("similarity", "相似性"),
        ("completeness", "完整性"),
    )
    summary = _pick(row, "sequence_support", "sequence_evidence", "evidence_summary", default="")
    details = [f"{label} {row[key]}" for key, label in fields if row.get(key) is not None]
    return "；".join(([str(summary)] if summary else []) + details) or "未提供序列支持摘要"


def _detection(row):
    value = _pick(row, "detection_status", "detected", default=None)
    if value is not None:
        return {
            "是": "检出",
            "否": "本次未检出",
            "detected": "检出",
            "not_detected": "本次未检出",
            "positive": "检出",
            "negative": "本次未检出",
            "insufficient_coverage": "覆盖不足无法判断",
        }.get(value, value)
    abundance = finite(row.get("value", row.get("abundance")))
    if abundance is not None:
        return "检出" if abundance > 0 else "本次记录为零；检出限未提供"
    return _pick(row, "result", "status", default="覆盖不足无法判断")


def _contributors(row):
    direct = _pick(row, "contributing_taxa", "contributor", default="")
    if direct:
        return direct
    values = row.get("contributors")
    if not isinstance(values, list) or not values:
        return "未提供分层贡献"
    result = []
    for value in values[:4]:
        if isinstance(value, dict):
            name = _pick(value, "taxon", "species", "name")
            amount = finite(value.get("abundance"))
            result.append(
                str(name)
                + (f"（{amount:.5g} {value.get('unit', '')}）" if amount is not None else "")
            )
    return "；".join(result) or "未提供分层贡献"


def _quantity(row, parent=None):
    parent = parent if isinstance(parent, dict) else {}
    value = finite(row.get("value", row.get("abundance")))
    if value is None:
        return _pick(row, "result", "answer")
    unit = row.get("unit", parent.get("unit", "单位未提供"))
    return f"{value:.5g} {unit}"


def _linked(row, entity):
    # Co-occurrence, organism names and knowledge-graph edges are not sequence linkage.
    supported = row.get(f"{entity}_link_supported") is True
    proof = _pick(row, f"{entity}_link_evidence", default="")
    if row.get("sequence_link_target") == entity:
        supported = supported or row.get("sequence_link_supported") is True
        proof = proof or _pick(row, "link_evidence", "sequence_link", default="")
    if supported and proof:
        return _pick(row, entity, f"{entity}_name", default="已支持；名称未提供"), proof
    return "宿主未确定" if entity == "host" else "遗传背景未确定", "未获得对应序列连接支持"


class Body:
    def __init__(self, document):
        from .document import number, records, table

        self.doc, self.evidence = document, document["evidence"]
        self.inputs = document.get("template_inputs", {})
        self.topics = {t["id"]: t for s in document["sections"] for t in s["topics"]}
        self.number, self.records, self.table = number, records, table
        self.qc_failed = str(document.get("metadata", {}).get("qc_status", "")).lower() in {
            "failed",
            "fail",
            "不通过",
            "未通过",
        }
        self.out = []

    def group(self, *names):
        return (
            [] if self.qc_failed else [r for r in self.evidence.values() if r.get("kind") in names]
        )

    def topic_rows(self, *ids):
        keys = dict.fromkeys(
            k
            for tid in ids
            for k in self.topics.get(tid, {}).get("evidence_ids", [])
            if self.topics.get(tid, {}).get("status") != "missing"
        )
        return [] if self.qc_failed else [self.evidence[k] for k in keys]

    def raw(self, module, *keys):
        return [] if self.qc_failed else self.records(self.inputs.get(module), *keys)

    def emit(self, headers, rows, missing="本次未提供对应数据，无法判断。", limit=8):
        if rows:
            self.out.append(self.table(headers, rows[:limit]))
            if len(rows) > limit:
                self.out.append(
                    f"本表展示前 {limit} 项，共 {len(rows)} 项；完整明细保存在结构化报告。"
                )
        else:
            self.out.append("本次样本质控未通过，暂不进行健康解读。" if self.qc_failed else missing)

    def standard(self, rows):
        self.emit(
            ["功能或项目", "本次结果", "参考比较", "主要贡献菌与证据"],
            [
                [
                    r["label"],
                    r["result_text"],
                    r["reference_text"],
                    f"{_contributors(r)}；{_sequence(r)}",
                ]
                for r in rows
            ],
        )

    def functions(self, words):
        def matches(row):
            name = " ".join(
                str(row.get(k, "")) for k in ("name", "id", "annotation", "gene", "gene_family")
            ).lower()
            return any(
                re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", name)
                if w.isascii() and len(w) < 5
                else w in name
                for w in words
            )

        return [r for r in self.group("function", "pathway") if matches(r)]

    def extra(self, module, headers, columns, *keys, missing="本次未提供对应专项结果，无法判断。"):
        rows = self.raw(module, *keys)
        self.emit(headers, [[_pick(r, *fields) for fields in columns] for r in rows], missing)


    def composition(self, block):
        species = self.group("species")
        if block == 1:
            ranks = (
                ("门", "tax_phylum"),
                ("纲", "tax_class"),
                ("目", "tax_order"),
                ("科", "tax_family"),
                ("属", "tax_genus"),
                ("种", "species"),
            )
            for label, group in ranks:
                rows = sorted(self.group(group), key=lambda r: -(r.get("value") or 0))
                if rows:
                    self.out.append(f"**{label}水平组成**")
                    self.emit(
                        ["分类层级", "主要类群", "相对丰度"],
                        [[label, r["label"], r["result_text"]] for r in rows],
                    )
            if not any(self.group(group) for _, group in ranks):
                self.emit([], [], "本次未提供可用分类组成结果。")
            self.out.append("未提供的分类层级不从下级条目拼接估算；完整分类清单见结构化报告。")
        elif block == 2:
            positive = sorted(
                [r for r in species if (r.get("value") or 0) > 0], key=lambda r: -r["value"]
            )
            rows = []
            if positive:
                rows.append(["丰度最高的物种", positive[0]["label"]])
                rows.append(["第一优势物种占比", positive[0]["result_text"]])
            rows.extend([[r["label"], r["result_text"]] for r in self.group("dominance")])
            self.emit(["组成指标", "本次结果"], rows)
            module = self.inputs.get("core_microbiome") or {}
            core = self.raw("core_microbiome", "members")
            if core and isinstance(module, dict) and module.get("definition"):
                by_name = {str(r.get("species", r["label"])).casefold(): r for r in species}
                core = [
                    {**by_name.get(str(_pick(r, "species", "name")).casefold(), {}), **r}
                    for r in core
                ]
                self.out.append("参考核心菌群定义：" + str(module["definition"]))
                self.emit(
                    ["参考核心成员", "检出状态", "相对丰度", "备注"],
                    [
                        [
                            _pick(r, "species", "name"),
                            _detection(r),
                            _quantity(r, module),
                            _pick(r, "note"),
                        ]
                        for r in core
                    ],
                )
                known = [r for r in core if finite(r.get("value", r.get("abundance"))) is not None]
                if len(known) == len(core) and len(
                    {str(_pick(r, "species", "name")).casefold() for r in core}
                ) == len(core):
                    count = sum(finite(r.get("value", r.get("abundance"))) > 0 for r in known)
                    self.out.append(f"核心成员检出数 / 参考成员数：{count} / {len(core)}。")
                    if all(r.get("unit", module.get("unit")) == "%" for r in known):
                        total = math.fsum(finite(r.get("value", r.get("abundance"))) for r in known)
                        self.out.append(f"检出核心成员合计相对丰度：{total:.5g}%。")
                else:
                    self.out.append(
                        f"参考成员数：{len(core)}；部分成员缺少可核对的检出记录，不填补未检出或合计丰度。"
                    )
            else:
                self.out.append("本次未提供参考核心菌群定义及成员清单，核心成员检出率未启用。")
        elif block == 3:
            rows = self.group("enterotype")
            values = []
            for r in rows:
                values.extend(
                    [
                        ["群落组成倾向", r["result_text"]],
                        ["主要支持类群", _pick(r, "supporting_taxa", "dominant_genera")],
                        [
                            "分类方法与版本",
                            f"{_pick(r, 'method')}；{_pick(r, 'version', 'model_version')}",
                        ],
                        [
                            "判定稳定性或不确定性",
                            _pick(r, "uncertainty", "stability", default="未提供"),
                        ],
                    ]
                )
            self.emit(["判读项目", "填写内容"], values, "本次未提供肠型判定结果，无法归类。")
            self.out.append("肠型用于描述群落组成特征。")
        else:
            rows = [r for r in species if r.get("comparison") in {"above", "below", "within"}]
            rows.sort(key=lambda r: (r["comparison"] == "within", -(r.get("value") or 0)))
            self.emit(
                ["重点物种", "本次丰度", "参考区间", "人群分位数", "比较结果"],
                [
                    [
                        r["label"],
                        r["result_text"],
                        r["reference_text"],
                        _pick(r, "percentile"),
                        {"above": "高于参考", "below": "低于参考", "within": "区间内"}[
                            r["comparison"]
                        ],
                    ]
                    for r in rows
                ],
                "本次没有可用的物种参考比较，不能判定偏高或偏低。",
            )
            reference = self.doc.get("audit", {}).get("reference_comparison", {})
            details = reference.get("species", {})
            if details:
                self.out.append(
                    "参考人群与版本："
                    + str(
                        _pick(
                            details,
                            "reference_version",
                            "source",
                            "reference_file",
                            default="沿用分析记录；人群与版本详见证据文件",
                        )
                    )
                )
            # Optional absolute quantities require an actual validated quantitative basis.
            absolute = [
                r
                for r in self.raw("absolute_abundance", "measurements")
                if r.get("unit")
                and r.get("method")
                and (r.get("data_type") == "measured" or r.get("validated_quantification") is True)
                and finite(r.get("value")) is not None
            ]
            if absolute:
                self.out.append("**绝对丰度补充结果**")
                self.emit(
                    ["定量项目", "本次结果", "测量或估算依据"],
                    [
                        [
                            _pick(r, "name", "species"),
                            f"{self.number(r['value'])} {r['unit']}",
                            r["method"],
                        ]
                        for r in absolute
                    ],
                )

    def diversity(self, block):
        if block == 1:
            rows = self.group("div_richness", "div_shannon", "div_simpson", "div_evenness")
            refs = self.group("div_reference")

            def match(r):
                metric = r["kind"].removeprefix("div_")
                return next((v for v in refs if str(v.get("metric", "")).lower() == metric), r)

            self.emit(
                ["多样性指标", "本次结果", "参考区间", "人群分位数"],
                [
                    [
                        r["label"],
                        r["result_text"],
                        match(r)["reference_text"],
                        _pick(match(r), "percentile"),
                    ]
                    for r in rows
                ],
            )
            estimate = self.inputs.get("diversity") or {}
            if isinstance(estimate, dict) and finite(estimate.get("richness_estimate")) is not None:
                self.out.append(
                    "丰富度估计："
                    + self.number(estimate["richness_estimate"])
                    + "；方法："
                    + str(_pick(estimate, "richness_method"))
                )
            self.out.append(
                "Shannon 指数同时反映丰富度与均匀度；仅在相同分析口径和适用参考人群下比较，不设置通用健康分界值。"
            )
        elif block == 2:
            self.standard(self.group("div_reference"))
            self.out.append(
                "人群内的多样性位置与群落组成距离分别解释；未提供群落差异指标或匹配参考时，不补算群落距离。"
            )
            beta = (self.inputs.get("diversity") or {}).get("community_difference")
            if isinstance(beta, dict) and beta.get("result") is not None:
                self.emit(
                    ["参考人群", "群落差异指标", "本次结果", "方法与版本"],
                    [
                        [
                            _pick(beta, "reference_population"),
                            _pick(beta, "metric"),
                            beta["result"],
                            _pick(beta, "method", "version"),
                        ]
                    ],
                )
        elif block == 3:
            rows = []
            for row in self.group("pathway", "function"):
                contributors = row.get("contributors")
                if not isinstance(contributors, list):
                    continue
                valid = [
                    v
                    for v in contributors
                    if isinstance(v, dict)
                    and finite(v.get("abundance")) is not None
                    and finite(v["abundance"]) > 0
                ]
                # Missing contributors or mixed units do not establish a denominator.
                if not valid or len({v.get("unit", row.get("unit")) for v in valid}) != 1:
                    continue
                total = math.fsum(finite(v["abundance"]) for v in valid)
                count = len({str(_pick(v, "taxon", "species", "name")) for v in valid})
                complete = row.get("contributors_complete") is True
                share = (
                    f"{max(finite(v['abundance']) for v in valid) / total * 100:.4g}%"
                    if complete
                    else "分层贡献完整性未确认，暂不计算"
                )
                rows.append(
                    [
                        row["label"],
                        f"已记录 {count} 个",
                        share,
                        _pick(row, "contribution_percentile"),
                    ]
                )
            for row in self.raw("functional_redundancy"):
                rows.append(
                    [
                        _pick(row, "name", "function"),
                        _pick(row, "contributor_count"),
                        _pick(row, "top_contributor_share"),
                        _pick(row, "percentile"),
                    ]
                )
            self.emit(
                ["功能项目", "贡献菌数", "首位贡献菌占比", "人群分位数"],
                rows,
                "本次未提供可用的分层贡献或功能冗余结果，无法判断。",
            )
            self.out.append(
                "贡献菌数描述已记录的功能分工，不直接代表生态恢复力；贡献集中度不在分层贡献不完整时推算。"
            )
        else:
            self.extra(
                "metabolic_cooperation",
                ["功能环节", "主要贡献菌", "关键功能或产物", "连接证据"],
                [
                    ("stage",),
                    ("contributors", "taxon"),
                    ("function", "product"),
                    ("link_evidence", "evidence"),
                ],
                "stages",
            )
            self.out.append("本栏描述潜在功能协作，不直接代表实际菌间相互作用或生态恢复力。")

    def key_taxa(self, block):
        if block in (1, 2):
            ids = (
                (
                    "key_taxa.bifidobacteria",
                    "key_taxa.lactic_acid",
                    "key_taxa.butyrate",
                    "key_taxa.mucin",
                )
                if block == 1
                else ("key_taxa.opportunists", "key_taxa.pathogens")
            )
            self.emit(
                ["微生物名称", "功能或关注背景", "检出状态", "相对丰度", "人群分位数"],
                [
                    [
                        r["label"],
                        _pick(
                            r,
                            "functional_background",
                            "attention_note",
                            "annotation",
                            default="具体物种及菌株背景需结合证据解释",
                        ),
                        _detection(r),
                        r["result_text"],
                        _pick(r, "percentile"),
                    ]
                    for r in self.topic_rows(*ids)
                ],
            )
            self.out.append("展示层级为所列具体分类单元；未列出的成员不据此判定未检出。")
        elif block == 3:
            self.emit(
                ["重点结果", "序列支持摘要", "检出可信度", "关联证据等级"],
                [
                    [
                        r["label"],
                        _sequence(r),
                        _pick(r, "detection_confidence", default="未提供，无法判断"),
                        _pick(r, "association_evidence_level", "evidence_level"),
                    ]
                    for r in self.topic_rows("key_taxa.opportunists", "key_taxa.pathogens")
                ],
            )
            self.out.append("检出可信度与健康关联证据分别报告；知识图谱关系不替代本次序列支持。")
        else:
            self.emit(
                ["解读层次", "本次可支持的结论", "补充依据或信息"],
                [
                    [
                        "物种层面",
                        "以本章检出与丰度记录为依据"
                        if self.group("species", "pathogen")
                        else "无可用记录",
                        "具体物种、适用人群及关联文献",
                    ],
                    [
                        "菌株层面",
                        "见第4章；缺少谱系及序列连接支持时无法判断",
                        "宿主归属及序列连接证据",
                    ],
                    ["感染层面", "本报告不能仅凭物种检出判断感染", "症状、临床检查及复核信息"],
                ],
            )
            self.out.append(
                "物种检出不直接等于感染；健康相关性结合具体物种、菌株与情境解读，不统一标记为有益或有害。"
            )

    def strains(self, block):
        if block == 1:
            self.extra(
                "strains",
                ["重点微生物", "可分析层级", "本次结果", "证据状态"],
                [
                    ("species", "name"),
                    ("analysis_level", "level"),
                    ("result", "lineage", "strain"),
                    ("evidence_status", "confidence"),
                ],
                "strains",
                "lineages",
            )
        elif block == 2:
            rows = self.raw("virulence", "markers", "genes")
            self.emit(
                ["功能类别", "关键标记或基因簇", "检出与完整性", "证据摘要"],
                [
                    [
                        _pick(r, "category", "function"),
                        _pick(r, "gene", "marker", "name"),
                        _detection(r),
                        _sequence(r),
                    ]
                    for r in rows
                ],
                "本次未提供毒力标记专项检测结果，无法判断。",
            )
        elif block == 3:
            rows = self.raw("virulence", "markers", "genes")
            self.emit(
                ["重点标记或致病型", "微生物宿主", "序列连接证据"],
                [
                    [_pick(r, "pathotype", "gene", "marker", "name"), *_linked(r, "host")]
                    for r in rows
                ],
            )
        else:
            self.emit(
                ["重点标记", "微生物宿主归属", "序列支持摘要"],
                [
                    [_pick(r, "gene", "marker", "name"), _linked(r, "host")[0], _sequence(r)]
                    for r in self.raw("virulence", "markers", "genes")
                ],
            )
            self.out.append(
                "缺少连接证据时，标记与物种分别报告；基因检出不直接代表表达、产毒或实际感染。"
            )

    def resistance(self, block):
        rows = self.group("amr")
        if block == 1:
            self.emit(
                ["基因 家族或突变", "检出状态", "序列证据", "注释等级"],
                [
                    [
                        r["label"],
                        _detection(r),
                        _sequence(r),
                        _pick(r, "annotation_level", "evidence_level"),
                    ]
                    for r in rows
                ],
                "本次未提供耐药决定因素检测结果，未启用。",
            )
        elif block == 2:
            self.emit(
                ["对应类别", "主要耐药机制", "代表决定因素", "结果与人群位置"],
                [
                    [
                        _pick(r, "drug_class"),
                        _pick(r, "mechanism"),
                        r["label"],
                        f"{r['result_text']}；{r['reference_text']}",
                    ]
                    for r in rows
                ],
            )
            self.out.append(
                "丰度按各条目原有单位呈现；一个标记可对应多个药物类别，不跨类别直接相加为总量。"
            )
        elif block == 3:
            self.emit(
                ["耐药决定因素", "可能宿主", "可移动遗传元件", "各连接证据"],
                [
                    [
                        r["label"],
                        _linked(r, "host")[0],
                        _linked(r, "mobile_element")[0],
                        f"宿主：{_linked(r, 'host')[1]}；元件：{_linked(r, 'mobile_element')[1]}",
                    ]
                    for r in rows
                ],
            )
            self.extra(
                "mobile_elements",
                ["元件标记", "本次结果", "序列支持", "连接对象"],
                [
                    ("name", "marker"),
                    ("result",),
                    ("sequence_support", "evidence"),
                    ("linked_marker",),
                ],
                "elements",
                missing="本次未提供独立的可移动遗传元件检测结果。",
            )
        else:
            self.out.append(
                "本栏描述耐药相关序列，不等同于药敏试验或个体用药效果；不直接给出抗生素选择结论。"
            )

    def other_microbes(self, block):
        module = {1: "archaea", 2: "fungi", 3: "dna_viruses"}.get(block)
        if module:
            rows = self.raw(module, "members", "species", "viruses")
            if block == 3:
                self.emit(
                    ["重点成员或类别", "检出状态", "基因组质量", "微生物宿主关联"],
                    [
                        [
                            _pick(r, "name", "species"),
                            _detection(r),
                            _pick(r, "genome_quality", "completeness"),
                            _linked(r, "host")[0],
                        ]
                        for r in rows
                    ],
                    "本次未提供DNA病毒组专项结果，无法判断。",
                )
            else:
                if not rows:
                    kingdom = "k__Archaea" if module == "archaea" else "k__Fungi"
                    rows = [
                        r for r in self.group("species") if kingdom in str(r.get("lineage", ""))
                    ]
                self.emit(
                    ["重点成员", "检出状态", "相对丰度", "功能或检测能力说明"],
                    [
                        [
                            _pick(r, "name", "species"),
                            _detection(r),
                            _quantity(r, self.inputs.get(module)),
                            _pick(r, "methane_markers", "detection_scope", "sequence_support"),
                        ]
                        for r in rows
                    ],
                    "本次未提供对应专项结果，不能由细菌组成推断。",
                )
                if module == "archaea":
                    self.out.append(
                        "古菌分类检出与产甲烷标记分别报告；未提供甲烷代谢标记时不由分类名称推算产甲烷能力。"
                    )
        else:
            self.out.append(
                "各类别分别使用其检测条件；本次检测能力内未检出与覆盖不足无法判断分别解释。普通DNA宏基因组不覆盖完整RNA病毒组；三类微生物的类内组成不用于比较总量。"
            )

    def nutrients(self, block):
        if block == 1:
            self.standard(
                self.topic_rows("nutrient_metabolism.carbohydrate", "nutrient_metabolism.fiber")
            )
            self.out.append(
                "抗性淀粉、果胶、菊粉和木聚糖分别按具体底物注释报告；底物特异性支持不足时，仅保留酶家族或通路层级。"
            )
        elif block == 2:
            self.extra(
                "cazy",
                ["代表酶家族", "相关基因簇", "底物注释", "注释可信度"],
                [
                    ("family", "name"),
                    ("gene_cluster",),
                    ("substrate",),
                    ("annotation_confidence", "evidence_level"),
                ],
                "families",
                "clusters",
            )
        elif block == 3:
            rows = self.topic_rows(
                "nutrient_metabolism.amino_acid",
                "nutrient_metabolism.lipid",
                "nutrient_metabolism.vitamin",
                "nutrient_metabolism.nucleotide",
            )
            self.emit(
                ["功能类别或路径", "合成潜力", "降解潜力", "主要贡献菌"],
                [
                    [
                        r["label"],
                        _pick(r, "synthesis_result", default="未单独判定"),
                        _pick(r, "degradation_result", default="未单独判定"),
                        _contributors(r),
                    ]
                    for r in rows
                ],
            )
            if rows:
                self.out.append("**已有通路结果**")
                self.standard(rows)
            self.out.append(
                "蛋白质及氨基酸、脂质、维生素与辅酶、嘌呤与嘧啶按具体反应方向分别解释，不由通路名称自动填补合成或降解结果。"
            )
        else:
            self.out.append(
                "关键标记、覆盖、标准化丰度及分层贡献按已有注释呈现。功能潜力不直接代表实际摄入、消化吸收效果或个人营养状态。"
            )

    def metabolism(self, block, topic_ids):
        rows = self.topic_rows(*topic_ids)
        extra_words = {
            1: ("acetate", "propionate", "butyrate", "乙酸", "丙酸", "丁酸"),
            2: ("lactate", "succinate", "乳酸", "琥珀酸"),
            3: ("bsh", "bai", "bile acid", "bile salt", "胆汁酸", "脱结合", "脱羟基"),
            4: ("indole", "tryptophan", "吲哚", "色氨酸"),
            5: (
                "cresol",
                "histamine",
                "putrescine",
                "cadaverine",
                "对甲酚",
                "组胺",
                "腐胺",
                "尸胺",
            ),
            6: (
                "methanogenesis",
                "hydrogen",
                "sulfate reduction",
                "产氢",
                "耗氢",
                "甲烷",
                "硫化氢",
            ),
            7: ("tma", "trimethylamine", "cutc", "cnta", "三甲胺"),
            8: ("lipopolysaccharide", "脂多糖", "lipid a", "peptidoglycan", "肽聚糖"),
        }
        rows = list({id(r): r for r in rows + self.functions(extra_words[block])}.values())
        if block in {1, 2}:
            # Named aromatic derivatives are distinct targets, not the plain
            # acetate/propionate/lactate intermediates embedded in their names.
            rows = [
                r
                for r in rows
                if not any(
                    word in str(r.get("name", r.get("label", ""))).lower()
                    for word in ("indole", "imidazole", "phenyl", "吲哚", "咪唑", "苯基")
                )
            ]
        potential = [r for r in rows if r.get("measurement_type") == "functional_potential"]
        self.emit(
            ["产物或功能分支", "反应方向", "本次功能结果", "主要贡献菌与证据"],
            [
                [
                    r["label"],
                    _pick(
                        r,
                        "reaction_direction",
                        "direction",
                        default="以所列路径注释为准；方向未单独验证",
                    ),
                    r["result_text"],
                    f"{_contributors(r)}；{_sequence(r)}",
                ]
                for r in potential
            ],
            "本次未提供该方向的测序功能结果，无法判断。",
        )
        other = [r for r in rows if r.get("measurement_type") != "functional_potential"]
        if other:
            from .document import TYPE_LABELS

            self.out.append("**已有代谢物检测或模型记录**")
            self.emit(
                ["项目", "本次结果", "来源类型", "参考比较"],
                [
                    [
                        r["label"],
                        r["result_text"],
                        TYPE_LABELS[r["measurement_type"]],
                        r["reference_text"],
                    ]
                    for r in other
                ],
            )
        notes = {
            1: "乙酸、丙酸、丁酸分别解释；不同路径的比例不用于比较实际产量。",
            2: "乳酸与琥珀酸的生成、后续利用分别报告；未提供反应方向时不推算周转或积累。",
            3: "脱结合（BSH相关）与7α脱羟基（bai相关）是不同分支；不以次级胆汁酸名称替代基因标记。",
            4: "吲哚、吲哚乳酸、吲哚丙酸分别解释；肠脑轴关联解读见第10章。",
            5: "对甲酚、组胺、腐胺、尸胺分别按生成与利用路径解释；不以两条路径丰度相减推算净生成量。",
            6: "产氢、耗氢、产甲烷与硫化氢生成分别解释，不由基因丰度换算排气量或症状强度。",
            7: "胆碱与肉碱相关路径分别报告；TMA生成潜力不直接代表TMA或TMAO实际水平。",
            8: "基因证据不直接代表内毒素活性，不用于推算其他分子的实际水平。",
        }
        self.out.append(notes[block])

    def ecology(self, block, topic_ids):
        rows = self.topic_rows(*topic_ids)
        if block == 1:
            self.emit(
                ["相关维度", "代表证据", "本次结果", "证据等级"],
                [
                    [
                        _pick(r, "dimension", "label"),
                        _pick(r, "gene", "id", "name"),
                        r["result_text"],
                        _pick(r, "evidence_level"),
                    ]
                    for r in rows
                ],
            )
        elif block == 2:
            self.emit(
                ["相关特征", "关联方向", "适用背景", "证据等级"],
                [
                    [
                        r["label"],
                        _pick(r, "association_direction", default="未提供"),
                        _pick(r, "study_population", "applicable_context"),
                        _pick(r, "association_evidence_level", "evidence_level"),
                    ]
                    for r in rows
                ],
            )
            if rows:
                self.standard(rows)
        elif block == 3:
            self.standard(rows)
        else:
            self.emit(
                ["引用结果", "与本章的联系", "本次可解释范围"],
                [
                    [
                        "第7章底物利用",
                        "与宿主底物和微生物资源利用相关",
                        "仅解释已提供的底物及通路注释",
                    ],
                    ["第8章代谢功能", "与微生物代谢环境相关", "功能潜力不等同于屏障或免疫实测"],
                ],
            )
            if rows:
                self.standard(rows)
        notes = {
            1: "底物竞争、代谢环境和抑菌功能是定植抗力的关联线索，未据此计算定植抗力分。",
            2: "关联方向、适用人群及研究背景需有对应文献；未提供时不补写炎症或免疫结论。",
            3: "结合黏蛋白相关酶、通路完整性与生态背景解读，不将相关酶检出直接等同于屏障损伤。",
            4: "综合引用第7章底物利用和第8章代谢功能，不重复计分，也不直接给出屏障、免疫或抗炎能力分。",
        }
        self.out.append(notes[block])

    def brain(self, block, topic_ids):
        if block == 4:
            self.emit(
                ["背景信息", "本次填写", "来源与时间"],
                [
                    [
                        _pick(r, "name", "domain"),
                        _quantity(r),
                        f"{_pick(r, 'source', 'scale')}；{_pick(r, 'date')}",
                    ]
                    for r in self.raw("scales")
                ],
                "睡眠、压力和情绪量表未提供。",
            )
            self.out.append("量表结果与测序结果分开解释；菌群基因不直接换算脑内递质或激素水平。")
        else:
            self.standard(self.topic_rows(*topic_ids))
            if block == 2:
                self.out.append(
                    "色氨酸各产物方向引用第8.4节基础结果，关联解释不替代生成路径测定。"
                )
            if block == 3:
                self.out.append("去结合等微生物转化功能与宿主激素水平分别解释。")

    def symptoms(self, block, topic_ids):
        if block == 1:
            rows = self.topic_rows(*topic_ids)
            self.emit(
                ["排便或症状项目", "本次记录", "信息来源与时间"],
                [
                    [
                        r["label"],
                        r["result_text"],
                        f"{_pick(r, 'source', 'questionnaire', 'method')}；{_pick(r, 'date', 'recorded_at')}",
                    ]
                    for r in rows
                ],
                "Bristol粪便类型、排便频率及便秘、腹泻、腹胀、排气、腹痛记录未提供。",
            )
        elif block == 2:
            module = self.inputs.get("symptoms")
            comparisons = (
                []
                if self.qc_failed or not isinstance(module, dict)
                else self.records(module.get("functional_comparisons"))
            )
            self.emit(
                ["功能方向", "测序结果摘要", "对应症状", "关联证据"],
                [
                    [
                        _pick(r, "function"),
                        _pick(r, "sequencing_result"),
                        _pick(r, "symptom"),
                        _pick(r, "association_evidence"),
                    ]
                    for r in comparisons
                ],
                "本次未提供可核对的症状与功能对应证据，不依据菌群自动推断症状。",
            )
            self.out.append("功能对照引用第8章的产气与耗气、乳酸利用、蛋白发酵及胆汁酸转化结果。")
        else:
            self.out.append(
                "症状记录、测序结果及研究关联分别解释；关联方向不直接代表个体症状的原因。没有症状信息时显示未提供。"
            )

    def diseases(self, block, topic_ids):
        if block == 1:
            self.emit(
                ["关联模块", "是否启用", "目标用途或适用人群", "结果类型"],
                [
                    [
                        r["label"],
                        "已提供关联记录",
                        _pick(r, "target_population", "intended_use"),
                        "研究性关联",
                    ]
                    for r in self.group("disease")
                ],
                "本次未提供疾病研究关联模块。",
            )
        elif block == 2:
            self.standard(self.topic_rows(*topic_ids))
            details = [
                [r["label"], r["feature_summary"]]
                for r in self.group("disease")
                if r.get("feature_summary")
            ]
            if details:
                self.emit(["所选模块", "关联特征及方向"], details)
            self.out.append(
                "文献效应、研究人群及证据等级按已有来源解释；关联菌数量和启发式关联分不换算为患病概率。"
            )
        elif block == 3:
            self.emit(
                ["所选模型与版本", "目标用途与适用人群", "外部验证", "性能与不确定性"],
                [
                    [
                        f"{r['label']}／{r['model_version']}",
                        f"{_pick(r, 'intended_use', 'endpoint')}；{_pick(r, 'target_population')}",
                        _pick(
                            r,
                            "external_validation",
                            default="上游声明已通过外部验证；验证详情未提供",
                        ),
                        _pick(r, "performance", "uncertainty"),
                    ]
                    for r in self.group("prediction")
                ],
                "模型未启用：本次没有同时满足外部验证、样本适用性及版本条件的模型。",
            )
        else:
            self.emit(
                ["输出项目", "本次结果", "结果含义与时间窗"],
                [
                    [
                        r["label"],
                        r["result_text"],
                        f"{_pick(r, 'output_definition', 'score_definition')}；{_pick(r, 'time_window')}",
                    ]
                    for r in self.topic_rows(*topic_ids)
                ],
                "模型结果未启用；缺少适用验证的模块仅保留研究性关联。",
            )
            self.out.append(
                "分类分值、当前状态识别和未来发病概率分别解释；仅在对应终点及时间窗的验证支持时报告预测概率。"
            )

    def specialized(self, block):
        module = self.inputs.get("specialized_metabolism") or {}
        key = {1: "dietary", 2: "drugs", 3: "validation"}[block]
        rows = (
            [] if self.qc_failed or not isinstance(module, dict) else self.records(module.get(key))
        )
        columns = {
            1: (
                ["专项底物", "路径或酶证据", "主要贡献菌", "本次功能结果"],
                [("substrate", "name"), ("pathway", "enzyme"), ("contributors",), ("result",)],
            ),
            2: (
                ["专项项目", "已知酶或序列变异", "本次序列支持", "适用用药背景"],
                [
                    ("name", "drug"),
                    ("enzyme", "variant"),
                    ("sequence_support",),
                    ("medication_background",),
                ],
            ),
            3: (
                ["专项项目", "路径注释证据", "健康关联或应用证据", "报告用途"],
                [("name",), ("annotation_evidence",), ("application_evidence",), ("intended_use",)],
            ),
        }
        headers, fields = columns[block]
        self.emit(
            headers,
            [[_pick(r, *f) for f in fields] for r in rows],
            "本次未提供对应专项代谢转化结果，未启用。",
        )
        if block == 3:
            self.out.append("功能潜力不直接代表体内转化量；本栏不直接输出药物剂量或疗效结论。")

    def synthesis(self, block):
        findings = self.doc["overview_findings"]
        if block == 1:
            from .document import TYPE_LABELS

            self.emit(
                ["优先级", "本次发现", "证据充分程度", "实际相关性"],
                [
                    [
                        r["priority"],
                        f"{r['finding']}（第{r['source']}节）",
                        TYPE_LABELS.get(r["evidence_type"], r["evidence_type"]),
                        r["reason"],
                    ]
                    for r in findings
                ],
                "现有结果尚不足以筛选具有明确健康关注依据的重点发现；详见各章结果与适用范围。",
            )
        elif block == 2:
            actions, seen = [], set()
            for topic in self.topics.values():
                if (
                    topic["status"] != "missing"
                    and topic.get("advice")
                    and topic["advice"] not in seen
                ):
                    seen.add(topic["advice"])
                    actions.append(
                        [
                            topic["title"],
                            topic["advice"],
                            "第" + TOPIC_PLACEMENT[topic["id"]] + "节结果",
                            "记录执行情况、症状及耐受变化",
                        ]
                    )
            self.emit(
                ["目标", "具体行动", "依据", "观察方式"],
                actions[:5],
                "本次未形成有充分依据的个体化饮食调整建议；可记录饮食、排便和近期用药背景，供后续结果对照。",
            )
            background = self.group("diet", "nutrition")
            if background:
                self.out.append("**已有饮食与营养背景记录**")
                self.emit(
                    ["背景项目", "本次记录", "来源"],
                    [
                        [r["label"], r["result_text"], _pick(r, "method", "source")]
                        for r in background
                    ],
                )
        elif block == 3:
            rows = []
            for finding in findings:
                row = self.evidence[finding["evidence_id"]]
                if row.get("kind") in {"pathogen", "virulence", "amr"}:
                    rows.append(
                        [
                            row["label"],
                            "确认检出及归属依据",
                            "复核支持读段、覆盖、注释版本及宿主连接证据",
                        ]
                    )
                elif row.get("comparison") in {"above", "below"}:
                    rows.append(
                        [
                            row["label"],
                            "确认参考比较的适用性",
                            "核对参考人群、分析方法、单位及检测背景",
                        ]
                    )
            self.emit(
                ["待核实事项", "目的", "可用依据或行动"],
                rows,
                "可补充采样、症状、饮食与用药背景；未评估的专项结果在相应章节注明，不视为正常。",
            )
        else:
            rows = []
            for row in self.raw("composite_models", "models"):
                valid = (
                    row.get("externally_validated") is True
                    and row.get("applicable") is True
                    and row.get("model_version")
                    and row.get("scale_definition")
                    and row.get("validation_evidence")
                    and finite(row.get("value")) is not None
                )
                rows.append(
                    [
                        _pick(row, "name", "metric"),
                        "已验证用途" if valid else "未启用",
                        f"{self.number(row['value'])} {row.get('unit', '')}" if valid else "未启用",
                        f"{row['scale_definition']}；{row['validation_evidence']}"
                        if valid
                        else "量尺、验证或本次适用性不足",
                    ]
                )
            self.emit(
                ["综合指标", "状态", "本次结果", "含义与适用范围"],
                rows,
                "综合健康分、失衡分与模型肠龄均未启用：本次未提供量尺、验证及适用性完整的模型，不填造分值。",
            )
            self.out.append(
                "健康分与失衡分分别定义，未必互为补数；模型肠龄是模型输出，不能仅凭菌群组成计算。"
            )



def prepare_presentation(document):
    document["audit"]["body_template_version"] = TEMPLATE_VERSION
    document["audit"]["overview_rule_version"] = RULE_VERSION
    document["presentation"] = {
        **document.get("presentation", {}),
        "version": TEMPLATE_VERSION,
        "chapters": [
            {
                "number": n,
                "title": title,
                "subsections": [f"{n}.{i} {h}" for i, (h, _) in enumerate(blocks, 1)],
            }
            for n, title, _, blocks in CHAPTERS
        ],
        "overview_rule_version": RULE_VERSION,
        "topic_placement": TOPIC_PLACEMENT,
    }
    document["overview_findings"] = select_findings(document)


def render_body(document):
    from .word_template import render_body as render_word_body

    return render_word_body(document)


def render_toc():
    # Standard Markdown anchors also work in a standalone Markdown reader.
    def anchor(title):
        return title.lower().replace(" ", "-")

    return [
        "## 目录",
        "- [检测结果总览](#检测结果总览)",
        *[f"- [{n} {title}](#{anchor(f'{n} {title}')})" for n, title, _, _ in CHAPTERS],
        "- [附录与参考资料](#附录与参考资料)",
    ]


def render_overview(document):
    from .document import table
    from .document import TYPE_LABELS

    rows = document["overview_findings"]
    output = [
        "## 检测结果总览",
        "仅列出本次有结果支撑、值得优先关注或复核的发现，最多五项；按专项检出和参考偏离排序，不作为健康风险评分。",
    ]
    if rows:
        output.append(
            table(
                ["关注顺序", "本次重点发现", "关注依据", "详见"],
                [
                    [
                        r["priority"],
                        r["finding"],
                        f"{TYPE_LABELS.get(r['evidence_type'], r['evidence_type'])}；{r['reason']}",
                        f"第{r['source']}节",
                    ]
                    for r in rows
                ],
            )
        )
    else:
        output.append(
            "现有结果尚不足以筛选具有明确健康关注依据的重点发现；这不表示全部结果正常。具体结果及适用范围见正文。"
        )
    return output
