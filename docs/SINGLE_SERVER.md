# 单服务器架构

```text
浏览器 http://<服务器IP>:8502
        |
        v
Next.js 0.0.0.0:8502
        | /backend/* -> /*
        v
FastAPI 127.0.0.1:8503
        |-- var/ 下的本地数据库和文件
        |-- 本机模型服务 127.0.0.1:11434（可选）
        |-- 本机 LitKG 127.0.0.1:8080（可选）
        |-- 本机 Elasticsearch 127.0.0.1:9200（默认随项目启动）
        `-- 本机 Redis（可选）
```

浏览器中的 API 和文件地址保持同源相对路径。服务器 IP 改变后无需重新编译浏览器地址。
API 和 daemon 仅绑定回环地址；默认不启用跨域访问，如需独立前端可配置
`WGS_CORS_ORIGINS`。不再创建 SSH 转发，也不依赖旧服务器或跳板机。

## 数据布局

默认 `WGS_WORKSPACE=<项目根目录>/var`，所有相对路径均以项目根目录解析，
与执行命令时的工作目录无关。只设置 `WGS_WORKSPACE` 即可整体移动默认数据位置；
显式设置的单项路径优先。

| 目录/文件 | 用途 | 可选覆盖变量 |
|---|---|---|
| `var/db/wgs_agent.db` | 用户、认证会话、对话、消息、审计元数据 | `WGS_CONVERSATION_DB_FILE` |
| `var/knowledge/kb.db` | 本地文献与知识数据库 | `WGS_KB_SQLITE_PATH` 或 `WGS_KNOWLEDGE_DB` |
| `var/knowledge/documents/` | 知识文档 | `WGS_KB_DIR` |
| `var/knowledge/index/` | 知识索引预留位置 | `WGS_KB_INDEX_DIR` |
| `var/elasticsearch/` | 托管 ES 的管理密码与应用密码，目录 700、文件 600 | 随 `WGS_WORKSPACE` 移动 |
| `var/agent-config/` | Agent、Skill、设置及待确认动作 | `WGS_AGENT_CONFIG_DIR` |
| `var/uploads/` | 原始测序上传 | `WGS_UPLOAD_ROOT` |
| `var/upload-jobs/` | 上传任务状态 | `WGS_UPLOAD_JOB_ROOT` |
| `var/bioinformatics/` | 单样本分析结果、矩阵和 runner 状态 | `WGS_BIOINFORMATICS_OUTPUT_ROOT` |
| `var/bioinformatics/legacy/` | 兼容旧流程的矩阵结果（初始为空） | `WGS_LEGACY_PIPELINE_OUTPUT_DIR` |
| `var/results/` | 分析 JSON、报告及配型图 | `WGS_RESULTS_DIR` |
| `var/reference/` | 通路、代谢物及疾病表描述性统计；不作为健康物种参考 | `WGS_REFERENCE_DIR` |
| `var/reference/cmd/native-v3/` | cMD健康物种参考 | `WGS_CMD_REFERENCE_DIR` |
| `var/databases/` | 生信数据库 | 各工具数据库配置 |
| `var/model-training/`、`var/model-registry/` | 模型训练产物与注册信息 | `WGS_FMT_TRIPLET_MODEL_DIR`、`WGS_MODEL_REGISTRY_ROOT` |
| `var/fmt/` | 供体丰度及配对数据 | `WGS_FMT_DATA_ROOT` |
| `var/sandboxes/` | 用户/会话文件沙箱 | `WGS_AGENT_SANDBOX_ROOT` |
| `var/workspaces/default/` | 进程执行沙箱 | `WGS_SANDBOX_WORKSPACE` |
| `var/agent-audit/`、`var/logs/`、`var/traces/`、`var/run/` | 审计、日志、追踪、PID | 对应 `WGS_*` 配置 |
| `var/sessions/`、`var/runs/`、`var/policy.toml` | 可选 daemon 的会话、运行与权限策略 | `WGS_SESSIONS_DIR`、`WGS_RUNS_DIR`、`WGS_POLICY_FILE` |

`knowledge_base/` 仅保留 schema、脚本和文档；运行数据库和下载文献不再写入源码目录。
运行数据受 `.gitignore` 排除。新目录默认权限为 700，新数据文件为 600。

## 全新初始化

完成 Python 依赖安装后，在项目根目录运行：

```bash
.venv/bin/python scripts/init_data.py
```

脚本创建空的会话/用户数据库和知识数据库，不导入旧数据、不下载参考库、不调用外部接口、
不启动任何服务。重复执行会保留新环境中已有的记录。它不支持自动清空已有数据库。
首次启动 API 时会补齐默认 Agent/Skill/设置及系统内部用户；真实登录账号通过页面注册。

本地持久化默认使用 SQLite。`WGS_DATABASE_URL` 可显式切换数据库，初始化脚本只负责
本地 SQLite，并跳过显式配置的外部数据库；MySQL 等外部数据库需另行初始化。
Redis 和 LitKG 仍需单独启动。Elasticsearch 在运行 `deploy/start.sh` 时默认自动启动，
也可关闭托管模式；缺少相应服务时，相关记忆或检索功能会返回错误/降级状态。

生信 worker 默认路径为项目内的
`runtime/scripts/postfmt_pipeline/process_postfmt_sample.sh`，兼容流程脚本默认位于
`runtime/pipeline/`。单样本 Worker 已包含在仓库内，所需分析环境、外部工具、参考库和
训练模型需另行安装或恢复；缺失时分析功能会明确
返回不可用状态，不会自动读取其他项目目录。可通过 `.env.example` 中的变量指定本机安装位置。
恢复资源包后，设置 `WGS_FMT_RESOURCE_ROOT`（或 `FMT_ROOT`）即可识别其中的
`models/fmt-triplet-v1` 和 `data/fmt-matching/`，单项路径覆盖配置仍优先。
迁移步骤见 [README](../README.md#迁移生信运行资源)。

## 后续启动

参考 [README](../README.md) 完成前端构建后，才可手动运行 `bash deploy/start.sh`。
前端构建和启动必须使用相同的 `WGS_API_PORT`；修改该值需要重新构建。
启动脚本不会安装 Python/Web 依赖、构建前端、修改防火墙或连接 SSH 跳板机。

## Elasticsearch 随项目启动

默认 `WGS_ELASTICSEARCH_MANAGED=true`。安装并启动本机 Docker 后，当前用户需要有权访问
其 socket；脚本不会修改用户分组、socket 权限或内核参数，也不会使用远程 Docker context。
首次启动从 [Elastic 官方镜像仓库](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/docker.html)
拉取固定版本 `8.19.23`，已有镜像和容器会复用，不自动升级。

```bash
bash deploy/start.sh
bash deploy/status.sh
bash deploy/stop.sh
```

启动顺序为：本地数据初始化 → ES 就绪检查 → 配置应用账号 → 初始化 ES 索引 → API/Web。
ES 无法启动或认证失败时，启动脚本报错退出，不继续启动 API/Web。ES 启动超时会停止本次
新启动的 ES 容器，保留容器日志、凭据和数据；已在运行的实例不会因本次检查失败而被停止。
单节点的健康状态 `yellow`（副本未分配）允许继续启动。

| 配置 | 默认值 | 作用 |
|---|---|---|
| `WGS_ELASTICSEARCH_MANAGED` | `true` | `false` 时跳过自动启动和索引初始化，使用现有 URL/认证配置 |
| `WGS_ELASTICSEARCH_URL` | `http://127.0.0.1:9200` | 托管模式仅允许此回环地址，可修改端口，不能与项目其他端口冲突 |
| `WGS_ELASTICSEARCH_VERSION` | `8.19.23` | 官方镜像的固定 `8.x.y` 版本 |
| `WGS_ELASTICSEARCH_MEMORY` | `2g` | 容器内存上限，至少 `1g` |
| `WGS_ELASTICSEARCH_HEAP` | `512m` | JVM 堆，至少 `256m`，不超过容器内存一半 |
| `WGS_ELASTICSEARCH_START_TIMEOUT` | `120` | 容器启动后的就绪等待秒数；首次镜像下载另计 |
| `WGS_ELASTICSEARCH_DOCKER_SOCKET` | `/var/run/docker.sock` | 可改为 rootless Docker 的本机 socket |

