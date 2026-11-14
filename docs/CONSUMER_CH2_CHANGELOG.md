# 第2章消费者改版与验收记录

分支：`feat/consumer-ch2`。基线：`feat/consumer-ch1` 的已完成提交 `a11a4eeac8b0a13509cdc5fd255cbeb6d8f931aa`。

工作目录：gpu02 上的 `/home/zhanghaiyang/fmt-healthcare-agent-consumer-ch2`。第一章原工作目录未切换分支、未写入文件。稳定基线集成采用 rebase，无冲突；暂存恢复成功。创建、每轮文件写入、锁检查、文件前后 SHA 和提交均保留审计。

远端报告与机器验收记录位于 `tmp/consumer-ch2/export/after/`；本地交付包内的同名JSON与页面文件便于直接审阅。

## 结果

- 第二章改为「菌群的多样性与分工」，正文为两页，位于新报告第8–9页。
- 原2.3与2.4合并；原 `word.2.3`、`word.2.4` 与证据 ID 保留，2.4标记为合并到2.3。目录和正文不再呈现2.4。
- 正文只显示菌种数、综合多样性和均衡度；原始四项指标及主分析、参考统计进入A1。
- 组成典型度使用3537人留一法分布。样本百分位为95.5895，边界不确定，按共享G2规则降档为「少见」。
- 功能取数改为全部命中通路聚合，补充已有UniRef记录的关键酶证据。正文不展示贡献百分比、通路编号或注释覆盖缺口。
- 乳酸利用缺少可核对的物种贡献记录，对应流程栏隐藏并记录G6。不能据此判为缺少乳酸利用能力。

## 文件及作用

| 文件 | 作用 |
|---|---|
| `src/wgs_agent/reporting/cmd_derived.py` | G10离线float32分块距离、留一法典型度、第一优势菌与前五合计分布、SHA校验、排除本人后的缓存距离复用 |
| `scripts/prepare_cmd_reference.py` | 在原参考资产准备入口增加 `--derive-from` 和 `--block-size` |
| `src/wgs_agent/reporting/cmd.py` | 复用原人群筛选、本人排除、最少30人和bootstrap；一次目标距离向量用于典型度和散点图 |
| `src/wgs_agent/reporting/ordination.py` | 接收离线参考距离与目标距离，保留原PCoA/Lingoes技术记录 |
| `src/wgs_agent/reporting/functional_metrics.py` | G11 `aggregate_category()`、精确通路分类、单位不一致分支、酶标记集合与覆盖缺口 |
| `src/wgs_agent/reporting/consumer_markers.py` | 复用第12章严格UniRef解析和EC映射，只读既有数据，排除异常行，不调用生信程序 |
| `src/wgs_agent/reporting/consumer_basis.py` | G12 `comparison_basis_note(document, chapter)` |
| `src/wgs_agent/reporting/consumer_chapter.py` | 第一章1.4改用G12组件 |
| `src/wgs_agent/reporting/consumer_chapter_two.py` | 三指标、典型度、功能阶段、确定性兜底、隐藏登记和A1明细 |
| `src/wgs_agent/reporting/consumer_copy.py` | 第二章标题、导语、writing_focus、章节专用规则、60%与3种菌配置 |
| `knowledge_base/consumer_glossary.yaml` | 七项指定概念、阶段意义及功能标签，均以approved方式复用G4服务 |
| `src/wgs_agent/reporting/chapter_two.py` | 在原准备流程中接入消费者数据，原始结果接口保留 |
| `src/wgs_agent/reporting/word_template.py` | 第二章消费者正文、原2.3/2.4证据合并、原ID映射与段落接口 |
| `src/wgs_agent/reporting/word_figures.py` | 复用并扩展 `draw_tier_scale()` 的格式化值与颜色；按消费者层输出第二章图 |
| `src/wgs_agent/reporting/template_body.py` | 同步第二章标题和三个可见小节元数据 |
| `src/wgs_agent/reporting/consumer_appendix.py` | 在共享A1中加入第二章明细；继续使用A2–A4 |
| `src/wgs_agent/reporting/narrative.py` | 复用G1/G7/G8，第二章规则只在第二章生效，合并后的2.4不单独请求生成 |
| `src/wgs_agent/tools/report_maker.py` | 第二章复用消费者说明框、Markdown强调与小字样式 |

## 样本实际命中的通路

全部来自既有 `ZYMO_D6331_pathabundance.tsv` 与 `ZYMO_D6331_pathabundance_relab.tsv`，两份文件的通路贡献行计数一致。

| 类别 | ID | 名称 | 物种贡献行 |
|---|---|---|---:|
| 丁酸合成 | PWY-5676 | acetyl-CoA fermentation to butanoate II | 0 |
| 丁酸合成 | P163-PWY | L-lysine fermentation to acetate and butanoate | 1 |
| 丁酸合成 | CENTFERM-PWY | pyruvate fermentation to butanoate | 0 |
| 乳酸利用 | PWY-8086 | (S)-lactate fermentation to propanoate, acetate and hydrogen | 0 |
| 复杂多糖降解 | PWY-6731 | starch degradation III | 3 |

