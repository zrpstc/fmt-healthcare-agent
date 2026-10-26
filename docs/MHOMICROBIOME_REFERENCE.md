> 2026-10-26: automatic target preparation is available. See [automatic workflow](MHO_AUTOMATIC.md); the manual commands below remain useful for migration and troubleshooting.

# MHOmicrobiome 接入与准备数据指南

适用：gpu02 `/home/zhanghaiyang/fmt-healthcare-agent`。实现基于当前代码；健康对照入口与提交 `ae89557a0055aa20b865fce5e9dd8730c53f515d` 一致。更新日期：2026-10-25。

## 0. gpu02 本次已准备好的内容

适配源码已经写入项目，来源文件已放入 `var/reference-sources/mho/825084d/`，正式参考库已构建在 `var/reference/mho/jan25-825084d/`，103 人、3389 个物种键，三个文件合计 **1,166,859 bytes（约 1.17 MB）**。`var/runtime/envs/mho-tax/bin/metaphlan` 已验证为 4.2.2；原 `fmt-tax` 仍为 4.2.4。已有 Jan25 索引完整，无需另下。

**尚未修改线上 `.env`、未重启服务、未重跑真实患者。**当前服务器继续使用时，从第 6 节为真实样本生成对照谱，然后按第 8 节验收并启用即可；第 4、5 节用于复现或迁移，不要直接覆盖现有版本目录。原文件备份和完整补丁位于项目 `tmp/mho-adaptation-backup-20261025T040159Z/`（原始备份）及本次后续同前缀备份目录。

## 1. 这次接入的范围

选择 `WGS_HEALTHY_REFERENCE_PROVIDER=mho` 后，报告的健康人群比较改用 MHOmicrobiome 中 **103 名 MHNO（代谢健康、非肥胖）**个体。物种输出 P5、中位数、P95、经验百分位、检出率及参考人数；多样性提供丰富度、Shannon、Simpson 1−D 和 Pielou。

原有 MetaPhlAn 4.2.4 主分析、HUMAnN、功能/疾病关联及 FMT 配型逻辑保留。健康比较使用一份独立生成的 MetaPhlAn **4.2.2** 待测谱，结果存放在分析 JSON 的 `healthy_comparison`，不替换主分析 `species/compare/diversity` 的原始数值。报告为 MHNO 数值建立独立证据及表格，不再将旧物种参考区间解释为本库的区间。

报告生成只读取本地文件，不联网、不下载、不启动 MetaPhlAn。缺文件、版本不符、校验失败、匹配人数不足时，MHNO 区显示不可用并清除本功能的旧比较结果。其他报告模块继续按原逻辑运行。

## 2. 必须明确的分析口径

| 项目 | 固定要求 |
|---|---|
| 来源表型 | Supplementary Data 3 的 `phenotype=MHNO`，每研究/个体只取一份 |
| 来源规模 | 全矩阵 931 份；实际选取 103 人；3389 个原始叶节点汇总到 3389 个唯一物种键 |
| 软件 | MetaPhlAn 4.2.2；4.2.4 产物不能改标签冒充 |
| 数据库 | `mpa_vJan25_CHOCOPhlAnSGB_202503`；不能换 Jun23、旧 SGB 或其他 Jan25 发布 |
| 丰度 | 双方均按 species 汇总，然后除以各自的已分类 species 总量 ×100 |
| 多样性 | 双方使用项目同一公式；Shannon 自然对数，Simpson 1−Σp²，Pielou H/ln(S) |
| 参考人数门槛 | 排除同一个体/run 并做所配置的人口学匹配后至少 30 人；这只是程序门槛 |

原矩阵所选 103 份谱的丰度合计实际为 **68.30771873758901–100.00011**，不能假设每份已经加总为 100。程序对参考和待测谱采用同一已分类物种分母，保留原始总量；不会把缺失部分按具体物种补出。完整矩阵中的零值参与分位数计算，不能只保留 Top N 或非零物种。MetaPhlAn 待测文件只读取末级 `s__` 行，忽略父分类与 `t__` 行，避免重复计数。

MHNO 不是通用临床正常人群。本方案采用论文发布的处理结果，没有重跑、统一参考人的原始测序深度、提取方法及全部研究批次。尤其丰富度受深度影响，四项多样性和物种区间均为**探索性队列位置**。不据此生成疾病概率或临床正常值。默认使用 MHNO 总体，不能声称已经按年龄、性别、地区匹配。

## 3. 需要下载多大、存在哪里

