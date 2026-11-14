# 消费者报告展示层（第1章）

消费者正文由 `consumer_copy.py` 和 `consumer_chapter.py` 覆盖；Word 原稿、word_contract.json、小节编号和证据主题 ID 不变。完整13章仍然保留。当前 `CONSUMER_CHAPTERS={1}`，未改版章节的文案、图谱和配色继续使用原实现。

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
| WGS_REPORT_KNOWLEDGE_GRAPHS | appendix | 当前已改版章节的图谱移至A4；off 隐藏这些图谱 |

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

A1保留参考方法、归一化、局限、bootstrap、批次和逐研究明细，以及原始丰度和参考文字；A2汇总词典条目；A3集中登记省略原因；A4放置第1章原有知识子图。节点、关系和配色实现未修改。引用通过现有 bibliography 出口追加，消费者来源从1001编号，避免改变既有模块编号。

“全报告消费者规则”与“不改第2–13章输出”发生范围冲突时，当前只对已启用的章节应用消费者规则。其余章节的旧空状态、方法段及图谱位置暂保留，后续逐章迁移。旧章节规则兜底保持兼容；第1章不再使用原始行拼接兜底。

## 仅刷新展示

```bash
.venv/bin/python scripts/refresh_report_presentation.py ZYMO_D6331 \
  --report-path /path/to/results/ZYMO_D6331_report.json \
  --preserve-other-chapters
```

新增参数逐字节复用已有非消费者章节图片；默认调用保持兼容。缺少待保留图片时失败，不悄悄替换。报告仍先在暂存目录完整生成再发布；不启动生信分析。预览可通过进程环境中的 WGS_RESULTS_DIR 指向独立目录。
