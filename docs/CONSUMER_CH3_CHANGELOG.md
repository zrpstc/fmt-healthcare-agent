# 第3章消费者改版与 G13–G15 交付记录

基线 main：`8b4abce679fc1b8941fb03560bfc5b8b91a02129`；工作分支：`feat/consumer-ch3`。已完成前置的逐小节inline子图修复。本文记录本次实现和实际样本验收，后续修改应以当前代码和测试为准。

## 实现与数据边界

| 文件/组件 | 作用 |
| --- | --- |
| consumer_graph.py / knowledge_graph.py | G13展示副本清洗、清洗后中文校验、稀疏图省略及逐节候选审计 |
| graph_visual.py | pending虚线、approved实线、普通/自环标签碰撞检测、9pt以上节点及图例留白；全报告图谱去红色 |
| consumer_key_taxa.py / consumer_key_taxa.yaml | G14唯一面板、分类别名、合计、未检出闸门、估算reads阈值、G11同源标签 |
| cmd_derived.py / consumer_reference.py | G10离线类别分布、面板SHA及同层/排除本人校验；复用已验证距离矩阵 |
| consumer_badges.py | G15按独立论文计数，区分物种、属和菌株证据 |
| glossary.py / consumer_glossary.yaml | watch_note独立缓存/审核字段；用户给定概念及B.fragilis固定说明 |
| consumer_chapter_three.py / consumer_copy.py | 两节卡片、方向化档位、G4解释、固定提醒、规则兜底及原始明细附录 |
| consumer_basis.py / word_figures.py | 第3章一次口径说明，共享紧凑刻度条、卡片图及首次学名管理 |
| word_template.py / template_body.py / narrative.py | 标题、目录、解读规则、3.3合入3.2，保留稳定ID |
| consumer_appendix.py | A1原表/support完整保留与G13汇总，A4保留未在正文完整展示的原主题图 |
| domain_tools.py / refresh_report_presentation.py | 正常生成与展示刷新两条入口均接入第3章，JSON/证据快照保存审计 |
| functional_metrics.py / consumer_chapter_two.py | G11从同一YAML解析产丁酸成员，并使用分类别名核对coverage_gap |
| docs与tests | 同步公共接口/配置/资产准备、专项测试与旧契约断言 |

Word原稿、word_contract.json、catalog.py、chapter_three.py均未修改；旧selected_rows及其调用路径保留。原始topic/evidence ID不变。3.3独立标题、图3-2及表3-3移出正文，pathogens的证据映射并入3.2；3.4继续隐藏。原word.3.3/3.4对象仍在结构化视图中标记隐藏，其他章节解读保持原值。刷新只使用既有分析和独立比较谱，没有运行MetaPhlAn/HUMAnN。

图谱清洗严格做删除与重绘，没有扩展证据范围或增加推断边。候选先清洗再验证剩余中文；否则旧图中的RiCBM未翻译标签会在删除前阻断整图。带“组”的生物词如基因组、组成、组织予以保留，研究分组仍删除。默认inline及appendix/off语义保持前置任务约定。第3章“全报告不用红色”覆盖前置任务的保留红色要求：抑制/降低关系从红橙改琥珀色，疾病/结局节点改灰色，不改语义。

## 面板与 MetaPhlAn 3/v30 分类名核对

核对对象为服务器既有 `mpa_v30_CHOCOPhlAn_201901.pkl` 分类目录及3537人参考的984种特征；目录SHA见 taxonomy-panel-audit.json。以下完整列出成员。新乳杆菌属不在v30目录中，保留其名称用于识别主分析新命名，同时旧Lactobacillus覆盖v30谱。Roseburia spp.、Butyricicoccus spp.按属登记，避免把spp.误当成种名。新旧命名只用于明确匹配，不改原始taxon名称。

