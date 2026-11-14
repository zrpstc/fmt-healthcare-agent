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

以应用账号运行即可。需要管理员权限时，交互终端会由 sudo 直接认证；也可使用 `sudo bash deploy/start.sh` 等同一套入口。NFS 上的锁、日志、PID 和状态文件均以配置的应用用户身份访问。命令不输出凭据，不修改 NFS 导出规则。

`deploy/lib/` 是四个入口共用的实现，不是另一套日常命令。历史脚本完整保存在本机 Git 忽略的 `deploy-backup/` 中，保留原始相对路径，不能直接在备份位置运行。新克隆仓库不包含本机备份。逐项用途和处置见 [部署脚本核查表](../docs/DEPLOY_SCRIPT_AUDIT.md)。