只下载两个预计算文件，合计 **9,103,950 bytes，约 9.1 MB（8.68 MiB）**；不下载 103 人 FASTQ，不下载整套 MHOmicrobiome Git 仓库。转换后的参考库约 1.17 MB，压缩后更小。待测样本额外运行 MetaPhlAn 时，已有去宿主 FASTQ 和比对临时文件仍需要磁盘空间；9.1 MB 不包括这些文件和物种注释索引。

```text
var/reference-sources/mho/825084d/   # 原始 CSV + 表型 XLSX；只读留档
var/reference/mho/jan25-825084d/     # manifest.json、metadata.tsv、species_abundance.tsv
var/runtime/envs/mho-tax/           # 独立 4.2.2 软件环境
var/reference-targets/mho/<SID>/
    profile.tsv                    # 原始 4.2.2 完整物种输出
    provenance.json                # 实际版本、参数、输入路径/大小/mtime、输出 SHA256
    run.log                        # 运行日志
```

## 4. 下载并构建参考库

在 gpu02 用项目 Python 执行；`PYTHONPATH` 明确指向本次源码。下面路径均按服务器现状填写。

项目现有环境已含 `openpyxl`。其他机器可先用 `.venv/bin/python -c 'import openpyxl'` 检查；缺少时执行 `.venv/bin/python -m pip install 'openpyxl>=3.1,<4'`，仅用于读取来源工作簿。

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
SRC="$PWD/var/reference-sources/mho/825084d"
REF="$PWD/var/reference/mho/jan25-825084d"

.venv/bin/python scripts/mho_reference.py download --source-dir "$SRC"
.venv/bin/python scripts/mho_reference.py build --source-dir "$SRC" --output "$REF"
```

第一次 `build` 应输出 `n_subjects: 103`、`n_species: 3389`、`status: built_not_activated`。`download` 可重复执行，会校验已有文件；`build` 拒绝覆盖已有目录。目录已经存在时可验证，或为新版本另起目录，禁止手动覆盖矩阵后继续沿用旧清单。

```bash
.venv/bin/python - "$REF" <<'PY'
import sys
from pathlib import Path
from wgs_agent.reporting.mho import load_bundle
manifest, labels, features, matrix, hashes = load_bundle(Path(sys.argv[1]))
print('individuals=', len(labels), 'species=', len(features))
print('pipeline=', manifest['pipeline'])
print('normalization=', manifest['normalization'])
print('file_sha256=', hashes)
PY
```

构建程序会检查来源 SHA256、表型、唯一 subject/study、AI4Food 访视映射、矩阵数值及每份归一化合计。AI4Food 的表型表用数字 subject，矩阵使用 `A4F_<subject>_V1/V3`，只接受唯一匹配，歧义直接失败。清单记录来源、处理范围、软件、数据库、归一化方式和两个 TSV 的 SHA256。

来源固定为：

| 文件 | SHA256 |
|---|---|
| `whole_cohort_data.csv` | `5a7bc4b93ad1786ef3cdeac4a23d2bd73c2565115008dc3244a792745302f462` |
| `phenotypes.xlsx` | `ef2948ec098de917142bfcb59c04605495a53f1663c27326e02eb4cdc2aa4b98` |

[固定 CSV](https://raw.githubusercontent.com/blacruz17/MHOmicrobiome/825084dcc8ebb73efb9f4282a35f15920729eac4/data/whole_cohort_data.csv)，[官方表型 XLSX](https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41467-026-72588-1/MediaObjects/41467_2026_72588_MOESM5_ESM.xlsx)。服务器无法访问下载地址时，可在有网机器下载这两个文件、核验上述 SHA256，再放进 `$SRC`。脚本不会接受不同版本内容。

## 5. 准备独立 MetaPhlAn 4.2.2 环境

现有主环境 `var/runtime/envs/fmt-tax` 为 4.2.4；保留它。使用其已安装依赖创建独立 Python 环境，仅在新环境安装 4.2.2：

```bash
ROOT=/home/zhanghaiyang/fmt-healthcare-agent
TAX_ENV="$ROOT/var/runtime/envs/fmt-tax"
MHO_ENV="$ROOT/var/runtime/envs/mho-tax"

