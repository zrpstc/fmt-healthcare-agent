> MHOmicrobiome automatic profiling is now supported: see [automatic setup](docs/MHO_AUTOMATIC.md).

# WGS-FMT-Agent v2

肠道菌群与 FMT 科研分析平台，支持 FASTQ 上传、物种和功能分析、供受体配型、知识检索及报告生成。前端使用 Next.js，后端使用 FastAPI。

请按照下面说明部署。

健康人群参考采用 MHOmicrobiome 时，请按 [MHOmicrobiome 准备与接入指南](docs/MHOMICROBIOME_REFERENCE.md) 下载约 9.1 MB 预计算数据、构建 MHNO 参考，并为待测样本准备独立 MetaPhlAn 4.2.2 对照谱。

## 1. 准备服务器

需要安装：

- Python **3.12**，并支持创建虚拟环境。
- Node.js **22**，包含 npm。
- Conda、Mamba 或 Micromamba 中的一种。
- Docker：默认用于启动 Elasticsearch，当前用户需要有访问权限。

Ubuntu 可由管理员安装虚拟环境支持和中文 PDF 字体：

```bash
sudo apt-get install python3.12-venv fonts-wqy-microhei
```

后续项目安装、启动和停止统一使用同一个普通用户执行。

## 2. 获取项目并准备资源

首次获取源码：

```bash
git clone https://github.com/Sandro-Z/fmt-healthcare-agent.git
cd fmt-healthcare-agent
```

已有项目直接进入项目根目录。下文以：

```text
/home/zhanghaiyang/fmt-healthcare-agent
```

为例，其他服务器请替换成实际路径。

从原服务器复制以下资源：

| 位置 | 内容 |
|---|---|
| `fmt-databases/` | `kneaddata/`、`metaphlan4/`、`metaphlan4_vJun23/`、`humann3/` |
| `data/model-training/fmt-triplet-v1/` | 完整模型目录，包含 `feature_schema.json`、`fmt_triplet_contrastive_model.npz` 和模型清单 |
| `var/data/fmt-matching/` | `species_abundance_train.csv`、`match.xlsx` |

参考数据库需要保留完整索引文件，包括 Jan25 和 vJun23 两套 MetaPhlAn 数据库。

为兼容当前检查脚本，在 `var/databases` 尚不存在时创建软链接：

```bash
mkdir -p var
ln -sT "$PWD/fmt-databases" var/databases
```

已有正确链接可跳过；如果该位置已有目录，先确认其内容。

数据库、模型、样本、报告和密钥通过 Git 之外的方式保存和迁移。完整资源清单见 [资源说明](runtime/resources/README.md)。

## 3. 配置 `.env`

首次创建配置文件：

```bash
test -f .env || cp .env.example .env
chmod 600 .env
```

编辑 `.env`，修改已有变量或取消对应注释，每个变量只保留一个有效定义：

```dotenv
WGS_ENV=production
WGS_ENV_ROOT=./.venv
WGS_WORKSPACE=./var

WGS_WEB_HOST=0.0.0.0
WGS_WEB_PORT=8502
WGS_API_PORT=8503
WGS_CORS_ORIGINS=

FMT_ROOT=/home/zhanghaiyang/fmt-healthcare-agent/var
WGS_FMT_RESOURCE_ROOT=/home/zhanghaiyang/fmt-healthcare-agent/var
ENV_ROOT=/home/zhanghaiyang/fmt-healthcare-agent/var/runtime/envs
DB_ROOT=/home/zhanghaiyang/fmt-healthcare-agent/fmt-databases

WGS_FMT_TRIPLET_MODEL_DIR=/home/zhanghaiyang/fmt-healthcare-agent/data/model-training/fmt-triplet-v1

WGS_UPLOAD_THREADS=4
```

其他路径覆盖项通常保持注释，上传、报告、日志和本地数据库会自动放在 `var/` 下。模型存放位置不同时，应同步修改 `WGS_FMT_TRIPLET_MODEL_DIR`。

外部服务按实际情况配置：