核对的另外两条丁酸路线 `P162-PWY` 与 `PWY-5022` 在本样本中均不存在。复杂多糖类别在本样本确实只命中一条通路；新接口不会为扩大类别而加入淀粉合成、脂多糖合成等不相符的路线。

`PWY-5022` 是4-aminobutanoate degradation V，应按丁酸生成路线明确纳入。原先笼统排除全部aminobutanoate会误排这一路线；其他生成琥珀酸等产物的GABA降解路线仍排除。采用精确ID与精确名称例外，不放宽整个底物正则。

分类核对依据：[MetaCyc通路登记](https://targetstatus.ssgcid.org/Pathway/PWY-5022)、[MetaCyc乳酸利用通路](https://solcyc.sgn.cornell.edu/META/NEW-IMAGE?object=PWY-8086&type=PATHWAY)。MetaCyc主站的PWY-5022详页需要登录，因此该项分类仍列为人工复核项。

## 修复前后贡献者

| 类别 | 修复前 | 修复后 |
|---|---|---|
| 丁酸合成 | 只选P163-PWY；Fusobacterium nucleatum为唯一已记录贡献者，显示100% | 汇总三条丁酸路线；通路直接贡献者仍为F. nucleatum；EC标记补充Bacteroides fragilis、Clostridioides difficile、Escherichia coli、Prevotella corporis，共5个已命名贡献者 |
| 乳酸利用 | PWY-8086存在，但没有贡献物种 | 确认原始数据也没有物种贡献行；不编造物种或比例，正文隐藏此栏，A1保留通路总量与缺口 |
| 复杂多糖降解 | PWY-6731的E. coli、B. fragilis、C. difficile | 全类别扫描后仍只有同一条通路与同三种菌；已有贡献内比例为66.3705%、29.8386%、3.7909% |

酶证据来自既有基因家族表和本地EC映射，使用第12章已有的严格解析器：

- EC 2.7.2.7：B. fragilis、P. corporis、C. difficile。
- EC 2.8.3.8：E. coli、C. difficile，另有未分类贡献。
- 原输入有两条非标准UniRef记录，已隔离，不参与计量。原 `functional_modules` 的invalid_input状态没有被覆盖。
- 酶数量与通路数量不混加；酶补充者的通路级占比为未知，排在有可用通路占比者之后。

普拉梭菌（Faecalibacterium prausnitzii，主分析13.295725%）仍未出现在以上通路或两种关键酶的物种贡献中。原因是现有注释覆盖限制，不能由菌种丰度替代基因证据。罗氏韦荣球菌（Veillonella rogosae，24.777299%）同样记录乳酸类别的coverage_gap。A1保留两条缺口，并写明「基因注释可能遗漏部分菌。」

## 乳酸空项的根因

PWY-8086在原始和相对丰度文件中均有1条群落通路记录、0条物种贡献记录。现有解析没有丢行，category也能正确识别其乳酸利用方向。原有表格将这一数据缺口作为空行呈现，消费者容易误读。

修复包含全通路聚合、单位校验和既有关键酶证据接入；对于仍缺少原始物种证据的乳酸栏，按G6隐藏并保留审计。没有运行HUMAnN、MetaPhlAn、重新注释任务或其他生信程序。

## G10资产与重建

版本：`cmd-consumer-derived-v1`；参考人数3537；构建耗时12.935秒。

| 文件 | SHA256 |
|---|---|
| manifest.json | `81260d92e4bc6fc74b34c10f314d9350e438cd8c15cac10c223d1fc781a344d7` |
| metadata.tsv | `d0a1c6afd5ada8f46ad44efe8c3d0a600357570ad9f6313cd9a2e97a52764b99` |
| species_abundance.tsv | `a29cb8837eefaeacc4a9e9fe0f66b0cf345a86d76d9c3d4022236b024f8f8dee` |
| consumer_derived.json | `7679b7089837edc92dc588998ab4c4711a79a5baa71e8efe6f9a1017517aff1f` |
| consumer_distances.npy | `a753d4fff7c32c07426df1f64199118284f8f0f4418e0fe6d98624cffc8128cc` |

资产位于隔离工作目录的 `tmp/consumer-ch2/cmd-consumer-v1`，未替换生产参考资产。一次性重建命令，在gpu02的仓库根目录执行，输出必须是尚不存在的新目录：

```bash
PYTHONPATH=src /home/zhanghaiyang/miniconda3/envs/wgs-fmt-agent-v2/bin/python \
  scripts/prepare_cmd_reference.py \
  --derive-from /storageB/zhanghaiyang/fmtha-data/var/reference/cmd/native-v3 \
  --output /home/zhanghaiyang/fmt-healthcare-agent-consumer-ch2/tmp/consumer-ch2/cmd-consumer-rebuilt \
  --block-size 64
```

离线使用float32分块存储3537×3537距离；运行时一次样本距离向量复用于典型度和图示。本人排除后的参考中位数从离线缓存距离调整，不重新计算参考间距离。实际样本验证禁用了运行时 `pdist`，比较和图示仍成功。

新资产缺失、SHA错误、分层不符或不足30人时，典型度不发布，按G6登记；不以主分析谱替代。已有散点图仍可展示。原群落图的兼容接口保持原契约。

## 验收与原稿保护

- 正文G1与额外技术词扫描：0次；科学计数法：0次；Shannon：仅首次1次。
- 第二章2页；原2.4交叉引用：0次。
- 全量pytest：720通过、2项原有跳过，16项子测试通过；耗时128.03秒。28条警告来自原有Matplotlib测试字体，交付PDF与PNG已单独目视检查。
- 原始测量、全部证据ID和主题ID保留。第一章成品作为最终回归数据基线；仅第二章解读映射重建。
- `word_contract.json`与四份Word原稿只读；契约SHA256仍为 `98688cfd0b575b9d49b6b61e608d137e0c933cc405d7cc9d68707cdcb8281ffc`。
- `redundancy_rows()`的原输出接口保留。调用搜索只发现第二章自身和测试；未改版章节继续使用原有数据契约。精确的PWY-5022分类修正不影响本样本其他章节，因为该通路不存在。
- 最终测试汇总、Git提交和锁检查见 `test-summary.json`、`git-delivery.json`、`coordination-audit.json`。

## 旧断言逐项调整

| 测试 | 调整原因与保留的验证 |
|---|---|
| test_chapter_two：diversity_figure_contains_both_profiles… | 空「丰富度估计」表不再留在正文；改查三指标和首次Shannon；原始两套数值仍验证 |
| test_report_templates：template_chapters_replace… | 第二章标题改用consumer_copy，目录仍完整 |
| test_report_templates：contribution_concentration… | 无有效单位时隐藏；部分贡献占比保留描述范围，正文不展示80%或参考结论 |
| test_report_templates：rendering_preserves_graph_objects… | G4增加引用，改在渲染后核对完整书目；图谱对象逐项保持不变，A4存在 |
| test_word_template：complete_word_contract… | 原稿现有52表、28图表、9流程；只更新过时计数，不改契约 |
| test_word_template：every_word_field… | 消费者空图隐藏；第三章原本允许三个空表；校验实际引用图像均存在 |
| test_word_template：directions_and_contribution… | 现行组胺表按合成/分解标明方向；部分功能记录保持原范围，不伪造完整性 |
| test_word_template：subunit_abundance… | 校验现行原稿配色247A94，不再硬编码旧246A73；微量柱形仍须可见 |
| test_health_report：两项标准聊天/后端修复测试；test_word_template：model_uses_word_subsections… | 测试假回复同时遵守第二章G1消费者规则，保留生成、重试与协议验证 |
| test_report_knowledge_graph：三项旧正文提示断言 | 图谱在结构化数据中保留，消费者使用A4；不再要求旧正文固定提示词 |
| test_agent_execution：real_subagent_runs_readonly… | 原只读工具集已加入fetch_knowledge_base，测试与现行接口同步 |
| test_chapter_seven：concurrent_report_edit… | 隔离结果目录，并隔离CLI关闭日志的进程级影响；保留并发写入中止验证 |
| test_fmt_triplet_online：三项路径默认值/回退断言 | 与现行data/fmt-matching规范路径一致；显式资源目录不回退到旧目录 |
| test_graph_presentation：unknown_english_fallback… | 现行图谱保留有来源的原文标签，验证source fallback审计而非丢弃关系 |
| test_litkg_full_acquisition：acquisition_drains… | 显式测试pending使用开关的开、关两种策略；采集内容始终完整保留 |
| test_report_module_integration：cache_recovery… | 补齐既有运行时路径桥接测试夹具；只使用假执行器，不运行真实生信任务 |

其中与本章设计无关的基线失败，已在接入消费者层前记录；只调整有现行代码或新设计依据的断言/夹具。其他章节生产行为未因这些测试修正而改变。

## 页面文件

- `before/`：原报告第11–13页。
- `after/`：新报告第二章第8–9页。
- `appendix/`：A1新增多样性、组成、功能和关键酶明细所在页面。
- `chapter2.pdf`：独立两页章节，便于审阅。

## 人工确认事项

1. 「多种菌分担」的≥3种、第一名<60%阈值是描述性编辑阈值，是否继续使用；可在FUNCTION_BACKUP中调整。
2. 关键酶标记只作补充证据，不能证明完整丁酸通路或实际产量；是否需要更严格的物种/菌株和底物专一性审核。
3. PWY-5022精确归类、五档典型度措辞及词典功能标签，建议由领域人员复核。
4. 普拉梭菌和罗氏韦荣球菌的覆盖缺口仍存在。如需补齐原始功能归属，应另行核查既有注释/参考覆盖；本次没有启动新生信任务。
5. 新资产未激活到生产配置；部署或切换参考目录不属于本次分支交付。
