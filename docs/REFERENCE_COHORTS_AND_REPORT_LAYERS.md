# 参考队列与三层报告实施规范

## 1. 第一批参考数据

项目内的候选队列清单保存在 `config/reference_cohorts.json`。第一批不直接下载数 TB 的 FASTQ，而采用两阶段建设：

1. 从 curatedMetagenomicData 导出样本元数据、MetaPhlAn3 相对丰度和 HUMAnN3 通路矩阵，快速建立参考分位数与外部验证集。
2. 保存每个样本的 BioProject/Run accession。论文定稿或模型锁版前，选定队列的原始 FASTQ 必须用项目同一版本的去宿主、MetaPhlAn 和 HUMAnN 流程重跑。

优先队列：

- 健康核心：HMP_2012、LifeLinesDeep_2016、ZeeviD_2015、MehtaRS_2018。
- 中国人群：JieZ_2017、QinJ_2012，只保留明确标注的健康对照作为健康参考。
- 饮食协变量复核：AsnicarF_2021。
- FMT/定植外部验证：IaniroG_2022。
- IBD 对照：NielsenHB_2014。

`study_samples_total` 是整项研究样本数，不是最终健康样本数。建立健康参考库时必须使用样本级元数据筛选，并做到：

- `body_site == stool/feces`；
- 明确 `disease == healthy`；
- 排除近期抗生素、住院、活动性感染和不合格 QC（字段可用时）；
- 重复受试者只保留预先定义的基线时间点；
- 年龄、地区、性别、BMI 和测序批次缺失情况进入数据字典；
- 训练、验证、测试按受试者和研究分组，禁止同一研究随机泄漏到多个集合。

候选队列清单可刷新：

```bash
python scripts/discover_reference_cohorts.py --output data/reference_catalog/cmd_healthy_fecal_cohorts.json
```

该命令只下载小型研究目录，不下载 FASTQ。

## 2. 参考库输出

统一处理后建议形成以下版本化产物：

```text
data/reference_catalog/<release>/
├── cohort_manifest.tsv
├── sample_metadata.parquet
├── species_relative_abundance.parquet
├── pathway_abundance.parquet
├── healthy_species_percentiles.parquet
├── healthy_pathway_percentiles.parquet
├── batch_qc.json
└── provenance.json
```

`provenance.json` 至少记录来源 accession、下载日期、FASTQ 校验值、宿主参考、MetaPhlAn/HUMAnN 版本、数据库版本、过滤规则、纳入/排除数量和输出校验值。P5–P95 只表示参考分布，不命名为“临床正常值”。

## 3. 三层报告

每次重新生成报告会产生：

| 层级 | 文件 | 用途 |
| --- | --- | --- |
| 主报告 | `<sample>_health_report.md/.pdf` | 面向用户；只保留结果概览、主要物种/通路、FMT 候选和解释边界 |
| 技术附录 | `<sample>_technical_appendix.md` | 面向研究人员；完整表格、方法、版本、证据编号、校验值和限制 |
| 交互数据 | `<sample>_interactive_report.json` | 前端 ECharts 的稳定数据协议；物种、通路、疾病关联、供体排序可切换和悬停查看 |

旧的 `health_report` 文件名继续保留，因此已有下载链接不失效。旧样本需要点击“重新生成报告”后才会补齐技术附录和交互 JSON。

## 4. 数据解释边界

- 物种和通路是测序数据经流程计算得到的估计值，不写成直接生化实测。
- HUMAnN 通路描述编码潜能，不代表蛋白表达、酶活性或体内代谢物浓度。
- 疾病关联分不等于患病概率。
- FMT 匹配分只在当前候选库内用于排序，不等于移植成功率。
- LLM 只解释已有结构化结果和证据，不得生成新的数值、诊断或治疗建议。

## 5. 数据来源

- curatedMetagenomicData: <https://bioconductor.org/packages/release/data/experiment/html/curatedMetagenomicData.html>
- HMP/iHMP: <https://ihmpdcc.org/data.php>
- MGnify API: <https://www.ebi.ac.uk/metagenomics/api/v1/>
- GMrepo: <https://gmrepo.humangut.info/>
- NCBI SRA: <https://www.ncbi.nlm.nih.gov/sra/>

GMrepo 目前作为辅助检索与表型复核来源。它的公开 REST 接口在本次核查中返回服务端错误，因此在接口重新验证前不作为生产报告的强依赖。
