# 消费者报告展示层（第1–3章）

消费者正文由 `consumer_copy.py`、`consumer_chapter.py`、`consumer_chapter_two.py` 和 `consumer_chapter_three.py` 覆盖；Word 原稿、word_contract.json 和证据主题 ID 不变。完整13章仍然保留。当前 `CONSUMER_CHAPTERS={1,2,3}`。第3章只显示3.1、3.2，原3.3证据并入3.2，原始解读ID继续保留。

原始检测值、参考统计及旧模型文案保留在原结构化字段。消费者数据另存 `document.consumer`；缺失项目按任务契约另外登记在 `document.consumer_omissions`。旧第1章图片载荷保留在 `consumer.raw_chapter_one.source_word_figures`。

## 数字、名称与空状态

正文数量调用 `consumer_format`。百分数至多三位有效数字；因此100%边界显示100%，不显示100.0%。人数按千分位保留精确整数。`tier()` 在边界不确定时降档，不从退化区间发布明显偏高/低判断。

`taxon_labels.display_name(row, first_mention)` 返回首次出现的斜体拉丁学名。`NameRegistry` 为每次完整渲染重新建立，保证重复渲染一致；后续消费者章节可复用同一实例。未命名分类单元的标识符留在附录与原始数据。

无可靠解释的档案单元格保持空白。核心定义或成员不可核对时，隐藏对应图表并登记原因。没有可展示内容的小节仅保留规定的一句范围说明。方案B明确允许隐藏1.3，故不显示其空标题。

## 术语服务与人工审核

`knowledge_base/consumer_glossary.yaml` 使用 YAML 1.2 的 JSON 子集，无额外解析依赖。条目带版本、证据范围和来源。人工维护的种子条目为 approved；自动生成条目始终为 pending。种子条目是编辑性词典，发布前仍应由产品/医学编辑确认中文译名和措辞。

查询依次使用 approved 词典、同版本缓存、LitKG、现有 PubmedSearchTool、可选网页检索。LitKG 复用第3章的功能证据和检索接口，优先物种级证据。命中证据后只压缩该来源；模型拒绝或没有可靠内容时不编造解释。无可用模型时只使用词典和已有缓存，不为无法压缩的材料发起网络请求。

| 配置 | 默认值 | 含义 |
| --- | --- | --- |
| WGS_GLOSSARY_REQUIRE_REVIEW | 1 | pending 不进正文，进入运行时待审队列 |
| WGS_WEB_SEARCH_PROVIDER | 空 | 网页检索关闭；searxng 才启用 |
| WGS_SEARXNG_URL | 空 | 仅从环境读取，不能写入报告或代码 |
| WGS_REPORT_KNOWLEDGE_GRAPHS | inline | inline：已改版章节逐小节最多一幅，A4只收正文未展示的图；appendix：全部放A4；off：全报告隐藏子图 |
| WGS_REPORT_GRAPH_BODY_MAX_NODES | 8 | 正文图节点上限，最少2，最多12；边上限6；不影响原始主题图和附录 |

缓存为工作区 `runtime/glossary/` 下的 term_id+version 内容键；待审队列为 `runtime/glossary_review_queue.jsonl`。不同报告复用同一缓存，避免同菌解释漂移。队列使用文件锁去重，缓存原子替换。审核通过后，把完整条目加入人工词典并标记 approved；修改解释时同步提升词典/服务版本。只改队列状态不会绕过正文审核闸门。

SearXNG 的 settings.yml 必须开启：

```yaml
search:
  formats: [html, json]
```

网页结果按域名白名单筛选，Wikipedia 排最后；最多三条。每次请求超时5秒、响应体上限256KiB。重定向逐跳复核域名。仅提取正文作为不可信证据，忽略网页指令；网络失败不阻断报告。

## 集中度、肠型和独立谱

1.2 的主分析集中度与1.1保持一致。用于参考比较的集中度单列，使用独立比较谱，并重新核对原报告的参考包哈希、排除本人、人口学分层、人数与版本签名；任何不一致都隐藏参考位置。

肠型采用方案B。服务器参考资产 `feature_level=species`，校验文件只有 metadata.tsv 和 species_abundance.tsv，没有属级参考矩阵及经验证的聚类资产。此次不从物种名推导属谱，不发布未经验证的肠型。优势菌属说明并入1.1，原因写入A3。方案A不适用，故不增加虚构的聚类资产或置信度测试。

1.4仅发布可比较的参考行，按明显偏离、略偏离、常见排序，最多八行。退化区间、未知比较状态的原始记录仍保留在JSON和A1。主分析与独立谱的数值分开显示。口径提示中的“本节”与禁用词冲突，因此改用“此处”。

## 附录与兼容范围

A1保留参考方法、归一化、局限、bootstrap、批次和逐研究明细，以及原始丰度和参考文字；A2汇总词典条目；A3集中登记省略原因。A4按知识子图模式收图，内容为空时整节省略。引用通过现有 bibliography 出口追加，消费者来源从1001编号，避免改变既有模块编号。

## 逐小节知识子图

原「正文不插图、统一移入A4」要求已废止。`knowledge_graph.subsection_graph(document, chapter, sub, seeds)` 只从 display_status=ready 的主题候选中选图，先合并允许/已引用的文献 claim；失败或重复时按 seeds 命中边数、边数、平均置信度选单图。边排序复用相关度和置信度，并给端点命中正文实体的边增加60分。同章或相邻小节签名重复时改选下一候选，无替代时不显示占位字，并登记 `no_ready_subgraph`。

