# WGS-FMT-Agent v2

肠道菌群与 FMT 科研分析平台，支持 FASTQ 上传、物种和功能分析、供受体配型、知识检索及报告生成。前端使用 Next.js，后端使用 FastAPI。

请按照下面说明部署。

健康参考仅使用 curatedMetagenomicData（cMD3 / MetaPhlAn 3 / v30）。准备、分层及变量迁移见 [cMD指南](docs/CMD_REFERENCE.md)。

## 消费者版网页报告

专业版 PDF/Markdown 保持不变。平台另生成 `{sample}_consumer_report.json`（契约 `consumer-report/1`），并通过 `/r/{sample}` 内部预览、`/share/{token}` 公开只读页、`/reports` 分享入口和 `/reports/review` 术语审核台提供消费者版阅读体验。详见 [设计规范](docs/consumer-web/DESIGN.md)、[运维说明](docs/consumer-web/OPERATIONS.md) 和 [默认决策](docs/consumer-web/DECISIONS.md)。

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
WGS_WEB_PORT=18502
WGS_API_PORT=18503
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

生信环境定义保存在 `runtime/environments/fmt-tax.yml` 和 `runtime/environments/fmt-func.yml`。当前服务器复用已安装环境。历史安装、检查、打包和恢复工具已归档至本机 Git 忽略的 `deploy-backup/`，不再作为受维护的部署入口；新服务器按环境定义和资源清单准备依赖，见 [资源说明](runtime/resources/README.md)。

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
http://<服务器IP>:18502/
```

服务器防火墙需要允许访问 Web 端口。API 默认仅监听本机 `127.0.0.1:18503`。

首次使用：

1. 打开网页并注册账号。
2. 在设置页面填写模型服务地址、API Key 和默认模型，测试连接。
3. 上传一个已知样本，验证分析、配型和报告流程。

网页对话模型通过设置页面配置；仅填写 `.env` 中的 `DEEPSEEK_API_KEY` 不会自动完成网页模型配置。

健康检查：

```bash
curl -fsS http://127.0.0.1:18503/health
curl -fsS http://127.0.0.1:18503/api/backend/health
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

修改代码或 `.env` 后，只需执行：

```bash
bash deploy/restart.sh
```

四个日常入口为 `start.sh`、`stop.sh`、`restart.sh`、`status.sh`；命令自动读取项目 `.env`，需要时重新构建前端。以 [部署说明](deploy/README.md) 为准。

运行数据默认保存在 `var/`，应用日志位于 `var/logs/`。

## 7. 常见问题

**创建 `.venv` 时提示 `ensurepip is not available`**

安装 `python3.12-venv` 后重试。已有 `.venv` 时，先确认其 Python 和 pip 是否正常，再决定是否重建。

历史生信安装和迁移脚本已归档，不再通过日常部署命令安装或迁移参考库。使用 `runtime/environments/` 的环境定义准备生信工具。

**检查提示缺少生信程序**

确认安装过程已经成功结束，并检查 `var/runtime/envs/`。仅创建 `.venv` 或安装 `requirements.txt` 不会安装生信环境。

**PID 文件或 Docker 提示 `Permission denied`**

核对运行目录属主和 Docker 访问权限，由管理员修正后再运行。应用统一使用同一个普通用户管理。状态脚本无法读取 PID 时，不能据其输出判断服务是否已经停止。

## 8. cMD健康参考

唯一来源是cMD3已发表的成人健康标签粪便对照；报告使用独立MetaPhlAn 3.0.14/v30待测谱。
未设置 `WGS_HEALTHY_REFERENCE_PROVIDER` 或设为 `cmd` 均使用cMD；其他值明确报不支持。
参考包缺失、SHA256不符、版本不兼容、匹配后不足30人时显示“未建立健康对照”，不回退。

P5、P95和目标百分位附固定种子1000次bootstrap的95%置信区间；边界重叠不判高低。
物种越界数另与参考者计数分布比较。支持country/sex/age_band分层、测序深度提示和研究批次摘要。
建包参数、离线报告行为和迁移表见 [cMD指南](docs/CMD_REFERENCE.md)。不会自动重建或发布参考包。

推荐只在 `.env` 设置 `WGS_CMD_DATA_ROOT=<新数据库父目录>`，由 `deploy/start.sh` 在后台自动准备下述数据并在完成后启用（见 [部署说明](deploy/README.md)）。手动方式：`export_cmd_metadata.R --bioc-release 3.22` 配合 `prepare_cmd_reference.py --antibiotics-policy no_or_unrecorded` 可把健康参考从3,537人扩大到约7,000人。`scripts/prepare_cmd_cohort_models.py` 用同一批cMD数据另建人群模型包（`WGS_CMD_COHORT_DIR`），提供肠道年龄、肠型、健康指数和10类疾病患者人群参考，供消费者版总体健康得分、肠龄肠型章节和致病基因章节使用；未配置时这些内容自动隐藏。

## 更多说明

当前 gpu02 复用现有 Elasticsearch。应用重启前会检查认证连接；应用停止和重启不会操作外部依赖的容器、数据卷或密码。排错统一使用 `bash deploy/status.sh`，详细行为及旧脚本处置见 [部署说明](deploy/README.md)。

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
