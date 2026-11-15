# 报告中的相关知识子图

健康报告默认 inline 模式。已改版章节在每个小节末尾、小结之后展示最多一幅中文知识子图，原「全部移入A4」要求已废止。正文不列证据原句、技术 ID、来源表格或 REST 地址；报告末尾按一级模块汇总参考文献。网页预览、Markdown 和 PDF 使用同一份内容；结构化报告保留原始证据与图谱事实。

## 筛选范围

- 优先使用模型解读实际引用的 Claim。没有文献引用的检测说明展示该主题的相关文献关系，并明确标为相关关系。
- 匹配依据为该主题的检测实体、主题关键词与 Claim 的主客体，或者知识记录中明确填写的 `topic_ids`。文献标题、文件名和背景原句中的偶然提及不作为匹配依据。
- 原主题子图最多6条关系、12个实体；正文副本默认最多8个实体、6条边，可用 WGS_REPORT_GRAPH_BODY_MAX_NODES 调整节点上限，不裁剪附录和结构化原图。仅保留原始 Claim 的直接主客体关系，不扩展邻居，不生成推断边。
- 图中合并同一实体，按连通分量排布。节点尺寸随连接度和中文标签长度变化，图幅随组件大小调整。
- 不同实体类别使用不同节点颜色，关系类别使用不同边颜色，图底部提供中文图例。推测关系使用虚线。
- 否定、推测、不显著、未报告效应等标记保留；复杂实体、关系和属性仅在展示层简写，不修改原始主客体、方向和证据。
- 完整证据 ID、Claim ID、文档 ID、文件名、证据原句和页码保存在结构化报告及证据文件。
- 只选 display_status=ready 的候选。没有可用且不重复的中文正文图时不输出占位字，在 consumer_omissions 中登记 reason_code=no_ready_subgraph；缺少检测结果或质控失败的主题不展示子图。

## 小节选择与模式

共享函数 `subsection_graph(document, chapter, sub, seeds) -> dict | None` 合并CHAPTERS映射及consumer_copy.GRAPH_TOPICS的候选。仅合并候选已有 allowed_narrative_ids / narrative_evidence_ids，以伪topic复用build_topic_graph；其证据资格约束保持不变。边排序沿用_score、_confidence，端点命中实际正文seeds加60分。合并不可展示或签名重复时，按命中seeds的边数、边数、平均置信度依次选择单图；同章和相邻小节不重复相同签名。

无topic的1.4补充composition.species和composition.dominance；2.3补充metabolites.scfa（丁酸）、nutrient_metabolism.fiber（纤维/多糖底物）、metabolites.intermediates（乳酸）。补充ID均出自TOPIC_KEYWORDS，原因及每节候选/得分/seeds命中保存在变更说明和consumer.subsection_graphs。

`WGS_REPORT_KNOWLEDGE_GRAPHS=inline|appendix|off`，默认inline。inline下A4只列正文尚未展示的完整主题图，若某主题图全部claim已展示则不重复；appendix下全报告图谱集中到A4；off下全报告不显示子图。A4为空时整节省略。模式切换不删除结构化图谱。

图题使用「图 X-Yk  与本节相关的研究知识」。全报告首次出现时附G4已审核的「知识子图」说明：「圆圈是菌、物质或健康状态，连线是已发表研究报道过的关系；它帮助理解背景，不代表这些关系已在您体内发生。」正文图只用中文节点标签，节点文字在PDF中至少9pt。原关系语义、否定、推测和颜色不变；红橙色 #ca694f 对应「抑制与降低」，具体predicate由样本验收记录列明。

## 自动检索与回退

常规报告生成复用现有 `WGS_CLAIM_API_URL/TOKEN/KNOWLEDGE_BASE_ID/TIMEOUT` 配置。在生成模型解读前，对配置的知识库分页扫描 Claim，再只保留与报告主题匹配的记录。检索请求不发送样本测量值，也不调用全图接口。报告默认最多扫描 10000 条，可通过 `WGS_REPORT_GRAPH_SCAN_LIMIT` 调低；与其他检索工具的扫描上限相互独立。

设置 `WGS_REPORT_GRAPH_RETRIEVAL_DISABLED=1` 可关闭自动检索，仍会展示输入中已绑定的相关 Claim。接口异常时继续使用已绑定记录，报告生成不因此失败；审计字段 `audit.knowledge_graph_retrieval` 保存检索状态、已扫描条数、总条数、是否截断和新增记录数。扫描截断时不能把没有匹配解释为全知识库不存在相关证据。