| 服务 | 配置方式 |
|---|---|
| 业务数据库 | 默认使用 SQLite，保持 `WGS_DATABASE_URL` 注释即可 |
| Elasticsearch | 有本机 Docker 权限时保留 `WGS_ELASTICSEARCH_MANAGED=true` |
| 独立 Elasticsearch | 设置 `WGS_ELASTICSEARCH_MANAGED=false`，填写实际地址和认证信息 |
| 暂不使用 Elasticsearch | 设置 `WGS_ELASTICSEARCH_MANAGED=false`，相关检索功能暂不可用 |
| Redis | `WGS_REDIS_URL` 指向实际运行的服务 |
| LitKG | 配置实际的 `WGS_CLAIM_API_URL`、Token 和知识库 ID |

填写服务地址不会自动安装或启动 Redis、LitKG 等外部服务。其余参数初次部署可保留模板默认值。

## 4. 安装应用和生信环境

### 应用依赖

```bash
python3.12 -m venv .venv &&
.venv/bin/python -m pip install -r requirements.txt &&
.venv/bin/python -m pip check
```

如果虚拟环境创建失败，先处理报错，再继续安装。

### 生信环境

生信安装和检查脚本需要先将 `.env` 导出到当前终端：

```bash
set -a
source .env
set +a

bash deploy/install-bioinformatics-envs.sh &&
bash deploy/check-bioinformatics-runtime.sh
```

安装脚本分别创建 `fmt-tax` 和 `fmt-func`，默认位置为：

```text
var/runtime/envs/fmt-tax
var/runtime/envs/fmt-func
```

源码目录 `runtime/environments/` 保存环境定义文件。

检查出现 `Runtime check passed` 后，再验证程序能够运行：

```bash
"$ENV_ROOT/fmt-tax/bin/metaphlan" --version
"$ENV_ROOT/fmt-func/bin/humann" --version
```

### 初始化数据并构建前端

```bash
.venv/bin/python scripts/init_data.py &&
npm ci --prefix apps/workspace-web &&
NEXT_TELEMETRY_DISABLED=1 npm run build --prefix apps/workspace-web
```

初始化会创建运行目录和空的本地数据库，保留已有记录。原服务器的账号、会话、文献及历史报告需要另行迁移。

## 5. 启动和使用

从项目根目录启动：

```bash
bash deploy/start.sh &&
bash deploy/status.sh
```

默认访问地址：

```text
http://<服务器IP>:8502/
```

服务器防火墙需要允许访问 Web 端口。API 默认仅监听本机 `127.0.0.1:8503`。

首次使用：

1. 打开网页并注册账号。
2. 在设置页面填写模型服务地址、API Key 和默认模型，测试连接。
3. 上传一个已知样本，验证分析、配型和报告流程。

网页对话模型通过设置页面配置；仅填写 `.env` 中的 `DEEPSEEK_API_KEY` 不会自动完成网页模型配置。

健康检查：

```bash
curl -fsS http://127.0.0.1:8503/health
curl -fsS http://127.0.0.1:8503/api/backend/health
```

健康接口正常后，仍需通过实际样本确认生信流程和报告功能可用。

## 6. 日常管理

查看状态：

```bash
bash deploy/status.sh
```

停止服务：

```bash
bash deploy/stop.sh
```

修改配置时，先使用旧配置停止服务，再编辑 `.env` 并重新启动。修改 `WGS_API_PORT` 后，还需要重新构建前端：

```bash
npm run build --prefix apps/workspace-web
```

启动、停止和状态脚本会自动读取 `.env`。手动运行生信安装或检查脚本前，需要重新执行 `set -a`、`source .env`、`set +a`。

运行数据默认保存在 `var/`，应用日志位于 `var/logs/`。

## 7. 常见问题

**创建 `.venv` 时提示 `ensurepip is not available`**

安装 `python3.12-venv` 后重试。已有 `.venv` 时，先确认其 Python 和 pip 是否正常，再决定是否重建。

**Conda 收集索引时提示 `sqlite3.OperationalError: database is locked`**

使用 `conda-libmamba-solver 26.4.0` 时，可临时关闭分片索引后重试：

```bash
CONDA_PLUGINS_USE_SHARDED_REPODATA=false \
  bash deploy/install-bioinformatics-envs.sh &&
bash deploy/check-bioinformatics-runtime.sh
```

