# 第 6 章“古菌、真菌与 DNA 病毒组”诊断与实现

检查日期：2026-11-04。主机：gpu02。项目：`/home/zhanghaiyang/fmt-healthcare-agent`。

## 结论

空章节主要由“结果提取与报告绑定未完成”以及“病毒分析步骤未启用”共同造成，不是缺少原始测序数据。两个现有样本均有可用的脱宿主 FASTQ、完整 MetaPhlAn 分类谱及本地参考数据库。

| 内容 | 原因 | 实测结果 |
|---|---|---|
| 古菌 | 模板预留输入，但没有从完整分类谱生成对应模块 | 两个样本现有标记物筛查均未报告古菌阳性 |
| 真菌 | 同样缺少谱系提取与接入 | 两个样本均未报告真菌阳性；参考库实际包含真菌分类条目 |
| 病毒 | 已安装 MetaPhlAn 4.2.4 和 VSG 参考文件，但工作流未启用 VSC 分析 | 补算后 test2 检出 2 个 VSC，test_complete_data 检出 14 个 VSC |
| DNA 类型 | 默认 VSC 输出不提供足以确认 DNA 类型的注释 | 保留为病毒候选，明确显示“DNA 类型未核实” |

“标记物筛查未检出”不能替换为“样本绝对不存在”；VSC 覆盖广度、覆盖深度也不能替换为微生物相对丰度。

## 已实现路线

1. 复用完整 MetaPhlAn 分类谱，按明确分类谱系提取古菌和真菌；不把所有真核生物当作真菌，不使用截断后的优势物种摘要。丰度保留原分类谱分母。
2. 在现有流程启用 `--profile_vsc`、`--vsc_out`、`--samout`，覆盖广度阈值为 0.75。MetaPhlAn 4.2.4 的必要 SAM 输出参数已通过实际运行核实。
3. 为已有缓存样本提供独立病毒补算入口，补算不覆盖原细胞微生物分类谱。两个现有样本已补算并导入新结果目录。
4. 输出 `archaea`、`fungi`、`dna_viruses` 三个结构化模块。区分未分析、结果异常、已完成未检出、检出；完成标记与样本和文件摘要绑定，旧生成缓存不能覆盖最新有效实测结果。
5. 补齐输入加载、报告生成器合并及 Word 表格绑定，最终 Markdown/PDF 显示对应状态、结果与检测边界；质控失败时不显示可判读的检测结论。
6. VSC 仅在有明确 `genome_type` 注释时确认 DNA 类型；当前无此注释的簇不虚构 DNA 类型、宿主或致病风险。全面 DNA 病毒分类仍需要版本可追踪的类型注释数据；完整真菌组也超出现有有限标记物库的覆盖范围。

## 文件与产物

新增核心模块：

- `src/wgs_agent/pipeline/non_bacterial.py`
- `src/wgs_agent/reporting/chapter_six.py`
- `tests/test_chapter_six.py`

共享文件仅插入第 6 章接入钩子：`reporting/inputs.py`、`reporting/template_body.py`、`reporting/word_template.py`、`tools/domain_tools.py` 和 `runtime/scripts/postfmt_pipeline/process_postfmt_sample.sh`。写入时读取最新文件、保留备份并比较并发修改，没有重置工作区或提交其他进程的改动。

真实结果：

- `var/bioinformatics/profiles/viruses/test2_vsc.tsv`
- `var/bioinformatics/profiles/viruses/test_complete_data_vsc.tsv`
- 同目录下对应的 `*_vsc.completed.json`
- `var/bioinformatics/profiles/non_bacterial/test2.json`
- `var/bioinformatics/profiles/non_bacterial/test_complete_data.json`

离线预览：`tmp/chapter6-20261104/previews/`。完整运行诊断保存在权限受限的项目临时目录中。未向外部模型发送样本数据。

## 验证

- 新增 17 个第 6 章测试全部通过，覆盖谱系、单位、异常值、缺失/阴性区分、完成标记、路径限制、旧缓存优先级、质控以及最终报告渲染。
- 相关测试共 60 个，52 个通过，8 个失败。8 个失败用例在移除本次接入钩子的隔离副本中也全部复现；未改动无关章节来消除这些既有失败。
- 工作流 shell 语法与当前源码语法检查通过。
- 离线 Markdown/PDF 已核对第 6 章检测状态、病毒覆盖指标及 DNA 类型限定说明。
- 待并行报告任务释放锁后，已使用项目现有脚本重启生产报告 API（8503）；健康检查返回 200。测试 API（18503）仍返回 200。
- 正式报告原文件未覆盖；新生成报告使用已启用的第 6 章链路。两个样本的新病毒结果已经落盘。

## 历史样本补算命令

从项目目录执行，使用有权读取样本结果的账号；新工作流会自动执行对应步骤：

```bash
.venv/bin/python -m wgs_agent.pipeline.non_bacterial \
  --sample-id SAMPLE_ID \
  --output-root var/bioinformatics \
  --ensure-viral \
  --metaphlan var/runtime/envs/fmt-tax/bin/metaphlan \
  --db-dir fmt-databases/metaphlan4 \
  --index mpa_vJan25_CHOCOPhlAnSGB_202503 \
  --threads 4
```

回滚时只移除第 6 章钩子及新增模块；不要整文件恢复共享源码备份，以免覆盖其他 Codex 后续修改。现有正式报告文件由其他并行任务共同使用，独立预览用于验证，不应拿旧快照覆盖其结果。

## 上游依据

- [MetaPhlAn 官方说明：细菌、古菌、真核生物与病毒分析范围](https://github.com/biobakery/MetaPhlAn/wiki/MetaPhlAn-4.1)
- [官方病毒模块教程：开启参数、覆盖指标、阈值及独立 VSC 输出](https://github.com/biobakery/biobakery/wiki/MetaPhlAn-4.1#3-metaphlan-viral-module-tutorial)
- [维护者说明：真核生物默认纳入，病毒需开启参数并单独输出](https://forum.biobakery.org/t/some-questions-about-annotations/8318)
