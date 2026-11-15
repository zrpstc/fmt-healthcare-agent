# 消费者逐小节知识子图修复与验收

分支：`fix/consumer-inline-subgraphs`。起点：已同步的main `7504fde`。

第1、2章独立渲染器曾绕过Word finish()唯一的子图出口，且旧默认appendix把消费者图汇总至A4。本次按新产品要求恢复小节末尾插图；Word原稿、word_contract.json、topic/evidence ID和原始关系语义保持不变。

## 实现

- knowledge_graph.subsection_graph()共享选择：原CHAPTERS主题加GRAPH_TOPICS补充映射；仅考虑display_status=ready且可用的既有图。
- 将候选允许/已引用claim并集交给原build_topic_graph构建伪topic。原证据资格约束不变；正文专用参数控制最多8节点、6边。边排序保留待审优先级，使用原相关度、置信度和60分seeds端点命中加权。
- 合并不可展示或签名重复时，单图按seeds命中边数、边数、平均置信度选择。签名按知识库、claim和关系端点身份规范化；同章及实际相邻小节去重，不把属级关系误记为物种命中。
- 原始topic图完整保留；正文图另存consumer.subsection_graphs，含每节全部候选、就绪状态、逐边分数、命中seeds、最终签名与图片。
- 两章在小结后、下一标题前调用共享出口。1.3隐藏，2.4仍合并。后续加入CONSUMER_CHAPTERS的普通Word章节自动使用共享finish出口，自定义渲染器复用同一Markdown函数。
- inline为默认，正文逐节最多一幅，A4只列正文未展示的完整主题图；appendix集中到A4；off全报告不显示子图。空A4整节省略。无图时无占位字，登记no_ready_subgraph。
- G4增加approved的「知识子图」条目，完整读图说明仅在全报告首幅图之后出现一次。
- 正文专用布局使用单列连通分量，扩大中文节点框与类型字号，分开并行边并避让关系标签；原图配色及关系不变。复用第10章既有乙酰胆碱、去甲肾上腺素、5-羟色胺中文名，避免命中正文菌种的claim因标签不齐退回无关图。
- 展示刷新证据文件新增consumer_subsection_graphs，原knowledge_subgraphs不裁剪。同步更新概览、知识子图文档和共享基础设施指南。

## 无topic小节的补充映射

| 小节 | 补充topic | 选择理由 |
| --- | --- | --- |
| 1.4 | composition.species、composition.dominance | 与明显偏离的具体菌及组成优势相关；只改变展示候选范围 |
| 2.3 | metabolites.scfa | TOPIC_KEYWORDS已有butyrate、丁酸和短链脂肪酸，最接近丁酸产物 |
| 2.3 | nutrient_metabolism.fiber | 已有cellulose、xylan、pectin、inulin、resistant starch、纤维和抗性淀粉，覆盖膳食多糖底物 |
| 2.3 | metabolites.intermediates | 已有lactate、乳酸，覆盖乳酸中间产物；也包含琥珀酸，仍通过实际seeds加权，不据此新增利用关系 |

没有新增topic或证据ID，没有扩展知识邻居或推断边。与允许claim无关的seeds不能让一条关系越过证据闸门。

## ZYMO_D6331实际选图

通过scripts/refresh_report_presentation.py，基于上一版第2章成品在隔离目录重新生成，保留其他章节已有Word图。没有重跑生信分析或知识检索。

| 小节 | 候选topic | 结果 | 节点/边 | 命中边数 | 合计排序分 | 命中seeds |
| --- | --- | --- | --- | --- | --- | --- |
| 1.1 | composition.phyla、genera、species | 合并图，报告第6页 | 7/6 | 6 | 653.5 | 普拉梭菌/Faecalibacterium prausnitzii、大肠埃希菌/Escherichia coli |
| 1.2 | composition.dominance | 无文献边，省略 | — | — | — | 第一优势菌罗氏韦荣球菌/Veillonella rogosae作为seeds保留审计 |
| 1.4 | composition.species、dominance | 合并图，报告第9页 | 8/6 | 3 | 477.0 | 大肠埃希菌/Escherichia coli |
| 2.1 | diversity.richness、shannon、simpson、evenness | 未绑定可用文献边，省略 | — | — | — | 多样性、丰富度、均衡度等 |
| 2.2 | diversity.reference | 主题无可用结果/文献边，省略 | — | — | — | 组成典型度、菌群组成、健康人群等 |
| 2.3 | metabolites.scfa、nutrient_metabolism.fiber、metabolites.intermediates | 合并图，报告第12页；fiber主题缺数据，未参与 | 8/5 | 4 | 388.0 | butyrate；三栏实际贡献菌、产物的完整seeds列表另见JSON |

详细候选分数、未选原因、重复判定、逐条evidence ID和命中seeds保存在交付物subsection-selection.json；上表按同一份审计汇总，不把没有证据的图补造出来。排序分是既有文献相关度加展示权重，不是临床评分。

第1章为报告第5–9页，第2章为第10–12页；两章PNG与独立PDF均已导出。PDF正文节点及类型文字的实测最小字号约11.42pt，高于9pt；首次读图说明全文仅出现一次。Word原稿与合同不变，报告evidence逐项一致，原topic图nodes/edges逐项一致。

## 配色保留与人工事项

关系类别「抑制与降低」沿用红橙色#ca694f。该样本全报告其他子图实际出现的红橙predicate为INHIBITS；本次选中的三幅正文图没有该类边。疾病与结局节点仍保留粉红填充与#bd5367边框。以上均保持原样，由人工决定后续是否调整。

现有claim的待审核、推测、否定、研究条件和方向标记继续展示；没有把这些研究关系解释成已在本样本体内发生。若希望1.2、2.1、2.2也有图，应先由现有证据流程提供可用文献关系，本修复不扩展背景知识。

## 并发协作与验证记录

工作区在写入前逐次检查Git锁及本任务文件SHA256；不删除锁、不覆盖并发编辑。执行中另一个agent提交c3f148a（README、共享指南、正文模板说明及reporting/AGENTS.md），无代码重叠；保护检查曾拦住写入，核实纯文档提交后完整保留，阅读新指导并同步本指南。

远端审计：.git/consumer-inline-subgraphs-audit.jsonl，包含基线、文件前后SHA、写入拦截核查和并发提交保留记录。修复前文件备份位于.git/consumer-inline-backup。

测试覆盖：无topic映射、证据并集和闸门、seeds加权、同章/相邻图去重、无图无占位、三种模式、空A4、首次说明、重复渲染、未来章节自动接入、中文标签和节点/关系标签几何无重叠。最终全量统计及Git整合状态见交付物test-summary.json和git-delivery.json。

最终全量pytest：735 passed、2 skipped、28 warnings、16 subtests passed，129.02秒。警告来自既有测试的Matplotlib字体；交付页面单独完成目视检查。git diff --check通过，受保护原稿/合同无差异。

旧断言调整：test_consumer_reporting不再要求正文无图；test_report_knowledge_graph按inline/appendix/off分别检查；无可用已渲染图片时test_report_templates不再要求空A4标题。原始图谱及书目保留断言继续有效。

测试采用独立WGS_WORKSPACE与environment知识配置，pytest进程受控禁用真实dotenv加载。早期一次全量超时；一次隔离配置将PYTHON_DOTENV_DISABLED传给合成.env测试导致单项失败，已修正测试运行方式，不改无关测试或业务逻辑。各次原始日志留在tmp/consumer-inline下，过滤后结果纳入交付记录。
