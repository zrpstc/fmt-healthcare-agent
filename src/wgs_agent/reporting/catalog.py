"""The product outline is versioned code, never an LLM-generated table of contents."""

from dataclasses import dataclass

VERSION = "health-report-v4"
TITLE = "肠道菌群精准健康分析报告"


@dataclass(frozen=True)
class Topic:
    id: str
    title: str
    sources: tuple[str, ...]
    keywords: tuple[str, ...] = ()
    missing: str = "本次缺少对应数据，暂未评估。"


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    introduction: str
    topics: tuple[Topic, ...]


SECTIONS = (
    Section(
        "composition",
        "菌群组成与结构",
        "了解主要菌群的组成、优势分布和群落结构。",
        (
            Topic("phyla", "门水平组成", ("tax_phylum",)),
            Topic("genera", "属水平组成", ("tax_genus",)),
            Topic("species", "种水平组成", ("species",)),
            Topic("enterotype", "优势菌属与群落分型", ("enterotype",)),
            Topic("dominance", "优势菌集中程度", ("dominance",)),
        ),
    ),
    Section(
        "diversity",
        "菌群多样性",
        "从丰富度与均匀度两个方面观察菌群多样性。",
        (
            Topic("richness", "检出丰富度", ("div_richness",)),
            Topic("shannon", "Shannon 多样性指数", ("div_shannon",)),
            Topic("simpson", "Simpson 多样性指数", ("div_simpson",)),
            Topic("evenness", "Pielou 均匀度", ("div_evenness",)),
            Topic(
                "reference",
                "参考人群位置与纵向变化",
                ("div_reference",),
                missing="需匹配的参考人群或历次检测结果，本次暂未比较。",
            ),
        ),
    ),
    Section(
        "key_taxa",
        "重点菌群",
        "按关注方向展示重点菌群；同一菌种的作用还取决于菌株和宿主背景。",
        (
            Topic("bifidobacteria", "双歧杆菌相关菌群", ("species",), ("bifidobacterium",)),
            Topic(
                "lactic_acid",
                "乳酸菌相关菌群",
                ("species",),
                (
                    "lactobacillus",
                    "lacticaseibacillus",
                    "lactiplantibacillus",
                    "lactococcus",
                    "limosilactobacillus",
                ),
            ),
            Topic(
                "butyrate",
                "产丁酸相关菌群",
                ("species",),
                (
                    "faecalibacterium",
                    "roseburia",
                    "agathobacter",
                    "anaerostipes",
                    "eubacterium rectale",
                    "butyricicoccus",
                ),
            ),
            Topic(
                "mucin",
                "黏液利用相关菌群",
                ("species",),
                (
                    "akkermansia",
                    "ruminococcus torques",
                    "mediterraneibacter gnavus",
                    "ruminococcus gnavus",
                ),
            ),
            Topic(
                "opportunists",
                "条件致病相关菌群",
                ("species",),
                (
                    "escherichia",
                    "klebsiella",
                    "enterococcus",
                    "enterobacter",
                    "fusobacterium",
                    "bilophila",
                    "desulfovibrio",
                ),
            ),
            Topic(
                "pathogens",
                "病原体与毒力标志",
                ("pathogen",),
                missing="本次未提供专项病原体及毒力标志检测结果。",
            ),
        ),
    ),
    Section(
        "ecology",
        "肠道微生态功能",
        "以功能基因和通路观察微生态潜能，结合可用的专项检测解读。",
        (
            Topic(
                "colonization",
                "定植抵抗相关功能",
                ("function", "pathway"),
                ("colonization", "bacteriocin", "定植", "细菌素"),
            ),
            Topic("barrier", "肠道屏障相关功能", ("function",), ("barrier", "屏障")),
            Topic(
                "inflammation",
                "炎症与免疫相关功能",
                ("function", "pathway"),
                ("lipopolysaccharide", "inflammation", "脂多糖", "炎症", "免疫"),
            ),
            Topic(
                "gas",
                "产气与气体利用",
                ("function", "pathway"),
                (
                    "methanogenesis",
                    "hydrogen metabolism",
                    "hydrogen sulfide",
                    "产气",
                    "甲烷",
                    "气体利用",
                ),
            ),
            Topic(
                "mucin",
                "黏液降解与交叉营养",
                ("function", "pathway"),
                ("mucin", "cross-feeding", "黏液", "交叉营养"),
            ),
            Topic(
                "redox",
                "氧化应激相关功能",
                ("function", "pathway"),
                ("oxidative stress", "glutathione", "氧化应激", "谷胱甘肽"),
            ),
        ),
    ),
    Section(
        "nutrient_metabolism",
        "营养物质代谢",
        "按营养底物归类展示代谢通路，便于理解菌群的功能特点。",
        (
            Topic(
                "carbohydrate",
                "碳水化合物代谢",
                ("pathway", "function"),
                ("glycolysis", "glucose", "carbohydrate", "starch", "糖酵解", "碳水", "淀粉"),
            ),
            Topic(
                "fiber",
                "膳食纤维与抗性淀粉利用",
                ("pathway", "function"),
                ("cellulose", "xylan", "pectin", "inulin", "resistant starch", "纤维", "抗性淀粉"),
            ),
            Topic(
                "amino_acid",
                "蛋白质与氨基酸代谢",
                ("pathway", "function"),
                (
                    "amino acid",
                    "tryptophan",
                    "valine",
                    "leucine",
                    "methionine",
                    "lysine",
                    "arginine",
                    "氨基酸",
                    "蛋白质",
                ),
            ),
            Topic(
                "lipid",
                "脂质与胆汁酸代谢",
                ("pathway", "function"),
                ("fatty acid", "lipid", "bile", "脂肪酸", "脂质", "胆汁酸"),
            ),
            Topic(
                "vitamin",
                "维生素合成与利用",
                ("pathway", "function"),
                (
                    "folate",
                    "biotin",
                    "cobalamin",
                    "thiamin",
                    "riboflavin",
                    "menaquinone",
                    "vitamin",
                    "叶酸",
                    "维生素",
                ),
            ),
            Topic(
                "nucleotide",
                "核苷酸与嘌呤代谢",
                ("pathway", "function"),
                (
                    "purine",
                    "pyrimidine",
                    "nucleotide",
                    "guanosine",
                    "adenosine",
                    "ump",
                    "嘌呤",
                    "核苷酸",
                ),
            ),
        ),
    ),
    Section(
        "metabolites",
        "微生物代谢产物",
        "分别展示代谢物检测、模型预测与相关通路证据。",
        (
            Topic(
                "scfa",
                "短链脂肪酸",
                ("metabolite", "pathway"),
                (
                    "butyrate",
                    "propionate",
                    "acetate",
                    "isovaler",
                    "丁酸",
                    "丙酸",
                    "乙酸",
                    "短链脂肪酸",
                ),
            ),
            Topic(
                "intermediates",
                "乳酸与琥珀酸",
                ("metabolite", "pathway"),
                ("lactate", "succinate", "乳酸", "琥珀酸"),
            ),
            Topic(
                "bile",
                "次级胆汁酸",
                ("metabolite", "pathway"),
                ("deoxychol", "lithochol", "secondary bile", "次级胆汁酸", "脱氧胆酸"),
            ),
            Topic(
                "indoles",
                "吲哚及色氨酸衍生物",
                ("metabolite", "pathway"),
                ("indole", "tryptophan", "吲哚", "色氨酸"),
            ),
            Topic(
                "phenols",
                "酚类、对甲酚与胺类",
                ("metabolite", "pathway"),
                ("phenol", "cresol", "putrescine", "cadaverine", "酚", "腐胺", "尸胺"),
            ),
            Topic(
                "sulfur",
                "氨与硫化氢相关代谢",
                ("metabolite", "pathway"),
                ("ammonia", "hydrogen sulfide", "sulfate reduction", "硫化氢", "氨生成"),
            ),
            Topic(
                "tma",
                "TMA/TMAO 相关代谢",
                ("metabolite", "pathway"),
                ("trimethylamine", "tmao", "三甲胺"),
            ),
        ),
    ),
    Section(
        "nutrition",
        "营养摄入与状态推算",
        "结合饮食记录、营养问卷和检验结果评估营养背景。",
        (
            Topic(
                "macro",
                "能量与宏量营养素摄入",
                ("nutrition", "diet"),
                (
                    "energy",
                    "calorie",
                    "protein",
                    "carbohydrate",
                    "fat",
                    "能量",
                    "蛋白质",
                    "碳水",
                    "脂肪",
                ),
            ),
            Topic("fiber", "膳食纤维摄入", ("nutrition", "diet"), ("fiber", "fibre", "纤维")),
            Topic(
                "variety",
                "饮食多样性与食物结构",
                ("diet",),
                ("diversity", "variety", "vegetable", "fruit", "多样", "蔬菜", "水果", "食物结构"),
            ),
            Topic(
                "vitamins",
                "维生素营养状态",
                ("nutrition",),
                ("vitamin", "folate", "b12", "维生素", "叶酸"),
            ),
            Topic(
                "minerals",
                "矿物质与微量元素状态",
                ("nutrition",),
                ("iron", "zinc", "ferritin", "calcium", "铁", "锌", "钙", "微量元素"),
            ),
        ),
    ),
    Section(
        "gut_brain",
        "肠脑轴及内分泌关联",
        "展示相关功能与研究关联，宿主神经递质和激素水平以专项检测为准。",
        (
            Topic(
                "tryptophan",
                "色氨酸与血清素相关通路",
                ("axis", "pathway"),
                ("tryptophan", "serotonin", "kynurenine", "色氨酸", "血清素", "犬尿氨酸"),
            ),
            Topic(
                "gaba",
                "GABA 与谷氨酸相关功能",
                ("axis", "pathway"),
                ("gaba", "gamma-aminobut", "glutamate decarboxyl", "氨基丁酸", "谷氨酸脱羧"),
            ),
            Topic(
                "histamine",
                "组胺相关代谢",
                ("axis", "pathway"),
                ("histamine", "histidine decarboxyl", "组胺", "组氨酸脱羧"),
            ),
            Topic(
                "catecholamine",
                "儿茶酚胺相关代谢",
                ("axis", "pathway"),
                ("dopamine", "catecholamine", "dopac", "多巴胺", "儿茶酚胺"),
            ),
            Topic(
                "estrogen",
                "雌激素再循环相关功能",
                ("axis", "pathway"),
                ("glucuronidase", "estrogen", "葡萄糖醛酸苷酶", "雌激素"),
            ),
            Topic(
                "metabolic_signals",
                "胆汁酸与代谢内分泌信号",
                ("axis",),
                ("fxr", "tgr5", "glp", "胆汁酸", "内分泌"),
            ),
        ),
    ),
    Section(
        "symptoms",
        "症状相关菌分析",
        "围绕已报告的症状整理菌群线索，同时保留相反证据。",
        (
            Topic(
                "bloating", "腹胀与排气", ("symptom",), ("bloating", "flatulence", "腹胀", "排气")
            ),
            Topic("constipation", "便秘", ("symptom",), ("constipation", "便秘")),
            Topic("diarrhea", "腹泻", ("symptom",), ("diarrhea", "diarrhoea", "腹泻")),
            Topic("pain", "腹痛与腹部不适", ("symptom",), ("abdominal pain", "腹痛", "腹部不适")),
            Topic(
                "stool",
                "排便性状与食物相关不适",
                ("symptom",),
                ("bristol", "stool", "food", "排便", "食物", "乳糖"),
            ),
        ),
    ),
    Section(
        "diseases",
        "疾病相关特征与风险模型",
        "将文献关联特征与经过验证的疾病预测模型分别展示。",
        (
            Topic(
                "gastrointestinal",
                "肠道疾病相关特征",
                ("disease",),
                (
                    "crohn",
                    "colitis",
                    "ibs",
                    "ibd",
                    "colorectal",
                    "克罗恩",
                    "结肠",
                    "肠易激",
                    "肠炎",
                    "胃癌",
                ),
            ),
            Topic(
                "metabolic",
                "代谢疾病相关特征",
                ("disease",),
                ("diabetes", "obesity", "metabolic", "糖尿病", "肥胖", "代谢"),
            ),
            Topic(
                "liver",
                "肝脏疾病相关特征",
                ("disease",),
                ("liver", "cirrhosis", "nafld", "masld", "肝"),
            ),
            Topic(
                "cardiovascular",
                "心血管相关特征",
                ("disease",),
                ("cardio", "atherosclerosis", "heart", "心血管", "动脉", "心力"),
            ),
            Topic(
                "neuro",
                "神经与精神健康相关特征",
                ("disease",),
                (
                    "depression",
                    "parkinson",
                    "alzheimer",
                    "schizophrenia",
                    "抑郁",
                    "帕金森",
                    "认知",
                    "精神",
                ),
            ),
            Topic("other", "其他疾病研究关联", ("disease_other",)),
            Topic(
                "models",
                "经过验证的疾病风险模型",
                ("prediction",),
                missing="本次未提供经过验证且适用于本样本的疾病预测模型结果。",
            ),
        ),
    ),
    Section(
        "resistance",
        "抗生素耐药性",
        "按抗生素类别与耐药机制展示基因检测结果。",
        (
            Topic(
                "beta_lactam",
                "β-内酰胺类",
                ("amr",),
                ("beta-lactam", "beta lactam", "β-lactam", "内酰胺"),
            ),
            Topic("aminoglycoside", "氨基糖苷类", ("amr",), ("aminoglycoside", "氨基糖苷")),
            Topic("macrolide", "大环内酯类", ("amr",), ("macrolide", "大环内酯")),
            Topic("quinolone", "喹诺酮类", ("amr",), ("quinolone", "喹诺酮")),
            Topic("tetracycline", "四环素类", ("amr",), ("tetracycline", "四环素")),
            Topic(
                "sulfonamide",
                "磺胺及甲氧苄啶类",
                ("amr",),
                ("sulfonamide", "trimethoprim", "磺胺", "甲氧苄啶"),
            ),
            Topic("other", "其他类别及多重耐药", ("amr_other",)),
            Topic("mechanisms", "耐药机制与基因背景", ("amr",)),
        ),
    ),
)

TOPICS = {f"{section.id}.{topic.id}": topic for section in SECTIONS for topic in section.topics}