test ! -e "$MHO_ENV" && "$TAX_ENV/bin/python" -m venv --system-site-packages "$MHO_ENV"
"$MHO_ENV/bin/python" -m pip install --no-deps 'metaphlan==4.2.2'
"$MHO_ENV/bin/metaphlan" --version
```

应报告 `MetaPhlAn version 4.2.2`。`--version` 有时附带默认数据库未发现提示，实际运行始终显式给出数据库目录和索引。`--no-deps` 避免更改既有环境的依赖；这是依赖现有 fmt-tax 环境的轻量环境，迁移服务器时需一并准备依赖。不要对 `fmt-tax/bin/pip` 执行降级。

检查已有数据库：

```bash
DB="$ROOT/var/databases/metaphlan4"
test -r "$DB/mpa_vJan25_CHOCOPhlAnSGB_202503.pkl"
ls -lh "$DB"/mpa_vJan25_CHOCOPhlAnSGB_202503*.bt2l
```

需要 `.pkl` 和完整 Bowtie2 索引。gpu02 已有 Jan25，可复用路径/软链接；不要复制或重新下载大型数据库。数据库不完整时先补齐，不能用另一套库替代。

## 6. 为每个待测样本生成独立对照谱

输入是主流程已完成质控、去宿主的完整合并 FASTQ，通常位于 `var/bioinformatics/clean_merged/<SID>.dehosted.fastq.gz`。不要拿 HUMAnN 的 Jun23 谱、Top N 表、分析 JSON 或现有 4.2.4 TSV 作为本命令输入。

```bash
ROOT=/home/zhanghaiyang/fmt-healthcare-agent
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
TAX_ENV="$ROOT/var/runtime/envs/fmt-tax"
MHO_ENV="$ROOT/var/runtime/envs/mho-tax"
DB="$ROOT/var/databases/metaphlan4"
REF="$ROOT/var/reference/mho/jan25-825084d"
SID='替换为真实样本ID'
READS="$ROOT/var/bioinformatics/clean_merged/${SID}.dehosted.fastq.gz"
PROFILES="$ROOT/var/reference-targets/mho"
test -r "$READS"

.venv/bin/python scripts/mho_reference.py profile \
  --sample-id "$SID" \
  --reads "$READS" \
  --metaphlan "$MHO_ENV/bin/metaphlan" \
  --tool-bin "$TAX_ENV/bin" \
  --database "$DB" \
  --profiles-dir "$PROFILES" \
  --threads 8
```

来自公开 run 时追加 `--source-runs 'ERR123456,ERR123457'`，以排除同 run 进入参考。也可通过下一节 metadata 提供 subject/study/run 标识。默认使用所提供的全部 reads；参考人的测序深度没有统一，不宣称深度匹配。比对临时文件成功后删除，保留谱、运行记录和日志。已有 `<SID>` 目录时拒绝覆盖；重新分析请用新 `--profiles-dir`，并在验收后切换配置。

**gpu02 的权限现状：**`clean_merged` 及现有部分产物由 root 持有且目录为 700，SSH 用户 `zhanghaiyang` 无法读取。此步骤须由能读取该样本文件的服务运行用户/管理员执行，并保证报告服务可读取新参考和新产物。不对全部患者数据执行 `chmod -R 777`。代码适配和参考建库不依赖读取这些患者 FASTQ；没有实际运行此步骤前，不能声称某个患者已完成 MHNO 对照。

## 7. 可选的人口学匹配与个体排除

发布的表型文件主要提供 subject、run、study 和 phenotype。本实现不会推测缺失人口学信息。默认以 103 人总体作探索性比较。

若后续获得可靠年龄/性别/国家信息，可另建 TSV：

```text
sample_id<TAB>age<TAB>sex<TAB>country
真实参考样本ID<TAB>40<TAB>female<TAB>CHN
```

将 `<TAB>` 换成真实制表符，`sample_id` 必须匹配已生成的 `metadata.tsv`。重新构建新的目录，例如：

```bash
.venv/bin/python scripts/mho_reference.py build \
  --source-dir "$SRC" --output "$ROOT/var/reference/mho/jan25-matched-v2" \
  --demographics /实际路径/demographics.tsv \
  --stratify-by age sex country --age-window-years 10
