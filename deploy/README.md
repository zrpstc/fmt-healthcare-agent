# 项目统一启动、关闭与重载

日常操作只使用下面三个入口，无需逐个处理模块：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
bash deploy/stop.sh
bash deploy/start.sh
```

一次完成停止和重新启动：

```bash
bash deploy/reload.sh
# restart.sh 与 reload.sh 等价
bash deploy/status.sh
```

前端固定使用当前配置的 18502，后端使用 18503，代理统一为 `/backend/:path*`。端口以项目 `.env` 为准。启动、关闭、重启、状态查询全部经过 `deploy/project.sh` 和 `deploy/runtime.py`。

## 整个项目的重载范围

- workspace API，包括其内部的 Agent、工具和报告逻辑。
- workspace Web，包括旧的预览实例及其 npm/Next 子进程。
- 独立 agent daemon，按现有配置决定是否启用。
- 项目托管的 Elasticsearch。外部 litkg、模型服务及其他项目的服务不由这里停止。

当前 `WGS_ELASTICSEARCH_MANAGED=true`。停止和启动托管 Elasticsearch 需要管理员权限。在交互终端运行入口脚本时，如需权限会通过 sudo 请求认证。也可以直接使用管理员入口：

```bash
sudo bash deploy/stop.sh
sudo bash deploy/start.sh
# 或
sudo bash deploy/reload.sh
```

权限和依赖管理连接在停止任何应用进程之前检查。权限不足时明确报错，不会先停掉网页，再留下无法处理的 Elasticsearch。状态查询可使用应用账号的只读集群健康接口，不需要 Docker 管理权限。

## 为什么现在能彻底重载

1. 不再单凭 PID 文件判断服务是否存在。会核对项目目录、启动命令、进程启动时间，发现并关闭当前项目的新旧实例及子进程。
2. 优先正常结束进程，等待退出；超时后结束仍属于该项目的残留进程。错误或失效的 PID 文件不会使其他服务被误停。
3. 关闭后验证没有项目进程残留，并清理旧 preview PID 记录。统一进程记录在 `var/run/project-processes.json`。
4. 启动重新读取 `.env`，不复用旧进程的环境，也不无条件复用存活实例。若直接 start 时服务已经运行，会要求改用 reload。
5. 前端按源码、依赖锁文件和后端代理配置验证构建；发生变化自动重新构建，未变化复用已验证产物。使用独立的 `.next-project-*` 构建目录，避免旧预览构建混用。
6. 等待后端知识库配置、样本列表、报告列表、前端页面和前端代理实际就绪；新实例启动失败会清理本次启动的组件，不把部分启动结果当成成功。状态查询也会检查样本与报告接口，500 会标记为 degraded。
7. 应用以 `.env` 中的 `WGS_RUN_USER` 运行，目前为 zhanghaiyang；管理员权限用于托管依赖管理。管理员启动 API 前，会把整个项目树的条目统一为该账号和组，并补齐所有者读写权限及目录访问权限。保留私有文件的私有属性和程序可执行属性；符号链接只调整链接本身，项目外目标保持原状。若硬链接还被项目外使用，先在项目内建立内容相同的独立文件，避免修改项目外文件的权限。Elasticsearch 的项目内控制文件也保持项目账号所有，Docker 数据卷位于项目外，不随该操作变更。

这里的“彻底重载”是结束项目进程、重启托管依赖、重读配置和必要时重新构建，不会删除数据库、研究数据、模型或 Elasticsearch 数据卷。

## 保留给 Agent 的细分入口

| 入口 | 操作 |
|---|---|
| `restart-report-api.sh` | 重新启动 workspace API |
| `restart-web.sh` | 重新构建必要产物并重启 Web |
| `restart-agent.sh` | 重启已配置的独立 agent daemon |
| `restart-elasticsearch.sh` | 重启项目托管的 Elasticsearch，需管理员权限 |
| `manage-preview-api.py` | 兼容原预览 API 管理方式，委托给统一管理器 |

这些入口只是统一管理器的薄包装，不各自维护另一套端口、PID 或进程判断逻辑。

旧 `activate-*` 的入口保留，现统一执行项目重载。它们原本带固定日期、旧构建和旧源码回滚的一次性迁移逻辑保存在 `deploy/legacy/*.sh.txt`，供历史查阅，不用于日常重载。环境安装、打包、恢复及诊断脚本仍保留各自用途。

## 验证记录

2026-11-05：27 项生命周期测试通过，生产前端构建成功。实际管理员全量重载后，新前后端均由项目用户运行，18502/18503 正常响应，网页代理和后端都确认 KB 30 / full。旧预览进程已消失，旧 preview PID 文件已清理。Elasticsearch 单节点返回 yellow，就绪检查通过，JVM 启动时间对应本次重载。

旧数据权限迁移完成后，实际样本与报告接口均返回 200，可读到 1 个样本与 1 份报告；样本详情与 5 个报告文件下载接口通过检查。需要在应用保持运行时单独执行旧权限迁移，可用 `sudo bash deploy/project.sh repair-data`，无须重启 Elasticsearch。迁移前的权限元数据保存在 `var/run/permission-migration-*.json`。

全项目所有权修复使用 `sudo bash deploy/project.sh repair-ownership`。已实查 230,803 个项目条目，非目标用户所有的条目、所有者权限缺失和不可访问条目均为 0；`var/bioinformatics/profiles/metaphlan/test_complete_data_profile.tsv` 已归属 zhanghaiyang，可读写。修复摘要记录在 `var/run/project-ownership-repair-*.json`。

随后实际重新生成 `test_complete_data` 报告：生成接口返回 200 / complete，耗时 221.1 秒，5 项产物均可下载。模型解读状态为 partial，24 个主题被采用。生成后复查 230,815 个条目，非目标用户所有、缺少所有者权限、不可访问条目及遍历错误均为 0。

测试覆盖失效和伪造 PID、PID 重用、旧预览进程及其脱离会话的子进程、外部进程不受影响、权限预检、代理配置不一致、启动失败清理，以及普通账号查询 Elasticsearch 状态。

修改前备份：`tmp/unified-deploy-20261105T025450/`。