原始输入哈希保持不变；自动检索记录另外保存选择结果哈希。新检索记录加入报告的 `evidence` 与 `references.matched_docs`，可供模型按现有主题引用协议使用。

## 图谱中文化

生成报告时，先对展示中用到的实体名、类型、关系名、属性去重，再分批交给环境变量配置的模型翻译为简体中文并简化。图谱翻译优先级为 `WGS_REPORT_GRAPH_LLM_BASE_URL/MODEL/API_KEY`、`WGS_REPORT_LLM_BASE_URL/MODEL/API_KEY`、`DEEPSEEK_BASE_URL/API_KEY` 与 `WGS_LLM_DEFAULT_MODEL`，最后回退到既有工作区模型。

模型只接收知识标签、类型及属性，不接收样本编号、检测数值或完整报告。输出绑定固定标签 ID，检查中文和长度；未通过的条目最多修复一次。复杂缩写可用中文核心名称或可区分的中文实验组别展示别名，完整原名留在结构化数据。知识库的否定与推测等标记由程序保留。

缓存位于运行目录 `report-graph-labels/`，按模型服务、模型和翻译协议隔离，文件权限为 `0600`。重复生成报告复用有效中文标签。`WGS_REPORT_GRAPH_LLM_DISABLED=1` 单独关闭图谱模型请求，`WGS_REPORT_LLM_DISABLED=1` 只关闭正文模型解读。没有完整中文标签的子图显示暂不可用，避免夹杂未翻译英文。状态及未通过条目保存在 `audit.graph_translation`。

## 模块参考文献

`bibliography.py` 从各模块实际引用的文献及相关子图提取来源，在模块内按 DOI、PMID、题名等去重。文末按“模块名称 → [1] 作者. 题名. 期刊, 年份. DOI.”排版为独立段落，不输出正文证据列表。知识输入和 LitKG Claim 中已有的题名、作者、期刊、年份、卷期页、DOI、PMID 会保留；未提供的字段直接省略，不让模型补造。原论文题名保留来源语言。

## 产物与发布

- `sections[].topics[].knowledge_subgraph`：`nodes/edges/selection/candidate_count/truncated/figure`。
- `{sample_id}_report_evidence.json` 中的 `knowledge_subgraphs`：同一份子图快照。
- `module_bibliographies`：按模块汇总的参考文献及证据 ID 映射；`graph_label_translations`：中文显示标签。两者同时保存到结构化报告和证据文件。
- `{sample_id}_{topic_id}_kg_{digest}.png`：与报告同目录的图片，摘要来自图谱内容。已有图片接口及报告预览直接支持这些文件名。
- 图表和报告先在同一暂存目录生成；PDF 成功后再发布。PDF 生成失败时保留上一版报告。内容寻址的图片名保证新版本图片不会覆盖旧版报告依赖的不同内容。
- PDF 按报告目录解析相对图片路径；图片访问仍限定在报告目录内。产物权限为 `0600`。

修改后需重启 workspace-api 才能加载新的 Python 模块。无需修改或重新构建 Web 前端。已有报告需在网页点击“重新生成报告”后才会出现子图。

## 验证

```bash
# 合成数据、已绑定知识，默认不请求模型和知识服务
PYTHONPATH=src .venv/bin/python scripts/preview_health_report.py --output-dir tmp/offline-preview
# 合成数据，读取当前知识库的真实 Claim，不调用模型
PYTHONPATH=src .venv/bin/python scripts/preview_health_report.py --use-knowledge-graph --output-dir tmp/graph-preview
# 只调用环境模型翻译图谱，不调用正文解读模型
PYTHONPATH=src .venv/bin/python scripts/preview_health_report.py --use-knowledge-graph --use-graph-llm --output-dir tmp/chinese-graph-preview
# 单独隔离运行目录，避免测试读取线上私有运行数据
WGS_WORKSPACE="$PWD/tmp/report-tests" WGS_REPORT_GRAPH_RETRIEVAL_DISABLED=1 WGS_REPORT_GRAPH_LLM_DISABLED=1 \
  .venv/bin/python -m pytest tests/test_graph_presentation.py tests/test_report_knowledge_graph.py tests/test_health_report.py \
  tests/test_claim_report_references.py tests/test_report_refresh.py
```
