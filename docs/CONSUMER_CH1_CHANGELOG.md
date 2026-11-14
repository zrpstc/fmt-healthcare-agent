# 第1章消费者展示改版交付说明

工作主机：gpu02。仓库：`/home/zhanghaiyang/fmt-healthcare-agent`。分支：`feat/consumer-ch1`。

ZYMO_D6331第1章由原PDF第5–10页的6页，缩短为新版第5–7页的3页。完整13章保留。逐字比较第2–13章Markdown正文一致；这些章节的既有图片以保留模式原样复用。原始 evidence 与 template_inputs 完全一致。Word原稿和word_contract.json没有改动。

隔离预览在 `tmp/consumer-ch1/after/`，交付文件在 `tmp/consumer-ch1/deliverables/`。线上原始报告没有替换，没有重启API/Web，没有启动新的生信任务。

## 验证结果与验收缺口

- 新增消费者测试：36项通过。
- 第1章、消费者基础设施、健康报告、参考比较与组成说明等相关测试：121项通过，0失败。
- 全量pytest：666通过、18失败、2跳过。
- 原始提交的独立快照基线：625通过、23失败、2跳过。最终18项失败全部属于原有23项失败，没有新增失败。
- 第1章正文禁用词命中为0；百分数精度检查通过；门水平堆叠条与集中度条的底层数值合计100%。
- PDF及逐页PNG已生成并查看；附录A1、A2、A3、A4的起始页分别为86、91、92、93。

“全量pytest通过”的验收条件尚未满足。没有通过删除测试、标记xfail或改变第2–13章/图谱行为来制造通过结果。完整失败编号另附机器可读摘要。基线和最终日志分别保存在 `tmp/consumer-ch1/baseline-tests.log` 与 `tmp/consumer-ch1/full-tests.log`。

## 肠型方案与口径

采用方案B。现有cMD参考资产的feature_level为species，校验文件仅含metadata.tsv和species_abundance.tsv，没有属级参考矩阵或经过验证的聚类中心。隐藏1.3，把优势菌属说明合入1.1，并在省略清单登记；未生成方案A的虚构资产。

1.2主分析前五种合计72.5%。单列的同口径比较谱前五种合计73.0%，高于约87%的参考人群，属于略高；这两套数值没有混算。1.4仅使用独立比较谱，口径提示只写一次。

## 改动文件及作用

| 文件 | 作用 |
| --- | --- |
| src/wgs_agent/reporting/consumer_format.py | 百分数、人数、参考位置和五档标签 |
| src/wgs_agent/reporting/consumer_copy.py | 章节展示文案、禁用词和写作焦点 |
| src/wgs_agent/reporting/consumer_state.py | 报告级名称登记、省略清单、可留空的消费者表格 |
| src/wgs_agent/reporting/glossary.py | 版本词典、来源顺序、压缩、缓存、审核闸门和引用编号 |
| src/wgs_agent/reporting/web_search.py | 默认关闭的白名单SearXNG检索和限量抓取 |
| knowledge_base/consumer_glossary.yaml | 版本化概念、大类和菌种解释种子词典 |
| src/wgs_agent/reporting/consumer_reference.py | 与原报告队列签名绑定的集中度比较 |
| src/wgs_agent/reporting/consumer_appendix.py | 方法、术语、省略项和迁移图谱的A1–A4出口 |
| src/wgs_agent/reporting/consumer_chapter.py | 第1章消费者数据、图形、自然中文兜底和正文 |
| src/wgs_agent/reporting/chapter_one.py | 既有第1章数据入口对接消费者载荷，保留旧API |
| src/wgs_agent/reporting/taxon_labels.py | 补全译名、首次提及学名和未命名菌描述 |
| src/wgs_agent/reporting/ordination.py | 优势菌属使用中文名称 |
| src/wgs_agent/reporting/narrative.py | 按章节启用消费者提示和数字校验，空数据不调用模型 |
| src/wgs_agent/reporting/word_template.py | 第1章覆写出口、写作焦点和确定性兜底接入 |
| src/wgs_agent/reporting/template_body.py | 目录和展示元数据使用新标题 |
| src/wgs_agent/reporting/word_figures.py | 通用刻度条、隐藏空图、保留其他章节图片的可选接口 |
| src/wgs_agent/reporting/document.py | 在既有附录范围接入A1–A4 |
| src/wgs_agent/reporting/bibliography.py | 现有文献出口追加消费者词典来源，保持编号稳定 |
| src/wgs_agent/tools/report_maker.py | 第1章提示框、拉丁名斜体和表格列宽 |
| scripts/refresh_report_presentation.py | 可选逐字节复用其他章节图片，继续先暂存后发布 |
| tests/test_consumer_reporting.py | 36项边界、来源、审核、空状态、数字及图片保留测试 |
| tests/test_chapter_one.py | 更新与集中度条、空状态隐藏、紧凑刻度条和方案B冲突的旧断言 |
| tests/test_health_report.py | 新章标题；模拟模型按消费者语气输出，支持摘录符合长度契约 |
| tests/test_word_template.py | 缺少可比较位置时，不推测参考中位数、隐藏比较载荷 |
| tests/test_community_ordination.py | 优势菌属中文译名断言 |
| tests/test_report_templates.py | 新标题和无法核对核心成员时隐藏图表的断言 |
| docs/CONSUMER_REPORTING.md | 配置、审核、缓存、兼容边界和刷新命令 |
| docs/CONSUMER_CH1_CHANGELOG.md | 本交付说明、验证、变更清单和限制 |

