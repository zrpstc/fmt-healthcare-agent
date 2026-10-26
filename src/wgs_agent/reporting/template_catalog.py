"""Presentation outline transcribed from the four supplied report templates.

The evidence/narrative topic IDs remain stable so knowledge graphs and module
bibliographies retain their existing contracts. Only their body placement changes.
"""

TEMPLATE_VERSION = "word-native-1-14-v2"

# number, title, introduction, [(subheading, legacy evidence/narrative topic IDs)]
CHAPTERS = (
    (
        3,
        "菌群组成与群落结构",
        "本章展示菌群的主要组成、优势与核心成员，以及与参考人群的比较。",
        (
            (
                "菌群分类与相对丰度",
                ("composition.phyla", "composition.genera", "composition.species"),
            ),
            ("优势物种与核心菌群", ("composition.dominance",)),
            ("肠型或群落组成倾向", ("composition.enterotype",)),
            ("与匹配参考人群的组成比较", ()),
        ),
    ),
    (
        4,
        "菌群多样性与生态功能结构",
        "本章展示菌群多样性、人群位置，以及功能分工与潜在协作特征。",
        (
            (
                "菌群多样性",
                (
                    "diversity.richness",
                    "diversity.shannon",
                    "diversity.simpson",
                    "diversity.evenness",
                ),
            ),
            ("与匹配参考人群的群落差异", ("diversity.reference",)),
            ("功能冗余与贡献集中度", ()),
            ("潜在代谢协作", ()),
        ),
    ),
    (
        5,
        "重点健康相关菌与条件致病菌",
        "本章展示重点微生物的检出结果、丰度及关联背景，并结合证据解读。",
        (
            (
                "重点健康相关菌",
                (
                    "key_taxa.bifidobacteria",
                    "key_taxa.lactic_acid",
                    "key_taxa.butyrate",
                    "key_taxa.mucin",
                ),
            ),
            ("条件致病菌与其他重点关注微生物", ("key_taxa.opportunists",)),
            ("检出状态与证据支持", ("key_taxa.pathogens",)),
            ("结果解释与适用范围", ()),
        ),
    ),
    (
        6,
        "菌株特征与毒力因子",
        "本章说明是否具备菌株判断条件，并展示毒力相关功能与微生物归属证据。",
        (
            ("菌株与谱系判断", ()),
            ("毒力相关功能概览", ()),
            ("致病型与序列连接证据", ()),
            ("宿主归属与可解释范围", ()),
        ),
    ),
    (
        7,
        "耐药组与可移动遗传元件",
        "本章描述微生物耐药相关序列及其遗传背景，重点展示类别与证据。",
        (
            (
                "耐药决定因素",
                (
                    "resistance.beta_lactam",
                    "resistance.aminoglycoside",
                    "resistance.macrolide",
                    "resistance.quinolone",
                    "resistance.tetracycline",
                    "resistance.sulfonamide",
                    "resistance.other",
                ),
            ),
            ("对应药物类别与机制", ()),
            ("可能宿主与可移动元件关联", ("resistance.mechanisms",)),
            ("结果解读", ()),
        ),
    ),
    (
        8,
        "古菌 真菌与DNA病毒组",
        "按不同微生物类别分别展示检出结果与可报告范围。",
        (
            ("产甲烷古菌", ()),
            ("真菌", ()),
            ("DNA噬菌体与其他DNA病毒", ()),
            ("检测范围与结果解读", ()),
        ),
    ),
    (
        9,
        "膳食底物利用与营养物质代谢",
        "展示微生物利用底物及合成、降解营养物质的基因功能潜力。",
        (
            (
                "复杂碳水底物利用潜力",
                ("nutrient_metabolism.carbohydrate", "nutrient_metabolism.fiber"),
            ),
            ("糖活性酶与相关基因簇", ()),
            (
                "其他营养物质的合成与降解",
                (
                    "nutrient_metabolism.amino_acid",
                    "nutrient_metabolism.lipid",
                    "nutrient_metabolism.vitamin",
                    "nutrient_metabolism.nucleotide",
                ),
            ),
            ("功能结果的证据摘要", ()),
        ),
    ),
    (
        10,
        "微生物代谢物生成与利用潜力",
        "按反应方向展示生成、利用及转化功能；本章仅呈现测序支持的功能潜力，已有代谢物检测结果另列。",
        (
            ("短链脂肪酸相关功能", ("metabolites.scfa",)),
            ("乳酸与琥珀酸的周转", ("metabolites.intermediates",)),
            ("胆汁酸转化", ("metabolites.bile",)),
            ("色氨酸代谢的不同产物方向", ("metabolites.indoles",)),
            ("蛋白发酵与生物胺相关功能", ("metabolites.phenols", "gut_brain.histamine")),
            ("气体的产生与消耗相关功能", ("ecology.gas", "metabolites.sulfur")),
            ("TMA生成相关功能", ("metabolites.tma",)),
            ("脂多糖与其他细胞组分合成特征", ()),
        ),
    ),
    (
        11,
        "肠道微生态与宿主互作相关特征",
        "整合具体物种与功能证据，展示与宿主互作有关的线索。",
        (
            ("定植抗力相关线索", ("ecology.colonization",)),
            ("炎症与免疫互作相关特征", ("ecology.inflammation",)),
            ("黏液糖链与宿主底物利用", ("ecology.mucin",)),
            ("屏障相关线索的综合解释", ("ecology.barrier", "ecology.redox")),
        ),
    ),
    (
        12,
        "肠脑轴与内分泌相关代谢",
        "展示神经活性分子与激素转化的微生物功能证据，并单列量表背景。",
        (
            ("神经活性分子的生成与降解相关功能", ("gut_brain.gaba", "gut_brain.catecholamine")),
            ("芳香族氨基酸代谢的关联解读", ("gut_brain.tryptophan",)),
            ("雌激素等相关微生物转化功能", ("gut_brain.estrogen", "gut_brain.metabolic_signals")),
            ("量表背景与综合解读", ()),
        ),
    ),
    (
        13,
        "症状相关特征与问卷对照",
        "将本次排便和症状记录与功能结果并列，帮助理解可能相关的线索。",
        (
            (
                "排便与症状记录",
                (
                    "symptoms.stool",
                    "symptoms.bloating",
                    "symptoms.constipation",
                    "symptoms.diarrhea",
                    "symptoms.pain",
                ),
            ),
            ("症状与功能结果对照", ()),
            ("关联方向与可解释范围", ()),
        ),
    ),
    (
        14,
        "疾病相关特征与经验证模型",
        "先展示疾病研究关联，再单独呈现符合适用条件的模型结果。",
        (
            ("疾病关联模块与适用范围", ()),
            (
                "关联菌与功能特征",
                (
                    "diseases.gastrointestinal",
                    "diseases.metabolic",
                    "diseases.liver",
                    "diseases.cardiovascular",
                    "diseases.neuro",
                    "diseases.other",
                ),
            ),
            ("模型适用条件与验证信息", ()),
            ("模型结果与分值含义", ("diseases.models",)),
        ),
    ),
    (
        15,
        "专项代谢转化功能",
        "逐项展示膳食成分及药物转化的序列功能线索，并说明验证阶段。",
        (
            ("多酚与异黄酮等膳食成分转化", ()),
            ("药物转化相关功能", ()),
            ("验证阶段与适用范围", ()),
        ),
    ),
    (
        16,
        "综合解读与行动建议",
        "按证据及实际相关性归纳结果，并将建议对应到明确的发现与观察目标。",
        (
            ("关键发现与需要关注的内容", ()),
            (
                "饮食与生活方式观察目标",
                (
                    "nutrition.macro",
                    "nutrition.fiber",
                    "nutrition.variety",
                    "nutrition.vitamins",
                    "nutrition.minerals",
                ),
            ),
            ("待核实信息与结果复核", ()),
            ("综合健康分 失衡分与肠龄", ()),
        ),
    ),
)

CHAPTERS = tuple((n - 2, title, intro, blocks) for n, title, intro, blocks in CHAPTERS)

TOPIC_PLACEMENT = {
    topic_id: f"{number}.{index}"
    for number, _, _, blocks in CHAPTERS
    for index, (_, topic_ids) in enumerate(blocks, 1)
    for topic_id in topic_ids
}

# Explicit optional inputs. They do not trigger new bioinformatics analyses.
TEMPLATE_INPUT_KEYS = (
    "taxonomy",
    "diversity",
    "core_microbiome",
    "absolute_abundance",
    "strains",
    "virulence",
    "mobile_elements",
    "archaea",
    "fungi",
    "dna_viruses",
    "cazy",
    "metabolic_cooperation",
    "functional_redundancy",
    "scales",
    "specialized_metabolism",
    "composite_models",
    "symptoms",
    "resistance",
    "healthy_comparison",
)
