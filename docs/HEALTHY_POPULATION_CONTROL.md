# 健康人群对照：实现、数据缺口与下载

检查日期：2026-10-24。项目位置：gpu02 `/home/zhanghaiyang/fmt-healthcare-agent`。

## 当前结论

代码已支持带来源、健康标签、个体标识和分析版本的健康参考队列。物种提供 P5、中位数、P95、
包含零值的经验百分位、检出率和独立参考人数；完整谱提供丰富度、Shannon、Simpson 及 Pielou 对照。
输出进入分析 JSON、报告 Markdown/PDF、结构化报告和证据 JSON。未给出疾病概率或综合健康分数。

现有资源不足以建立经过核验的健康人群基线：

| 本机资源 | 实际检查结果 | 可以支持什么 |
|---|---|---|
| `data/reference/species_reference_overall.csv` | 1,440 个物种；每行声明 `n_samples=13265`；全部 P5=0；1,190 行 P5=P95=0 | 250 个物种有非零宽度描述区间；不能由该表证明 13,265 名独立健康者，也不能判定偏低 |
| `var/data/fmt-matching/species_abundance_train.csv` + `match.xlsx` | 132 份谱、1,973 个特征；标签有133行，其中51份 `donor + healthy` 均在矩阵中 | 保留已有探索性健康供体多样性比较；缺少 `subject_id/study_id`、完整健康筛选及分析版本，不能升级为核验健康队列 |
| `fmt-databases/metaphlan4` | `mpa_vJan25_CHOCOPhlAnSGB_202503` | 物种注释索引；本身不包含健康人群分布 |
| `fmt-databases/metaphlan4_vJun23` | `mpa_vJun23_CHOCOPhlAnSGB_202307` | HUMAnN 兼容索引；不能与 Jan25 丰度直接视为同口径 |

P5 为零并不单独说明计算错误，稀疏物种在健康队列中也可能大多未检出。这里的关键缺口是
原始样本、健康纳入标准、独立个体及分析版本不可追溯。

没有安装新队列时，报告明确写“健康人群对照：未建立”，保留原有描述性物种参照和探索性供体子集。
显式配置新队列后，文件缺失、版本不一致、完整谱缺失、人口学匹配信息缺失或人数不足均关闭本次健康比较，
清除本功能生成的旧参考数值，不会换用另一批人群。既有纵向记录保留。

## 至少要准备的数据

最小可用资源是**一套健康粪便宏基因组队列**，包括完整物种丰度矩阵、样本元数据及来源/处理清单。
不必再下载一个病原体、耐药或基因组注释数据库才能启用物种与多样性对照。

1. 每个匹配层在质控、去重及排除待测个体后至少30名独立健康者。这只是本功能的运行门槛，
   不是临床参考区间已获验证的样本量标准；实际队列规模需要按用途设计。
2. 明确的健康纳入/排除标准，例如疾病、近期抗生素、妊娠或其他影响因素的处理，记录来源论文与版本。
   “非IBD/非CRC”不能单独等同健康，“无标签”也不能等同健康。
3. 每份样本具备 `sample_id, subject_id, study_id, health_status, qc_pass, body_site`。
   需要人口学匹配时，还需双方的 `age, sex, country`。`subject_id` 必须跨研究可区分；重复访视每人只取一份。
4. 所有参考与待测样本采用相同物种分析软件版本、同一精确数据库索引、相同物种层级、丰度单位及质控口径。
   不使用 Top N、按参考覆盖过滤后的物种谱或16S谱替代完整 shotgun 物种谱。
5. 若要扩展到功能通路对照，还需同一 HUMAnN/UniRef/MetaCyc 版本、相同归一化单位的健康通路矩阵。
   本次实现覆盖物种和四项多样性，不将通路推算当作实测代谢物浓度。

## 推荐下载路径