| 类别 | 级别/面板名 | 明确别名 | v30目录命中 | 参考匹配种数 |
| --- | --- | --- | --- | --- |
| helpful.bifidobacteria | genus / Bifidobacterium | — | Bifidobacterium | 22 |
| helpful.lactobacilli | genus / Lactobacillus | — | Lactobacillus | 58 |
| helpful.lactobacilli | genus / Lacticaseibacillus | — | 无该新名称 | 0 |
| helpful.lactobacilli | genus / Lactiplantibacillus | — | 无该新名称 | 0 |
| helpful.lactobacilli | genus / Limosilactobacillus | — | 无该新名称 | 0 |
| helpful.lactobacilli | genus / Ligilactobacillus | — | 无该新名称 | 0 |
| helpful.butyrate | species / Faecalibacterium prausnitzii | — | Faecalibacterium prausnitzii | 1 |
| helpful.butyrate | genus / Roseburia | — | Roseburia | 9 |
| helpful.butyrate | species / Agathobacter rectalis | Eubacterium rectale | Eubacterium rectale | 1 |
| helpful.butyrate | species / Anaerostipes hadrus | — | Anaerostipes hadrus | 1 |
| helpful.butyrate | genus / Butyricicoccus | — | Butyricicoccus | 2 |
| helpful.butyrate | species / Eubacterium hallii | Anaerobutyricum hallii | Eubacterium hallii | 1 |
| helpful.akkermansia | species / Akkermansia muciniphila | — | Akkermansia muciniphila | 1 |
| watch.opportunists | genus / Escherichia | — | Escherichia | 4 |
| watch.opportunists | genus / Klebsiella | — | Klebsiella | 7 |
| watch.opportunists | genus / Enterobacter | — | Enterobacter | 5 |
| watch.opportunists | genus / Enterococcus | — | Enterococcus | 18 |
| watch.opportunists | genus / Citrobacter | — | Citrobacter | 11 |
| watch.opportunists | genus / Proteus | — | Proteus | 3 |
| watch.opportunists | species / Clostridioides difficile | Clostridium difficile | Clostridioides difficile | 1 |
| watch.opportunists | species / Clostridium perfringens | — | Clostridium perfringens | 1 |
| watch.inflammation_assoc | species / Mediterraneibacter gnavus | Ruminococcus gnavus | Ruminococcus gnavus | 1 |
| watch.inflammation_assoc | species / Ruminococcus torques | — | Ruminococcus torques | 1 |
| watch.inflammation_assoc | genus / Fusobacterium | — | Fusobacterium | 13 |
| watch.sulfide | genus / Bilophila | — | Bilophila | 1 |
| watch.sulfide | genus / Desulfovibrio | — | Desulfovibrio | 5 |
| watch.conditional_commensal | species / Bacteroides fragilis | — | Bacteroides fragilis | 1 |

参考派生包位于gpu02 `tmp/consumer-ch3/cmd-key-taxa-v1`，面板SHA与当前YAML一致。已验证复用原G10距离矩阵；通过把cdist/pdist替换为抛错函数证明没有重新拟合距离。新增离线类别分布构建耗时1.917秒。资产仅用于本次隔离预览，未自动切换线上配置。未来面板变动需新目录重新派生，SHA不符时正文隐藏类别参考位置。

## ZYMO_D6331 类别结果

卡片合计使用主分析百分数，与第1章1.1相同；参考位置用独立cMD谱计算，只提示一次口径。表中保留原始精度供核对，正文使用G2格式。

| 类别 | 主分析合计% | 独立谱合计% | 参考百分位 | 档位 | 检出成员 | 未检出判断 |
| --- | --- | --- | --- | --- | --- | --- |
| 双歧杆菌 | 1.483927 | 2.585279741472026 | 46.536612948826686 | 常见 | 青春双歧杆菌 1.483927% | 已有正值成员，不写未检出 |
| 乳杆菌类 | 4.612265 | 7.420639257936074 | 99.40627650551315 | 很多 | 发酵黏液乳杆菌 4.612265% | 已有正值成员，不写未检出 |
| 主要产丁酸菌 | 16.807817 | 15.851248414875158 | 50.77749505230421 | 常见 | 普拉梭菌 13.295725%、人类罗氏菌 3.512092% | 已有正值成员，不写未检出 |
| 阿克曼菌 | 1.902623 | 2.408939759106024 | 80.63330506078597 | 较多 | 嗜黏蛋白阿克曼菌 1.902623% | 已有正值成员，不写未检出 |
| 条件致病菌 | 12.515746 | 22.13614778638522 | 98.19055696918292 | 明显偏多 | 大肠埃希菌 11.120034%、艰难梭菌 1.395712% | 已有正值成员，不写未检出 |
| 研究中与肠道炎症相关的菌 | 5.50671 | 7.277519272248072 | 96.35284139100933 | 明显偏多 | 动物梭杆菌 5.50671% | 已有正值成员，不写未检出 |
| 常见菌、仅特定菌株需关注 | 13.657273 | 22.10275778972422 | 99.85863726321742 | 明显偏多 | 脆弱拟杆菌 13.657273% | 已有正值成员，不写未检出 |
| 产硫化氢相关菌 | — | — | — | 隐藏 | 完整谱中没有面板成员 | QC未明确通过，隐藏并登记G6，不能发布“本次未检出” |

