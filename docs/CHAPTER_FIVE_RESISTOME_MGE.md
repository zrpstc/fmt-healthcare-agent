# 第五章排查与实现记录

2026-11-04，gpu02，`/home/zhanghaiyang/fmt-healthcare-agent`。

结论：两个现有样本都有原始双端 FASTQ 和去宿主 reads。原问题主要是**专用生信模块、参考库及结果加载链路缺失**，不是单独的前端展示问题。现已补齐现有数据可支持的获得性耐药基因和 IS/MITE 筛查，并更新实际报告。

## 根因与边界

- 报告已有耐药/MGE 展示逻辑；输入契约是 `resistance.genes`、`mobile_elements.results`，`amr` 是报告内部证据组。此前没有流程产生这些样本结果，也没有加载器接入它们。
- MetaPhlAn 物种组成、HUMAnN 通路产物不能替代专用耐药/MGE 注释。
- 当前补齐的是 reads 对参考序列的筛查。完整质粒、整合子、复杂转座子、耐药点突变、宿主归属及基因—元件物理连锁仍没有相应结构证据，报告明确标注范围，未用同一样本中的共检出代替物理连锁。

## 已实现

新增 `src/wgs_agent/pipeline/resistome_mge.py`、`src/wgs_agent/reporting/chapter_five.py`、参考库构建脚本、第五章专用离线刷新脚本和测试。

流程为：去宿主 reads → Bowtie2 比对 → 支持 reads、覆盖广度、一致性和 MAPQ 过滤 → 结构化结果 → 输入加载/历史分析刷新 → 第五章 Markdown/PDF。普通处理和已有主流程产物的恢复路径均已接入；第五章失败会保留明确状态，不阻断原主流程。

参考库采用官方 ResFinder 数据库和固定版本 MGEdb 1.1.1。合并完全相同或反向互补的参考序列；MGE 筛查限于 IS/MITE，避免把整段 ICE/转座子携带的耐药货物当成独立元件证据。此实现使用数据库进行 Bowtie2 筛查，并非调用 ResFinder 或 MobileElementFinder 应用程序。[ResFinder 官方文档](https://raw.githubusercontent.com/genomicepidemiology/resfinder/master/README.md)、[MGEdb 官方说明](https://pypi.org/project/MGEdb/1.1.1/)、[MobileElementFinder 官方说明](https://pypi.org/project/MobileElementFinder/)。

默认阈值：支持 reads ≥3、参考覆盖广度 ≥80%、一致性 ≥90%、MAPQ ≥20。丰度为 RPKM，不是细胞相对丰度。多重比对及高度相似等位参考会受到保守过滤；未达标不能解释为不存在任何耐药机制。

## 实测结果

| 样本 | 去宿主 reads | 达标耐药参考组 | 达标 IS/MITE 参考组 |
|---|---:|---:|---:|
| test2 | 162,854 | 0 | 0 |
| test_complete_data | 6,399,734 | 0 | 37 |

参考库分别含 3,205 和 5,360 个去重参考序列。37 指参考组信号，不代表 37 个独立基因组位点或完整可转移元件。两个样本均为 `completed`；低于阈值的候选未作为阳性报告。

已更新 `var/results/` 下两份样本的分析 JSON、报告 JSON、证据 JSON、Markdown 和 PDF。主 API 的 Markdown/PDF 下载均为 HTTP 200，并能读取新版第五章。JSON 保留完整结果列表；正文表格按现有展示规则截取前若干项。

## 验证与并发保护

94 项相关测试通过，包括真实 Bowtie2 阳性/阴性、覆盖广度、低质量和多重比对过滤、缓存、损坏数据库、样本隔离、状态区分及正式报告渲染。另有 11 项既有合同、绘图、参考比较和模型测试失败，均通过修改前源码复现，未修改其他章节来消除这些失败。

已逐项确认：第五章之外的 Markdown 不变，其他章节 JSON 不变，其他分析字段不变。PDF 文件有效且能提取到新结果。共享文件在写前备份、校验语法并比对内容；报告使用已有样本报告锁及写前比对。没有提交 Git、重置用户修改或操作另一预览服务。

代码备份位于 `tmp/chapter5-code-backup-20261104T020949Z/`；报告备份位于 `var/results/.chapter5-backup-<sample>-<timestamp>/`。

## 后续使用

以下命令在 gpu02 项目目录执行，使用有权读取对应样本的账号：

```bash
PYTHONPATH=src .venv/bin/python -m wgs_agent.pipeline.resistome_mge \
  --sample-id SAMPLE --output-root var/bioinformatics --threads 4

PYTHONPATH=src .venv/bin/python scripts/refresh_chapter_five.py \
  --report-path var/results/SAMPLE_report.json \
  --output-root var/bioinformatics
```

新上传样本由工作流自动调用。若以后扩展到物理连锁，主路线应增加样本组装及 contig 上的 ARG/MGE 定位，再结合 MAG/宿主分类证据；报告只在证据成立时展示共定位，不据此直接认定发生了水平转移。