**推荐：用 curatedMetagenomicData 查健康样本及元数据，再经 ENA/SRA 获取原始 shotgun reads，使用本项目版本重跑。**
其官方文档说明提供人工整理元数据及物种、通路等产物；当前发布说明的预计算分类使用 MetaPhlAn3、功能使用 HUMAnN3。
所以这些预计算物种表不能直接作为本机 Jan25/MetaPhlAn4 的可比参考。
[官方包与版本说明](https://bioconductor.org/packages/release/data/experiment/html/curatedMetagenomicData.html)，
[官方数据访问示例](https://bioconductor.org/packages/release/data/experiment/vignettes/curatedMetagenomicData/inst/doc/curatedMetagenomicData.html)。

使用项目的基础 R 导出脚本，仅读取官方源码包中的 `sampleMetadata.rda`，无需安装整套分析依赖：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
Rscript scripts/export_cmd_metadata.R
```

已在 gpu02 实际验证：输出 22,588 条样本、141 个字段；源码来自 Bioconductor 3.20 的
`curatedMetagenomicData 3.14.0` 官方归档（约1.9 MB），下载后核验官方 MD5，导出后回读核对行列及样本编号。
基础 R 即可运行，也已验证 `Rscript --vanilla scripts/export_cmd_metadata.R` 不依赖用户包库。

输出在 `var/reference-sources/cmd/`：

- `sample_metadata.tsv`：完整元数据，包含健康与疾病样本，尚未筛选为健康队列。
- `package_version.txt`：元数据来源源码包版本；不表示整套 R 包已安装。
- `metadata_source.tsv`：下载地址、来源版本、校验和、行列数及提取方法。
- `source/`：已校验的官方源码包缓存。

重复运行会复用相同快照；已有文件内容不同时拒绝覆盖，可用
`Rscript scripts/export_cmd_metadata.R --output-dir /path/to/new/snapshot` 保存另一份。

本机系统 R 为4.4.1，但系统 `Matrix/nlme/cluster` 等二进制包由R4.5.3构建，
完整安装曾出现 `ANY_ATTRIB/R_chk_memcpy` 缺失符号，以及 GSL 开发库缺失。
这些是完整分析环境的问题；当前元数据提取步骤不加载这些包，无需先修复系统环境。
项目 `.Renviron` 的本地 R 包库配置仍保留供其他 R 任务使用。


接下来直接使用配套 ENA 工具。完整的文件清单、目录树、单样本下载、批次下载和生信衔接，
见 [README 第8节](../README.md#8-准备健康人群对照数据ena)。

```bash
.venv/bin/python scripts/healthy_ena.py prepare \
  --study AsnicarF_2021 --ena-project PRJEB39223 --limit 50
.venv/bin/python -u scripts/healthy_ena.py download --runs 1
.venv/bin/python scripts/healthy_ena.py verify --runs 1
```

`prepare` 只下载小型 ENA 索引并建立候选清单，不下载 FASTQ。原始文件由 `download` 单独下载到
`var/reference-sources/healthy-ena-demo/raw/<run>/`，校验清单和来源记录保存在其上一级目录。
本机已准备的示例是50名候选者、50个run、100个FASTQ，压缩数据合计约217 GB（202.08 GiB）。
先下载并校验1个run的R1/R2，再确认磁盘及生信试跑结果，最后将 `--runs` 改为50。

该示例项目同时含WGS和AMPLICON；工具按 cMD 中的run编号选取Illumina双端宏基因组WGS，
不会把同项目的16S扩增子加入计划。健康标签、成年及无当前抗生素使用的筛选只用于候选准备，
正式健康纳入标准和测序QC仍待核验，不会自动将 `qc_pass` 标为通过。

ENA 官方说明：[文件报告接口](https://ena-docs.readthedocs.io/en/latest/retrieval/programmatic-access/file-reports.html)，
[下载及MD5核验](https://ena-docs.readthedocs.io/en/latest/retrieval/file-download.html)。

**替代：HMP 健康人群 shotgun 数据。** 官方目录区分 Healthy Human Subjects 和疾病项目，并提供健康人群
WMS 索引/质控 reads：[HMP 数据目录](https://www.ihmpdcc.org/data.php)。先浏览清单：

```bash
aws s3 ls --no-sign-request s3://hmpdcc/hmp1/hhs/microbiome/wms/raw/
aws s3 ls --no-sign-request s3://hmpdcc/hmp1/hhs/microbiome/wms/analysis/qc/qc_2017/
```

这两个路径分别是原始 run 索引及质控产物目录，不能假设全部条目都是健康粪便 FASTQ。
结合受试者、部位及访视元数据选择 stool，并经 ENA/SRA 或目录列出的文件获取；每人只保留一份符合标准的样本。
HMP 可作为初始研究参考；用于本地目标人群时仍需核验适用性。

小红书补充检索读到了元数据检索经验，不能据此确认健康标签或分析版本；上述下载与兼容性判断以项目本机检查及原始文档为依据。

## 构建并接入

准备 `metadata.tsv`，第一行为以下字段，后续每行一个真实样本；不要将示例行作为实际参考数据：

```text
sample_id  subject_id  study_id  health_status  qc_pass  body_site  age  sex  country
```

实际使用制表符；健康值为 `healthy`，质控通过为 `true/1/pass`，部位为 `stool`。
年龄为年数，国家使用同一代码体系，性别统一 `female/male`（匹配也兼容 F/M 和女/男）。
先完成项目同口径的质控/去宿主及 MetaPhlAn 分析，将完整谱放到
`<profiles-root>/profiles/metaphlan/{sample_id}_profile.tsv`。健康标签不能代替测序质控。

准备 `manifest.json`，将占位字段替换成核验后的真实信息：

```json
{
  "schema_version": "healthy-reference-v1",
  "cohort_id": "REPLACE_WITH_REAL_COHORT",
  "cohort_version": "REPLACE_WITH_RELEASE",
  "source_url": "REPLACE_WITH_DATASET_OR_PAPER_URL",
  "inclusion_criteria": "REPLACE_WITH_VERIFIED_INCLUSION_AND_EXCLUSION_CRITERIA",
  "body_site": "stool",
  "unit": "%",
  "complete_species_profiles": true,
  "pipeline": {
    "profiler": "MetaPhlAn",
    "profiler_version": "REPLACE_WITH_ACTUAL_RUN_VERSION",
    "database_version": "mpa_vJan25_CHOCOPhlAnSGB_202503"
  },
  "minimum_subjects": 30,
  "stratify_by": [],
  "age_window_years": 10
}
```

`stratify_by` 可填 `age/sex/country` 的任意组合。`age` 按待测年龄±`age_window_years` 筛选；其他字段精确匹配。
人数不足时不自动放宽。所有人群标签和版本仍需要维护者依据原始记录核验，JSON 中的声明不是自动认证。

构建命令仅读取已完成产物，不重新测序分析，不覆盖已有目录：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/build_healthy_reference.py \
  --manifest /path/to/manifest.json \
  --metadata /path/to/metadata.tsv \
  --profiles-root /path/to/completed-output \
  --output /path/to/reference/healthy-release-1
```

产物为 `manifest.json`、`metadata.tsv`、`species_abundance.tsv`，文件权限0600。
矩阵行是样本、列是物种、值是百分数；保留全部物种，不过滤稀有菌。只在完整兼容谱中把确实未检出的物种补零。
构建器核验首份样本对应匹配层是否满足运行条件；实际报告仍针对每个待测样本重新筛选并核验，不能把一次构建成功理解为所有人口学层均够用。
个体去重以 `(study_id, subject_id)` 为键，按样本编号排序选首份有效谱；跨研究复用的同一受试者应由维护者统一去重，
无法用不同研究的局部编号自动识别同一人。

在 `.env` 中设置并由 API 所属用户重启后生效：

```dotenv
WGS_HEALTHY_REFERENCE_DIR=/path/to/reference/healthy-release-1
```

默认未配置时检查工作区 `reference/healthy/`，本机默认即 `var/reference/healthy/`。
目标的完整谱需有 `taxonomy.pipeline` 或分析元数据 `metadata.taxonomy_pipeline`，与清单三项版本一致。
读取器可从 `#mpa_...` 及 `#MetaPhlAn version x.y.z` 头自动取证。
历史 TSV 常只记录数据库、没有软件版本：应根据原始运行日志补录到目标分析 JSON；不能凭现在安装的版本推断历史版本。
构建器在参考谱未写软件版本时使用清单声明，因此填清单前必须核验该批原始运行环境。

重新生成报告后检查：

- `metadata.reference_comparison.healthy_population.status` 为 `available`，独立人数及排除计数符合预期。
- 物种记录有 `reference_version/percentile/n_subjects`；四项指数有健康参考分布。
- `*_report.json` 与 `*_report_evidence.json` 的参考哈希相同。
- 零宽区间保留未知高低状态；经验百分位仍可记录，不能解释为正常或疾病概率。

旧 `download_public_reference.py` 已删除“健康样本不足就使用全部样本”的回退；其历史 URL 和旧 R 导出脚本
不是新健康队列的接入入口，不应直接运行后就把产物标成已验证健康参考。推荐使用上面的原始来源与新构建器。

## 部署与恢复

本次仅后端代码变化，前端现有报告预览无需重建。gpu02 API 以 root 运行，SSH 用户
`zhanghaiyang` 没有免密 sudo，需有权限的维护者执行：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
sudo bash deploy/restart-report-api.sh
```

然后在网页重新生成目标报告。数据尚未补齐时，新报告会明确显示健康对照未建立。
本次修改前的源码与已存在改动基线保存在 `tmp/healthy-control-20261024/source-baseline.tar.gz`，
被改文件的逐项备份在 `tmp/healthy-control-20261024/before/`；没有重置用户已有改动或提交 Git。
