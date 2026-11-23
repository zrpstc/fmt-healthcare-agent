# 部署脚本核查与收敛

基线 HEAD：`adc05f6dfec078fe93da117e8787ec7fdf238c6e`。核查对象为清理前 `deploy/` 的全部 32 个文件：21 个 Shell 脚本、5 个 Python 脚本、4 个历史脚本文本及2个说明文件。所有 Shell 语法检查、Python 编译检查通过；语法通过不代表应继续作为部署入口使用。

日常命令只保留 `bash deploy/start.sh`、`bash deploy/stop.sh`、`bash deploy/restart.sh`、`bash deploy/status.sh`。前三者改变应用运行状态，`status` 只读。`restart` 统一承担代码与配置刷新，按需重建前端。必要实现保留在 `deploy/lib/`。

| 原路径（相对 deploy/） | 核实后的实际用途 | 当前有效性及处置 |
| --- | --- | --- |
| `start.sh` | 委托运行核心启动整项目 | 保留，唯一启动入口 |
| `stop.sh` | 委托运行核心停止整项目 | 保留，唯一停止入口 |
| `restart.sh` | 委托运行核心停止后启动、重新读配置 | 保留，唯一重启入口 |
| `status.sh` | 委托运行核心读取状态 | 保留，补充外部依赖健康与整体 ready |
| `project.sh` | 选择项目 Python、转发动作、交互 sudo | 有效共用逻辑；原件归档，实现收敛到 `lib/command.sh` |
| `runtime.py` | 进程发现、PID 防误杀、构建、读配置及依赖调度 | 必要核心；原件归档，维护版本移至 `lib/runtime.py` |
| `project_ownership.py` | 目录属主、权限与硬链接修复 | 必要内部辅助；原件归档，维护版本移至 `lib/project_ownership.py` |
| `reload.sh` | 与 restart 相同的停止再启动动作 | 重复入口，归档；统一使用 restart |
| `restart-agent.sh` | 按组件重启 agent | 有效但非整项目入口，归档 |
| `restart-elasticsearch.sh` | 按组件重启受管搜索服务 | 不适用于当前外部依赖模式，归档；现由新的 `deploy/restart-elasticsearch.sh` 取代（同时支持外部容器，见 deploy/README.md） |
| `restart-report-api.sh` | 按组件重启 workspace-api | 有效但重复管理入口，归档 |
| `restart-web.sh` | 按组件重启 workspace-web | 有效但重复管理入口，归档 |
| `activate-agent-runtime.sh` | 实际已是整项目 restart 的兼容别名 | 名称与实际用途不符，归档 |
| `activate-knowledge-ui.sh` | 实际已是整项目 restart 的兼容别名 | 名称与实际用途不符，归档 |
| `activate-mho-automatic.sh` | 实际已是整项目 restart 的兼容别名 | 不再执行 MHO 操作；旧名称归档 |
| `activate-report-templates.sh` | 实际已是整项目 restart 的兼容别名 | 不再执行专门模板迁移，归档 |
| `activate-specialized-metabolism.sh` | 实际已是整项目 restart 的兼容别名 | 不再执行专门功能回填，归档 |
| `manage-preview-api.py` | 转发到统一核心的 API 组件管理 | 兼容入口，已无独立预览生命周期，归档 |
| `knowledge_runtime.py` | 旧 PID 匹配检查及 API 组件管理 | 兼容用途，归档 |
| `common.sh` | source .env、解析旧 Shell 环境、提供 ES 调用 | 旧脚本共用函数；四个入口不再依赖，归档 |
| `diagnose-runtime.py` | 只读检查 NFS 锁、状态和日志权限 | 诊断脚本有效，非日常入口，归档；状态统一使用 status |
| `diagnose-elasticsearch.sh` | 加载 common 后调用搜索诊断程序，可选启动旧容器 | 不适用于当前目录对应容器不存在的场景，归档 |
| `install-bioinformatics-envs.sh` | 创建 fmt-tax、fmt-func Conda 环境 | 一次性维护工具，非应用启动；归档 |
| `check-bioinformatics-runtime.sh` | 检查生信二进制、GLPK 和参考库/模型路径 | 资源维护工具，非服务状态检查；归档 |
| `package-bioinformatics-runtime.sh` | conda-pack 环境、打包库/模型/匹配数据并计算校验 | 离线迁移工具，非日常部署；归档 |
| `restore-bioinformatics-runtime.sh` | 校验并解包迁移包、重定位环境、恢复资源 | 离线迁移工具，非日常部署；归档 |
| `legacy/activate-agent-runtime.sh.txt` | 针对当时预构建产物和配置的 agent 一次性迁移与回滚 | 历史文本，不是当前有效入口；归档 |
| `legacy/activate-knowledge-ui.sh.txt` | 旧知识 UI 构建切换与 API/Web 重启 | 历史文本，依赖旧 PID/构建约定；归档 |
| `legacy/activate-report-templates.sh.txt` | 旧报告模板 Web 构建切换与 API 重启 | 历史文本，依赖当时 staging；归档 |
| `legacy/activate-specialized-metabolism.sh.txt` | 特定样本功能回填后重启 API | 历史一次性数据操作，不是部署入口；归档 |
| `legacy/README.md` | 历史文本说明 | 随历史文件归档 |
| `README.md` | 旧部署说明 | 原件归档，改写为四入口说明 |

## Elasticsearch 根因与当前选择

失败启动日志确认配置端口已被占用。真实 sudo 只读检查确认：当前目录对应受管容器不存在；占用端口的已运行容器具有相同端口和配置指纹，但工作目录标签、samefile 及数据卷归属均不匹配。旧逻辑因此尝试创建当前目录的实例，在端口检查阶段失败，最终只上报通用的 `ELASTICSEARCH_START_FAILED`。

用户明确选择复用现有 Elasticsearch。项目 `.env` 已切换为外部依赖模式，继续使用已保存的应用凭据，切换前后认证健康检查均通过。原配置留有权限600的本地私有备份。未接管其他目录的容器，未更改容器标签、索引、密码或数据卷。

外部依赖模式下，应用启动及重启前检查认证连接；检查失败返回 `EXTERNAL_ELASTICSEARCH_UNAVAILABLE`。应用停止/重启只操作本项目进程。状态同时报告依赖 mode、认证健康和总体 ready。

## 备份与验证边界

旧文件完整保存在服务器项目根目录的 `deploy-backup/` 时间子目录，32个文件逐字节比对一致。整个目录由根 `.gitignore` 的 `/deploy-backup/` 忽略，不加入 Git；新克隆不含该本机备份。保留原始相对路径用于历史核查，不能直接在备份位置执行。

验证覆盖四个 Shell 入口从项目内外及含空格路径正确定位同一核心、失败退出码传播、外部依赖不可用时不先停应用、外部模式不操作 Docker、整体状态、NFS 应用身份访问及子进程永久降权。旧测试中针对已移除 Shell 架构和生信打包工具的用例随入口退役；替换为当前命令契约与外部依赖行为测试。

最终相关回归测试83项全部通过，0失败、0错误、0跳过。四入口及内部 Shell 语法检查、Python 编译、项目目录外的 `--help` 调用和 `git diff --check` 均通过。备份目录被 Git 忽略，已跟踪文件数为0。最新只读状态：API/Web停止，agent未启用，外部Elasticsearch运行、health为yellow；整体ready为false，等待用户手动启动应用。

依赖安装/迁移/历史样本回填脚本没有实际执行；本次不生成报告。实际服务启动、停止和重启由用户手动执行，自动验证不证明真实整项目启动已成功。
