# 部署与日常操作

服务启动后会持续轮询就绪状态，默认最多45秒；API/Web的知识库配置、样本和报告列表接口，以及Web首页检查均通过后，启动命令才返回成功。临时连接失败、HTTP 500/503或数据接口尚未可用时会继续等待；进程退出、知识库配置错误或等待超时会报错。

初始化只准备应用运行目录和本地数据库模式。生信参考库由独立资源路径配置管理，不会因旧 `databases` 符号链接失效而尝试创建或替换它。

在项目目录执行，日常只使用四个入口：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
bash deploy/start.sh       # 启动
bash deploy/stop.sh        # 停止
bash deploy/restart.sh     # 重启并重新读取配置、检查前端构建
bash deploy/status.sh      # 只读状态检查
```

`start` 检查依赖、准备应用目录，按需构建前端，然后启动 API、Web 及配置启用的 agent。已有进程时返回 `PROJECT_ALREADY_RUNNING_USE_RESTART`，使用 `restart` 应用代码或配置变更。`restart` 在停止应用之前检查外部 Elasticsearch 是否可用；通过后停止并重新启动应用。正常退出会清理 PID 和运行状态。

每条命令返回 JSON。`status` 的 `result.ready` 表示全部启用的服务和 Elasticsearch 均通过检查；`ok: true` 只表示状态命令执行成功。API/Web 的检查包含样本、报告列表读取，不生成报告。agent 未启用时显示 `disabled`。

当前 gpu02 复用已运行的 Elasticsearch，采用 `WGS_ELASTICSEARCH_MANAGED=false`。启动时验证认证连接；应用停止、重启不会停止该外部依赖。若外部依赖不可用，返回 `EXTERNAL_ELASTICSEARCH_UNAVAILABLE`，先恢复 Elasticsearch 后再启动应用。项目内部仍支持受管 Elasticsearch，供明确配置独立实例的安装使用。

### 单独重启 Elasticsearch

```bash
bash deploy/restart-elasticsearch.sh                  # 自动找到发布 WGS_ELASTICSEARCH_URL 端口的本机容器
bash deploy/restart-elasticsearch.sh --container NAME # 或指定容器名（必须发布同一端口）
```

只重启 Elasticsearch，不停、不重启应用进程；`start`/`stop`/`restart` 的行为不变。容器在运行则 `docker restart`，已停止则 `docker start`，然后等待集群变为 green/yellow（最长 `WGS_ELASTICSEARCH_START_TIMEOUT` 秒，默认120，可用 `--timeout` 覆盖）。操作 Docker 需要管理员权限，交互终端会自动 sudo。受管模式下等同于 `restart --component elasticsearch`。

安全边界：只操作本机（URL 为 127.0.0.1/localhost）且端口与 `WGS_ELASTICSEARCH_URL` 一致的唯一容器；找不到、有多个或指定的容器端口不符时直接报错（`ELASTICSEARCH_CONTAINER_NOT_FOUND`、`ELASTICSEARCH_CONTAINER_AMBIGUOUS`、`ELASTICSEARCH_CONTAINER_PORT_MISMATCH`），不重启任何容器。重启后仍不健康时返回 `ELASTICSEARCH_UNHEALTHY_AFTER_RESTART` 及当前 health：磁盘水位、分片损坏等导致的 red 无法靠重启恢复，需按 `_cluster/allocation/explain` 的原因处理。该实例若还被其他项目使用，重启期间它们也会短暂不可用。

恢复健康后再执行 `bash deploy/restart.sh` 应用代码或配置变更。

以应用账号运行即可。需要管理员权限时，交互终端会由 sudo 直接认证；也可使用 `sudo bash deploy/start.sh` 等同一套入口。NFS 上的锁、日志、PID 和状态文件均以配置的应用用户身份访问。命令不输出凭据，不修改 NFS 导出规则。

`deploy/lib/` 是四个入口共用的实现，不是另一套日常命令。历史脚本完整保存在本机 Git 忽略的 `deploy-backup/` 中，保留原始相对路径，不能直接在备份位置运行。新克隆仓库不包含本机备份。逐项用途和处置见 [部署脚本核查表](../docs/DEPLOY_SCRIPT_AUDIT.md)。


## 单独重启报告 API 并刷新配置

```bash
bash deploy/restart-report-api.sh
```

该脚本固定执行 `restart --component workspace-api`，可从任意工作目录调用，也支持 `--json`。
它复用部署锁、进程身份校验、退出清理和就绪检查；重启前后重新读取项目 `.env`，使报告生成相关环境配置、Python 模块与模板随新进程生效。
报告生成目前与样本、聊天和知识接口共用 `workspace-api`，因此这些 API 在重启期间会短暂中断。脚本不重启 Web、Agent daemon 或 Elasticsearch，不执行前端构建，也不重新生成或覆盖已有报告。
修改报告相关配置后执行此脚本即可；配置值继续保留在原配置文件中，不通过脚本参数传入。传入其他 `--component` 也不能扩大重启范围。


## 已停用的旧工作区端口

工作区 Web/API 的默认端口为 `18502` / `18503`。`8502` / `8503` 已停用；部署入口会拒绝任何服务使用这两个旧端口并返回 `RETIRED_WORKSPACE_PORT`，且在重启停服前完成校验。
生产配置使用项目 `.env`；环境示例、前端 API 代理及辅助工具的默认值均使用新端口。历史备份与旧构建产物不作为当前部署配置，正常部署会按源代码指纹重新构建前端。


## cMD参考数据自动准备（扩大健康参考与人群模型）

只需在项目 `.env` 中指定存放新数据库的父目录，例如：

```dotenv
WGS_CMD_DATA_ROOT=/storageB/zhanghaiyang/fmtha-data/fmt-databases
```

该目录（或其上级）需对应用账号可写，其余目录和文件全部自动生成。之后照常执行：

```bash
git pull --ff-only origin main
bash deploy/restart.sh      # 首次部署用 start.sh
```

`start`/`restart` 在服务就绪后，若数据尚未齐备，会在后台启动 `scripts/prepare_cmd_data.py`，不阻塞、也不影响服务启动。它在 `<WGS_CMD_DATA_ROOT>/cmd/` 下依次完成：

| 步骤 | 产物 |
|---|---|
| 下载 ExperimentHub 官方资源目录（约10 MB） | `cmd/catalog/experimenthub.sqlite3` |
| 导出 cMD 3.18.0（Bioconductor 3.22）元数据，按官方MD5校验源码包 | `cmd/metadata-bioc3.22/` |
| 解压源码包并核对版本 | `cmd/metadata-bioc3.22/package/curatedMetagenomicData/` |
| 下载并导出各研究物种丰度矩阵 | `cmd/cache/` |
| 建扩大后的健康参考（约7,000人） | `cmd/healthy-cmd3.18.0-no_or_unrecorded/` |
| 建人群模型包（肠龄、肠型、健康指数、患病人群参考） | `cmd/cohort-models-v1-cmd3.18.0/` |
| 建疾病风险参考（孟德尔随机化权重 × 健康/患者人群评分分布） | `cmd/disease-risk-v1-cmd3.18.0-<权重哈希>/` |
| 建膳食营养参考（孟德尔随机化权重 × 健康人群评分分布） | `cmd/diet-nutrition-v1-cmd3.18.0-<权重哈希>/` |

每步已完成就跳过；中断或失败后，下次 `start`/`restart` 会从未完成的步骤继续。同一时间只运行一个准备进程（`cmd/prepare.lock`），`stop`/`restart` 不会打断正在进行的下载。进度和日志：

```bash
bash deploy/status.sh        # result.cmd_data：state 为 preparing/running/failed/interrupted/ready，含 step、error、log
```

准备期间报告继续使用原健康参考（`var/reference/cmd/native-v3`），肠龄肠型、患病人群参考、疾病风险评估与膳食营养评分暂不显示；新包发布后，运行中的服务自动切换，无需重启。消费者版报告随后打开即重建；专业版报告在下次生成时使用新参考。

前提：服务器能访问 `bioconductor.org`、`experimenthub.bioconductor.org` 及其数据存储地址，`PATH` 中有 `Rscript`（只用 base R；私有R库可设 `WGS_CMD_R_LIBRARY`）。常见错误码：`RSCRIPT_MISSING`、`CATALOG_DOWNLOAD_FAILED`、`METADATA_EXPORT_FAILED`、`MATRIX_EXPORT_FAILED`、`DATA_ROOT_NOT_WRITABLE`，详情见 `log` 指向的文件。

疾病风险参考的目录名带 `knowledge_base/disease_mr/disease_mr_weights.json` 的哈希，膳食营养参考带 `knowledge_base/diet_mr/diet_mr_weights.json` 的哈希：更新权重文件并重启后会自动建新包，不影响已有的健康参考和人群模型包（这一步复用 `cmd/cache/` 中已下载的矩阵，不重复下载）。

优先级：`.env` 中显式设置的 `WGS_CMD_REFERENCE_DIR`、`WGS_CMD_COHORT_DIR`、`WGS_CMD_DISEASE_RISK_DIR`、`WGS_CMD_DIET_NUTRITION_DIR` 始终优先；要使用自动准备的数据，请删除这两行。回退：删除 `WGS_CMD_DATA_ROOT` 后 `bash deploy/restart.sh`，即恢复原参考，肠龄肠型和患病人群参考自动隐藏；已准备的数据保留在原处。

也可以手动运行同一流程（前台、输出到终端）：

```bash
.venv/bin/python scripts/prepare_cmd_data.py
```