本样本taxonomy.complete=True，但metadata.qc_status为空。未知QC没有被补成通过；有正值的测量卡片保留，没有成员的类别遵循严格未检出闸门隐藏。所有成员均缺estimated reads字段，因此不显示检出可靠度徽标，不拿普通reads或coverage代替；后续样本若需要徽标，应在流程配置中开启MetaPhlAn `rel_ab_w_read_stats`。本次不补跑。输入没有给出可信数值检测下限，A1明确记为未提供，不编造阈值。

## G4 条目、来源与审核

用户给定的7项概念定义及新增类别概念使用curated-user-provided来源，review_status=approved。B.fragilis关注说明为用户固定内容，watch_review_status=approved；正文只说“请看第4章”，不预先写检测结论。已有F.prausnitzii、E.coli、B.fragilis one_liner保持完全不变，与第1章共用相同term_id。F.prausnitzii和E.coli现有来源是菌株范围，G15不把它们升级为物种证据。

另从本报告已绑定的文献，通过G4可注入压缩器生成以下4条待审草稿。它们写入独立 `tmp/consumer-ch3/glossary-review` 缓存/队列，未改生产缓存，未自动批准，正文不显示。完整来源题名、DOI、claim/document ID和审核字段见glossary-review.json。证据没有说明的含量偏多含义不补写。

| 对象 | 字段/草稿 | 范围 | 来源 | 审核/正文 |
| --- | --- | --- | --- | --- |
| Bifidobacterium adolescentis | one_liner：研究发现它携带多种维生素合成相关基因。 | species | litkg:claim:43743 | pending / 隐藏 |
| Roseburia hominis | one_liner：同属研究提示可参与丁酸生成。 | genus | litkg:claim:39093 | pending / 隐藏 |
| Akkermansia muciniphila | one_liner：研究中将它列为参与丙酸生成的菌种。 | species | litkg:claim:39436 | pending / 隐藏 |
| Clostridioides difficile | watch_note：研究中关注其产生毒素的能力，具体需看第4章毒力检测。 | species | litkg:claim:38415 | pending / 隐藏 |

发酵黏液乳杆菌没有合适的已绑定功能证据；大肠埃希菌现有功能证据不能回答“为何需要留意”；动物梭杆菌只有同属疾病关联，不能据此填写本样本或物种的含量解释。这些字段静默留空，记录G6，列入人工后续补证。不会用模板句充数。approved概念和固定句可见，生成内容仍受独立审核闸门约束。

## 子图清洗与版式

| 小节 | 节点前→后 | 边前→后 | 分量 | 删除原因计数/状态 |
| --- | --- | --- | --- | --- |
| 1.1 | 7→7 | 6→6 | 2 | {} / ready |
| 1.2 | 0→0 | 0→0 | — | {} / no_ready_subgraph |
| 1.4 | 8→4 | 6→3 | 1 | {"unseeded_component_nodes": 4, "unseeded_component_edges": 3} / ready |
| 2.1 | 0→0 | 0→0 | — | {} / no_ready_subgraph |
| 2.2 | 0→0 | 0→0 | — | {} / no_ready_subgraph |
| 2.3 | 8→6 | 5→4 | 2 | {"extra_component_nodes": 2, "extra_component_edges": 1} / ready |
| 3.1 | 8→7 | 6→5 | 2 | {"study_group_nodes": 1, "dangling_edges": 1} / ready |
| 3.2 | 8→3 | 6→2 | 1 | {"study_group_nodes": 1, "identifier_nodes": 3, "dangling_edges": 2, "structural_edges": 2, "extra_component_nodes": 1, "extra_component_edges": 0} / ready |

正文实际出图：1.1、1.4、2.3、3.1、3.2。其他可见小节没有可用图时不显示占位文字。正文节点最小约11.42pt；逐页目检没有节点/边标签重叠，虚线说明完整在画布内。3.1图中的哈氏厌氧棒菌属于包含实际展示seed的研究背景分量，不是推断为本样本的检出成员；读图说明已明确边只说明文献背景。seeds列表、候选、评分和逐候选清洗明细见subsection-selection.json。