## test_chapter_one.py冲突断言逐条说明

1. 1.2.1图形模式从bars扩展为concentration，第一段仍保留第一优势菌真实占比。
2. 删除“未绘制核心检出圆环”占位文案断言，改为正文不出现且有core_definition_missing登记。
3. 1.4不再要求图片高度大于1500像素；八行紧凑刻度条保持可读且更短。
4. 方案B不再保留1.3正文；后续章节一致性比较明确在附录之前截止，因为附录是本次新增的交付内容。

## 冲突处理与待确认事项

1. 全局消费者规则与“不改第2–13章输出”冲突时，先保持未改版章节输出；公用接口已建立，后续逐章迁移。
2. 不改知识子图配色与“全报告禁止红色”冲突时，保留原图配色；第1章新图没有红色，旧图中的红色仅随原图迁入附录。
3. “口径说明”原句含禁用词“本节”，正文改为“此处”。100.0%与三位有效数字上限冲突时显示100%。人数仍保留精确整数。
4. 现有Word合同的实际表格/图形库存与部分旧测试断言不一致；没有改动合同来迎合测试。部分其他章节、LitKG状态策略、资源路径和部署脚本测试仍失败，需单独修复。
5. 人体普雷沃菌本次没有进入正文的可靠功能解释，表格解释格留空并登记。不能把空白理解为没有相关研究。
6. 词典种子已设置approved用于受控发布；自动生成内容仍为pending。上线前需要编辑确认中文译名、菌株/物种适用范围及科普措辞。此次仅生成隔离预览，没有线上发布。
7. 线上模型压缩、PubMed与SearXNG的真实网络联调没有在本次离线预览中启用；查询顺序、缓存、闸门、重定向白名单和超限行为已用可控测试验证。

后附本次实际采用的glossary条目与全部PNG链接。使用方法详见CONSUMER_REPORTING.md。

## 本次实际采用的glossary条目