**检查提示缺少生信程序**

确认安装过程已经成功结束，并检查 `var/runtime/envs/`。仅创建 `.venv` 或安装 `requirements.txt` 不会安装生信环境。

**PID 文件或 Docker 提示 `Permission denied`**

核对运行目录属主和 Docker 访问权限，由管理员修正后再运行。应用统一使用同一个普通用户管理。状态脚本无法读取 PID 时，不能据其输出判断服务是否已经停止。

## 8. 准备健康人群对照数据（ENA）

以下命令全部在 **gpu02 的项目根目录**执行：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
```

数据准备顺序是：**样本信息 → ENA 下载清单 → R1/R2 FASTQ → 下载校验 → 生信处理 → 健康参考库**。
下载完成还不能直接用于报告；需要按本项目分析版本生成完整物种谱，再构建参考库。

### 第一步：准备样本信息（本机已完成）

```bash
Rscript scripts/export_cmd_metadata.R
```

该命令仅读取官方源码包中的元数据，不需要安装整套 R 分析包。
结果为 `var/reference-sources/cmd/sample_metadata.tsv`，当前快照包含22,588条样本记录、141个字段。
其中既有健康样本，也有疾病样本，不能直接把全部记录作为健康对照。

### 第二步：生成明确的下载清单（不下载 FASTQ）

下面以 `AsnicarF_2021 / PRJEB39223` 为演示批次，选择50名符合标签筛选的候选者：

```bash
.venv/bin/python scripts/healthy_ena.py prepare \
  --study AsnicarF_2021 \
  --ena-project PRJEB39223 \
  --limit 50
