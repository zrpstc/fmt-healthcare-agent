# LitKG 作为 FMT科研助手正式知识库

部署实例：`http://127.0.0.1:8080`，知识库 `main`，实际 ID 为 **26**。
2026-10-24 验证该知识库包含 47 篇文档、6533 条 Claim；这些计数随后续抽取更新。

## 活动检索链路

```text
FMT科研助手 / 循证整理 subagent
  -> search_knowledge_base(query, max_results)
  -> POST /knowledge-bases/26/ask
     {question, hops: 1, limit, generate: false}
  -> facts + citations + warnings + 实际 retrieval 模式
  -> FMT 项目自身模型整合最终回答
```

`generate=false` 固定在程序中，用户或模型无法通过工具参数开启 LitKG 的答案生成。
不使用上游 `answer` / `statements` 字段作为生成结论，只接收有原文引用的事实。
本次只接入已经运行的 LitKG，不重新抽取文献、不修改 LitKG 数据库或模型服务。

旧 Agent 工具从 `/claims?limit=1000&offset=0` 取首批记录并在本地匹配关键词，可能遗漏其他记录。
现由 LitKG 服务完成检索，Agent 工具不再扫描 `/claims`。知识库界面的分页浏览、图谱和
其他结构化工作流仍可使用各自的 `/claims` 接口，不要把通用 Claim 适配器的路径改为 `/ask`。

## 配置

```dotenv
WGS_CLAIM_API_URL=http://127.0.0.1:8080
WGS_CLAIM_API_KNOWLEDGE_BASE_ID=26
WGS_CLAIM_API_TIMEOUT=20
WGS_CLAIM_API_ASK_HOPS=1
WGS_CLAIM_API_LOCAL_FALLBACK=false
```

KB ID 必须从部署实例 `/knowledge-bases` 的真实列表选择，不自动猜测另一个库。
`hops` 支持 0..2；请求 limit 最多 30，现有前端 Agent 工具白名单上限为 20。
已有 `WGS_CLAIM_API_TOKEN` 在配置时作为 Authorization 发送，不写入结果或异常正文。

LitKG 是主知识源。默认接口失败会显式报错，不把失败当成无文献；只有主动设置
`WGS_CLAIM_API_LOCAL_FALLBACK=true` 才可用 SQLite/Markdown 降级，返回 `degraded` 及
`primary=false`，明确与 LitKG 证据区分。一次 `/ask` 空召回不会悄悄换库。
设置页中的历史 SQLite 路径只属于本地文件来源，不决定本工具的正式知识库。

## 证据契约

- 事实保留 `id`、`predicate`、所有 `participants`、`qualifiers`、`negated`、`speculative`。
- 引用保留 `citation ID`、`fact_id`、`claim_id`、文档/分块、标题、DOI、页码、章节和原文句。
- 每条事实通过 `citation_ids` 对应具体原文；没有对应引用的事实不作为回答依据。
- 引用句不被截断。超过约 17K 字符工具封装预算时，先省略补充上下文并标记
  `context_omitted`，仍超出预算则整组省略事实/引用并增加 `omitted_fact_count` 与告警。
- 不重复转发上游答案，也不按前缀截断证据 JSON。结果保留实际 `retrieval` 模式和告警。
- 旧 `search_claim_references` 报告调用保持返回引用列表，内部也使用 `/ask` 证据。

## 当前检索能力与边界

实测 LitKG 返回 `retrieval=text`。**不能据此宣称向量/语义检索已启用。** 本次不配置额外
embedding 服务；若日后 LitKG 自身启用语义检索，适配层按其实际返回模式透传。

当前英文文献索引中，中文问题“哪些肠道菌群与丁酸生成及肠道炎症有关？”未召回；英文
`Faecalibacterium prausnitzii butyrate inflammation` 可以返回原文事实。主/子 Agent 的
运行提示词要求优先英文科研术语，保留拉丁名，并在中文无结果后用英文/同义词改写。
这不是中文语义召回的保证；原始检索相关性、图邻居扩展和上游上下文预算仍影响覆盖。
返回有事实不代表它直接支持问题中的每个主张，回答必须标明证据缺口、条件和推测性。

## 验证与生效

新增 `tests/test_litkg_agent_retrieval.py` 覆盖固定 generate=false、禁止首批 Claim 扫描、
跨 KB 响应拒绝、错误响应、空召回、否定/推测和参与者保留、完整引用预算、兼容引用列表
及明确标记的降级来源。与既有 Agent、PubMed、报告引用和知识网关测试共 45 项通过。

真实工具验证：英文查询从 LitKG 收到 13 条事实，完整封装 10 条事实/10 条引用，
工具外层 JSON 15244 字符；其余条目明确标注省略。真实 Qwen 模型使用英文查询，
最终中文回答保留了 Fact/Citation ID、文档 131、页码 6 及推测性条件，没有把缺失的
丁酸证据补造成已证实结论。记录位于 `tmp/litkg-integration-20261024/`。

仅需重启后端 API，前端和 LitKG 无需重启：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
sudo bash deploy/restart-report-api.sh
```

激活前相关源码和 `.env` 备份放在 `tmp/litkg-integration-20261024/backup/`；
该目录权限为 700，不应发布包含运行配置的备份。回滚时恢复相关源码和 `.env`，再重启 API。
