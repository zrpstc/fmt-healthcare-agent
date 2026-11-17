# curatedMetagenomicData健康参考

健康参考唯一来源为curatedMetagenomicData（provider=`cmd`）。参考使用cMD3原生MetaPhlAn 3/v30已发表物种谱；待测谱独立使用MetaPhlAn **3.0.14**，数据库精确为`mpa_v30_CHOCOPhlAn_201901`。主分析Jan25谱及FMT配型独立保留。

本次核查服务器已有官方3.14.0源码包中的DESCRIPTION、NEWS.md、README.md：只明确MetaPhlAn 3，未提供cMD3重处理精确小版本。`SOURCE_PROFILER_MINOR_VERSION=None`，来源小版本继续标为“未公布”，不将待测3.0.14冒充来源版本。

## 严格契约

- 筛选粪便、年龄≥18、`disease=healthy`、`study_condition=control`、`antibiotics_current_use=no`，排除明确妊娠或哺乳；不额外限定BMI。
- 先验证完整物种矩阵，再按字符串规范化后的`study_id + subject_id`选最早合格时间点。同一个体只保留一份。
- 校验metadata.tsv和species_abundance.tsv的SHA256、schema、normalization、单位、完整性、表型及精确参考pipeline字典；待测provenance须精确3.0.14/v30，谱头已记录的版本不得冲突。
- 排除同名样本、原始样本别名、同一研究/个体及重复run；未给研究时保守排除相同个体编号。匹配并排除本人后**至少30名独立个体**，不放宽。
- 未配置、包无效、版本冲突、人口学缺失、分层人数不足时，`healthy_comparison.audit.status=unavailable`，显示“未建立健康对照”及原因码，不回退。
- `WGS_HEALTHY_REFERENCE_PROVIDER`未设置、空或`cmd`均使用cMD；其他值返回`unsupported_provider`并写不含配置原值的日志。
- 每次再生成报告都重算cMD结果，清除历史来源的P5/P95、percentile、status和异常计数；主分析丰度、实测数据、FMT及其他专项结果保留。

## 不确定性与零值

统一使用线性分位数`(n-1)*p`和含零、含并列值的midrank经验百分位。固定种子20261114，1000次经验bootstrap，以2.5%和97.5%分位数给出`p5_ci95`、`p95_ci95`和`percentile_ci95`。

为控制内存，bootstrap直接采样经验重采样分位数的精确边际分布：对相邻Uniform次序统计量采样后映射到排序观测值，保留线性插值；目标百分位通过“低于/等于/高于目标”的多项分布采样。各特征单独给边际区间，不把它们解释为联合置信区间。

目标位于P5或P95置信区间内时，`borderline=true`、`uncertainty_status=borderline`，不判high/low、不计确认越界。一般比较的`status=borderline`。目标为0且P5>0时，检出语义始终为`status=not_detected`；若同时与边界CI重叠，仍保留`borderline=true`并从确认越界计数和总览关注项排除。表格写明“未检出（边界不确定）”。这是检出状态与统计不确定性的两个维度。

其他零值不自动判偏低；零宽参考区间不产生high/low。所有章节、总览与`n_abnormal`使用同一规则。置信区间见结构化结果及正文参考文本。

## 越界物种数基线

在同一个物种全集（参考物种与目标物种的并集）上，记录每位参考者越出P5–P95的物种数。≤300人逐个体留一；>300人用全参考集分位数近似留一，并在audit和正文明确标注。

`outlier_baseline`包含每位参考者计数、P5/P95/中位数、目标原始越界数和目标在该计数分布的经验百分位。原始越界数包括零值和参考中从未检出的目标物种，与排除边界不确定后的`n_abnormal`分别展示。这是描述性多重比较背景，不是FDR校正或疾病概率。

## 人口学分层

建包参数`--stratify-by country sex age_band`可选任意非重复组合；不传时使用总体。`--age-band-boundaries 18 30 40 50 60 70 80`指定严格递增的年龄段下界，必须从18开始，最后一段开放至更高年龄。各段左闭右开；30岁进入30岁起的段。

manifest保存`stratify_by`、`age_band_boundaries`、`stratum_subject_counts`，建包时逐层打印个体数。比较阶段校验字段、边界及计数，按完整组合精确匹配。缺失值统一包括空、NA、N/A、NaN、None、null、unknown（不区分大小写）；数值0本身不是缺失。sex规范化f/m/女/男，country去空格并统一大小写。某层不足30人或排除本人后不足30人均不可用，绝不并入其他层。

旧包的空`stratify_by=[]`继续有效；旧式滑动年龄窗匹配不再接受，需用新包显式年龄段。

## 深度及研究批次

官方元数据若有`number_reads`/`number_bases`，建包时保留并把有效正值人数、P5、中位数、P95写入manifest的`depth_distribution`；加载时用已校验metadata重算核对。比较审计另给**所选层**的深度分布。

