# 完整知识库获取与知识使用

## 当前行为

应用默认 `WGS_KNOWLEDGE_ACQUISITION_SCOPE=full`。先获取整个知识库的实体、关系、claim 和完整事实，再由调用方决定如何检索、筛选、引用和展示。

- 获取层没有问题关键词、跳数、关系类型白名单或总条数上限。
- 关系获取显式包含 pending、negated、speculative；完整 facts/claims 保留原始证据和审核状态。关系接口中的 evidence_samples 是摘要，完整证据保存在 facts/claims 中。
- 分页大小只决定一次请求的数量；会持续翻页、去重、核对数量。持续入库时允许补扫；无法补齐时明确失败，不发布部分快照。
- 完整快照写入 `var/cache/knowledge_snapshots/`，原子替换。默认缓存 300 秒，可用 `WGS_KNOWLEDGE_SNAPSHOT_TTL` 调整或显式刷新。
- 导出分集合读取；源库可能在集合之间变化，不声称所有集合来自同一个数据库事务时间点。快照记录 acquisition time、各集合实际数量与 consistency。
- 搜索的返回条数和上下文预算、GraphRAG 跳数、报告章节白名单、每张图的边数，均属于使用层，不改变已获取的完整数据。
- 待审核内容始终保留在快照中。使用层默认仍排除待审核内容，可用独立配置 `WGS_KNOWLEDGE_USAGE_INCLUDE_PENDING=true` 改变这一规则。第三章原有功能关系和结果筛选规则继续单独适用。

`targeted` 模式仍可显式选择，用于兼容旧的服务端定向检索；它不是默认全库模式。

## 配置在哪里

默认权威来源：`/home/zhanghaiyang/fmt-healthcare-agent/.env`。

```dotenv
WGS_CLAIM_API_KNOWLEDGE_BASE_ID=30
WGS_CLAIM_API_URL=http://127.0.0.1:8080
WGS_KNOWLEDGE_ACQUISITION_SCOPE=full
```

统一解析器：`src/wgs_fmt_platform/knowledge/knowledge_settings.py` 的 `refresh_knowledge_settings()`。

默认 `WGS_KNOWLEDGE_CONFIG_SOURCE=project_env`，调用知识功能时重新读取项目 `.env` 中明确的知识配置，覆盖后端进程继承的旧值；不改认证字段的优先级。明确设置 `WGS_KNOWLEDGE_CONFIG_SOURCE=environment` 才采用进程环境优先的部署方式。

`LitkgRetrievalConfig.from_env()` 不再用硬编码知识库编号作为缺省值。未提供编号时明确报配置错误。

## 接口与工具

以下接口在 workspace API 后端提供：

| 接口 | 用途 |
|---|---|
| `GET /api/knowledge-base/config` | 当前 KB 编号、配置来源、获取模式和使用层 pending 配置 |
| `GET /api/knowledge-base/snapshot` | 完整获取或复用完整快照，返回数量、完整性与快照路径 |
| `GET /api/knowledge-base/snapshot?force_refresh=true` | 强制重新获取全库 |
| `GET /api/knowledge-base/export` | 下载完整 JSON 快照 |

新 agent 工具：`fetch_knowledge_base`，可选参数 `force_refresh`。返回完整快照位置和统计，避免把整个导出文件直接塞入模型的单条消息。普通知识搜索、原生 GraphRAG 和生产报告均已接入完整快照获取。

在 gpu02 本机验证：

```bash
curl -fsS http://127.0.0.1:18503/api/knowledge-base/config
curl -fsS http://127.0.0.1:18503/api/knowledge-base/snapshot
```

## 为什么重开项目仍是旧库

检查时存在两组端口：当前预览网页/后端是 18502/18503，标准启动配置是 8502/8503。18503 的旧后端是脱离 SSH 会话后继续运行的独立进程，启动环境指向 KB 25；磁盘 `.env` 已是 KB 30。

原有 Python `load_dotenv(..., override=False)` 不覆盖已有进程环境；原有 start.sh 遇到存活 PID 直接复用。关闭编辑器或网页，不等于停止这个预览后端。标准 PID 文件还属于 root，且不管理当前用户的 18503 预览进程。

本次已更新实际预览后端到 KB 30，并增加独立管理入口和 PID 文件 `var/run/workspace-api-preview.pid`，不与标准服务的 PID 文件混用：

```bash
/home/zhanghaiyang/fmt-healthcare-agent/.venv/bin/python /home/zhanghaiyang/fmt-healthcare-agent/deploy/manage-preview-api.py status
/home/zhanghaiyang/fmt-healthcare-agent/.venv/bin/python /home/zhanghaiyang/fmt-healthcare-agent/deploy/manage-preview-api.py restart
/home/zhanghaiyang/fmt-healthcare-agent/.venv/bin/python /home/zhanghaiyang/fmt-healthcare-agent/deploy/manage-preview-api.py stop
/home/zhanghaiyang/fmt-healthcare-agent/.venv/bin/python /home/zhanghaiyang/fmt-healthcare-agent/deploy/manage-preview-api.py start
```

标准 start.sh 也加入知识配置匹配检查，不再无条件复用配置过时且可由当前账户管理的 API 进程。

## 验证记录

2026-11-05，真实 API 已确认：KB 30、project_env、full、complete=true。一次运行快照包含 24,273 个实体、7,874 条关系、8,000 条 claim 和 8,000 条事实。源库持续入库，后续读数可能增加。

额外验证：报告获取函数即使收到使用 limit=1，仍先获得整个快照的全部 claim；GraphRAG 回归用例取得 45 条候选关系后，才按独立输出上限返回 1 条事实；上下文预算计入获取元信息且不切断引用。

相关测试：42 项通过，3 项报告测试失败。相同 3 项在修改前的代码副本中也失败：

- `test_graph_contains_only_relevant_actual_claims_and_valid_endpoints`
- `test_missing_results_and_title_only_references_do_not_create_edges`
- `test_malformed_service_payload_does_not_break_report`

原文件备份：`/home/zhanghaiyang/fmt-healthcare-agent/tmp/full-kb-change-20261105T020740/`。备份中是修改前的文件；新增文件如需回退应一并处理。