1.1以菌种小档案的菌为seeds；1.2以第一优势菌为seeds；1.4只用明显偏离常见范围的菌。2.1/2.2使用正文的多样性与组成概念；2.3使用三栏实际展示的前三名贡献菌及相应产物。中文名和学名均参与匹配，图中标签只用中文。隐藏的1.3不参与选图；原2.4仍合并至2.3。

`GRAPH_TOPICS[(1,4)]` 补充 composition.species、composition.dominance。`GRAPH_TOPICS[(2,3)]` 采用 metabolites.scfa（butyrate/丁酸）、nutrient_metabolism.fiber（纤维、抗性淀粉及多糖底物）、metabolites.intermediates（lactate/乳酸）；三者均来自既有TOPIC_KEYWORDS，不创建topic或证据ID。乳酸topic也包含琥珀酸，只作为原有候选范围，seeds加权不新增乳酸利用关系。

每图位于小结之后、下一标题之前，图题为「图 X-Yk  与本节相关的研究知识」。首次子图后显示G4已审核条目「知识子图」的完整读图说明，全报告只出现一次。正文节点字号和节点类型字号单独放大，结合PDF实际图片缩放验证至少9pt。正文图在 `consumer.subsection_graphs` 中另存候选、得分、命中的seeds和最终图，原 `sections[].topics[].knowledge_subgraph` 不裁剪。后续加入CONSUMER_CHAPTERS的普通章节自动走共享出口，自定义渲染器复用 subsection_graph_markdown 并提供实际展示的 graph_seeds。

第3章任务已覆盖此前保留红色的约定：全报告图谱的「抑制与降低」改用琥珀色 #b47a24，「疾病与结局」节点改用灰色。关系和节点语义保持不变。

## 第3章与 G13–G15

`consumer_chapter_three.prepare()` 把展示副本写入 `consumer.chapter_three`；旧表和支持记录完整保留于 `raw_legacy_tables`，A1分列两套丰度、参考人数、百分位和检出证据。`refresh_word_section()` 只更新旧报告的第3章解读视图，不覆盖其他章节的既有解读。

G13 `consumer_graph.consumer_graph_filter(graph,seeds)` 只删减正文副本。删除研究分组、探针/编号、结构性关系、远离seeds的Other节点及无seeds分量，最多保留两个分量；不足两条边隐藏并登记 `subgraph_too_sparse`。先清洗再校验剩余中文标签，避免被即将删除的RiCBM等编号阻断。pending边用虚线，approved边用实线，正文不写“待审核”。节点、关系标签和图例进行边界/碰撞检查；审计在 `consumer.graph_filter_audit` 和A1。

G14 唯一面板 `knowledge_base/consumer_key_taxa.yaml` 是版本化JSON兼容YAML。它同时提供G11的 `butyrate_producer` 名单，不再从词典另维护该标签。消费者层按完整主分析种谱匹配属/种和明确别名；`catalog.py`、`chapter_three.selected_rows()` 和旧路径不变。参考位置只读取G10预计算类别分布，按同一已校验、排除本人的参考层选择，面板SHA过期则隐藏参考位置，不在运行时重拟合。

“本次未检出”必须同时满足：QC明确通过、`taxonomy.complete is True`、完整谱没有任何该类成员。未知QC、残缺分类谱或零值成员记录均不发布未检出。估算reads徽标仅接受专用estimated字段；面板默认阈值为高≥1000、中≥100、低<100。缺字段隐藏并登记G6；后续流程若需徽标，应开启MetaPhlAn `rel_ab_w_read_stats`，本任务不重跑。

G15 `consumer_badges.research_badge()` 按独立论文去重，物种级≥3为“多项研究”、1–2为“少量研究”、只有属级为“同属研究推断”。编辑来源不计研究，菌株证据不升级为物种证据，没有可见one_liner不显示徽标。

`Glossary.get_watch_note()` 复用检索顺序和缓存，但用 `watch_review_status` 独立审核；新生成的watch_note始终pending，不随one_liner已审核而自动通过。正文只发布已审核字段，空值静默隐藏并登记G6；B.fragilis使用用户提供的固定说明，指向“请看第4章”，不预判检测结论。样本验收、分类名核对和待审草稿见 [CONSUMER_CH3_CHANGELOG.md](CONSUMER_CH3_CHANGELOG.md)。

“全报告消费者规则”与“不改第2–13章输出”发生范围冲突时，当前只对已启用的章节应用消费者规则。其余章节的旧空状态、方法段及图谱位置暂保留，后续逐章迁移。旧章节规则兜底保持兼容；第1章不再使用原始行拼接兜底。

## 仅刷新展示

```bash
.venv/bin/python scripts/refresh_report_presentation.py ZYMO_D6331 \
  --report-path /path/to/results/ZYMO_D6331_report.json \
  --preserve-other-chapters
```

新增参数逐字节复用已有非消费者章节图片；默认调用保持兼容。缺少待保留图片时失败，不悄悄替换。报告仍先在暂存目录完整生成再发布；不启动生信分析。预览可通过进程环境中的 WGS_RESULTS_DIR 指向独立目录。