自动待测谱工作流逐条读取其去宿主FASTQ，记录准确reads数和碱基数；缓存重用只针对相同输入SHA256和分析配置。待测深度落在所选参考P5–P95之外时提示“丰富度可能不可比”，不下采样。旧待测provenance缺深度时报告缺失，不伪造读数。cMD原研究深度定义与本地去宿主reads口径仍可能不同。

audit和正文还列所选研究数、各研究独立人数、各研究丰富度与Shannon中位数，以及这些研究中位数的最小/最大范围。此摘要不进行批次校正。

## 建包和待测谱

不会自动重建或发布线上参考包。需要新分层或深度字段时，应由管理员选择**新输出目录**执行：

```bash
Rscript scripts/export_cmd_metadata.R --output-dir /path/to/cmd-source-snapshot
PYTHONPATH=src .venv/bin/python scripts/prepare_cmd_reference.py \
  --package-dir /path/to/official/curatedMetagenomicData \
  --metadata /path/to/cmd-source-snapshot/sample_metadata.tsv \
  --catalog /path/to/ExperimentHub.sqlite \
  --source-dir /path/to/cmd-source-cache \
  --output /path/to/new-cmd-reference \
  --stratify-by country sex age_band \
  --age-band-boundaries 18 30 40 50 60 70 80
```

已有同路径包只校验并复用；分层参数不同则报错，绝不覆盖。命令中的官方源码目录和Hub目录需使用部署中已有的真实路径；导出脚本缓存的源码压缩包需先解压到独立准备目录。建包输出不是自动发布指令。

```bash
PYTHONPATH=src .venv/bin/python -m wgs_agent.pipeline.cmd_workflow \
  --sample-id SAMPLE --output-root /path/to/bioinformatics \
  --group-json /path/to/SAMPLE.json --threads 4
```

postfmt直接调用该入口。报告生成只读取本地参考与既有待测谱，不启动profiling、下载或重建参考。

## 扩大健康参考（抗生素口径）

`prepare_cmd_reference.py --antibiotics-policy no_or_unrecorded` 在原有筛选之外，纳入原研究**未记录**当前抗生素使用的健康成人；明确记录为在用（yes）者仍排除。默认值`no`保持原严格契约，旧包继续有效；加载器同时接受两种口径，manifest的`selection_criteria.antibiotics_current_use`记录实际口径，报告局限性第一条随之改写。

人数主要取决于两点：cMD元数据版本和抗生素口径。按官方sampleMetadata核查（2026-11，成人健康对照粪便独立个体，未扣除无效谱）：

| 元数据版本 | `no` | `no_or_unrecorded` |
|---|---|---|
| Bioconductor 3.20 / cMD 3.14.0（原默认，服务器旧包3,537人） | 3,538 | 4,739 |
| Bioconductor 3.22 / cMD 3.18.0（当前发行版） | 5,655 | 7,042 |

两个版本的物种丰度资源完全相同（122个relative_abundance资源），3.18.0补全了年龄、抗生素等元数据。`scripts/export_cmd_metadata.R --bioc-release 3.22`导出3.18.0元数据（官方PACKAGES索引MD5 `717f3f71242bf3bf54b2997b6f88c0ee`），默认仍为3.20。建包时`--package-dir`须指向同版本解压源码。实际人数以建包输出为准。换包须写入**新目录**，再改`WGS_CMD_REFERENCE_DIR`。

## 人群模型包（肠龄、肠型、健康指数、患病人群参考）

`scripts/prepare_cmd_cohort_models.py`复用健康参考的官方源码包、元数据快照、ExperimentHub目录和下载/导出缓存（`--source-dir`），选取成人粪便谱中的健康对照（默认`no_or_unrecorded`口径）和10类成人疾病队列（CRC、adenoma、IBD、T2D、IGT、ACVD、CAD、cirrhosis、AS、schizophrenia；每类至少50人才建模）。每个(研究,个体,分组)保留最早有效谱。输出`manifest.json`与`models.json`，均为纯JSON（线性系数、聚类中心、分位数），不含pickle；manifest记录models.json的SHA256，加载时校验。

| 模型 | 方法 | 交叉验证 |
|---|---|---|
| 肠道年龄 | 健康成人（18–90岁）物种log10(丰度%+0.001)标准化后岭回归；同龄比较用交叉验证预测值对实际年龄的线性关系校正回归均值效应 | 按研究分组K折，记录MAE与相关系数 |
| 肠型 | 健康成人属水平Hellinger变换，k-means（k=3），按普雷沃菌属/拟杆菌属负荷命名；样本归最近中心，明确程度=1−最近/次近距离；PCA仅用于作图 | — |
| 健康指数 | 健康 vs 合并疾病队列的类别平衡L2逻辑回归（C=0.05） | 按研究分组K折AUC |
| 患病人群参考 | 每类疾病对比同研究健康对照（不足20人时用全部健康对照并标注），Mann-Whitney+BH（q<0.1）选富集/缺失各至多15种菌；特征分=富集均值−缺失均值 | 按研究分组K折、每折重选菌种的AUC；消费者版只展示AUC≥0.65的疾病 |