```

待测分析 JSON 的 `metadata` 必须提供同样的 `age/sex/country`。性别支持 female/male、F/M、女/男；国家按字符串忽略大小写比较，请双方统一编码。年龄在 ±10 岁内，性别/国家相同；任一缺失或匹配后少于 30 人就不比较，不自动回退总体。

提供 `metadata.subject_id` 和 `metadata.study_id` 可排除同研究的同一个体；`source_runs`、`run_ids` 或 `NCBI_accession` 可排除同 run。没有这些标识时，只能排除同名样本，报告会记录身份核验的局限。

## 8. 先验收，再启用报告

先在命令作用域传入配置，无需改服务 `.env`：

```bash
WGS_HEALTHY_REFERENCE_PROVIDER=mho \
WGS_HEALTHY_REFERENCE_DIR="$REF" \
WGS_MHO_PROFILES_DIR="$PROFILES" \
.venv/bin/python scripts/mho_reference.py check --sample-id "$SID"
```

需要匹配/排除标识时，追加 `--metadata-json /实际路径/metadata.json`。文件内容是 metadata 对象本身，如 `{"subject_id":"...","study_id":"...","age":40,"sex":"female","country":"CHN"}`，不是整份 analysis JSON。

验收条件：退出码 0；`audit.status=available`；`n_subjects>=30`；pipeline 为 4.2.2/精确 Jan25；`species_count` 是完整参考/待测物种并集；有可计算的多样性行；`target_raw_species_sum`、SHA256 和 limitations 已记录。若 P5=P95，只显示分位数，不判偏高/偏低。

随后在 `.env` 修改/加入以下三个唯一配置，并让报告服务重新加载：

```dotenv
WGS_HEALTHY_REFERENCE_PROVIDER=mho
WGS_HEALTHY_REFERENCE_DIR=/home/zhanghaiyang/fmt-healthcare-agent/var/reference/mho/jan25-825084d
WGS_MHO_PROFILES_DIR=/home/zhanghaiyang/fmt-healthcare-agent/var/reference-targets/mho
```

按项目现有服务管理方式重启 API（由拥有权限的运行用户执行，例如 `sudo bash deploy/restart-report-api.sh`），再使用现有“重新生成报告”入口。旧 PDF 不会因修改配置自动重写。

新报告应满足：

1. 分析 JSON 的 `healthy_comparison.audit.status` 为 `available`。
2. `metadata.reference_comparison.healthy_population.provider` 为 `mho`。
3. 报告 JSON 的 `template_inputs.healthy_comparison` 与分析结果一致；证据含 `HS*` 物种与 `HV*` 多样性。
4. Markdown/PDF 出现“MHOmicrobiome 对照”和“独立对照谱”，标明已分类物种内归一化、参考人数及局限。
5. 主分析的丰度及功能/FMT 等既有产物保持原逻辑。不能把主分析 4.2.4 百分数与 MHNO 表的分位数合并解读。

## 9. 常见失败、回滚和复现

| `audit.reason` 或错误 | 操作 |
|---|---|
| `reference_missing` | 核对 `$REF` 三个文件及报告运行用户读权限 |
| `invalid_reference` | SHA/结构/配置不符；从固定来源建新目录，勿手工篡改清单 |
| `target_unreadable` | 核对运行用户与独立产物目录读权限 |
| `target_missing` | 按第 6 节为该 SID 运行；检查 profiles 路径和样本编号 |
| `incompatible_pipeline` | 用独立 4.2.2 和精确 Jan25 重跑；不能伪造 provenance/header |
| `invalid_target` | 检查完整谱、有限非负百分数及 SHA；去除手工修改产物并在新目录重跑 |
| `missing_matching_metadata` | 补足真实人口学字段；需要改匹配策略时另建版本 |
| `insufficient_subjects` | 审查匹配策略/同人排除；不降低程序最低 30 人门槛 |
| `target_qc_failed` | 先解决既有样本质控失败原因 |
| 软件/比对命令失败 | 核对 4.2.2、Bowtie2 PATH、Jan25 完整索引、输入权限、磁盘；失败不会发布半成品 |

回滚：恢复原 `.env`，取消 `WGS_HEALTHY_REFERENCE_PROVIDER=mho` 并恢复此前的参考路径，重新加载报告服务，然后按需重新生成报告。保留本次新目录便于追溯；无需删除主流程产物。参考/软件新版本一律使用新目录，审核后再切换环境变量。

```bash
.venv/bin/python -m pytest -q tests/test_mho_reference.py tests/test_healthy_population.py \
  tests/test_report_reference_workflow.py tests/test_reporting.py \
  tests/test_health_report.py tests/test_detailed_report.py tests/test_word_template.py
```

本次上述 97 项相关测试在 gpu02 的隔离源码副本中全部通过，包含参考转换、版本/完整性拒绝、同人排除、主谱恢复、Word 表格/图表及 Markdown/PDF/JSON 产物链路。复现测试建议使用不带生产 `.env` 的源码副本，避免既有测试读取线上模型配置后等待实际服务；不需要在测试时重跑患者数据。

研究依据：[来源论文](https://doi.org/10.1038/s41467-026-72588-1)，[固定仓库版本](https://github.com/blacruz17/MHOmicrobiome/tree/825084dcc8ebb73efb9f4282a35f15920729eac4)，[作者 MetaPhlAn 处理脚本](https://github.com/blacruz17/MHOmicrobiome/blob/825084dcc8ebb73efb9f4282a35f15920729eac4/1_preprocessing/metaphlanScript.sh)。本功能仅使用物种矩阵，不会自动获得同口径的健康功能通路、病原风险模型或其他临床模型。
