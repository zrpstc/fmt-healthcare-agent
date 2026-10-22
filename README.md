# WGS-FMT-Agent v2

肠道菌群临床分析智能体。当前活动界面是 Next.js，业务接口是 FastAPI；样本处理、FMT
配型、知识检索、报告生成和 Agent 工具保留为共享 Python 包。旧 Streamlit 界面和旧 8000
端口 API 已从活动源码移除。

第一次接触本项目，请先阅读 `docs/PROJECT_ARCHITECTURE_GUIDE.md`，其中包含整体调用链、
常用依赖、模块对应关系、数据存储方式和完整安装启动流程。

参考人群筛选、公开数据来源以及“主报告 + 技术附录 + 交互展示”三层报告规范见
`docs/REFERENCE_COHORTS_AND_REPORT_LAYERS.md`；首批队列清单位于
`config/reference_cohorts.json`。

## 目录结构

```text
apps/
  workspace-web/          Next.js 用户界面（8502）
  workspace-api/          FastAPI 工作区接口（8503）
    app/
src/
  wgs_agent/              Agent、Pipeline、工具和领域逻辑
  wgs_fmt_platform/       契约、基础设施、模型和报告能力
deploy/
  start.sh                启动当前系统
  stop.sh                 停止当前系统
  status.sh               查看状态
  restore-reverse-tunnels.sh
runtime/
  scripts/                可迁移的宏基因组分析 Worker
  environments/           MetaPhlAn/HUMAnN 精确环境定义
  resources/              大型资源清单与迁移说明
data/                     本地运行数据（不提交 Git）
datasets/                 评测数据集
knowledge_base/           本地知识资源
infrastructure/           MySQL/PostgreSQL/SQLite 初始化资源
scripts/                  离线处理、训练和运维脚本
tests/                    共享 Python 单元与集成测试
```

运行期日志、PID、结果和上传文件位于项目外：
`/storage/main/users/zhangrongpeng/data/fmt/wgs-fmt-agent-v2-data`。

Git 仓库仅保存源码、测试、文档和配置模板。`.env`、数据库、样本、报告、审计日志、
模型产物、下载文献、向量索引及字体二进制均由 `.gitignore` 排除。中文 PDF 字体的本地
安装方式见 `src/wgs_agent/tools/fonts/README.md`。

## 迁移到其他服务器

仓库已经包含应用源码、分析 Worker、环境版本、资源清单以及在线重建/离线迁移脚本。
参考数据库和 Conda 环境合计约 113 GiB，不进入普通 Git；它们以带 SHA-256 校验的分组件
资源包迁移。FASTQ、患者资料、生产数据库、API Key 和 `.env` 也不得提交。

```bash
# 源服务器：制作离线资源包（OUTPUT_DIRECTORY 应位于有足够空间的存储）
export FMT_ROOT=/storage/main/users/zhangrongpeng/data/fmt
bash deploy/package-bioinformatics-runtime.sh /path/to/wgs-fmt-shotgun-v1

# 目标服务器：克隆仓库后恢复资源
export FMT_ROOT=/srv/wgs-fmt
bash deploy/restore-bioinformatics-runtime.sh /path/to/wgs-fmt-shotgun-v1
cp .env.production.example .env
# 修改 .env 中的路径、密码、Token 和服务地址
bash deploy/start.sh
bash deploy/status.sh
```

若目标服务器可联网，可先运行 `bash deploy/install-bioinformatics-envs.sh` 重建两个分析环境，
再从官方来源安装参考数据库。完整清单及说明见 `runtime/resources/README.md`。

## 启动与停止

首次部署或重建依赖环境时，先按照 `docs/ENVIRONMENT.md` 创建 Conda/Node 环境并配置
生产 `.env`。完整且精确锁定的 Python 包版本位于 `requirements.txt`，前端版本位于
`apps/workspace-web/package-lock.json`。日常启动命令如下：

```bash
cd /storage/main/users/zhangrongpeng/data/fmt/apps/WGS-FMT-Agent-v2
bash deploy/start.sh
bash deploy/status.sh
```

浏览器访问：`http://10.181.9.172:8502/`。前端通过 `/backend/*` 反向代理到本机
8503 端口，外部用户不需要直接访问后端。

```bash
bash deploy/stop.sh
```

默认路径可以用 `WGS_APP_ROOT`、`WGS_ENV_ROOT` 和 `WGS_WORKSPACE` 覆盖。

## 开发与验证

```bash
# Python
/storage/main/users/zhangrongpeng/data/fmt/runtime/envs/wgs-fmt-agent-v2/bin/pip install -e '.[dev,infra,legacy]'
/storage/main/users/zhangrongpeng/data/fmt/runtime/envs/wgs-fmt-agent-v2/bin/pytest

# Web
cd apps/workspace-web
npm install
npm run build
```

FastAPI 开发启动：

```bash
python -m uvicorn app.main:app --app-dir apps/workspace-api --host 0.0.0.0 --port 8503 --reload
```

## 安全约束

- API Key 只通过环境变量或权限受控的运行期配置注入，不提交到源码。
- Pipeline、报告覆盖及其他写操作必须经过确认和审计。
- 临床关联结果仅供科研分析，不能替代临床诊断或治疗决策。
- 沙箱只允许访问配置的工作区根目录。

## 迁移与回退

本次目录整理说明及完整备份位置见 `docs/ACTIVE_SYSTEM.md`。