ES HTTP 端口仅发布到宿主机 `127.0.0.1`，使用密码认证；该本机连接使用 HTTP。
集群传输端口不发布。管理密码和仅用于当前知识索引的应用账号密码分别保存在
`$WGS_WORKSPACE/elasticsearch/password` 和 `client-password`，不会输出到启动日志。
托管模式会为 API/daemon 注入 `WGS_ELASTICSEARCH_USERNAME=wgs-platform` 和
`WGS_ELASTICSEARCH_PASSWORD_FILE`，并清空外部 `WGS_ELASTICSEARCH_API_KEY`。
升级前已经运行的 API/daemon 需通过 `stop.sh`、`start.sh` 重启以读取这些环境变量。
直接运行 uvicorn、CLI 或独立工具时，需自行设置这两个环境变量才能访问托管实例。

索引数据位于 Docker 命名卷 `wgs-elasticsearch-<工作区路径哈希>-data`，容器名称去掉 `-data`。
`status.sh` 会显示实际名称。停止项目只停止该工作区创建的 ES 容器，不删除卷或凭据，
也不会接管已占用端口的其他实例。备份需同时保存索引快照和凭据目录；仅备份 `var/`
不包含 Docker 卷中的索引。移动 `WGS_WORKSPACE` 会使用另一个容器/卷，应另行迁移数据。
不要删除密码文件后继续复用旧数据卷。

更改镜像版本、端口或内存配置时，脚本会拒绝复用配置不匹配的旧容器。
需要先停止项目、保存索引快照，再仅重建对应 ES 容器，保留原数据卷与密码目录；
切勿删除数据卷或尝试将已有数据降级到旧版 ES。恢复原配置可继续复用未重建的旧容器。
关闭托管模式后，`stop.sh` 仍可停止之前由本工作区创建的实例。

手动连接外部实例时可使用现有 API key，或设置 `WGS_ELASTICSEARCH_USERNAME` 和
`WGS_ELASTICSEARCH_PASSWORD_FILE`；API key 优先。密码文件路径相对项目根目录解析。