运行时（`reporting/cohort_insights.py`）只读模型包和该样本已有的MetaPhlAn3/v30独立待测谱，校验provenance、版本和质控；缺包、校验和不符、版本不符均返回`audit.status=unavailable`及原因码，不回退。结果写入报告`template_inputs.cohort_insights`；旧报告在构建消费者版时现场计算。

```bash
PYTHONPATH=src .venv/bin/python scripts/prepare_cmd_cohort_models.py \
  --package-dir /path/to/official/curatedMetagenomicData \
  --metadata /path/to/cmd-source-snapshot/sample_metadata.tsv \
  --catalog /path/to/ExperimentHub.sqlite \
  --source-dir /path/to/cmd-source-cache \
  --output /path/to/var/reference/cmd/cohort-models-v1
```

已存在的输出目录只报告`already_built`，不覆盖。患病人群参考描述的是菌群特征与公开患者群体的相似程度，不是患病概率或诊断。

## 环境变量迁移

| 变量或参数 | 状态 | 行为/迁移 |
|---|---|---|
| `WGS_HEALTHY_REFERENCE_PROVIDER` | 保留，可选 | 未设置/空/`cmd`使用cMD；其他值明确不支持 |
| `WGS_HEALTHY_REFERENCE_DIR` | 删除 | 不再读取；cMD使用`WGS_CMD_REFERENCE_DIR` |
| `WGS_HEALTHY_ENA_DIR` | 删除 | ENA通用参考下载器已移除 |
| `WGS_MHO_*` | 全部删除 | 不再读取；按用途改为`WGS_CMD_*`，不复用旧谱 |
| `WGS_SPECIES_REFERENCE_FILE` | 删除 | 旧总体CSV/TSV不再读取，没有替代阈值文件变量 |
| `WGS_REFERENCE_DIR` | 保留，仅非健康物种用途 | 既有通路/代谢物描述统计及疾病表目录；不再查找物种健康参考 |
| `WGS_REFERENCE_CACHE_DIR` | 保留，仅通路工具 | 既有公共HUMAnN通路缓存，不是健康物种来源 |
| `WGS_CMD_REFERENCE_DIR` | 保留 | 默认工作区`reference/cmd/native-v3` |
| `WGS_CMD_PROFILES_DIR` | 保留 | 默认工作区`reference-targets/cmd` |
| `WGS_CMD_COHORT_DIR` | 新增 | 人群模型包，默认工作区`reference/cmd/cohort-models-v1` |
| `--antibiotics-policy` | 新增CLI参数 | `no`（默认，原契约）或`no_or_unrecorded`（扩大健康参考） |
| `export_cmd_metadata.R --bioc-release` | 新增CLI参数 | `3.20`（默认，cMD 3.14.0）或`3.22`（cMD 3.18.0，元数据更完整） |
| `WGS_CMD_AUTO_PROFILE` | 保留 | 默认true；false/0/no/off关闭自动准备，报告仍可读既有谱 |
| `WGS_CMD_PYTHON` | 保留 | 独立MetaPhlAn解释器；不是应用Python，shell应用使用`WGS_ENV_ROOT/bin/python` |
| `WGS_CMD_VENDOR_DIR` | 保留 | 默认工作区`runtime/vendor/metaphlan-3.0.14` |
| `WGS_CMD_TOOL_BIN`、`WGS_CMD_DATABASE` | 保留 | 工具目录、v30索引目录；与主分析分开 |
| `WGS_CMD_THREADS` | 保留 | 自动准备线程数，默认4 |
| `WGS_CMD_SOURCE_DIR` | 保留 | 官方元数据/源码准备目录 |
| `WGS_FMT_MATCHING_DIR`及配型变量 | 保留原用途 | 仅供FMT配型；不再提取供体子集作为健康多样性参照 |
| `--stratify-by` | 新增CLI参数 | country/sex/age_band精确组合匹配 |
| `--age-band-boundaries` | 新增CLI参数 | 年龄段下界，默认18/30/40/50/60/70/80 |

`ProviderSpec(frozen=True)`将schema、参考pipeline、待测pipeline、normalization、最低人数和目录函数分开描述；允许未来另定义cMD4的精确契约。本次不实现、不接受cMD4包。

## 存量数据

本次不删除`var/`或外置工作区中的参考包、原始序列和样本结果。管理员确认不再需要后可手动归档旧`reference/mho`、`reference/healthy`、`reference-targets/mho`、`reference-sources/mho`、`reference-sources/healthy-ena-demo`及旧物种总体表；不要清理cMD、FMT配型数据、其他专项资源或患者原始数据。路径按实际配置的工作区解析。

当前服务器旧cMD包有3537人、984物种，metadata中无reads/bases字段；不重建时仍能计算新置信区间、越界基线和批次摘要，但参考深度可比性会明确标为缺失。