| term | one_liner | 来源 | review_status |
| --- | --- | --- | --- |
| relative_abundance | 某种菌占全部微生物的比例，不等于它的绝对数量。 | 健康报告消费者术语编辑规则 (consumer-editorial-v1) | approved |
| taxonomic_ranks | 门是大类，属是较小的类，种是更具体的成员。 | 健康报告消费者术语编辑规则 (consumer-editorial-v1) | approved |
| reference_population | 用于比较的一组人，帮助了解您的结果是否常见。 | 健康报告消费者术语编辑规则 (consumer-editorial-v1) | approved |
| enterotype | 按整体菌群组成作出的描述性分类，不代表好坏。 | 健康报告消费者术语编辑规则 (consumer-editorial-v1) | approved |
| bacillota | 成员多样，包括粪杆菌和韦荣球菌等。 | NCBI Taxonomy: Bacillota (https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?name=Bacillota) | approved |
| bacteroidota | 包含拟杆菌和普雷沃菌等常见成员。 | NCBI Taxonomy: Bacteroidota (https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?name=Bacteroidota) | approved |
| pseudomonadota | 包含埃希菌等成员，具体作用因菌种而异。 | NCBI Taxonomy: Pseudomonadota (https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?name=Pseudomonadota) | approved |
| fusobacteriota | 包含梭杆菌等成员。 | NCBI Taxonomy: Fusobacteriota (https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?name=Fusobacteriota) | approved |
| verrucomicrobiota | 包含阿克曼菌等成员。 | NCBI Taxonomy: Verrucomicrobiota (https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?name=Verrucomicrobiota) | approved |
| actinomycetota | 包含双歧杆菌等成员。 | NCBI Taxonomy: Actinomycetota (https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?name=Actinomycetota) | approved |
| ascomycota | 这是一大类真菌，包含部分酵母。 | NCBI Taxonomy: Ascomycota (https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?name=Ascomycota) | approved |
| methanobacteriota | 包含产生甲烷的古菌，古菌与细菌不同。 | NCBI Taxonomy: Methanobacteriota (https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?name=Methanobacteriota) | approved |
| veillonella rogosae | 可产生乙酸和丙酸，最早从口腔菌斑中分离。 | Veillonella rogosae sp. nov., an anaerobic, Gram-negative coccus isolated from dental plaque (https://pmc.ncbi.nlm.nih.gov/articles/PMC2884930/) | approved |
| bacteroides fragilis | 能利用部分复杂糖类，是肠道常见成员之一。 | Genomic analysis of Bacteroides fragilis reveals extensive DNA inversions regulating cell surface adaptation (https://pubmed.ncbi.nlm.nih.gov/15466707/) | approved |
| faecalibacterium prausnitzii | 部分菌株能利用乙酸参与丁酸的生成。 | Contribution of acetate to butyrate formation by human faecal bacteria (https://pubmed.ncbi.nlm.nih.gov/15182395/) | approved |
| escherichia coli | 部分菌株能在有氧或缺氧环境中生长。 | Respiration of Escherichia coli in the Mouse Intestine (https://pmc.ncbi.nlm.nih.gov/articles/PMC2044527/) | approved |

## PNG交付索引

改版前为第5–10页；改版后为第5–7页。附录按实际PDF页码导出全部延续页。


before-chapter-one：

- [before-chapter-one-page-005.png](before-chapter-one-page-005.png)
- [before-chapter-one-page-006.png](before-chapter-one-page-006.png)
- [before-chapter-one-page-007.png](before-chapter-one-page-007.png)
- [before-chapter-one-page-008.png](before-chapter-one-page-008.png)
- [before-chapter-one-page-009.png](before-chapter-one-page-009.png)
- [before-chapter-one-page-010.png](before-chapter-one-page-010.png)

after-chapter-one：

- [after-chapter-one-page-005.png](after-chapter-one-page-005.png)
- [after-chapter-one-page-006.png](after-chapter-one-page-006.png)
- [after-chapter-one-page-007.png](after-chapter-one-page-007.png)

after-appendix：

- [after-appendix-page-086.png](after-appendix-page-086.png)
- [after-appendix-page-087.png](after-appendix-page-087.png)
- [after-appendix-page-088.png](after-appendix-page-088.png)
- [after-appendix-page-089.png](after-appendix-page-089.png)
- [after-appendix-page-090.png](after-appendix-page-090.png)
- [after-appendix-page-091.png](after-appendix-page-091.png)
- [after-appendix-page-092.png](after-appendix-page-092.png)
- [after-appendix-page-093.png](after-appendix-page-093.png)
- [after-appendix-page-094.png](after-appendix-page-094.png)
- [after-appendix-page-095.png](after-appendix-page-095.png)

## 尚未通过的原有测试

以下18项在原始基线中均已失败：

- `tests/test_agent_execution.py::test_real_subagent_runs_readonly_and_returns_to_primary`
- `tests/test_chapter_seven.py::test_concurrent_report_edit_aborts_before_publication`
- `tests/test_chapter_two.py::test_diversity_figure_contains_both_profiles_and_true_reference_statistics`
- `tests/test_fmt_triplet_online.py::test_triplet_resources_follow_portable_root[False-WGS_FMT_RESOURCE_ROOT]`
- `tests/test_fmt_triplet_online.py::test_triplet_resources_follow_portable_root[False-FMT_ROOT]`
- `tests/test_fmt_triplet_online.py::test_triplet_resources_keep_fresh_workspace_defaults`
- `tests/test_graph_presentation.py::test_unknown_english_fallback_is_hidden_instead_of_leaking_to_image`
- `tests/test_litkg_full_acquisition.py::test_acquisition_drains_every_page_and_preserves_all_statuses_and_predicates`
- `tests/test_report_knowledge_graph.py::test_graph_contains_only_relevant_actual_claims_and_valid_endpoints`
- `tests/test_report_knowledge_graph.py::test_missing_results_and_title_only_references_do_not_create_edges`
- `tests/test_report_knowledge_graph.py::test_malformed_service_payload_does_not_break_report`
- `tests/test_report_module_integration.py::test_cache_recovery_runs_all_supplements_without_base_pipeline`
- `tests/test_report_refresh.py::test_reports_and_downloads_are_not_cached`
- `tests/test_report_templates.py::test_contribution_concentration_requires_complete_consistent_units`
- `tests/test_word_template.py::test_complete_word_contract_without_example_measurements`
- `tests/test_word_template.py::test_every_word_field_and_visual_has_a_missing_data_state`
- `tests/test_word_template.py::test_directions_and_contribution_denominators_remain_separate`
- `tests/test_word_template.py::test_subunit_abundance_is_visible_and_labels_have_space`
