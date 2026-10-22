# WGS-FMT-Agent v2

肠道菌群与 FMT 科研分析平台，支持 FASTQ 上传、物种和功能分析、供受体配型、知识检索及报告生成。前端使用 Next.js，后端使用 FastAPI。

请按照下面说明部署。

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

## 更多说明

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
