# 当前活动系统与迁移记录

## 唯一活动 Web 系统

| 服务 | 目录 | 默认监听 | 用途 |
|---|---|---|---|
| workspace-web | `apps/workspace-web` | `0.0.0.0:18502` | 当前服务器 IP + 端口入口 |
| workspace-api | `apps/workspace-api` | `127.0.0.1:18503` | Next.js `/backend/*` 转发 |
| agent-daemon | `src/wgs_agent` | `127.0.0.1:7438` | 可选 JSON-RPC 后台 |
| elasticsearch | `scripts/manage_elasticsearch.py` / Docker | `127.0.0.1:9200` | 默认随项目启动的认证检索实例，可关闭自动托管 |

已停用并从活动源码删除：Streamlit 8501 服务、旧 FastAPI 8000 服务及其容器入口。

当前使用单服务器直连架构，已移除反向 SSH 隧道脚本。运行数据默认统一到项目的 `var/`，
全新初始化，不迁移旧样本、账号、报告或知识文献。配置与目录说明见
[单服务器架构](SINGLE_SERVER.md)。修改源码和初始化本地数据不会自动部署服务。