```

脚本要求粪便、成年、明确标注 `control + healthy`、当前未使用抗生素，排除标注妊娠/哺乳者，
同一研究的同一个体只选一份。未提供的妊娠/哺乳信息会列入 `review_flags`，不会被当成已确认的否定记录。
这仍是**待审核候选批次**，需要核对原研究纳入条件和目标人群适用性。

该 ENA 项目同时包含 WGS 和 AMPLICON 数据，不能直接下载整个项目。
脚本只选与元数据 run 编号对应的 **Illumina 双端宏基因组 WGS**，不纳入16S扩增子。

下载计划保存在 `var/reference-sources/healthy-ena-demo/`：

| 文件 | 用途 | 是否测序数据 |
|---|---|---|
| `selected_samples.tsv` | 候选者、样本编号、个体编号、年龄、性别、地区；保留待审核状态 | 否 |
| `ena_runs.tsv` | 所选 ENA run 的文件地址、MD5、字节数和测序类型 | 否 |
| `download_manifest.tsv` | 每个要下载的文件对应的地址、大小、MD5和本地路径 | 否 |
| `checksums.md5` | 预期 MD5 校验清单 | 否 |
| `selection.json` | 候选人数、文件总数、预计下载量和来源哈希 | 否 |
| `groups/*.json`、`processing_manifest.tsv` | 将本地 R1/R2 与生信处理样本对应起来 | 否 |
| `raw/<run>/<run>_1.fastq.gz` | 真正需要下载的 R1 reads | **是** |
| `raw/<run>/<run>_2.fastq.gz` | 真正需要下载的 R2 reads | **是** |

示例计划已在 gpu02 生成：**50名候选者、50个run、100个FASTQ文件，压缩文件合计约217 GB（202.08 GiB）**。
生信处理还需另留临时和结果空间。先查看计划和剩余空间：

```bash
cat var/reference-sources/healthy-ena-demo/selection.json
df -h var/reference-sources
```

### 第三步：先下载一份样本的两个 FASTQ

```bash
.venv/bin/python -u scripts/healthy_ena.py download --runs 1
.venv/bin/python scripts/healthy_ena.py verify --runs 1
```

本示例第一份样本是 `SAMEA7041133`，对应 run `ERR4330026`。会下载这**两个文件**，合计约4.07 GB：

```text
var/reference-sources/healthy-ena-demo/raw/ERR4330026/ERR4330026_1.fastq.gz
var/reference-sources/healthy-ena-demo/raw/ERR4330026/ERR4330026_2.fastq.gz
```

`_1` 是R1、`_2` 是R2，两者必须成对。保留 `.gz` 压缩格式及原文件名，下载器会自动放到对应目录。
下载中使用 `.part` 后缀；大小和 MD5 都通过后才改为正式文件名。中断后重新运行同一下载命令可续传。
最终看到两条 `VERIFIED` 及 `Verified 2 FASTQ files` 才表示这一次下载完整。

### 第四步：确认空间与试跑结果后，下载剩余批次

```bash
.venv/bin/python -u scripts/healthy_ena.py download --runs 50
.venv/bin/python scripts/healthy_ena.py verify --runs 50
```

已经通过校验的文件会复用。`--runs 50` 表示下载计划中的前50个run，不是新增50个。
本示例一人一份样本、一份样本一个run；其他研究可能一份生物样本对应多个run，需要全部保留并归并处理。
本批次全部完成后应看到 `Verified 100 FASTQ files`，结果写入 `download_status.tsv`。

### 第五步：生信处理后，才能构建健康参考库

先对已经下载并校验的第一份样本试跑。此步骤会启动实际生信计算：

```bash
set -a
source .env
set +a

bash runtime/scripts/postfmt_pipeline/process_postfmt_sample.sh \
  --group-json var/reference-sources/healthy-ena-demo/groups/SAMEA7041133.json \
  --output-root "$PWD/var/reference-sources/healthy-processed" \
  --threads 4
```

该流程依次运行质控、去宿主、MetaPhlAn及HUMAnN。第一份完整物种谱将生成在：

```text
var/reference-sources/healthy-processed/profiles/metaphlan/SAMEA7041133_profile.tsv
```

下载的 MD5 通过只表示传输完整，不表示测序质控通过。`selected_samples.tsv` 中的
`health_status=candidate`、空的 `qc_pass` 是待审核状态。完成健康条件核对和测序质控后，
将符合条件者整理成建库用的 `metadata.tsv`（`health_status=healthy`、`qc_pass=true`），
保留原来的 `sample_id/subject_id/study_id`，再按[健康对照建库说明](docs/HEALTHY_POPULATION_CONTROL.md#构建并接入)
运行 `scripts/build_healthy_reference.py`。

最终报告读取的是以下三个文件，而不是原始 FASTQ：

```text
var/reference/healthy/manifest.json
var/reference/healthy/metadata.tsv
var/reference/healthy/species_abundance.tsv
```

**目录区分：**原始健康样本放 `var/reference-sources/healthy-ena-demo/raw/`；处理结果放
`var/reference-sources/healthy-processed/`；最终健康参考库放 `var/reference/healthy/`。
`fmt-databases/` 存放物种/功能注释索引，不放这些样本的 FASTQ。

字段和校验依据见 [ENA 文件报告](https://ena-docs.readthedocs.io/en/latest/retrieval/programmatic-access/file-reports.html)
及 [ENA 下载说明](https://ena-docs.readthedocs.io/en/latest/retrieval/file-download.html)。


## 更多说明

重启 Elasticsearch 时，HTTP 端口可能先于认证状态就绪。启动脚本会在
`WGS_ELASTICSEARCH_START_TIMEOUT`（默认 120 秒）内重试临时的 401/403；
持续认证失败才报告凭据错误，认证成功但集群未就绪则报告启动超时。

需要核查时，可从项目目录运行以下命令；它只启动已有的本项目容器并输出脱敏诊断，保留密码和数据卷：

```bash
sudo bash deploy/diagnose-elasticsearch.sh --start-existing --duration 60
```

- [项目架构](docs/PROJECT_ARCHITECTURE_GUIDE.md)
- [报告相关知识子图](docs/REPORT_KNOWLEDGE_SUBGRAPHS.md)
- [环境说明](docs/ENVIRONMENT.md)
- [单服务器部署与数据目录](docs/SINGLE_SERVER.md)
- [资源清单与离线迁移](runtime/resources/README.md)
- [中文 PDF 字体](src/wgs_agent/tools/fonts/README.md)

开发验证：

```bash
.venv/bin/python -m pytest
npm run build --prefix apps/workspace-web
```