## 页面与验收

- 改版前第3章：原PDF第13–17页，共5页，PNG在交付包 `before/chapter3_page_013.png` 至017。
- 改版后第3章：新PDF第11–13页，共3页，符合不多于4页；PNG在 `after/chapter123_page_011.png` 至013。
- 第1–3章全部页面：新PDF第5–13页，9张PNG均导出并目检；含子图的页面为6、8、10、12、13。
- PDF摘取为 `chapters1-3-consumer.pdf`；原完整报告及其JSON/证据在gpu02 `tmp/consumer-ch3/report-v1`。
- 刷新程序为 `scripts/refresh_report_presentation.py`，使用 `--preserve-other-chapters`；原evidence逐对象相等、原topic集合相同、原主题图nodes/edges相同、除word.3外解读对象相同、基线源文件字节未变。
- 第3章正文G1及追加禁用词0命中，无3.3/3.4残留引用；第1–3章正文知识图无“待审核”、研究分组或中文数字编号节点。
- 全量pytest：766 passed、2 skipped、28 warnings、16 subtests passed，134.91秒。warnings为已有绘图字体告警。完整测试日志留在gpu02，交付只含脱敏结果摘要。

## 更新的旧测试断言

1. test_consumer_chapter_two：coverage_gap样本补上明确百分数单位，避免新G14同源标签接受无单位数据。
2. test_consumer_inline_subgraphs合并：一边图例改成两条可归属seed的关系；明确合并claim并集且原图不改。
3. 同图去重与跨章去重：候选各含两边，验证合并→下一候选→无替代省略，继续保持签名去重。
4. analyte中文补全：增加第二条有效关系，仍验证复用既有中文名。
5. 后续新章节自动出口：第3章已有专用渲染器，改以第4章临时opt-in和明确展示seeds验证通用出口。
6. 单图fallback排序：seed命中候选至少两边，继续验证命中优先。
7. 正文节点上限：使用完整且足够长的合成菌名与两seed，验证≤4节点，同时原JSON保持12节点。
8. 逐节位置和首次读图说明：构造能通过G13的两边图，继续验证小结后放图、说明仅一次和重复渲染稳定。
9. 三模式测试：inline样本改为两边可用图；appendix/off断言继续保留。
10. graph_multiline、graph_presentation、原图发布/API一致性：显式appendix模式，按A4去重后的实际展示主题检查同一PNG/JSON/API/PDF，而非固定要求后来重复的key_taxa图片名出现。
11. test_health_report模型桩：对word.3.*返回消费者文案，避免旧“已记录”套话被新G1闸门拒绝。
12. test_word_template空图数量：28改26，空第3章卡片替换旧两图；原Word合同28图的只读断言继续保留。

新增测试覆盖分组/编号/结构边/远端Other删除、最多两个seed分量、至少两边、未翻译噪声先清洗、pending样式和图例边界、自环碰撞；面板别名/合计/参考/未检出前置条件/估算reads；G15论文去重与watch独立审核；第1/3章同菌同解释、G11同源、旧ID及其他章节保持、3.3隐藏和第4章引用校验。

## 人工确认清单

- 是否认可面板成员与属/种边界，尤其Roseburia/Butyricicoccus按属，以及v30旧名匹配策略。
- 是否认可检出可靠度高≥1000、中≥100、低<100的编辑阈值；当前样本不展示徽标。
- 是否认可阿克曼菌单列helpful、M.gnavus/R.torques归watch的拆组；当前样本动物梭杆菌在watch组。
- 审核4条pending草稿及缺说明的实际菌；新批准内容必须写回同一G4词典，维持第1/3章一致。
- 确认未知QC的真实来源后再决定能否展示未检出；不能由报告程序猜测通过。
- 生产使用类别参考位置前，按部署流程选择新的已校验派生包；本次只完成构建与预览，不改线上凭据或配置。

## 并发保护与审计

每次写入前检查当前分支、HEAD、Git锁及本任务已写文件SHA256；不匹配即停写。应用前git apply --check，保留原文件备份；所有应用和分阶段提交写入 `.git/consumer-ch3-audit.jsonl`。没有检测到需要覆盖的其他agent未提交改动；既有consumer-ch2工作树保持原状。没有使用force push、hard reset或覆盖他人文件。
